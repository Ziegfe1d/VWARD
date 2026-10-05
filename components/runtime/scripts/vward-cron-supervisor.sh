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


OFF_FLAG=${VWARD_COMPONENT_STATE:-/opt/etc/vward/components}/vward.off
OFF_BIN=${VWARD_OFF_BIN:-/opt/bin/vward-off.sh}

recover_critical()
{
    # VWARD switched off as a whole: cron and the Panel only.
    [ ! -e "$OFF_FLAG" ] || return 0
    /opt/etc/init.d/S91vward-route-engine start \
        >/dev/null 2>&1

    /opt/bin/vward-tunnel-health.sh \
        >/dev/null 2>&1

    /opt/bin/vward-tunnel-guard.sh \
        >/dev/null 2>&1
}


# Boot watch. At boot the home network may come up after the Panel's web server, which
# then cannot bind its address; it is started again here, and after a crash too.
# AdGuard Home only in the first half hour after boot: its start script does not always
# bring it up, and later a stopped AdGuard Home is the owner's choice. Every start goes
# through one gate (vward_agh_ensure): a start is not repeated before 120 s have passed,
# the pause grows after each failure, an orphaned PID file is removed first.
CONSOLE_INIT=${VWARD_CONSOLE_INIT:-/opt/etc/init.d/S93vward-console}
CONSOLE_PIDFILE=${VWARD_CONSOLE_PIDFILE:-/opt/var/run/vward-console-lighttpd.pid}
AGH_INIT=${VWARD_AGH_INIT:-/opt/etc/init.d/S99adguardhome}
AGH_WATCH_SECONDS=${VWARD_AGH_WATCH_SECONDS:-1800}
VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
[ ! -r "$VWARD_ADMISSION_LIB" ] || . "$VWARD_ADMISSION_LIB"
UPTIME_FILE=${VWARD_UPTIME_FILE:-/proc/uptime}
WATCH_EVERY=6
PANEL_DOWN=0
PANEL_WAIT=1
PANEL_SKIP=0

# The supervisor is background work: the lowest CPU priority. What it starts for the owner
# (cron, the Panel, AdGuard Home) gets the normal priority back.
UNNICE=
if renice -n 19 -p $$ >/dev/null 2>&1 && command -v nice >/dev/null 2>&1; then
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

SENTINEL_BIN=${VWARD_SENTINEL_BIN:-/opt/share/vward/sentinel/vward-sentinel}
SENTINEL_CTL=${VWARD_SENTINEL_CTL:-/opt/bin/vward-sentinel.sh}
SENTINEL_PIDFILE=${VWARD_SENTINEL_PIDFILE:-/opt/var/run/vward/sentinel.pid}
SENTINEL_WAIT=1
SENTINEL_SKIP=0

sentinel_alive()
{
    S_PID=
    [ -r "$SENTINEL_PIDFILE" ] && read -r S_PID 2>/dev/null < "$SENTINEL_PIDFILE" || :
    case "$S_PID" in ''|*[!0-9]*) return 1 ;; esac
    kill -0 "$S_PID" 2>/dev/null
}

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
    [ -r "$2" ] && read -r L_PID 2>/dev/null < "$2" || :
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

# ---- The components agent ----------------------------------------------------------------
# This supervisor is VWARD's components agent: it alone starts and restarts VWARD's programs,
# the tunnels' modules and AdGuard Home. The others (the real-time watcher, the network agent)
# ask it through vward_agent_ask; a byte in its pipe wakes it at once.
REQ_DIR=${VWARD_AGENT_REQ:-/tmp/vward-agent-components}
WAKE=$REQ_DIR/.wake
INITD=${VWARD_INITD:-/opt/etc/init.d}
BIN_DIR=${VWARD_BIN_DIR:-/opt/bin}
mkdir -p "$REQ_DIR" 2>/dev/null
[ -p "$WAKE" ] || mkfifo -m 600 "$WAKE" 2>/dev/null || :
# The wait between rounds: on the pipe when the shell can wait on it with a time limit.
WAIT_PIPE=0
# shellcheck disable=SC3045
[ -p "$WAKE" ] && [ -z "$( (read -t 1 _x < /dev/null) 2>&1)" ] && WAIT_PIPE=1

pidfile_of()
{
    case "$1" in
        route-engine) echo "$RUN_DIR/route-engine.pid" ;;
        panel) echo "$CONSOLE_PIDFILE" ;;
        awg-t[0-9]*) echo "$RUN_DIR/awg-engine/${1#awg-}.pid" ;;
        xray-v[0-9]*) echo "$RUN_DIR/vless-engine/${1#xray-}.pid" ;;
        *) return 1 ;;
    esac
}

