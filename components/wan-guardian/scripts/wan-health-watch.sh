#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

DIR="${VWARD_WAN_HEALTH_DIR:-/opt/var/lib/wan-health}"
STATE="$DIR/state"
LOG="${VWARD_WAN_HEALTH_LOG:-/opt/var/log/wan-health.log}"
LOCK="${VWARD_WAN_HEALTH_LOCK:-/tmp/wan-health-watch.lock}"

JQ="${VWARD_JQ:-/opt/bin/jq}"
DISCOVERY="${VWARD_DISCOVERY_BIN:-/opt/bin/vward-discovery.sh}"
CURL_BIN="${VWARD_CURL:-/opt/bin/curl}"
PING_BIN="${VWARD_PING:-/opt/bin/ping}"
SYS_CLASS_NET="${VWARD_SYS_CLASS_NET:-/sys/class/net}"

mkdir -p "$DIR"

if ! mkdir "$LOCK" 2>/dev/null; then
    OLD_PID="$(cat "$LOCK/pid" 2>/dev/null)"

    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        exit 0
    fi

    rm -rf "$LOCK"
    mkdir "$LOCK" || exit 1
fi

echo $$ > "$LOCK/pid"

cleanup()
{
    rm -rf "$LOCK"
}

trap cleanup EXIT INT TERM

OLD_STATUS="UNKNOWN"
OLD_CLASS="UNKNOWN"
FAIL_COUNT=0
OK_COUNT=0

if [ -f "$STATE" ]; then
    OLD_STATUS="$(awk -F= '$1=="STATUS"{print $2}' "$STATE")"
    OLD_CLASS="$(awk -F= '$1=="CLASS"{print $2}' "$STATE")"
    FAIL_COUNT="$(awk -F= '$1=="FAIL_COUNT"{print $2}' "$STATE")"
    OK_COUNT="$(awk -F= '$1=="OK_COUNT"{print $2}' "$STATE")"
fi

case "$FAIL_COUNT" in
    ''|*[!0-9]*) FAIL_COUNT=0 ;;
esac

case "$OK_COUNT" in
    ''|*[!0-9]*) OK_COUNT=0 ;;
esac

DISCOVERY_STATE="UNAVAILABLE"
DISCOVERY_SELECTION=""
DISCOVERY_MAPPING=""
DISCOVERY_RC=127
WAN_RCI_ID=""
WAN_IF=""
WAN_TYPE=""
WAN_LINK=""
WAN_CONNECTED=""
WAN_STATE=""
WAN_ADDRESS=""
WAN_DEFAULTGW="false"
VIA_RCI_ID=""
VIA_IF=""
VIA_MAPPING=""
DISCOVERY_USABLE=0

