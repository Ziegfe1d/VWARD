/*
 * vward-sentinel: VWARD's real-time watcher on the router.
 *
 * One small process instead of checks once a minute:
 *   - the kernel tells it at once when an interface goes up or down or loses its
 *     address (netlink), nothing is polled for that;
 *   - every SAMPLE_MS (2 s) it reads /proc: available memory, load, and the memory and
 *     CPU of VWARD's long-running programs (no process is started for that);
 *   - every DNS_EVERY seconds it sends one DNS query to the router's resolver itself and
 *     measures the answer;
 *   - every CHAIN_EVERY seconds (5) it asks AdGuard Home in the DNS chain (CHAIN=addr:port);
 *     CHAIN_MISS (3) misses in a row are the event «chain-fail» (again each minute while it
 *     lasts): AdGuard Home is taken out of the chain in seconds, not minutes;
 *   - it learns what is normal for this router (a moving average of every value) and
 *     reports a program that grows well past its own normal or past its limit.
 * Whatever it notices becomes an event: ACT EVENT ARGS... is started (fork and exec only
 * then), at most once per RATE seconds per event, never two at a time for one event.
 * What it saw is written to STATE_DIR (RAM) every STATE_MS (10 s) and an hourly line to HOURS_FILE.
 *
 * Configuration (key=value, one per line):
 *   STATE_DIR=/tmp/vward-sentinel      ACT=/opt/bin/vward-sentinel-act.sh
 *   HOURS_FILE=/opt/var/lib/vward/sentinel/hours.tsv
 *   SAMPLE_MS=2000   STATE_MS=10000   DNS=127.0.0.1:53   DNS_NAME=vward-probe.invalid   DNS_EVERY=30
 *   CHAIN=192.168.1.1:65053   CHAIN_EVERY=5   CHAIN_MISS=3
 *   MEM_LOW_KB=16384  BUSY_MEM_KB=24576
 *   WATCH=name:pidfile:limit_kb   (up to 16)
 *   IFACE=dev                     (up to 16; empty: every interface)
 *   PROC=/proc                    (tests)
 *
 * Usage: vward-sentinel CONFIG [--once]
 * Integer arithmetic only: the router's MIPS has no FPU.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/netlink.h>
#include <linux/rtnetlink.h>
#include <net/if.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define VERSION "2"
#define MAXW 16
#define MAXIF 16
#define MAXEV 48
#define MAXKIDS 4

struct watch {
    char name[32], pidfile[160];
    long limit_kb;
    long pid, rss_kb, rss_max_kb;
    long rss_base_x16;        /* moving average of RSS, x16 */
    long over, grow, down;    /* consecutive samples */
    long cpu_prev, cpu_x100;  /* process jiffies, CPU % x100 (moving average) */
    long downs, leaks;
};

struct ifstate { char name[IF_NAMESIZE]; int up; int known; };

struct ratekey { char key[64]; time_t last; pid_t running; };

static char conf_path[256];
static char state_dir[160] = "/tmp/vward-sentinel";
static char act[160] = "/opt/bin/vward-sentinel-act.sh";
static char hours_file[200] = "/opt/var/lib/vward/sentinel/hours.tsv";
static char proc_dir[160] = "/proc";
static char dns_name[128] = "vward-probe.invalid";
static struct sockaddr_in dns_addr, chain_addr;
static long chain_every = 5, chain_miss_need = 3;
static long sample_ms = 2000, state_ms = 10000, dns_every = 30, mem_low_kb = 16384, busy_mem_kb = 24576;
static struct watch w[MAXW];
static int nw;
static char ifaces[MAXIF][IF_NAMESIZE];
static int nif;
static struct ifstate ifs[MAXIF * 2];
static struct ratekey rk[MAXEV];

/* What was seen since the start. */
static time_t started;
static long samples, dns_ok, dns_fail, dns_ms_last = -1, dns_ms_x16 = -1, events, actions_ok, actions_fail, link_events;
static long mem_kb = -1, mem_min_kb = -1, mem_base_x16 = -1, load_x100, load_max_x100, cpus = 1;
static int busy, mem_low;
/* This hour. */
static long h_dns_ok, h_dns_fail, h_events, h_ok, h_fail, h_mem_min = -1, h_load_max, h_downs, h_leaks;
static time_t h_start;

