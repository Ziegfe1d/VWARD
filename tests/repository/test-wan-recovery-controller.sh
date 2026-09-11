#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
CONTROLLER="$ROOT/components/wan-guardian/scripts/wan-recovery-controller.sh"
TMP="${TMPDIR:-/tmp}/vward-wan-controller-test.$$"
PLANNER="$TMP/planner.sh"
ACTUATOR="$TMP/actuator.sh"
OBSERVER="$TMP/observer.sh"
LOCK="$TMP/controller.lock"
MARKER="$TMP/actuator.called"
STATE="$TMP/recovery.state"
AUDIT="$TMP/recovery.log"
HEALTH="$TMP/health.state"
UPDATER_LOCK="$TMP/updater.lock"
UPDATER_BARRIER="$TMP/update.barrier"
UPDATER_REQUEST="$TMP/update.request"
LEGACY_LOCK="$TMP/legacy.lock"
LEGACY_LOCK_DIR="$TMP/legacy.lock.d"
TUNNEL_LOCK="$TMP/tunnel.lock"
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT INT TERM

fail()
{
    echo "FAIL: $*" >&2
    exit 1
}

cat > "$PLANNER" <<'EOF'
#!/bin/sh
case "${VWARD_TEST_PLAN_MODE:-plan}" in
    plan)
        cat <<'OUT'
MODE=dryrun
DECISION=PLAN
ACTION=INTERFACE_RECONNECT
REASON=test_plan
TARGET_RCI_ID=UplinkAlpha
TARGET_LINUX_IF=wan0
EXECUTED=NO
OUT
        ;;
    dhcp)
        cat <<'OUT'
MODE=dryrun
DECISION=PLAN
ACTION=DHCP_RENEW
REASON=test_dhcp
TARGET_RCI_ID=UplinkAlpha
TARGET_LINUX_IF=wan0
EXECUTED=NO
OUT
        ;;
    hold)
        cat <<'OUT'
MODE=dryrun
DECISION=HOLD
ACTION=NONE
REASON=healthy
TARGET_RCI_ID=UplinkAlpha
TARGET_LINUX_IF=wan0
EXECUTED=NO
OUT
        ;;
    bad-action)
        cat <<'OUT'
MODE=dryrun
DECISION=PLAN
ACTION=SHELL_COMMAND
REASON=bad
TARGET_RCI_ID=UplinkAlpha
TARGET_LINUX_IF=wan0
EXECUTED=NO
OUT
        ;;
    executed)
        cat <<'OUT'
MODE=dryrun
DECISION=PLAN
ACTION=INTERFACE_RECONNECT
REASON=bad
TARGET_RCI_ID=UplinkAlpha
TARGET_LINUX_IF=wan0
EXECUTED=YES
OUT
        ;;
esac
EOF
chmod 0755 "$PLANNER"

cat > "$ACTUATOR" <<'EOF'
#!/bin/sh
: > "$VWARD_TEST_ACTUATOR_MARKER"
ACTION="$1"
case "$ACTION" in
    DHCP_RENEW) KIND=RCI_DHCP_RENEW ;;
    SESSION_RECONNECT) KIND=RCI_SESSION_RECONNECT ;;
    *) KIND=RCI_INTERFACE_RECONNECT ;;
esac

if [ "${VWARD_WAN_RECOVERY_EXECUTION_ENABLED:-0}" = 1 ]; then
    MODE_OUT=execute
else
    MODE_OUT=dryrun
fi

if [ "${VWARD_TEST_ACT_MODE:-ready}" = blocked ]; then
    cat <<OUT
MODE=$MODE_OUT
RESULT=BLOCKED
ACTION=$ACTION
REASON=capability_changed
EXECUTION_KIND=$KIND
TARGET_RCI_ID=$2
TARGET_LINUX_IF=$3
MUTATION_ATTEMPTED=NO
EXECUTED=NO
OUT
    exit 0
fi

if [ "${VWARD_WAN_RECOVERY_EXECUTION_ENABLED:-0}" = 1 ]; then
    [ "${VWARD_WAN_RECOVERY_CONTROLLER_AUTH:-0}" = 1 ] || exit 9
    cat <<OUT