if [ -x "$DISCOVERY" ] && [ -x "$JQ" ]; then
    DISCOVERY_JSON="$("$DISCOVERY" wan-guard 2>/dev/null)"
    DISCOVERY_RC=$?

    if printf '%s\n' "$DISCOVERY_JSON" |
        "$JQ" -e 'type == "object" and .role == "wan-guard"' >/dev/null 2>&1
    then
        DISCOVERY_STATE="$(
            printf '%s\n' "$DISCOVERY_JSON" |
            "$JQ" -r '.state // "UNAVAILABLE"'
        )"
        DISCOVERY_SELECTION="$(
            printf '%s\n' "$DISCOVERY_JSON" |
            "$JQ" -r '.selection // ""'
        )"
        DISCOVERY_MAPPING="$(
            printf '%s\n' "$DISCOVERY_JSON" |
            "$JQ" -r '.interface.mapping // ""'
        )"
        WAN_RCI_ID="$(
            printf '%s\n' "$DISCOVERY_JSON" |
            "$JQ" -r '.interface.rci_id // ""'
        )"
        WAN_IF="$(
            printf '%s\n' "$DISCOVERY_JSON" |
            "$JQ" -r '.interface.linux_if // ""'
        )"
        WAN_TYPE="$(
            printf '%s\n' "$DISCOVERY_JSON" |
            "$JQ" -r '.interface.type // ""'
        )"
        WAN_LINK="$(
            printf '%s\n' "$DISCOVERY_JSON" |
            "$JQ" -r '.interface.link // ""'
        )"
        WAN_CONNECTED="$(
            printf '%s\n' "$DISCOVERY_JSON" |
            "$JQ" -r '.interface.connected // ""'
        )"
        WAN_STATE="$(
            printf '%s\n' "$DISCOVERY_JSON" |
            "$JQ" -r '.interface.state // ""'
        )"
        WAN_ADDRESS="$(
            printf '%s\n' "$DISCOVERY_JSON" |
            "$JQ" -r '.interface.address // ""'
        )"
        WAN_DEFAULTGW="$(
            printf '%s\n' "$DISCOVERY_JSON" |
            "$JQ" -r '.interface.defaultgw // false'
        )"
        VIA_RCI_ID="$(
            printf '%s\n' "$DISCOVERY_JSON" |
            "$JQ" -r '.interface.via_rci_id // ""'
        )"
        VIA_IF="$(
            printf '%s\n' "$DISCOVERY_JSON" |
            "$JQ" -r '.interface.via_linux_if // ""'
        )"
        VIA_MAPPING="$(
            printf '%s\n' "$DISCOVERY_JSON" |
            "$JQ" -r '.interface.via_mapping // ""'
        )"
    else
        DISCOVERY_STATE="INVALID_RESULT"
    fi
fi

if [ "$DISCOVERY_STATE" = "READY" ] &&
   [ -n "$WAN_RCI_ID" ] &&
   [ -n "$WAN_IF" ]; then
    DISCOVERY_USABLE=1
fi

PATH_IF="$WAN_IF"
PHYSICAL_IF="$WAN_IF"

if [ -n "$VIA_IF" ]; then
    PHYSICAL_IF="$VIA_IF"
fi

INTERNET_JSON=""
INTERNET_JSON_OK=0

if [ "$DISCOVERY_USABLE" -eq 1 ]; then
    if [ -n "${VWARD_WAN_HEALTH_INET_FILE:-}" ]; then
        INTERNET_JSON="$(cat "$VWARD_WAN_HEALTH_INET_FILE" 2>/dev/null)"
    else
        INTERNET_JSON="$(
            "$CURL_BIN" --fail --silent --show-error \
                --connect-timeout 2 \
                --max-time 3 \
                'http://127.0.0.1:79/rci/show/internet/status' \
                2>/dev/null
        )"
    fi

    if printf '%s\n' "$INTERNET_JSON" |
        "$JQ" -e 'type == "object"' >/dev/null 2>&1
    then
        INTERNET_JSON_OK=1
    fi
fi

GATEWAY=""
GATEWAY_ACCESSIBLE="false"
DNS_ACCESSIBLE="false"
INTERNET="false"
RELIABLE="false"

if [ "$INTERNET_JSON_OK" -eq 1 ]; then
    GATEWAY="$(
        printf '%s\n' "$INTERNET_JSON" |
        "$JQ" -r '.gateway.address // ""'
    )"
    GATEWAY_ACCESSIBLE="$(
        printf '%s\n' "$INTERNET_JSON" |
        "$JQ" -r '."gateway-accessible" // false'
    )"
    DNS_ACCESSIBLE="$(
        printf '%s\n' "$INTERNET_JSON" |
        "$JQ" -r '."dns-accessible" // false'
    )"
    INTERNET="$(
        printf '%s\n' "$INTERNET_JSON" |
        "$JQ" -r '.internet // false'
    )"
    RELIABLE="$(
        printf '%s\n' "$INTERNET_JSON" |
        "$JQ" -r '.reliable // false'
    )"
fi

CARRIER="unknown"

if [ "$DISCOVERY_USABLE" -eq 1 ] &&
   [ -n "$PHYSICAL_IF" ] &&
   [ -r "$SYS_CLASS_NET/$PHYSICAL_IF/carrier" ]; then
    CARRIER="$(cat "$SYS_CLASS_NET/$PHYSICAL_IF/carrier" 2>/dev/null || echo unknown)"
