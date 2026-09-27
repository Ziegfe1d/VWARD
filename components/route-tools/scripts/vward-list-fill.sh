#!/bin/sh

# Keenetic domain lists grow from the domain catalog (itdog, v2fly).
#
# Each list is tied to catalog categories: the one most of its own domains belong
# to, or else the one named like the list (a setting can name them or switch the
# list off).  After the nightly catalog update the domains of those categories the
# list does not cover yet (an entry covers its subdomains) are added once they
# answer in DNS.  VWARD removes only what it added itself: a domain gone from the
# catalog, or silent three nights in a row.  A domain the owner took out of the
# list is never added again.  At most 300 entries per list (Keenetic's limit).
#
#   vward-list-fill.sh run [GROUP]              every list (nightly) or one now
#   vward-list-fill.sh set GROUP auto|off|CAT[,CAT...]
#   vward-list-fill.sh undo GROUP               take back the last run on GROUP
#   vward-list-fill.sh status GROUP             key=value
#
# The last line of every call is result=changed|unchanged or error=CODE.

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

ETC="${VWARD_ROUTE_ETC:-/opt/etc/vward/route-engine}"
CATALOG="$ETC/hints-catalog.tsv"
INCLUDES="$ETC/hints-includes.tsv"
CONF="$ETC/list-fill.conf"
STATE="${VWARD_LIST_FILL_STATE:-/opt/var/lib/vward/list-fill}"
LOG="${VWARD_LIST_FILL_LOG:-/opt/var/log/vward-list-fill.log}"
NDMC="${VWARD_NDMC:-ndmc}"
CHANGE_LOCK="${VWARD_ROUTE_CHANGE_LOCK:-/tmp/vward-route-change.lock}"
# One run at a time: the nightly job and "Пополнить сейчас" share the state files.
RUN_LOCK="${VWARD_LIST_FILL_LOCK:-/tmp/vward-list-fill.lock}"
REFRESH_TS="${VWARD_ROUTE_REFRESH_TS:-/opt/var/lib/vward/route-engine/groups-refresh}"
DNS="${VWARD_LIST_FILL_DNS:-127.0.0.1}"
MAX="${VWARD_LIST_FILL_MAX:-300}"
PER_RUN="${VWARD_LIST_FILL_PER_RUN:-100}"
TIME_LIMIT="${VWARD_LIST_FILL_TIME_LIMIT:-600}"
MISS_LIMIT=3
# A category this big is "everything of a country", not a service.
BIG_CATEGORY=1500

VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
[ -r "$VWARD_ADMISSION_LIB" ] || { echo "error=admission_unavailable"; exit 1; }
. "$VWARD_ADMISSION_LIB"
vward_component_gate route-tools

OP="${1:-}"
GROUP="${2:-}"
WORK=""
LOCKED=0
RUN_LOCKED=0

die() { echo "error=$1"; exit "${2:-1}"; }
valid_group() { printf '%s\n' "$1" | grep -Eq '^domain-list[0-9]{1,3}$'; }
now() { date '+%Y-%m-%d %H:%M:%S'; }
log() { printf '%s|%s\n' "$(now)" "$*" >> "$LOG" 2>/dev/null || true; }

cleanup()
{
    [ -z "$WORK" ] || rm -rf "${WORK:?}"
    [ "$LOCKED" = 0 ] || rm -rf "${CHANGE_LOCK:?}"
    [ "$RUN_LOCKED" = 0 ] || rm -rf "${RUN_LOCK:?}"
    vward_admission_leave 2>/dev/null || true
}

# The lock the route engine and the Console take for group changes.
change_lock()
{
    n=0
    while ! mkdir "$CHANGE_LOCK" 2>/dev/null; do
        old=$(cat "$CHANGE_LOCK/pid" 2>/dev/null)
        if [ -n "$old" ] && ! kill -0 "$old" 2>/dev/null; then rm -rf "${CHANGE_LOCK:?}"; continue; fi
        n=$((n + 1))
        [ "$n" -ge 30 ] && return 1
        sleep 1
    done
    LOCKED=1
    echo $$ > "$CHANGE_LOCK/pid"
}
change_unlock() { [ "$LOCKED" = 0 ] || rm -rf "${CHANGE_LOCK:?}"; LOCKED=0; }

