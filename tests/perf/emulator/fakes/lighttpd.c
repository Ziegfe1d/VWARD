/* Fake lighttpd for the router emulator: S93keenetic-apps (beta) calls this
 * with "-f CONF" and no "&", expecting it to daemonize itself the way the
 * real lighttpd does. A compiled, double-forked binary (like crond.c and
 * tcpdump.c) rather than a backgrounded shell command: a shell "cmd &" can
 * still leave the test harness's own stdout pipe open through the detached
 * child in this sandbox, which then hangs any reader waiting for EOF. */
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>

int main(void)
{
    if (fork() > 0) return 0;
    setsid();
    int fd = open("/dev/null", O_RDWR);
    if (fd >= 0) { dup2(fd, 0); dup2(fd, 1); dup2(fd, 2); if (fd > 2) close(fd); }
    FILE *f = fopen("/opt/var/run/keenetic-apps-lighttpd.pid", "w");
    if (f) { fprintf(f, "%d\n", getpid()); fclose(f); }
    for (;;) pause();
}