fi

PING_GW=1
PING_CF=1
PING_YA=1
NETWORK_OK=0

if [ "$DISCOVERY_USABLE" -eq 1 ] &&
   [ "$INTERNET_JSON_OK" -eq 1 ] &&
   [ "$CARRIER" != "0" ]; then

    if [ -n "$GATEWAY" ] && [ "$GATEWAY" != "null" ]; then
        "$PING_BIN" -c 1 -W 2 -I "$PATH_IF" "$GATEWAY" >/dev/null 2>&1
        PING_GW=$?
    fi

    "$PING_BIN" -c 1 -W 2 -I "$PATH_IF" 1.0.0.1 >/dev/null 2>&1
    PING_CF=$?

    "$PING_BIN" -c 1 -W 2 -I "$PATH_IF" 77.88.8.1 >/dev/null 2>&1
    PING_YA=$?
fi

if [ "$PING_CF" -eq 0 ] || [ "$PING_YA" -eq 0 ]; then
    NETWORK_OK=1
fi

LOGICAL_UPLINK=0
[ -n "$VIA_RCI_ID" ] && LOGICAL_UPLINK=1

CLASS="UNKNOWN"

if [ "$DISCOVERY_STATE" != "READY" ]; then
    case "$DISCOVERY_STATE" in
        NOT_FOUND)
            CLASS="DISCOVERY_NOT_FOUND"
            ;;
        REQUIRES_SELECTION)
            CLASS="DISCOVERY_REQUIRES_SELECTION"
            ;;
        STALE_MAPPING)
            CLASS="DISCOVERY_STALE_MAPPING"
            ;;
        INVALID_MAPPING)
            CLASS="DISCOVERY_INVALID_MAPPING"
            ;;
        *)
            CLASS="DISCOVERY_UNAVAILABLE"
            ;;
    esac
elif [ -z "$WAN_RCI_ID" ]; then
    CLASS="DISCOVERY_INVALID_RESULT"
elif [ -z "$WAN_IF" ]; then
    CLASS="MAPPING_UNRESOLVED"
elif [ "$INTERNET_JSON_OK" -ne 1 ]; then
    CLASS="UTILITY_DEGRADED"
elif [ "$CARRIER" = "0" ]; then
    CLASS="PHY_DOWN"
elif [ "$WAN_LINK" = "down" ] ||
     [ "$WAN_CONNECTED" = "no" ] ||
     [ "$WAN_STATE" = "down" ]; then
    if [ "$LOGICAL_UPLINK" -eq 1 ]; then
        CLASS="SESSION_FAILURE"
    else
        CLASS="LINK_FAILURE"
    fi
elif [ -z "$WAN_ADDRESS" ] || [ "$WAN_ADDRESS" = "null" ]; then
    if [ "$LOGICAL_UPLINK" -eq 1 ]; then
        CLASS="SESSION_FAILURE"
    else
        CLASS="ADDRESS_FAILURE"
    fi
elif [ "$WAN_DEFAULTGW" != "true" ]; then
    CLASS="ROUTE_FAILURE"
elif [ "$NETWORK_OK" -eq 1 ] && [ "$DNS_ACCESSIBLE" != "true" ]; then
    CLASS="DNS_ONLY_FAILURE"
elif [ "$INTERNET" = "true" ] && [ "$NETWORK_OK" -eq 1 ]; then
    CLASS="HEALTHY"
elif [ "$PING_GW" -ne 0 ] &&
     [ "$GATEWAY_ACCESSIBLE" != "true" ] &&
     [ "$PING_CF" -ne 0 ] &&
     [ "$PING_YA" -ne 0 ]; then
    CLASS="GATEWAY_FAILURE"
elif [ "$PING_CF" -ne 0 ] &&
     [ "$PING_YA" -ne 0 ] &&
     [ "$INTERNET" != "true" ]; then
    CLASS="INTERNET_FAILURE"
else
    CLASS="DEGRADED"
fi