ndm()
{
    nd_out=$("$NDMC" -c "$1" 2>&1) || return 1
    printf '%s\n' "$nd_out" | grep -Eqi '(^|[^a-z])(error|failed|invalid|unknown command|not found|no such entry)' && return 1
    return 0
}

snapshot() { "$NDMC" -c "show running-config" > "$WORK/rc" 2>/dev/null && [ -s "$WORK/rc" ]; }

# items GROUP include|exclude: the list's entries, lower case.
items()
{
    awk -v g="$1" -v k="$2" '
        /^object-group fqdn / {cur=$3; next}
        /^!/ {cur=""; next}
        cur==g && $1==k {print tolower($2)}' "$WORK/rc"
}

description()
{
    awk -v g="$1" '
        /^object-group fqdn / {cur=$3; next}
        /^!/ {cur=""; next}
        cur==g && $1=="description" {sub(/^[ \t]*description[ \t]+/, ""); gsub(/"/, ""); print; exit}' "$WORK/rc"
}

conf_mode()
{
    [ -r "$CONF" ] || { echo auto; return; }
    cm=$(awk -F= -v g="$1" '$1==g {v=substr($0, length(g) + 2)} END {print v}' "$CONF")
    echo "${cm:-auto}"
}

# categories GROUP: the catalog categories the list follows, one per line.
categories()
{
    ct_mode=$(conf_mode "$1")
    case "$ct_mode" in
        off) return 0 ;;
        auto) ;;
        *) printf '%s\n' "$ct_mode" | tr ',' '\n' | sed '/^$/d'; return 0 ;;
    esac
    [ -s "$CATALOG" ] || return 0
    items "$1" include > "$WORK/own"
    # By content: the service category most of the list's own domains are in.
    ct_best=$(awk -F'|' -v big="$BIG_CATEGORY" '
        FILENAME == ARGV[1] {own[$1] = 1; n++; next}
        !(($1 "|" $3) in seen) {seen[$1 "|" $3] = 1; size[$3]++; if ($1 in own) hit[$3]++}
        END {
            for (c in hit) {
                if (size[c] > big || hit[c] < 2 || hit[c] * 10 < n * 4) continue
                if (hit[c] > bh || (hit[c] == bh && size[c] < bs)) {best = c; bh = hit[c]; bs = size[c]}
            }
            print best
        }' "$WORK/own" "$CATALOG")
    if [ -n "$ct_best" ]; then echo "$ct_best"; return 0; fi
    # Else by name: the list called like a category ("YouTube" -> youtube).
    ct_name=$(description "$1" | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9]//g')
    [ -n "$ct_name" ] || return 0
    awk -F'|' -v c="$ct_name" -v big="$BIG_CATEGORY" '$3 == c {n++} END {if (n > 0 && n <= big) print c}' "$CATALOG"
}

# wanted: the smallest set of catalog entries covering the categories (with
# the categories they include), one entry per service domain.
wanted()
{
    sort -u "$WORK/cats" > "$WORK/cats.set"
    if [ -s "$INCLUDES" ]; then
        i=0
        while [ "$i" -lt 4 ]; do
            awk -F'|' 'FILENAME == ARGV[1] {c[$1] = 1; next} ($2 in c) {print $3}' "$WORK/cats.set" "$INCLUDES" |
                cat - "$WORK/cats.set" | sort -u > "$WORK/cats.next"
            cmp -s "$WORK/cats.next" "$WORK/cats.set" && break
            mv "$WORK/cats.next" "$WORK/cats.set"
            i=$((i + 1))
        done
    fi
    awk -F'|' 'FILENAME == ARGV[1] {c[$1] = 1; next} ($3 in c) {print $1}' "$WORK/cats.set" "$CATALOG" |
        awk '{print gsub(/\./, ".") "\t" $0}' | sort -n -k1,1 -k2,2 | cut -f2 |
        awk '{
            d = $0; x = d; covered = 0
            while (1) { if (x in keep) {covered = 1; break}; i = index(x, "."); if (!i) break; x = substr(x, i + 1) }
            if (!covered) {keep[d] = 1; print d}
        }'
}

