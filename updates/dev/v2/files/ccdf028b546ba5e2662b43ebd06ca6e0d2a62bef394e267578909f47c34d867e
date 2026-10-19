#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
# Who acts, for the journals of the programs it asks (one decision, one agent).
VWARD_ACTOR=components-agent
export VWARD_ACTOR

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
# AdGuard Home from 90 s after boot and from then on (fix.28.2: only the first half hour
# before, and a build that crashed a day later stayed down a whole day, Viva 2026-10-16),
# while ads protection is on and no package update holds it. Every start goes through one
# gate (vward_agh_ensure): a start is not repeated before 120 s have passed, the pause grows
# after each failure, an orphaned PID file is removed first. A program that cannot run on
# this processor is replaced by the official build (ext-agh-official) and told in the bell.
CONSOLE_INIT=${VWARD_CONSOLE_INIT:-/opt/etc/init.d/S93vward-console}
CONSOLE_PIDFILE=${VWARD_CONSOLE_PIDFILE:-/opt/var/run/vward-console-lighttpd.pid}
AGH_INIT=${VWARD_AGH_INIT:-/opt/etc/init.d/S99adguardhome}
# An update replacing AdGuard Home announces its restart here (the DNS guard's «planned»: until when).
AGH_PLANNED_FILE=${VWARD_DNS_CHAIN_STATE:-/tmp/vward-dns-chain}/planned
CONFIG_BIN=${VWARD_CONSOLE_CONFIG_BIN:-/opt/bin/vward-console-config.sh}
COMP_STATE_DIR=${VWARD_COMPONENT_STATE:-/opt/etc/vward/components}
COMP_PENDING_FILE=${VWARD_COMPONENT_PENDING:-/opt/etc/vward/component-ops/pending}
AGH_OFF_FILE=${VWARD_AGH_DISABLED:-$COMP_STATE_DIR/adguardhome.disabled}
VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
[ ! -r "$VWARD_ADMISSION_LIB" ] || . "$VWARD_ADMISSION_LIB"
UPTIME_FILE=${VWARD_UPTIME_FILE:-/proc/uptime}
WATCH_EVERY=6
PANEL_DOWN=0
PANEL_WAIT=1
PANEL_SKIP=0
SSH_INIT=${VWARD_SSH_INIT:-/opt/etc/init.d/S51dropbear}
SSH_DOWN=0 SSH_WAIT=1 SSH_SKIP=0

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
    # Observation mode (fix.28.6): proposed, not done.
    if command -v vward_agent_acts >/dev/null 2>&1 &&
       ! vward_agent_acts components "mem-restart:$1" "$1 занимает $RSS КБ памяти (предел $3 КБ): перезапустить"; then
        eval "OVER_$1=0"
        return 0
    fi
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

# doh_note: the bell's notification of a Smart DNS client that does not start.
doh_note()
{
    command -v vward_note >/dev/null 2>&1 ||
        { [ ! -r "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}" ] || . "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}"; } 2>/dev/null
    command -v vward_note >/dev/null 2>&1 || return 0
    case "${VD_WHY:-}" in
        not_running) dn_t="Программа клиента не запускается." ;;
        *) dn_t="Программа клиента работает, но не принимает запросы." ;;
    esac
    vward_note warn "Smart DNS: клиент DoH не запускается" \
        "$dn_t Сайты из Smart DNS (например, ИИ-сервисы) могут не открываться. VWARD пробует запустить его снова с паузами до 15 минут и переустановит его библиотеки HTTPS, если не поможет."
}

# agh_watched: AdGuard Home is VWARD's to keep running: ads protection on (VWARD off turns
# every component off) and no update replacing it right now (a mere check of the packages
# holds their lock for minutes and is no reason to look away).
agh_watched()
{
    command -v vward_agh_ensure >/dev/null 2>&1 || return 1
    vward_component_enabled ads-privacy-guard || return 1
    # Switched off in «Компоненты» (fix.32): not started again.
    [ ! -e "$AGH_OFF_FILE" ] || return 1
    aw_until=; [ ! -r "$AGH_PLANNED_FILE" ] || read -r aw_until < "$AGH_PLANNED_FILE" || :
    case "$aw_until" in ''|*[!0-9]*) return 0 ;; esac
    [ "$(date +%s)" -ge "$aw_until" ]
}

