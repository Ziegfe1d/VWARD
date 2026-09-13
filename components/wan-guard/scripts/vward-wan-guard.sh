#!/opt/bin/sh

PATH="/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin"

VERSION="0.3-recovery"
MODE="recovery"

ETH="eth3"
BOOT_GRACE=180

RCI_ISP="http://127.0.0.1:79/rci/show/interface?name=ISP"
RCI_NET="http://127.0.0.1:79/rci/show/internet/status"

LOG="/opt/var/log/vward-wan-guard.log"
STATE="/tmp/vward-wan-guard.state"
LOCKDIR="/tmp/vward-wan-guard.lock.d"

CURL="/opt/bin/curl"
JQ="/opt/bin/jq"
PING="/opt/bin/ping"

LOCK_OWNED=0

now()
{
    date '+%Y-%m-%d %H:%M:%S%z'
}

lock_is_live()
{
    LPID="$(cat "$LOCKDIR/pid" 2>/dev/null)"

    case "$LPID" in
        ''|*[!0-9]*)
            return 1
            ;;
    esac

    [ -d "/proc/$LPID" ] || return 1

    grep -Fq "vward-wan-guard.sh" "/proc/$LPID/cmdline" 2>/dev/null
}

cleanup()
{
    if [ "$LOCK_OWNED" = "1" ]
    then
        OWNER="$(cat "$LOCKDIR/pid" 2>/dev/null)"

        if [ "$OWNER" = "$$" ]
        then
            rm -rf "$LOCKDIR" 2>/dev/null || true
        fi
    fi
}

acquire_lock()
{
    if mkdir "$LOCKDIR" 2>/dev/null
    then
        printf '%s\n' "$$" > "$LOCKDIR/pid"
        LOCK_OWNED=1
        return 0
    fi

    if lock_is_live
    then
        echo "CLASS=LOCKED"
        echo "ACTION=${ACTION:-NONE}"
        return 1
    fi

    sleep 1

    if lock_is_live
    then
        echo "CLASS=LOCKED"
        echo "ACTION=${ACTION:-NONE}"
        return 1
    fi

    rm -rf "$LOCKDIR" 2>/dev/null || {
        echo "CLASS=LOCK_ERROR"
        echo "ACTION=${ACTION:-NONE}"
        return 1
    }

    if mkdir "$LOCKDIR" 2>/dev/null
    then
        printf '%s\n' "$$" > "$LOCKDIR/pid"
        LOCK_OWNED=1
        echo "STALE_LOCK_RECOVERED=YES"
        return 0
    fi

    echo "CLASS=LOCKED"
    echo "ACTION=${ACTION:-NONE}"
    return 1
}

emit_state()
{
    CLASS="$1"
    DETAIL="$2"
    wan_recover "$CLASS"

    PREV=""

    if [ -f "$STATE" ]
    then
        PREV="$(cat "$STATE" 2>/dev/null)"
    fi

    echo "VERSION=$VERSION"
    echo "MODE=$MODE"
    echo "CLASS=$CLASS"
    echo "$DETAIL"
    echo "ACTION=${ACTION:-NONE}"

    if [ "$PREV" != "$CLASS" ]
    then
        printf '%s class=%s previous=%s %s\n' \
            "$(now)" \
            "$CLASS" \
            "${PREV:-NONE}" \
            "$DETAIL" >> "$LOG"

        printf '%s\n' "$CLASS" > "$STATE"
    fi
}

# WAN_GUARDIAN_RECOVERY_V03

REC_DIR="/tmp/vward-wan-guard-recovery"
REC_LOG="/opt/var/log/vward-wan-guard-recovery.log"

CONFIRM_FAILURES=3

RENEW_COOLDOWN=600
BOUNCE_COOLDOWN=1800

MAX_RENEW_HOUR=3
MAX_BOUNCE_HOUR=2
MAX_BOUNCE_DAY=6

wg_num()
{
    WR_VALUE="$(cat "$1" 2>/dev/null)"

    case "$WR_VALUE" in
        ''|*[!0-9]*)
            echo "$2"
            ;;
        *)
            echo "$WR_VALUE"
            ;;
    esac
}

wg_reset_fail()
{
    rm -f "$REC_DIR/fail_class"
    echo 0 > "$REC_DIR/fail_count"
}

wg_reset_all()
{
    wg_reset_fail
    echo 0 > "$REC_DIR/stage"
}

wg_bucket_count()
{
    WR_PREFIX="$1"
    WR_KEY="$2"

    WR_OLDKEY="$(cat "$REC_DIR/${WR_PREFIX}_key" 2>/dev/null)"
    WR_COUNT="$(wg_num "$REC_DIR/${WR_PREFIX}_count" 0)"

    if [ "$WR_OLDKEY" != "$WR_KEY" ]; then
        WR_COUNT=0
    fi

    echo "$WR_COUNT"
}