# covered_by SETFILE DOMAINSFILE: the domains an entry of SETFILE covers.
# Files are told apart by name: an empty first file must stay the first file.
covered_by()
{
    awk 'FILENAME == ARGV[1] {s[$0] = 1; next}
        {x = $0; while (1) { if (x in s) {print $0; break}; i = index(x, "."); if (!i) break; x = substr(x, i + 1) }}' "$1" "$2"
}

alive()
{
    if [ -n "${VWARD_LIST_FILL_RESOLVE:-}" ]; then "$VWARD_LIST_FILL_RESOLVE" "$1"; return; fi
    nslookup "$1" "$DNS" 2>/dev/null |
        awk '/^Name:/ {f = 1; next} f && /Address/ {for (i = 1; i <= NF; i++) if ($i ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ && $i != "0.0.0.0" && $i !~ /^127\./) ok = 1} END {exit !ok}'
}

touch_state() { mkdir -p "$STATE" && touch "$STATE/$1.added" "$STATE/$1.declined" "$STATE/$1.misses"; }
has_line() { grep -qxF "$2" "$1" 2>/dev/null; }
drop() { grep -vxF "$2" "$1" > "$1.tmp" 2>/dev/null; mv -f "$1.tmp" "$1"; }
# misses_set GROUP DOMAIN COUNT: nights in a row the domain did not answer (0 forgets it).
misses_set()
{
    awk -v d="$2" '$1 != d' "$STATE/$1.misses" > "$STATE/$1.misses.tmp" 2>/dev/null
    [ "$3" = 0 ] || echo "$2 $3" >> "$STATE/$1.misses.tmp"
    mv -f "$STATE/$1.misses.tmp" "$STATE/$1.misses"
}

status_write()
{
    {
        echo "ts=$(date +%s)"
        for sw_kv in "$@"; do echo "$sw_kv"; done
    } > "$STATE/$GROUP.status.tmp" && mv -f "$STATE/$GROUP.status.tmp" "$STATE/$GROUP.status"
}

# plan GROUP: what the list should gain and lose, with the DNS checks; no lock
# held (the checks take minutes).  Leaves $WORK/GROUP.add, .remove and .meta.
plan()
{
    G=$1
    GROUP=$G
    touch_state "$G"
    : > "$WORK/$G.add"; : > "$WORK/$G.remove"
    categories "$G" > "$WORK/cats"
    CATS=$(tr '\n' ',' < "$WORK/cats" | sed 's/,$//')
    if [ ! -s "$WORK/cats" ]; then
        printf 'CATS=\nCAND_N=0\nFULL=0\n' > "$WORK/$G.meta"
        return 0
    fi
    wanted > "$WORK/want"
    items "$G" include | sort -u > "$WORK/inc"
    items "$G" exclude | sort -u > "$WORK/exc"

    # The owner took a domain VWARD added out of the list: never again.
    : > "$WORK/gone"
    while IFS= read -r d; do
        has_line "$WORK/inc" "$d" || echo "$d" >> "$WORK/gone"
    done < "$STATE/$G.added"
    while IFS= read -r d; do
        drop "$STATE/$G.added" "$d"; misses_set "$G" "$d" 0
        has_line "$STATE/$G.declined" "$d" || echo "$d" >> "$STATE/$G.declined"
    done < "$WORK/gone"

    : > "$WORK/remove"; : > "$WORK/add"
    START=$(date +%s)
    # What VWARD added: gone from the catalog, or silent MISS_LIMIT nights running.
    covered_by "$WORK/want" "$STATE/$G.added" > "$WORK/still"
    while IFS= read -r d; do
        if ! has_line "$WORK/still" "$d"; then echo "$d" >> "$WORK/remove"; continue; fi
        [ $(($(date +%s) - START)) -lt "$TIME_LIMIT" ] || continue
        m=$(awk -v d="$d" '$1 == d {print $2}' "$STATE/$G.misses"); m=${m:-0}
        if alive "$d"; then m=0; else m=$((m + 1)); fi
        misses_set "$G" "$d" "$m"
        [ "$m" -lt "$MISS_LIMIT" ] || echo "$d" >> "$WORK/remove"
    done < "$STATE/$G.added"

    # New: not covered by the list, not excluded, not declined; alive; within the limit.
    sort -u "$WORK/inc" "$WORK/exc" "$STATE/$G.declined" > "$WORK/have"
    covered_by "$WORK/have" "$WORK/want" | sort -u > "$WORK/cov"
    awk 'FILENAME == ARGV[1] {c[$0] = 1; next} !($0 in c)' "$WORK/cov" "$WORK/want" > "$WORK/cand"
    INC_N=$(grep -c . "$WORK/inc"); REM_N=$(grep -c . "$WORK/remove")
    ROOM=$((MAX - INC_N + REM_N))
    CAND_N=$(grep -c . "$WORK/cand")
    n=0
    while IFS= read -r d; do
        [ "$n" -lt "$ROOM" ] && [ "$n" -lt "$PER_RUN" ] || break
        [ $(($(date +%s) - START)) -lt "$TIME_LIMIT" ] || break
        alive "$d" || continue
        echo "$d" >> "$WORK/add"; n=$((n + 1))
    done < "$WORK/cand"
    FULL=0; [ "$ROOM" -gt "$n" ] || [ "$CAND_N" -le "$n" ] || FULL=1
    mv -f "$WORK/remove" "$WORK/$G.remove"; mv -f "$WORK/add" "$WORK/$G.add"
    printf 'CATS=%s\nCAND_N=%s\nFULL=%s\n' "$CATS" "$CAND_N" "$FULL" > "$WORK/$G.meta"
}