# agh_note SEV TITLE TEXT: the bell, through the shared profile library.
agh_note()
{
    command -v vward_note >/dev/null 2>&1 ||
        { [ ! -r "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}" ] || . "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}"; } 2>/dev/null
    command -v vward_note >/dev/null 2>&1 || return 0
    vward_note "$1" "$2" "$3" d-agh
}

# agh_keep WHO: one start through the gate, its result in the journal. A broken program:
# told once per boot, the official build put in its place (at most once a day, in the
# background: a download of 10 MB). Starts that do not bring it up (3 in a row): told once.
agh_keep()
{
    [ ! -e "$AGH_OFF_FILE" ] || return 0
    VWARD_UNNICE=$UNNICE vward_agh_ensure "$AGH_INIT"
    case "$?" in
        10) log_event "AGH_STARTED|$1" ;;
        13) [ -e "$VWARD_AGH_STATE/noted" ] || {
                : > "$VWARD_AGH_STATE/noted"
                ak_rc=; [ ! -r "$VWARD_AGH_STATE/broken" ] || ak_rc=$(cut -d'|' -f2 "$VWARD_AGH_STATE/broken" 2>/dev/null)
                log_event "AGH_BINARY_BROKEN|$1|exit=${ak_rc:-?}"
                case "$ak_rc" in
                    132) ak_t="Программа AdGuard Home не подходит процессору роутера (недопустимая инструкция)." ;;
                    *) ak_t="Программа AdGuard Home завершается с ошибкой ${ak_rc:-?} сразу после запуска." ;;
                esac
                agh_note err "AdGuard Home не запускается" \
                    "$ak_t Реклама не блокируется, DNS идёт мимо AdGuard Home. VWARD ставит официальную сборку AdGuard Home для этого роутера."
            }
            agh_repair "$1" ;;
        11) ak_f=; [ ! -r "$VWARD_AGH_STATE/fails" ] || read -r ak_f < "$VWARD_AGH_STATE/fails"
            case "$ak_f" in ''|*[!0-9]*) ak_f=0 ;; esac
            if [ "$ak_f" -ge 3 ] && [ ! -e "$VWARD_AGH_STATE/noted" ]; then
                : > "$VWARD_AGH_STATE/noted"
                log_event "AGH_START_FAILED|$1|in_a_row=$ak_f"
                agh_note warn "AdGuard Home не запускается" \
                    "Запуск не помогает уже $ak_f раза подряд. Реклама не блокируется, DNS идёт мимо AdGuard Home. VWARD пробует снова каждые 10 минут; журнал AdGuard Home: Система → Журналы."
            fi ;;
    esac
}

# agh_repair WHO: the official build of AdGuard Home instead of a broken program, by the Panel's
# helper (backup, checksum, rollback), in the background, at most once a day.
AGH_REPAIR_STAMP=${VWARD_AGH_REPAIR_STAMP:-/opt/var/lib/vward/ext-update/agh-repair.last}
agh_repair()
{
    [ -x "$CONFIG_BIN" ] || return 0
    [ -z "$(find "$AGH_REPAIR_STAMP" -mmin -1440 2>/dev/null)" ] || return 0
    ! command -v vward_agent_acts >/dev/null 2>&1 ||
        vward_agent_acts components agh-official "AdGuard Home не запускается: установить официальную сборку AdGuard Home" || return 0
    mkdir -p "$(dirname "$AGH_REPAIR_STAMP")" 2>/dev/null && : > "$AGH_REPAIR_STAMP" || return 0
    log_event "AGH_REPAIR_STARTED|$1"
    (trap '' HUP; exec $UNNICE "$CONFIG_BIN" ext-agh-official repair) </dev/null >/dev/null 2>&1 &
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
        # 0 only when the engine started something (a switched-off tunnel is left alone).
        awg-*) [ -x "$BIN_DIR/vward-awg-engine.sh" ] && "$BIN_DIR/vward-awg-engine.sh" supervise | grep -q '^result=changed$' ;;
        xray-*) [ -x "$BIN_DIR/vward-vless-engine.sh" ] && "$BIN_DIR/vward-vless-engine.sh" supervise | grep -q '^result=changed$' ;;
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

