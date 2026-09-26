#!/bin/sh
set -u

CONF=${VWARD_WIFI_CLIENT_GUARD_CONF:-/opt/etc/vward/wifi-client-guard.conf}
LOG=${VWARD_WIFI_CLIENT_GUARD_LOG:-/opt/var/log/vward-wifi-client-guard.log}
BACKUP_DIR=${VWARD_WIFI_CLIENT_GUARD_BACKUP:-/opt/var/backups/vward/wifi-client-guard}
CONTROL_ENABLED=0
AUTO_APPLY=0
HOME_BRIDGE=

[ ! -r "$CONF" ] || . "$CONF"

log()
{
    level=$1
    shift
    printf '%s %s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$level" "$*" >> "$LOG" 2>/dev/null || :
}

die()
{
    code=$1
    shift
    echo "$*" >&2
    log ERROR "$*"
    exit "$code"
}

valid_mac()
{
    printf '%s\n' "$1" | grep -Eiq '^([0-9a-f]{2}:){5}[0-9a-f]{2}$'
}

valid_bridge()
{
    case "$1" in ''|*[!A-Za-z0-9_.-]*) return 1 ;; *) return 0 ;; esac
}

ACTION=${1:-}
MAC="$(printf '%s' "${2:-}" | tr 'A-F' 'a-f')"
CONFIRM=${3:-}

case "$ACTION" in
    status)
        valid_mac "$MAC" || die 2 "invalid MAC"
        CFG="$(ndmc -c 'show running-config' 2>/dev/null)" || die 1 "running-config unavailable"
        RULE="$(printf '%s\n' "$CFG" | grep -Ei "mac band $MAC [01]" | sed -n '1p')"
        [ -n "$RULE" ] && printf '%s\n' "$RULE" || echo "AUTO"
        exit 0
        ;;
    bind-2g) BAND=0; REQUIRED=WIFI_BIND_2G ;;
    bind-5g) BAND=1; REQUIRED=WIFI_BIND_5G ;;
    auto) BAND=auto; REQUIRED=WIFI_BAND_AUTO ;;
    *) echo "usage: $0 {status|bind-2g|bind-5g|auto} MAC [confirmation]" >&2; exit 2 ;;
esac

[ "$CONTROL_ENABLED" = 1 ] || die 20 "control disabled"
[ "$AUTO_APPLY" = 0 ] || die 21 "AUTO_APPLY is reserved and must remain 0 in this dev stage"
valid_mac "$MAC" || die 2 "invalid MAC"
if [ -z "$HOME_BRIDGE" ]; then
    VWARD_PROFILE_LIB=${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}
    [ -r "$VWARD_PROFILE_LIB" ] || die 2 "device profile library is unavailable"
    . "$VWARD_PROFILE_LIB"
    vward_profile_load >/dev/null 2>&1 || :
    HOME_BRIDGE=${VWARD_LAN_INTERFACE:-}
    [ -n "$HOME_BRIDGE" ] || HOME_BRIDGE=$(vward_discover_lan_interface 2>/dev/null)
fi
valid_bridge "$HOME_BRIDGE" || die 2 "home bridge is missing or ambiguous; set HOME_BRIDGE"
[ "$CONFIRM" = "$REQUIRED" ] || die 22 "confirmation required"

VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
[ -r "$VWARD_ADMISSION_LIB" ] || die 1 "runtime admission library is unavailable"
. "$VWARD_ADMISSION_LIB"
vward_component_gate wifi-client-guard 69
cleanup() { vward_admission_leave 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 73' HUP INT TERM
vward_admission_enter wifi-client-control || die 75 "update in progress; Wi-Fi control deferred"

CFG="$(ndmc -c 'show running-config' 2>/dev/null)" || die 1 "running-config unavailable"
printf '%s\n' "$CFG" | grep -Eiq "known host .* $MAC$|host $MAC permit" || die 23 "MAC is not a registered host"

PREV_BAND="$(printf '%s\n' "$CFG" | grep -Ei "mac band $MAC [01]" | sed -n '1s/.*mac band [^ ]* \([01]\).*/\1/p')"

umask 077
mkdir -p "$BACKUP_DIR" || die 1 "backup directory unavailable"
STAMP="$(date '+%Y%m%d-%H%M%S')"
BACKUP="$BACKUP_DIR/running-config-before-$MAC-$STAMP.txt"
printf '%s\n' "$CFG" > "$BACKUP" || die 1 "backup write failed"
log INFO "backup=$BACKUP action=$ACTION mac=$MAC"

apply_previous()
{
    if [ "$PREV_BAND" = 0 ] || [ "$PREV_BAND" = 1 ]; then
        ndmc -c "interface $HOME_BRIDGE mac band $MAC $PREV_BAND" >/dev/null 2>&1 || return 1
    else
        ndmc -c "no interface $HOME_BRIDGE mac band $MAC" >/dev/null 2>&1 || return 1
    fi
    ndmc -c 'system configuration save' >/dev/null 2>&1
}

if [ "$BAND" = auto ]; then
    ndmc -c "no interface $HOME_BRIDGE mac band $MAC" || die 1 "failed to remove band rule"
else
    ndmc -c "interface $HOME_BRIDGE mac band $MAC $BAND" || die 1 "failed to apply band rule"
fi

if ! ndmc -c 'system configuration save'; then
    apply_previous || :
    die 1 "configuration save failed; rollback attempted"
fi

AFTER="$(ndmc -c 'show running-config' 2>/dev/null)" || {
    apply_previous || :
    die 1 "acceptance read failed; rollback attempted"
}

if [ "$BAND" = auto ]; then
    if printf '%s\n' "$AFTER" | grep -Eiq "mac band $MAC [01]"; then
        apply_previous || :
        die 1 "acceptance failed; rollback attempted"
    fi
else
    if ! printf '%s\n' "$AFTER" | grep -Fiq "mac band $MAC $BAND"; then
        apply_previous || :
        die 1 "acceptance failed; rollback attempted"
    fi
fi

log INFO "control PASS action=$ACTION mac=$MAC bridge=$HOME_BRIDGE backup=$BACKUP"
echo "PASS action=$ACTION mac=$MAC bridge=$HOME_BRIDGE backup=$BACKUP"
exit 0
