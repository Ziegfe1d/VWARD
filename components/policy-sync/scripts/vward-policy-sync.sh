#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

VERSION="2.0"
WG="nwg1"
MODE="${1:-sync}"

STATE="/opt/var/lib/vward/policy-sync"
SOURCE_ROOT="$STATE/source-catalog"
ITDOG_SRC="$SOURCE_ROOT/itdog"
LOYAL_SRC="$SOURCE_ROOT/loyalsoldier"
CATALOG="$STATE/catalog"
INDEX="$STATE/catalog.index"
OWNED="$STATE/owned.dynamic.routes"
ACTIVE="$STATE/active.categories"
LOCK="$STATE/lock"

HINT_CATALOG="/opt/etc/vward/route-engine/hints-catalog.tsv"
HINT_INCLUDES="/opt/etc/vward/route-engine/hints-includes.tsv"

LOG="/opt/var/log/vward-policy-sync-sync.log"
WORK="$STATE/work.$$"

ITDOG_ARCH="$WORK/itdog.tar.gz"
LOYAL_JSON="$WORK/loyal.json"

MAX_CATEGORY_ROUTES=2000

mkdir -p "$STATE" "$SOURCE_ROOT"

if ! mkdir "$LOCK" 2>/dev/null; then
    echo "SUBNET_SYNC=ALREADY_RUNNING"
    exit 0
fi

mkdir -p "$WORK"

cleanup()
{
    rm -rf "$WORK" "$LOCK"
}
trap cleanup EXIT INT TERM

touch "$OWNED"

log()
{
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"
}

download()
{
    URL="$1"
    OUT="$2"

    curl -4 -f -L \
      --connect-timeout 10 \
      --max-time 120 \
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
    tr '[:upper:]' '[:lower:]' |
    sed 's/[^a-z0-9._-]/-/g'
}

normalize_ipv4()
{
    awk '
    function valid(ip, p, a, n) {
        n=split(ip,a,".")
        if (n != 4) return 0

        for (i=1;i<=4;i++) {
            if (a[i] !~ /^[0-9]+$/) return 0
            if (a[i] < 0 || a[i] > 255) return 0
        }

        if (p < 1 || p > 32) return 0

        if (a[1] == 0) return 0
        if (a[1] == 10) return 0
        if (a[1] == 127) return 0
        if (a[1] >= 224) return 0

        if (a[1] == 100 && a[2] >= 64 && a[2] <= 127) return 0
        if (a[1] == 169 && a[2] == 254) return 0
        if (a[1] == 172 && a[2] >= 16 && a[2] <= 31) return 0
        if (a[1] == 192 && a[2] == 168) return 0

        return 1
    }

    {
        gsub(/\r/,"")
        sub(/#.*/,"")
        gsub(/^[ \t]+|[ \t]+$/,"")

        if ($0 == "") next

        n=split($0,b,"/")
        if (n != 2) next

        ip=b[1]
        p=b[2]+0

        if (valid(ip,p))
            print ip "/" p
    }' | sort -u
}

prefix_mask()
{
    case "$1" in
        1)  echo 128.0.0.0 ;;
        2)  echo 192.0.0.0 ;;
        3)  echo 224.0.0.0 ;;
        4)  echo 240.0.0.0 ;;
        5)  echo 248.0.0.0 ;;
        6)  echo 252.0.0.0 ;;
        7)  echo 254.0.0.0 ;;
        8)  echo 255.0.0.0 ;;
        9)  echo 255.128.0.0 ;;
        10) echo 255.192.0.0 ;;
        11) echo 255.224.0.0 ;;
        12) echo 255.240.0.0 ;;
        13) echo 255.248.0.0 ;;
        14) echo 255.252.0.0 ;;
        15) echo 255.254.0.0 ;;
        16) echo 255.255.0.0 ;;
        17) echo 255.255.128.0 ;;
        18) echo 255.255.192.0 ;;
        19) echo 255.255.224.0 ;;
        20) echo 255.255.240.0 ;;
        21) echo 255.255.248.0 ;;
        22) echo 255.255.252.0 ;;
        23) echo 255.255.254.0 ;;
        24) echo 255.255.255.0 ;;
        25) echo 255.255.255.128 ;;
        26) echo 255.255.255.192 ;;
        27) echo 255.255.255.224 ;;
        28) echo 255.255.255.240 ;;
        29) echo 255.255.255.248 ;;
        30) echo 255.255.255.252 ;;
        31) echo 255.255.255.254 ;;
        32) echo 255.255.255.255 ;;
        *) return 1 ;;
    esac
}

