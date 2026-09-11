#!/opt/bin/sh
set -eu

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

EXECUTION_ENABLED="${VWARD_WAN_RECOVERY_EXECUTION_ENABLED:-0}"
MODE="dryrun"
[ "$EXECUTION_ENABLED" = "1" ] && MODE="execute"

PLANNER="${VWARD_WAN_RECOVERY_PLANNER:-/opt/bin/wan-recovery-plan.sh}"
ACTUATOR="${VWARD_WAN_RECOVERY_ACTUATOR:-/opt/bin/wan-recovery-actuator.sh}"
OBSERVER="${VWARD_WAN_HEALTH_OBSERVER:-/opt/bin/wan-health-watch.sh}"
HEALTH_STATE="${VWARD_WAN_HEALTH_STATE:-/opt/var/lib/wan-health/state}"
LOCK_DIR="${VWARD_WAN_RECOVERY_GATE_LOCK:-/tmp/wan-recovery-controller.lock}"
STATE_FILE="${VWARD_WAN_RECOVERY_STATE_FILE:-/opt/var/lib/wan-recovery/state}"
AUDIT_LOG="${VWARD_WAN_RECOVERY_AUDIT_LOG:-/opt/var/log/wan-recovery.log}"

COOLDOWN_SEC="${VWARD_WAN_RECOVERY_COOLDOWN_SEC:-300}"
WINDOW_SEC="${VWARD_WAN_RECOVERY_WINDOW_SEC:-3600}"
MAX_ATTEMPTS="${VWARD_WAN_RECOVERY_MAX_ATTEMPTS:-3}"
POSTCHECK_ATTEMPTS="${VWARD_WAN_RECOVERY_POSTCHECK_ATTEMPTS:-3}"
POSTCHECK_DELAY_SEC="${VWARD_WAN_RECOVERY_POSTCHECK_DELAY_SEC:-3}"
NOW_EPOCH="${VWARD_NOW_EPOCH:-$(date +%s)}"

UPDATER_LOCK="${VWARD_UPDATE_LOCK_DIR:-/opt/var/run/vward/updater.lock}"
UPDATER_BARRIER="${VWARD_UPDATE_BARRIER_LOCK:-/tmp/vward-update.lock}"
UPDATER_REQUEST="${VWARD_UPDATE_REQUEST_MARKER:-/tmp/vward-update-requested}"
LEGACY_WAN_LOCK="${VWARD_LEGACY_WAN_LOCK:-/tmp/wan-guardian.lock}"
LEGACY_WAN_LOCK_DIR="${VWARD_LEGACY_WAN_LOCK_DIR:-/tmp/wan-guardian.lock.d}"
TUNNEL_MUTATION_LOCK="${VWARD_TUNNEL_MUTATION_LOCK:-/tmp/wg-failopen.lock}"

LOCK_OWNED=0
EXECUTED="NO"
POSTCHECK="NOT_RUN"
PLANNER_DECISION="UNKNOWN"
ACTION="NONE"
EXECUTION_KIND="NONE"
TARGET_RCI_ID="none"
TARGET_LINUX_IF="none"

value()
{
    printf '%s\n' "$1" | awk -F= -v k="$2" '$1==k {print substr($0,index($0,"=")+1); exit}'
}

state_value()
{
    key="$1"
    [ -r "$STATE_FILE" ] || return 1
    awk -F= -v k="$key" '$1==k {print substr($0,index($0,"=")+1); exit}' "$STATE_FILE"
}

valid_uint()
{
    printf '%s\n' "$1" | grep -Eq '^[0-9]+$'
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
    echo "PLANNER_DECISION=$PLANNER_DECISION"
    echo "ACTION=$ACTION"
    echo "EXECUTION_KIND=$EXECUTION_KIND"
    echo "TARGET_RCI_ID=$TARGET_RCI_ID"
    echo "TARGET_LINUX_IF=$TARGET_LINUX_IF"
    echo "POSTCHECK=$POSTCHECK"
    echo "EXECUTED=$EXECUTED"
    exit 0
}

