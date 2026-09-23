/* Fake crond for the router emulator: detaches and idles, so that pidof finds
 * a running crond while the audit runs the cron jobs itself. */
#include <fcntl.h>
#include <unistd.h>

int main(void)
{
    if (fork() > 0) return 0;
    setsid();
    int fd = open("/dev/null", O_RDWR);
    if (fd >= 0) { dup2(fd, 0); dup2(fd, 1); dup2(fd, 2); if (fd > 2) close(fd); }
    for (;;) pause();
}
