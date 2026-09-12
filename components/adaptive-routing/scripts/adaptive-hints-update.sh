#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

VERSION="2.0"

DIR="/opt/etc/adaptive-route"
DEST="$DIR/hints.conf"
LOG="/opt/var/log/adaptive-hints-update.log"

RUS="/tmp/hints-russia.$$"
TG="/tmp/hints-telegram.$$"
NEW="/tmp/hints-new.$$"
V2DIR="/tmp/hints-v2fly.$$"

mkdir -p "$DIR" "$V2DIR"

cleanup()
{
    rm -f "$RUS" "$TG" "$NEW"
    rm -rf "$V2DIR"
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

normalize_v2fly()
{
    awk '
    {
        gsub(/\r/,"")
        gsub(/^[ \t]+|[ \t]+$/,"")

        if ($0=="" || substr($0,1,1)=="#")
            next

        split($0,a,/[ \t]+/)
        d=tolower(a[1])

        if (d ~ /^include:/ ||
            d ~ /^keyword:/ ||
            d ~ /^regexp:/)
            next

        sub(/^domain:/,"",d)
        sub(/^full:/,"",d)
        sub(/^\*\./,"",d)
        sub(/^\./,"",d)
        sub(/\.$/,"",d)

        if (d ~ /^[a-z0-9_-]+(\.[a-z0-9_-]+)*$/)
            print d
    }'
}

fetch_v2fly()
{
    NAME="$1"
    OUT="$V2DIR/$NAME.raw"
    URL="https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/$NAME"

    if fetch "$URL" "$OUT"; then
        COUNT=$(normalize_v2fly < "$OUT" | wc -l)
        echo "V2FLY_$NAME=$COUNT"
        return 0
    fi

    rm -f "$OUT"
    echo "WARN_V2FLY_$NAME=DOWNLOAD_FAILED"
    return 0
}

fetch \
"https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Russia/inside-raw.lst" \
"$RUS" || exit 1

fetch \
"https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Services/telegram.lst" \
"$TG" || exit 1

for NAME in \
    tiktok \
    telegram \
    twitter \
    facebook \
    instagram \
    discord
do
    fetch_v2fly "$NAME"
done

{
    normalize < "$RUS"
    normalize < "$TG"

    for FILE in "$V2DIR"/*.raw; do
        [ -f "$FILE" ] || continue
        normalize_v2fly < "$FILE"
    done
} | sort -u > "$NEW"

RCOUNT=$(normalize < "$RUS" | wc -l)
TCOUNT=$(normalize < "$TG" | wc -l)
V2COUNT=$(
    {
        for FILE in "$V2DIR"/*.raw; do
            [ -f "$FILE" ] || continue
            normalize_v2fly < "$FILE"
        done
    } | sort -u | wc -l
)
TOTAL=$(wc -l < "$NEW")

[ "$RCOUNT" -ge 500 ] || exit 2
[ "$TCOUNT" -ge 10 ] || exit 3
[ "$TOTAL" -ge 500 ] || exit 4

cp "$NEW" "$DEST.new" || exit 5
mv "$DEST.new" "$DEST" || exit 6

echo "$(date '+%Y-%m-%d %H:%M:%S')|OK|version=$VERSION|itdog_russia=$RCOUNT|itdog_telegram=$TCOUNT|v2fly=$V2COUNT|total=$TOTAL" \
>> "$LOG"

echo "HINTS_UPDATE_VERSION=$VERSION"
echo "ITDOG_RUSSIA=$RCOUNT"
echo "ITDOG_TELEGRAM=$TCOUNT"
echo "V2FLY_TOTAL=$V2COUNT"
echo "TOTAL=$TOTAL"