# restart_allowed NAME: at most RESTART_MAX starts of one program within an hour (fix.32). One
# that keeps dying is left stopped, the owner told once in 6 hours: a start loop only eats the
# router's memory and flash.
RESTART_DIR=${VWARD_RESTART_DIR:-/tmp/vward-restarts}
RESTART_MAX=${VWARD_RESTART_MAX:-5}
restart_allowed()
{
    mkdir -p "$RESTART_DIR" 2>/dev/null || return 0
    RA_F="$RESTART_DIR/$(printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_')"
    RA_NOW=$(date +%s)
    RA_N=$(awk -v n="$RA_NOW" '$1 == "t" && $2 + 3600 > n {c++} END {print c + 0}' "$RA_F" 2>/dev/null)
    if [ "${RA_N:-0}" -ge "$RESTART_MAX" ]; then
        RA_TOLD=$(awk '$1 == "told" {print $2}' "$RA_F" 2>/dev/null | tail -n 1)
        if [ $((RA_NOW - ${RA_TOLD:-0})) -ge 21600 ]; then
            echo "told $RA_NOW" >> "$RA_F"
            log_event "RESTART_LIMIT|$1|starts_last_hour=$RA_N"
            command -v vward_note >/dev/null 2>&1 ||
                { [ ! -r "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}" ] || . "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}"; } 2>/dev/null
            ! command -v vward_note >/dev/null 2>&1 || vward_note err "Компонент $1 остановлен" \
                "За час он запускался $RA_N раз и снова останавливался. Агент компонентов больше не запускает его до следующего часа, чтобы не нагружать роутер. Подробности: Система → Журналы." utils
        fi
        return 1
    fi
    { awk -v n="$RA_NOW" '($1 == "t" && $2 + 3600 > n) || $1 == "told"' "$RA_F" 2>/dev/null; echo "t $RA_NOW"; } > "$RA_F.$$" && mv -f "$RA_F.$$" "$RA_F"
    return 0
}

# agent_do REQUEST: what another agent asked for.
agent_do()
{
    case "$1" in
        agh-start)
            agh_watched || return 1
            agh_keep "asked-by=$RQ_BY" ;;
        start:*)
            restart_allowed "${1#start:}" || return 0
            start_of "${1#start:}" && log_event "STARTED|${1#start:}|asked-by=$RQ_BY" ;;
        restart:*)
            AN=${1#restart:}
            AF=$(pidfile_of "$AN") || return 1
            restart_allowed "$AN" || return 0
            ! command -v vward_agent_acts >/dev/null 2>&1 ||
                vward_agent_acts components "restart:$AN" "Перезапустить $AN (просит $RQ_BY)" || return 0
            AP=
            [ ! -r "$AF" ] || read -r AP < "$AF" || :
            case "$AP" in ''|*[!0-9]*) ;; *)
                kill "$AP" 2>/dev/null
                AW=0
                while kill -0 "$AP" 2>/dev/null && [ "$AW" -lt 5 ]; do sleep 1; AW=$((AW + 1)); done
                kill -9 "$AP" 2>/dev/null ;;
            esac
            start_of "$AN"
            log_event "RESTARTED|$AN|asked-by=$RQ_BY" ;;
        engine-restart:*|engine-kick:*)
            AT=${1#*:}
            AB=$(engine_of "$AT") || return 0
            AO=restart; case "$1" in engine-kick:*) AO=kick ;; esac
            restart_allowed "module-$AT" || return 0
            "$AB" "$AO" "$AT" </dev/null >/dev/null 2>&1
            log_event "MODULE_$(echo "$AO" | tr 'a-z' 'A-Z')|$AT|asked-by=$RQ_BY" ;;
        *) return 64 ;;
    esac
}

