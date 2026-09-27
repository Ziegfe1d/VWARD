#!/bin/sh

# Domains Keenetic routes by name (an object-group fqdn with a route) are
# resolved through Keenetic's own DNS, so Keenetic learns every address a device
# gets for them, subdomains included, before the device connects.
#
# Devices keep asking AdGuard Home (their names and filtering stay).  AdGuard
# Home sends only these domains on to Keenetic's DNS with one row
# [/a.com/b.com/]LAN:53; Keenetic's DNS asks AdGuard Home back as the client
# "Keenetic DNS (VWARD)", which has the usual servers without that row, so there
# is no loop.  The row is only written while that client exists and the chain
# answers; it is removed before the client.
#
# Only when Keenetic's DNS itself asks AdGuard Home (ip name-server LAN:port):
# otherwise these domains would leave through Keenetic's own servers.
# Domains with their own row in AdGuard Home (Smart DNS) are left to that row.
#
#   vward-ads-privacy-route-dns.sh status
#   vward-ads-privacy-route-dns.sh on|off
#   vward-ads-privacy-route-dns.sh apply|tick   (tick: the scheduler, a check every 5 minutes)

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "FAIL: common library not found" >&2; exit 1; }
. "$LIB"

STATUS="${VWARD_ROUTE_DNS_STATUS:-/tmp/vward-route-dns.status}"
# Off unless switched on: on the owner's router Keenetic's DNS took the chain for a
# loop ("proxy loop detected" between two services on the router's address), dropped AdGuard Home
# as its server and lost its own DNS (2026-09-27).  The old "disabled" flag of
# 0.2.0-rc.1.fix.16 is gone with the default.
ENABLED_FLAG="${VWARD_ROUTE_DNS_ENABLED:-$ADS_ETC/route-dns.enabled}"
DISABLED_FLAG="${VWARD_ROUTE_DNS_DISABLED:-$ADS_ETC/route-dns.disabled}"
RCI_BASE="${VWARD_RCI_BASE:-http://127.0.0.1:79/rci}"
LOCK="${VWARD_ROUTE_DNS_LOCK:-/tmp/vward-route-dns.lock}"
NDMC="${VWARD_NDMC:-ndmc}"
EVERY="${VWARD_ROUTE_DNS_EVERY_SEC:-300}"
CLIENT_NAME="Keenetic DNS (VWARD)"

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
        if [ -e "$ENABLED_FLAG" ]; then echo "enabled=1"; else echo "enabled=0"; fi
        [ -r "$STATUS" ] && grep -E '^(ts|result|domains|skipped|changed_ts)=' "$STATUS"
        exit 0 ;;
    on) mkdir -p "$(dirname "$ENABLED_FLAG")" && : > "$ENABLED_FLAG" || exit 1; rm -f "$DISABLED_FLAG" ;;
    off) rm -f "$ENABLED_FLAG" || exit 1 ;;
    apply|tick) ;;
    *) echo "usage: $0 status|on|off|apply|tick" >&2; exit 64 ;;
esac

ENABLED=0; [ ! -e "$ENABLED_FLAG" ] || ENABLED=1
if [ "$OP" = tick ]; then
    # Off and nothing left in AdGuard Home: no work at all.
    case "$(status_value result)" in off|dns_lost) [ "$ENABLED" = 1 ] || exit 0 ;; esac
    LAST=$(ads_num "$(status_value ts)" 0)
    [ $(($(ads_epoch) - LAST)) -ge "$EVERY" ] || exit 0
fi
[ -s "$ADS_AGH_AUTH_FILE" ] || [ -n "${AGH_API_BASE:-}" ] || { status_write not_connected; echo "ROUTE_DNS=NOT_CONNECTED"; exit 0; }

