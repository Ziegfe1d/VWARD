#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH


VWARD_PROFILE_LIB=${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}
[ -r "$VWARD_PROFILE_LIB" ] || { echo "VWARD device profile library is unavailable" >&2; exit 1; }
. "$VWARD_PROFILE_LIB"
vward_profile_load || exit 1
VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
[ -r "$VWARD_ADMISSION_LIB" ] || { echo "VWARD runtime admission library is unavailable" >&2; exit 1; }
. "$VWARD_ADMISSION_LIB"
vward_component_gate policy-sync
vward_admission_enter policy-sync || exit $?

VERSION="2.0"
WG="$VWARD_TUNNEL_DEVICE"
# Keenetic takes the interface name in "ip route", not the kernel device.
RT="${VWARD_TUNNEL_INTERFACE:-$WG}"
MODE="${1:-sync}"

STATE="/opt/var/lib/vward/policy-sync"
SOURCE_ROOT="$STATE/source-catalog"
ITDOG_SRC="$SOURCE_ROOT/itdog"
LOYAL_SRC="$SOURCE_ROOT/loyalsoldier"
# Subnets a service publishes itself: exact where the collections guess.
OFFICIAL_SRC="$SOURCE_ROOT/official"
SOURCES_STATUS="${VWARD_ROUTE_SOURCES_STATUS:-/opt/var/lib/vward/route-sources.status}"
CATALOG="$STATE/catalog"
INDEX="$STATE/catalog.index"
OWNED="$STATE/owned.dynamic.routes"
# Device the owned routes point to; differs from $WG after the tunnel for routes changed.
OWNED_DEVICE="$STATE/owned.interface"
ACTIVE="$STATE/active.categories"
# Categories switched off in the Panel never get routes, even if their domains are routed.
EXCLUDED="${VWARD_POLICY_EXCLUDED:-/opt/etc/vward/policy-sync/excluded.categories}"
LOCK="$STATE/lock"
# Categories left off because they would take a Smart DNS domain into the tunnel.
SMARTDNS_HELD="$STATE/smartdns.categories"
# Blocks around Smart DNS addresses kept out of the tunnel, and the addresses of the last run.
SMARTDNS_BLOCKS="$STATE/smartdns.addresses"
SMARTDNS_ADDR_CACHE="$STATE/smartdns.resolved"
SMARTDNS_HOLD_PREFIX=24
# Removals held back by the shrink guard (fix.34.1, r2), and the last set of routes that synced clean.
SHRINK_PENDING="$STATE/shrink.pending"
LAST_GOOD="$STATE/owned.last-good"
LISTS_CONF="${VWARD_DOMAIN_LISTS_CONF:-/opt/etc/vward/route-engine/domain-lists.conf}"
NSLOOKUP="${VWARD_NSLOOKUP:-nslookup}"

HINT_CATALOG="/opt/etc/vward/route-engine/hints-catalog.tsv"
HINT_INCLUDES="/opt/etc/vward/route-engine/hints-includes.tsv"

LOG="/opt/var/log/vward-policy-sync-sync.log"
WORK="$STATE/work.$$"

ITDOG_ARCH="$WORK/itdog.tar.gz"
LOYAL_JSON="$WORK/loyal.json"

MAX_CATEGORY_ROUTES=2000
MAX_SOURCE_ARCHIVE_BYTES=${MAX_SOURCE_ARCHIVE_BYTES:-33554432}
MAX_SOURCE_UNPACKED_BYTES=${MAX_SOURCE_UNPACKED_BYTES:-67108864}
MAX_SOURCE_ARCHIVE_ENTRIES=${MAX_SOURCE_ARCHIVE_ENTRIES:-20000}

mkdir -p "$STATE" "$SOURCE_ROOT"

# The lock lives on the USB drive: one a power cut left behind is taken over.
if ! vward_lock_take "$LOCK"; then
    echo "SUBNET_SYNC=ALREADY_RUNNING"
    exit 0
fi

mkdir -p "$WORK"

