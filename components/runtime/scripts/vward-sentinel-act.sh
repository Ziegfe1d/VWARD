#!/bin/sh
# vward-sentinel-act.sh EVENT ARGS: what VWARD does the moment the real-time watcher
# (vward-sentinel) notices something. The watcher starts it at most once per event within
# its rate and never twice at a time; exit 0 = done, else = could not help (counted).
# The watcher only sees; each event goes to the agent of its zone: interfaces and DNS chain to
# the network agent, programs and AdGuard Home to the components agent (asked, never done here).
#   link DEV up|down, addr DEV lost   the provider's or a tunnel's interface changed: the
#                                     network agent checks it now, not within a minute
#   down NAME                         a program of VWARD is gone: the components agent starts it
#   leak NAME RSS                     above its memory limit: the components agent restarts it
#   grow NAME RSS                     far above its own normal: logged
#   mem-low                           the router is short of memory: logged (optional
#                                     work already waits: the watcher's busy flag)
#   dns-fail                          the router's DNS did not answer twice: the components
#                                     agent starts AdGuard Home when it is not running
#   chain-fail                        AdGuard Home in the DNS chain silent 3 times in a row:
#                                     out of the chain when the provider's DNS answers

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

LOG=${VWARD_SENTINEL_LOG:-/opt/var/log/vward-sentinel.log}
INITD=${VWARD_INITD:-/opt/etc/init.d}
BIN_DIR=${VWARD_BIN_DIR:-/opt/bin}
AGH_INIT=${VWARD_AGH_INIT:-$INITD/S99adguardhome}
VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
VWARD_PROFILE_LIB=${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}

log() { mkdir -p "${LOG%/*}" 2>/dev/null; printf '%s|ACT|%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG" 2>/dev/null; }

valid() { case "$1" in ''|*[!A-Za-z0-9_.:-]*) return 1 ;; esac; }

# The programs VWARD's components agent starts and restarts (it alone does; asked here).
known() { case "$1" in route-engine|panel|awg-t[0-9]*|xray-v[0-9]*) return 0 ;; esac; return 1; }

# ask REQUEST: to the components agent (the cron supervisor); 0 = it has the request.
ask() {
    [ -r "$VWARD_ADMISSION_LIB" ] && . "$VWARD_ADMISSION_LIB" && command -v vward_agent_ask >/dev/null 2>&1 || return 1
    vward_agent_ask "$1"
}

wan_device() {
    [ -r "$VWARD_PROFILE_LIB" ] && . "$VWARD_PROFILE_LIB" && vward_profile_load >/dev/null 2>&1 && echo "${VWARD_WAN_DEVICE:-}"
}

EVENT=${1:-}
case "$EVENT" in
    link|addr)
        DEV=${2:-}
        valid "$DEV" || exit 64
        log "$EVENT|$DEV|${3:-}"
        if [ "$DEV" = "$(wan_device)" ]; then
            "$BIN_DIR/vward-wan-guard.sh" </dev/null >/dev/null 2>&1
        else
            "$BIN_DIR/vward-tunnel-health.sh" </dev/null >/dev/null 2>&1
            "$BIN_DIR/vward-tunnel-guard.sh" </dev/null >/dev/null 2>&1
        fi
        ;;
    down)
        valid "${2:-}" && known "$2" || exit 64
        log "down|$2"
        ask "start:$2"
        ;;
    leak)
        valid "${2:-}" && known "$2" || exit 64
        log "leak|$2|rss_kb=${3:-}|restart"
        ask "restart:$2"
        ;;
    grow)
        valid "${2:-}" || exit 64
        log "grow|$2|rss_kb=${3:-}"
        ;;
    mem-low)
        log "mem-low"
        ;;
    dns-fail)
        # AdGuard Home dead: the components agent starts it (through its one gate: not again
        # within 120 s, growing pauses, no orphaned PID file).
        if [ -x "$AGH_INIT" ] && ! pidof AdGuardHome >/dev/null 2>&1; then
            log "dns-fail|adguardhome-start"
            ask agh-start
        else
            log "dns-fail|nothing-to-start"
            exit 1
        fi
        ;;
    chain-fail)
        log "chain-fail"
        G=${VWARD_DNS_GUARD_BIN:-$BIN_DIR/vward-ads-privacy-dns-guard.sh}
        [ -x "$G" ] || exit 1
        "$G" chain-out </dev/null 2>/dev/null | grep -q '^chain_state=out$'
        ;;
    *) exit 64 ;;
esac