# start_of NAME: the starter of a program of VWARD.
start_of()
{
    case "$1" in
        route-engine) $UNNICE "$INITD/S91vward-route-engine" start ;;
        panel) $UNNICE "$CONSOLE_INIT" start ;;
        awg-*) [ ! -x "$BIN_DIR/vward-awg-engine.sh" ] || "$BIN_DIR/vward-awg-engine.sh" supervise ;;
        xray-*) [ ! -x "$BIN_DIR/vward-vless-engine.sh" ] || "$BIN_DIR/vward-vless-engine.sh" supervise ;;
        *) return 1 ;;
    esac </dev/null >/dev/null 2>&1
}

# engine_of TUNNEL: the module (AmneziaWG or VLESS) that runs this tunnel.
engine_of()
{
    for EK in "${VWARD_VLESS_ETC:-/opt/etc/vward/vless-engine}|${VWARD_VLESS_ENGINE_BIN:-$BIN_DIR/vward-vless-engine.sh}" \
              "${VWARD_AWG_ETC:-/opt/etc/vward/awg-engine}|${VWARD_AWG_ENGINE_BIN:-$BIN_DIR/vward-awg-engine.sh}"; do
        EB=${EK#*|}
        [ -x "$EB" ] && awk -F '\t' -v n="$1" '$2 == n {f = 1} END {exit !f}' "${EK%%|*}/tunnels.tsv" 2>/dev/null || continue
        echo "$EB"; return 0
    done
    return 1
}

# agent_do REQUEST: what another agent asked for.
agent_do()
{
    case "$1" in
        agh-start)
            command -v vward_agh_ensure >/dev/null 2>&1 || return 1
            VWARD_UNNICE=$UNNICE vward_agh_ensure "$AGH_INIT"
            case "$?" in
                10) log_event "AGH_STARTED|asked" ;;
                13) log_event "AGH_BINARY_BROKEN|asked" ;;
            esac ;;
        start:*)
            start_of "${1#start:}" && log_event "STARTED|${1#start:}|asked" ;;
        restart:*)
            AN=${1#restart:}
            AF=$(pidfile_of "$AN") || return 1
            AP=
            [ ! -r "$AF" ] || read -r AP < "$AF" || :
            case "$AP" in ''|*[!0-9]*) ;; *)
                kill "$AP" 2>/dev/null
                AW=0
                while kill -0 "$AP" 2>/dev/null && [ "$AW" -lt 5 ]; do sleep 1; AW=$((AW + 1)); done
                kill -9 "$AP" 2>/dev/null ;;
            esac
            start_of "$AN"
            log_event "RESTARTED|$AN|asked" ;;
        engine-restart:*|engine-kick:*)
            AT=${1#*:}
            AB=$(engine_of "$AT") || return 0
            AO=restart; case "$1" in engine-kick:*) AO=kick ;; esac
            "$AB" "$AO" "$AT" </dev/null >/dev/null 2>&1
            log_event "MODULE_$(echo "$AO" | tr 'a-z' 'A-Z')|$AT|asked" ;;
        *) return 64 ;;
    esac
}

# Requests in the order they came; while VWARD is switched off nothing starts (they go).
process_requests()
{
    for RQ in "$REQ_DIR"/*; do
        [ -f "$RQ" ] || continue
        [ -e "$OFF_FLAG" ] || agent_do "${RQ##*/}"
        rm -f "$RQ"
    done
}

# ---- Watching the other agents ---------------------------------------------------------------
# The components agent also watches the network, updates and maintenance agents: each must have
# run lately, none may hang, none may run twice at a time. A hung run is stopped (the next one
# starts fresh); a late agent and two runs at once are reported. The state for the Panel in RAM.
AGENTS_STATE=${VWARD_AGENTS_STATE:-/tmp/vward-agents.state}
# script|agent|file its run touches|late after s (0: not checked)|hung after s (0: never stopped)
AGENT_JOBS="
vward-tunnel-health.sh|network|/tmp/vward-tunnel-health-chain.cron.last|300|240
vward-tunnel-guard.sh|network||0|300
vward-wan-guard.sh|network|/tmp/vward-wan-guard.cron.last|300|300
vward-wan-recovery.sh|network||0|600
vward-route-reconciler.sh|network|/tmp/vward-route-reconciler-maint.cron.last|900|600
vward-housekeeping.sh|maintenance|/tmp/vward-housekeeping.cron.last|10800|1800
vward-update-watch.sh|updates|/opt/var/log/vward/updater-watch.log|3600|0
"
AGENT_NOTED=" "

