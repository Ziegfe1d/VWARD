#!/opt/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

VERSION="0.2.0-beta.1-gated"
EXECUTION_ENABLED="${VWARD_WAN_RECOVERY_EXECUTION_ENABLED:-0}"
CONTROLLER_AUTH="${VWARD_WAN_RECOVERY_CONTROLLER_AUTH:-0}"
DISCOVERY="${VWARD_DISCOVERY_BIN:-/opt/bin/vward-discovery.sh}"
CAPABILITY="${VWARD_WAN_CAPABILITY_BIN:-/opt/bin/wan-capability.sh}"
JQ="${VWARD_JQ:-/opt/bin/jq}"
NDMC="${VWARD_NDMC:-/bin/ndmc}"
RECONNECT_PAUSE_SEC="${VWARD_WAN_RECOVERY_RECONNECT_PAUSE_SEC:-1}"

ACTION="${1:-}"
EXPECTED_RCI_ID="${2:-}"
EXPECTED_LINUX_IF="${3:-}"

MODE="dryrun"
[ "$EXECUTION_ENABLED" = "1" ] && MODE="execute"
EXECUTED="NO"
MUTATION_ATTEMPTED="NO"
EXECUTION_KIND="NONE"
RECOVERY_NOTE="none"

emit()
{
    RESULT="$1"
    REASON="$2"

    echo "VERSION=$VERSION"
    echo "MODE=$MODE"
    echo "RESULT=$RESULT"
    echo "ACTION=${ACTION:-NONE}"
    echo "REASON=$REASON"
    echo "EXECUTION_KIND=${EXECUTION_KIND:-NONE}"
    echo "CAPABILITY_STATE=${CAPABILITY_STATE:-NOT_CHECKED}"
    echo "ADDRESSING_MODE=${ADDRESSING_MODE:-unknown}"
    echo "TARGET_RCI_ID=${CURRENT_RCI_ID:-none}"
    echo "TARGET_LINUX_IF=${CURRENT_LINUX_IF:-none}"
    echo "TARGET_TYPE=${CURRENT_TYPE:-unknown}"
    echo "VIA_RCI_ID=${CURRENT_VIA_RCI_ID:-none}"
    echo "VIA_LINUX_IF=${CURRENT_VIA_LINUX_IF:-none}"
    echo "MUTATION_ATTEMPTED=$MUTATION_ATTEMPTED"
    echo "RECOVERY_NOTE=$RECOVERY_NOTE"
    echo "EXECUTED=$EXECUTED"
    exit 0
}

valid_rci_id()
{
    printf '%s\n' "$1" | grep -Eq '^[A-Za-z0-9_.:@+-]+$'
}

valid_linux_if()
{
    printf '%s\n' "$1" | grep -Eq '^[A-Za-z0-9_.:@+-]+$'
}

valid_uint()
{
    printf '%s\n' "$1" | grep -Eq '^[0-9]+$'
}

load_capability()
{
    [ -x "$CAPABILITY" ] || {
        CAPABILITY_STATE="UNAVAILABLE"
        return 1
    }

    CAPABILITY_JSON="$("$CAPABILITY" 2>/dev/null || true)"
    if ! printf '%s\n' "$CAPABILITY_JSON" |
        "$JQ" -e 'type == "object" and .provider == "wan-capability" and .role == "wan-guard"' >/dev/null 2>&1
    then
        CAPABILITY_STATE="INVALID_RESULT"
        return 1
    fi

    CAPABILITY_STATE="$(printf '%s\n' "$CAPABILITY_JSON" | "$JQ" -r '.state // "UNAVAILABLE"')"
    [ "$CAPABILITY_STATE" = "READY" ] || return 1

    CAP_RCI_ID="$(printf '%s\n' "$CAPABILITY_JSON" | "$JQ" -r '.interface.rci_id // ""')"
    CAP_LINUX_IF="$(printf '%s\n' "$CAPABILITY_JSON" | "$JQ" -r '.interface.linux_if // ""')"
    ADDRESSING_MODE="$(printf '%s\n' "$CAPABILITY_JSON" | "$JQ" -r '.addressing.mode // "unknown"')"
    DHCP_RENEW_CAPABLE="$(printf '%s\n' "$CAPABILITY_JSON" | "$JQ" -r '.addressing.dhcp_renew // false')"

    [ "$CAP_RCI_ID" = "$CURRENT_RCI_ID" ] || {
        CAPABILITY_STATE="ROLE_MISMATCH"
        return 1
    }
    [ "$CAP_LINUX_IF" = "$CURRENT_LINUX_IF" ] || {
        CAPABILITY_STATE="MAPPING_MISMATCH"
        return 1
    }

    return 0
}

run_ndmc()
{
    NDMC_LINE="$1"
    LD_LIBRARY_PATH= "$NDMC" -c "$NDMC_LINE" >/dev/null 2>&1
}

execute_reconnect()
{
    MUTATION_ATTEMPTED="YES"

    if ! run_ndmc "interface $CURRENT_RCI_ID down"; then
        EXECUTED="FAILED"
        emit ERROR interface_down_failed
    fi

    if [ "$RECONNECT_PAUSE_SEC" -gt 0 ]; then
        sleep "$RECONNECT_PAUSE_SEC"
    fi

    if run_ndmc "interface $CURRENT_RCI_ID up"; then
        EXECUTED="YES"
        emit EXECUTED reconnect_completed
    fi

    RECOVERY_NOTE="up_retry"
    sleep 1
    if run_ndmc "interface $CURRENT_RCI_ID up"; then
        EXECUTED="YES"
        RECOVERY_NOTE="up_retry_succeeded"
        emit EXECUTED reconnect_completed_after_retry
    fi

    EXECUTED="PARTIAL"
    RECOVERY_NOTE="up_retry_failed"
    emit ERROR interface_up_failed
}

