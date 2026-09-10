#!/opt/bin/sh
set -eu

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

MODE="dryrun"
PLANNER="${VWARD_WAN_RECOVERY_PLANNER:-/opt/bin/wan-recovery-plan.sh}"
ACTUATOR="${VWARD_WAN_RECOVERY_ACTUATOR:-/opt/bin/wan-recovery-actuator.sh}"
LOCK_DIR="${VWARD_WAN_RECOVERY_GATE_LOCK:-/tmp/wan-recovery-controller.lock}"
LOCK_OWNED=0

value()
{
    printf '%s\n' "$1" | awk -F= -v k="$2" '$1==k {print substr($0,index($0,"=")+1); exit}'
}

cleanup()
{
    if [ "$LOCK_OWNED" -eq 1 ] && [ -d "$LOCK_DIR" ]; then
        rmdir "$LOCK_DIR" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

emit()
{
    RESULT="$1"
    REASON="$2"

    echo "MODE=$MODE"
    echo "RESULT=$RESULT"
    echo "REASON=$REASON"
    echo "PLANNER_DECISION=${PLANNER_DECISION:-UNKNOWN}"
    echo "ACTION=${ACTION:-NONE}"
    echo "EXECUTION_KIND=${EXECUTION_KIND:-NONE}"
    echo "TARGET_RCI_ID=${TARGET_RCI_ID:-none}"
    echo "TARGET_LINUX_IF=${TARGET_LINUX_IF:-none}"
    echo "EXECUTED=NO"
    exit 0
}

[ -x "$PLANNER" ] || emit BLOCKED planner_unavailable
[ -x "$ACTUATOR" ] || emit BLOCKED actuator_unavailable

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    emit BLOCKED gate_busy
fi
LOCK_OWNED=1

PLANNER_OUT="$("$PLANNER" 2>/dev/null || true)"
PLANNER_MODE="$(value "$PLANNER_OUT" MODE)"
PLANNER_DECISION="$(value "$PLANNER_OUT" DECISION)"
ACTION="$(value "$PLANNER_OUT" ACTION)"
TARGET_RCI_ID="$(value "$PLANNER_OUT" TARGET_RCI_ID)"
TARGET_LINUX_IF="$(value "$PLANNER_OUT" TARGET_LINUX_IF)"
PLANNER_EXECUTED="$(value "$PLANNER_OUT" EXECUTED)"
PLANNER_REASON="$(value "$PLANNER_OUT" REASON)"

[ "$PLANNER_MODE" = "dryrun" ] || emit BLOCKED planner_mode_invalid
[ "$PLANNER_EXECUTED" = "NO" ] || emit BLOCKED planner_execution_guard_violation

case "$PLANNER_DECISION" in
    HOLD|DEFER|BLOCKED)
        ACTION=NONE
        emit NO_ACTION "planner_${PLANNER_DECISION}_${PLANNER_REASON:-unspecified}"
        ;;
    PLAN)
        ;;
    *)
        ACTION=NONE
        emit BLOCKED planner_decision_invalid
        ;;
esac

case "$ACTION" in
    SESSION_RECONNECT|INTERFACE_RECONNECT|DHCP_RENEW)
        ;;
    *)
        emit BLOCKED unsupported_planner_action
        ;;
esac

[ -n "$TARGET_RCI_ID" ] && [ "$TARGET_RCI_ID" != "none" ] || emit BLOCKED planner_target_rci_missing
[ -n "$TARGET_LINUX_IF" ] && [ "$TARGET_LINUX_IF" != "none" ] || emit BLOCKED planner_target_linux_missing

ACTUATOR_OUT="$("$ACTUATOR" "$ACTION" "$TARGET_RCI_ID" "$TARGET_LINUX_IF" 2>/dev/null || true)"
ACTUATOR_MODE="$(value "$ACTUATOR_OUT" MODE)"
ACTUATOR_RESULT="$(value "$ACTUATOR_OUT" RESULT)"
ACTUATOR_ACTION="$(value "$ACTUATOR_OUT" ACTION)"
ACTUATOR_RCI_ID="$(value "$ACTUATOR_OUT" TARGET_RCI_ID)"
ACTUATOR_LINUX_IF="$(value "$ACTUATOR_OUT" TARGET_LINUX_IF)"
ACTUATOR_EXECUTED="$(value "$ACTUATOR_OUT" EXECUTED)"
EXECUTION_KIND="$(value "$ACTUATOR_OUT" EXECUTION_KIND)"
ACTUATOR_REASON="$(value "$ACTUATOR_OUT" REASON)"

[ "$ACTUATOR_MODE" = "dryrun" ] || emit BLOCKED actuator_mode_invalid
[ "$ACTUATOR_EXECUTED" = "NO" ] || emit BLOCKED actuator_execution_guard_violation
[ "$ACTUATOR_ACTION" = "$ACTION" ] || emit BLOCKED actuator_action_mismatch
[ "$ACTUATOR_RCI_ID" = "$TARGET_RCI_ID" ] || emit BLOCKED actuator_role_mismatch
[ "$ACTUATOR_LINUX_IF" = "$TARGET_LINUX_IF" ] || emit BLOCKED actuator_mapping_mismatch

if [ "$ACTUATOR_RESULT" != "READY" ]; then
    emit BLOCKED "actuator_${ACTUATOR_REASON:-not_ready}"
fi

case "$EXECUTION_KIND" in
    RCI_SESSION_RECONNECT|RCI_INTERFACE_RECONNECT|RCI_DHCP_RENEW)
        ;;
    *)
        emit BLOCKED actuator_execution_kind_invalid
        ;;
esac

emit READY validated_dryrun_gate
