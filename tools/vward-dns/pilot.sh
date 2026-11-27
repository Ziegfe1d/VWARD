#!/bin/sh
# Optional, bounded Keenetic pilot. The global DNS handler has no pilot mode.
set -f
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
umask 077
BASE=$(CDPATH='' cd -- "$(dirname "$0")" && pwd) || exit 1
BIN=${VWARD_DNS_BIN:-$BASE/vward-dns}
ROOT=${VWARD_ROOT_PREFIX:-}
PROFILE=${VWARD_PROFILE_LIB:-$ROOT/opt/lib/vward/vward-device-profile.sh}
ADMISSION=${VWARD_ADMISSION_LIB:-$ROOT/opt/lib/vward/vward-runtime-admission.sh}
STATE=${VWARD_DNS_PILOT_STATE:-$ROOT/opt/var/lib/vward/dns-pilot}
LOCK=${VWARD_ROUTE_CHANGE_LOCK:-$ROOT/tmp/vward-route-change.lock}
NDMC=${VWARD_NDMC:-ndmc}
PORT=65153
WORK=
LOCKED=0
UNDO=0
SCOPE_AWK='
    function overlaps(d, i, a, b) {
        d = tolower(d); sub(/\.$/, "", d); sub(/^\*\./, "", d)
        for (i in zones) {
            a = "." zones[i]; b = "." d
            if (d == zones[i] || (length(d) > length(a) && substr(d, length(d)-length(a)+1) == a) ||
                (length(zones[i]) > length(b) && substr(zones[i], length(zones[i])-length(b)+1) == b)) return 1
        }
        return 0
    }
    BEGIN {split(domains, zones, "\n")}
'

fail() { printf 'error=%s\n' "$1" >&2; exit 1; }

ndmc_timed() {
    "$NDMC" -c "$1" & nd_pid=$!
    (
        sleep 8 & pause_pid=$!
        trap 'kill "$pause_pid" 2>/dev/null; exit 0' TERM
        wait "$pause_pid" && kill "$nd_pid" 2>/dev/null
    ) </dev/null >/dev/null 2>&1 & nd_timer=$!
    wait "$nd_pid"; nd_rc=$?
    nd_pid=
    kill "$nd_timer" 2>/dev/null || :
    wait "$nd_timer" 2>/dev/null || :
    nd_timer=
    return "$nd_rc"
}

# Includes both suffix directions to catch overlapping user bindings, as well
# as domain-specific encrypted upstreams. The global chain is outside the scope.
snapshot() {
    ndmc_timed "show running-config" > "$WORK/config" 2>/dev/null || return 1
    awk -v domains="$DOMAINS" -v iface="$TUNNEL" "$SCOPE_AWK"'
        {sub(/\r$/, "")}
        $1 == "interface" && $2 == iface {seen_interface = 1}
        $1 == "!" {seen_separator = 1}
        ($1 == "ip" || $1 == "ipv6") && $2 == "name-server" && NF >= 4 && overlaps($4) {
            $1 = $1; print; next
        }
        $1 == "https" || $1 == "tls" || $1 == "dns-proxy" || $1 == "filter" {
            for (i = 1; i < NF; i++) if ($i == "domain" && overlaps($(i+1))) {print "foreign encrypted DNS rule"; next}
        }
        END {if (!seen_interface || !seen_separator) exit 1}
    ' "$WORK/config" > "$WORK/rows" || return 1
    LC_ALL=C sort "$WORK/rows" > "$1"
}

ndm() {
    nd_status=0
    ndmc_timed "$1" > "$WORK/ndm.reply" 2>&1 || nd_status=$?
    if [ "$nd_status" -eq 0 ] &&
       ! grep -Eqi '(^|[^a-z])(error|failed|invalid|unknown command|not found|no such entry)' "$WORK/ndm.reply"; then
        return 0
    fi
    printf 'ndmc_failed rc=%s command=%s\n' "$nd_status" "$1" >&2
    awk 'NR > 3 {exit} {print "ndmc_reply: " substr($0, 1, 220)}' "$WORK/ndm.reply" >&2
    return 1
}

# The Viva BusyBox has awk but no comm. Count duplicates so the same scope
# checks work even when the running configuration contains repeated entries.
compare_rules() {
    case "$1" in -23|-12) ;; *) return 2 ;; esac
    [ -r "$2" ] && [ -r "$3" ] || return 1
    awk -v mode="$1" '
        FILENAME == ARGV[1] { count[$0]++; next }
        count[$0] > 0 { count[$0]--; if (mode == "-12") print; next }
        mode == "-23" { print }
    ' "$3" "$2"
}

