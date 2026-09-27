#!/bin/sh

# Names in AdGuard Home the devices Keenetic knows, through AdGuard Home's API:
# no restart, no DNS gap.  Keenetic is read through RCI (no session lines in
# its log).  Clients are added or renamed, and an address a device got from
# another one is moved over; nothing is deleted and per-client settings stay.
#
#   vward-ads-privacy-clients.sh [tick]   cron path: sync when the devices changed
#   vward-ads-privacy-clients.sh sync     sync now
#   vward-ads-privacy-clients.sh status   last result, key=value
#   vward-ads-privacy-clients.sh on|off   switch the sync (Panel)

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "FAIL: common library not found" >&2; exit 1; }
. "$LIB"

STATUS="${VWARD_ADS_CLIENTS_STATUS:-/tmp/vward-ads-clients.status}"
DISABLED_FLAG="${VWARD_ADS_CLIENTS_DISABLED:-$ADS_ETC/clients-sync.disabled}"
CRONTAB_FILE="${VWARD_CRONTAB_FILE:-/opt/var/spool/cron/crontabs/root}"
OLD_SCRIPT=agh-keenetic-clients-sync.sh
RCI_BASE="${VWARD_RCI_BASE:-http://127.0.0.1:79/rci}"
# A full pass at least this often even when the devices look the same.
FULL_EVERY="${VWARD_ADS_CLIENTS_FULL_SEC:-3600}"
LOCK="${VWARD_ADS_CLIENTS_LOCK:-/tmp/vward-ads-clients.lock}"

OP="${1:-tick}"

status_value() { [ -r "$STATUS" ] && awk -F= -v k="$1" '$1 == k {print substr($0, length(k) + 2); exit}' "$STATUS"; }

# status_write RESULT [key=value...]: the last run, kept in RAM.
status_write()
{
    sw_tmp="$STATUS.$$"
    {
        echo "ts=$(ads_epoch)"
        echo "result=$1"
        shift
        for sw_kv in "$@"; do echo "$sw_kv"; done
    } > "$sw_tmp" && mv -f "$sw_tmp" "$STATUS"
}

case "$OP" in
    status)
        if [ -e "$DISABLED_FLAG" ]; then echo "enabled=0"; else echo "enabled=1"; fi
        [ -r "$STATUS" ] && grep -E '^(ts|result|devices|clients|added|updated|failed|changed_ts|note)=' "$STATUS"
        exit 0 ;;
    on)
        rm -f "$DISABLED_FLAG" || exit 1
        echo "CLIENTS=ON"; exit 0 ;;
    off)
        mkdir -p "$(dirname "$DISABLED_FLAG")" && : > "$DISABLED_FLAG" || exit 1
        echo "CLIENTS=OFF"; exit 0 ;;
    tick|sync) ;;
    *) echo "usage: $0 [tick|sync|status|on|off]" >&2; exit 64 ;;
esac

[ ! -e "$DISABLED_FLAG" ] || { status_write disabled; echo "CLIENTS=DISABLED"; exit 0; }
# The old script rewrites AdGuardHome.yaml with a restart; two writers would fight.
if [ -r "$CRONTAB_FILE" ] && grep -v '^[[:space:]]*#' "$CRONTAB_FILE" | grep -Fq "$OLD_SCRIPT"; then
    status_write old_script "note=$OLD_SCRIPT"
    echo "CLIENTS=OLD_SCRIPT"
    exit 0
fi
[ -s "$ADS_AGH_AUTH_FILE" ] || [ -n "${AGH_API_BASE:-}" ] || { status_write not_connected; echo "CLIENTS=NOT_CONNECTED"; exit 0; }