case "$CLASS" in
    HEALTHY)
        STATUS="UP"
        FAIL_COUNT=0
        OK_COUNT=$((OK_COUNT + 1))
        ;;
    DNS_ONLY_FAILURE|DEGRADED)
        STATUS="DEGRADED"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        OK_COUNT=0
        ;;
    DISCOVERY_*|MAPPING_UNRESOLVED|UTILITY_DEGRADED)
        STATUS="UNKNOWN"
        FAIL_COUNT=0
        OK_COUNT=0
        ;;
    *)
        STATUS="DOWN"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        OK_COUNT=0
        ;;
esac

NOW_EPOCH="$(date +%s)"
NOW_TEXT="$(date '+%Y-%m-%d %H:%M:%S')"
TMP_STATE="$STATE.tmp.$$"

{
    echo "STATUS=$STATUS"
    echo "CLASS=$CLASS"
    echo "LAST_CHECK=$NOW_EPOCH"
    echo "FAIL_COUNT=$FAIL_COUNT"
    echo "OK_COUNT=$OK_COUNT"

    echo "DISCOVERY_STATE=$DISCOVERY_STATE"
    echo "DISCOVERY_RC=$DISCOVERY_RC"
    echo "DISCOVERY_SELECTION=${DISCOVERY_SELECTION:-none}"
    echo "DISCOVERY_MAPPING=${DISCOVERY_MAPPING:-none}"

    echo "RCI_ID=${WAN_RCI_ID:-none}"
    echo "LINUX_IF=${WAN_IF:-none}"
    echo "TYPE=${WAN_TYPE:-unknown}"

    echo "VIA_RCI_ID=${VIA_RCI_ID:-none}"
    echo "VIA_LINUX_IF=${VIA_IF:-none}"
    echo "VIA_MAPPING=${VIA_MAPPING:-none}"

    echo "PATH_IF=${PATH_IF:-none}"
    echo "PHYSICAL_IF=${PHYSICAL_IF:-none}"
    echo "CARRIER=$CARRIER"

    echo "LINK=${WAN_LINK:-unknown}"
    echo "CONNECTED=${WAN_CONNECTED:-unknown}"
    echo "RCI_STATE=${WAN_STATE:-unknown}"
    echo "ADDRESS=${WAN_ADDRESS:-none}"
    echo "DEFAULTGW=$WAN_DEFAULTGW"

    echo "GATEWAY=${GATEWAY:-none}"
    echo "GATEWAY_ACCESSIBLE=$GATEWAY_ACCESSIBLE"
    echo "DNS_ACCESSIBLE=$DNS_ACCESSIBLE"
    echo "INTERNET=$INTERNET"
    echo "RELIABLE=$RELIABLE"

    echo "PING_GW=$PING_GW"
    echo "PING_CF=$PING_CF"
    echo "PING_YA=$PING_YA"
    echo "NETWORK_OK=$NETWORK_OK"
} > "$TMP_STATE"

mv "$TMP_STATE" "$STATE"

if [ "$CLASS" != "$OLD_CLASS" ] || [ "$STATUS" != "$OLD_STATUS" ]; then
    echo "$NOW_TEXT|$OLD_STATUS/$OLD_CLASS->$STATUS/$CLASS|discovery=$DISCOVERY_STATE|rci=${WAN_RCI_ID:-none}|path_if=${PATH_IF:-none}|physical_if=${PHYSICAL_IF:-none}|carrier=$CARRIER|gw=$PING_GW|p1=$PING_CF|p2=$PING_YA" \
        >> "$LOG"
fi

echo "WAN_STATUS=$STATUS"
echo "WAN_CLASS=$CLASS"
echo "Discovery=$DISCOVERY_STATE Selection=${DISCOVERY_SELECTION:-none} RCI=${WAN_RCI_ID:-none}"
echo "PathIF=${PATH_IF:-none} PhysicalIF=${PHYSICAL_IF:-none} Carrier=$CARRIER"
echo "Gateway=$PING_GW Probe1=$PING_CF Probe2=$PING_YA Network=$NETWORK_OK"
echo "FailCount=$FAIL_COUNT OkCount=$OK_COUNT"

exit 0