MODE=execute
RESULT=EXECUTED
ACTION=$ACTION
REASON=mock_execution
EXECUTION_KIND=$KIND
TARGET_RCI_ID=$2
TARGET_LINUX_IF=$3
MUTATION_ATTEMPTED=YES
EXECUTED=YES
OUT
else
    cat <<OUT
MODE=dryrun
RESULT=READY
ACTION=$ACTION
REASON=validated_dryrun
EXECUTION_KIND=$KIND
TARGET_RCI_ID=$2
TARGET_LINUX_IF=$3
MUTATION_ATTEMPTED=NO
EXECUTED=NO
OUT
fi
EOF
chmod 0755 "$ACTUATOR"

cat > "$OBSERVER" <<'EOF'
#!/bin/sh
now="${VWARD_TEST_OBSERVER_NOW:-1000}"
case "${VWARD_TEST_OBSERVER_MODE:-healthy}" in
    healthy)
        cat > "$VWARD_TEST_HEALTH_STATE" <<OUT
STATUS=UP
CLASS=HEALTHY
LAST_CHECK=$now
RCI_ID=UplinkAlpha
LINUX_IF=wan0
OUT
        ;;
    down)
        cat > "$VWARD_TEST_HEALTH_STATE" <<OUT
STATUS=DOWN
CLASS=INTERNET_FAILURE
LAST_CHECK=$now
RCI_ID=UplinkAlpha
LINUX_IF=wan0
OUT
        ;;
    wrong-role)
        cat > "$VWARD_TEST_HEALTH_STATE" <<OUT
STATUS=UP
CLASS=HEALTHY
LAST_CHECK=$now
RCI_ID=OtherWAN
LINUX_IF=wan0
OUT
        ;;
esac
exit 0
EOF
chmod 0755 "$OBSERVER"

value()
{
    printf '%s\n' "$1" | awk -F= -v k="$2" '$1==k {print substr($0,index($0,"=")+1); exit}'
}

run_controller()
{
    plan_mode="$1"
    act_mode="${2:-ready}"
    execution="${3:-0}"
    now="${4:-1000}"
    observer_mode="${5:-healthy}"
    cooldown="${6:-300}"
    window="${7:-3600}"
    max_attempts="${8:-3}"

    rm -f "$MARKER"
    VWARD_WAN_RECOVERY_PLANNER="$PLANNER" \
    VWARD_WAN_RECOVERY_ACTUATOR="$ACTUATOR" \
    VWARD_WAN_HEALTH_OBSERVER="$OBSERVER" \
    VWARD_WAN_HEALTH_STATE="$HEALTH" \
    VWARD_WAN_RECOVERY_GATE_LOCK="$LOCK" \
    VWARD_WAN_RECOVERY_STATE_FILE="$STATE" \
    VWARD_WAN_RECOVERY_AUDIT_LOG="$AUDIT" \
    VWARD_WAN_RECOVERY_EXECUTION_ENABLED="$execution" \
    VWARD_WAN_RECOVERY_COOLDOWN_SEC="$cooldown" \
    VWARD_WAN_RECOVERY_WINDOW_SEC="$window" \
    VWARD_WAN_RECOVERY_MAX_ATTEMPTS="$max_attempts" \
    VWARD_WAN_RECOVERY_POSTCHECK_ATTEMPTS=2 \
    VWARD_WAN_RECOVERY_POSTCHECK_DELAY_SEC=0 \
    VWARD_NOW_EPOCH="$now" \
    VWARD_POSTCHECK_NOW_EPOCH="$now" \
    VWARD_UPDATE_LOCK_DIR="$UPDATER_LOCK" \
    VWARD_UPDATE_BARRIER_LOCK="$UPDATER_BARRIER" \
    VWARD_UPDATE_REQUEST_MARKER="$UPDATER_REQUEST" \
    VWARD_LEGACY_WAN_LOCK="$LEGACY_LOCK" \
    VWARD_LEGACY_WAN_LOCK_DIR="$LEGACY_LOCK_DIR" \
    VWARD_TUNNEL_MUTATION_LOCK="$TUNNEL_LOCK" \
    VWARD_TEST_PLAN_MODE="$plan_mode" \
    VWARD_TEST_ACT_MODE="$act_mode" \
    VWARD_TEST_ACTUATOR_MARKER="$MARKER" \
    VWARD_TEST_OBSERVER_MODE="$observer_mode" \
    VWARD_TEST_OBSERVER_NOW="$now" \
    VWARD_TEST_HEALTH_STATE="$HEALTH" \
    sh "$CONTROLLER"
}