prepare_storage()
{
    state_dir=$(dirname "$STATE_FILE")
    log_dir=$(dirname "$AUDIT_LOG")
    umask 077
    mkdir -p "$state_dir" "$log_dir" || return 1
    touch "$AUDIT_LOG" || return 1
    chmod 600 "$AUDIT_LOG" 2>/dev/null || return 1
    return 0
}

audit()
{
    status="$1"
    reason="$2"
    printf '%s action=%s rci=%s linux_if=%s status=%s reason=%s\n' \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        "$ACTION" "$TARGET_RCI_ID" "$TARGET_LINUX_IF" "$status" "$reason" \
        >> "$AUDIT_LOG"
}

write_state()
{
    last_attempt="$1"
    last_success="$2"
    window_start="$3"
    window_count="$4"
    result="$5"

    tmp="$STATE_FILE.tmp.$$"
    umask 077
    {
        echo "LAST_ATTEMPT_EPOCH=$last_attempt"
        echo "LAST_SUCCESS_EPOCH=$last_success"
        echo "WINDOW_START_EPOCH=$window_start"
        echo "WINDOW_COUNT=$window_count"
        echo "LAST_ACTION=$ACTION"
        echo "LAST_RCI_ID=$TARGET_RCI_ID"
        echo "LAST_LINUX_IF=$TARGET_LINUX_IF"
        echo "LAST_RESULT=$result"
    } > "$tmp" || return 1
    chmod 600 "$tmp" || { rm -f "$tmp"; return 1; }
    mv -f "$tmp" "$STATE_FILE" || { rm -f "$tmp"; return 1; }
    return 0
}

mutation_conflict()
{
    for conflict in \
        "$UPDATER_LOCK" \
        "$UPDATER_BARRIER" \
        "$UPDATER_REQUEST" \
        "$LEGACY_WAN_LOCK" \
        "$LEGACY_WAN_LOCK_DIR" \
        "$TUNNEL_MUTATION_LOCK"
    do
        [ ! -e "$conflict" ] || return 0
    done
    return 1
}

postcheck_health()
{
    attempt=1
    while [ "$attempt" -le "$POSTCHECK_ATTEMPTS" ]; do
        if [ "$attempt" -gt 1 ] && [ "$POSTCHECK_DELAY_SEC" -gt 0 ]; then
            sleep "$POSTCHECK_DELAY_SEC"
        fi

        "$OBSERVER" >/dev/null 2>&1 || true

        if [ -r "$HEALTH_STATE" ]; then
            hs_status=$(state_health_value STATUS)
            hs_class=$(state_health_value CLASS)
            hs_rci=$(state_health_value RCI_ID)
            hs_linux=$(state_health_value LINUX_IF)
            hs_last=$(state_health_value LAST_CHECK)

            if valid_uint "$hs_last" && [ "$hs_last" -ge "$NOW_EPOCH" ] && \
               [ "$hs_status" = "UP" ] && [ "$hs_class" = "HEALTHY" ] && \
               [ "$hs_rci" = "$TARGET_RCI_ID" ] && [ "$hs_linux" = "$TARGET_LINUX_IF" ]; then
                return 0
            fi
        fi

        attempt=$((attempt + 1))
    done
    return 1
}

state_health_value()
{
    key="$1"
    awk -F= -v k="$key" '$1==k {print substr($0,index($0,"=")+1); exit}' "$HEALTH_STATE" 2>/dev/null || true
}

case "$EXECUTION_ENABLED" in
    0|1) ;;
    *) emit BLOCKED invalid_execution_switch ;;
esac

for numeric in "$COOLDOWN_SEC" "$WINDOW_SEC" "$MAX_ATTEMPTS" "$POSTCHECK_ATTEMPTS" "$POSTCHECK_DELAY_SEC" "$NOW_EPOCH"
do
    valid_uint "$numeric" || emit BLOCKED invalid_numeric_policy
 done

