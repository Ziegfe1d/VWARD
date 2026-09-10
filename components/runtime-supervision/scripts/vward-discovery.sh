#!/bin/sh
set -eu

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

JQ="${VWARD_JQ:-/opt/bin/jq}"
CURL="${VWARD_CURL:-/opt/bin/curl}"
RCI_BASE="${VWARD_RCI_BASE:-http://127.0.0.1:79/rci}"
DISCOVERY_CONFIG="${VWARD_DISCOVERY_CONFIG:-/opt/etc/vward/discovery.conf}"

fail()
{
    echo "VWARD_DISCOVERY_ERROR=$*" >&2
    exit 2
}

[ -x "$JQ" ] || fail "jq_unavailable"

read_interfaces()
{
    if [ -n "${VWARD_DISCOVERY_INTERFACES_FILE:-}" ]; then
        cat "$VWARD_DISCOVERY_INTERFACES_FILE"
        return
    fi

    "$CURL" --fail --silent --show-error \
        --connect-timeout 2 \
        --max-time 5 \
        "$RCI_BASE/show/interface"
}

read_ip_addr()
{
    if [ -n "${VWARD_DISCOVERY_IP_ADDR_FILE:-}" ]; then
        cat "$VWARD_DISCOVERY_IP_ADDR_FILE"
        return
    fi

    ip -4 addr show 2>/dev/null || true
}

system_name_for_rci()
{
    RCI_ID="$1"

    if [ -n "${VWARD_DISCOVERY_SYSTEM_NAMES_FILE:-}" ] && \
       [ -r "$VWARD_DISCOVERY_SYSTEM_NAMES_FILE" ]; then
        awk -v k="$RCI_ID" '$1 == k {print $2; exit}' \
            "$VWARD_DISCOVERY_SYSTEM_NAMES_FILE"
        return
    fi

    SYSTEM_JSON="$(
        "$CURL" --fail --silent --show-error \
            --connect-timeout 2 \
            --max-time 3 \
            "$RCI_BASE/show/interface/system-name?name=$RCI_ID" \
            2>/dev/null || true
    )"

    printf '%s\n' "$SYSTEM_JSON" |
    "$JQ" -r '."system-name" // ""' 2>/dev/null || true
}

linux_if_for_address()
{
    ADDRESS="$1"

    [ -n "$ADDRESS" ] || return 0

    read_ip_addr |
    awk -v a="$ADDRESS" '
        /^[0-9][0-9]*:/ {
            iface=$2
            iface=substr(iface,1,length(iface)-1)
            next
        }
        $1 == "inet" {
            split($2,p,"/")
            if (p[1] == a) {
                print iface
                exit
            }
        }
    '
}

linux_mapping_for_interface()
{
    RCI_ID="$1"
    ADDRESS="$2"

    SYSTEM_IF="$(system_name_for_rci "$RCI_ID")"

    if [ -n "$SYSTEM_IF" ]; then
        printf '%s|system-name\n' "$SYSTEM_IF"
        return
    fi

    ADDRESS_IF="$(linux_if_for_address "$ADDRESS")"

    if [ -n "$ADDRESS_IF" ]; then
        printf '%s|address\n' "$ADDRESS_IF"
        return
    fi

    printf '|unresolved\n'
}

config_value()
{
    KEY="$1"

    [ -r "$DISCOVERY_CONFIG" ] || return 0

    awk -F= -v k="$KEY" '
        $1 == k {
            print substr($0,index($0,"=")+1)
            exit
        }
    ' "$DISCOVERY_CONFIG"
}

INTERFACES="$(read_interfaces 2>/dev/null || true)"

printf '%s\n' "$INTERFACES" |
"$JQ" -e 'type == "object"' >/dev/null 2>&1 ||
    fail "invalid_interface_inventory"

interface_address()
{
    printf '%s\n' "$INTERFACES" |
    "$JQ" -r --arg n "$1" '.[$n].address // ""' 2>/dev/null
}