# Default remains zero-write dry-run.
rm -f "$STATE" "$AUDIT" "$HEALTH"
OUT="$(run_controller plan ready 0)"
[ "$(value "$OUT" RESULT)" = READY ] || fail "valid dry-run plan was not accepted"
[ "$(value "$OUT" MODE)" = dryrun ] || fail "default controller mode must be dryrun"
[ "$(value "$OUT" EXECUTION_KIND)" = RCI_INTERFACE_RECONNECT ] || fail "interface execution kind missing"
[ "$(value "$OUT" EXECUTED)" = NO ] || fail "default controller must not execute"
[ -f "$MARKER" ] || fail "controller did not call actuator for PLAN"
[ ! -e "$STATE" ] || fail "dry-run controller must not write recovery state"
[ ! -e "$AUDIT" ] || fail "dry-run controller must not write audit log"
[ ! -e "$LOCK" ] || fail "controller lock was not released"

OUT="$(run_controller dhcp ready 0)"
[ "$(value "$OUT" RESULT)" = READY ] || fail "DHCP dry-run plan was not accepted"
[ "$(value "$OUT" EXECUTION_KIND)" = RCI_DHCP_RENEW ] || fail "DHCP execution kind missing"

OUT="$(run_controller hold ready 0)"
[ "$(value "$OUT" RESULT)" = NO_ACTION ] || fail "HOLD must produce NO_ACTION"
[ ! -f "$MARKER" ] || fail "actuator must not be called for HOLD"

OUT="$(run_controller bad-action ready 0)"
[ "$(value "$OUT" RESULT)" = BLOCKED ] || fail "unsupported action must block"
[ "$(value "$OUT" REASON)" = unsupported_planner_action ] || fail "unsupported action reason missing"
[ ! -f "$MARKER" ] || fail "actuator must not be called for unsupported action"

OUT="$(run_controller executed ready 0)"
[ "$(value "$OUT" RESULT)" = BLOCKED ] || fail "executing planner must violate guard"
[ "$(value "$OUT" REASON)" = planner_execution_guard_violation ] || fail "planner execution guard reason missing"

# Live execution path is only reachable through the controller and must pass post-check.
rm -f "$STATE" "$AUDIT" "$HEALTH"
OUT="$(run_controller plan ready 1 1000 healthy 300 3600 3)"
[ "$(value "$OUT" MODE)" = execute ] || fail "execute mode not reported"
[ "$(value "$OUT" RESULT)" = SUCCESS ] || fail "healthy post-check did not confirm recovery"
[ "$(value "$OUT" POSTCHECK)" = HEALTHY ] || fail "healthy post-check state missing"
[ "$(value "$OUT" EXECUTED)" = YES ] || fail "successful recovery execution missing"
grep -Fq 'LAST_RESULT=SUCCESS' "$STATE" || fail "persistent success state missing"
grep -Fq 'WINDOW_COUNT=1' "$STATE" || fail "first attempt was not counted"
grep -Fq 'status=SUCCESS' "$AUDIT" || fail "success audit record missing"

# A second attempt inside cooldown is blocked before Actuator.
OUT="$(run_controller plan ready 1 1050 healthy 300 3600 3)"
[ "$(value "$OUT" RESULT)" = BLOCKED ] || fail "cooldown must block"
[ "$(value "$OUT" REASON)" = cooldown_active ] || fail "cooldown reason missing"
[ ! -f "$MARKER" ] || fail "cooldown must block before actuator"

# Window rate limit also blocks before Actuator.
rm -f "$STATE" "$AUDIT" "$HEALTH"
OUT="$(run_controller plan ready 1 2000 healthy 0 3600 1)"
[ "$(value "$OUT" RESULT)" = SUCCESS ] || fail "first rate-limit window attempt failed"
OUT="$(run_controller plan ready 1 2001 healthy 0 3600 1)"
[ "$(value "$OUT" RESULT)" = BLOCKED ] || fail "rate limit must block second attempt"
[ "$(value "$OUT" REASON)" = rate_limit_reached ] || fail "rate-limit reason missing"
[ ! -f "$MARKER" ] || fail "rate limit must block before actuator"

