#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

HOST="$1"

DNS1="${ADAPTIVE_DNS1:-9.9.9.10}"
DNS2="${ADAPTIVE_DNS2:-149.112.112.10}"

[ -n "$HOST" ] || exit 1


has_ipv4_answer()
{
    awk '
        /^Name:/ {
            answer=1
            next
        }

        answer &&
        /^Address [0-9]+:/ &&
        $3 ~ /^[0-9]+\./ {
            found=1
        }

        END {
            exit found ? 0 : 1
        }
    '
}


try_dns()
{
    SERVER="$1"

    OUT=$(nslookup "$HOST" "$SERVER" 2>/dev/null)

    if printf '%s\n' "$OUT" | has_ipv4_answer; then
        printf '%s\n' "$OUT"
        return 0
    fi

    return 1
}


try_dns "$DNS1" && exit 0
try_dns "$DNS2" && exit 0

exit 1
