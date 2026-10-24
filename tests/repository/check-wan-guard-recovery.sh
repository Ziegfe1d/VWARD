#!/bin/sh
set -u

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
SOURCE="$ROOT/components/wan-guard/scripts/vward-wan-guard.sh"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/vward-wan-recovery.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
trap 'exit 1' HUP INT TERM

fail(){ echo "FAIL: $*" >&2; exit 1; }

grep -Fq 'WAN_BOUNCE_MARKER="$REC_DIR/owned-down"' "$SOURCE" ||
    fail "WAN bounce has no durable in-process recovery marker"
grep -Fq 'trap wan_signal_exit 1 2 15' "$SOURCE" ||
    fail "WAN Guard signals do not use compensating recovery"

sed -n \
    -e '/^wg_num()/,/^}/p' \
    -e '/^wg_reset_fail()/,/^}/p' \
    -e '/^wg_reset_all()/,/^}/p' \
    -e '/^wg_bucket_count()/,/^}/p' \
    -e '/^wg_bucket_inc()/,/^}/p' \
    -e '/^wan_run_up()/,/^}/p' \
    -e '/^wan_restore_incomplete_bounce()/,/^}/p' \
    -e '/^wan_signal_exit()/,/^}/p' \
    -e '/^wan_recover()/,/^}/p' \
    "$SOURCE" > "$WORK/functions.sh"

for fn in wan_run_up wan_restore_incomplete_bounce wan_signal_exit wan_recover; do
    grep -q "^$fn()" "$WORK/functions.sh" || fail "missing $fn helper"
done

cat > "$WORK/ndmc" <<'SH'
#!/bin/sh
printf '%s\n' "$*" >> "$WAN_TEST_LOG"
if [ "${*% down}" != "$*" ]; then
    if [ "${WAN_TEST_SIGNAL_DOWN:-0}" = 1 ]; then
        kill -TERM "$WAN_TEST_PARENT_PID"
    fi
    [ "${WAN_TEST_FAIL_DOWN:-0}" = 1 ] && exit 1
fi
[ "${WAN_TEST_FAIL_UP:-0}" = 1 ] && exit 1
exit 0
SH
chmod +x "$WORK/ndmc"

WAN_TEST_LOG="$WORK/ndmc.log"
export WAN_TEST_LOG
NDMC="$WORK/ndmc"
VWARD_WAN_INTERFACE=ISP
REC_DIR="$WORK/state"
WAN_BOUNCE_MARKER="$REC_DIR/owned-down"
REC_LOG="$WORK/recovery.log"
WAN_BOUNCE_PHASE=IDLE
WAN_CANCEL_REQUESTED=0
mkdir -p "$REC_DIR"

# Avoid retry delays in the isolated failure simulation.
sleep(){ :; }

. "$WORK/functions.sh"

printf '%s\n' ISP > "$WAN_BOUNCE_MARKER"
wan_restore_incomplete_bounce || fail "startup recovery rejected a successful WAN up"
[ ! -e "$WAN_BOUNCE_MARKER" ] || fail "successful recovery retained owned-down marker"
grep -Fq 'interface ISP up' "$WAN_TEST_LOG" || fail "startup recovery did not request WAN up"

: > "$WAN_TEST_LOG"
printf '%s\n' ISP > "$WAN_BOUNCE_MARKER"
if (wan_signal_exit); then
    fail "signal handler returned success"
fi
[ ! -e "$WAN_BOUNCE_MARKER" ] || fail "signal recovery retained owned-down marker"
grep -Fq 'interface ISP up' "$WAN_TEST_LOG" || fail "signal recovery did not request WAN up"

# In-memory ownership closes the tiny interval after an accepted down but
# before the persistent marker write completes.
: > "$WAN_TEST_LOG"
WAN_BOUNCE_PHASE=OWNED_DOWN
rm -f "$WAN_BOUNCE_MARKER"
if (wan_signal_exit); then
    fail "owned-down signal handler returned success"
fi
grep -Fq 'interface ISP up' "$WAN_TEST_LOG" || fail "in-memory owned down was not restored"
WAN_BOUNCE_PHASE=IDLE

: > "$WAN_TEST_LOG"
printf '%s\n' ISP > "$WAN_BOUNCE_MARKER"
WAN_TEST_FAIL_UP=1
export WAN_TEST_FAIL_UP
if wan_restore_incomplete_bounce; then
    fail "failed WAN up was reported as recovered"