# Existing mutating component/updater locks fail closed.
rm -f "$STATE" "$AUDIT" "$HEALTH"
mkdir "$UPDATER_LOCK"
OUT="$(run_controller plan ready 1 3000 healthy 0 3600 3)"
rmdir "$UPDATER_LOCK"
[ "$(value "$OUT" RESULT)" = BLOCKED ] || fail "updater conflict must block"
[ "$(value "$OUT" REASON)" = mutating_component_conflict ] || fail "updater conflict reason missing"
[ ! -f "$MARKER" ] || fail "updater conflict must block before actuator"

: > "$TUNNEL_LOCK"
OUT="$(run_controller plan ready 1 3000 healthy 0 3600 3)"
rm -f "$TUNNEL_LOCK"
[ "$(value "$OUT" REASON)" = mutating_component_conflict ] || fail "tunnel mutation conflict must block"

# Executed mutation without healthy selected-path post-check is not declared success.
rm -f "$STATE" "$AUDIT" "$HEALTH"
OUT="$(run_controller plan ready 1 4000 down 0 3600 3)"
[ "$(value "$OUT" RESULT)" = RECOVERY_UNCONFIRMED ] || fail "failed post-check must remain unconfirmed"
[ "$(value "$OUT" POSTCHECK)" = FAILED ] || fail "failed post-check marker missing"
[ "$(value "$OUT" EXECUTED)" = YES ] || fail "mutation occurrence must remain visible"
grep -Fq 'LAST_RESULT=UNCONFIRMED' "$STATE" || fail "unconfirmed state missing"

rm -f "$STATE" "$AUDIT" "$HEALTH"
OUT="$(run_controller plan ready 1 5000 wrong-role 0 3600 3)"
[ "$(value "$OUT" RESULT)" = RECOVERY_UNCONFIRMED ] || fail "wrong-role post-check must fail"

# Actuator block/failure after reservation is not treated as successful recovery.
rm -f "$STATE" "$AUDIT" "$HEALTH"
OUT="$(run_controller plan blocked 1 6000 healthy 0 3600 3)"
[ "$(value "$OUT" RESULT)" = ERROR ] || fail "blocked live actuator must return controller error"
[ "$(value "$OUT" REASON)" = actuator_capability_changed ] || fail "actuator block reason missing"
grep -Fq 'LAST_RESULT=ACTUATOR_BLOCKED' "$STATE" || fail "actuator block state missing"

# Existing controller lock blocks every mode.
mkdir "$LOCK"
OUT="$(
    VWARD_WAN_RECOVERY_PLANNER="$PLANNER" \
    VWARD_WAN_RECOVERY_ACTUATOR="$ACTUATOR" \
    VWARD_WAN_RECOVERY_GATE_LOCK="$LOCK" \
    VWARD_TEST_ACTUATOR_MARKER="$MARKER" \
    sh "$CONTROLLER"
)"
rmdir "$LOCK"
[ "$(value "$OUT" RESULT)" = BLOCKED ] || fail "existing gate lock must block controller"
[ "$(value "$OUT" REASON)" = gate_busy ] || fail "gate busy reason missing"

for forbidden in 'ndmc' 'eval ' 'ip dhcp client renew' 'IFACE="ISP"' 'COMMAND=' 'system configuration save'; do
    if grep -Fq "$forbidden" "$CONTROLLER"; then
        fail "controller contains forbidden execution token: $forbidden"
    fi
done

for required in \
    'VWARD_WAN_RECOVERY_EXECUTION_ENABLED' \
    'VWARD_WAN_RECOVERY_COOLDOWN_SEC' \
    'VWARD_WAN_RECOVERY_MAX_ATTEMPTS' \
    'VWARD_WAN_RECOVERY_POSTCHECK_ATTEMPTS' \
    'VWARD_WAN_RECOVERY_CONTROLLER_AUTH=1' \
    'mutating_component_conflict' \
    'RECOVERY_UNCONFIRMED'
do
    grep -Fq "$required" "$CONTROLLER" || fail "controller execution policy missing: $required"
done

sh -n "$CONTROLLER" || fail "controller shell syntax"
echo "WAN_RECOVERY_CONTROLLER_TESTS=PASS"