ndm()
{
    CMD="$1"

    OUT="$(ndmc -c "$CMD" 2>&1)"
    RC=$?

    if [ "$RC" -ne 0 ]; then
        log "NDM_FAIL rc=$RC cmd=$CMD result=$OUT"
        return 1
    fi

    echo "$OUT" |
    grep -Eqi 'error\[|syntax error|not found|no such entry' && {
        log "NDM_FAIL cmd=$CMD result=$OUT"
        return 1
    }

    return 0
}

replace_source_dir()
{
    NEW="$1"
    DEST="$2"

    OLD="${DEST}.old.$$"
    rm -rf "$OLD"

    if [ -d "$DEST" ]; then
        mv "$DEST" "$OLD" || return 1
    fi

    if mv "$NEW" "$DEST"; then
        rm -rf "$OLD"
        return 0
    fi

    [ -d "$OLD" ] && mv "$OLD" "$DEST"
    return 1
}

update_itdog_catalog()
{
    NEW="$WORK/itdog-source"
    EX="$WORK/itdog-extract"

    mkdir -p "$NEW"

    if ! download \
      "https://codeload.github.com/itdoginfo/allow-domains/tar.gz/refs/heads/main" \
      "$ITDOG_ARCH"; then
        echo "SOURCE_ITDOG=UNAVAILABLE"
        return 1
    fi

    if ! extract_archive "$ITDOG_ARCH" "$EX"; then
        echo "SOURCE_ITDOG=EXTRACT_FAILED"
        return 1
    fi

    FILES=0

    find "$EX" -type f -path '*/Subnets/IPv4/*.lst' 2>/dev/null |
    while IFS= read -r FILE; do
        CAT="$(category_name "$FILE")"
        [ -n "$CAT" ] || continue

        normalize_ipv4 < "$FILE" > "$NEW/$CAT.cidr"
        COUNT="$(wc -l < "$NEW/$CAT.cidr" 2>/dev/null)"
        [ -n "$COUNT" ] || COUNT=0

        if [ "$COUNT" -eq 0 ]; then
            rm -f "$NEW/$CAT.cidr"
        fi
    done

    FILES="$(find "$NEW" -type f -name '*.cidr' 2>/dev/null | wc -l)"
    [ -n "$FILES" ] || FILES=0

    if [ "$FILES" -lt 1 ]; then
        echo "SOURCE_ITDOG=NO_IPV4_LISTS"
        return 1
    fi

    replace_source_dir "$NEW" "$ITDOG_SRC" || return 1
    echo "SOURCE_ITDOG=OK:categories=$FILES"
    return 0
}