fi
[ -f "$WAN_BOUNCE_MARKER" ] || fail "failed recovery lost its retry marker"

printf '%s\n' OLD_INTERFACE > "$WAN_BOUNCE_MARKER"
wan_restore_incomplete_bounce || fail "foreign marker was not quarantined"
[ ! -e "$WAN_BOUNCE_MARKER" ] || fail "foreign marker still blocks recovery"
[ -f "$WAN_BOUNCE_MARKER.invalid.$$" ] || fail "foreign marker was not quarantined"

unset WAN_TEST_FAIL_UP
rm -f "$WAN_BOUNCE_MARKER"

# Exercise the real bounce path: a rejected down must never authorize an up.
: > "$WAN_TEST_LOG"
WAN_TEST_FAIL_DOWN=1
export WAN_TEST_FAIL_DOWN
CONFIRM_FAILURES=1
BOUNCE_COOLDOWN=0
MAX_BOUNCE_HOUR=10
MAX_BOUNCE_DAY=10
DETAIL=test
WAN_BOUNCE_PHASE=IDLE
WAN_CANCEL_REQUESTED=0
wan_recover PHY_DOWN
[ "$ACTION" = WAN_BOUNCE_DOWN_FAILED ] || fail "failed down has wrong action: $ACTION"
grep -Fq 'interface ISP down' "$WAN_TEST_LOG" || fail "failed-down scenario did not attempt down"
if grep -Fq 'interface ISP up' "$WAN_TEST_LOG"; then
    fail "failed down incorrectly forced WAN up"
fi
[ ! -e "$WAN_BOUNCE_MARKER" ] || fail "failed down created ownership marker"

# A normal accepted bounce must down, up, and clear ownership.
: > "$WAN_TEST_LOG"
unset WAN_TEST_FAIL_DOWN
rm -rf "$REC_DIR"
mkdir -p "$REC_DIR"
DETAIL=test
WAN_BOUNCE_PHASE=IDLE
WAN_CANCEL_REQUESTED=0
wan_recover PHY_DOWN
grep -Fq 'interface ISP down' "$WAN_TEST_LOG" || fail "normal bounce missed down"
grep -Fq 'interface ISP up' "$WAN_TEST_LOG" || fail "normal bounce missed up"
[ ! -e "$WAN_BOUNCE_MARKER" ] || fail "normal bounce retained ownership marker"

# Run a separate shell so TERM during the five-second bounce wait cannot kill
# this test process.  The signal handler must compensate with up and exit.
cat > "$WORK/term-scenario.sh" <<'SH'
#!/bin/sh
set -u
. "$1"
NDMC="$2"; WAN_TEST_LOG="$3"; export WAN_TEST_LOG
VWARD_WAN_INTERFACE=ISP; REC_DIR="$4"; WAN_BOUNCE_MARKER="$REC_DIR/owned-down"
REC_LOG="$5"; CONFIRM_FAILURES=1; BOUNCE_COOLDOWN=0
MAX_BOUNCE_HOUR=10; MAX_BOUNCE_DAY=10; DETAIL=test
WAN_BOUNCE_PHASE=IDLE; WAN_CANCEL_REQUESTED=0
mkdir -p "$REC_DIR"
sleep(){ [ "$1" = 5 ] && kill -TERM "$$" || :; }
trap wan_signal_exit 1 2 15
wan_recover PHY_DOWN
exit 99
SH
chmod +x "$WORK/term-scenario.sh"
: > "$WAN_TEST_LOG"
if sh "$WORK/term-scenario.sh" "$WORK/functions.sh" "$NDMC" "$WAN_TEST_LOG" \
    "$WORK/term-state" "$REC_LOG"; then
    fail "TERM during bounce returned success"
fi
grep -Fq 'interface ISP down' "$WAN_TEST_LOG" || fail "TERM scenario missed down"
grep -Fq 'interface ISP up' "$WAN_TEST_LOG" || fail "TERM scenario did not restore up"
[ ! -e "$WORK/term-state/owned-down" ] || fail "TERM recovery retained marker"

