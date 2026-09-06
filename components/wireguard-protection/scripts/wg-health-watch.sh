#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

DIR="/opt/var/lib/wg-health"
STATE="$DIR/state"
LOG="/opt/var/log/wg-health.log"
LOCK="/tmp/wg-health-watch.lock"

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

    curl -4 -k \
      --noproxy '*' \
      --interface nwg1 \
      --connect-timeout 1 \
      --max-time 2 \
      -sS -o /dev/null \
      "$URL" >/dev/null 2>&1
}


# СНАЧАЛА реальный трафик.
P1=0
P2=0

probe "https://1.1.1.1/cdn-cgi/trace" && P1=1
probe "https://8.8.8.8/" && P2=1

NET_OK=0

if [ "$P1" -eq 1 ] || [ "$P2" -eq 1 ]; then
    NET_OK=1
fi


# ПОТОМ состояние Keenetic.
INFO=$(ndmc -c "show interface Wireguard1" 2>/dev/null)

CONFIG_STATE=$(echo "$INFO" | awk '/^[[:space:]]*state:/ {print $2; exit}')
LINK_STATE=$(echo "$INFO" | awk '/^[[:space:]]*link:/ {print $2; exit}')
ONLINE_STATE=$(echo "$INFO" | awk '/^[[:space:]]*online:/ {print $2; exit}')

IF_OK=0

echo "$INFO" | grep -q 'link: up' &&
echo "$INFO" | grep -q 'online: yes' &&
    IF_OK=1

HS=$(
    echo "$INFO" |
    awk '/last-handshake:/ {
        print $2
        exit
    }'
)

case "$HS" in
    ''|*[!0-9]*) HS=999999 ;;
esac

HS_OK=0
[ "$HS" -le 300 ] && HS_OK=1


# Реальный проход трафика — главный критерий.
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


NOW_EPOCH=$(date +%s)
NOW_TEXT=$(date '+%Y-%m-%d %H:%M:%S')
TMP="$STATE.tmp.$$"

{
    echo "STATUS=$STATUS"
    echo "LAST_CHECK=$NOW_EPOCH"
    echo "FAIL_COUNT=$FAIL_COUNT"
    echo "OK_COUNT=$OK_COUNT"
    echo "CONFIG_STATE=${CONFIG_STATE:-unknown}"
    echo "LINK_STATE=${LINK_STATE:-unknown}"
    echo "ONLINE_STATE=${ONLINE_STATE:-unknown}"
    echo "INTERFACE_OK=$IF_OK"
    echo "HANDSHAKE_AGE=$HS"
    echo "HANDSHAKE_OK=$HS_OK"
    echo "PROBE_1=$P1"
    echo "PROBE_2=$P2"
    echo "NETWORK_OK=$NET_OK"
} > "$TMP"

mv "$TMP" "$STATE"

if [ "$STATUS" != "$OLD_STATUS" ]; then
    echo "$NOW_TEXT|$OLD_STATUS->$STATUS|if=$IF_OK|hs=$HS|p1=$P1|p2=$P2" \
        >> "$LOG"
fi

echo "WG_STATUS=$STATUS"
echo "Interface=$IF_OK Network=$NET_OK HandshakeAge=$HS"
echo "Probe1=$P1 Probe2=$P2"
echo "FailCount=$FAIL_COUNT OkCount=$OK_COUNT"

exit 0
