#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

DIR="${VWARD_WG_HEALTH_DIR:-/opt/var/lib/wg-health}"
STATE="$DIR/state"
RCI_CACHE="$DIR/interface-rci-cache"
LOG="${VWARD_WG_HEALTH_LOG:-/opt/var/log/wg-health.log}"
LOCK="${VWARD_WG_HEALTH_LOCK:-/tmp/wg-health-watch.lock}"

JQ="${VWARD_JQ:-/opt/bin/jq}"
DISCOVERY="${VWARD_DISCOVERY_BIN:-/opt/bin/vward-discovery.sh}"
CURL_BIN="${VWARD_CURL:-curl}"
NDMC_BIN="${VWARD_NDMC:-ndmc}"
IP_BIN="${VWARD_IP:-ip}"
SYS_CLASS_NET="${VWARD_SYS_CLASS_NET:-/sys/class/net}"

# Healthy WG only needs an NDM snapshot periodically.
# Any anomaly forces an immediate refresh.
RCI_REFRESH_INTERVAL=900

mkdir -p "$DIR"

if ! mkdir "$LOCK" 2>/dev/null; then
    OLD=$(cat "$LOCK/pid" 2>/dev/null)

    if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
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


# ------------------------------------------------------------
# DISCOVERY / ROLE SELECTION
# ------------------------------------------------------------

DISCOVERY_STATE="UNKNOWN"
DISCOVERY_SELECTION=""
DISCOVERY_MAPPING=""
WG_RCI_ID=""
WG_IF=""
DISCOVERY_USABLE=0

if [ -x "$DISCOVERY" ] && [ -x "$JQ" ]; then
    DISCOVERY_JSON="$($DISCOVERY tunnel-guard 2>/dev/null)"
    DISCOVERY_RC=$?

    if printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -e . >/dev/null 2>&1; then
        DISCOVERY_STATE="$(printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -r '.state // "UNKNOWN"')"
        DISCOVERY_SELECTION="$(printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -r '.selection // ""')"
        WG_RCI_ID="$(printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -r '.interface.rci_id // ""')"
        WG_IF="$(printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -r '.interface.linux_if // ""')"
        DISCOVERY_MAPPING="$(printf '%s\n' "$DISCOVERY_JSON" | "$JQ" -r '.interface.mapping // ""')"
    else
        DISCOVERY_STATE="INVALID_RESULT"
    fi
else
    DISCOVERY_RC=127
    DISCOVERY_STATE="UNAVAILABLE"
fi

if [ "$DISCOVERY_STATE" = "READY" ] &&
   [ -n "$WG_RCI_ID" ] &&
   [ -n "$WG_IF" ]; then
    DISCOVERY_USABLE=1
fi


OLD_STATUS="UNKNOWN"
FAIL_COUNT=0
OK_COUNT=0

if [ -f "$STATE" ]; then
    OLD_STATUS=$(awk -F= '$1=="STATUS"{print $2}' "$STATE")
    FAIL_COUNT=$(awk -F= '$1=="FAIL_COUNT"{print $2}' "$STATE")
    OK_COUNT=$(awk -F= '$1=="OK_COUNT"{print $2}' "$STATE")
fi

case "$FAIL_COUNT" in
    ''|*[!0-9]*) FAIL_COUNT=0 ;;
esac

case "$OK_COUNT" in
    ''|*[!0-9]*) OK_COUNT=0 ;;
esac


probe()
{
    URL="$1"

    [ "$DISCOVERY_USABLE" -eq 1 ] || return 1

    "$CURL_BIN" -4 -k \
      --noproxy '*' \
      --interface "$WG_IF" \
      --connect-timeout 1 \
      --max-time 2 \
      -sS -o /dev/null \
      "$URL" >/dev/null 2>&1
}


NOW_EPOCH=$(date +%s)


# ------------------------------------------------------------
# LOCAL INTERFACE STATE
# ------------------------------------------------------------

IF_EXISTS=0
CARRIER="unknown"
ADDR=""
FLAGS=""
LOCAL_IF_OK=0

if [ "$DISCOVERY_USABLE" -eq 1 ] &&
   [ -d "$SYS_CLASS_NET/$WG_IF" ]; then
    IF_EXISTS=1
    CARRIER=$(cat "$SYS_CLASS_NET/$WG_IF/carrier" 2>/dev/null || echo unknown)

    ADDR=$(
        "$IP_BIN" -4 addr show dev "$WG_IF" 2>/dev/null |
        awk '/inet / {print $2; exit}'
    )

    FLAGS=$("$IP_BIN" link show "$WG_IF" 2>/dev/null | head -1)

    if [ "$CARRIER" = "1" ] &&
       [ -n "$ADDR" ] &&
       echo "$FLAGS" | grep -q 'UP'; then
        LOCAL_IF_OK=1
    fi