# Requests in the order they came; while VWARD is switched off nothing starts (they go).
process_requests()
{
    for RQ in "$REQ_DIR"/*; do
        [ -f "$RQ" ] || continue
        RQ_BY=; [ ! -s "$RQ" ] || read -r RQ_BY < "$RQ" || :
        RQ_BY=${RQ_BY:-unknown}
        VWARD_ACTOR="components-agent asked-by=$RQ_BY"
        [ -e "$OFF_FLAG" ] || agent_do "${RQ##*/}"
        VWARD_ACTOR=components-agent
        rm -f "$RQ"
    done
}

# ---- Watching the other agents ---------------------------------------------------------------
# The components agent also watches the network, updates and maintenance agents: each must have
# run lately, none may hang, none may run twice at a time. A hung run is stopped (the next one
# starts fresh); a late agent and two runs at once are reported. The state for the Panel in RAM.
AGENTS_STATE=${VWARD_AGENTS_STATE:-/tmp/vward-agents.state}
# script|agent|file its run touches|late after s (0: not checked)|hung after s (0: never stopped)
# A run is stopped only when it is certainly stuck: a slow router (a busy Keenetic answers ndmc
# in seconds) makes a working run long, and stopping one halfway through a change is worse than
# waiting.
AGENT_JOBS="
vward-tunnel-health.sh|network|/tmp/vward-tunnel-health-chain.cron.last|600|1800
vward-tunnel-guard.sh|network||0|1800
vward-wan-guard.sh|network|/tmp/vward-wan-guard.cron.last|600|1800
vward-wan-recovery.sh|network||0|1800
vward-route-reconciler.sh|network|/tmp/vward-route-reconciler-maint.cron.last|1800|1800
vward-housekeeping.sh|maintenance|/tmp/vward-housekeeping.cron.last|10800|3600
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
        # Late: its last run is older than it should be (not in the first 15 minutes after boot,
        # nor before a job had its own interval to run since this agent started: 5 false ones
        # right after an installation, fix.30).
        if [ "$WL" -gt 0 ] && [ "$WA_UP" -ge 900 ] && [ -n "$WF" ] && [ $((WA_NOW - ${SUP_STARTED:-0})) -ge "$WL" ]; then
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
            if [ "$WH" -gt 0 ] && [ "$WAGE" -gt "$WH" ] &&
               { ! command -v vward_agent_acts >/dev/null 2>&1 ||
                 vward_agent_acts components "hung:$WS" "$WS работает $WAGE с (больше $WH с): остановить зависший запуск"; }; then
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

# Entware's SSH server runs whenever its start script is there (and not ENABLED=no). After a
# reboot (a Viva, 2026-10-12) the start script said «dropbear already running» with no server:
# the pid file left from before the reboot named a number another program had now, and nobody
# could log in until the next reboot. Not running: that pid file goes, the server starts; a
# start that fails is tried again after 1, 2, 4, 8, then every 15 minutes.
ssh_running()
{
    for SR in $(pidof dropbear sshd 2>/dev/null); do
        case "$(readlink "$PROC/$SR/exe" 2>/dev/null)" in /opt/*) return 0 ;; esac
    done
    return 1
}

keep_ssh()
{
    [ -x "$SSH_INIT" ] && ! grep -q '^ENABLED=no' "$SSH_INIT" 2>/dev/null || return 0
    if ssh_running; then
        SSH_DOWN=0 SSH_WAIT=1 SSH_SKIP=0
        return 0
    fi
    if [ "$SSH_SKIP" -gt 0 ]; then
        SSH_SKIP=$((SSH_SKIP - 1))
        return 0
    fi
    SSH_PF=$(sed -n "s/^PIDFILE=[\"']*\([^\"' ]*\).*/\1/p" "$SSH_INIT" | head -n 1)
    rm -f "${SSH_PF:-/opt/var/run/dropbear.pid}"
    $UNNICE "$SSH_INIT" start </dev/null >/dev/null 2>&1
    sleep 1
    if ssh_running; then
        log_event "SSH_STARTED|the SSH server was not running"
        SSH_DOWN=0 SSH_WAIT=1
    else
        [ "$SSH_DOWN" = 1 ] || log_event "SSH_START_FAILED|$SSH_INIT"
        SSH_DOWN=1
        SSH_SKIP=$SSH_WAIT
        SSH_WAIT=$((SSH_WAIT * 2))
        [ "$SSH_WAIT" -le 15 ] || SSH_WAIT=15
    fi
}