# age_of PID: seconds the process has run (its start in /proc/PID/stat, 100 ticks a second).
age_of()
{
    AS=
    read -r AS 2>/dev/null < "$PROC/$1/stat" || return 1
    AS=${AS##*) }
    # shellcheck disable=SC2086
    set -- $AS
    [ "$#" -ge 20 ] || return 1
    shift 19
    AU=; read -r AU _ 2>/dev/null < "$UPTIME_FILE" || return 1
    echo $(( ${AU%%.*} - $1 / 100 ))
}

# ppid_of PID
ppid_of() { PS_=; read -r PS_ 2>/dev/null < "$PROC/$1/stat" || return 1; PS_=${PS_##*) }; set -- $PS_; echo "$2"; }

watch_agents()
{
    WA_UP=; [ ! -r "$UPTIME_FILE" ] || read -r WA_UP _ < "$UPTIME_FILE" || :
    WA_UP=${WA_UP%%.*}; case "$WA_UP" in ''|*[!0-9]*) WA_UP=0 ;; esac
    WA_NOW=$(date +%s)
    WA_NET=ok WA_UPD=ok WA_MNT=ok
    # The runs going on now, once: «pid script» of every agent script.
    WA_RUNS=$(ps w 2>/dev/null | awk -v jobs="$AGENT_JOBS" '
        BEGIN {n = split(jobs, j, "\n"); for (i = 1; i <= n; i++) if (split(j[i], f, "|") >= 5) s[f[1]] = 1}
        {for (k in s) if (index($0, "/" k) && $0 !~ /awk/) {print $1, k; break}}')
    OLDIFS_A=$IFS
    IFS='
'
    for WJ in $AGENT_JOBS; do
        IFS=$OLDIFS_A
        [ -n "$WJ" ] || { IFS='
'; continue; }
        OLDIFS_B=$IFS; IFS='|'
        # shellcheck disable=SC2086
        set -- $WJ
        IFS=$OLDIFS_B
        WS=$1 WG=$2 WF=$3 WL=$4 WH=$5
        WST=ok
        # Late: its last run is older than it should be (not in the first 15 minutes after boot).
        if [ "$WL" -gt 0 ] && [ "$WA_UP" -ge 900 ] && [ -n "$WF" ]; then
            WT=$(date -r "$WF" +%s 2>/dev/null || echo 0)
            if [ $((WA_NOW - WT)) -gt "$WL" ]; then
                WST=late
                case "$AGENT_NOTED" in *" late:$WS "*) ;; *) log_event "AGENT_LATE|$WG|$WS|last=$WT"; AGENT_NOTED="$AGENT_NOTED late:$WS " ;; esac
            else
                AGENT_NOTED=$(printf '%s' "$AGENT_NOTED" | sed "s/ late:$WS //")
            fi
        fi
        # Runs of this script that are not a part of another run of it (its own subshells are).
        WN=0
        for WP in $(printf '%s\n' "$WA_RUNS" | awk -v s="$WS" '$2 == s {print $1}'); do
            WPP=$(ppid_of "$WP") || continue
            printf '%s\n' "$WA_RUNS" | awk -v p="$WPP" -v s="$WS" '$1 == p && $2 == s {f = 1} END {exit !f}' && continue
            WN=$((WN + 1))
            WAGE=$(age_of "$WP") || continue
            if [ "$WH" -gt 0 ] && [ "$WAGE" -gt "$WH" ]; then
                kill "$WP" 2>/dev/null && log_event "AGENT_HUNG|$WG|$WS|pid=$WP|age=$WAGE|stopped"
                WST=hung
            fi
        done
        [ "$WN" -le 1 ] || log_event "AGENT_TWICE|$WG|$WS|runs=$WN"
        case "$WG:$WST" in
            network:late|network:hung) [ "$WA_NET" = hung ] || WA_NET=$WST ;;
            updates:late|updates:hung) WA_UPD=$WST ;;
            maintenance:late|maintenance:hung) WA_MNT=$WST ;;
        esac
        IFS='
'
    done
    IFS=$OLDIFS_A
    printf 'at=%s\nnetwork=%s\ncomponents=ok\nupdates=%s\nmaintenance=%s\n' "$WA_NOW" "$WA_NET" "$WA_UPD" "$WA_MNT" > "$AGENTS_STATE.tmp" &&
        mv -f "$AGENTS_STATE.tmp" "$AGENTS_STATE"
}

# SSH stays: when memory runs out, the kernel stops some program to free it; never the SSH
# server or its sessions (Keenetic's or Entware's dropbear, OpenSSH), the way in to fix things.
# New sessions inherit it from the server; checked once a minute, written only when it differs.
protect_ssh()
{
    for SP in $(pidof dropbear sshd 2>/dev/null); do
        [ -w "$PROC/$SP/oom_score_adj" ] || continue
        read -r SA 2>/dev/null < "$PROC/$SP/oom_score_adj" || continue
        [ "$SA" = -1000 ] || echo -1000 > "$PROC/$SP/oom_score_adj" 2>/dev/null || :
    done
}

