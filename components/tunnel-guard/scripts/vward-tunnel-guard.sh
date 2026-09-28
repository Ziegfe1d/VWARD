#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH


VWARD_PROFILE_LIB=${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}
[ -r "$VWARD_PROFILE_LIB" ] || { echo "VWARD device profile library is unavailable" >&2; exit 1; }
. "$VWARD_PROFILE_LIB"
vward_profile_load || exit 1
VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
[ -r "$VWARD_ADMISSION_LIB" ] || { echo "VWARD runtime admission library is unavailable" >&2; exit 1; }
. "$VWARD_ADMISSION_LIB"
vward_component_gate tunnel-guard
vward_admission_enter tunnel-guard || exit $?

MODE="AUTO"

HEALTH="${VWARD_TUNNEL_HEALTH_STATE:-/tmp/vward-tunnel-health/state}"

DIR="${VWARD_TUNNEL_GUARD_DIR:-/opt/var/lib/vward/tunnel-guard}"
STATE="$DIR/state"
LOG="${VWARD_TUNNEL_GUARD_LOG:-/opt/var/log/vward-tunnel-guard.log}"
LOCK="${VWARD_TUNNEL_GUARD_LOCK:-/tmp/vward-tunnel-guard-guard.lock}"

WAN_IF="$VWARD_WAN_DEVICE"
WG_IF="$VWARD_TUNNEL_DEVICE"

MAX_HEALTH_AGE=180
DOWN_CONFIRM=1
RECOVERY_INTERVAL=300
DISABLE_FILE="${VWARD_ETC:-/opt/etc/vward}/tunnel-guard.disabled"
# Several tunnels: when the one VWARD routes through dies, its routes go to the best other
# tunnel that answers (the quality samples); only with none alive do the lists go direct.
# When the first one answers again for three minutes, the routes come back to it.
FALLBACK_OFF="${VWARD_ETC:-/opt/etc/vward}/tunnel-fallback.disabled"
RETURN_OFF="${VWARD_ETC:-/opt/etc/vward}/tunnel-return.disabled"
FALLBACK="$DIR/fallback"
QUALITY=${VWARD_TUNNEL_QUALITY_BIN:-/opt/bin/vward-tunnel-quality.sh}
HELPER=${VWARD_CONSOLE_CONFIG_BIN:-/opt/bin/vward-console-config.sh}
RETURN_STREAK=3

mkdir -p "$DIR"

if ! mkdir "$LOCK" 2>/dev/null; then
    OLD=$(cat "$LOCK/pid" 2>/dev/null)

    if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
        exit 0
    fi

    rm -rf "${LOCK:?}"
    mkdir "$LOCK" || exit 1
fi

echo $$ > "$LOCK/pid"

cleanup()
{
    rm -rf "${LOCK:?}"
    vward_admission_leave 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM


probe_iface()
{
    IFACE="$1"
    URL="$2"

    "${VWARD_CURL_BIN:-curl}" -4 -k \
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


# fallback_pick: another tunnel answering in its last two samples, least loss, then fastest.
fallback_pick()
{
    [ ! -e "$FALLBACK_OFF" ] && [ -x "$QUALITY" ] && [ -x "$HELPER" ] || return 1
    "$QUALITY" summary 2>/dev/null |
        awk -F '\t' -v cur="$VWARD_TUNNEL_INTERFACE" '$1 != cur && $5 >= 2 && $3 < 100 {print $7 "\t" ($8 == "-" ? 99999 : $8) "\t" $1}' |
        sort -n -k1,1 -k2,2 | head -n 1 | cut -f3
}

# switch_to TUNNEL: VWARD's routes to TUNNEL, the Panel's own «Использовать для маршрутов».
switch_to()
{
    VWARD_TUNNEL_BY_GUARD=1 "$HELPER" tunnel "$1" 2>/dev/null | tail -n 1 | grep -q '^result=changed'
}

FALLBACK_FROM=""
FALLBACK_AT=0
FALLBACK_TO=""
if [ -f "$FALLBACK" ]; then
    while IFS='=' read -r K V; do
        case "$K" in
            FROM) FALLBACK_FROM=$V ;;
            AT) FALLBACK_AT=$V ;;
        esac
    done < "$FALLBACK"
fi
case "$FALLBACK_FROM" in *[!A-Za-z0-9_.-]*) FALLBACK_FROM="" ;; esac

DOWN_STREAK=0
FAILOPEN_ACTIVE=0
LAST_RECOVERY_TEST=0

OLD_MODE=""
OLD_ACTION=""

if [ -f "$STATE" ]; then
    while IFS='=' read -r K V; do
        case "$K" in
            MODE) OLD_MODE=$V ;;
            DOWN_STREAK) DOWN_STREAK=$V ;;
            FAILOPEN_ACTIVE) FAILOPEN_ACTIVE=$V ;;
            LAST_RECOVERY_TEST) LAST_RECOVERY_TEST=$V ;;
            LAST_ACTION) OLD_ACTION=$V ;;
        esac
    done < "$STATE"