# Every remembered rule is validated against the data generated from the fixed pilot scope.
# Recovery tolerates a partially executed switch or a lost response to a Keenetic command.
restore() {
    [ -f "$STATE/pending" ] && [ ! -L "$STATE/pending" ] || return 1
    cmp -s "$STATE/pending" "$WORK/recovery" || return 1
    snapshot "$WORK/current" || return 1
    compare_rules -23 "$WORK/current" "$WORK/allowed" > "$WORK/diff" && [ ! -s "$WORK/diff" ] || return 1
    compare_rules -23 "$WORK/before" "$WORK/current" > "$WORK/diff" || return 1
    while IFS= read -r rule; do ndm "$rule" || :; done < "$WORK/diff"
    # Read the new state before taking out the local server so there is always a
    # configured path back. Running-config proof is distinct from DNS success.
    snapshot "$WORK/current" || return 1
    compare_rules -23 "$WORK/before" "$WORK/current" > "$WORK/diff" && [ ! -s "$WORK/diff" ] || return 1
    compare_rules -12 "$WORK/pilot" "$WORK/current" > "$WORK/diff" || return 1
    while IFS= read -r rule; do
        ndm "no $rule" || :
    done < "$WORK/diff"
    snapshot "$WORK/current" && cmp -s "$WORK/current" "$WORK/before" || return 1
    # An accepted Keenetic command can leave rules inactive in ndnproxy. Keep
    # the recovery record until the previous rules are back in both places.
    if ! wait_live_rules "$WORK/before"; then
        [ -s "$WORK/before" ] && repair_legacy_live || return 1
    fi
    rm -f "$STATE/pending"
}

cleanup() {
    status=$?
    trap '' HUP INT TERM
    [ -z "${hold_pid:-}" ] || { kill "$hold_pid" 2>/dev/null; wait "$hold_pid" 2>/dev/null; }
    [ -z "${nd_pid:-}" ] || { kill "$nd_pid" 2>/dev/null; wait "$nd_pid" 2>/dev/null; }
    [ -z "${nd_timer:-}" ] || { kill "$nd_timer" 2>/dev/null; wait "$nd_timer" 2>/dev/null; }
    if [ "$UNDO" = 1 ]; then
        if restore; then echo "result=original_dns_configuration_restored"
        else printf 'error=dns_restore_unverified recovery=%s\n' "$STATE/pending" >&2; status=1; fi
    fi
    [ "$LOCKED" = 0 ] || vward_lock_release "$LOCK" || status=1
    [ -z "$WORK" ] || rm -rf "${WORK:?}"
    command -v vward_admission_leave >/dev/null 2>&1 && vward_admission_leave
    trap - EXIT
    exit "$status"
}

read_live_rules() {
    live_file=
    for live in ${VWARD_NDNPROXY_CONF:-/var/ndnproxymain.conf /tmp/ndnproxymain.conf}; do
        [ ! -r "$live" ] || { live_file=$live; break; }
    done
    [ -n "$live_file" ] || return 1
    awk -v domains="$DOMAINS" -v upstream="$PILOT_ADDRESS:$PORT" -v iface="$TUNNEL" "$SCOPE_AWK"'
        BEGIN {for (i in zones) selected[zones[i]] = 1}
        $1 == "dns_server" && $2 == "=" && NF >= 3 {
            if (NF == 3 || $4 == ".") {
                endpoint = $3; gsub(/\[|\]/, "", endpoint)
                if (endpoint ~ /^[0-9]+\.[0-9.]+(:[0-9]+)?$/ || endpoint ~ /^[0-9A-Fa-f.:]*:[0-9A-Fa-f.:]+$/)
                    seen_default = 1
                next
            }
            name = tolower($4); sub(/\.$/, "", name)
            if (!overlaps(name)) next
            seen_scoped = 1
            if (!selected[name]) {print "overlapping live DNS rule " name; next}
            if ($3 == upstream) {print "ip name-server " $3 " " name; next}
            address = $3; sub(/:53$/, "", address)
            if (address == "1.1.1.1" || address == "8.8.8.8")
                print "ip name-server " address " " name " on " iface
            else
                print "unexpected live DNS upstream " name
        }
        END {if (!seen_default && !seen_scoped) exit 1}
    ' "$live_file" > "$WORK/live-unsorted" || return 1
    LC_ALL=C sort "$WORK/live-unsorted" > "$WORK/live"
}

