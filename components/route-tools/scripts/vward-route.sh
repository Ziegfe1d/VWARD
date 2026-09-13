#!/bin/sh
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

CONF="/opt/etc/vward/route-engine/services.conf"
STATE_DIR="/opt/var/lib/vward/route-tools"
LOG="/opt/var/log/vward-route.log"
LOCK="/tmp/vward-route.lock"
RUNCFG="/tmp/vward-route.running"

mkdir -p "$STATE_DIR"

# Не допускаем двух одновременных запусков.
if ! mkdir "$LOCK" 2>/dev/null; then
    echo "Adaptive-route already running"
    exit 0
fi

cleanup()
{
    rm -rf "$LOCK"
    rm -f "$RUNCFG"
}
trap cleanup EXIT INT TERM

log()
{
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"
}

# Один снимок конфигурации на весь цикл.
ndmc -c "show running-config" > "$RUNCFG" 2>/dev/null

is_in_vpn()
{
    GROUP="$1"
    HOST="$2"

    sed -n "/^object-group fqdn $GROUP/,/^!/p" "$RUNCFG" | \
        grep -Fq "include $HOST"
}

save_state()
{
    STATE="$1"
    FAILS="$2"
    OKS="$3"

    TMP="${STATE}.tmp.$$"

    {
        echo "FAILS=$FAILS"
        echo "OKS=$OKS"
    } > "$TMP"

    mv "$TMP" "$STATE"
}

check_service()
{
    NAME="$1"
    HOST="$2"
    GROUP="$3"
    WAN="$4"
    URL="$5"
    FAIL_LIMIT="$6"
    OK_LIMIT="$7"

    STATE="$STATE_DIR/$HOST.state"

    FAILS=0
    OKS=0

    [ -f "$STATE" ] && . "$STATE"

    if is_in_vpn "$GROUP" "$HOST"; then
        CURRENT="VPN"
    else
        CURRENT="ISP"
    fi

    IP=$(nslookup "$HOST" 9.9.9.10 2>/dev/null | \
        awk '/^Address [0-9]+:/ && $3 ~ /^[0-9]+\./ {ip=$3} END{print ip}')

    RESULT="FAIL"
    CODE="000"
    TIME="-"
    RC=1

    if [ "${FORCE_RESULT:-}" = "fail" ]; then
        RESULT="FAIL"

    elif [ "${FORCE_RESULT:-}" = "ok" ]; then
        RESULT="OK"

    elif [ -n "$IP" ]; then
        OUT=$(curl -4 \
            --interface "$WAN" \
            --resolve "$HOST:443:$IP" \
            --connect-timeout 5 \
            --max-time 8 \
            -A "Mozilla/5.0" \
            -sS -o /dev/null \
            -w '%{http_code} %{time_total}' \
            "$URL" 2>/dev/null)

        RC=$?
        CODE=$(echo "$OUT" | awk '{print $1}')
        TIME=$(echo "$OUT" | awk '{print $2}')

        if [ "$RC" = "0" ] &&
           [ -n "$CODE" ] &&
           [ "$CODE" != "000" ]; then
            RESULT="OK"
        fi
    fi

    if [ "$CURRENT" = "ISP" ]; then
        OKS=0
        if [ "$RESULT" = "OK" ]; then
            FAILS=0
        else
            FAILS=$((FAILS + 1))
        fi
    else
        FAILS=0
        if [ "$RESULT" = "OK" ]; then
            OKS=$((OKS + 1))
        else
            OKS=0
        fi
    fi

    ACTION="NONE"

    if [ "$CURRENT" = "ISP" ] && [ "$FAILS" -ge "$FAIL_LIMIT" ]; then

        if ndmc -c "object-group fqdn $GROUP include $HOST" >/dev/null 2>&1; then
            CURRENT="VPN"
            ACTION="ISP->VPN"
            FAILS=0
            OKS=0

            log "$NAME $HOST SWITCH ISP->VPN"

            nslookup "$HOST" 192.168.1.1 >/dev/null 2>&1
        else
            ACTION="SWITCH_FAILED"
            log "$NAME $HOST ERROR ISP->VPN"
        fi

    elif [ "$CURRENT" = "VPN" ] && [ "$OKS" -ge "$OK_LIMIT" ]; then

        if ndmc -c "no object-group fqdn $GROUP include $HOST" >/dev/null 2>&1; then
            CURRENT="ISP"
            ACTION="VPN->ISP"
            FAILS=0
            OKS=0

            log "$NAME $HOST SWITCH VPN->ISP"
        else
            ACTION="SWITCH_FAILED"
            log "$NAME $HOST ERROR VPN->ISP"
        fi
    fi

    save_state "$STATE" "$FAILS" "$OKS"

    echo "===== $NAME ====="
    echo "Host:       $HOST"
    echo "Direct IP:  ${IP:-N/A}"
    echo "ISP test:   $RESULT"
    echo "curl rc:    $RC"
    echo "HTTP:       $CODE"
    echo "Time:       ${TIME}s"
    echo "Fails:      $FAILS / $FAIL_LIMIT"
    echo "Success:    $OKS / $OK_LIMIT"
    echo "Route:      $CURRENT"
    echo "Action:     $ACTION"
    echo
}

while IFS='|' read -r NAME HOST GROUP WAN URL FAIL_LIMIT OK_LIMIT
do
    case "$NAME" in
        ""|\#*) continue ;;
    esac

    check_service \
        "$NAME" "$HOST" "$GROUP" "$WAN" "$URL" \
        "$FAIL_LIMIT" "$OK_LIMIT"

done < "$CONF"
