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

# Automatic recovery switched off from the Console: classify, but never act,
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

echo WAN_GUARD_RECOVERY=PASS
