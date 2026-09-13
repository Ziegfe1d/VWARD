#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

VERSION="3.0"

DIR="/opt/etc/adaptive-route"
STATE="/opt/var/lib/adaptive-hints"
CACHE="$STATE/sources"
DEST="$DIR/hints.conf"
CATALOG="$DIR/hints-catalog.tsv"
INCLUDES="$DIR/hints-includes.tsv"
LOG="/opt/var/log/adaptive-hints-update.log"

WORK="/tmp/adaptive-hints.$$"
ITDOG_ARCH="$WORK/itdog.tar.gz"
V2_ARCH="$WORK/v2fly.tar.gz"

mkdir -p "$DIR" "$CACHE" "$WORK"

cleanup()
{
    rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

fetch()
{
    URL="$1"
    OUT="$2"

    curl -4 -f -L \
      --connect-timeout 10 \
      --max-time 90 \
      -sS "$URL" -o "$OUT"
}

extract_archive()
{
    ARCH="$1"
    OUTDIR="$2"

    mkdir -p "$OUTDIR"
    tar -xzf "$ARCH" -C "$OUTDIR" >/dev/null 2>&1
}

category_name()
{
    basename "$1" |
    sed 's/\.[^.]*$//' |
    tr '[:upper:]' '[:lower:]'
}

normalize_domains()
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

update_itdog()
{
    TMP="$WORK/itdog.tsv"

    if ! fetch \
      "https://codeload.github.com/itdoginfo/allow-domains/tar.gz/refs/heads/main" \
      "$ITDOG_ARCH"; then
        echo "SOURCE_ITDOG=UNAVAILABLE"
        return 1
    fi

    if ! extract_archive "$ITDOG_ARCH" "$WORK/itdog"; then
        echo "SOURCE_ITDOG=EXTRACT_FAILED"
        return 1
    fi

    : > "$TMP"
    COUNT_FILES=0

    find "$WORK/itdog" -type f -name '*.lst' 2>/dev/null |
    while IFS= read -r FILE; do
        case "$FILE" in
            */Subnets/*) continue ;;
        esac

        CAT="$(category_name "$FILE")"
        [ -n "$CAT" ] || continue

        normalize_domains < "$FILE" |
        awk -v s="itdog" -v c="$CAT" '
            NF { print $0 "|" s "|" c }
        ' >> "$TMP"
    done

    sort -u "$TMP" > "$TMP.sorted"
    mv "$TMP.sorted" "$TMP"
    COUNT="$(wc -l < "$TMP" 2>/dev/null)"
    [ -n "$COUNT" ] || COUNT=0

    if [ "$COUNT" -lt 100 ]; then
        echo "SOURCE_ITDOG=BAD_COUNT:$COUNT"
        return 1
    fi

    cp "$TMP" "$CACHE/itdog.tsv.new" || return 1
    mv "$CACHE/itdog.tsv.new" "$CACHE/itdog.tsv" || return 1

    echo "SOURCE_ITDOG=OK:$COUNT"
    return 0
}

update_v2fly()
{
    TMP="$WORK/v2fly.tsv"
    INC="$WORK/v2fly-includes.tsv"

    if ! fetch \
      "https://codeload.github.com/v2fly/domain-list-community/tar.gz/refs/heads/master" \
      "$V2_ARCH"; then
        echo "SOURCE_V2FLY=UNAVAILABLE"
        return 1
    fi

    if ! extract_archive "$V2_ARCH" "$WORK/v2fly"; then
        echo "SOURCE_V2FLY=EXTRACT_FAILED"
        return 1
    fi

    DATA=""
    for ROOT in "$WORK"/v2fly/*; do
        [ -d "$ROOT/data" ] || continue
        DATA="$ROOT/data"
        break
    done

    [ -n "$DATA" ] || {
        echo "SOURCE_V2FLY=NO_DATA"
        return 1
    }

    : > "$TMP"
    : > "$INC"

    for FILE in "$DATA"/*; do
        [ -f "$FILE" ] || continue

        CAT="$(category_name "$FILE")"
        [ -n "$CAT" ] || continue

        normalize_domains < "$FILE" |
        awk -v s="v2fly" -v c="$CAT" '
            NF { print $0 "|" s "|" c }
        ' >> "$TMP"

        awk -v p="$CAT" '
        {
            gsub(/\r/,"")
            gsub(/^[ \t]+|[ \t]+$/,"")

            if (tolower($0) ~ /^include:/) {
                x=tolower($0)
                sub(/^include:/,"",x)
                split(x,a,/[ \t]+/)
                if (a[1] ~ /^[a-z0-9_.-]+$/)
                    print "v2fly|" p "|" a[1]
            }
        }' "$FILE" >> "$INC"
    done

    sort -u "$TMP" > "$TMP.sorted"
    mv "$TMP.sorted" "$TMP"
    sort -u "$INC" > "$INC.sorted"
    mv "$INC.sorted" "$INC"

    COUNT="$(wc -l < "$TMP" 2>/dev/null)"
    CATS="$(awk -F'|' '{print $3}' "$TMP" | sort -u | wc -l)"
    [ -n "$COUNT" ] || COUNT=0
    [ -n "$CATS" ] || CATS=0

    if [ "$COUNT" -lt 1000 ] || [ "$CATS" -lt 100 ]; then
        echo "SOURCE_V2FLY=BAD_COUNT:domains=$COUNT categories=$CATS"
        return 1
    fi

    cp "$TMP" "$CACHE/v2fly.tsv.new" || return 1
    mv "$CACHE/v2fly.tsv.new" "$CACHE/v2fly.tsv" || return 1

    cp "$INC" "$CACHE/v2fly-includes.tsv.new" || return 1
    mv "$CACHE/v2fly-includes.tsv.new" "$CACHE/v2fly-includes.tsv" || return 1

    echo "SOURCE_V2FLY=OK:domains=$COUNT categories=$CATS"
    return 0
}

update_itdog || true
update_v2fly || true

MERGED="$WORK/merged.tsv"
INC_MERGED="$WORK/includes.tsv"

: > "$MERGED"
: > "$INC_MERGED"

for FILE in "$CACHE/itdog.tsv" "$CACHE/v2fly.tsv"; do
    [ -s "$FILE" ] || continue
    cat "$FILE" >> "$MERGED"
done

[ -s "$CACHE/v2fly-includes.tsv" ] &&
    cat "$CACHE/v2fly-includes.tsv" >> "$INC_MERGED"

sort -u "$MERGED" > "$MERGED.sorted"
mv "$MERGED.sorted" "$MERGED"

sort -u "$INC_MERGED" > "$INC_MERGED.sorted"
mv "$INC_MERGED.sorted" "$INC_MERGED"

TOTAL_ROWS="$(wc -l < "$MERGED" 2>/dev/null)"
TOTAL_DOMAINS="$(cut -d'|' -f1 "$MERGED" | sort -u | wc -l)"
TOTAL_CATS="$(cut -d'|' -f3 "$MERGED" | sort -u | wc -l)"
[ -n "$TOTAL_ROWS" ] || TOTAL_ROWS=0
[ -n "$TOTAL_DOMAINS" ] || TOTAL_DOMAINS=0
[ -n "$TOTAL_CATS" ] || TOTAL_CATS=0

if [ "$TOTAL_DOMAINS" -lt 1000 ]; then
    echo "ERROR=NO_HEALTHY_DOMAIN_CATALOG"
    exit 4
fi

cut -d'|' -f1 "$MERGED" | sort -u > "$WORK/hints.conf"

cp "$MERGED" "$CATALOG.new" || exit 5
mv "$CATALOG.new" "$CATALOG" || exit 6

cp "$INC_MERGED" "$INCLUDES.new" || exit 7
mv "$INCLUDES.new" "$INCLUDES" || exit 8

cp "$WORK/hints.conf" "$DEST.new" || exit 9
mv "$DEST.new" "$DEST" || exit 10

echo "$(date '+%Y-%m-%d %H:%M:%S')|OK|version=$VERSION|rows=$TOTAL_ROWS|domains=$TOTAL_DOMAINS|categories=$TOTAL_CATS" \
>> "$LOG"

echo "HINTS_UPDATE_VERSION=$VERSION"
echo "DOMAIN_ROWS=$TOTAL_ROWS"
echo "UNIQUE_DOMAINS=$TOTAL_DOMAINS"
echo "CATEGORIES=$TOTAL_CATS"
echo "MODE=DYNAMIC_ALL_LISTS"