# TERM delivered while ndmc down is running must be deferred until its return
# code establishes whether VWARD owns a compensating up.
cat > "$WORK/down-signal-scenario.sh" <<'SH'
#!/bin/sh
set -u
. "$1"
NDMC="$2"; WAN_TEST_LOG="$3"; export WAN_TEST_LOG
VWARD_WAN_INTERFACE=ISP; REC_DIR="$4"; WAN_BOUNCE_MARKER="$REC_DIR/owned-down"
REC_LOG="$5"; CONFIRM_FAILURES=1; BOUNCE_COOLDOWN=0
MAX_BOUNCE_HOUR=10; MAX_BOUNCE_DAY=10; DETAIL=test
WAN_BOUNCE_PHASE=IDLE; WAN_CANCEL_REQUESTED=0
WAN_TEST_SIGNAL_DOWN=1; WAN_TEST_PARENT_PID=$$
WAN_TEST_FAIL_DOWN="$6"
export WAN_TEST_SIGNAL_DOWN WAN_TEST_PARENT_PID WAN_TEST_FAIL_DOWN
mkdir -p "$REC_DIR"
sleep(){ :; }
trap wan_signal_exit 1 2 15
wan_recover PHY_DOWN
exit 99
SH
chmod +x "$WORK/down-signal-scenario.sh"

: > "$WAN_TEST_LOG"
if sh "$WORK/down-signal-scenario.sh" "$WORK/functions.sh" "$NDMC" "$WAN_TEST_LOG" \
    "$WORK/down-signal-ok" "$REC_LOG" 0; then
    fail "deferred TERM after accepted down returned success"
fi
grep -Fq 'interface ISP up' "$WAN_TEST_LOG" || fail "accepted down was not compensated after TERM"

: > "$WAN_TEST_LOG"
if sh "$WORK/down-signal-scenario.sh" "$WORK/functions.sh" "$NDMC" "$WAN_TEST_LOG" \
    "$WORK/down-signal-fail" "$REC_LOG" 1; then
    fail "deferred TERM after rejected down returned success"
fi
if grep -Fq 'interface ISP up' "$WAN_TEST_LOG"; then
    fail "rejected down was incorrectly compensated after TERM"
fi

# Automatic recovery switched off from the Panel: classify, but never act,
# and do not accumulate failures that would fire right after re-enabling.
: > "$WAN_TEST_LOG"
rm -rf "$REC_DIR"; mkdir -p "$REC_DIR"
WAN_GUARD_DISABLE_FILE="$WORK/wan-guard.disabled"
: > "$WAN_GUARD_DISABLE_FILE"
CONFIRM_FAILURES=1
DETAIL=test
wan_recover PHY_DOWN
[ "$ACTION" = DISABLED_BY_USER ] || fail "disabled guard has wrong action: $ACTION"
[ ! -s "$WAN_TEST_LOG" ] || fail "disabled guard touched the WAN interface"
[ "$(cat "$REC_DIR/fail_count")" = 0 ] || fail "disabled guard accumulated failures"
rm -f "$WAN_GUARD_DISABLE_FILE"
wan_recover PHY_DOWN
grep -Fq 'interface ISP down' "$WAN_TEST_LOG" || fail "re-enabled guard does not act"

# A busy router: one more try for RCI, and never two replies glued together.
sed -n '/^wg_rci_get()/,/^}/p' "$SOURCE" > "$WORK/rci.sh"
grep -q '^wg_rci_get()' "$WORK/rci.sh" || fail "missing wg_rci_get helper"
cat > "$WORK/curl" <<'SH'
#!/bin/sh
n=$(($(cat "$WAN_TEST_CALLS" 2>/dev/null || echo 0) + 1)); echo "$n" > "$WAN_TEST_CALLS"
case "$WAN_TEST_RCI:$n" in
    slow:1) exit 28 ;;
    slow:2) printf '{"ok":1}' ;;
    cut:1) printf '{"par'; exit 28 ;;
    cut:2) printf '{"ok":2}' ;;
    down:*) exit 7 ;;
    fast:*) printf '{"ok":0}' ;;
esac
SH
chmod +x "$WORK/curl"
WAN_TEST_CALLS="$WORK/calls"; export WAN_TEST_CALLS
for c in 'fast|{"ok":0}|1' 'slow|{"ok":1}|2' 'cut|{"ok":2}|2' 'down||2'; do
    IFS='|' read -r mode want calls <<CASE
$c
CASE
    rm -f "$WAN_TEST_CALLS"
    got=$(WAN_TEST_RCI=$mode CURL="$WORK/curl" sh -c 'vward_cs(){ :; }; vward_keenetic_timed(){ :; }; . "$1"; sleep(){ :; }; wg_rci_get http://rci/x' sh "$WORK/rci.sh")
    [ "$got" = "$want" ] && [ "$(cat "$WAN_TEST_CALLS")" = "$calls" ] ||
        fail "wg_rci_get $mode: got '$got' after $(cat "$WAN_TEST_CALLS") calls"