watch_services()
{
    protect_ssh
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

    # The Panel's web server picks up settings an update brought (a shell test, no process).
    if [ -x "$CONSOLE_INIT" ] && [ /opt/share/vward/console/lighttpd.conf -nt /opt/var/run/vward/console-lighttpd.conf ]; then
        $UNNICE "$CONSOLE_INIT" start </dev/null >/dev/null 2>&1 && log_event "PANEL_RECONFIGURED"
    fi

    # VWARD switched off as a whole: cron and the Panel stay, nothing else of VWARD starts;
    # the other agents are idle on purpose then, not watched.
    # DNS redirects into AdGuard Home that came back (Keenetic rebuilt its firewall) go again.
    if [ -e "$OFF_FLAG" ]; then
        [ ! -x "$OFF_BIN" ] || $UNNICE "$OFF_BIN" keep </dev/null >/dev/null 2>&1
        printf 'at=%s\nstate=off\n' "$(date +%s)" > "$AGENTS_STATE" 2>/dev/null
        return 0
    fi
    watch_agents

    # The tunnels' modules (AmneziaWG, VLESS): a stopped one starts again. Without such
    # tunnels this is one file test, no process.
    [ ! -f "${VWARD_AWG_ETC:-/opt/etc/vward/awg-engine}/tunnels.tsv" ] || [ ! -x "$BIN_DIR/vward-awg-engine.sh" ] ||
        "$BIN_DIR/vward-awg-engine.sh" supervise </dev/null >/dev/null 2>&1 || :
    [ ! -f "${VWARD_VLESS_ETC:-/opt/etc/vward/vless-engine}/tunnels.tsv" ] || [ ! -x "$BIN_DIR/vward-vless-engine.sh" ] ||
        "$BIN_DIR/vward-vless-engine.sh" supervise </dev/null >/dev/null 2>&1 || :

    UP=
    [ ! -r "$UPTIME_FILE" ] || read -r UP _ < "$UPTIME_FILE" || :
    UP=${UP%%.*}
    case "$UP" in ''|*[!0-9]*) return 0 ;; esac
    if [ "$UP" -ge 90 ] && [ "$UP" -lt "$AGH_WATCH_SECONDS" ] && command -v vward_agh_ensure >/dev/null 2>&1; then
        VWARD_UNNICE=$UNNICE vward_agh_ensure "$AGH_INIT"
        case "$?" in
            10) log_event "AGH_STARTED|uptime=$UP" ;;
            13) [ "${AGH_BROKEN_LOGGED:-0}" = 1 ] || { AGH_BROKEN_LOGGED=1; log_event "AGH_BINARY_BROKEN|uptime=$UP"; } ;;
        esac
    fi

    # The real-time watcher (vward-sentinel) sees leaks within seconds; without it this
    # minute's check does.
    if sentinel_alive; then
        :
    else
        watch_memory
        if [ -x "$SENTINEL_BIN" ] && [ -x "$SENTINEL_CTL" ]; then
            if [ "$SENTINEL_SKIP" -gt 0 ]; then
                SENTINEL_SKIP=$((SENTINEL_SKIP - 1))
            elif $UNNICE "$SENTINEL_CTL" start </dev/null >/dev/null 2>&1 && sentinel_alive; then
                log_event "SENTINEL_STARTED"
                SENTINEL_WAIT=1
            else
                log_event "SENTINEL_START_FAILED"
                SENTINEL_SKIP=$SENTINEL_WAIT
                SENTINEL_WAIT=$((SENTINEL_WAIT * 2))
                [ "$SENTINEL_WAIT" -le 60 ] || SENTINEL_WAIT=60
            fi
        fi
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

    # Until the next round; what another agent asks is done at once, the rounds keep their time.
    if [ "$WAIT_PIPE" = 1 ]; then
        RT=$INTERVAL
        while [ "$RT" -gt 0 ]; do
            T0=; [ ! -r "$UPTIME_FILE" ] || read -r T0 _ < "$UPTIME_FILE" || :
            # shellcheck disable=SC3045
            read -t "$RT" _w <> "$WAKE" || break
            process_requests
            T1=; [ ! -r "$UPTIME_FILE" ] || read -r T1 _ < "$UPTIME_FILE" || :
            case "${T0%%.*}${T1%%.*}" in ''|*[!0-9]*) break ;; esac
            RT=$((RT - ${T1%%.*} + ${T0%%.*}))
        done
    else
        sleep "$INTERVAL"
    fi
    process_requests
done