wireguard_interface_json()
{
    RCI_ID="$1"
    ADDRESS="$(interface_address "$RCI_ID")"
    LINUX_MAP="$(linux_mapping_for_interface "$RCI_ID" "$ADDRESS")"
    LINUX_IF="${LINUX_MAP%%|*}"
    MAPPING="${LINUX_MAP#*|}"

    printf '%s\n' "$INTERFACES" |
    "$JQ" -c \
        --arg n "$RCI_ID" \
        --arg linux_if "$LINUX_IF" \
        --arg mapping "$MAPPING" '
        .[$n] |
        {
            rci_id:$n,
            linux_if:$linux_if,
            mapping:$mapping,
            description:(.description // ""),
            type:(.type // ""),
            index:(.index // null),
            address:(.address // ""),
            link:(.link // ""),
            connected:(.connected // ""),
            state:(.state // "")
        }
    '
}

wan_interface_json()
{
    RCI_ID="$1"
    ADDRESS="$(interface_address "$RCI_ID")"
    LINUX_MAP="$(linux_mapping_for_interface "$RCI_ID" "$ADDRESS")"
    LINUX_IF="${LINUX_MAP%%|*}"
    MAPPING="${LINUX_MAP#*|}"

    VIA_RCI_ID="$(
        printf '%s\n' "$INTERFACES" |
        "$JQ" -r --arg n "$RCI_ID" '.[$n].via // ""' 2>/dev/null
    )"

    VIA_LINUX_IF=""
    VIA_MAPPING=""

    if [ -n "$VIA_RCI_ID" ]; then
        VIA_ADDRESS="$(interface_address "$VIA_RCI_ID")"
        VIA_MAP="$(linux_mapping_for_interface "$VIA_RCI_ID" "$VIA_ADDRESS")"
        VIA_LINUX_IF="${VIA_MAP%%|*}"
        VIA_MAPPING="${VIA_MAP#*|}"
    fi

    printf '%s\n' "$INTERFACES" |
    "$JQ" -c \
        --arg n "$RCI_ID" \
        --arg linux_if "$LINUX_IF" \
        --arg mapping "$MAPPING" \
        --arg via_rci_id "$VIA_RCI_ID" \
        --arg via_linux_if "$VIA_LINUX_IF" \
        --arg via_mapping "$VIA_MAPPING" '
        .[$n] |
        {
            rci_id:$n,
            interface_name:(."interface-name" // ""),
            linux_if:$linux_if,
            mapping:$mapping,
            via_rci_id:$via_rci_id,
            via_linux_if:$via_linux_if,
            via_mapping:$via_mapping,
            description:(.description // ""),
            type:(.type // ""),
            index:(.index // null),
            address:(.address // ""),
            link:(.link // ""),
            connected:(.connected // ""),
            state:(.state // ""),
            global:(.global // false),
            defaultgw:(.defaultgw // false),
            priority:(.priority // null),
            security_level:(."security-level" // "")
        }
    '
}

WIREGUARD_IDS="$(
    printf '%s\n' "$INTERFACES" |
    "$JQ" -r '
        to_entries[] |
        select((.value.type // "") == "Wireguard") |
        .key
    ' 2>/dev/null
)"

WIREGUARD_JSON="$(
    printf '%s\n' "$WIREGUARD_IDS" |
    while IFS= read -r RCI_ID
    do
        [ -n "$RCI_ID" ] || continue
        wireguard_interface_json "$RCI_ID"
    done |
    "$JQ" -s -c '.'
)"

[ -n "$WIREGUARD_JSON" ] || WIREGUARD_JSON='[]'

WAN_IDS="$(
    printf '%s\n' "$INTERFACES" |
    "$JQ" -r '
        to_entries[] |
        select((.value.global // false) == true) |
        select((.value.defaultgw // false) == true) |
        select((.value["security-level"] // "") == "public") |
        .key
    ' 2>/dev/null
)"

WAN_JSON="$(
    printf '%s\n' "$WAN_IDS" |
    while IFS= read -r RCI_ID
    do
        [ -n "$RCI_ID" ] || continue
        wan_interface_json "$RCI_ID"
    done |
    "$JQ" -s -c '.'
)"

[ -n "$WAN_JSON" ] || WAN_JSON='[]'

wireguard_inventory()
{
    printf '%s\n' "$WIREGUARD_JSON" |
    "$JQ" -c '{
        schema:1,
        provider:"vward-discovery",
        kind:"wireguard",
        count:length,
        interfaces:.
    }'
}

wan_inventory()
{
    printf '%s\n' "$WAN_JSON" |
    "$JQ" -c '{
        schema:1,
        provider:"vward-discovery",
        kind:"wan",
        count:length,
        interfaces:.
    }'
}

tunnel_guard_selection()
{
    PREFERRED="${VWARD_TUNNEL_GUARD_RCI_ID:-}"

    if [ -z "$PREFERRED" ]; then
        PREFERRED="$(config_value tunnel_guard_rci_id)"
    fi

    COUNT="$(
        printf '%s\n' "$WIREGUARD_JSON" |
        "$JQ" -r 'length'
    )"

    if [ -n "$PREFERRED" ]; then
        MATCH="$(
            printf '%s\n' "$WIREGUARD_JSON" |
            "$JQ" -c --arg n "$PREFERRED" '
                map(select(.rci_id == $n)) |
                if length == 1 then .[0] else empty end
            '
        )"

        if [ -n "$MATCH" ]; then
            printf '%s\n' "$MATCH" |
            "$JQ" -c '{
                schema:1,
                provider:"vward-discovery",
                role:"tunnel-guard",
                state:"READY",
                selection:"configured",
                interface:.
            }'
            return 0
        fi

        "$JQ" -n -c \
            --arg preferred "$PREFERRED" \
            --argjson count "$COUNT" '{
                schema:1,
                provider:"vward-discovery",
                role:"tunnel-guard",
                state:"STALE_MAPPING",
                configured_rci_id:$preferred,
                candidate_count:$count
            }'
        return 4
    fi

    case "$COUNT" in
        0)
            "$JQ" -n -c '{
                schema:1,
                provider:"vward-discovery",
                role:"tunnel-guard",
                state:"NOT_FOUND",
                candidate_count:0
            }'
            return 3
            ;;
        1)
            printf '%s\n' "$WIREGUARD_JSON" |
            "$JQ" -c '{
                schema:1,
                provider:"vward-discovery",
                role:"tunnel-guard",
                state:"READY",
                selection:"single-candidate",
                interface:.[0]
            }'
            return 0
            ;;
        *)
            "$JQ" -n -c \
                --argjson count "$COUNT" '{
                    schema:1,
                    provider:"vward-discovery",
                    role:"tunnel-guard",
                    state:"REQUIRES_SELECTION",
                    candidate_count:$count
                }'
            return 4
            ;;
    esac
}

wan_guard_selection()
{
    PREFERRED="${VWARD_WAN_GUARD_RCI_ID:-}"

    if [ -z "$PREFERRED" ]; then
        PREFERRED="$(config_value wan_guard_rci_id)"
    fi

    COUNT="$(
        printf '%s\n' "$WAN_JSON" |
        "$JQ" -r 'length'
    )"

    if [ -n "$PREFERRED" ]; then
        EXISTS="$(
            printf '%s\n' "$INTERFACES" |
            "$JQ" -r --arg n "$PREFERRED" 'has($n)' 2>/dev/null
        )"

        if [ "$EXISTS" != "true" ]; then
            "$JQ" -n -c \
                --arg preferred "$PREFERRED" \
                --argjson count "$COUNT" '{
                    schema:1,
                    provider:"vward-discovery",
                    role:"wan-guard",
                    state:"STALE_MAPPING",
                    configured_rci_id:$preferred,
                    candidate_count:$count
                }'
            return 4
        fi

        ELIGIBLE="$(
            printf '%s\n' "$INTERFACES" |
            "$JQ" -r --arg n "$PREFERRED" '
                ((.[$n].global // false) == true) and
                ((.[$n]["security-level"] // "") == "public")
            ' 2>/dev/null
        )"

        if [ "$ELIGIBLE" != "true" ]; then
            "$JQ" -n -c \
                --arg preferred "$PREFERRED" \
                --argjson count "$COUNT" '{
                    schema:1,
                    provider:"vward-discovery",
                    role:"wan-guard",
                    state:"INVALID_MAPPING",
                    configured_rci_id:$preferred,
                    candidate_count:$count
                }'
            return 4
        fi

        MATCH="$(wan_interface_json "$PREFERRED")"

        printf '%s\n' "$MATCH" |
        "$JQ" -c '{
            schema:1,
            provider:"vward-discovery",
            role:"wan-guard",
            state:"READY",
            selection:"configured",
            interface:.
        }'
        return 0
    fi

    case "$COUNT" in
        0)
            "$JQ" -n -c '{
                schema:1,
                provider:"vward-discovery",
                role:"wan-guard",
                state:"NOT_FOUND",
                candidate_count:0
            }'
            return 3
            ;;
        1)
            printf '%s\n' "$WAN_JSON" |
            "$JQ" -c '{
                schema:1,
                provider:"vward-discovery",
                role:"wan-guard",
                state:"READY",
                selection:"single-candidate",
                interface:.[0]
            }'
            return 0
            ;;
        *)
            "$JQ" -n -c \
                --argjson count "$COUNT" '{
                    schema:1,
                    provider:"vward-discovery",
                    role:"wan-guard",
                    state:"REQUIRES_SELECTION",
                    candidate_count:$count
                }'
            return 4
            ;;
    esac
}

COMMAND="${1:-wireguard}"

case "$COMMAND" in
    wireguard)
        wireguard_inventory
        ;;
    tunnel-guard)
        tunnel_guard_selection
        ;;
    wan)
        wan_inventory
        ;;
    wan-guard)
        wan_guard_selection
        ;;
    *)
        echo "Usage: vward-discovery.sh {wireguard|tunnel-guard|wan|wan-guard}" >&2
        exit 64
        ;;
esac