ads_admission_enter ads-route-dns
WORK=""
cleanup()
{
    [ -z "$WORK" ] || rm -rf "${WORK:?}"
    ads_lock_release "$LOCK" 2>/dev/null || true
    ads_admission_leave
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
ads_lock_acquire "$LOCK" 120 || { echo "ROUTE_DNS=BUSY"; exit 75; }
WORK="$(mktemp -d /tmp/vward-route-dns.XXXXXX)" || ads_die "temporary directory unavailable"

# The router's LAN address and AdGuard Home's DNS port.
LAN="" PORT=""
pl_out=$(
    VWARD_DEVICE_CONFIG="$ADS_DEVICE_CONFIG"; export VWARD_DEVICE_CONFIG
    . "$ADS_DEVICE_PROFILE_LIB" >/dev/null 2>&1 || exit 1
    vward_profile_load >/dev/null 2>&1 || exit 1
    printf '%s %s\n' "${VWARD_LAN_ADDRESS:-}" "${VWARD_ADGUARD_CONFIG:-}"
) && set -- $pl_out && LAN=${1:-} &&
    PORT=$(awk '/^[^ #]/ {d = ($1 == "dns:")} d && $1 == "port:" {print $2; exit}' "${2:-/dev/null}" 2>/dev/null)
case "$PORT" in ''|*[!0-9]*) PORT="" ;; esac
[ -n "$LAN" ] && [ -n "$PORT" ] || { status_write profile_unavailable; echo "ROUTE_DNS=FAIL"; echo "ERROR=profile_unavailable"; exit 1; }
SRV="$LAN:53"

finish()
{
    fi_result=$1; shift
    status_write "$fi_result" "$@"
    echo "ROUTE_DNS=$(printf '%s' "$fi_result" | tr 'a-z' 'A-Z')"
    case "$fi_result" in ok|off|dns_lost|not_via_agh|no_domains) exit 0 ;; esac
    echo "ERROR=$fi_result"
    exit 1
}

ads_agh_api_get dns_info "$WORK/info.json" >/dev/null 2>&1 || finish agh_unavailable
ads_agh_api_get clients "$WORK/clients.json" >/dev/null 2>&1 || finish agh_unavailable
CHANGED_TS=$(status_value changed_ts)

# Keenetic's own DNS stopped answering while the chain is on: the chain goes at
# once and the switch is turned off (Keenetic takes AdGuard Home back by itself).
if [ "$ENABLED" = 1 ] && [ "$(status_value result)" = ok ]; then
    DNS_OK=$("$ADS_CURL" -s --max-time 5 "$RCI_BASE/show/internet/status" 2>/dev/null | "$ADS_JQ" -r '.["dns-accessible"] | tostring' 2>/dev/null)
    if [ "$DNS_OK" = false ]; then
        rm -f "$ENABLED_FLAG"
        ENABLED=0
        ads_log "ROUTE_DNS|auto_off|keenetic_dns_lost"
        AUTO_OFF=1
    fi
fi

# Wanted: the domains of every Keenetic group that has a route.
WANT=1
REASON=ok
if [ "$ENABLED" = 0 ]; then
    WANT=0 REASON=off
    [ "${AUTO_OFF:-0}" = 0 ] || REASON=dns_lost
    : > "$WORK/domains.txt"
else
    "$NDMC" -c "show running-config" > "$WORK/rc.txt" 2>/dev/null && [ -s "$WORK/rc.txt" ] || finish router_unavailable
    # Keenetic's DNS must itself ask AdGuard Home, or these domains would leave another way.
    if ! awk -v s="$LAN:$PORT" '$1 == "ip" && $2 == "name-server" && $3 == s && (NF == 3 || $4 == "\"\"") {f = 1} END {exit !f}' "$WORK/rc.txt"; then
        WANT=0 REASON=not_via_agh
    fi
    awk '$1 == "route" && $2 == "object-group" && NF >= 4 {print $3}' "$WORK/rc.txt" | sort -u > "$WORK/groups.txt"
    awk 'NR == FNR {g[$1] = 1; next}
         $1 == "object-group" && $2 == "fqdn" {f = ($3 in g); next}
         /^!/ {f = 0}
         f && $1 == "include" {print tolower($2)}' "$WORK/groups.txt" "$WORK/rc.txt" |
        sed 's/^\*\.//' |
        awk 'length($0) <= 253 && /^[a-z0-9][a-z0-9.-]*[a-z0-9]$/ && index($0, ".") && $0 !~ /\.\./ && $0 !~ /^[0-9.]+$/' |
        sort -u > "$WORK/domains.txt"
    [ -s "$WORK/domains.txt" ] || { [ "$WANT" = 0 ] || { WANT=0 REASON=no_domains; }; }
