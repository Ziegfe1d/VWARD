#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

PIDFILE="/opt/var/run/vward/cron-supervisor.pid"
LOCK="/tmp/vward-cron-supervisor.lock"
LOG="/opt/var/log/vward-cron-supervisor.log"
HEARTBEAT="/tmp/vward-cron-supervisor.last"

INTERVAL=10

mkdir -p /opt/var/run/vward /opt/var/log


if ! mkdir "$LOCK" 2>/dev/null; then

    OLD=$(cat "$LOCK/pid" 2>/dev/null)

    if [ -n "$OLD" ] &&
       kill -0 "$OLD" 2>/dev/null; then
        exit 0
    fi

    rm -rf "${LOCK:?}"
    mkdir "$LOCK" || exit 1
fi


echo $$ > "$LOCK/pid"
echo $$ > "$PIDFILE"


cleanup()
{
    CUR=$(cat "$PIDFILE" 2>/dev/null)

    [ "$CUR" = "$$" ] &&
        rm -f "$PIDFILE"

    rm -rf "${LOCK:?}"
}

trap cleanup EXIT
trap 'exit 0' INT TERM


log_event()
{
    echo "$(date '+%Y-%m-%d %H:%M:%S')|$*" >> "$LOG"
}


recover_critical()
{
    /opt/etc/init.d/S91vward-route-engine start \
        >/dev/null 2>&1

    /opt/bin/vward-tunnel-health.sh \
        >/dev/null 2>&1

    /opt/bin/vward-tunnel-guard.sh \
        >/dev/null 2>&1
}


# Boot watch. At boot the home network may come up after the Panel's web server, which
# then cannot bind its address; it is started again here, and after a crash too.
# AdGuard Home only in the first 10 minutes after boot: its start script does not always
# bring it up, and later a stopped AdGuard Home is the owner's choice.
CONSOLE_INIT=${VWARD_CONSOLE_INIT:-/opt/etc/init.d/S93vward-console}
CONSOLE_PIDFILE=${VWARD_CONSOLE_PIDFILE:-/opt/var/run/vward-console-lighttpd.pid}
AGH_INIT=${VWARD_AGH_INIT:-/opt/etc/init.d/S99adguardhome}
UPTIME_FILE=${VWARD_UPTIME_FILE:-/proc/uptime}
WATCH_EVERY=6
PANEL_DOWN=0

watch_services()
{
    P=
    [ ! -r "$CONSOLE_PIDFILE" ] || read -r P < "$CONSOLE_PIDFILE" || :
    if [ -x "$CONSOLE_INIT" ] && { [ -z "$P" ] || ! kill -0 "$P" 2>/dev/null; }; then
        if "$CONSOLE_INIT" start </dev/null >/dev/null 2>&1; then
            log_event "PANEL_STARTED"
            PANEL_DOWN=0
        else
            [ "$PANEL_DOWN" = 1 ] || log_event "PANEL_START_FAILED"
            PANEL_DOWN=1
        fi
    fi

    UP=
    [ ! -r "$UPTIME_FILE" ] || read -r UP _ < "$UPTIME_FILE" || :
    UP=${UP%%.*}
    case "$UP" in ''|*[!0-9]*) return 0 ;; esac
    if [ "$UP" -ge 90 ] && [ "$UP" -lt 600 ] && [ -x "$AGH_INIT" ] &&
       ! pidof AdGuardHome >/dev/null 2>&1; then
        "$AGH_INIT" start </dev/null >/dev/null 2>&1
        log_event "AGH_STARTED|uptime=$UP"
    fi
}


log_event "SUPERVISOR_START|pid=$$"
TICK=0


while :; do

    date > "$HEARTBEAT"

    PIDS=$(pidof crond 2>/dev/null)
    CNT=$(echo "$PIDS" | wc -w)

    if [ "$CNT" -eq 0 ]; then

        log_event "CROND_DOWN"

        /opt/etc/init.d/S90crond start \
            >/dev/null 2>&1

        sleep 2

        PIDS=$(pidof crond 2>/dev/null)
        CNT=$(echo "$PIDS" | wc -w)

        if [ "$CNT" -eq 1 ]; then

            log_event "CROND_RESTARTED|pid=$PIDS"

            recover_critical

        else
            log_event "CROND_RESTART_FAILED|count=$CNT|pids=$PIDS"
        fi

    elif [ "$CNT" -gt 1 ]; then

        log_event "CROND_MULTIPLE|count=$CNT|pids=$PIDS"

    fi

    TICK=$((TICK + 1))
    # Once a minute, not on the first round: at boot S93 starts the Panel just after.
    [ $((TICK % WATCH_EVERY)) -ne 0 ] || watch_services

    sleep "$INTERVAL"
done
