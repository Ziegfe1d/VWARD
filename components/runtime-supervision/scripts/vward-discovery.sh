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

        ADDRESS="$(
            printf '%s\n' "$INTERFACES" |
            "$JQ" -r --arg n "$RCI_ID" '.[$n].address // ""'
        )"

        LINUX_IF="$(linux_if_for_address "$ADDRESS")"

        printf '%s\n' "$INTERFACES" |
        "$JQ" -c \
            --arg n "$RCI_ID" \
            --arg linux_if "$LINUX_IF" '
            .[$n] |
            {
                rci_id:$n,
                linux_if:$linux_if,
                mapping:(if $linux_if == "" then "unresolved" else "address" end),
                description:(.description // ""),
                type:(.type // ""),
                index:(.index // null),
                address:(.address // ""),
                link:(.link // ""),
                connected:(.connected // ""),
                state:(.state // "")
            }
        '
    done |
    "$JQ" -s -c '.'
)"

[ -n "$WIREGUARD_JSON" ] || WIREGUARD_JSON='[]'

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

COMMAND="${1:-wireguard}"

case "$COMMAND" in
    wireguard)
        wireguard_inventory
        ;;
    tunnel-guard)
        tunnel_guard_selection
        ;;
    *)
        echo "Usage: vward-discovery.sh {wireguard|tunnel-guard}" >&2
        exit 64
        ;;
esac