cleanup()
{
    rm -rf "${WORK:?}" "${LOCK:?}"
    vward_admission_leave 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

touch "$OWNED"

log()
{
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"
}

download()
{
    URL="$1"
    OUT="$2"
    LIMIT_BLOCKS=$(( (MAX_SOURCE_ARCHIVE_BYTES + 511) / 512 ))

    (
      ulimit -f "$LIMIT_BLOCKS" || exit 1
      curl --http1.1 -4 -f -L \
        --connect-timeout 10 \
        --max-time 120 \
        --max-filesize "$MAX_SOURCE_ARCHIVE_BYTES" \
        -sS "$URL" -o "$OUT"
    ) || return 1
    SIZE="$(wc -c 2>/dev/null < "$OUT" | tr -d ' ')"
    case "$SIZE" in ''|*[!0-9]*) return 1 ;; esac
    [ "$SIZE" -le "$MAX_SOURCE_ARCHIVE_BYTES" ]
}

archive_validate()
{
    ARCH="$1"
    OUTDIR="$2"
    LIST="$OUTDIR/.vward-archive-list.$$"
    VERBOSE="$OUTDIR/.vward-archive-verbose.$$"

    tar -tzf "$ARCH" > "$LIST" 2>/dev/null || { rm -f "$LIST" "$VERBOSE"; return 1; }
    tar -tvzf "$ARCH" > "$VERBOSE" 2>/dev/null || { rm -f "$LIST" "$VERBOSE"; return 1; }
    awk -v max_entries="${MAX_SOURCE_ARCHIVE_ENTRIES:-20000}" '
      $0=="" || $0==".." || $0 ~ /^\// || $0 ~ /^\.\.\// || $0 ~ /\/\.\.\// || $0 ~ /\/\.\.$/ {exit 1}
      {n++} END {if (n>max_entries) exit 1}
    ' "$LIST" || { rm -f "$LIST" "$VERBOSE"; return 1; }
    awk -v max_bytes="${MAX_SOURCE_UNPACKED_BYTES:-67108864}" '
      substr($0,1,1)!="-" && substr($0,1,1)!="d" {exit 1}
      $3 !~ /^[0-9]+$/ {exit 1}
      {sum += $3} END {if (sum>max_bytes) exit 1}
    ' "$VERBOSE" || { rm -f "$LIST" "$VERBOSE"; return 1; }
    rm -f "$LIST" "$VERBOSE"
}