wg_bucket_inc()
{
    WR_PREFIX="$1"
    WR_KEY="$2"

    WR_OLDKEY="$(cat "$REC_DIR/${WR_PREFIX}_key" 2>/dev/null)"
    WR_COUNT="$(wg_num "$REC_DIR/${WR_PREFIX}_count" 0)"

    if [ "$WR_OLDKEY" != "$WR_KEY" ]; then
        WR_COUNT=0
    fi

    WR_COUNT=$((WR_COUNT + 1))

    echo "$WR_KEY" > "$REC_DIR/${WR_PREFIX}_key"
    echo "$WR_COUNT" > "$REC_DIR/${WR_PREFIX}_count"
}

wan_recover()
{
    ACTION="NONE"

    WR_CLASS="$1"

    mkdir -p "$REC_DIR"

    WR_FAIL_COUNT="$(wg_num "$REC_DIR/fail_count" 0)"
    WR_STAGE="$(wg_num "$REC_DIR/stage" 0)"
    WR_PREV_CLASS="$(cat "$REC_DIR/fail_class" 2>/dev/null)"

    case "$WR_CLASS" in

        HEALTHY|BOOT_GRACE|UTILITY_DEGRADED|DNS_ONLY_FAILURE|VPN_ONLY_FAILURE|UNKNOWN)
            wg_reset_all
            WR_FAIL_COUNT=0
            WR_STAGE=0

            DETAIL="$DETAIL recovery_count=0 recovery_stage=0"
            return
            ;;

        PHY_DOWN|DHCP_FAILURE|GATEWAY_FAILURE|INTERNET_FAILURE)
            ;;

        *)
            wg_reset_all
            WR_FAIL_COUNT=0
            WR_STAGE=0

            DETAIL="$DETAIL recovery_count=0 recovery_stage=0"
            return
            ;;
    esac

    if [ "$WR_PREV_CLASS" = "$WR_CLASS" ]; then
        WR_FAIL_COUNT=$((WR_FAIL_COUNT + 1))
    else
        WR_FAIL_COUNT=1
        echo "$WR_CLASS" > "$REC_DIR/fail_class"
    fi

    echo "$WR_FAIL_COUNT" > "$REC_DIR/fail_count"

    if [ "$WR_FAIL_COUNT" -lt "$CONFIRM_FAILURES" ]; then
        ACTION="WAIT_CONFIRM_${WR_FAIL_COUNT}_OF_${CONFIRM_FAILURES}"

        DETAIL="$DETAIL recovery_count=$WR_FAIL_COUNT recovery_stage=$WR_STAGE"
        return
    fi

    WR_NOW="$(date '+%s')"

    if [ "$WR_CLASS" = "PHY_DOWN" ] || [ "$WR_STAGE" -ge 1 ]; then

        WR_LAST_BOUNCE="$(wg_num "$REC_DIR/last_bounce" 0)"

        if [ "$WR_LAST_BOUNCE" -gt 0 ]; then
            WR_AGE=$((WR_NOW - WR_LAST_BOUNCE))

            if [ "$WR_AGE" -ge 0 ] && [ "$WR_AGE" -lt "$BOUNCE_COOLDOWN" ]; then
                ACTION="BOUNCE_COOLDOWN"

                DETAIL="$DETAIL recovery_count=$WR_FAIL_COUNT recovery_stage=$WR_STAGE"
                return
            fi
        fi

        WR_HOUR="$(date '+%Y%m%d%H')"
        WR_DAY="$(date '+%Y%m%d')"

        WR_BOUNCE_HOUR="$(wg_bucket_count bounce_hour "$WR_HOUR")"
        WR_BOUNCE_DAY="$(wg_bucket_count bounce_day "$WR_DAY")"

        if [ "$WR_BOUNCE_HOUR" -ge "$MAX_BOUNCE_HOUR" ] || \
           [ "$WR_BOUNCE_DAY" -ge "$MAX_BOUNCE_DAY" ]; then

            ACTION="BOUNCE_RATE_LIMIT"

            DETAIL="$DETAIL recovery_count=$WR_FAIL_COUNT recovery_stage=$WR_STAGE"
            return
        fi

        ACTION="WAN_BOUNCE"

        LD_LIBRARY_PATH= /bin/ndmc -c "interface ISP down" \
            >/tmp/vward-wan-guard.ndmc.down 2>&1
        WR_DOWN_RC=$?

        sleep 5

        WR_UP_RC=1
        WR_UP_TRIES=0

        while [ "$WR_UP_TRIES" -lt 3 ]
        do
            WR_UP_TRIES=$((WR_UP_TRIES + 1))

            LD_LIBRARY_PATH= /bin/ndmc -c "interface ISP up" \
                >/tmp/vward-wan-guard.ndmc.up 2>&1
            WR_UP_RC=$?

            [ "$WR_UP_RC" -eq 0 ] && break

            sleep 2
        done

        echo "$WR_NOW" > "$REC_DIR/last_bounce"

        wg_bucket_inc bounce_hour "$WR_HOUR"
        wg_bucket_inc bounce_day "$WR_DAY"

        echo 2 > "$REC_DIR/stage"

        WR_STAGE=2
        WR_FAIL_COUNT=0

        wg_reset_fail

        printf '%s action=WAN_BOUNCE class=%s down_rc=%s up_rc=%s up_tries=%s\n' \
            "$(date '+%Y-%m-%d %H:%M:%S%z')" \
            "$WR_CLASS" \
            "$WR_DOWN_RC" \
            "$WR_UP_RC" \
            "$WR_UP_TRIES" >> "$REC_LOG"

        if [ "$WR_UP_RC" -ne 0 ]; then
            ACTION="WAN_BOUNCE_UP_FAILED"
        fi

        DETAIL="$DETAIL recovery_count=0 recovery_stage=2 down_rc=$WR_DOWN_RC up_rc=$WR_UP_RC"
        return
    fi

    WR_LAST_RENEW="$(wg_num "$REC_DIR/last_renew" 0)"

    if [ "$WR_LAST_RENEW" -gt 0 ]; then
        WR_AGE=$((WR_NOW - WR_LAST_RENEW))

        if [ "$WR_AGE" -ge 0 ] && [ "$WR_AGE" -lt "$RENEW_COOLDOWN" ]; then
            ACTION="RENEW_COOLDOWN"

            DETAIL="$DETAIL recovery_count=$WR_FAIL_COUNT recovery_stage=$WR_STAGE"
            return
        fi
    fi

    WR_HOUR="$(date '+%Y%m%d%H')"
    WR_RENEW_HOUR="$(wg_bucket_count renew_hour "$WR_HOUR")"

    if [ "$WR_RENEW_HOUR" -ge "$MAX_RENEW_HOUR" ]; then
        ACTION="RENEW_RATE_LIMIT"

        DETAIL="$DETAIL recovery_count=$WR_FAIL_COUNT recovery_stage=$WR_STAGE"
        return
    fi

    ACTION="DHCP_RENEW"

    LD_LIBRARY_PATH= /bin/ndmc -c "interface ISP ip dhcp client renew" \
        >/tmp/vward-wan-guard.ndmc.renew 2>&1
    WR_RENEW_RC=$?

    echo "$WR_NOW" > "$REC_DIR/last_renew"

    wg_bucket_inc renew_hour "$WR_HOUR"

    echo 1 > "$REC_DIR/stage"

    WR_STAGE=1
    WR_FAIL_COUNT=0

    wg_reset_fail

    printf '%s action=DHCP_RENEW class=%s rc=%s\n' \
        "$(date '+%Y-%m-%d %H:%M:%S%z')" \
        "$WR_CLASS" \
        "$WR_RENEW_RC" >> "$REC_LOG"

    DETAIL="$DETAIL recovery_count=0 recovery_stage=1 renew_rc=$WR_RENEW_RC"
}

