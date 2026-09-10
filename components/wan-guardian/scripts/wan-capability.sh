#!/opt/bin/sh
set -eu

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

DISCOVERY="${VWARD_DISCOVERY_BIN:-/opt/bin/vward-discovery.sh}"
JQ="${VWARD_JQ:-/opt/bin/jq}"
NDMC="${VWARD_NDMC:-/bin/ndmc}"
RUNNING_CONFIG_FILE="${VWARD_RUNNING_CONFIG_FILE:-}"

emit_unavailable()
{
    reason="$1"
    "$JQ" -n -c --arg reason "$reason" '{
        schema:1,
        provider:"wan-capability",
        role:"wan-guard",
        state:"UNAVAILABLE",
        reason:$reason
    }'
    exit 4
}

[ -x "$JQ" ] || {
    echo '{"schema":1,"provider":"wan-capability","role":"wan-guard","state":"UNAVAILABLE","reason":"jq_unavailable"}'
    exit 4
}

[ -x "$DISCOVERY" ] || emit_unavailable discovery_unavailable

ROLE_JSON="$("$DISCOVERY" wan-guard 2>/dev/null || true)"
printf '%s\n' "$ROLE_JSON" |
"$JQ" -e 'type == "object" and .role == "wan-guard"' >/dev/null 2>&1 ||
    emit_unavailable discovery_invalid_result

ROLE_STATE="$(printf '%s\n' "$ROLE_JSON" | "$JQ" -r '.state // "UNAVAILABLE"')"
[ "$ROLE_STATE" = READY ] || emit_unavailable "discovery_$ROLE_STATE"

RCI_ID="$(printf '%s\n' "$ROLE_JSON" | "$JQ" -r '.interface.rci_id // ""')"
LINUX_IF="$(printf '%s\n' "$ROLE_JSON" | "$JQ" -r '.interface.linux_if // ""')"
TYPE="$(printf '%s\n' "$ROLE_JSON" | "$JQ" -r '.interface.type // ""')"
VIA_RCI_ID="$(printf '%s\n' "$ROLE_JSON" | "$JQ" -r '.interface.via_rci_id // ""')"
VIA_LINUX_IF="$(printf '%s\n' "$ROLE_JSON" | "$JQ" -r '.interface.via_linux_if // ""')"

[ -n "$RCI_ID" ] || emit_unavailable missing_rci_id

read_running_config()
{
    if [ -n "$RUNNING_CONFIG_FILE" ]; then
        [ -r "$RUNNING_CONFIG_FILE" ] || return 1
        cat "$RUNNING_CONFIG_FILE"
        return
    fi

    [ -x "$NDMC" ] || return 1
    "$NDMC" -c "show running-config" 2>/dev/null
}

RUNNING_CONFIG="$(read_running_config || true)"
[ -n "$RUNNING_CONFIG" ] || emit_unavailable running_config_unavailable

BLOCK="$(
    printf '%s\n' "$RUNNING_CONFIG" |
    awk -v target="$RCI_ID" '
        $1 == "interface" && $2 == target {inside=1; next}
        inside && $1 == "!" {exit}
        inside && $1 == "interface" {exit}
        inside {
            line=$0
            sub(/^[[:space:]]+/, "", line)
            print line
        }
    '
)"

[ -n "$BLOCK" ] || emit_unavailable interface_block_not_found

ADDRESSING_MODE=unknown
DHCP_RENEW=false
ADDRESSING_EVIDENCE=none

if printf '%s\n' "$BLOCK" | grep -Eq '^ip address dhcp([[:space:]]|$)'; then
    ADDRESSING_MODE=dhcp
    DHCP_RENEW=true
    ADDRESSING_EVIDENCE=running_config_ip_address_dhcp
elif printf '%s\n' "$BLOCK" | grep -Eq '^ip address [0-9]+\.[0-9]+\.[0-9]+\.[0-9]+([[:space:]]|$)'; then
    ADDRESSING_MODE=static
    ADDRESSING_EVIDENCE=running_config_static_ipv4
elif [ -n "$VIA_RCI_ID" ]; then
    ADDRESSING_MODE=logical
    ADDRESSING_EVIDENCE=discovery_logical_uplink
fi

SESSION_RECONNECT=false
[ -n "$VIA_RCI_ID" ] && SESSION_RECONNECT=true

"$JQ" -n -c \
    --arg rci_id "$RCI_ID" \
    --arg linux_if "$LINUX_IF" \
    --arg type "$TYPE" \
    --arg via_rci_id "$VIA_RCI_ID" \
    --arg via_linux_if "$VIA_LINUX_IF" \
    --arg addressing_mode "$ADDRESSING_MODE" \
    --arg addressing_evidence "$ADDRESSING_EVIDENCE" \
    --argjson dhcp_renew "$DHCP_RENEW" \
    --argjson session_reconnect "$SESSION_RECONNECT" '{
        schema:1,
        provider:"wan-capability",
        role:"wan-guard",
        state:"READY",
        interface:{
            rci_id:$rci_id,
            linux_if:$linux_if,
            type:$type,
            via_rci_id:$via_rci_id,
            via_linux_if:$via_linux_if
        },
        addressing:{
            mode:$addressing_mode,
            evidence:$addressing_evidence,
            dhcp_renew:$dhcp_renew
        },
        recovery:{
            interface_reconnect:true,
            session_reconnect:$session_reconnect
        },
        source:"running-config"
    }'