static volatile sig_atomic_t stop, reload;

static void on_sig(int s) { if (s == SIGHUP) reload = 1; else stop = 1; }

static long mono_ms(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (long)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}

static int read_file(const char *path, char *buf, size_t size)
{
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    ssize_t n = read(fd, buf, size - 1);
    close(fd);
    if (n < 0) return -1;
    buf[n] = 0;
    return (int)n;
}

/* Write PATH through PATH.tmp and rename: a reader never sees half a file. */
static void write_atomic(const char *path, const char *data, size_t len)
{
    char tmp[300];
    snprintf(tmp, sizeof tmp, "%s.tmp", path);
    int fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (fd < 0) return;
    ssize_t n = write(fd, data, len);
    close(fd);
    if (n == (ssize_t)len) rename(tmp, path); else unlink(tmp);
}

static void mkdirs(const char *path)
{
    char p[256];
    snprintf(p, sizeof p, "%s", path);
    for (char *s = p + 1; *s; s++)
        if (*s == '/') { *s = 0; mkdir(p, 0755); *s = '/'; }
    mkdir(p, 0755);
}

static void log_line(const char *fmt, ...)
{
    char path[200], line[400], ts[32];
    time_t now = time(NULL);
    struct tm tm;
    localtime_r(&now, &tm);
    strftime(ts, sizeof ts, "%Y-%m-%d %H:%M:%S", &tm);
    va_list ap;
    va_start(ap, fmt);
    int n = snprintf(line, sizeof line, "%s|", ts);
    n += vsnprintf(line + n, sizeof line - n - 1, fmt, ap);
    va_end(ap);
    if (n > (int)sizeof line - 2) n = sizeof line - 2;
    line[n++] = '\n';
    snprintf(path, sizeof path, "%s/events.log", state_dir);
    int fd = open(path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
    if (fd >= 0) { ssize_t r = write(fd, line, n); (void)r; close(fd); }
}

/* ------------------------------------------------------------ configuration */

/* "a.b.c.d[:port]" into A (family 0 when it is not an address). */
static void parse_addr(const char *v, struct sockaddr_in *a)
{
    char host[64];
    snprintf(host, sizeof host, "%s", v);
    char *c = strchr(host, ':');
    int port = 53;
    if (c) { *c = 0; port = atoi(c + 1); }
    memset(a, 0, sizeof *a);
    a->sin_family = AF_INET;
    a->sin_port = htons(port);
    if (inet_pton(AF_INET, host, &a->sin_addr) != 1) a->sin_family = 0;
}

static void config_load(void)
{
    char buf[8192];
    nw = 0;
    nif = 0;
    chain_addr.sin_family = 0;
    if (read_file(conf_path, buf, sizeof buf) < 0) return;
    for (char *line = strtok(buf, "\n"); line; line = strtok(NULL, "\n")) {
        char *eq = strchr(line, '=');
        if (!eq || line[0] == '#') continue;
        *eq = 0;
        const char *k = line, *v = eq + 1;
        if (!strcmp(k, "STATE_DIR")) snprintf(state_dir, sizeof state_dir, "%s", v);
        else if (!strcmp(k, "ACT")) snprintf(act, sizeof act, "%s", v);
        else if (!strcmp(k, "HOURS_FILE")) snprintf(hours_file, sizeof hours_file, "%s", v);
        else if (!strcmp(k, "PROC")) snprintf(proc_dir, sizeof proc_dir, "%s", v);
        else if (!strcmp(k, "DNS_NAME")) snprintf(dns_name, sizeof dns_name, "%s", v);
        else if (!strcmp(k, "SAMPLE_MS")) sample_ms = atol(v) >= 200 ? atol(v) : 2000;
        else if (!strcmp(k, "STATE_MS")) state_ms = atol(v) >= 200 ? atol(v) : 10000;
        else if (!strcmp(k, "DNS_EVERY")) dns_every = atol(v);
        else if (!strcmp(k, "MEM_LOW_KB")) mem_low_kb = atol(v);
        else if (!strcmp(k, "BUSY_MEM_KB")) busy_mem_kb = atol(v);
        else if (!strcmp(k, "DNS")) parse_addr(v, &dns_addr);
        else if (!strcmp(k, "CHAIN")) parse_addr(v, &chain_addr);
        else if (!strcmp(k, "CHAIN_EVERY")) chain_every = atol(v) >= 1 ? atol(v) : 5;
        else if (!strcmp(k, "CHAIN_MISS")) chain_miss_need = atol(v) >= 1 ? atol(v) : 3;
        else if (!strcmp(k, "WATCH") && nw < MAXW) {
            char name[32], pf[160];
            long lim = 0;
            if (sscanf(v, "%31[^:]:%159[^:]:%ld", name, pf, &lim) == 3) {
                memset(&w[nw], 0, sizeof w[nw]);
                snprintf(w[nw].name, sizeof w[nw].name, "%s", name);
                snprintf(w[nw].pidfile, sizeof w[nw].pidfile, "%s", pf);
                w[nw].limit_kb = lim;
                w[nw].rss_base_x16 = -1;
                w[nw].cpu_prev = -1;
                nw++;
            }
        } else if (!strcmp(k, "IFACE") && nif < MAXIF && *v) {
            snprintf(ifaces[nif++], IF_NAMESIZE, "%s", v);
        }
    }
}

/* ------------------------------------------------------------ actions */

static struct ratekey *rate_get(const char *key)
{
    struct ratekey *free_slot = NULL, *oldest = &rk[0];
    for (int i = 0; i < MAXEV; i++) {
        if (!strcmp(rk[i].key, key)) return &rk[i];
        if (!rk[i].key[0] && !free_slot) free_slot = &rk[i];
        if (rk[i].last < oldest->last && !rk[i].running) oldest = &rk[i];
    }
    struct ratekey *r = free_slot ? free_slot : oldest;
    memset(r, 0, sizeof *r);
    snprintf(r->key, sizeof r->key, "%s", key);
    return r;
}

static int running_kids(void)
{
    int n = 0;
    for (int i = 0; i < MAXEV; i++) if (rk[i].running) n++;
    return n;
}

/* event KEY RATE ARGV...: start ACT with ARGV unless KEY ran within RATE seconds or runs. */
static void event(const char *key, long rate, const char *a1, const char *a2, const char *a3)
{
    struct ratekey *r = rate_get(key);
    time_t now = time(NULL);
    events++; h_events++;
    if (r->running || (r->last && now - r->last < rate) || running_kids() >= MAXKIDS) return;
    r->last = now;
    log_line("EVENT|%s|%s|%s", a1, a2 ? a2 : "", a3 ? a3 : "");
    if (access(act, X_OK) != 0) return;
    pid_t p = fork();
    if (p == 0) {
        int fd = open("/dev/null", O_RDWR);
        if (fd >= 0) { dup2(fd, 0); dup2(fd, 1); dup2(fd, 2); if (fd > 2) close(fd); }
        const char *argv[] = { act, a1, a2, a3, NULL };
        execv(act, (char *const *)argv);
        _exit(127);
    }
    if (p > 0) r->running = p;
}

static void reap(void)
{
    int st;
    pid_t p;
    while ((p = waitpid(-1, &st, WNOHANG)) > 0) {
        for (int i = 0; i < MAXEV; i++) {
            if (rk[i].running != p) continue;
            rk[i].running = 0;
            int ok = WIFEXITED(st) && WEXITSTATUS(st) == 0;
            if (ok) { actions_ok++; h_ok++; } else { actions_fail++; h_fail++; }
            log_line("ACTION|%s|%s", rk[i].key, ok ? "ok" : "fail");
        }
    }
}

/* ------------------------------------------------------------ /proc */

static long meminfo_kb(const char *field)
{
    char path[200], buf[4096];
    snprintf(path, sizeof path, "%s/meminfo", proc_dir);
    if (read_file(path, buf, sizeof buf) < 0) return -1;
    char *p = strstr(buf, field);
    return p ? atol(p + strlen(field)) : -1;
}

static long count_cpus(void)
{
    char path[200], buf[16384];
    snprintf(path, sizeof path, "%s/cpuinfo", proc_dir);
    if (read_file(path, buf, sizeof buf) < 0) return 1;
    long n = 0;
    for (char *p = buf; (p = strstr(p, "processor")); p += 9)
        if (p == buf || p[-1] == '\n') n++;
    return n > 0 ? n : 1;
}

static long total_jiffies(void)
{
    char path[200], buf[512];
    snprintf(path, sizeof path, "%s/stat", proc_dir);
    if (read_file(path, buf, sizeof buf) < 0 || strncmp(buf, "cpu ", 4)) return -1;
    long sum = 0;
    char *p = buf + 4;
    for (int i = 0; i < 8; i++) sum += strtol(p, &p, 10);
    return sum;
}

static long pid_from(const char *pidfile)
{
    char buf[32];
    if (read_file(pidfile, buf, sizeof buf) < 0) return 0;
    long pid = atol(buf);
    return pid > 1 ? pid : 0;
}

/* RSS (kB) and CPU jiffies of PID; 0 if it is gone or a zombie. */
static int pid_sample(long pid, long *rss_kb, long *jiffies)
{
    char path[200], buf[1024];
    snprintf(path, sizeof path, "%s/%ld/stat", proc_dir, pid);
    if (read_file(path, buf, sizeof buf) < 0) return 0;
    char *p = strrchr(buf, ')');
    if (!p || p[1] != ' ' || p[2] == 'Z' || p[2] == 'X') return 0;
    /* fields after ") ": state(3) ... utime(14) stime(15) */
    p += 2;
    for (int f = 3; f < 14 && p; f++) { p = strchr(p, ' '); if (p) p++; }
    if (!p) return 0;
    long ut = strtol(p, &p, 10), stime = strtol(p, &p, 10);
    *jiffies = ut + stime;
    snprintf(path, sizeof path, "%s/%ld/status", proc_dir, pid);
    *rss_kb = 0;
    if (read_file(path, buf, sizeof buf) >= 0) {
        char *r = strstr(buf, "VmRSS:");
        if (r) *rss_kb = atol(r + 6);
    }
    return 1;
}

static void sample(long dt_jiffies)
{
    char path[200], buf[128];
    samples++;

    mem_kb = meminfo_kb("MemAvailable:");
    if (mem_kb >= 0) {
        if (mem_min_kb < 0 || mem_kb < mem_min_kb) mem_min_kb = mem_kb;
        if (h_mem_min < 0 || mem_kb < h_mem_min) h_mem_min = mem_kb;
        mem_base_x16 = mem_base_x16 < 0 ? mem_kb * 16 : mem_base_x16 + (mem_kb * 16 - mem_base_x16) / 64;
        if (mem_kb < mem_low_kb && !mem_low) { mem_low = 1; event("mem-low", 600, "mem-low", NULL, NULL); log_line("MEM_LOW|%ld", mem_kb); }
        else if (mem_kb >= mem_low_kb + 4096 && mem_low) { mem_low = 0; log_line("MEM_OK|%ld", mem_kb); }
    }
    snprintf(path, sizeof path, "%s/loadavg", proc_dir);
    if (read_file(path, buf, sizeof buf) > 0) {
        long a = atol(buf), b = 0;
        char *dot = strchr(buf, '.');
        if (dot) b = atol(dot + 1);
        load_x100 = a * 100 + (b > 99 ? b / 10 : b);
        if (load_x100 > load_max_x100) load_max_x100 = load_x100;
        if (load_x100 > h_load_max) h_load_max = load_x100;
    }
    /* The busy flag: optional work of VWARD waits while it exists (vward_busy). */
    int now_busy = load_x100 >= cpus * 100 || (mem_kb >= 0 && mem_kb < busy_mem_kb);
    if (now_busy != busy) {
        busy = now_busy;
        snprintf(path, sizeof path, "%s/busy", state_dir);
        if (busy) write_atomic(path, "1\n", 2); else unlink(path);
    }

    for (int i = 0; i < nw; i++) {
        struct watch *x = &w[i];
        long pid = pid_from(x->pidfile), rss = 0, jf = 0;
        char key[64];
        if (!pid || !pid_sample(pid, &rss, &jf)) {
            x->rss_kb = 0;
            x->cpu_prev = -1;
            if (x->pid || x->down) x->down++;
            /* Gone for 3 samples (6 s): its starter is asked now, not in a minute. */
            snprintf(key, sizeof key, "down-%.40s", x->name);
            if (x->down == 3) { x->downs++; h_downs++; event(key, 60, "down", x->name, NULL); }
            x->pid = 0;
            continue;
        }
        if (pid != x->pid) { x->cpu_prev = -1; x->over = x->grow = 0; }
        x->pid = pid;
        x->down = 0;
        x->rss_kb = rss;
        if (rss > x->rss_max_kb) x->rss_max_kb = rss;
        /* Its own normal: a slow moving average (a few minutes). */
        x->rss_base_x16 = x->rss_base_x16 < 0 ? rss * 16 : x->rss_base_x16 + (rss * 16 - x->rss_base_x16) / 128;
        if (x->cpu_prev >= 0 && dt_jiffies > 0) {
            long pct = (jf - x->cpu_prev) * 10000 / dt_jiffies; /* % x100 of all CPUs */
            x->cpu_x100 = x->cpu_x100 + (pct - x->cpu_x100) / 8;
        }
        x->cpu_prev = jf;
        char rs[24];
        snprintf(rs, sizeof rs, "%ld", rss);
        /* Above its limit 3 samples in a row: a leak, restarted by ACT. */
        if (x->limit_kb > 0 && rss > x->limit_kb) {
            snprintf(key, sizeof key, "leak-%.40s", x->name);
            if (++x->over == 3) { x->leaks++; h_leaks++; event(key, 300, "leak", x->name, rs); }
        } else x->over = 0;
        /* Twice its own normal and 8 MB over it for a minute: growing, reported once. */
        long base = x->rss_base_x16 / 16;
        if (samples > 60 && rss > base * 2 && rss > base + 8192) {
            snprintf(key, sizeof key, "grow-%.40s", x->name);
            if (++x->grow == 30) event(key, 3600, "grow", x->name, rs);
        } else x->grow = 0;
    }
}

/* ------------------------------------------------------------ netlink */

static int nl_open(void)
{
    int fd = socket(AF_NETLINK, SOCK_RAW | SOCK_CLOEXEC | SOCK_NONBLOCK, NETLINK_ROUTE);
    if (fd < 0) return -1;
    struct sockaddr_nl sa = { .nl_family = AF_NETLINK, .nl_groups = RTMGRP_LINK | RTMGRP_IPV4_IFADDR };
    if (bind(fd, (struct sockaddr *)&sa, sizeof sa) < 0) { close(fd); return -1; }
    return fd;
}

static int if_wanted(const char *name)
{
    if (!nif) return 1;
    for (int i = 0; i < nif; i++) if (!strcmp(ifaces[i], name)) return 1;
    return 0;
}

static struct ifstate *if_get(const char *name)
{
    for (unsigned i = 0; i < sizeof ifs / sizeof ifs[0]; i++)
        if (ifs[i].known && !strcmp(ifs[i].name, name)) return &ifs[i];
    for (unsigned i = 0; i < sizeof ifs / sizeof ifs[0]; i++)
        if (!ifs[i].known) { ifs[i].known = 1; snprintf(ifs[i].name, sizeof ifs[i].name, "%s", name); ifs[i].up = -1; return &ifs[i]; }
    return NULL;
}

static void nl_read(int fd)
{
    char buf[8192];
    for (;;) {
        ssize_t n = recv(fd, buf, sizeof buf, 0);
        if (n <= 0) return;
        for (struct nlmsghdr *h = (struct nlmsghdr *)buf; NLMSG_OK(h, (size_t)n); h = NLMSG_NEXT(h, n)) {
            if (h->nlmsg_type == RTM_NEWLINK || h->nlmsg_type == RTM_DELLINK) {
                struct ifinfomsg *ifi = NLMSG_DATA(h);
                const char *name = NULL;
                int len = IFLA_PAYLOAD(h);
                for (struct rtattr *a = IFLA_RTA(ifi); RTA_OK(a, len); a = RTA_NEXT(a, len))
                    if (a->rta_type == IFLA_IFNAME) name = RTA_DATA(a);
                if (!name || !if_wanted(name)) continue;
                int up = h->nlmsg_type == RTM_NEWLINK && (ifi->ifi_flags & IFF_UP) && (ifi->ifi_flags & IFF_RUNNING);
                struct ifstate *s = if_get(name);
                if (!s || s->up == up) continue;
                int first = s->up < 0;
                s->up = up;
                if (first && up) continue;
                link_events++;
                char key[64];
                /* Down and up are separate events: one never hides the other. */
                snprintf(key, sizeof key, "link-%.16s-%s", name, up ? "up" : "down");
                log_line("LINK|%s|%s", name, up ? "up" : "down");
                event(key, 5, "link", name, up ? "up" : "down");
            } else if (h->nlmsg_type == RTM_DELADDR) {
                struct ifaddrmsg *ifa = NLMSG_DATA(h);
                char name[IF_NAMESIZE];
                if (!if_indextoname(ifa->ifa_index, name) || !if_wanted(name)) continue;
                link_events++;
                char key[64];
                snprintf(key, sizeof key, "addr-%s", name);
                log_line("ADDR|%s|lost", name);
                event(key, 5, "addr", name, "lost");
            }
        }
    }
}

/* ------------------------------------------------------------ DNS */

static unsigned short dns_id;
static long dns_sent_ms = -1, next_dns;
static int dns_retry;

/* The query for DNS_NAME (type A) with ID into Q; its length. */
static int build_query(unsigned char *q, unsigned short id)
{
    int n = 12;
    memset(q, 0, 12);
    q[0] = id >> 8; q[1] = id & 255; q[2] = 1; /* RD */ q[5] = 1; /* QDCOUNT */
    const char *s = dns_name;
    while (*s && n < 280) {
        const char *dot = strchr(s, '.');
        int l = dot ? (int)(dot - s) : (int)strlen(s);
        if (l <= 0 || l > 63) break;
        q[n++] = l;
        memcpy(q + n, s, l);
        n += l;
        s += l + (dot ? 1 : 0);
    }
    q[n++] = 0;
    q[n++] = 0; q[n++] = 1; /* A */
    q[n++] = 0; q[n++] = 1; /* IN */
    return n;
}

static void dns_send(int fd)
{
    unsigned char q[300];
    dns_id = (unsigned short)(mono_ms() ^ getpid());
    int n = build_query(q, dns_id);
    if (sendto(fd, q, n, 0, (struct sockaddr *)&dns_addr, sizeof dns_addr) == n) dns_sent_ms = mono_ms();
    else dns_sent_ms = mono_ms() - 5000; /* counts as no answer */
}

static void dns_result(int ok, long ms)
{
    dns_sent_ms = -1;
    /* The next query: 3 s after a first miss, DNS_EVERY otherwise. */
    next_dns = mono_ms() + (ok || dns_retry ? dns_every * 1000 : 3000);
    if (ok) {
        dns_ok++; h_dns_ok++;
        dns_ms_last = ms;
        dns_ms_x16 = dns_ms_x16 < 0 ? ms * 16 : dns_ms_x16 + (ms * 16 - dns_ms_x16) / 16;
        dns_retry = 0;
        return;
    }
    /* One miss is asked again in 3 s; two in a row are an event. */
    if (!dns_retry) { dns_retry = 1; return; }
    dns_fail++; h_dns_fail++;
    dns_retry = 0;
    event("dns", 120, "dns-fail", NULL, NULL);
}

static void dns_read(int fd)
{
    unsigned char r[512];
    ssize_t n;
    while ((n = recv(fd, r, sizeof r, 0)) > 0) {
        if (n >= 12 && dns_sent_ms >= 0 && ((r[0] << 8) | r[1]) == dns_id && (r[2] & 0x80)) {
            int rcode = r[3] & 15;
            /* NOERROR or NXDOMAIN: the resolver answers. SERVFAIL, REFUSED: it does not. */
            dns_result(rcode == 0 || rcode == 3, mono_ms() - dns_sent_ms);
        }
    }
}

/* AdGuard Home in the chain: a query every CHAIN_EVERY s, 2 s to answer. */
static unsigned short chain_id;
static long chain_sent_ms = -1, next_chain, chain_miss, chain_ok, chain_fails;

static void chain_send(int fd)
{
    unsigned char q[300];
    chain_id = (unsigned short)((mono_ms() ^ getpid()) + 7919);
    int n = build_query(q, chain_id);
    if (sendto(fd, q, n, 0, (struct sockaddr *)&chain_addr, sizeof chain_addr) == n) chain_sent_ms = mono_ms();
    else chain_sent_ms = mono_ms() - 5000;
}

static void chain_result(int ok)
{
    chain_sent_ms = -1;
    next_chain = mono_ms() + chain_every * 1000;
    if (ok) { chain_ok++; chain_miss = 0; return; }
    chain_miss++;
    /* CHAIN_MISS in a row, then once a minute while it lasts (the event's own rate). */
    if (chain_miss >= chain_miss_need) { chain_fails++; event("chain", 60, "chain-fail", NULL, NULL); }
}

static void chain_read(int fd)
{
    unsigned char r[512];
    ssize_t n;
    while ((n = recv(fd, r, sizeof r, 0)) > 0)
        if (n >= 12 && chain_sent_ms >= 0 && ((r[0] << 8) | r[1]) == chain_id && (r[2] & 0x80))
            chain_result((r[3] & 15) == 0 || (r[3] & 15) == 3);
}

/* ------------------------------------------------------------ state */

static void state_write(void)
{
    char buf[6144], path[200];
    int n = 0;
    time_t now = time(NULL);
#define P(...) do { if (n < (int)sizeof buf - 200) n += snprintf(buf + n, sizeof buf - n, __VA_ARGS__); } while (0)
    P("version=%s\nstarted=%ld\nnow=%ld\nsamples=%ld\ncpus=%ld\n", VERSION, (long)started, (long)now, samples, cpus);
    P("mem_kb=%ld\nmem_min_kb=%ld\nmem_base_kb=%ld\nload_x100=%ld\nload_max_x100=%ld\nbusy=%d\nmem_low=%d\n",
      mem_kb, mem_min_kb, mem_base_x16 < 0 ? -1 : mem_base_x16 / 16, load_x100, load_max_x100, busy, mem_low);
    P("dns_ok=%ld\ndns_fail=%ld\ndns_ms=%ld\ndns_ms_avg=%ld\n", dns_ok, dns_fail, dns_ms_last, dns_ms_x16 < 0 ? -1 : dns_ms_x16 / 16);
    if (chain_addr.sin_family) P("chain_ok=%ld\nchain_fail=%ld\nchain_miss=%ld\n", chain_ok, chain_fails, chain_miss);
    P("events=%ld\nlink_events=%ld\nactions_ok=%ld\nactions_fail=%ld\n", events, link_events, actions_ok, actions_fail);
    for (int i = 0; i < nw; i++)
        P("watch=%s|%ld|%ld|%ld|%ld|%ld|%ld|%ld|%ld\n", w[i].name, w[i].pid, w[i].rss_kb,
          w[i].rss_base_x16 < 0 ? -1 : w[i].rss_base_x16 / 16, w[i].rss_max_kb, w[i].limit_kb, w[i].cpu_x100, w[i].downs, w[i].leaks);
#undef P
    snprintf(path, sizeof path, "%s/state", state_dir);
    write_atomic(path, buf, n);
}

/* One line an hour on the USB stick (7 days kept): what the Panel's «Стабильность» shows. */
static void hour_write(time_t now)
{
    char dir[200], line[256], buf[65536];
    snprintf(dir, sizeof dir, "%s", hours_file);
    char *slash = strrchr(dir, '/');
    if (slash) { *slash = 0; mkdirs(dir); }
    int ln = snprintf(line, sizeof line, "%ld\t%ld\t%ld\t%ld\t%ld\t%ld\t%ld\t%ld\t%ld\t%ld\n", (long)h_start,
                      h_dns_ok, h_dns_fail, h_events, h_ok, h_fail, h_mem_min, h_load_max, h_downs, h_leaks);
    int n = read_file(hours_file, buf, sizeof buf - sizeof line);
    if (n < 0) n = 0;
    /* keep the last 167 lines */
    int lines = 0;
    for (int i = 0; i < n; i++) if (buf[i] == '\n') lines++;
    char *start = buf;
    while (lines > 167) { char *nl = strchr(start, '\n'); if (!nl) break; start = nl + 1; lines--; }
    int keep = n - (int)(start - buf);
    memmove(buf, start, keep);
    memcpy(buf + keep, line, ln);
    write_atomic(hours_file, buf, keep + ln);
    h_dns_ok = h_dns_fail = h_events = h_ok = h_fail = h_downs = h_leaks = 0;
    h_mem_min = -1;
    h_load_max = 0;
    h_start = now;
}

/* ------------------------------------------------------------ main */

int main(int argc, char **argv)
{
    if (argc < 2 || !strcmp(argv[1], "--version")) { puts("vward-sentinel " VERSION); return argc < 2; }
    snprintf(conf_path, sizeof conf_path, "%s", argv[1]);
    int once = argc > 2 && !strcmp(argv[2], "--once");
    config_load();
    mkdirs(state_dir);
    signal(SIGTERM, on_sig);
    signal(SIGINT, on_sig);
    signal(SIGHUP, on_sig);
    signal(SIGPIPE, SIG_IGN);
    started = time(NULL);
    h_start = started;
    cpus = count_cpus();

    int nl = once ? -1 : nl_open();
    int dfd = -1;
    if (dns_addr.sin_family && dns_every > 0) dfd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    int cfd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);

    long next_sample = mono_ms(), next_state = 0;
    next_dns = mono_ms() + 1000;
    next_chain = mono_ms() + 2000;
    long jiffies_prev = total_jiffies();
    log_line("START|%s|watch=%d|ifaces=%d|netlink=%s", VERSION, nw, nif, nl >= 0 ? "yes" : "no");

    while (!stop) {
        if (reload) { reload = 0; config_load(); log_line("RELOAD|watch=%d", nw); }
        long now = mono_ms();
        if (now >= next_sample) {
            long j = total_jiffies();
            sample(j >= 0 && jiffies_prev >= 0 ? j - jiffies_prev : 0);
            jiffies_prev = j;
            next_sample = now + sample_ms;
        }
        if (dfd >= 0) {
            if (dns_sent_ms >= 0 && now - dns_sent_ms >= 2000) dns_result(0, 0);
            if (dns_sent_ms < 0 && now >= next_dns) dns_send(dfd);
        }
        /* CHAIN can come and go with a reload (AdGuard Home switched on or off). */
        int chain_on = cfd >= 0 && chain_addr.sin_family;
        if (chain_on) {
            if (chain_sent_ms >= 0 && now - chain_sent_ms >= 2000) chain_result(0);
            if (chain_sent_ms < 0 && now >= next_chain) chain_send(cfd);
        }
        reap();
        if (now >= next_state) {
            state_write();
            next_state = now + state_ms;
            time_t t = time(NULL);
            if (t - h_start >= 3600) hour_write(t);
        }
        if (once) break;

        struct pollfd pf[3];
        int np = 0;
        if (nl >= 0) { pf[np].fd = nl; pf[np].events = POLLIN; np++; }
        if (dfd >= 0) { pf[np].fd = dfd; pf[np].events = POLLIN; np++; }
        if (chain_on) { pf[np].fd = cfd; pf[np].events = POLLIN; np++; }
        long t = mono_ms(), wait = next_sample - t;
        if (dfd >= 0 && dns_sent_ms >= 0 && dns_sent_ms + 2000 - t < wait) wait = dns_sent_ms + 2000 - t;
        if (dfd >= 0 && dns_sent_ms < 0 && next_dns - t < wait) wait = next_dns - t;
        if (chain_on && chain_sent_ms >= 0 && chain_sent_ms + 2000 - t < wait) wait = chain_sent_ms + 2000 - t;
        if (chain_on && chain_sent_ms < 0 && next_chain - t < wait) wait = next_chain - t;
        if (wait < 10) wait = 10;
        if (poll(pf, np, (int)wait) > 0) {
            for (int i = 0; i < np; i++) {
                if (!(pf[i].revents & POLLIN)) continue;
                if (pf[i].fd == nl) nl_read(nl); else if (pf[i].fd == dfd) dns_read(dfd); else chain_read(cfd);
            }
        }
    }
    state_write();
    log_line("STOP");
    return 0;
}