fi

# The rows AdGuard Home has, ours ([/...]LAN:53) set apart; Smart DNS domains keep their row.
"$ADS_JQ" -n --slurpfile info "$WORK/info.json" --rawfile doms "$WORK/domains.txt" --arg srv "$SRV" --argjson want "$WANT" '
    ($info[0].upstream_dns // []) as $all |
    def ours: type == "string" and startswith("[/") and endswith("]" + $srv);
    [$all[] | select(ours | not)] as $base |
    [$base[] | select(type == "string" and startswith("[/")) | ltrimstr("[/") | split("]")[0] | split("/")[] | select(length > 0)] as $own |
    [$doms | split("\n")[] | select(length > 0)] as $d |
    [$d[] | . as $x | select(any($own[]; . == $x) | not)] as $keep |
    {all: $all, base: $base, keep: $keep, skipped: (($d | length) - ($keep | length)),
     client_up: [$base[] | select(type == "string" and length > 0 and (startswith("#") | not))],
     wanted: (if $want == 1 and ($keep | length) > 0 then $base + ["[/" + ($keep | join("/")) + "/]" + $srv] else $base end)}' \
    > "$WORK/plan.json" 2>/dev/null || finish plan_failed
NKEEP=$("$ADS_JQ" '.keep | length' "$WORK/plan.json")
SKIPPED=$("$ADS_JQ" '.skipped' "$WORK/plan.json")
[ "$WANT" = 0 ] || [ "$NKEEP" -gt 0 ] || { WANT=0 REASON=no_domains; }
ROWS_DIFFER=1
"$ADS_JQ" -e '.all == .wanted' "$WORK/plan.json" >/dev/null && ROWS_DIFFER=0

# Another client holding the router's address: our client cannot exist, so no row either.
if "$ADS_JQ" -e --arg n "$CLIENT_NAME" --arg a "$LAN" \
    'any((.clients // [])[]; .name != $n and any((.ids // [])[]; . == $a or . == "127.0.0.1"))' "$WORK/clients.json" >/dev/null; then
    [ "$WANT" = 0 ] || { WANT=0 REASON=client_conflict; }
fi
HAVE_CLIENT=0
"$ADS_JQ" -e --arg n "$CLIENT_NAME" 'any((.clients // [])[]; .name == $n)' "$WORK/clients.json" >/dev/null && HAVE_CLIENT=1

# set_rows JSONPATH: write AdGuard Home's server list (.base or .wanted from the plan).
set_rows()
{
    "$ADS_JQ" "{upstream_dns: $1}" "$WORK/plan.json" > "$WORK/rows.json" &&
        ads_agh_api_post dns_config "$WORK/rows.json" "$WORK/rows.out" >/dev/null 2>&1
}
cache_clear() { echo '{}' > "$WORK/empty.json"; ads_agh_api_post cache_clear "$WORK/empty.json" "$WORK/cc.out" >/dev/null 2>&1 || true; }

if [ "$WANT" = 0 ]; then
    # Off: the row first, then the client (never a row without the client).
    if "$ADS_JQ" -e '.all != .base' "$WORK/plan.json" >/dev/null; then
        set_rows .base || finish apply_failed
        cache_clear
        CHANGED_TS=$(ads_epoch)
        ads_log "ROUTE_DNS|rows_removed|$REASON"
    fi
    if [ "$HAVE_CLIENT" = 1 ]; then
        "$ADS_JQ" -n --arg n "$CLIENT_NAME" '{name: $n}' > "$WORK/del.json"
        ads_agh_api_post clients/delete "$WORK/del.json" "$WORK/del.out" >/dev/null 2>&1 || finish apply_failed
        CHANGED_TS=$(ads_epoch)
        ads_log "ROUTE_DNS|client_removed|$REASON"
    fi
    finish "$REASON" "domains=0" "skipped=$SKIPPED" "changed_ts=${CHANGED_TS:-}"
fi

# On: the client first, with AdGuard Home's servers minus our row.
"$ADS_JQ" --slurpfile p "$WORK/plan.json" --arg n "$CLIENT_NAME" --arg a "$LAN" '
    ([(.clients // [])[] | select(.name == $n)][0]) as $old |
    ($old // {name: $n, use_global_settings: true, use_global_blocked_services: true, filtering_enabled: true,
              parental_enabled: false, safebrowsing_enabled: false, ignore_querylog: false,
              ignore_statistics: false, tags: []}) |
    .ids = [$a, "127.0.0.1"] | .upstreams = $p[0].client_up |
    .upstreams_cache_enabled = true |
    .upstreams_cache_size = (if (.upstreams_cache_size // 0) > 0 then .upstreams_cache_size else 1048576 end) |
    if $old == null then {add: .} elif $old == . then {} else {update: {name: $n, data: .}} end' \
    "$WORK/clients.json" > "$WORK/client-op.json" 2>/dev/null || finish plan_failed
if "$ADS_JQ" -e '.add' "$WORK/client-op.json" >/dev/null; then
    "$ADS_JQ" '.add' "$WORK/client-op.json" > "$WORK/client.json"
    ads_agh_api_post clients/add "$WORK/client.json" "$WORK/client.out" >/dev/null 2>&1 || finish apply_failed
    CHANGED_TS=$(ads_epoch)
    ads_log "ROUTE_DNS|client_added"
elif "$ADS_JQ" -e '.update' "$WORK/client-op.json" >/dev/null; then
    "$ADS_JQ" '.update' "$WORK/client-op.json" > "$WORK/client.json"
    ads_agh_api_post clients/update "$WORK/client.json" "$WORK/client.out" >/dev/null 2>&1 || finish apply_failed
    CHANGED_TS=$(ads_epoch)
    ads_log "ROUTE_DNS|client_updated"
fi

if [ "$ROWS_DIFFER" = 1 ]; then
    # The chain must answer before any domain is sent into it.
    "$ADS_JQ" -n --arg s "$SRV" --slurpfile i "$WORK/info.json" \
        '{upstream_dns: [$s], bootstrap_dns: ($i[0].bootstrap_dns // [])}' > "$WORK/test.json"
    if ! ads_agh_api_post test_upstream_dns "$WORK/test.json" "$WORK/test.out" >/dev/null 2>&1 ||
       ! "$ADS_JQ" -e --arg s "$SRV" '.[$s] == "OK"' "$WORK/test.out" >/dev/null 2>&1; then
        # Nothing of ours may stay: an old row goes, then the client.
        if "$ADS_JQ" -e '.all != .base' "$WORK/plan.json" >/dev/null; then set_rows .base || true; fi
        "$ADS_JQ" -n --arg n "$CLIENT_NAME" '{name: $n}' > "$WORK/del.json"
        ads_agh_api_post clients/delete "$WORK/del.json" "$WORK/del.out" >/dev/null 2>&1 || true
        ads_log "ROUTE_DNS|chain_failed"
        finish chain_failed "domains=0" "skipped=$SKIPPED" "changed_ts=$(ads_epoch)"
    fi
    set_rows .wanted || finish apply_failed
    cache_clear
    CHANGED_TS=$(ads_epoch)
    ads_log "ROUTE_DNS|rows_set|domains=$NKEEP|skipped=$SKIPPED"
fi
finish ok "domains=$NKEEP" "skipped=$SKIPPED" "changed_ts=${CHANGED_TS:-}"
