#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

DIR="/opt/etc/adaptive-route"
DEST="$DIR/hints.conf"
LOG="/opt/var/log/adaptive-hints-update.log"

RUS="/tmp/hints-russia.$$"
TG="/tmp/hints-telegram.$$"
NEW="/tmp/hints-new.$$"

mkdir -p "$DIR"

cleanup()
{
    rm -f "$RUS" "$TG" "$NEW"
}
trap cleanup EXIT INT TERM

fetch()
{
    URL="$1"
    OUT="$2"

    curl -4 -f -L \
      --connect-timeout 5 \
      --max-time 30 \
      -sS "$URL" -o "$OUT"
}

normalize()
{
    awk '
    {
        gsub(/\r/,"")
        gsub(/^[ \t]+|[ \t]+$/,"")

        if ($0=="" || substr($0,1,1)=="#")
            next

        d=tolower($0)

        sub(/^\*\./,"",d)
        sub(/^\./,"",d)
        sub(/\.$/,"",d)

        if (d ~ /^[a-z0-9_-]+(\.[a-z0-9_-]+)*$/)
            print d
    }'
}

fetch \
"https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Russia/inside-raw.lst" \
"$RUS" || exit 1

fetch \
"https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Services/telegram.lst" \
"$TG" || exit 1

{
    normalize < "$RUS"
    normalize < "$TG"
} | sort -u > "$NEW"

RCOUNT=$(normalize < "$RUS" | wc -l)
TCOUNT=$(normalize < "$TG" | wc -l)
TOTAL=$(wc -l < "$NEW")

[ "$RCOUNT" -ge 500 ] || exit 2
[ "$TCOUNT" -ge 10 ] || exit 3
[ "$TOTAL" -ge 500 ] || exit 4

cp "$NEW" "$DEST.new" || exit 5
mv "$DEST.new" "$DEST" || exit 6

echo "$(date '+%Y-%m-%d %H:%M:%S')|OK|Russia=$RCOUNT|Telegram=$TCOUNT|Total=$TOTAL" \
>> "$LOG"

echo "Russia=$RCOUNT"
echo "Telegram=$TCOUNT"
echo "Total=$TOTAL"
