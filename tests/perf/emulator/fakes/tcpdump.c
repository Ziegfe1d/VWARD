/* Fake tcpdump for the router emulator: prints one DNS query line per interval
 * from /emu/dns-queries, forever. A compiled binary so that ps shows "tcpdump"
 * as the command, like the real one. Interval: VWARD_EMU_DNS_INTERVAL seconds. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(void)
{
    const char *env = getenv("VWARD_EMU_DNS_INTERVAL");
    unsigned interval = env ? (unsigned)atoi(env) : 1;
    char name[256];
    setvbuf(stdout, NULL, _IOLBF, 0);
    for (;;) {
        FILE *f = fopen("/emu/dns-queries", "r");
        if (!f) return 1;
        while (fgets(name, sizeof name, f)) {
            name[strcspn(name, "\n")] = 0;
            if (printf("12:00:00.000000 br0 In IP 192.0.2.20.40000 > 192.0.2.1.53: 4242+ A? %s. (32)\n", name) < 0) return 0;
            if (interval) sleep(interval);
        }
        fclose(f);
        /* An empty or exhausted file must not spin the loop. */
        sleep(interval ? interval : 1);
    }
}
