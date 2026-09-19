#!/bin/sh
set -u

CONF=${VWARD_WIFI_CLIENT_GUARD_CONF:-/opt/etc/vward/wifi-client-guard.conf}
STATE_DIR=${VWARD_WIFI_CLIENT_GUARD_STATE:-/opt/var/lib/vward/wifi-client-guard}
WINDOW_SEC=86400
BAND_SWITCH_WARN=20
WEAK_5G_SAMPLE_WARN=5
WEAK_5G_RSSI=-75

[ ! -r "$CONF" ] || . "$CONF"

valid_positive()
{
    case "$1" in ''|*[!0-9]*) return 1 ;; esac
    [ "$1" -gt 0 ]
}

case "${1:---once}" in
    --health)
        valid_positive "$WINDOW_SEC" || exit 1
        valid_positive "$BAND_SWITCH_WARN" || exit 1
        valid_positive "$WEAK_5G_SAMPLE_WARN" || exit 1
        exit 0
        ;;
    --once) ;;
    *) echo "usage: $0 [--once|--health]" >&2; exit 2 ;;
esac

valid_positive "$WINDOW_SEC" || exit 2
valid_positive "$BAND_SWITCH_WARN" || exit 2
valid_positive "$WEAK_5G_SAMPLE_WARN" || exit 2
case "$WEAK_5G_RSSI" in -[0-9]*|[0-9]*) ;; *) exit 2 ;; esac

CURRENT="$STATE_DIR/current.tsv"
SAMPLES="$STATE_DIR/samples.tsv"
EVENTS="$STATE_DIR/events.tsv"
OUTPUT="$STATE_DIR/analysis.tsv"
TMP="$OUTPUT.$$"
NOW="$(date +%s)"
MIN=$((NOW - WINDOW_SEC))
TAB="$(printf '\t')"

mkdir -p "$STATE_DIR" || exit 1
: > "$TMP"

if [ ! -r "$CURRENT" ]; then
    mv -f "$TMP" "$OUTPUT"
    exit 0
fi

while IFS="$TAB" read -r epoch mac ap band rssi txrate uptime
do
    [ -n "$mac" ] || continue
    switches=0
    weak5=0
    min5=-
    if [ -r "$EVENTS" ]; then
        switches="$(awk -F '\t' -v min="$MIN" -v m="$mac" '$1+0>=min && tolower($2)==tolower(m) && $3=="BAND_SWITCH"{n++} END{print n+0}' "$EVENTS")"
    fi
    if [ -r "$SAMPLES" ]; then
        weak5="$(awk -F '\t' -v min="$MIN" -v m="$mac" -v limit="$WEAK_5G_RSSI" '$1+0>=min && tolower($2)==tolower(m) && $4=="5" && $5 ~ /^-?[0-9]+$/ && $5+0<=limit{n++} END{print n+0}' "$SAMPLES")"
        min5="$(awk -F '\t' -v min="$MIN" -v m="$mac" '$1+0>=min && tolower($2)==tolower(m) && $4=="5" && $5 ~ /^-?[0-9]+$/{if(!seen || $5+0<best){best=$5+0;seen=1}} END{if(seen)print best;else print "-"}' "$SAMPLES")"
    fi

    health=OK
    recommendation=none
    reason=stable
    if [ "$switches" -ge "$BAND_SWITCH_WARN" ] && [ "$weak5" -ge "$WEAK_5G_SAMPLE_WARN" ]; then
        health=WARNING
        recommendation=bind_2g
        reason=frequent_switches_and_weak_5g
    elif [ "$switches" -ge "$BAND_SWITCH_WARN" ]; then
        health=WARNING
        recommendation=review
        reason=frequent_band_switches
    fi

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$epoch" "$mac" "$band" "$health" "$recommendation" "$reason" "$switches" "$weak5" "$min5" >> "$TMP"
done < "$CURRENT"

mv -f "$TMP" "$OUTPUT"
cat "$OUTPUT"
exit 0