# apply GROUP: the plan, under the change lock against a fresh running-config:
# removals first (they make room); prints "added removed".
apply()
{
    G=$1
    GROUP=$G
    CATS=$(sed -n 's/^CATS=//p' "$WORK/$G.meta"); CAND_N=$(sed -n 's/^CAND_N=//p' "$WORK/$G.meta"); FULL=$(sed -n 's/^FULL=//p' "$WORK/$G.meta")
    items "$G" include | sort -u > "$WORK/inc"
    : > "$STATE/$G.last.tmp"
    A=0 R=0
    while IFS= read -r d; do
        has_line "$WORK/inc" "$d" || continue
        ndm "no object-group fqdn $G include $d" || continue
        drop "$STATE/$G.added" "$d"; misses_set "$G" "$d" 0
        echo "- $d" >> "$STATE/$G.last.tmp"; R=$((R + 1)); log "LIST_REMOVE|$G|$d"
    done < "$WORK/$G.remove"
    while IFS= read -r d; do
        has_line "$WORK/inc" "$d" && continue
        ndm "object-group fqdn $G include $d" || continue
        echo "$d" >> "$STATE/$G.added"
        echo "+ $d" >> "$STATE/$G.last.tmp"; A=$((A + 1)); log "LIST_ADD|$G|$d"
    done < "$WORK/$G.add"
    if [ $((A + R)) -gt 0 ]; then
        mv -f "$STATE/$G.last.tmp" "$STATE/$G.last"
    else
        rm -f "$STATE/$G.last.tmp"
    fi
    PENDING=$((${CAND_N:-0} - A)); [ "$PENDING" -ge 0 ] || PENDING=0
    [ -n "$CATS" ] || { status_write "mode=$(conf_mode "$G")" "categories=" "added=0" "removed=0" "pending=0" "full=0" "vward=$(grep -c . "$STATE/$G.added")"; echo "0 0"; return 0; }
    status_write "mode=$(conf_mode "$G")" "categories=$CATS" "added=$A" "removed=$R" "pending=$PENDING" "full=$FULL" "vward=$(grep -c . "$STATE/$G.added")"
    log "LIST_FILL|$G|added=$A|removed=$R|pending=$PENDING|full=$FULL|categories=$CATS"
    echo "$A $R"
}

save()
{
    ndm "system configuration save" || return 1
    mkdir -p "$(dirname "$REFRESH_TS")" 2>/dev/null && echo 0 > "$REFRESH_TS" 2>/dev/null
    return 0
}

