#!/opt/bin/sh
# VWARD manual WAN recovery: "dhcp-renew" asks the provider for the address
# again, "wan-bounce" reconnects the WAN interface (down, 5 s, up).
#
# Shares the WAN Guard lock and its ownership protocol: before the interface
# is taken down its name is written to the owned-down marker, so an
# interrupted bounce is brought back up by this tool's signal handler or by
# the next WAN Guard run.
PATH="/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin"

VWARD_PROFILE_LIB=${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}
[ -r "$VWARD_PROFILE_LIB" ] || { echo "ERROR=PROFILE_UNAVAILABLE"; exit 1; }
. "$VWARD_PROFILE_LIB"
vward_profile_load || { echo "ERROR=PROFILE_UNAVAILABLE"; exit 1; }
[ -n "${VWARD_WAN_INTERFACE:-}" ] || { echo "ERROR=WAN_INTERFACE_UNKNOWN"; exit 1; }

case "${1:-}" in
    dhcp-renew|wan-bounce) REQUEST=$1 ;;
    *) echo "ERROR=INVALID_REQUEST"; echo "ALLOWED=dhcp-renew|wan-bounce"; exit 64 ;;
esac

VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
[ -r "$VWARD_ADMISSION_LIB" ] || { echo "ERROR=ADMISSION_UNAVAILABLE"; exit 1; }
. "$VWARD_ADMISSION_LIB"
vward_admission_enter wan-recovery || { echo "ERROR=UPDATER_BUSY"; exit 75; }

NDMC=${NDMC:-/bin/ndmc}
LOCKDIR=${VWARD_WAN_GUARD_LOCK:-/tmp/vward-wan-guard.lock.d}
REC_DIR=${VWARD_WAN_RECOVERY_DIR:-/tmp/vward-wan-guard-recovery}
REC_LOG=${VWARD_WAN_RECOVERY_LOG:-/opt/var/log/vward-wan-guard-recovery.log}
WAN_BOUNCE_MARKER="$REC_DIR/owned-down"
MANUAL_COOLDOWN=${VWARD_WAN_MANUAL_COOLDOWN:-60}
BOUNCE_WAIT=${VWARD_WAN_BOUNCE_WAIT:-5}

LOCK_OWNED=0
PHASE=IDLE
CANCEL=0
UP_RC=1

log_action()
{
    printf '%s action=%s interface=%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S%z')" "$1" "$VWARD_WAN_INTERFACE" "$2" >> "$REC_LOG" 2>/dev/null
    return 0
}

run_up()
{
    tries=0
    while [ "$tries" -lt 3 ]; do
        tries=$((tries + 1))
        LD_LIBRARY_PATH= "$NDMC" -c "interface $VWARD_WAN_INTERFACE up" >/dev/null 2>&1
        UP_RC=$?
        [ "$UP_RC" -eq 0 ] && return 0
        [ "$tries" -ge 3 ] || sleep 2
    done
    return 1
}

cleanup()
{
    if [ "$LOCK_OWNED" = 1 ] && [ "$(cat "$LOCKDIR/pid" 2>/dev/null)" = "$$" ]; then
        rm -rf "$LOCKDIR" 2>/dev/null
    fi
    vward_admission_leave 2>/dev/null || true
}

on_signal()
{
    # A signal while "down" runs is acted on once its result is known.
    if [ "$PHASE" = DOWN_COMMAND ]; then
        CANCEL=1
        return
    fi
    trap '' 1 2 15
    if [ "$PHASE" = OWNED_DOWN ] && run_up; then
        rm -f "$WAN_BOUNCE_MARKER"
        log_action MANUAL_WAN_BOUNCE_INTERRUPTED "up_rc=0"
    fi
    echo "ERROR=INTERRUPTED"
    exit 1
}