if ! acquire_lock
then
    exit 0
fi

trap cleanup 0
trap 'cleanup; exit 1' 1 2 15

UPTIME="$(awk '{print int($1)}' /proc/uptime 2>/dev/null)"

case "$UPTIME" in
    ''|*[!0-9]*)
        emit_state \
            "UTILITY_DEGRADED" \
            "reason=uptime_unavailable"
        exit 0
        ;;
esac

if [ "$UPTIME" -lt "$BOOT_GRACE" ]
then
    emit_state \
        "BOOT_GRACE" \
        "uptime=${UPTIME}s grace=${BOOT_GRACE}s"
    exit 0
fi

ISP_JSON="$(
    "$CURL" -fsS \
        --connect-timeout 2 \
        --max-time 3 \
        "$RCI_ISP" 2>/dev/null
)"

NET_JSON="$(
    "$CURL" -fsS \
        --connect-timeout 2 \
        --max-time 3 \
        "$RCI_NET" 2>/dev/null
)"

if [ -z "$ISP_JSON" ] || \
   ! printf '%s' "$ISP_JSON" | "$JQ" -e . >/dev/null 2>&1
then
    emit_state \
        "UTILITY_DEGRADED" \
        "reason=isp_rci_unavailable"
    exit 0
fi

if [ -z "$NET_JSON" ] || \
   ! printf '%s' "$NET_JSON" | "$JQ" -e . >/dev/null 2>&1