done

# Keenetic's RCI silent, the connection checked without it (fix.33.2, WP-B): carrier and an
# outside address up - the state stays, one journal line an episode, the misses counted; down -
# UTILITY_DEGRADED as before; VWARD_WAN_RCI_PROBES=0 - as before without checking.
sed -n -e '/^wg_rci_missing()/,/^}/p' -e '/^wg_num()/,/^}/p' "$SOURCE" > "$WORK/miss.sh"
grep -q '^wg_rci_missing()' "$WORK/miss.sh" || fail "missing wg_rci_missing helper"
mkdir -p "$WORK/net/eth3"
cat > "$WORK/ping" <<'SH'
#!/bin/sh
for a in "$@"; do last=$a; done
echo "$last" >> "$WAN_TEST_PINGS"
case " $WAN_TEST_UP " in *" $last "*) exit 0 ;; esac
exit 1
SH
chmod +x "$WORK/ping"
miss() {
    rm -f "$WORK/pings"
    WAN_TEST_UP=$1 WAN_TEST_PINGS="$WORK/pings" PING="$WORK/ping" ETH=eth3 VWARD_SYSFS_NET="$WORK/net" \
        STATE="$WORK/wstate" LOG="$WORK/wan.log" RCI_MISS="$WORK/miss" VERSION=t MODE=t \
        sh -c 'now(){ echo NOW; }
            wan_recover(){ echo "recover:$1" >> "$WORK/recover"; }
            emit_state(){ echo "CLASS=$1"; echo "$2"; echo "$1" > "$STATE"; }
            . "$1"; wg_rci_missing "$2"' sh "$WORK/miss.sh" "$2"
}
export WORK
echo 1 > "$WORK/net/eth3/carrier"; echo HEALTHY > "$WORK/wstate"; rm -f "$WORK/wan.log" "$WORK/miss" "$WORK/recover"
out=$(miss "77.88.8.1" isp_rci_unavailable)
printf '%s\n' "$out" | grep -qx 'CLASS=HEALTHY' && [ "$(cat "$WORK/wstate")" = HEALTHY ] ||
    fail "RCI silent with the internet up must keep the state: $out"
[ "$(cat "$WORK/pings")" = "$(printf '1.0.0.1\n77.88.8.1')" ] || fail "the second address is tried when the first is silent"
miss "1.0.0.1" internet_rci_unavailable >/dev/null
[ "$(cat "$WORK/pings")" = 1.0.0.1 ] || fail "one answering address is enough"
[ "$(cat "$WORK/miss")" = 2 ] && [ "$(grep -c 'rci_unavailable reason=isp_rci_unavailable probes=ok class_kept=HEALTHY' "$WORK/wan.log")" = 1 ] &&
    [ "$(wc -l < "$WORK/wan.log")" = 1 ] || fail "one journal line an episode, the misses counted"
[ "$(cat "$WORK/recover")" = "$(printf 'recover:UTILITY_DEGRADED\nrecover:UTILITY_DEGRADED')" ] || fail "the recovery is reset as before"
out=$(miss "" isp_rci_unavailable)
printf '%s\n' "$out" | grep -qx 'CLASS=UTILITY_DEGRADED' && printf '%s\n' "$out" | grep -q 'reason=isp_rci_unavailable probes=fail carrier=1 ping_cf=1 ping_ya=1' ||
    fail "RCI silent and nothing answering must stay UTILITY_DEGRADED: $out"
echo HEALTHY > "$WORK/wstate"; echo 0 > "$WORK/net/eth3/carrier"
miss "1.0.0.1 77.88.8.1" isp_rci_unavailable | grep -qx 'CLASS=UTILITY_DEGRADED' || fail "no carrier is not a working connection"
echo 1 > "$WORK/net/eth3/carrier"; echo HEALTHY > "$WORK/wstate"
out=$(VWARD_WAN_RCI_PROBES=0 miss "1.0.0.1" isp_rci_unavailable)
printf '%s\n' "$out" | grep -qx 'CLASS=UTILITY_DEGRADED' && [ ! -e "$WORK/pings" ] || fail "VWARD_WAN_RCI_PROBES=0 must keep the old way: $out"
grep -Fq 'printf '"'"'%s rci_back misses=%s\n'"'"'' "$SOURCE" || fail "the end of an episode must be journaled"

echo WAN_GUARD_RECOVERY=PASS