extract_archive()
{
    ARCH="$1"
    OUTDIR="$2"

    mkdir -p "$OUTDIR" || return 1
    archive_validate "$ARCH" "$OUTDIR" || return 1
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
    rm -rf "${OLD:?}"

    if [ -d "$DEST" ]; then
        mv "$DEST" "$OLD" || return 1
    fi

    if mv "$NEW" "$DEST"; then
        rm -rf "${OLD:?}"
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
        COUNT="$(wc -l 2>/dev/null < "$NEW/$CAT.cidr")"
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
    awk '{gsub(/[}],[ \t]*[{]/, "}\n{"); print}' |
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
        COUNT="$(wc -l 2>/dev/null < "$NEW/$CAT.cidr")"
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

update_official_catalog()
{
    NEW="$WORK/official-source"
    mkdir -p "$NEW"
    if ! download "https://core.telegram.org/resources/cidr.txt" "$WORK/telegram-official.raw"; then
        echo "SOURCE_OFFICIAL=UNAVAILABLE"
        return 1
    fi
    normalize_ipv4 < "$WORK/telegram-official.raw" > "$NEW/telegram.cidr"
    COUNT="$(wc -l 2>/dev/null < "$NEW/telegram.cidr")"
    [ -n "$COUNT" ] || COUNT=0
    if [ "$COUNT" -lt 3 ]; then
        echo "SOURCE_OFFICIAL=BAD_COUNT:$COUNT"
        return 1
    fi
    replace_source_dir "$NEW" "$OFFICIAL_SRC" || return 1
    echo "SOURCE_OFFICIAL=OK:telegram=$COUNT"
    return 0
}

# source_status ID ok|fail DIR: the result and the subnets the source keeps.
source_status()
{
    ss_n="$(cat "$3"/*.cidr 2>/dev/null | wc -l | tr -d ' ')"
    mkdir -p "$(dirname "$SOURCES_STATUS")" 2>/dev/null
    { [ ! -r "$SOURCES_STATUS" ] || awk -F'|' -v id="$1" '$1 != id' "$SOURCES_STATUS"
      echo "$1|$(date +%s)|$2|${ss_n:-0}"; } > "$SOURCES_STATUS.tmp.$$" && mv -f "$SOURCES_STATUS.tmp.$$" "$SOURCES_STATUS"
}

build_catalog()
{
    NEW="$WORK/catalog-new"
    IDX="$WORK/catalog.index"

    mkdir -p "$NEW"
    : > "$IDX"

    for FILE in "$ITDOG_SRC"/*.cidr "$LOYAL_SRC"/*.cidr "$OFFICIAL_SRC"/*.cidr; do
        [ -f "$FILE" ] || continue

        CAT="$(category_name "$FILE")"
        [ -n "$CAT" ] || continue

        cat "$FILE" >> "$NEW/$CAT.tmp"
    done

    for FILE in "$NEW"/*.tmp; do
        [ -f "$FILE" ] || continue

        CAT="$(category_name "$FILE")"

        # Only public IPv4 subnets, /8 or narrower: a home, a provider's or a reserved range in
        # the tunnel would take the router's own answers there too (an SSH session from the
        # internet, the provider's DNS), so a source that lists one never gets it routed.
        awk -F'[./]' '
            BEGIN {
                split("0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 198.18.0.0/15 224.0.0.0/3", r, " ")
                for (i in r) { split(r[i], q, "[./]"); rs[i] = ((q[1] * 256 + q[2]) * 256 + q[3]) * 256 + q[4]; re[i] = rs[i] + 2 ^ (32 - q[5]) - 1 }
            }
            NF != 5 || $5 !~ /^[0-9]+$/ || $5 < 8 || $5 > 32 {next}
            {
                for (i = 1; i <= 4; i++) if ($i !~ /^[0-9]+$/ || $i > 255) next
                s = ((($1 * 256 + $2) * 256 + $3) * 256 + $4); z = 2 ^ (32 - $5); s = int(s / z) * z; e = s + z - 1
                for (i in r) if (s <= re[i] && e >= rs[i]) next
                print
            }' "$FILE" | sort -u > "$NEW/$CAT.cidr"
        rm -f "$FILE"

        COUNT="$(wc -l 2>/dev/null < "$NEW/$CAT.cidr")"
        [ -n "$COUNT" ] || COUNT=0

        printf '%s|%s\n' "$CAT" "$COUNT" >> "$IDX"
    done

    CATS="$(wc -l 2>/dev/null < "$IDX")"
    [ -n "$CATS" ] || CATS=0

    if [ "$CATS" -lt 1 ]; then
        echo "ERROR=EMPTY_IP_CATALOG"
        return 1
    fi

    OLD="${CATALOG}.old.$$"
    rm -rf "${OLD:?}"

    [ -d "$CATALOG" ] && mv "$CATALOG" "$OLD"

    if ! mv "$NEW" "$CATALOG"; then
        [ -d "$OLD" ] && mv "$OLD" "$CATALOG"
        return 1
    fi

    rm -rf "${OLD:?}"

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

    # Keenetic writes the interface name in DNS routes; older setups used
    # the kernel device: both count.
    awk -v wg="$WG" -v wgi="${VWARD_TUNNEL_INTERFACE:-}" '
        $1=="route" &&
        $2=="object-group" &&
        ($4==wg || ($4==wgi && wgi!="")) {
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

            sort -u "$EXPANDED" > "$NEXT" &&
            mv "$NEXT" "$EXPANDED" || rm -f "$NEXT"

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

        COUNT="$(wc -l 2>/dev/null < "$FILE")"
        [ -n "$COUNT" ] || COUNT=0

        if [ "$COUNT" -gt "$MAX_CATEGORY_ROUTES" ]; then
            log "SKIP category=$CAT routes=$COUNT reason=safety-cap"
            continue
        fi

        echo "$CAT" >> "$OUT"
    done

    sort -u "$OUT" > "$OUT.sorted" &&
    mv "$OUT.sorted" "$OUT" || rm -f "$OUT.sorted"
}

# Smart DNS wins over an IP category, address by address (fix.34.1, r1 and r3): the block
# (/SMARTDNS_HOLD_PREFIX, 24 by default) around each address a Smart DNS domain resolves to
# stays out of the tunnel, the rest of the category keeps its routes. Before, the whole category
# went off: meta.ai took all of Meta, copilot.microsoft.com Cloudflare and Discord (25.10).
# Every Smart DNS domain is resolved (the limit of 32 is gone); a domain that gives no address
# now keeps its addresses from the run before ($SMARTDNS_ADDR_CACHE). "block|domain|category"
# goes to $SMARTDNS_BLOCKS (the diagnostics); $SMARTDNS_HELD, whole categories off, stays empty.
smartdns_hold()
{
    : > "$SMARTDNS_HELD.new"
    : > "$WORK/smartdns-blocks"
    if [ -s "$2" ] && [ "$(awk -F= '$1 == "smartdns_guard" {print $2; exit}' "$LISTS_CONF" 2>/dev/null)" != 0 ]; then
        SD_ADDR="$WORK/smartdns-addresses"
        SD_LIST="$WORK/smartdns-domains"
        {
            awk '
                /^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1)}
                ctx && $1 == "https" && $2 == "upstream" && $(NF-1) == "domain" {print tolower($NF)}
            ' "$1"
            command -v vward_agh_smartdns_domains >/dev/null 2>&1 && vward_agh_smartdns_domains
        } | sort -u > "$SD_LIST"
        while IFS= read -r SD; do
            case "$SD" in ''|*[!a-z0-9.-]*) continue ;; esac
            "$NSLOOKUP" "$SD" "${VWARD_DNS_SERVER:-127.0.0.1}" 2>/dev/null |
                awk -v d="$SD" '/^Name:/ {n = 1; next} n {for (i = 2; i <= NF; i++) if ($i ~ /^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$/) print d, $i}'
        done < "$SD_LIST" > "$SD_ADDR.now"
        awk 'FILENAME == ARGV[1] {want[$1] = 1; next}
             FILENAME == ARGV[2] {now[$1] = 1; print; next}
             ($1 in want) && !($1 in now)' "$SD_LIST" "$SD_ADDR.now" "$SMARTDNS_ADDR_CACHE" 2>/dev/null |
            sort -u > "$SD_ADDR"
        if [ -s "$SD_ADDR" ]; then
            if ! cmp -s "$SD_ADDR" "$SMARTDNS_ADDR_CACHE" 2>/dev/null; then
                cp "$SD_ADDR" "$SMARTDNS_ADDR_CACHE.new" && mv -f "$SMARTDNS_ADDR_CACHE.new" "$SMARTDNS_ADDR_CACHE"
            fi
            while IFS= read -r CAT; do
                [ -s "$CATALOG/$CAT.cidr" ] || continue
                awk -F'[./]' -v c="$CAT" -v hp="$SMARTDNS_HOLD_PREFIX" '
                    function p2(e,  r) {r = 1; while (e-- > 0) r *= 2; return r}
                    BEGIN {bz = p2(32 - hp)}
                    NR == FNR {
                        split($0, p, " "); split(p[2], q, ".")
                        z = bz; b = int((((q[1] * 256 + q[2]) * 256 + q[3]) * 256 + q[4]) / z) * z
                        n++; bs[n] = b; dom[n] = p[1]
                        bt[n] = int(b / 16777216) "." int(b / 65536) % 256 "." int(b / 256) % 256 "." b % 256 "/" hp
                        next
                    }
                    NF == 5 {
                        z = p2(32 - $5); s = int(((($1 * 256 + $2) * 256 + $3) * 256 + $4) / z) * z
                        for (i = 1; i <= n; i++) if (bs[i] < s + z && s < bs[i] + bz) print bt[i] "|" dom[i] "|" c
                    }' "$SD_ADDR" "$CATALOG/$CAT.cidr"
            done < "$2" | sort -u > "$WORK/smartdns-blocks"
        fi
    fi

    if [ -s "$WORK/smartdns-blocks" ]; then
        log "HOLD smartdns blocks=$(cut -d'|' -f1 "$WORK/smartdns-blocks" | sort -u | wc -l) $(cut -d'|' -f3,2 "$WORK/smartdns-blocks" | sort -u | tr '\n' ' ')"
    fi
    if ! cmp -s "$WORK/smartdns-blocks" "$SMARTDNS_BLOCKS" 2>/dev/null; then
        cp "$WORK/smartdns-blocks" "$SMARTDNS_BLOCKS.new" && mv -f "$SMARTDNS_BLOCKS.new" "$SMARTDNS_BLOCKS"
    fi
    if ! cmp -s "$SMARTDNS_HELD.new" "$SMARTDNS_HELD" 2>/dev/null; then
        mv -f "$SMARTDNS_HELD.new" "$SMARTDNS_HELD"
    else
        rm -f "$SMARTDNS_HELD.new"
    fi
}

# Powers of two by p2(): BusyBox awk built without its math library has no «^» (CI, fix.34.1).
# The subnets of $2 without the held blocks of $1 ("a.b.c.d/len|..."): a subnet holding a block
# is split in halves down to the block, which is left out (a /13 with one held /24: 11 routes).
smartdns_split()
{
    awk -v hp="$SMARTDNS_HOLD_PREFIX" '
        function p2(e,  r) {r = 1; while (e-- > 0) r *= 2; return r}
        function num(a,  q) {split(a, q, "."); return ((q[1] * 256 + q[2]) * 256 + q[3]) * 256 + q[4]}
        function dot(v) {return int(v / 16777216) "." int(v / 65536) % 256 "." int(v / 256) % 256 "." v % 256}
        function hit(s, z,  i) {for (i = 1; i <= nb; i++) if (bs[i] < s + z && s < bs[i] + bz) return 1; return 0}
        function emit(s, len,  z) {
            z = p2(32 - len)
            if (!hit(s, z)) {print dot(s) "/" len; return}
            if (len >= hp) return
            emit(s, len + 1); emit(s + z / 2, len + 1)
        }
        BEGIN {bz = p2(32 - hp)}
        NR == FNR {split($0, p, "|"); split(p[1], q, "/"); if (!(q[1] in seen)) {seen[q[1]] = 1; bs[++nb] = num(q[1])}; next}
        {split($0, p, "/"); if (p[2] !~ /^[0-9]+$/ || p[2] > 32) next; z = p2(32 - p[2]); emit(int(num(p[1]) / z) * z, p[2] + 0)}
    ' "$1" "$2"
}

# Settings of the guards in domain-lists.conf: name, default.
lists_conf()
{
    LC="$(awk -F= -v k="$1" '$1 == k {print $2; exit}' "$LISTS_CONF" 2>/dev/null)"
    case "$LC" in ''|*[!0-9]*) LC="$2" ;; esac
    echo "$LC"
}

# The running configuration is incomplete (fix.34.1, r2): no FQDN group, or none of the routes
# VWARD owns while it owns some (it saved them). Nothing is removed on such a read.
run_partial()
{
    grep -q '^object-group fqdn ' "$1" || return 0
    [ -s "$OWNED" ] || return 1
    awk -v rt="$RT" '
        function p2(e,  r) {r = 1; while (e-- > 0) r *= 2; return r}
        function mask(l,  m, i, o, b) {m = ""; for (i = 0; i < 4; i++) {b = l - i * 8; b = b >= 8 ? 8 : (b < 0 ? 0 : b); o = 256 - p2(8 - b); m = m (i ? "." : "") o}; return m}
        NR == FNR {have[$0] = 1; next}
        {split($0, p, "/"); if (("ip route " p[1] " " mask(p[2]) " " rt " auto") in have || (p[2] == 32 && ("ip route " p[1] " " rt " auto") in have)) {found = 1; exit}}
        END {exit found ? 1 : 0}
    ' "$1" "$OWNED"
}

route_line()
{
    CIDR="$1"
    NET="${CIDR%/*}"
    PREFIX="${CIDR#*/}"
    MASK="$(prefix_mask "$PREFIX")" || return 1

    echo "ip route $NET $MASK $RT auto"
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

    sort -u "$WANTED" > "$WANTED.sorted" &&
    mv "$WANTED.sorted" "$WANTED" || rm -f "$WANTED.sorted"

    if [ -s "$WORK/smartdns-blocks" ]; then
        smartdns_split "$WORK/smartdns-blocks" "$WANTED" | sort -u > "$WANTED.split" &&
        mv "$WANTED.split" "$WANTED" || rm -f "$WANTED.split"
    fi

    ADDED=0
    REMOVED=0
    EXISTING=0
    ERRORS=0
    MOVED=0

    # The tunnel for routes changed: withdraw owned routes from the previous
    # device first; they are re-added through $WG below.  Routes that could not be
    # withdrawn stay owned by the previous device and are retried next run.
    PREV_WG="$(cat "$OWNED_DEVICE" 2>/dev/null)"
    case "$PREV_WG" in *[!A-Za-z0-9_.:-]*) PREV_WG="" ;; esac
    if [ -n "$PREV_WG" ] && [ "$PREV_WG" != "$RT" ] && [ "$PREV_WG" != "$WG" ]; then
        LEFT="$WORK/left-owned"
        : > "$LEFT"
        while IFS= read -r CIDR; do
            [ -n "$CIDR" ] || continue
            NET="${CIDR%/*}"
            MASK="$(prefix_mask "${CIDR#*/}")" || continue
            if ndm "no ip route $NET $MASK $PREV_WG"; then
                MOVED=$((MOVED + 1))
            else
                echo "$CIDR" >> "$LEFT"
                ERRORS=$((ERRORS + 1))
            fi
        done < "$OWNED"
        mv "$LEFT" "$OWNED"
        if [ -s "$OWNED" ]; then
            ndm "system configuration save" || true
            echo "MOVED_FROM=$PREV_WG"
            echo "MOVE_PENDING=$(wc -l < "$OWNED")"
            log "MOVE from=$PREV_WG to=$WG withdrawn=$MOVED pending=$(wc -l < "$OWNED")"
            return 1
        fi
        log "MOVE from=$PREV_WG to=$WG withdrawn=$MOVED"
    fi
    echo "$RT" > "$OWNED_DEVICE"

    while IFS= read -r CIDR; do
        [ -n "$CIDR" ] || continue

        ROUTE="$(route_line "$CIDR")" || continue

        # Keenetic shows a route to one address without its mask («ip route 192.0.2.1 OpkgTun2
        # auto»): compared with the mask only, it was added and saved again every hour (Viva
        # 2026-10-11).
        if grep -Fqx "$ROUTE" "$RUN" || { [ "${CIDR#*/}" = 32 ] && grep -Fqx "ip route ${CIDR%/*} $RT auto" "$RUN"; }; then
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

        if ndm "ip route $NET $MASK $RT auto"; then
            echo "$CIDR" >> "$NEXT_OWNED"
            ADDED=$((ADDED + 1))
        else
            ERRORS=$((ERRORS + 1))
        fi
    done < "$WANTED"

    # Shrink guard (fix.34.1, r2): 25.10 one pass removed 442 of 508 routes (a whole category held
    # for a Smart DNS domain), Instagram and the sites behind Cloudflare went direct. More than
    # shrink_max_routes or shrink_max_pct % of the owned routes at once, or a busy router: nothing
    # is removed (an incomplete running configuration stops the pass before, run_partial), the routes stay owned, the reason goes to
    # the log and $SHRINK_PENDING (the Panel). Each pass checks again; the held set is removed by
    # «--confirm-shrink» (the same routes or fewer). shrink_guard=0 turns the guard off.
    TO_REMOVE="$WORK/to-remove"
    awk 'NR == FNR {w[$0] = 1; next} $0 != "" && !($0 in w)' "$WANTED" "$OWNED" > "$TO_REMOVE"
    RM_N="$(wc -l < "$TO_REMOVE")"
    OWN_N="$(wc -l < "$OWNED")"
    SHRINK=""
    if [ "$RM_N" -gt 0 ] && [ "$(lists_conf shrink_guard 1)" != 0 ]; then
        SH_MAX="$(lists_conf shrink_max_routes 50)"
        SH_PCT="$(lists_conf shrink_max_pct 20)"
        if command -v vward_busy >/dev/null 2>&1 && vward_busy; then
            SHRINK=busy
        elif [ "$RM_N" -gt "$SH_MAX" ] || { [ "$RM_N" -ge 10 ] && [ $((RM_N * 100)) -gt $((SH_PCT * OWN_N)) ]; }; then
            SHRINK=limit
            if [ "${SHRINK_CONFIRMED:-0}" = 1 ] && [ -s "$SHRINK_PENDING.routes" ] &&
               awk 'NR == FNR {p[$0] = 1; next} !($0 in p) {bad = 1; exit} END {exit bad}' "$SHRINK_PENDING.routes" "$TO_REMOVE"; then
                SHRINK=""
                log "SHRINK_CONFIRMED remove=$RM_N owned=$OWN_N"
            fi
        fi
    fi

    if [ -n "$SHRINK" ]; then
        cat "$TO_REMOVE" >> "$NEXT_OWNED"
        cp "$TO_REMOVE" "$SHRINK_PENDING.routes.new" && mv -f "$SHRINK_PENDING.routes.new" "$SHRINK_PENDING.routes"
        printf 'reason=%s\nremove=%s\nowned=%s\nmax_routes=%s\nmax_pct=%s\nat=%s\n' "$SHRINK" "$RM_N" "$OWN_N" \
            "${SH_MAX:-}" "${SH_PCT:-}" "$(date '+%Y-%m-%d %H:%M:%S')" > "$SHRINK_PENDING.new" &&
            mv -f "$SHRINK_PENDING.new" "$SHRINK_PENDING"
        echo "SHRINK_HELD=$SHRINK"
        echo "SHRINK_PENDING=$RM_N"
        log "SHRINK_HOLD reason=$SHRINK remove=$RM_N owned=$OWN_N max_routes=${SH_MAX:-} max_pct=${SH_PCT:-}"
    else
        rm -f "$SHRINK_PENDING" "$SHRINK_PENDING.routes"
        while IFS= read -r CIDR; do
            [ -n "$CIDR" ] || continue

            NET="${CIDR%/*}"
            PREFIX="${CIDR#*/}"
            MASK="$(prefix_mask "$PREFIX")" || continue

            if ndm "no ip route $NET $MASK $RT"; then
                REMOVED=$((REMOVED + 1))
            else
                echo "$CIDR" >> "$NEXT_OWNED"
                ERRORS=$((ERRORS + 1))
            fi
        done < "$TO_REMOVE"
    fi

    sort -u "$NEXT_OWNED" > "$OWNED.new" &&
    mv "$OWNED.new" "$OWNED" || rm -f "$OWNED.new"

    cp "$CATS" "$ACTIVE.new"
    mv "$ACTIVE.new" "$ACTIVE"

    if [ "$ADDED" -gt 0 ] || [ "$REMOVED" -gt 0 ] || [ "$MOVED" -gt 0 ]; then
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
    [ "$MOVED" -eq 0 ] || echo "MOVED=$MOVED"
    echo "EXISTING_UNMANAGED=$EXISTING"
    echo "MANAGED_DYNAMIC=$(wc -l < "$OWNED")"
    echo "ERRORS=$ERRORS"
    echo "CONFIG_SAVE=$SAVE"

    log "SYNC active=$(wc -l < "$ACTIVE") wanted=$(wc -l < "$WANTED") added=$ADDED removed=$REMOVED existing=$EXISTING managed=$(wc -l < "$OWNED") errors=$ERRORS save=$SAVE${SHRINK:+ held=$SHRINK}"

    # The last set that synced clean: «--restore-last-good» brings it back in one step.
    if [ "$ERRORS" -eq 0 ] && [ -z "$SHRINK" ] && [ -s "$OWNED" ] && ! cmp -s "$OWNED" "$LAST_GOOD" 2>/dev/null; then
        cp "$OWNED" "$LAST_GOOD.new" && mv -f "$LAST_GOOD.new" "$LAST_GOOD"
    fi

    [ "$ERRORS" -eq 0 ]
}

