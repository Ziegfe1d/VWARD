#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
CONTROLLER="$ROOT/components/wan-guardian/scripts/wan-recovery-controller.sh"
TMP="${TMPDIR:-/tmp}/vward-wan-controller-test.$$"
PLANNER="$TMP/planner.sh"
ACTUATOR="$TMP/actuator.sh"
LOCK="$TMP/controller.lock"
MARKER="$TMP/actuator.called"
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
case "${VWARD_TEST_ACT_MODE:-ready}" in
    ready)
        case "$ACTION" in
            DHCP_RENEW) KIND=RCI_DHCP_RENEW ;;
            SESSION_RECONNECT) KIND=RCI_SESSION_RECONNECT ;;
            *) KIND=RCI_INTERFACE_RECONNECT ;;
        esac
        cat <<OUT
MODE=dryrun
RESULT=READY
ACTION=$ACTION
REASON=validated_dryrun
EXECUTION_KIND=$KIND
TARGET_RCI_ID=$2
TARGET_LINUX_IF=$3
EXECUTED=NO
OUT
        ;;
    blocked)
        cat <<OUT
MODE=dryrun
RESULT=BLOCKED
ACTION=$ACTION
REASON=capability_changed
TARGET_RCI_ID=$2
TARGET_LINUX_IF=$3
EXECUTED=NO
OUT
        ;;
    executed)
        cat <<OUT
MODE=dryrun
RESULT=READY
ACTION=$ACTION
REASON=bad
EXECUTION_KIND=RCI_INTERFACE_RECONNECT
TARGET_RCI_ID=$2
TARGET_LINUX_IF=$3
EXECUTED=YES
OUT
        ;;
esac
EOF
chmod 0755 "$ACTUATOR"

value()
{
    printf '%s\n' "$1" | awk -F= -v k="$2" '$1==k {print substr($0,index($0,"=")+1); exit}'
}

run_controller()
{
    rm -f "$MARKER"
    VWARD_WAN_RECOVERY_PLANNER="$PLANNER" \
    VWARD_WAN_RECOVERY_ACTUATOR="$ACTUATOR" \
    VWARD_WAN_RECOVERY_GATE_LOCK="$LOCK" \
    VWARD_TEST_PLAN_MODE="$1" \
    VWARD_TEST_ACT_MODE="${2:-ready}" \
    VWARD_TEST_ACTUATOR_MARKER="$MARKER" \
    sh "$CONTROLLER"
}

OUT="$(run_controller plan ready)"
[ "$(value "$OUT" RESULT)" = READY ] || fail "valid plan was not accepted"
[ "$(value "$OUT" EXECUTION_KIND)" = RCI_INTERFACE_RECONNECT ] || fail "interface execution kind missing"
[ "$(value "$OUT" EXECUTED)" = NO ] || fail "controller must stay dry-run"
[ -f "$MARKER" ] || fail "controller did not call actuator for PLAN"
[ ! -e "$LOCK" ] || fail "controller lock was not released"

OUT="$(run_controller dhcp ready)"
[ "$(value "$OUT" RESULT)" = READY ] || fail "DHCP plan was not accepted"
[ "$(value "$OUT" EXECUTION_KIND)" = RCI_DHCP_RENEW ] || fail "DHCP execution kind missing"

OUT="$(run_controller hold ready)"
[ "$(value "$OUT" RESULT)" = NO_ACTION ] || fail "HOLD must produce NO_ACTION"
[ ! -f "$MARKER" ] || fail "actuator must not be called for HOLD"

OUT="$(run_controller bad-action ready)"
[ "$(value "$OUT" RESULT)" = BLOCKED ] || fail "unsupported action must block"
[ "$(value "$OUT" REASON)" = unsupported_planner_action ] || fail "unsupported action reason missing"
[ ! -f "$MARKER" ] || fail "actuator must not be called for unsupported action"

OUT="$(run_controller plan blocked)"
[ "$(value "$OUT" RESULT)" = BLOCKED ] || fail "blocked actuator must block controller"
[ "$(value "$OUT" REASON)" = actuator_capability_changed ] || fail "actuator block reason missing"

OUT="$(run_controller plan executed)"
[ "$(value "$OUT" RESULT)" = BLOCKED ] || fail "executing actuator must violate guard"
[ "$(value "$OUT" REASON)" = actuator_execution_guard_violation ] || fail "actuator execution guard reason missing"

OUT="$(run_controller executed ready)"
[ "$(value "$OUT" RESULT)" = BLOCKED ] || fail "executing planner must violate guard"
[ "$(value "$OUT" REASON)" = planner_execution_guard_violation ] || fail "planner execution guard reason missing"

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

for forbidden in 'ndmc' 'eval ' 'ip dhcp client renew' 'IFACE="ISP"' 'COMMAND='; do
    if grep -Fq "$forbidden" "$CONTROLLER"; then
        fail "controller contains forbidden execution token: $forbidden"
    fi
done

sh -n "$CONTROLLER" || fail "controller shell syntax"
echo "WAN_RECOVERY_CONTROLLER_TESTS=PASS"