fi
OLD_STREAK=$DOWN_STREAK OLD_ACTIVE=$FAILOPEN_ACTIVE OLD_RECOVERY=$LAST_RECOVERY_TEST

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
        if "${VWARD_NDMC:-ndmc}" -c "interface $VWARD_TUNNEL_INTERFACE up" >/dev/null 2>&1; then
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

    rm -rf "${LOCK:?}"
    exit 0
fi
WG_STATUS="UNKNOWN"
CONFIG_STATE="unknown"
AGE="NA"


if [ ! -f "$HEALTH" ]; then

    ACTION="NO_HEALTH_STATE"
    DOWN_STREAK=0

else

    WG_STATUS=""
    LAST_CHECK=""
    CONFIG_STATE=""

    while IFS='=' read -r K V; do
        case "$K" in
            STATUS) WG_STATUS=$V ;;
            LAST_CHECK) LAST_CHECK=$V ;;
            CONFIG_STATE) CONFIG_STATE=$V ;;
        esac
    done < "$HEALTH"

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
                elif [ -n "$FALLBACK_FROM" ] && [ "$FALLBACK_FROM" != "$VWARD_TUNNEL_INTERFACE" ] &&
                     [ "$MODE" = "AUTO" ] && [ ! -e "$RETURN_OFF" ] && [ -x "$QUALITY" ] &&
                     [ "$("$QUALITY" summary 2>/dev/null | awk -F '\t' -v n="$FALLBACK_FROM" '$1 == n {print $5}')" -ge "$RETURN_STREAK" ] 2>/dev/null; then
                    # The first tunnel answers again: the routes go back to it.
                    if switch_to "$FALLBACK_FROM"; then
                        ACTION="FALLBACK_RETURN"
                        FALLBACK_TO=$FALLBACK_FROM
                        FALLBACK_FROM=""
                    else
                        ACTION="FALLBACK_RETURN_ERROR"
                    fi
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

                            elif [ "$MODE" = "AUTO" ] && ALT=$(fallback_pick) && [ -n "$ALT" ] && switch_to "$ALT"; then
                                # Another tunnel answers: VWARD's routes go there, nothing goes direct.
                                [ -n "$FALLBACK_FROM" ] || FALLBACK_FROM=$VWARD_TUNNEL_INTERFACE
                                FALLBACK_AT=$NOW
                                FALLBACK_TO=$ALT
                                DOWN_STREAK=0
                                ACTION="FALLBACK_SWITCH"
                            elif [ "$MODE" = "AUTO" ]; then

                                if "${VWARD_NDMC:-ndmc}" -c "interface $VWARD_TUNNEL_INTERFACE down" \
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

                        if "${VWARD_NDMC:-ndmc}" -c "interface $VWARD_TUNNEL_INTERFACE up" \
                           >/dev/null 2>&1; then

                            sleep 4

                            if wg_ok; then

                                FAILOPEN_ACTIVE=0
                                DOWN_STREAK=0
                                ACTION="FAILOPEN_RECOVERED"

                                /opt/bin/vward-tunnel-health.sh \
                                    >/dev/null 2>&1 || true

                            else

                                "${VWARD_NDMC:-ndmc}" -c "interface $VWARD_TUNNEL_INTERFACE down" \
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


# The state survives reboots (fail-open must be undone), so it stays on USB,
# but it is rewritten only when something in it changes.
if [ "$MODE|$DOWN_STREAK|$FAILOPEN_ACTIVE|$LAST_RECOVERY_TEST|$ACTION" != \
     "$OLD_MODE|$OLD_STREAK|$OLD_ACTIVE|$OLD_RECOVERY|$OLD_ACTION" ] ||
   [ ! -f "$STATE" ]; then

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
fi


# Where the routes went when the first tunnel died, until they come back.
if [ -n "$FALLBACK_FROM" ]; then
    # Written only when it changes: the state directory is on the USB stick.
    if [ "$(cat "$FALLBACK" 2>/dev/null)" != "$(printf 'FROM=%s\nAT=%s' "$FALLBACK_FROM" "$FALLBACK_AT")" ]; then
        { echo "FROM=$FALLBACK_FROM"; echo "AT=$FALLBACK_AT"; } > "$FALLBACK.tmp.$$" && mv -f "$FALLBACK.tmp.$$" "$FALLBACK"
    fi
else
    rm -f "$FALLBACK"
fi

case "$ACTION" in
    KEEP_UP|STAY_DOWN|WOULD_STAY_DOWN)
        ;;
    *)
        echo "$NOW_TEXT|$ACTION|health=$WG_STATUS|config=$CONFIG_STATE|age=$AGE|down_streak=$DOWN_STREAK|active=$FAILOPEN_ACTIVE${FALLBACK_TO:+|to=$FALLBACK_TO}${FALLBACK_FROM:+|from=$FALLBACK_FROM}" \
            >> "$LOG"
        ;;
esac


echo "ACTION=$ACTION"
echo "Health=$WG_STATUS ConfigState=$CONFIG_STATE Age=${AGE}s"
echo "DownStreak=$DOWN_STREAK FailOpenActive=$FAILOPEN_ACTIVE"
echo "Mode=$MODE"

exit 0
