#!/bin/sh
# vward-sentinel-act.sh EVENT ARGS: what VWARD does the moment the real-time watcher
# (vward-sentinel) notices something. The watcher starts it at most once per event within
# its rate and never twice at a time; exit 0 = done, else = could not help (counted).
#   link DEV up|down, addr DEV lost   the provider's or a tunnel's interface changed: the
#                                     guard that owns it checks now, not within a minute
#   down NAME                         a program of VWARD is gone: its starter, now
#   leak NAME RSS                     above its memory limit: stopped and started again
#   grow NAME RSS                     far above its own normal: logged
#   mem-low                           the router is short of memory: logged (optional
#                                     work already waits: the watcher's busy flag)
#   dns-fail                          the router's DNS did not answer twice: AdGuard Home
#                                     started when it is not running
#   chain-fail                        AdGuard Home in the DNS chain silent 3 times in a row:
#                                     out of the chain when the provider's DNS answers

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

RUN_DIR=${VWARD_RUN_DIR:-/opt/var/run/vward}
LOG=${VWARD_SENTINEL_LOG:-/opt/var/log/vward-sentinel.log}
INITD=${VWARD_INITD:-/opt/etc/init.d}
BIN_DIR=${VWARD_BIN_DIR:-/opt/bin}
CONSOLE_PIDFILE=${VWARD_CONSOLE_PIDFILE:-/opt/var/run/vward-console-lighttpd.pid}
AGH_INIT=${VWARD_AGH_INIT:-$INITD/S99adguardhome}
VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
VWARD_PROFILE_LIB=${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}

log() { mkdir -p "${LOG%/*}" 2>/dev/null; printf '%s|ACT|%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG" 2>/dev/null; }

valid() { case "$1" in ''|*[!A-Za-z0-9_.:-]*) return 1 ;; esac; }

pidfile_of() {
    case "$1" in
        route-engine) echo "$RUN_DIR/route-engine.pid" ;;
        panel) echo "$CONSOLE_PIDFILE" ;;
        awg-t[0-9]*) echo "$RUN_DIR/awg-engine/${1#awg-}.pid" ;;
        xray-v[0-9]*) echo "$RUN_DIR/vless-engine/${1#xray-}.pid" ;;
        *) return 1 ;;
    esac
}

# start_of NAME: the starter of a program of VWARD.
start_of() {
    case "$1" in
        route-engine) "$INITD/S91vward-route-engine" start ;;
        panel) "$INITD/S93vward-console" start ;;
        awg-*|xray-*) "$BIN_DIR/vward-tunnel-health.sh" ;;
        *) return 1 ;;
    esac </dev/null >/dev/null 2>&1
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
        valid "${2:-}" || exit 64
        log "down|$2"
        start_of "$2"
        ;;
    leak)
        valid "${2:-}" || exit 64
        F=$(pidfile_of "$2") || exit 64
        P=
        [ -r "$F" ] && read -r P < "$F"
        case "$P" in ''|*[!0-9]*) exit 1 ;; esac
        log "leak|$2|rss_kb=${3:-}|restart"
        kill "$P" 2>/dev/null
        n=0
        while kill -0 "$P" 2>/dev/null && [ "$n" -lt 5 ]; do sleep 1; n=$((n + 1)); done
        kill -9 "$P" 2>/dev/null
        start_of "$2"
        ;;
    grow)
        valid "${2:-}" || exit 64
        log "grow|$2|rss_kb=${3:-}"
        ;;
    mem-low)
        log "mem-low"
        ;;
    dns-fail)
        if [ -x "$AGH_INIT" ] && ! pidof AdGuardHome >/dev/null 2>&1; then
            # One gate for every starter: not again within 120 s, growing pauses, no orphaned PID file.
            if [ -r "$VWARD_ADMISSION_LIB" ] && . "$VWARD_ADMISSION_LIB" && command -v vward_agh_ensure >/dev/null 2>&1; then
                vward_agh_ensure "$AGH_INIT"
                case "$?" in
                    10) log "dns-fail|adguardhome-start" ;;
                    13) log "dns-fail|adguardhome-binary-broken"; exit 1 ;;
                    *) log "dns-fail|adguardhome-waiting"; exit 1 ;;
                esac
            else
                log "dns-fail|adguardhome-start"
                "$AGH_INIT" start </dev/null >/dev/null 2>&1
            fi
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