update_loyal_catalog()
{
    NEW="$WORK/loyal-source"
    LIST="$WORK/loyal-files.tsv"

    mkdir -p "$NEW"

    if ! download \
      "https://api.github.com/repos/Loyalsoldier/geoip/contents/text?ref=release" \
      "$LOYAL_JSON"; then
        echo "SOURCE_LOYALSOLDIER=UNAVAILABLE"
        return 1
    fi

    tr -d '\r\n' < "$LOYAL_JSON" |
    sed 's/},[[:space:]]*{/}\\
{/g' |
    sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\.txt\)".*"download_url"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1|\2/p' |
    sort -u > "$LIST"

    DISCOVERED=0
    DOWNLOADED=0

    while IFS='|' read -r NAME URL; do
        [ -n "$NAME" ] || continue
        [ -n "$URL" ] || continue

        CAT="$(category_name "$NAME")"

        # Двухбуквенные имена в этом источнике являются GeoIP стран/территорий.
        # Они доступны у источника, но не превращаются автоматически в VPN-маршрут.
        echo "$CAT" | grep -Eq '^[a-z][a-z]$' && continue

        DISCOVERED=$((DISCOVERED + 1))

        RAW="$WORK/loyal-$CAT.raw"

        if ! download "$URL" "$RAW"; then
            log "WARN loyal category download failed category=$CAT"
            continue
        fi

        normalize_ipv4 < "$RAW" > "$NEW/$CAT.cidr"
        COUNT="$(wc -l < "$NEW/$CAT.cidr" 2>/dev/null)"
        [ -n "$COUNT" ] || COUNT=0

        if [ "$COUNT" -eq 0 ]; then
            rm -f "$NEW/$CAT.cidr"
            continue
        fi

        DOWNLOADED=$((DOWNLOADED + 1))
    done < "$LIST"

    if [ "$DISCOVERED" -lt 1 ] || [ "$DOWNLOADED" -lt 1 ]; then
        echo "SOURCE_LOYALSOLDIER=NO_SERVICE_LISTS"
        return 1
    fi

    replace_source_dir "$NEW" "$LOYAL_SRC" || return 1
    echo "SOURCE_LOYALSOLDIER=OK:discovered=$DISCOVERED downloaded=$DOWNLOADED"
    return 0
}

build_catalog()
{
    NEW="$WORK/catalog-new"
    IDX="$WORK/catalog.index"

    mkdir -p "$NEW"
    : > "$IDX"

    for FILE in "$ITDOG_SRC"/*.cidr "$LOYAL_SRC"/*.cidr; do
        [ -f "$FILE" ] || continue

        CAT="$(category_name "$FILE")"
        [ -n "$CAT" ] || continue

        cat "$FILE" >> "$NEW/$CAT.tmp"
    done

    for FILE in "$NEW"/*.tmp; do
        [ -f "$FILE" ] || continue

        CAT="$(category_name "$FILE")"

        sort -u "$FILE" > "$NEW/$CAT.cidr"
        rm -f "$FILE"

        COUNT="$(wc -l < "$NEW/$CAT.cidr" 2>/dev/null)"
        [ -n "$COUNT" ] || COUNT=0

        printf '%s|%s\n' "$CAT" "$COUNT" >> "$IDX"
    done

    CATS="$(wc -l < "$IDX" 2>/dev/null)"
    [ -n "$CATS" ] || CATS=0

    if [ "$CATS" -lt 1 ]; then
        echo "ERROR=EMPTY_IP_CATALOG"
        return 1
    fi

    OLD="${CATALOG}.old.$$"
    rm -rf "$OLD"

    [ -d "$CATALOG" ] && mv "$CATALOG" "$OLD"

    if ! mv "$NEW" "$CATALOG"; then
        [ -d "$OLD" ] && mv "$OLD" "$CATALOG"
        return 1
    fi

    rm -rf "$OLD"

    cp "$IDX" "$INDEX.new" || return 1
    mv "$INDEX.new" "$INDEX" || return 1

    echo "IP_CATALOG_CATEGORIES=$CATS"
    return 0
}

collect_vpn_domains()
{
    RUN="$1"
    GROUPS="$WORK/vpn-groups"
    DOMAINS="$WORK/policy-domains"

    awk -v wg="$WG" '
        $1=="route" &&
        $2=="object-group" &&
        $4==wg {
            print $3
        }
    ' "$RUN" | sort -u > "$GROUPS"

    awk '
        NR==FNR {
            vpn[$1]=1
            next
        }

        /^object-group fqdn / {
            g=$3
            next
        }

        /^!/ {
            g=""
            next
        }

        g!="" && vpn[g] && $1=="include" {
            print tolower($2)
        }
    ' "$GROUPS" "$RUN" | sort -u > "$DOMAINS"

    cat "$DOMAINS"
}

collect_categories()
{
    DOMAINS="$1"
    OUT="$2"

    SUFFIX="$WORK/domain-suffixes"
    DIRECT="$WORK/direct-categories"
    EXPANDED="$WORK/expanded-categories"
    NEXT="$WORK/expanded-next"

    awk '
    {
        h=tolower($0)

        while (h!="") {
            print h

            p=index(h,".")
            if (p==0)
                break

            h=substr(h,p+1)
        }
    }' "$DOMAINS" | sort -u > "$SUFFIX"

    awk -F'|' '
        NR==FNR {
            wanted[$1]=1
            next
        }

        ($1 in wanted) {
            print $2 "|" $3
        }
    ' "$SUFFIX" "$HINT_CATALOG" | sort -u > "$DIRECT"

    cp "$DIRECT" "$EXPANDED"

    if [ -s "$HINT_INCLUDES" ]; then
        N=0

        while [ "$N" -lt 32 ]; do
            OLD_COUNT="$(wc -l < "$EXPANDED")"

            awk -F'|' '
                BEGIN { OFS="|" }

                NR==FNR {
                    have[$1 "|" $2]=1
                    next
                }

                (($1 "|" $3) in have) {
                    print $1,$2
                }
            ' "$EXPANDED" "$HINT_INCLUDES" >> "$EXPANDED"

            sort -u "$EXPANDED" > "$NEXT"
            mv "$NEXT" "$EXPANDED"

            NEW_COUNT="$(wc -l < "$EXPANDED")"
            [ "$NEW_COUNT" -eq "$OLD_COUNT" ] && break

            N=$((N + 1))
        done
    fi

    : > "$OUT"

    cut -d'|' -f2 "$EXPANDED" |
    tr '[:upper:]' '[:lower:]' |
    sed 's/[^a-z0-9._-]/-/g' |
    sort -u |
    while IFS= read -r CAT; do
        [ -n "$CAT" ] || continue

        # Не активируем целые GeoIP-страны/территории автоматически.
        echo "$CAT" | grep -Eq '^[a-z][a-z]$' && continue

        FILE="$CATALOG/$CAT.cidr"
        [ -s "$FILE" ] || continue

        COUNT="$(wc -l < "$FILE" 2>/dev/null)"
        [ -n "$COUNT" ] || COUNT=0

        if [ "$COUNT" -gt "$MAX_CATEGORY_ROUTES" ]; then
            log "SKIP category=$CAT routes=$COUNT reason=safety-cap"
            continue
        fi

        echo "$CAT" >> "$OUT"
    done

    sort -u "$OUT" > "$OUT.sorted"
    mv "$OUT.sorted" "$OUT"
}

route_line()
{
    CIDR="$1"
    NET="${CIDR%/*}"
    PREFIX="${CIDR#*/}"
    MASK="$(prefix_mask "$PREFIX")" || return 1

    echo "ip route $NET $MASK $WG auto"
}