watch_services()
{
    keep_ssh
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
    # A module switched off in «Компоненты» (fix.32) is left alone.
    [ ! -f "${VWARD_AWG_ETC:-/opt/etc/vward/awg-engine}/tunnels.tsv" ] || [ ! -x "$BIN_DIR/vward-awg-engine.sh" ] || [ -e "$COMP_STATE_DIR/module-awg.disabled" ] ||
        "$BIN_DIR/vward-awg-engine.sh" supervise </dev/null >/dev/null 2>&1 || :
    [ ! -f "${VWARD_VLESS_ETC:-/opt/etc/vward/vless-engine}/tunnels.tsv" ] || [ ! -x "$BIN_DIR/vward-vless-engine.sh" ] || [ -e "$COMP_STATE_DIR/module-vless.disabled" ] ||
        "$BIN_DIR/vward-vless-engine.sh" supervise </dev/null >/dev/null 2>&1 || :

    UP=
    [ ! -r "$UPTIME_FILE" ] || read -r UP _ < "$UPTIME_FILE" || :
    UP=${UP%%.*}
    case "$UP" in ''|*[!0-9]*) return 0 ;; esac
    # An operation on a component the power cut in the middle (fix.32): done again once, 2
    # minutes after boot, in the background (it may download or wait for Keenetic).
    if [ "$UP" -ge 120 ] && [ -s "$COMP_PENDING_FILE" ] && [ ! -e /tmp/vward-component-recover.done ] && [ -x "$CONFIG_BIN" ]; then
        : > /tmp/vward-component-recover.done
        log_event "COMPONENT_RECOVER|$(sed -n 's/^op=//p' "$COMP_PENDING_FILE" | head -n 1)"
        ( "$CONFIG_BIN" component-recover now </dev/null >/dev/null 2>&1 & )
    fi
    # Every pass in the first half hour after boot (its own start script may not bring it up),
    # then once a minute: a look at AdGuard Home is a few programs, the supervisor runs often.
    if [ "$UP" -ge 90 ] && { [ "$UP" -lt 1800 ] || [ $((UP - ${AGH_LOOK:-0})) -ge "${VWARD_AGH_EVERY:-60}" ]; } && agh_watched; then
        AGH_LOOK=$UP
        agh_keep "uptime=$UP"
    fi

    # Smart DNS's local DoH client (https-dns-proxy) not listening: started again, from the 3rd
    # minute after boot (its own start script comes first); a start that does not help waits
    # 1, 2, 4, 8, then 15 minutes.
    if [ "$UP" -ge 180 ] && command -v vward_doh_keep >/dev/null 2>&1; then
        if [ "$DOH_SKIP" -gt 0 ]; then
            DOH_SKIP=$((DOH_SKIP - 1))
        else
            VWARD_UNNICE=$UNNICE vward_doh_keep
            case "$?" in
                10) log_event "DOH_STARTED|Smart DNS client was not listening|by=${VD_INIT:-?}"; DOH_WAIT=1 DOH_FAILS=0 ;;
                11) DOH_FAILS=$((DOH_FAILS + 1))
                    log_event "DOH_START_FAILED|why=${VD_WHY:-unknown}|by=${VD_INIT:-?}|in_a_row=$DOH_FAILS|next_try_min=$DOH_WAIT"
                    DOH_SKIP=$DOH_WAIT; DOH_WAIT=$((DOH_WAIT * 2)); [ "$DOH_WAIT" -le 15 ] || DOH_WAIT=15
                    # The third failed start in a row: told once (31-45 silent failures a day went
                    # unnoticed, Viva 2026-10-16); the tries go on with their pauses.
                    [ "$DOH_FAILS" != 3 ] || doh_note ;;
                *) DOH_WAIT=1 DOH_FAILS=0 ;;
            esac
        fi
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
SUP_STARTED=$(date +%s)
DOH_SKIP=0 DOH_WAIT=1 DOH_FAILS=0
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
