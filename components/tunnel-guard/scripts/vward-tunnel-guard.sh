#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

MODE="AUTO"

HEALTH="/opt/var/lib/vward/tunnel-health/state"

DIR="/opt/var/lib/vward/tunnel-guard"
STATE="$DIR/state"
LOG="/opt/var/log/vward-tunnel-guard.log"
LOCK="/tmp/vward-tunnel-guard-guard.lock"

WAN_IF="eth3"
WG_IF="nwg1"

MAX_HEALTH_AGE=180
DOWN_CONFIRM=1
RECOVERY_INTERVAL=300
DISABLE_FILE="/opt/etc/vward/tunnel-guard.disabled"

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


probe_iface()
{
    IFACE="$1"
    URL="$2"

    curl -4 -k \
      --noproxy '*' \
      --interface "$IFACE" \
      --connect-timeout 1 \
      --max-time 2 \
      -sS -o /dev/null \
      "$URL" >/dev/null 2>&1
}


wan_ok()
{
    probe_iface "$WAN_IF" "https://1.1.1.1/cdn-cgi/trace" && return 0
    probe_iface "$WAN_IF" "https://8.8.8.8/" && return 0
    return 1
}


wg_ok()
{
    probe_iface "$WG_IF" "https://1.1.1.1/cdn-cgi/trace" && return 0
    probe_iface "$WG_IF" "https://8.8.8.8/" && return 0
    return 1
}


DOWN_STREAK=0
FAILOPEN_ACTIVE=0
LAST_RECOVERY_TEST=0

if [ -f "$STATE" ]; then
    DOWN_STREAK=$(awk -F= '$1=="DOWN_STREAK"{print $2}' "$STATE")
    FAILOPEN_ACTIVE=$(awk -F= '$1=="FAILOPEN_ACTIVE"{print $2}' "$STATE")
    LAST_RECOVERY_TEST=$(awk -F= '$1=="LAST_RECOVERY_TEST"{print $2}' "$STATE")
fi

case "$DOWN_STREAK" in
    ''|*[!0-9]*) DOWN_STREAK=0 ;;
esac

case "$FAILOPEN_ACTIVE" in
    1) ;;
    *) FAILOPEN_ACTIVE=0 ;;
esac

case "$LAST_RECOVERY_TEST" in
    ''|*[!0-9]*) LAST_RECOVERY_TEST=0 ;;
esac


NOW=$(date +%s)
NOW_TEXT=$(date '+%Y-%m-%d %H:%M:%S')

ACTION="NONE"

# Аварийный ручной запрет автоматики.
if [ -f "$DISABLE_FILE" ]; then

    RESTORED=0

    # Если WG был выключен именно Fail-Open автоматом,
    # при аварийном запрете автоматики сначала возвращаем его UP.
    if [ "$FAILOPEN_ACTIVE" -eq 1 ]; then
        if ndmc -c "interface nwg1 up" >/dev/null 2>&1; then
            RESTORED=1
            sleep 4
        fi
    fi

    FAILOPEN_ACTIVE=0
    DOWN_STREAK=0

    NOW=$(date +%s)
    NOW_TEXT=$(date '+%Y-%m-%d %H:%M:%S')
    TMP="$STATE.tmp.$$"

    {
        echo "MODE=$MODE"
        echo "DOWN_STREAK=0"
        echo "FAILOPEN_ACTIVE=0"
        echo "LAST_RECOVERY_TEST=0"
        echo "LAST_ACTION=DISABLED_BY_USER"
        echo "LAST_RUN=$NOW"
    } > "$TMP"

    mv "$TMP" "$STATE"

    echo "$NOW_TEXT|DISABLED_BY_USER|restored=$RESTORED" >> "$LOG"

    echo "ACTION=DISABLED_BY_USER"
    echo "RestoredWG=$RESTORED"
    echo "Mode=$MODE"

    rm -rf "$LOCK"
    exit 0
fi
WG_STATUS="UNKNOWN"
CONFIG_STATE="unknown"
AGE="NA"


if [ ! -f "$HEALTH" ]; then

    ACTION="NO_HEALTH_STATE"
    DOWN_STREAK=0