wait_live_rules() {
    live_left=5
    until read_live_rules && cmp -s "$WORK/live" "$1"; do
        [ "$live_left" -gt 0 ] || return 1
        live_left=$((live_left - 1))
        sleep 1
    done
}

repair_legacy_live() {
    read_live_rules && [ -s "$WORK/live" ] || return 1
    compare_rules -23 "$WORK/live" "$WORK/before" > "$WORK/diff" && [ ! -s "$WORK/diff" ] || return 1
    cp "$WORK/live" "$WORK/live-before-repair" || return 1
    snapshot "$WORK/current" && cmp -s "$WORK/current" "$WORK/before" || return 1
    read_live_rules && cmp -s "$WORK/live" "$WORK/live-before-repair" || return 1
    compare_rules -23 "$WORK/before" "$WORK/live" > "$WORK/diff" && [ -s "$WORK/diff" ] || return 1
    while IFS= read -r rule; do
        ndm "no $rule" || :
        ndm "$rule" || :
    done < "$WORK/diff"
    snapshot "$WORK/current" && cmp -s "$WORK/current" "$WORK/before" && wait_live_rules "$WORK/before"
}

valid_baseline() {
    [ -f "$1" ] && { [ ! -s "$1" ] || cmp -s "$1" "$WORK/legacy"; }
}

capture_baseline() {
    snapshot "$WORK/current" && valid_baseline "$WORK/current" || fail dns_scope_differs_from_expected
    read_live_rules && cmp -s "$WORK/live" "$WORK/current" || fail live_rules_unverified
    cp "$WORK/current" "$WORK/before" || fail cannot_prepare_restore
}

prepare_recovery() {
    LC_ALL=C sort "$WORK/before" "$WORK/pilot" > "$WORK/allowed" || return 1
    {
        if [ "$LEGACY_RECORD" = 0 ]; then
            printf 'pilot_address=%s\n' "$PILOT_ADDRESS"
        fi
        cat "$WORK/before"
    } > "$WORK/recovery"
}

[ "$#" = 1 ] || fail usage
case "$1" in serve|probe|plan|trial|restore) ;; *) fail usage ;; esac
HOLD_SECONDS=0
if [ "$1" = trial ]; then
    HOLD_SECONDS=${VWARD_DNS_PILOT_HOLD_SECONDS:-0}
    case "$HOLD_SECONDS" in *[!0-9]*) fail invalid_hold_seconds ;; esac
    [ "$HOLD_SECONDS" -le 180 ] 2>/dev/null || fail invalid_hold_seconds
fi
[ -x "$BIN" ] || fail binary_missing
[ -r "$PROFILE" ] || fail profile_missing
. "$PROFILE"
vward_profile_load || fail profile_unavailable
PILOT_ADDRESS=${VWARD_LAN_ADDRESS:-}
LEGACY_RECORD=0
if [ "$1" = restore ]; then
    [ -f "$STATE/pending" ] && [ ! -L "$STATE/pending" ] || fail missing_recovery_record
    IFS= read -r pending_first < "$STATE/pending" || fail invalid_recovery_record
    case "$pending_first" in
        pilot_address=*) PILOT_ADDRESS=${pending_first#pilot_address=} ;;
        'ip name-server '*) PILOT_ADDRESS=127.0.0.1; LEGACY_RECORD=1 ;;
        *) fail invalid_recovery_record ;;
    esac
fi
vward_valid_ipv4 "$PILOT_ADDRESS" || fail invalid_pilot_address
case "$PILOT_ADDRESS" in
    0.*) fail invalid_pilot_address ;;
    127.*) [ "$LEGACY_RECORD" = 1 ] || fail invalid_pilot_address ;;
esac
[ "$1" != probe ] || exec "$BIN" probe -port "$PORT" -address "$PILOT_ADDRESS"
TUNNEL=${VWARD_TUNNEL_INTERFACE:-}
DEVICE=${VWARD_TUNNEL_DEVICE:-}
case "$TUNNEL" in OpkgTun[0-9]) ;; *) fail not_an_opkg_tunnel ;; esac
[ "$DEVICE" = "$(printf '%s' "$TUNNEL" | tr 'A-Z' 'a-z')" ] || fail tunnel_device_unverified
[ "$1" != serve ] || exec "$BIN" serve -tunnel "$DEVICE" -port "$PORT" -address "$PILOT_ADDRESS"