fi


# ------------------------------------------------------------
# REAL WG TRAFFIC
# ------------------------------------------------------------

P1=0
P2=0

if [ "$DISCOVERY_USABLE" -eq 1 ]; then
    probe "https://1.1.1.1/cdn-cgi/trace" && P1=1
    probe "https://8.8.8.8/" && P2=1
fi

NET_OK=0

if [ "$P1" -eq 1 ] || [ "$P2" -eq 1 ]; then
    NET_OK=1
fi


# ------------------------------------------------------------
# CACHED KEENETIC STATE
# ------------------------------------------------------------

CONFIG_STATE="unknown"
LINK_STATE="unknown"
ONLINE_STATE="unknown"
HS=999999
LAST_RCI=0

if [ -f "$RCI_CACHE" ]; then
    CACHED_RCI_ID=$(awk -F= '$1=="RCI_ID"{print $2}' "$RCI_CACHE")

    # A cache created for a different tunnel must never be reused.
    if [ -n "$WG_RCI_ID" ] && [ "$CACHED_RCI_ID" = "$WG_RCI_ID" ]; then
        CONFIG_STATE=$(awk -F= '$1=="CONFIG_STATE"{print $2}' "$RCI_CACHE")
        LINK_STATE=$(awk -F= '$1=="LINK_STATE"{print $2}' "$RCI_CACHE")
        ONLINE_STATE=$(awk -F= '$1=="ONLINE_STATE"{print $2}' "$RCI_CACHE")
        HS=$(awk -F= '$1=="HANDSHAKE_AGE"{print $2}' "$RCI_CACHE")
        LAST_RCI=$(awk -F= '$1=="LAST_RCI"{print $2}' "$RCI_CACHE")
    fi
fi

[ -n "$CONFIG_STATE" ] || CONFIG_STATE="unknown"
[ -n "$LINK_STATE" ] || LINK_STATE="unknown"
[ -n "$ONLINE_STATE" ] || ONLINE_STATE="unknown"

case "$HS" in
    ''|*[!0-9]*) HS=999999 ;;
esac

case "$LAST_RCI" in
    ''|*[!0-9]*) LAST_RCI=0 ;;
esac

RCI_AGE=$((NOW_EPOCH - LAST_RCI))

case "$RCI_AGE" in
    -*)
        RCI_AGE=999999
        ;;
esac


# ------------------------------------------------------------
# RCI REFRESH POLICY
# ------------------------------------------------------------

NEED_RCI=0

if [ "$DISCOVERY_USABLE" -eq 1 ]; then
    [ "$LAST_RCI" -eq 0 ] && NEED_RCI=1
    [ "$RCI_AGE" -ge "$RCI_REFRESH_INTERVAL" ] && NEED_RCI=1

    # Any real/local anomaly gets an immediate authoritative snapshot.
    [ "$LOCAL_IF_OK" -ne 1 ] && NEED_RCI=1
    [ "$NET_OK" -ne 1 ] && NEED_RCI=1
    [ "$OLD_STATUS" != "UP" ] && NEED_RCI=1
fi

RCI_REFRESHED=0
RCI_OK=0

if [ "$NEED_RCI" -eq 1 ] && [ -n "$WG_RCI_ID" ]; then

    INFO=$("$NDMC_BIN" -c "show interface $WG_RCI_ID" 2>/dev/null)

    if [ -n "$INFO" ]; then

        CONFIG_STATE=$(
            echo "$INFO" |
            awk '/^[[:space:]]*state:/ {print $2; exit}'
        )

        LINK_STATE=$(
            echo "$INFO" |
            awk '/^[[:space:]]*link:/ {print $2; exit}'
        )

        ONLINE_STATE=$(
            echo "$INFO" |
            awk '/^[[:space:]]*online:/ {print $2; exit}'
        )

        HS=$(
            echo "$INFO" |
            awk '/last-handshake:/ {
                print $2
                exit
            }'
        )

        [ -n "$CONFIG_STATE" ] || CONFIG_STATE="unknown"
        [ -n "$LINK_STATE" ] || LINK_STATE="unknown"
        [ -n "$ONLINE_STATE" ] || ONLINE_STATE="unknown"

        case "$HS" in
            ''|*[!0-9]*) HS=999999 ;;
        esac

        CTMP="$RCI_CACHE.tmp.$$"

        {
            echo "RCI_ID=$WG_RCI_ID"
            echo "CONFIG_STATE=$CONFIG_STATE"
            echo "LINK_STATE=$LINK_STATE"
            echo "ONLINE_STATE=$ONLINE_STATE"
            echo "HANDSHAKE_AGE=$HS"
            echo "LAST_RCI=$NOW_EPOCH"
        } > "$CTMP" &&
        mv "$CTMP" "$RCI_CACHE"

        LAST_RCI=$NOW_EPOCH
        RCI_AGE=0
        RCI_REFRESHED=1
        RCI_OK=1
    fi