ads_admission_enter ads-clients
WORK=""
cleanup()
{
    [ -z "$WORK" ] || rm -rf "${WORK:?}"
    ads_lock_release "$LOCK" 2>/dev/null || true
    ads_admission_leave
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
ads_lock_acquire "$LOCK" 300 || { echo "CLIENTS=BUSY"; exit 0; }
WORK="$(mktemp -d /tmp/vward-ads-clients.XXXXXX)" || ads_die "temporary directory unavailable"

# Devices Keenetic has registered, online, with a name and an address.
"$ADS_CURL" -fsS --connect-timeout 2 --max-time 10 "$RCI_BASE/show/ip/hotspot" -o "$WORK/hotspot.json" 2>/dev/null &&
"$ADS_JQ" -c '
    def ipv4: type == "string" and (split(".") as $p | ($p | length) == 4 and
        all($p[]; (tonumber? // -1) as $n | $n >= 0 and $n <= 255 and ($n | tostring) == .));
    [(.host // [])[] | select(type == "object" and .registered == true and .active == true and
        ((.name // "") | type == "string" and length > 0) and ((.mac // "") | type == "string" and length == 17) and
        (.ip | ipv4) and .ip != "0.0.0.0") | {name, mac: (.mac | ascii_downcase), ip}] |
    reduce .[] as $h ([]; if any(.[]; .name == $h.name or .mac == $h.mac or .ip == $h.ip) then . else . + [$h] end) |
    sort_by(.mac)' "$WORK/hotspot.json" > "$WORK/hosts.json" 2>/dev/null ||
    { status_write router_unavailable; echo "CLIENTS=ROUTER_UNAVAILABLE"; exit 0; }

DEVICES=$("$ADS_JQ" 'length' "$WORK/hosts.json")
SIG=$(cksum < "$WORK/hosts.json" | awk '{print $1 ":" $2}')
LAST_TS=$(ads_num "$(status_value ts)" 0)
NOW=$(ads_epoch)
if [ "$OP" = tick ] && [ "$(status_value result)" = ok ] && [ "$(status_value sig)" = "$SIG" ] &&
   [ $((NOW - LAST_TS)) -lt "$FULL_EVERY" ]; then
    echo "CLIENTS=UNCHANGED"
    exit 0
fi

ads_agh_api_get clients "$WORK/clients.json" 2>/dev/null ||
    { status_write agh_unavailable "devices=$DEVICES"; echo "CLIENTS=AGH_UNAVAILABLE"; exit 0; }

# The plan: one JSON line per API call: ids leaving clients, then renames and
# new ids, then new clients.
"$ADS_JQ" -c --slurpfile hosts "$WORK/hosts.json" '
    def ipv4: type == "string" and (split(".") as $p | ($p | length) == 4 and
        all($p[]; (tonumber? // -1) as $n | $n >= 0 and $n <= 255 and ($n | tostring) == .));
    def mac: type == "string" and length == 17 and (split(":") | length) == 6;
    def has_id($x): any((.ids // [])[]; ascii_downcase == $x);
    def owner($C; $h):
        ([range(0; $C | length) | select($C[.] | has_id($h.mac))] +
         [range(0; $C | length) | select(($C[.] | has_id($h.ip)) and (any(($C[.].ids // [])[]; mac) | not))])[0];

    ((.clients // []) | map(.ids = (.ids // []))) as $C0 |
    (reduce $hosts[0][] as $h ({C: $C0, add: [], note: []};
        owner(.C; $h) as $m |
        # The address moved to this device: take it from any other client.
        reduce range(0; .C | length) as $i (.;
            if $i != $m and (.C[$i] | has_id($h.ip)) then
                ((.C[$i].ids | map(select(. != $h.ip)))) as $rest |
                if ($rest | length) > 0 then .C[$i].ids = $rest
                else .note += ["address_held:" + .C[$i].name] end
            else . end) |
        if $m != null then
            .C[$m].ids = ([$h.ip, $h.mac] + (.C[$m].ids | map(select((ipv4 | not) and ascii_downcase != $h.mac)))) |
            if .C[$m].name == $h.name then .
            elif any(.C[]; .name == $h.name) or any(.add[]; .name == $h.name) then .note += ["name_taken:" + $h.name]
            else .C[$m].name = $h.name end
        elif any(.C[]; .name == $h.name) then .note += ["name_taken:" + $h.name]
        else .add += [{name: $h.name, ids: [$h.ip, $h.mac], use_global_settings: true,
                       use_global_blocked_services: true, filtering_enabled: true, parental_enabled: false,
                       safebrowsing_enabled: false, ignore_querylog: false, ignore_statistics: false,
                       tags: [], upstreams: []}]
        end)) as $r |
    [range(0; $C0 | length) | select($C0[.] != $r.C[.]) | {old: $C0[.], new: $r.C[.]}] as $changed |
    # Ids leaving a client are dropped first, so a swap of addresses between
    # two devices never meets "this id belongs to another client".
    ($changed[] | (.old.ids - (.old.ids - .new.ids)) as $keep |
        select(($keep | length) > 0 and ($keep | length) < (.old.ids | length)) |
        {path: "clients/update", release: true, body: {name: .old.name, data: (.old | .ids = $keep)}}),
    ($changed[] | {path: "clients/update", body: {name: .old.name, data: .new}}),
    ($r.add[] | {path: "clients/add", body: .}),
    ($r.note[] | {note: .})
' "$WORK/clients.json" > "$WORK/plan.jsonl" 2>/dev/null ||
    { status_write plan_failed "devices=$DEVICES"; echo "CLIENTS=PLAN_FAILED"; exit 1; }

CLIENTS=$("$ADS_JQ" '(.clients // []) | length' "$WORK/clients.json" 2>/dev/null)
ADDED=0 UPDATED=0 FAILED=0 N=0
NOTES=$("$ADS_JQ" -r 'select(.note) | .note' "$WORK/plan.jsonl" | tr '\n' ' ')
"$ADS_JQ" -c 'select(.path)' "$WORK/plan.jsonl" > "$WORK/calls.jsonl"
while IFS= read -r CALL; do
    N=$((N + 1))
    printf '%s\n' "$CALL" | "$ADS_JQ" -c '.body' > "$WORK/body.$N.json"
    CALL_PATH=$(printf '%s\n' "$CALL" | "$ADS_JQ" -r 'if .release then "release" else .path end')
    WHO=$("$ADS_JQ" -r '.name' "$WORK/body.$N.json")
    API_PATH=clients/update
    [ "$CALL_PATH" != clients/add ] || API_PATH=clients/add
    if ads_agh_api_post "$API_PATH" "$WORK/body.$N.json" "$WORK/out.$N" 2>"$WORK/err.$N"; then
        case "$CALL_PATH" in clients/add) ADDED=$((ADDED + 1)) ;; clients/update) UPDATED=$((UPDATED + 1)) ;; esac
        ads_log "CLIENTS|$CALL_PATH|$WHO"
    else
        FAILED=$((FAILED + 1))
        ads_log "CLIENTS|$CALL_PATH-failed|$WHO|$(tr '\n' ' ' < "$WORK/err.$N" | cut -c1-160)"
    fi
done < "$WORK/calls.jsonl"

CHANGED_TS=$(status_value changed_ts)
[ $((ADDED + UPDATED)) -eq 0 ] || CHANGED_TS=$NOW
RESULT=ok
[ "$FAILED" -eq 0 ] || RESULT=partial
# A failed call is retried on the next tick: the signature is kept only on success.
[ "$RESULT" = ok ] || SIG=""
status_write "$RESULT" "devices=$DEVICES" "clients=$((CLIENTS + ADDED))" "added=$ADDED" "updated=$UPDATED" \
    "failed=$FAILED" "changed_ts=${CHANGED_TS:-}" "note=$NOTES" "sig=$SIG"
echo "CLIENTS=$(printf '%s' "$RESULT" | tr 'a-z' 'A-Z')"
echo "DEVICES=$DEVICES ADDED=$ADDED UPDATED=$UPDATED FAILED=$FAILED"
[ "$FAILED" -eq 0 ]
