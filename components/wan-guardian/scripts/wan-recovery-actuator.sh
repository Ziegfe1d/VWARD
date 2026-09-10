#!/opt/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

VERSION="0.2.0-beta.1-dryrun"
MODE="dryrun"
DISCOVERY="${VWARD_DISCOVERY_BIN:-/opt/bin/vward-discovery.sh}"
JQ="${VWARD_JQ:-/opt/bin/jq}"

ACTION="${1:-}"
EXPECTED_RCI_ID="${2:-}"
EXPECTED_LINUX_IF="${3:-}"

emit()
{
    RESULT="$1"
    REASON="$2"

    echo "VERSION=$VERSION"
    echo "MODE=$MODE"
    echo "RESULT=$RESULT"
    echo "ACTION=${ACTION:-NONE}"
    echo "REASON=$REASON"
    echo "TARGET_RCI_ID=${CURRENT_RCI_ID:-none}"
    echo "TARGET_LINUX_IF=${CURRENT_LINUX_IF:-none}"
    echo "TARGET_TYPE=${CURRENT_TYPE:-unknown}"
    echo "VIA_RCI_ID=${CURRENT_VIA_RCI_ID:-none}"
    echo "VIA_LINUX_IF=${CURRENT_VIA_LINUX_IF:-none}"
    echo "EXECUTED=NO"
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

case "$ACTION" in
    SESSION_RECONNECT|INTERFACE_RECONNECT)
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
esac

echo "VERSION=$VERSION"
echo "MODE=$MODE"
echo "RESULT=READY"
echo "ACTION=$ACTION"
echo "REASON=validated_dryrun"
echo "EXECUTION_KIND=$EXECUTION_KIND"
echo "TARGET_RCI_ID=$CURRENT_RCI_ID"
echo "TARGET_LINUX_IF=$CURRENT_LINUX_IF"
echo "TARGET_TYPE=${CURRENT_TYPE:-unknown}"
echo "VIA_RCI_ID=${CURRENT_VIA_RCI_ID:-none}"
echo "VIA_LINUX_IF=${CURRENT_VIA_LINUX_IF:-none}"
echo "EXECUTED=NO"
exit 0
