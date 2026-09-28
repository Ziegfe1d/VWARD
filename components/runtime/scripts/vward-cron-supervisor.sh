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
PANEL_WAIT=1
PANEL_SKIP=0

# The supervisor is background work: the lowest CPU priority. What it starts for the owner
# (cron, the Panel, AdGuard Home) gets the normal priority back.
UNNICE=
if renice -n 19 -p $$ >/dev/null 2>&1; then
    UNNICE="nice -n -19"
fi

# Memory. VWARD's long-running programs are stopped when they stay above their limit three
# minutes in a row (a leak); their own starters bring them back within a minute (S91 cron
# watchdog, this supervisor, the tunnel health check). Low memory of the whole router is
# logged once. All read by the shell from /proc.
PROC=${VWARD_PROC:-/proc}
RUN_DIR=${VWARD_RUN_DIR:-/opt/var/run/vward}
MEM_LOW_KB=${VWARD_MEM_LOW_KB:-16384}
MEM_LOW=0

rss_kb()
{
    RSS=
    [ -r "$PROC/$1/status" ] || return 1
    while read -r K V _; do
        [ "$K" != VmRSS: ] || { RSS=$V; return 0; }
    done < "$PROC/$1/status"
    return 1
}

# check_leak ID PIDFILE LIMIT_KB
check_leak()
{
    L_PID=
    [ -r "$2" ] && read -r L_PID < "$2" 2>/dev/null || :
    case "$L_PID" in ''|*[!0-9]*) eval "OVER_$1=0"; return 0 ;; esac
    rss_kb "$L_PID" || { eval "OVER_$1=0"; return 0; }
    if [ "$RSS" -le "$3" ]; then
        eval "OVER_$1=0"
        return 0
    fi
    eval "N=\${OVER_$1:-0}"
    N=$((N + 1))
    eval "OVER_$1=$N"
    [ "$N" -ge 3 ] || return 0
    kill "$L_PID" 2>/dev/null
    log_event "MEM_RESTART|$1|rss_kb=$RSS|limit_kb=$3"
    eval "OVER_$1=0"
}

watch_memory()
{
    check_leak routeengine "$RUN_DIR/route-engine.pid" "${VWARD_MEM_ROUTE_ENGINE_KB:-16384}"
    check_leak panel "$CONSOLE_PIDFILE" "${VWARD_MEM_PANEL_KB:-24576}"
    for F in "$RUN_DIR"/awg-engine/t*.pid "$RUN_DIR"/vless-engine/v*.pid; do
        [ -e "$F" ] || continue
        ID=${F##*/}
        ID=${ID%.pid}
        case "$F" in
            */awg-engine/*) check_leak "awg$ID" "$F" "${VWARD_MEM_AWG_KB:-65536}" ;;
            *) check_leak "vless$ID" "$F" "${VWARD_MEM_XRAY_KB:-98304}" ;;
        esac
    done

    AVAIL=
    if [ -r "$PROC/meminfo" ]; then
        while read -r K V _; do
            [ "$K" != MemAvailable: ] || { AVAIL=$V; break; }
        done < "$PROC/meminfo"
    fi
    case "$AVAIL" in ''|*[!0-9]*) return 0 ;; esac
    if [ "$AVAIL" -lt "$MEM_LOW_KB" ]; then
        [ "$MEM_LOW" = 1 ] || log_event "MEM_LOW|available_kb=$AVAIL"
        MEM_LOW=1
    elif [ "$MEM_LOW" = 1 ]; then
        log_event "MEM_OK|available_kb=$AVAIL"
        MEM_LOW=0
    fi
}

watch_services()
{
    P=
    [ ! -r "$CONSOLE_PIDFILE" ] || read -r P < "$CONSOLE_PIDFILE" || :
    if [ -x "$CONSOLE_INIT" ] && { [ -z "$P" ] || ! kill -0 "$P" 2>/dev/null; }; then
        # A start that fails is tried again after 1, 2, 4, 8, then every 15 minutes.
        if [ "$PANEL_SKIP" -gt 0 ]; then
            PANEL_SKIP=$((PANEL_SKIP - 1))
        elif $UNNICE "$CONSOLE_INIT" start </dev/null >/dev/null 2>&1; then
            log_event "PANEL_STARTED"
            PANEL_DOWN=0 PANEL_WAIT=1
        else
            [ "$PANEL_DOWN" = 1 ] || log_event "PANEL_START_FAILED"
            PANEL_DOWN=1
            PANEL_SKIP=$PANEL_WAIT
            PANEL_WAIT=$((PANEL_WAIT * 2))
            [ "$PANEL_WAIT" -le 15 ] || PANEL_WAIT=15
        fi
    else
        PANEL_DOWN=0 PANEL_WAIT=1 PANEL_SKIP=0
    fi

    UP=
    [ ! -r "$UPTIME_FILE" ] || read -r UP _ < "$UPTIME_FILE" || :
    UP=${UP%%.*}
    case "$UP" in ''|*[!0-9]*) return 0 ;; esac
    if [ "$UP" -ge 90 ] && [ "$UP" -lt 600 ] && [ -x "$AGH_INIT" ] &&
       ! pidof AdGuardHome >/dev/null 2>&1; then
        $UNNICE "$AGH_INIT" start </dev/null >/dev/null 2>&1
        log_event "AGH_STARTED|uptime=$UP"
    fi

    watch_memory
}


log_event "SUPERVISOR_START|pid=$$"
TICK=0


while :; do

    date > "$HEARTBEAT"

    PIDS=$(pidof crond 2>/dev/null)
    CNT=$(echo "$PIDS" | wc -w)

    if [ "$CNT" -eq 0 ]; then

        log_event "CROND_DOWN"

        $UNNICE /opt/etc/init.d/S90crond start \
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