then
    emit_state \
        "UTILITY_DEGRADED" \
        "reason=internet_rci_unavailable"
    exit 0
fi

LINK="$(printf '%s' "$ISP_JSON" | "$JQ" -r '.link // "unknown"')"
PORT_LINK="$(printf '%s' "$ISP_JSON" | "$JQ" -r '.port.link // "unknown"')"
CONNECTED="$(printf '%s' "$ISP_JSON" | "$JQ" -r '.connected // "unknown"')"
STATE_RCI="$(printf '%s' "$ISP_JSON" | "$JQ" -r '.state // "unknown"')"
ADDRESS="$(printf '%s' "$ISP_JSON" | "$JQ" -r '.address // ""')"
DEFAULTGW="$(printf '%s' "$ISP_JSON" | "$JQ" -r '.defaultgw // false')"
LAYER_IPV4="$(printf '%s' "$ISP_JSON" | "$JQ" -r '.summary.layer.ipv4 // "unknown"')"

GW="$(printf '%s' "$NET_JSON" | "$JQ" -r '.gateway.address // ""')"
GW_ACCESSIBLE="$(printf '%s' "$NET_JSON" | "$JQ" -r '."gateway-accessible" // false')"
DNS_ACCESSIBLE="$(printf '%s' "$NET_JSON" | "$JQ" -r '."dns-accessible" // false')"
INTERNET="$(printf '%s' "$NET_JSON" | "$JQ" -r '.internet // false')"
RELIABLE="$(printf '%s' "$NET_JSON" | "$JQ" -r '.reliable // false')"

CARRIER="$(cat "/sys/class/net/$ETH/carrier" 2>/dev/null || echo unknown)"
OPERSTATE="$(cat "/sys/class/net/$ETH/operstate" 2>/dev/null || echo unknown)"

PING_GW=1
PING_CF=1
PING_YA=1

if [ -n "$GW" ] && [ "$GW" != "null" ]
then
    "$PING" -c 1 -W 2 -I "$ETH" "$GW" >/dev/null 2>&1
    PING_GW=$?
fi

"$PING" -c 1 -W 2 -I "$ETH" 1.0.0.1 >/dev/null 2>&1
PING_CF=$?

"$PING" -c 1 -W 2 -I "$ETH" 77.88.8.1 >/dev/null 2>&1
PING_YA=$?

CLASS="UNKNOWN"

if [ "$CARRIER" != "1" ] || \
   [ "$LINK" != "up" ] || \
   [ "$PORT_LINK" != "up" ]
then
    CLASS="PHY_DOWN"

elif [ -z "$ADDRESS" ] || \
     [ "$ADDRESS" = "null" ] || \
     [ "$DEFAULTGW" != "true" ] || \
     [ "$LAYER_IPV4" != "running" ]
then
    CLASS="DHCP_FAILURE"

elif { [ "$PING_CF" -eq 0 ] || [ "$PING_YA" -eq 0 ]; } && \
     [ "$DNS_ACCESSIBLE" != "true" ]
then
    CLASS="DNS_ONLY_FAILURE"

elif [ "$INTERNET" = "true" ] && \
     { [ "$PING_CF" -eq 0 ] || \
       [ "$PING_YA" -eq 0 ] || \
       [ "$GW_ACCESSIBLE" = "true" ]; }
then
    CLASS="HEALTHY"

elif [ "$PING_GW" -ne 0 ] && \
     [ "$GW_ACCESSIBLE" != "true" ] && \
     [ "$PING_CF" -ne 0 ] && \
     [ "$PING_YA" -ne 0 ]
then
    CLASS="GATEWAY_FAILURE"

elif [ "$PING_CF" -ne 0 ] && \
     [ "$PING_YA" -ne 0 ] && \
     [ "$INTERNET" != "true" ]
then
    CLASS="INTERNET_FAILURE"
fi

DETAIL="carrier=$CARRIER operstate=$OPERSTATE link=$LINK port_link=$PORT_LINK connected=$CONNECTED state=$STATE_RCI address=${ADDRESS:-none} defaultgw=$DEFAULTGW gateway=${GW:-none} gateway_accessible=$GW_ACCESSIBLE dns_accessible=$DNS_ACCESSIBLE internet=$INTERNET reliable=$RELIABLE ping_gw=$PING_GW ping_cf=$PING_CF ping_ya=$PING_YA"

emit_state "$CLASS" "$DETAIL"

exit 0