reconcile_routes()
{
    RUN="$1"
    CATS="$2"

    WANTED="$WORK/wanted-cidr"
    NEXT_OWNED="$WORK/next-owned"

    : > "$WANTED"
    : > "$NEXT_OWNED"

    while IFS= read -r CAT; do
        [ -n "$CAT" ] || continue
        [ -s "$CATALOG/$CAT.cidr" ] || continue
        cat "$CATALOG/$CAT.cidr" >> "$WANTED"
    done < "$CATS"

    sort -u "$WANTED" > "$WANTED.sorted"
    mv "$WANTED.sorted" "$WANTED"

    ADDED=0
    REMOVED=0
    EXISTING=0
    ERRORS=0

    while IFS= read -r CIDR; do
        [ -n "$CIDR" ] || continue

        ROUTE="$(route_line "$CIDR")" || continue

        if grep -Fqx "$ROUTE" "$RUN"; then
            if grep -Fxq "$CIDR" "$OWNED"; then
                echo "$CIDR" >> "$NEXT_OWNED"
            else
                EXISTING=$((EXISTING + 1))
            fi
            continue
        fi

        NET="${CIDR%/*}"
        PREFIX="${CIDR#*/}"
        MASK="$(prefix_mask "$PREFIX")" || continue

        if ndm "ip route $NET $MASK $WG auto"; then
            echo "$CIDR" >> "$NEXT_OWNED"
            ADDED=$((ADDED + 1))
        else
            ERRORS=$((ERRORS + 1))
        fi
    done < "$WANTED"

    while IFS= read -r CIDR; do
        [ -n "$CIDR" ] || continue

        grep -Fxq "$CIDR" "$WANTED" && continue

        NET="${CIDR%/*}"
        PREFIX="${CIDR#*/}"
        MASK="$(prefix_mask "$PREFIX")" || continue

        if ndm "no ip route $NET $MASK $WG"; then
            REMOVED=$((REMOVED + 1))
        else
            echo "$CIDR" >> "$NEXT_OWNED"
            ERRORS=$((ERRORS + 1))
        fi
    done < "$OWNED"

    sort -u "$NEXT_OWNED" > "$OWNED.new"
    mv "$OWNED.new" "$OWNED"

    cp "$CATS" "$ACTIVE.new"
    mv "$ACTIVE.new" "$ACTIVE"

    if [ "$ADDED" -gt 0 ] || [ "$REMOVED" -gt 0 ]; then
        if ndm "system configuration save"; then
            SAVE="YES"
        else
            SAVE="FAILED"
            ERRORS=$((ERRORS + 1))
        fi
    else
        SAVE="NOT_NEEDED"
    fi

    echo "ACTIVE_CATEGORIES=$(wc -l < "$ACTIVE")"
    echo "WANTED_CIDR=$(wc -l < "$WANTED")"
    echo "ADDED=$ADDED"
    echo "REMOVED=$REMOVED"
    echo "EXISTING_UNMANAGED=$EXISTING"
    echo "MANAGED_DYNAMIC=$(wc -l < "$OWNED")"
    echo "ERRORS=$ERRORS"
    echo "CONFIG_SAVE=$SAVE"

    log "SYNC active=$(wc -l < "$ACTIVE") wanted=$(wc -l < "$WANTED") added=$ADDED removed=$REMOVED existing=$EXISTING managed=$(wc -l < "$OWNED") errors=$ERRORS save=$SAVE"

    [ "$ERRORS" -eq 0 ]
}

