#!/bin/sh
set -u

CONF=${VWARD_WIFI_CLIENT_GUARD_CONF:-/opt/etc/vward/wifi-client-guard.conf}
STATE_DIR=${VWARD_WIFI_CLIENT_GUARD_STATE:-/opt/var/lib/vward/wifi-client-guard}
LOG=${VWARD_WIFI_CLIENT_GUARD_LOG:-/opt/var/log/vward-wifi-client-guard.log}
ENABLED=0
AP_2G_PATTERN='(^|/)AccessPoint$|WifiMaster0'
AP_5G_PATTERN='AccessPoint_5G|WifiMaster1'
SAMPLE_RETENTION_SEC=172800

[ ! -r "$CONF" ] || . "$CONF"

log()
{
    level=$1
    shift
    printf '%s %s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$level" "$*" >> "$LOG" 2>/dev/null || :
}

valid_positive()
{
    case "$1" in ''|*[!0-9]*) return 1 ;; esac
    [ "$1" -gt 0 ]
}

band_for_ap()
{
    ap=$1
    if [ -n "$AP_5G_PATTERN" ] && printf '%s\n' "$ap" | grep -Eq "$AP_5G_PATTERN"; then
        printf '5\n'
    elif [ -n "$AP_2G_PATTERN" ] && printf '%s\n' "$ap" | grep -Eq "$AP_2G_PATTERN"; then
        printf '2.4\n'
    else
        printf 'unknown\n'
    fi
}

case "${1:---once}" in
    --health)
        command -v ndmc >/dev/null 2>&1 || exit 1
        ndmc -c 'show associations' >/dev/null 2>&1 || exit 1
        exit 0
        ;;
    --once) ;;
    *) echo "usage: $0 [--once|--health]" >&2; exit 2 ;;
esac

[ "$ENABLED" = 1 ] || { log INFO "monitor disabled"; exit 0; }
valid_positive "$SAMPLE_RETENTION_SEC" || { log ERROR "invalid SAMPLE_RETENTION_SEC"; exit 2; }

umask 077
mkdir -p "$STATE_DIR" || exit 1
mkdir -p "$(dirname "$LOG")" 2>/dev/null || :

RAW="$STATE_DIR/associations.raw.$$"
PARSED="$STATE_DIR/associations.parsed.$$"
CURRENT_NEW="$STATE_DIR/current.tsv.$$"
CURRENT="$STATE_DIR/current.tsv"
SAMPLES="$STATE_DIR/samples.tsv"
EVENTS="$STATE_DIR/events.tsv"
NOW="$(date +%s)"
MIN=$((NOW - SAMPLE_RETENTION_SEC))
TAB="$(printf '\t')"

cleanup()
{
    rm -f "$RAW" "$PARSED" "$CURRENT_NEW" "$STATE_DIR/samples.prune.$$" "$STATE_DIR/events.prune.$$"
}
trap cleanup EXIT HUP INT TERM

ndmc -c 'show associations' > "$RAW" 2>&1 || { log ERROR "show associations failed"; exit 1; }

awk '
function trim(s){gsub(/^[[:space:]]+|[[:space:]]+$/,"",s);return s}
function emit(){if(mac!="") print tolower(mac) "\t" ap "\t" txrate "\t" uptime "\t" rssi}
{
    line=$0
    sub(/^[[:space:]]*/,"",line)
    if(line=="station:"){emit();mac="";ap="";txrate="";uptime="";rssi="";next}
    key=line
    sub(/:.*/,"",key)
    key=trim(key)
    val=line
    sub(/^[^:]*:[[:space:]]*/,"",val)
    val=trim(val)
    if(key=="mac") mac=val
    else if(key=="ap") ap=val
    else if(key=="txrate") txrate=val
    else if(key=="uptime") uptime=val
    else if(key=="rssi") rssi=val
}
END{emit()}
' "$RAW" > "$PARSED" || exit 1

: > "$CURRENT_NEW"
while IFS="$TAB" read -r mac ap txrate uptime rssi
do
    [ -n "$mac" ] || continue
    band="$(band_for_ap "$ap")"
    [ -n "$rssi" ] || rssi=-
    [ -n "$txrate" ] || txrate=-
    [ -n "$uptime" ] || uptime=-
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$NOW" "$mac" "$ap" "$band" "$rssi" "$txrate" "$uptime" >> "$CURRENT_NEW"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$NOW" "$mac" "$ap" "$band" "$rssi" "$txrate" "$uptime" >> "$SAMPLES"

    prev_band=
    if [ -r "$CURRENT" ]; then
        prev_band="$(awk -F '\t' -v m="$mac" 'tolower($2)==tolower(m){print $4;exit}' "$CURRENT" 2>/dev/null)"
    fi
    if [ -n "$prev_band" ] && [ "$prev_band" != unknown ] && [ "$band" != unknown ] && [ "$prev_band" != "$band" ]; then
        printf '%s\t%s\tBAND_SWITCH\t%s\t%s\t%s\t%s\n' "$NOW" "$mac" "$prev_band" "$band" "$ap" "$rssi" >> "$EVENTS"
        log INFO "band switch mac=$mac from=$prev_band to=$band ap=$ap rssi=$rssi"
    fi
done < "$PARSED"

mv -f "$CURRENT_NEW" "$CURRENT" || exit 1

if [ -r "$SAMPLES" ]; then
    awk -F '\t' -v min="$MIN" '$1 ~ /^[0-9]+$/ && $1+0 >= min {print}' "$SAMPLES" > "$STATE_DIR/samples.prune.$$" &&
        mv -f "$STATE_DIR/samples.prune.$$" "$SAMPLES"
fi
if [ -r "$EVENTS" ]; then
    awk -F '\t' -v min="$MIN" '$1 ~ /^[0-9]+$/ && $1+0 >= min {print}' "$EVENTS" > "$STATE_DIR/events.prune.$$" &&
        mv -f "$STATE_DIR/events.prune.$$" "$EVENTS"
fi

count="$(wc -l < "$CURRENT" | tr -d ' ')"
log INFO "snapshot clients=$count"
exit 0