execute_dhcp_renew()
{
    MUTATION_ATTEMPTED="YES"

    if run_ndmc "interface $CURRENT_RCI_ID ip dhcp client renew"; then
        EXECUTED="YES"
        emit EXECUTED dhcp_renew_completed
    fi

    EXECUTED="FAILED"
    emit ERROR dhcp_renew_failed
}

case "$EXECUTION_ENABLED" in
    0|1) ;;
    *) emit BLOCKED invalid_execution_switch ;;
esac

case "$CONTROLLER_AUTH" in
    0|1) ;;
    *) emit BLOCKED invalid_controller_auth ;;
esac

valid_uint "$RECONNECT_PAUSE_SEC" || emit BLOCKED invalid_reconnect_pause
[ "$RECONNECT_PAUSE_SEC" -le 30 ] || emit BLOCKED reconnect_pause_too_large

case "$ACTION" in
    SESSION_RECONNECT|INTERFACE_RECONNECT|DHCP_RENEW)
        ;;
    '')
        emit BLOCKED missing_action
        ;;
    *)
        emit BLOCKED unsupported_action
        ;;
esac

[ -n "$EXPECTED_RCI_ID" ] || emit BLOCKED missing_expected_rci_id
[ -n "$EXPECTED_LINUX_IF" ] || emit BLOCKED missing_expected_linux_if
valid_rci_id "$EXPECTED_RCI_ID" || emit BLOCKED invalid_expected_rci_id
valid_linux_if "$EXPECTED_LINUX_IF" || emit BLOCKED invalid_expected_linux_if

[ -x "$DISCOVERY" ] || emit BLOCKED discovery_unavailable
[ -x "$JQ" ] || emit BLOCKED jq_unavailable

DISCOVERY_JSON="$("$DISCOVERY" wan-guard 2>/dev/null || true)"

if ! printf '%s\n' "$DISCOVERY_JSON" |
    "$JQ" -e 'type == "object" and .role == "wan-guard"' >/dev/null 2>&1
then
    emit BLOCKED discovery_invalid_result
fi

DISCOVERY_STATE="$(printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -r '.state // "UNAVAILABLE"')"
[ "$DISCOVERY_STATE" = "READY" ] || emit BLOCKED "discovery_$DISCOVERY_STATE"

CURRENT_RCI_ID="$(printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -r '.interface.rci_id // ""')"
CURRENT_LINUX_IF="$(printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -r '.interface.linux_if // ""')"
CURRENT_TYPE="$(printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -r '.interface.type // ""')"
CURRENT_VIA_RCI_ID="$(printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -r '.interface.via_rci_id // ""')"
CURRENT_VIA_LINUX_IF="$(printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -r '.interface.via_linux_if // ""')"

[ -n "$CURRENT_RCI_ID" ] || emit BLOCKED discovery_missing_rci_id
[ -n "$CURRENT_LINUX_IF" ] || emit BLOCKED discovery_missing_linux_if
valid_rci_id "$CURRENT_RCI_ID" || emit BLOCKED invalid_discovered_rci_id
valid_linux_if "$CURRENT_LINUX_IF" || emit BLOCKED invalid_discovered_linux_if

[ "$CURRENT_RCI_ID" = "$EXPECTED_RCI_ID" ] || emit BLOCKED target_role_mismatch
[ "$CURRENT_LINUX_IF" = "$EXPECTED_LINUX_IF" ] || emit BLOCKED target_mapping_mismatch

case "$ACTION" in
    SESSION_RECONNECT)
        [ -n "$CURRENT_VIA_RCI_ID" ] || emit BLOCKED logical_uplink_required
        valid_rci_id "$CURRENT_VIA_RCI_ID" || emit BLOCKED invalid_via_rci_id
        [ -n "$CURRENT_VIA_LINUX_IF" ] || emit BLOCKED via_linux_mapping_required
        valid_linux_if "$CURRENT_VIA_LINUX_IF" || emit BLOCKED invalid_via_linux_if
        EXECUTION_KIND="RCI_SESSION_RECONNECT"
        ;;

    INTERFACE_RECONNECT)
        [ -z "$CURRENT_VIA_RCI_ID" ] || emit BLOCKED physical_uplink_required
        EXECUTION_KIND="RCI_INTERFACE_RECONNECT"
        ;;

    DHCP_RENEW)
        [ -z "$CURRENT_VIA_RCI_ID" ] || emit BLOCKED physical_uplink_required
        if ! load_capability; then
            emit BLOCKED "capability_$CAPABILITY_STATE"
        fi
        [ "$ADDRESSING_MODE" = "dhcp" ] || emit BLOCKED addressing_not_dhcp
        [ "$DHCP_RENEW_CAPABLE" = "true" ] || emit BLOCKED dhcp_renew_not_capable
        EXECUTION_KIND="RCI_DHCP_RENEW"
        ;;
esac

if [ "$EXECUTION_ENABLED" != "1" ]; then
    emit READY validated_dryrun
fi

[ "$CONTROLLER_AUTH" = "1" ] || emit BLOCKED controller_authorization_required
[ -x "$NDMC" ] || emit BLOCKED ndmc_unavailable

case "$ACTION" in
    SESSION_RECONNECT|INTERFACE_RECONNECT)
        execute_reconnect
        ;;
    DHCP_RENEW)
        execute_dhcp_renew
        ;;
esac

emit ERROR unreachable_execution_state