echo "SUBNET_SYNC_VERSION=$VERSION"
echo "MODE=$MODE"
echo "SOURCES=itdoginfo/allow-domains+Loyalsoldier/geoip"
echo "SELECTION=DYNAMIC_FROM_ROUTED_DOMAINS"
echo "INTERFACE=$WG"

case "$MODE" in
    sync|--sync)
        update_itdog_catalog || true
        update_loyal_catalog || true
        build_catalog || {
            echo "SUBNET_SYNC=CATALOG_FAILED"
            exit 1
        }
        ;;
    --reconcile)
        [ -d "$CATALOG" ] || {
            echo "ERROR=CATALOG_MISSING"
            exit 1
        }
        ;;
    *)
        echo "ERROR=UNKNOWN_MODE"
        exit 2
        ;;
esac

if [ ! -s "$HINT_CATALOG" ]; then
    echo "SUBNET_SYNC=CATALOG_READY_HINTS_MISSING"
    exit 0
fi

RUN_RAW="$WORK/running.raw"
RUN="$WORK/running"

ndmc -c "show running-config" > "$RUN_RAW" 2>/dev/null || {
    echo "ERROR=CANNOT_READ_RUNNING_CONFIG"
    exit 1
}

tr -d '\r' < "$RUN_RAW" > "$RUN"

if [ ! -s "$RUN" ]; then
    echo "ERROR=EMPTY_RUNNING_CONFIG"
    exit 1
fi

DOMAINS="$WORK/policy-domains"
CATS="$WORK/desired-categories"

collect_vpn_domains "$RUN" > "$DOMAINS"
collect_categories "$DOMAINS" "$CATS"

echo "VPN_DOMAINS=$(wc -l < "$DOMAINS")"
echo "MATCHED_IP_CATEGORIES=$(wc -l < "$CATS")"

if reconcile_routes "$RUN" "$CATS"; then
    echo "SUBNET_SYNC=OK"
else
    echo "SUBNET_SYNC=PARTIAL"
fi

exit 0
