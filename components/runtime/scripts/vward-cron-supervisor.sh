#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

PIDFILE="/opt/var/run/crond-supervisor.pid"
LOCK="/tmp/crond-supervisor.lock"
LOG="/opt/var/log/crond-supervisor.log"
HEARTBEAT="/tmp/crond-supervisor.last"

INTERVAL=10

mkdir -p /opt/var/run /opt/var/log


if ! mkdir "$LOCK" 2>/dev/null; then

    OLD=$(cat "$LOCK/pid" 2>/dev/null)

    if [ -n "$OLD" ] &&
       kill -0 "$OLD" 2>/dev/null; then
        exit 0
    fi

    rm -rf "$LOCK"
    mkdir "$LOCK" || exit 1
fi


echo $$ > "$LOCK/pid"
echo $$ > "$PIDFILE"


cleanup()
{
    CUR=$(cat "$PIDFILE" 2>/dev/null)

    [ "$CUR" = "$$" ] &&
        rm -f "$PIDFILE"

    rm -rf "$LOCK"
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


log_event "SUPERVISOR_START|pid=$$"


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

    sleep "$INTERVAL"
done