else

    WG_STATUS=$(awk -F= '$1=="STATUS"{print $2}' "$HEALTH")
    LAST_CHECK=$(awk -F= '$1=="LAST_CHECK"{print $2}' "$HEALTH")
    CONFIG_STATE=$(awk -F= '$1=="CONFIG_STATE"{print $2}' "$HEALTH")

    [ -n "$CONFIG_STATE" ] || CONFIG_STATE="unknown"

    case "$LAST_CHECK" in
        ''|*[!0-9]*) AGE=999999 ;;
        *) AGE=$((NOW - LAST_CHECK)) ;;
    esac


    if [ "$AGE" -gt "$MAX_HEALTH_AGE" ]; then

        ACTION="HEALTH_STALE"
        DOWN_STREAK=0

    else

        case "$WG_STATUS" in

            UP)
                DOWN_STREAK=0

                if [ "$FAILOPEN_ACTIVE" -eq 1 ]; then
                    if [ "$MODE" = "AUTO" ]; then
                        ACTION="FAILOPEN_RESTORED"
                    else
                        ACTION="WOULD_RESTORE"
                    fi

                    FAILOPEN_ACTIVE=0
                else
                    ACTION="KEEP_UP"
                fi
                ;;


            RECOVERING)
                DOWN_STREAK=0
                ACTION="WAIT_RECOVERING"
                ;;


            DEGRADED)
                DOWN_STREAK=0
                ACTION="WAIT_DEGRADED"
                ;;


            DOWN)

                # Если WG выключен не нашим автоматом — не вмешиваемся.
                if [ "$FAILOPEN_ACTIVE" -eq 0 ] &&
                   [ "$CONFIG_STATE" != "up" ]; then

                    DOWN_STREAK=0
                    ACTION="INTERFACE_DISABLED_EXTERNAL"


                elif [ "$FAILOPEN_ACTIVE" -eq 0 ]; then

                    # Сначала убеждаемся, что сам интернет жив.
                    if ! wan_ok; then

                        DOWN_STREAK=0
                        ACTION="HOLD_WAN_DOWN"

                    else

                        DOWN_STREAK=$((DOWN_STREAK + 1))

                        if [ "$DOWN_STREAK" -lt "$DOWN_CONFIRM" ]; then

                            ACTION="WAIT_DOWN_CONFIRM"

                        else

                            # Финальная защита от устаревшего health-state.
                            if wg_ok; then

                                DOWN_STREAK=0
                                ACTION="ABORT_WG_RECOVERED"

                            elif [ "$MODE" = "AUTO" ]; then

                                if ndmc -c "interface nwg1 down" \
                                   >/dev/null 2>&1; then

                                    FAILOPEN_ACTIVE=1
                                    LAST_RECOVERY_TEST=$NOW
                                    ACTION="FAILOPEN_DOWN"
                                else
                                    ACTION="FAILOPEN_DOWN_ERROR"
                                fi

                            else

                                FAILOPEN_ACTIVE=1
                                LAST_RECOVERY_TEST=$NOW
                                ACTION="WOULD_DOWN"
                            fi
                        fi
                    fi


                else

                    # Интерфейс ранее был выключен нашим fail-open.
                    SINCE=$((NOW - LAST_RECOVERY_TEST))

                    if [ "$SINCE" -lt "$RECOVERY_INTERVAL" ]; then

                        if [ "$MODE" = "AUTO" ]; then
                            ACTION="STAY_DOWN"
                        else
                            ACTION="WOULD_STAY_DOWN"
                        fi

                    elif ! wan_ok; then

                        LAST_RECOVERY_TEST=$NOW
                        ACTION="RECOVERY_HOLD_WAN_DOWN"

                    elif [ "$MODE" = "WATCH" ]; then

                        LAST_RECOVERY_TEST=$NOW
                        ACTION="WOULD_RECOVERY_TEST"

                    else

                        LAST_RECOVERY_TEST=$NOW

                        if ndmc -c "interface nwg1 up" \
                           >/dev/null 2>&1; then

                            sleep 4

                            if wg_ok; then

                                FAILOPEN_ACTIVE=0
                                DOWN_STREAK=0
                                ACTION="FAILOPEN_RECOVERED"

                                /opt/bin/vward-tunnel-health.sh \
                                    >/dev/null 2>&1 || true

                            else

                                ndmc -c "interface nwg1 down" \
                                    >/dev/null 2>&1

                                ACTION="RECOVERY_FAILED"
                            fi

                        else
                            ACTION="RECOVERY_UP_ERROR"
                        fi
                    fi
                fi
                ;;


            *)
                ACTION="UNKNOWN_HEALTH"
                DOWN_STREAK=0
                ;;
        esac
    fi
fi


TMP="$STATE.tmp.$$"

{
    echo "MODE=$MODE"
    echo "DOWN_STREAK=$DOWN_STREAK"
    echo "FAILOPEN_ACTIVE=$FAILOPEN_ACTIVE"
    echo "LAST_RECOVERY_TEST=$LAST_RECOVERY_TEST"
    echo "LAST_ACTION=$ACTION"
    echo "LAST_RUN=$NOW"
} > "$TMP"

mv "$TMP" "$STATE"


case "$ACTION" in
    KEEP_UP|STAY_DOWN|WOULD_STAY_DOWN)
        ;;
    *)
        echo "$NOW_TEXT|$ACTION|health=$WG_STATUS|config=$CONFIG_STATE|age=$AGE|down_streak=$DOWN_STREAK|active=$FAILOPEN_ACTIVE" \
            >> "$LOG"
        ;;
esac


echo "ACTION=$ACTION"
echo "Health=$WG_STATUS ConfigState=$CONFIG_STATE Age=${AGE}s"
echo "DownStreak=$DOWN_STREAK FailOpenActive=$FAILOPEN_ACTIVE"
echo "Mode=$MODE"

exit 0
