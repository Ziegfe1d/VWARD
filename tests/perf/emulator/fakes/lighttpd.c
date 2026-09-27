/* Fake lighttpd for the router emulator, called with "-f CONF" and no "&",
 * expecting it to daemonize itself the way the real lighttpd does: it writes
 * its pid where CONF's server.pid-file says (beta's path when CONF has none)
 * and waits.  "-tt" (the configuration test) succeeds.  A compiled,
 * double-forked binary (like crond.c and tcpdump.c) rather than a backgrounded
 * shell command: a shell "cmd &" can still leave the test harness's own stdout
 * pipe open through the detached child in this sandbox, which then hangs any
 * reader waiting for EOF. */
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static void pid_file(const char *conf, char *out, size_t size)
{
    char line[512];
    FILE *f = conf ? fopen(conf, "r") : NULL;
    snprintf(out, size, "%s", "/opt/var/run/keenetic-apps-lighttpd.pid");
    if (!f) return;
    while (fgets(line, sizeof line, f)) {
        char *p = strstr(line, "server.pid-file"), *a, *b;
        if (!p || !(a = strchr(p, '"')) || !(b = strchr(a + 1, '"'))) continue;
        *b = 0;
        snprintf(out, size, "%s", a + 1);
        break;
    }
    fclose(f);
}

int main(int argc, char **argv)
{
    const char *conf = NULL;
    char path[512];
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-tt")) return 0;
        if (!strcmp(argv[i], "-f") && i + 1 < argc) conf = argv[i + 1];
    }
    pid_file(conf, path, sizeof path);
    if (fork() > 0) return 0;
    setsid();
    int fd = open("/dev/null", O_RDWR);
    if (fd >= 0) { dup2(fd, 0); dup2(fd, 1); dup2(fd, 2); if (fd > 2) close(fd); }
    FILE *f = fopen(path, "w");
    if (f) { fprintf(f, "%d\n", getpid()); fclose(f); }
    for (;;) pause();
}