[ "$WINDOW_SEC" -gt 0 ] || emit BLOCKED invalid_window
[ "$MAX_ATTEMPTS" -gt 0 ] || emit BLOCKED invalid_max_attempts
[ "$POSTCHECK_ATTEMPTS" -gt 0 ] || emit BLOCKED invalid_postcheck_attempts

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
    SESSION_RECONNECT|INTERFACE_RECONNECT|DHCP_RENEW) ;;
    *) emit BLOCKED unsupported_planner_action ;;
esac

[ -n "$TARGET_RCI_ID" ] && [ "$TARGET_RCI_ID" != "none" ] || emit BLOCKED planner_target_rci_missing
[ -n "$TARGET_LINUX_IF" ] && [ "$TARGET_LINUX_IF" != "none" ] || emit BLOCKED planner_target_linux_missing

if [ "$EXECUTION_ENABLED" = "1" ]; then
    [ -x "$OBSERVER" ] || emit BLOCKED observer_unavailable
    mutation_conflict && emit BLOCKED mutating_component_conflict
    prepare_storage || emit BLOCKED recovery_storage_unavailable

    LAST_ATTEMPT="$(state_value LAST_ATTEMPT_EPOCH 2>/dev/null || echo 0)"
    LAST_SUCCESS="$(state_value LAST_SUCCESS_EPOCH 2>/dev/null || echo 0)"
    WINDOW_START="$(state_value WINDOW_START_EPOCH 2>/dev/null || echo 0)"
    WINDOW_COUNT="$(state_value WINDOW_COUNT 2>/dev/null || echo 0)"

    for numeric in "$LAST_ATTEMPT" "$LAST_SUCCESS" "$WINDOW_START" "$WINDOW_COUNT"
    do
        valid_uint "$numeric" || emit BLOCKED recovery_state_invalid
    done

    [ "$LAST_ATTEMPT" -le "$NOW_EPOCH" ] || emit BLOCKED clock_regressed
    [ "$WINDOW_START" -le "$NOW_EPOCH" ] || emit BLOCKED clock_regressed

    if [ "$LAST_ATTEMPT" -gt 0 ] && [ $((NOW_EPOCH - LAST_ATTEMPT)) -lt "$COOLDOWN_SEC" ]; then
        emit BLOCKED cooldown_active
    fi

    if [ "$WINDOW_START" -eq 0 ] || [ $((NOW_EPOCH - WINDOW_START)) -ge "$WINDOW_SEC" ]; then
        WINDOW_START="$NOW_EPOCH"
        WINDOW_COUNT=0
    fi

    [ "$WINDOW_COUNT" -lt "$MAX_ATTEMPTS" ] || emit BLOCKED rate_limit_reached
    WINDOW_COUNT=$((WINDOW_COUNT + 1))

    write_state "$NOW_EPOCH" "$LAST_SUCCESS" "$WINDOW_START" "$WINDOW_COUNT" RESERVED ||
        emit BLOCKED recovery_state_write_failed
    audit RESERVED pre_mutation || emit BLOCKED recovery_audit_write_failed
fi

ACTUATOR_OUT="$(
    VWARD_WAN_RECOVERY_EXECUTION_ENABLED="$EXECUTION_ENABLED" \
    VWARD_WAN_RECOVERY_CONTROLLER_AUTH=1 \
    "$ACTUATOR" "$ACTION" "$TARGET_RCI_ID" "$TARGET_LINUX_IF" 2>/dev/null || true
)"
ACTUATOR_MODE="$(value "$ACTUATOR_OUT" MODE)"
ACTUATOR_RESULT="$(value "$ACTUATOR_OUT" RESULT)"
ACTUATOR_ACTION="$(value "$ACTUATOR_OUT" ACTION)"
ACTUATOR_RCI_ID="$(value "$ACTUATOR_OUT" TARGET_RCI_ID)"
ACTUATOR_LINUX_IF="$(value "$ACTUATOR_OUT" TARGET_LINUX_IF)"
ACTUATOR_EXECUTED="$(value "$ACTUATOR_OUT" EXECUTED)"
ACTUATOR_MUTATION_ATTEMPTED="$(value "$ACTUATOR_OUT" MUTATION_ATTEMPTED)"
EXECUTION_KIND="$(value "$ACTUATOR_OUT" EXECUTION_KIND)"
ACTUATOR_REASON="$(value "$ACTUATOR_OUT" REASON)"

