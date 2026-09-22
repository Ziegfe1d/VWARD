#!/bin/sh
set -u

CONF=${VWARD_WIFI_CLIENT_GUARD_CONF:-/opt/etc/vward/wifi-client-guard.conf}
LOCK=${VWARD_WIFI_CLIENT_GUARD_LOCK:-/tmp/vward-wifi-client-guard.lock}
BIN_DIR=${VWARD_WIFI_CLIENT_GUARD_BIN:-/opt/bin}
ENABLED=0

[ ! -r "$CONF" ] || . "$CONF"
[ "$ENABLED" = 1 ] || exit 0

VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
[ -r "$VWARD_ADMISSION_LIB" ] || { echo "VWARD runtime admission library is unavailable" >&2; exit 1; }
. "$VWARD_ADMISSION_LIB"
vward_admission_enter wifi-client-guard || exit $?

LOCK_OWNED=0
cleanup()
{
    if [ "$LOCK_OWNED" = 1 ]; then
        rm -f "$LOCK/pid" "$LOCK/pid_start"
        rmdir "$LOCK" 2>/dev/null
    fi
    vward_admission_leave 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 73' HUP INT TERM

lock_holder_alive()
{
    owner=$(cat "$LOCK/pid" 2>/dev/null) || return 1
    saved=$(cat "$LOCK/pid_start" 2>/dev/null) || return 1
    [ -n "$saved" ] && [ "$(vward_admission_pid_start "$owner" 2>/dev/null)" = "$saved" ]
}

[ ! -L "$LOCK" ] || { echo "Wi-Fi Client Guard lock is a symlink" >&2; exit 1; }
if ! mkdir "$LOCK" 2>/dev/null; then
    lock_holder_alive && exit 0
    rm -f "$LOCK/pid" "$LOCK/pid_start"
    rmdir "$LOCK" 2>/dev/null
    mkdir "$LOCK" 2>/dev/null || exit 0
fi
LOCK_OWNED=1
printf '%s\n' "$$" > "$LOCK/pid"
vward_admission_pid_start $$ > "$LOCK/pid_start"

"$BIN_DIR/vward-wifi-client-monitor.sh" --once || exit $?
"$BIN_DIR/vward-wifi-client-analyze.sh" --once