fi


# ------------------------------------------------------------
# HEALTH DECISION
# ------------------------------------------------------------

IF_OK="$LOCAL_IF_OK"

HS_OK=0
[ "$HS" -le 300 ] && HS_OK=1

if [ "$DISCOVERY_USABLE" -ne 1 ]; then
    STATUS="UNKNOWN"
    FAIL_COUNT=0
    OK_COUNT=0
else
    # Real traffic remains the primary criterion.
    GOOD=0

    if [ "$IF_OK" -eq 1 ] &&
       [ "$NET_OK" -eq 1 ]; then
        GOOD=1
    fi

    if [ "$GOOD" -eq 1 ]; then

        FAIL_COUNT=0
        OK_COUNT=$((OK_COUNT + 1))

        if [ "$OLD_STATUS" = "DOWN" ] ||
           [ "$OLD_STATUS" = "RECOVERING" ]; then

            if [ "$OK_COUNT" -ge 2 ]; then
                STATUS="UP"
            else
                STATUS="RECOVERING"
            fi

        else
            STATUS="UP"
        fi

    else

        OK_COUNT=0
        FAIL_COUNT=$((FAIL_COUNT + 1))

        if [ "$FAIL_COUNT" -ge 2 ]; then
            STATUS="DOWN"
        else
            STATUS="DEGRADED"
        fi
    fi
fi


NOW_TEXT=$(date '+%Y-%m-%d %H:%M:%S')
TMP_STATE="$STATE.tmp.$$"

{
    echo "STATUS=$STATUS"
    echo "LAST_CHECK=$NOW_EPOCH"
    echo "FAIL_COUNT=$FAIL_COUNT"
    echo "OK_COUNT=$OK_COUNT"

    echo "DISCOVERY_STATE=$DISCOVERY_STATE"
    echo "DISCOVERY_RC=$DISCOVERY_RC"
    echo "DISCOVERY_SELECTION=$DISCOVERY_SELECTION"
    echo "DISCOVERY_MAPPING=$DISCOVERY_MAPPING"
    echo "RCI_ID=${WG_RCI_ID:-none}"
    echo "LINUX_IF=${WG_IF:-none}"

    # Kept for wg-failopen compatibility.
    echo "CONFIG_STATE=${CONFIG_STATE:-unknown}"
    echo "LINK_STATE=${LINK_STATE:-unknown}"
    echo "ONLINE_STATE=${ONLINE_STATE:-unknown}"

    echo "INTERFACE_OK=$IF_OK"
    echo "LOCAL_IF_EXISTS=$IF_EXISTS"
    echo "LOCAL_CARRIER=$CARRIER"
    echo "LOCAL_ADDRESS=${ADDR:-none}"

    echo "HANDSHAKE_AGE=$HS"
    echo "HANDSHAKE_OK=$HS_OK"

    echo "PROBE_1=$P1"
    echo "PROBE_2=$P2"
    echo "NETWORK_OK=$NET_OK"

    echo "RCI_REFRESHED=$RCI_REFRESHED"
    echo "RCI_OK=$RCI_OK"
    echo "RCI_LAST=$LAST_RCI"
    echo "RCI_AGE=$RCI_AGE"
} > "$TMP_STATE"

mv "$TMP_STATE" "$STATE"


if [ "$STATUS" != "$OLD_STATUS" ]; then
    echo "$NOW_TEXT|$OLD_STATUS->$STATUS|discovery=$DISCOVERY_STATE|rci=${WG_RCI_ID:-none}|if=${WG_IF:-none}|if_ok=$IF_OK|hs=$HS|p1=$P1|p2=$P2|rci_refresh=$RCI_REFRESHED" \
        >> "$LOG"
fi


echo "WG_STATUS=$STATUS"
echo "Discovery=$DISCOVERY_STATE Selection=${DISCOVERY_SELECTION:-none} RCI=${WG_RCI_ID:-none} LinuxIF=${WG_IF:-none}"
echo "Interface=$IF_OK Network=$NET_OK HandshakeAge=$HS"
echo "Probe1=$P1 Probe2=$P2"
echo "FailCount=$FAIL_COUNT OkCount=$OK_COUNT"
echo "RCI_Refreshed=$RCI_REFRESHED RCI_Age=$RCI_AGE"

exit 0