[ "$ACTUATOR_ACTION" = "$ACTION" ] || emit BLOCKED actuator_action_mismatch
[ "$ACTUATOR_RCI_ID" = "$TARGET_RCI_ID" ] || emit BLOCKED actuator_role_mismatch
[ "$ACTUATOR_LINUX_IF" = "$TARGET_LINUX_IF" ] || emit BLOCKED actuator_mapping_mismatch

case "$EXECUTION_KIND" in
    RCI_SESSION_RECONNECT|RCI_INTERFACE_RECONNECT|RCI_DHCP_RENEW) ;;
    *) emit BLOCKED actuator_execution_kind_invalid ;;
esac

if [ "$EXECUTION_ENABLED" != "1" ]; then
    [ "$ACTUATOR_MODE" = "dryrun" ] || emit BLOCKED actuator_mode_invalid
    [ "$ACTUATOR_EXECUTED" = "NO" ] || emit BLOCKED actuator_execution_guard_violation
    [ "$ACTUATOR_RESULT" = "READY" ] || emit BLOCKED "actuator_${ACTUATOR_REASON:-not_ready}"
    emit READY validated_dryrun_gate
fi

[ "$ACTUATOR_MODE" = "execute" ] || emit BLOCKED actuator_mode_invalid

if [ "$ACTUATOR_RESULT" != "EXECUTED" ] || [ "$ACTUATOR_EXECUTED" != "YES" ]; then
    EXECUTED="${ACTUATOR_EXECUTED:-NO}"
    write_state "$NOW_EPOCH" "$LAST_SUCCESS" "$WINDOW_START" "$WINDOW_COUNT" "ACTUATOR_${ACTUATOR_RESULT:-UNKNOWN}" || true
    audit "ACTUATOR_${ACTUATOR_RESULT:-UNKNOWN}" "${ACTUATOR_REASON:-unknown}" || true
    emit ERROR "actuator_${ACTUATOR_REASON:-execution_failed}"
fi

EXECUTED="YES"
[ "$ACTUATOR_MUTATION_ATTEMPTED" = "YES" ] || {
    write_state "$NOW_EPOCH" "$LAST_SUCCESS" "$WINDOW_START" "$WINDOW_COUNT" ACTUATOR_GUARD_VIOLATION || true
    audit ACTUATOR_GUARD_VIOLATION mutation_not_reported || true
    emit ERROR actuator_mutation_guard_violation
}

if postcheck_health; then
    POSTCHECK="HEALTHY"
    SUCCESS_EPOCH="${VWARD_POSTCHECK_NOW_EPOCH:-$(date +%s)}"
    valid_uint "$SUCCESS_EPOCH" || SUCCESS_EPOCH="$NOW_EPOCH"
    write_state "$NOW_EPOCH" "$SUCCESS_EPOCH" "$WINDOW_START" "$WINDOW_COUNT" SUCCESS ||
        emit ERROR recovery_state_success_write_failed
    audit SUCCESS postcheck_healthy || emit ERROR recovery_audit_success_write_failed
    emit SUCCESS recovery_confirmed
fi

POSTCHECK="FAILED"
write_state "$NOW_EPOCH" "$LAST_SUCCESS" "$WINDOW_START" "$WINDOW_COUNT" UNCONFIRMED || true
audit UNCONFIRMED postcheck_failed || true
emit RECOVERY_UNCONFIRMED postcheck_failed