case "$OP" in
    status)
        valid_group "$GROUP" || die invalid_group 64
        echo "mode=$(conf_mode "$GROUP")"
        [ -r "$STATE/$GROUP.status" ] && grep -E '^(ts|categories|added|removed|pending|full|vward)=' "$STATE/$GROUP.status"
        echo "undo=$([ -s "$STATE/$GROUP.last" ] && echo 1 || echo 0)"
        exit 0 ;;
    set)
        valid_group "$GROUP" || die invalid_group 64
        V=$(printf '%s' "${3:-}" | tr 'A-Z:' 'a-z,')
        case "$V" in
            auto|off) ;;
            *) printf '%s\n' "$V" | grep -Eq '^[a-z0-9_.-]{1,40}(,[a-z0-9_.-]{1,40}){0,4}$' || die invalid_value 64 ;;
        esac
        [ "$(conf_mode "$GROUP")" != "$V" ] || { echo "result=unchanged"; exit 0; }
        mkdir -p "$ETC" || die write_failed
        { [ ! -r "$CONF" ] || awk -F= -v g="$GROUP" '$1 != g' "$CONF"; echo "$GROUP=$V"; } > "$CONF.tmp" &&
            chmod 0600 "$CONF.tmp" && mv -f "$CONF.tmp" "$CONF" || die write_failed
        log "LIST_FILL_SET|$GROUP|$V"
        echo "result=changed"; exit 0 ;;
    run|undo) ;;
    *) echo "usage: $0 run [GROUP]|set GROUP auto|off|CATS|undo GROUP|status GROUP" >&2; exit 64 ;;
esac

[ -z "$GROUP" ] || valid_group "$GROUP" || die invalid_group 64
[ "$OP" = run ] || [ -n "$GROUP" ] || die invalid_group 64
vward_admission_enter list-fill || die updater_busy 75
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
if ! mkdir "$RUN_LOCK" 2>/dev/null; then
    rl_old=$(cat "$RUN_LOCK/pid" 2>/dev/null)
    if [ -n "$rl_old" ] && kill -0 "$rl_old" 2>/dev/null; then die list_fill_busy 75; fi
    rm -rf "${RUN_LOCK:?}"; mkdir "$RUN_LOCK" 2>/dev/null || die list_fill_busy 75
fi
RUN_LOCKED=1
echo $$ > "$RUN_LOCK/pid"
WORK=$(mktemp -d /tmp/vward-list-fill.XXXXXX) || die temporary_file_unavailable

if [ "$OP" = undo ]; then
    change_lock || die route_change_busy 75
    snapshot || die router_config_unavailable
    [ -s "$STATE/$GROUP.last" ] || { echo "result=unchanged"; exit 0; }
    touch_state "$GROUP"
    U=0
    while read -r s d; do
        case "$s" in
            +) ndm "no object-group fqdn $GROUP include $d" || continue
               drop "$STATE/$GROUP.added" "$d"
               has_line "$STATE/$GROUP.declined" "$d" || echo "$d" >> "$STATE/$GROUP.declined" ;;
            -) ndm "object-group fqdn $GROUP include $d" || continue
               has_line "$STATE/$GROUP.added" "$d" || echo "$d" >> "$STATE/$GROUP.added" ;;
            *) continue ;;
        esac
        U=$((U + 1))
    done < "$STATE/$GROUP.last"
    rm -f "$STATE/$GROUP.last"
    [ "$U" = 0 ] || save || die config_save_failed
    log "LIST_FILL_UNDO|$GROUP|changes=$U"
    echo "result=changed"; exit 0
fi

[ -s "$CATALOG" ] || die catalog_missing
snapshot || die router_config_unavailable
if [ -n "$GROUP" ]; then
    grep -q "^object-group fqdn $GROUP\$" "$WORK/rc" || die list_not_found
    echo "$GROUP" > "$WORK/groups"
else
    awk '/^object-group fqdn domain-list[0-9]+$/ {print $3}' "$WORK/rc" > "$WORK/groups"
fi
while IFS= read -r G0; do plan "$G0"; done < "$WORK/groups"
# Changes only now, briefly under the lock, against what the router has at this moment.
change_lock || die route_change_busy 75
snapshot || die router_config_unavailable
TOTAL=0
while IFS= read -r G0; do
    set -- $(apply "$G0")
    TOTAL=$((TOTAL + ${1:-0} + ${2:-0}))
done < "$WORK/groups"
if [ "$TOTAL" -gt 0 ]; then
    save || die config_save_failed
    echo "result=changed"
else
    echo "result=unchanged"
fi