lock_is_live()
{
    lpid=$(cat "$LOCKDIR/pid" 2>/dev/null)
    case "$lpid" in ''|*[!0-9]*) return 1 ;; esac
    [ -d "/proc/$lpid" ] || return 1
    grep -Eq "vward-wan-(guard|recovery)[.]sh" "/proc/$lpid/cmdline" 2>/dev/null
}

acquire_lock()
{
    if ! mkdir "$LOCKDIR" 2>/dev/null; then
        lock_is_live && return 1
        rm -rf "$LOCKDIR" 2>/dev/null || return 1
        mkdir "$LOCKDIR" 2>/dev/null || return 1
    fi
    printf '%s\n' "$$" > "$LOCKDIR/pid"
    LOCK_OWNED=1
}

trap cleanup 0
trap on_signal 1 2 15

acquire_lock || { echo "ERROR=BUSY"; exit 75; }
mkdir -p "$REC_DIR" || { echo "ERROR=STATE_UNAVAILABLE"; exit 1; }

# An earlier bounce that never came back up is finished first; nothing else runs.
if [ -f "$WAN_BOUNCE_MARKER" ]; then
    if [ "$(cat "$WAN_BOUNCE_MARKER" 2>/dev/null)" = "$VWARD_WAN_INTERFACE" ] && run_up; then
        rm -f "$WAN_BOUNCE_MARKER"
        log_action MANUAL_BOUNCE_RECOVERY "up_rc=0"
    else
        echo "ERROR=INCOMPLETE_BOUNCE"
        exit 1
    fi
fi

NOW=$(date +%s)
LAST=$(cat "$REC_DIR/last_manual" 2>/dev/null)
case "$LAST" in ''|*[!0-9]*) LAST=0 ;; esac
if [ "$LAST" -gt 0 ] && [ $((NOW - LAST)) -ge 0 ] && [ $((NOW - LAST)) -lt "$MANUAL_COOLDOWN" ]; then
    echo "ERROR=COOLDOWN"
    echo "RETRY_AFTER=$((MANUAL_COOLDOWN - (NOW - LAST)))"
    exit 75
fi
echo "$NOW" > "$REC_DIR/last_manual"

echo "REQUEST=$REQUEST"
echo "INTERFACE=$VWARD_WAN_INTERFACE"

if [ "$REQUEST" = dhcp-renew ]; then
    LD_LIBRARY_PATH= "$NDMC" -c "interface $VWARD_WAN_INTERFACE ip dhcp client renew" >/dev/null 2>&1
    RC=$?
    log_action MANUAL_DHCP_RENEW "rc=$RC"
    [ "$RC" -eq 0 ] && { echo "RESULT=DONE"; exit 0; }
    echo "ERROR=RENEW_FAILED"
    exit 1
fi

PHASE=DOWN_COMMAND
LD_LIBRARY_PATH= "$NDMC" -c "interface $VWARD_WAN_INTERFACE down" >/dev/null 2>&1
DOWN_RC=$?
if [ "$DOWN_RC" -ne 0 ]; then
    PHASE=IDLE
    log_action MANUAL_WAN_BOUNCE "down_rc=$DOWN_RC"
    echo "ERROR=DOWN_FAILED"
    exit 1
fi
PHASE=OWNED_DOWN
printf '%s\n' "$VWARD_WAN_INTERFACE" > "$WAN_BOUNCE_MARKER" || {
    run_up && PHASE=IDLE
    echo "ERROR=MARKER_FAILED"
    exit 1
}
[ "$CANCEL" = 0 ] || on_signal

sleep "$BOUNCE_WAIT"

if run_up; then
    rm -f "$WAN_BOUNCE_MARKER"
    PHASE=IDLE
    log_action MANUAL_WAN_BOUNCE "down_rc=0 up_rc=0"
    echo "RESULT=DONE"
    exit 0
fi
# The marker stays: WAN Guard keeps bringing the interface up every minute.
log_action MANUAL_WAN_BOUNCE "down_rc=0 up_rc=$UP_RC"
echo "ERROR=UP_FAILED"
exit 1
