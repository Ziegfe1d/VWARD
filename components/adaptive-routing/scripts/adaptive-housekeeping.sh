#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

MAX_BYTES=2097152
KEEP=3

HOUSE_LOG="/opt/var/log/adaptive-housekeeping.log"

LOGS="
/opt/var/log/adaptive-live-events.log
/opt/var/log/agh-adaptive-live.log
/opt/var/log/wg-health.log
/opt/var/log/wg-failopen.log
/opt/var/log/vpn-audit.log
/opt/var/log/vpn-audit-summary.log
/opt/var/log/vpn-night-reconcile.log
/opt/var/log/adaptive-hints-update.log
/opt/var/log/crond.log
/opt/var/log/crond-supervisor.log
"

if [ "$1" = "--test" ]; then
    MAX_BYTES=1024
    KEEP=3
    LOGS="/tmp/adaptive-housekeeping-test.log"
fi


rotate_file()
{
    F="$1"

    [ -f "$F" ] || return 0

    SIZE=$(wc -c < "$F" 2>/dev/null)

    case "$SIZE" in
        ''|*[!0-9]*)
            return 1
            ;;
    esac

    [ "$SIZE" -lt "$MAX_BYTES" ] && return 0

    rm -f "$F.$KEEP"

    I=$((KEEP - 1))

    while [ "$I" -ge 1 ]; do
        if [ -f "$F.$I" ]; then
            J=$((I + 1))
            mv "$F.$I" "$F.$J"
        fi

        I=$((I - 1))
    done

    # copytruncate:
    # безопасно для Live/crond, которые могут держать лог открытым.
    cp "$F" "$F.1.tmp.$$" || return 1
    mv "$F.1.tmp.$$" "$F.1" || return 1

    : > "$F" || return 1

    echo "ROTATED|$F|$SIZE"
    return 0
}


ROTATED=0
ERRORS=0

for F in $LOGS; do

    BEFORE=0

    if [ -f "$F" ]; then
        BEFORE=$(wc -c < "$F" 2>/dev/null)
    fi

    OUT=$(rotate_file "$F")
    RC=$?

    if [ "$RC" -ne 0 ]; then
        ERRORS=$((ERRORS + 1))
        continue
    fi

    if [ -n "$OUT" ]; then
        echo "$OUT"
        ROTATED=$((ROTATED + 1))
    fi
done


if [ "$1" != "--test" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S')|rotated=$ROTATED|errors=$ERRORS" \
        >> "$HOUSE_LOG"
fi

echo "Rotated=$ROTATED Errors=$ERRORS"

[ "$ERRORS" -eq 0 ]
