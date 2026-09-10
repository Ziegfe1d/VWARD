#!/opt/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

MODE="dryrun"
STATE="${VWARD_WAN_HEALTH_STATE:-/opt/var/lib/wan-health/state}"
DISCOVERY="${VWARD_DISCOVERY_BIN:-/opt/bin/vward-discovery.sh}"
JQ="${VWARD_JQ:-/opt/bin/jq}"
MAX_STATE_AGE="${VWARD_WAN_RECOVERY_MAX_STATE_AGE:-120}"
CONFIRM_FAILURES="${VWARD_WAN_RECOVERY_CONFIRM_FAILURES:-3}"
NOW_EPOCH="${VWARD_NOW_EPOCH:-$(date +%s)}"

num_or()
{
    case "$1" in
        ''|*[!0-9]*) printf '%s\n' "$2" ;;
        *) printf '%s\n' "$1" ;;
    esac
}

state_value()
{
    awk -F= -v k="$1" '$1==k {print substr($0,index($0,"=")+1); exit}' "$STATE" 2>/dev/null
}

emit()
{
    DECISION="$1"
    ACTION="$2"
    REASON="$3"

    echo "MODE=$MODE"
    echo "DECISION=$DECISION"
    echo "ACTION=$ACTION"
    echo "REASON=$REASON"
    echo "STATUS=${STATUS:-UNKNOWN}"
    echo "CLASS=${CLASS:-UNKNOWN}"
    echo "FAIL_COUNT=${FAIL_COUNT:-0}"
    echo "DISCOVERY_STATE=${DISCOVERY_STATE:-UNAVAILABLE}"
    echo "TARGET_RCI_ID=${CURRENT_RCI_ID:-none}"
    echo "TARGET_LINUX_IF=${CURRENT_LINUX_IF:-none}"
    echo "TARGET_TYPE=${CURRENT_TYPE:-unknown}"
    echo "VIA_RCI_ID=${CURRENT_VIA_RCI_ID:-none}"
    echo "VIA_LINUX_IF=${CURRENT_VIA_LINUX_IF:-none}"
    echo "EXECUTED=NO"
    exit 0
}

case "$MAX_STATE_AGE" in
    ''|*[!0-9]*) MAX_STATE_AGE=120 ;;
esac
case "$CONFIRM_FAILURES" in
    ''|*[!0-9]*) CONFIRM_FAILURES=3 ;;
esac
case "$NOW_EPOCH" in
    ''|*[!0-9]*) emit BLOCKED NONE invalid_clock ;;
esac

[ -r "$STATE" ] || emit BLOCKED NONE observer_unavailable

STATUS="$(state_value STATUS)"
CLASS="$(state_value CLASS)"
LAST_CHECK="$(state_value LAST_CHECK)"
FAIL_COUNT="$(num_or "$(state_value FAIL_COUNT)" 0)"
OBSERVER_RCI_ID="$(state_value RCI_ID)"
OBSERVER_LINUX_IF="$(state_value LINUX_IF)"

[ "$OBSERVER_RCI_ID" = "none" ] && OBSERVER_RCI_ID=""
[ "$OBSERVER_LINUX_IF" = "none" ] && OBSERVER_LINUX_IF=""

LAST_CHECK="$(num_or "$LAST_CHECK" 0)"
[ "$LAST_CHECK" -gt 0 ] || emit BLOCKED NONE observer_timestamp_missing

STATE_AGE=$((NOW_EPOCH - LAST_CHECK))
case "$STATE_AGE" in
    -*) emit BLOCKED NONE observer_clock_skew ;;
esac
[ "$STATE_AGE" -le "$MAX_STATE_AGE" ] || emit BLOCKED NONE observer_stale

[ -x "$DISCOVERY" ] || emit BLOCKED NONE discovery_unavailable
[ -x "$JQ" ] || emit BLOCKED NONE jq_unavailable

DISCOVERY_JSON="$("$DISCOVERY" wan-guard 2>/dev/null)"
DISCOVERY_RC=$?

if ! printf '%s\n' "$DISCOVERY_JSON" |
    "$JQ" -e 'type == "object" and .role == "wan-guard"' >/dev/null 2>&1
then
    DISCOVERY_STATE="INVALID_RESULT"
    emit BLOCKED NONE discovery_invalid_result
fi

DISCOVERY_STATE="$(printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -r '.state // "UNAVAILABLE"')"
[ "$DISCOVERY_STATE" = "READY" ] || emit BLOCKED NONE "discovery_$DISCOVERY_STATE"

CURRENT_RCI_ID="$(printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -r '.interface.rci_id // ""')"
CURRENT_LINUX_IF="$(printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -r '.interface.linux_if // ""')"
CURRENT_TYPE="$(printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -r '.interface.type // ""')"
CURRENT_VIA_RCI_ID="$(printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -r '.interface.via_rci_id // ""')"
CURRENT_VIA_LINUX_IF="$(printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -r '.interface.via_linux_if // ""')"

[ -n "$CURRENT_RCI_ID" ] || emit BLOCKED NONE discovery_missing_rci_id
[ -n "$CURRENT_LINUX_IF" ] || emit BLOCKED NONE discovery_missing_linux_if
[ "$OBSERVER_RCI_ID" = "$CURRENT_RCI_ID" ] || emit BLOCKED NONE observer_role_mismatch
[ "$OBSERVER_LINUX_IF" = "$CURRENT_LINUX_IF" ] || emit BLOCKED NONE observer_mapping_mismatch

case "$STATUS" in
    UP)
        emit HOLD NONE observer_healthy
        ;;
    UNKNOWN|'')
        emit BLOCKED NONE observer_unknown
        ;;
    DEGRADED)
        emit HOLD NONE observer_degraded
        ;;
esac

case "$CLASS" in
    DNS_ONLY_FAILURE|UTILITY_DEGRADED|DEGRADED|DISCOVERY_*|MAPPING_UNRESOLVED)
        emit HOLD NONE non_recovery_class
        ;;
    PHY_DOWN)
        emit HOLD NONE physical_link_down
        ;;
esac

if [ "$FAIL_COUNT" -lt "$CONFIRM_FAILURES" ]; then
    emit DEFER NONE "confirm_${FAIL_COUNT}_of_${CONFIRM_FAILURES}"
fi

LOGICAL_UPLINK=0
[ -n "$CURRENT_VIA_RCI_ID" ] && LOGICAL_UPLINK=1

case "$CLASS" in
    SESSION_FAILURE)
        if [ "$LOGICAL_UPLINK" -eq 1 ]; then
            emit PLAN SESSION_RECONNECT confirmed_logical_session_failure
        fi
        emit HOLD NONE session_type_unconfirmed
        ;;

    ADDRESS_FAILURE)
        if [ "$LOGICAL_UPLINK" -eq 1 ]; then
            emit PLAN SESSION_RECONNECT confirmed_logical_address_failure
        fi
        emit HOLD NONE addressing_capability_required
        ;;

    LINK_FAILURE|GATEWAY_FAILURE|INTERNET_FAILURE)
        if [ "$LOGICAL_UPLINK" -eq 1 ]; then
            emit PLAN SESSION_RECONNECT confirmed_logical_path_failure
        fi
        emit PLAN INTERFACE_RECONNECT confirmed_physical_path_failure
        ;;

    ROUTE_FAILURE)
        emit HOLD NONE route_recheck_required
        ;;

    *)
        emit HOLD NONE unsupported_failure_class
        ;;
esac
