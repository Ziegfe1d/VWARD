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
    awk -v domains="$DOMAINS" -v iface="$TUNNEL" '
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
    ndmc_timed "$1" > "$WORK/ndm.reply" 2>&1 || return 1
    ! grep -Eqi '(^|[^a-z])(error|failed|invalid|unknown command|not found|no such entry)' "$WORK/ndm.reply"
}

# Every remembered rule is validated against the data generated from the fixed pilot scope.
# Recovery tolerates a partially executed switch or a lost response to a Keenetic command.
restore() {
    [ -f "$STATE/pending" ] && [ ! -L "$STATE/pending" ] || return 1
    cmp -s "$STATE/pending" "$WORK/before" || return 1
    snapshot "$WORK/current" || return 1
    comm -23 "$WORK/current" "$WORK/allowed" > "$WORK/diff" && [ ! -s "$WORK/diff" ] || return 1
    comm -23 "$WORK/before" "$WORK/current" > "$WORK/diff" || return 1
    while IFS= read -r rule; do ndm "$rule" || :; done < "$WORK/diff"
    # Read the new state before taking out the local server so there is always a
    # configured path back. Running-config proof is distinct from DNS success.
    snapshot "$WORK/current" || return 1
    comm -23 "$WORK/before" "$WORK/current" > "$WORK/diff" && [ ! -s "$WORK/diff" ] || return 1
    comm -12 "$WORK/pilot" "$WORK/current" > "$WORK/diff" || return 1
    while IFS= read -r rule; do
        ndm "no $rule" || :
    done < "$WORK/diff"
    snapshot "$WORK/current" && cmp -s "$WORK/current" "$WORK/before" || return 1
    rm -f "$STATE/pending"
}

cleanup() {
    status=$?
    trap '' HUP INT TERM
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

live_rules() {
    live_file=
    for live in ${VWARD_NDNPROXY_CONF:-/var/ndnproxymain.conf /tmp/ndnproxymain.conf}; do
        [ ! -r "$live" ] || { live_file=$live; break; }
    done
    [ -n "$live_file" ] || return 1
    awk -v upstream="127.0.0.1:$PORT" '
        $1 == "dns_server" && $2 == "=" && $3 == upstream {print "ip name-server " $3 " " tolower($4)}
    ' "$live_file" | LC_ALL=C sort > "$WORK/live"
    cmp -s "$WORK/live" "$WORK/pilot"
}

[ "$#" = 1 ] || fail usage
case "$1" in serve|probe|plan|trial|restore) ;; *) fail usage ;; esac
[ -x "$BIN" ] || fail binary_missing
[ "$1" != probe ] || exec "$BIN" probe -port "$PORT"
[ -r "$PROFILE" ] || fail profile_missing
. "$PROFILE"
vward_profile_load || fail profile_unavailable
TUNNEL=${VWARD_TUNNEL_INTERFACE:-}
DEVICE=${VWARD_TUNNEL_DEVICE:-}
case "$TUNNEL" in OpkgTun[0-9]) ;; *) fail not_an_opkg_tunnel ;; esac
[ "$DEVICE" = "$(printf '%s' "$TUNNEL" | tr 'A-Z' 'a-z')" ] || fail tunnel_device_unverified
[ "$1" != serve ] || exec "$BIN" serve -tunnel "$DEVICE" -port "$PORT"

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
done | LC_ALL=C sort > "$WORK/before"
for domain in $DOMAINS; do
    printf 'ip name-server 127.0.0.1:%s %s\n' "$PORT" "$domain"
done | LC_ALL=C sort > "$WORK/pilot"
LC_ALL=C sort "$WORK/before" "$WORK/pilot" > "$WORK/allowed"
if [ "$1" = plan ]; then
    snapshot "$WORK/current" && cmp -s "$WORK/current" "$WORK/before" || fail dns_scope_differs_from_expected
    echo "result=plan_ready tunnel=$TUNNEL port=$PORT domains=8 current_rules=16"
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
    restore || fail dns_restore_unverified
    echo "result=original_dns_configuration_restored"
    exit 0
fi

[ ! -e "$STATE/pending" ] && [ ! -L "$STATE/pending" ] || fail prior_trial_requires_restore
snapshot "$WORK/current" && cmp -s "$WORK/current" "$WORK/before" || fail dns_scope_differs_from_expected
"$BIN" probe -port "$PORT" || fail local_resolver_failed
"$BIN" health -port "$PORT" >/dev/null || fail local_health_unverified
mkdir -p "$STATE" && [ -d "$STATE" ] && [ ! -L "$STATE" ] && [ -O "$STATE" ] || fail unsafe_state_directory
pending=$(mktemp "$STATE/pending.XXXXXX") || fail cannot_record_restore
if ! cat "$WORK/before" > "$pending" || ! mv "$pending" "$STATE/pending"; then
    rm -f "$pending"
    fail cannot_record_restore
fi
UNDO=1
while IFS= read -r rule; do ndm "$rule" || fail attach_failed; done < "$WORK/pilot"
while IFS= read -r rule; do ndm "no $rule" || fail attach_failed; done < "$WORK/before"
snapshot "$WORK/current" && cmp -s "$WORK/current" "$WORK/pilot" || fail attachment_unverified
left=5
until live_rules; do
    [ "$left" -gt 0 ] || fail live_dns_attachment_unverified
    left=$((left - 1))
    sleep 1
done
counts=$("$BIN" health -port "$PORT") || fail local_health_unverified
"$BIN" probe -port 53 || fail keenetic_probe_failed
counts_after=$("$BIN" health -port "$PORT") || fail local_health_unverified
printf '%s\n%s\n' "$counts" "$counts_after" |
    awk 'NR == 1 {a=$1; b=$2} NR == 2 {ok=($1+0>a+0 && $2+0>b+0)} END {exit !ok}' ||
    fail queries_not_seen_by_vward_dns
echo "result=trial_verified"