DOMAINS=$("$BIN" domains) || fail invalid_pilot_domains
[ "$(printf '%s\n' "$DOMAINS" | grep -Ec '^[a-z0-9-]+(\.[a-z0-9-]+)+$')" = 8 ] &&
    [ "$(printf '%s\n' "$DOMAINS" | wc -l)" -eq 8 ] || fail invalid_pilot_domains
WORK=$(mktemp -d "$ROOT/tmp/vward-dns-pilot.XXXXXX") || fail work_directory
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
for domain in $DOMAINS; do
    for resolver in 8.8.8.8 1.1.1.1; do
        printf 'ip name-server %s %s on %s\n' "$resolver" "$domain" "$TUNNEL"
    done
done | LC_ALL=C sort > "$WORK/legacy" || fail cannot_prepare_restore
for domain in $DOMAINS; do
    printf 'ip name-server %s:%s %s\n' "$PILOT_ADDRESS" "$PORT" "$domain"
done | LC_ALL=C sort > "$WORK/pilot" || fail cannot_prepare_restore
if [ "$1" = plan ]; then
    capture_baseline
    count=$(awk 'END {print NR}' "$WORK/before") || fail cannot_count_baseline
    echo "result=plan_ready tunnel=$TUNNEL pilot_address=$PILOT_ADDRESS port=$PORT domains=8 current_rules=$count active_rules=$count"
    exit 0
fi

# Reuse VWARD's updater admission and route-change lock. The pilot must not
# bypass a router where the routing journal already owns native writes.
[ ! -e "$ROOT/opt/var/lib/vward/routing" ] && [ ! -L "$ROOT/opt/var/lib/vward/routing" ] ||
    fail routing_journal_present
[ -r "$ADMISSION" ] || fail admission_library_missing
. "$ADMISSION"
vward_admission_enter dns-pilot || fail updater_busy
vward_lock_take "$LOCK" || fail route_change_busy
LOCKED=1
if [ "$1" = restore ]; then
    if [ "$LEGACY_RECORD" = 1 ]; then
        cp "$STATE/pending" "$WORK/before" && cmp -s "$WORK/before" "$WORK/legacy" || fail invalid_recovery_record
    else
        sed '1d' "$STATE/pending" > "$WORK/before" && valid_baseline "$WORK/before" || fail invalid_recovery_record
    fi
    prepare_recovery || fail cannot_prepare_restore
    restore || fail dns_restore_unverified
    echo "result=original_dns_configuration_restored"
    exit 0
fi

[ ! -e "$STATE/pending" ] && [ ! -L "$STATE/pending" ] || fail prior_trial_requires_restore
capture_baseline
prepare_recovery || fail cannot_prepare_restore
"$BIN" probe -port "$PORT" -address "$PILOT_ADDRESS" || fail local_resolver_failed
"$BIN" health -port "$PORT" -address "$PILOT_ADDRESS" >/dev/null || fail local_health_unverified
mkdir -p "$STATE" && [ -d "$STATE" ] && [ ! -L "$STATE" ] && [ -O "$STATE" ] || fail unsafe_state_directory
pending=$(mktemp "$STATE/pending.XXXXXX") || fail cannot_record_restore
if ! cat "$WORK/recovery" > "$pending" || ! mv "$pending" "$STATE/pending"; then
    rm -f "$pending"
    fail cannot_record_restore
fi
UNDO=1
while IFS= read -r rule; do ndm "$rule" || fail attach_failed; done < "$WORK/pilot"
while IFS= read -r rule; do ndm "no $rule" || fail attach_failed; done < "$WORK/before"
snapshot "$WORK/current" && cmp -s "$WORK/current" "$WORK/pilot" || fail attachment_unverified
wait_live_rules "$WORK/pilot" || fail live_dns_attachment_unverified
counts=$("$BIN" health -port "$PORT" -address "$PILOT_ADDRESS") || fail local_health_unverified
"$BIN" probe -port 53 || fail keenetic_probe_failed
counts_after=$("$BIN" health -port "$PORT" -address "$PILOT_ADDRESS") || fail local_health_unverified
printf '%s\n%s\n' "$counts" "$counts_after" |
    awk 'NR == 1 {a=$1; b=$2} NR == 2 {ok=($1+0>a+0 && $2+0>b+0)} END {exit !ok}' ||
    fail queries_not_seen_by_vward_dns
echo "result=trial_verified"
if [ "$HOLD_SECONDS" -gt 0 ]; then
    echo "result=trial_hold seconds=$HOLD_SECONDS"
    sleep "$HOLD_SECONDS" & hold_pid=$!
    wait "$hold_pid" || fail trial_hold_interrupted
    hold_pid=
fi