echo "SUBNET_SYNC_VERSION=$VERSION"
echo "MODE=$MODE"
echo "SOURCES=itdoginfo/allow-domains+Loyalsoldier/geoip+official"
echo "SELECTION=DYNAMIC_FROM_ROUTED_DOMAINS"
echo "INTERFACE=$RT"

case "$MODE" in
    sync|--sync)
        if update_itdog_catalog; then source_status itdog-ip ok "$ITDOG_SRC"; else source_status itdog-ip fail "$ITDOG_SRC"; fi
        if update_loyal_catalog; then source_status loyalsoldier ok "$LOYAL_SRC"; else source_status loyalsoldier fail "$LOYAL_SRC"; fi
        if update_official_catalog; then source_status official ok "$OFFICIAL_SRC"; else source_status official fail "$OFFICIAL_SRC"; fi
        build_catalog || {
            echo "SUBNET_SYNC=CATALOG_FAILED"
            exit 1
        }
        ;;
    --reconcile|--confirm-shrink|--restore-last-good)
        [ "$MODE" != --confirm-shrink ] || SHRINK_CONFIRMED=1
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

vward_running_config > "$RUN_RAW" || {
    echo "ERROR=CANNOT_READ_RUNNING_CONFIG"
    exit 1
}

tr -d '\r' < "$RUN_RAW" > "$RUN"

