/*
 * vward-dnscap: the DNS queries of the LAN, for VWARD's route engine, without tcpdump.
 *
 * Entware's tcpdump depends on libpcap; libpcap 1.10.6 for MIPS died at every start
 * (SIGBUS/SIGSEGV), and the route engine learned no domain while it did.  This program
 * needs no library: a packet socket on the LAN device, a kernel filter (BPF) that lets
 * through only IPv4 packets to the router's DNS port 53 (UDP and TCP), and the question
 * of each query printed the way tcpdump prints it, which the engine reads:
 *
 *     q A? example.com.
 *     q AAAA? example.com.
 *     q HTTPS? example.com.
 *
 * Only queries from SUBNET to DNS count, not the router's own (src DNS).  Other query
 * types, answers, and names with characters a domain never has are skipped.
 *
 * Usage: vward-dnscap IFACE SUBNET DNS     (IFACE "any": every device)
 *        vward-dnscap --stdin SUBNET DNS   (tests: packets from stdin, 2-byte length each)
 *        vward-dnscap --version
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <linux/filter.h>
#include <linux/if_ether.h>
#include <linux/if_packet.h>
#include <net/if.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#define VERSION "1"

static unsigned int net_addr, net_mask, dns_addr; /* host byte order */

static int parse_ip(const char *s, unsigned int *out)
{
    struct in_addr a;
    if (inet_pton(AF_INET, s, &a) != 1) return -1;
    *out = ntohl(a.s_addr);
    return 0;
}

static int parse_subnet(const char *s)
{
    char ip[32];
    const char *slash = strchr(s, '/');
    long bits = 32;
    size_t n = slash ? (size_t)(slash - s) : strlen(s);
    if (n == 0 || n >= sizeof ip) return -1;
    memcpy(ip, s, n);
    ip[n] = 0;
    if (slash) {
        char *end;
        bits = strtol(slash + 1, &end, 10);
        if (*end || end == slash + 1 || bits < 0 || bits > 32) return -1;
    }
    if (parse_ip(ip, &net_addr)) return -1;
    net_mask = bits ? 0xffffffffu << (32 - bits) : 0;
    net_addr &= net_mask;
    return 0;
}

static unsigned int be16(const unsigned char *p) { return (unsigned int)p[0] << 8 | p[1]; }
static unsigned int be32(const unsigned char *p) { return (unsigned int)p[0] << 24 | (unsigned int)p[1] << 16 | (unsigned int)p[2] << 8 | p[3]; }

/* One line per query; a reader that went away ends the program. */
static void out(const char *type, const char *name)
{
    char line[300];
    int n = snprintf(line, sizeof line, "q %s? %s.\n", type, name);
    if (n <= 0 || (size_t)n >= sizeof line) return;
    if (write(1, line, (size_t)n) != n) exit(0);
}

static void dns_question(const unsigned char *m, size_t len)
{
    char name[256];
    size_t at = 12, w = 0;
    if (len < 17) return;
    if (m[2] & 0x80) return;                  /* an answer */
    if ((m[2] & 0x78) != 0) return;           /* not a standard query */
    if (be16(m + 4) < 1) return;              /* no question */
    for (;;) {
        unsigned int l;
        if (at >= len) return;
        l = m[at++];
        if (l == 0) break;
        if (l > 63 || at + l > len) return;   /* compression or broken: not in a question */
        if (w + l + 1 >= sizeof name) return;
        if (w) name[w++] = '.';
        for (unsigned int i = 0; i < l; i++) {
            unsigned char c = m[at + i];
            if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-' || c == '_'))
                return;
            name[w++] = (char)c;
        }
        at += l;
    }
    if (w == 0 || at + 4 > len) return;
    name[w] = 0;
    switch (be16(m + at)) {
        case 1: out("A", name); break;
        case 28: out("AAAA", name); break;
        case 65: out("HTTPS", name); break;
        default: break;
    }
}