if [ ! -s "$RUN" ]; then
    echo "ERROR=EMPTY_RUNNING_CONFIG"
    exit 1
fi

# An incomplete read would take the routes of the missing groups away: the pass stops here.
if run_partial "$RUN"; then
    printf 'reason=partial_config\nat=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" > "$SHRINK_PENDING.new" &&
        mv -f "$SHRINK_PENDING.new" "$SHRINK_PENDING"
    log "SKIP reconcile reason=partial_config lines=$(wc -l < "$RUN") owned=$(wc -l < "$OWNED")"
    echo "RUNNING_CONFIG=INCOMPLETE"
    echo "SUBNET_SYNC=SKIPPED"
    exit 0
fi

# One step back to the last set that synced clean: its routes are added again and owned.
if [ "$MODE" = --restore-last-good ]; then
    [ -s "$LAST_GOOD" ] || { echo "ERROR=NO_LAST_GOOD"; exit 1; }
    R_ADDED=0 R_ERR=0
    while IFS= read -r CIDR; do
        ROUTE="$(route_line "$CIDR")" || continue
        if grep -Fqx "$ROUTE" "$RUN" || { [ "${CIDR#*/}" = 32 ] && grep -Fqx "ip route ${CIDR%/*} $RT auto" "$RUN"; }; then
            continue
        fi
        if ndm "$ROUTE"; then R_ADDED=$((R_ADDED + 1)); else R_ERR=$((R_ERR + 1)); fi
    done < "$LAST_GOOD"
    sort -u "$OWNED" "$LAST_GOOD" > "$OWNED.new" && mv "$OWNED.new" "$OWNED"
    [ "$R_ADDED" -eq 0 ] || ndm "system configuration save" || R_ERR=$((R_ERR + 1))
    rm -f "$SHRINK_PENDING" "$SHRINK_PENDING.routes"
    log "RESTORE last-good routes=$(wc -l < "$LAST_GOOD") added=$R_ADDED errors=$R_ERR"
    echo "RESTORED=$R_ADDED"
    echo "ERRORS=$R_ERR"
    [ "$R_ERR" -eq 0 ] && echo "SUBNET_SYNC=OK" || echo "SUBNET_SYNC=PARTIAL"
    exit 0
fi

DOMAINS="$WORK/policy-domains"
CATS="$WORK/desired-categories"

collect_vpn_domains "$RUN" > "$DOMAINS"
collect_categories "$DOMAINS" "$CATS"
if [ -s "$EXCLUDED" ]; then
    grep -vxF -f "$EXCLUDED" "$CATS" > "$CATS.kept" || true
    mv "$CATS.kept" "$CATS"
fi

SMARTDNS_HOLD_PREFIX="$(lists_conf smartdns_hold_prefix 24)"
[ "$SMARTDNS_HOLD_PREFIX" -ge 16 ] && [ "$SMARTDNS_HOLD_PREFIX" -le 32 ] || SMARTDNS_HOLD_PREFIX=24
smartdns_hold "$RUN" "$CATS"

echo "VPN_DOMAINS=$(wc -l < "$DOMAINS")"
echo "MATCHED_IP_CATEGORIES=$(wc -l < "$CATS")"

if reconcile_routes "$RUN" "$CATS"; then
    echo "SUBNET_SYNC=OK"
else
    echo "SUBNET_SYNC=PARTIAL"
fi

exit 0