static void packet(const unsigned char *p, size_t len)
{
    size_t ihl;
    unsigned int src, dst, proto;
    if (len < 20 || (p[0] >> 4) != 4) return;
    ihl = (size_t)(p[0] & 15) * 4;
    if (ihl < 20 || len < ihl) return;
    if (be16(p + 2) < len) len = be16(p + 2);  /* Ethernet padding */
    if (len < ihl) return;
    if (be16(p + 6) & 0x1fff) return;          /* a later fragment */
    src = be32(p + 12);
    dst = be32(p + 16);
    if (dst != dns_addr || src == dns_addr || (src & net_mask) != net_addr) return;
    proto = p[9];
    p += ihl;
    len -= ihl;
    if (proto == 17) {
        if (len < 8 || be16(p + 2) != 53) return;
        dns_question(p + 8, len - 8);
    } else if (proto == 6) {
        size_t off;
        if (len < 20 || be16(p + 2) != 53) return;
        off = (size_t)(p[12] >> 4) * 4;
        if (off < 20 || len < off + 2 + 12) return;
        dns_question(p + off + 2, len - off - 2); /* a segment that starts a message */
    }
}

static int run_stdin(void)
{
    unsigned char hdr[2], buf[65536];
    for (;;) {
        size_t n, got = 0;
        if (fread(hdr, 1, 2, stdin) != 2) return 0;
        n = be16(hdr);
        if (n) got = fread(buf, 1, n, stdin);
        if (got != n) return 0;
        packet(buf, n);
    }
}

static int run_live(const char *ifname)
{
    struct sock_filter code[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, 16),             /* 0 ip dst */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 0, 9),       /* 1 == DNS (set below) */
        BPF_STMT(BPF_LD | BPF_H | BPF_ABS, 6),              /* 2 fragment offset */
        BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, 0x1fff, 7, 0), /* 3 */
        BPF_STMT(BPF_LD | BPF_B | BPF_ABS, 9),              /* 4 protocol */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 17, 1, 0),      /* 5 UDP */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 6, 0, 4),       /* 6 TCP */
        BPF_STMT(BPF_LDX | BPF_B | BPF_MSH, 0),             /* 7 x = header length */
        BPF_STMT(BPF_LD | BPF_H | BPF_IND, 2),              /* 8 destination port */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 53, 0, 1),      /* 9 */
        BPF_STMT(BPF_RET | BPF_K, 2048),                    /* 10 keep */
        BPF_STMT(BPF_RET | BPF_K, 0),                       /* 11 drop */
    };
    struct sock_fprog prog = { sizeof code / sizeof code[0], code };
    struct sockaddr_ll sll;
    unsigned char buf[2048];
    int rcv = 262144;
    int fd = socket(AF_PACKET, SOCK_DGRAM | SOCK_CLOEXEC, htons(ETH_P_IP));
    if (fd < 0) { fprintf(stderr, "vward-dnscap: socket: %s\n", strerror(errno)); return 2; }
    code[1].k = dns_addr;
    if (setsockopt(fd, SOL_SOCKET, SO_ATTACH_FILTER, &prog, sizeof prog) < 0) {
        fprintf(stderr, "vward-dnscap: filter: %s\n", strerror(errno));
        return 2;
    }
    setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &rcv, sizeof rcv);
    memset(&sll, 0, sizeof sll);
    sll.sll_family = AF_PACKET;
    sll.sll_protocol = htons(ETH_P_IP);
    if (strcmp(ifname, "any") != 0) {
        sll.sll_ifindex = (int)if_nametoindex(ifname);
        if (sll.sll_ifindex == 0) { fprintf(stderr, "vward-dnscap: no device %s\n", ifname); return 2; }
    }
    if (bind(fd, (struct sockaddr *)&sll, sizeof sll) < 0) {
        fprintf(stderr, "vward-dnscap: bind %s: %s\n", ifname, strerror(errno));
        return 2;
    }
    for (;;) {
        ssize_t n = recv(fd, buf, sizeof buf, 0);
        if (n < 0) {
            if (errno == EINTR || errno == ENOBUFS || errno == ENETDOWN) continue;
            fprintf(stderr, "vward-dnscap: recv: %s\n", strerror(errno));
            return 1;
        }
        packet(buf, (size_t)n);
    }
}

int main(int argc, char **argv)
{
    if (argc == 2 && !strcmp(argv[1], "--version")) { puts("vward-dnscap " VERSION); return 0; }
    if (argc != 4 || parse_subnet(argv[2]) || parse_ip(argv[3], &dns_addr)) {
        fprintf(stderr, "usage: vward-dnscap IFACE|any|--stdin SUBNET DNS\n");
        return 64;
    }
    if (!strcmp(argv[1], "--stdin")) return run_stdin();
    if (strlen(argv[1]) >= IF_NAMESIZE) { fprintf(stderr, "vward-dnscap: bad device\n"); return 64; }
    return run_live(argv[1]);
}
