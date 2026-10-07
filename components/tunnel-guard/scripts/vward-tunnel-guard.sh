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
# Keenetic's own lists with their own tunnel (and services) move the same way, one by one:
# GROUP<TAB>FIRST TUNNEL<TAB>NOW ON<TAB>SINCE per list moved.
LISTS_FALLBACK="$DIR/lists-fallback"
ADAPTIVE_GROUP=AdaptiveAuto
LW=""

# engine_kick NAME: a tunnel of VWARD's own engines (Xray, AmneziaWG) does not carry anything
# after Keenetic switched its interface off and on (seen on Viva 2026-10-04 with Xray); its
# program starts afresh on the adapter. Other tunnels: nothing.
engine_of()
{
    for ek in "${VWARD_VLESS_ETC:-/opt/etc/vward/vless-engine}|${VWARD_VLESS_ENGINE_BIN:-/opt/bin/vward-vless-engine.sh}" \
              "${VWARD_AWG_ETC:-/opt/etc/vward/awg-engine}|${VWARD_AWG_ENGINE_BIN:-/opt/bin/vward-awg-engine.sh}"; do
        ek_bin=${ek#*|}
        [ -x "$ek_bin" ] && awk -F '\t' -v n="$1" '$2 == n {f = 1} END {exit !f}' "${ek%%|*}/tunnels.tsv" 2>/dev/null || continue
        echo "$ek_bin"; return 0
    done
    return 1
}

# The network agent decides, the components agent restarts (it alone touches programs): the
# request waits for it, at most 30 s.
engine_kick()
{
    engine_of "$1" >/dev/null || return 0
    vward_agent_ask "engine-${2:-restart}:$1" "${VWARD_AGENT_WAIT:-30}" || :
}

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
    [ -z "${LW:-}" ] || rm -rf "${LW:?}"
    rm -rf "${LOCK:?}"
    vward_admission_leave 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM


# A page through a tunnel: through VLESS or AmneziaWG's engine a TLS answer from 1.1.1.1 takes
# seconds on this router; 2 s (as before) called a working tunnel dead and the guard switched it
# off (a router, 2026-10-07). The engine's own check waits 8 s.
probe_iface()
{
    IFACE="$1"
    URL="$2"

    "${VWARD_CURL_BIN:-curl}" -4 -k \
      --noproxy '*' \
      --interface "$IFACE" \
      --connect-timeout "${VWARD_PROBE_CONNECT:-4}" \
      --max-time "${VWARD_PROBE_MAX:-8}" \
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

# lists_best EXCLUDE: the best tunnel answering in its last two samples, EXCLUDE aside.
lists_best()
{
    awk -F '\t' -v x="$1" '$1 != x && $5 >= 2 && $3 < 100 {print $7 "\t" ($8 == "-" ? 99999 : $8) "\t" $1}' "$LW/q" |
        sort -n -k1,1 -k2,2 | head -n 1 | cut -f3
}

# lists_move GROUP TUNNEL: the Panel's own «Маршрут списка», verified by the helper.
lists_move()
{
    VWARD_TUNNEL_BY_GUARD=1 "$HELPER" domain-list "$1" "$2" </dev/null 2>/dev/null | tail -n 1 | grep -q '^result=changed'
}

# A list routed to a tunnel that failed its last two samples goes to the best tunnel that
# answers; back when its tunnel answers three minutes in a row. VWARD's own group and
# AdaptiveAuto follow VWARD's tunnel (switch_to); with no tunnel answering the list stays
# (Keenetic's «auto» route takes it past the dead tunnel).
lists_fallback()
{
    [ "$MODE" = AUTO ] && [ -x "$QUALITY" ] && [ -x "$HELPER" ] || return 0
    # One tunnel and nothing moved before: nowhere to move a list, and no process spent
    # finding it out (the quality check writes the tunnels it pinged, one per line).
    if [ -r "$QUALITY_MAP" ] && [ ! -s "$LISTS_FALLBACK" ]; then
        lf_n=0
        while read -r _; do lf_n=$((lf_n + 1)); done < "$QUALITY_MAP"
        [ "$lf_n" -ge 2 ] || return 0
    fi
    LW=$(mktemp -d /tmp/vward-guard-lists.XXXXXX 2>/dev/null) || { LW=""; return 0; }
    "$QUALITY" summary > "$LW/q" 2>/dev/null
    # Nothing moved and no tunnel failing: the router's configuration is not read at all.
    if [ ! -s "$LISTS_FALLBACK" ]; then
        [ ! -e "$FALLBACK_OFF" ] && awk -F '\t' '$11 >= 2 {f = 1} END {exit f ? 0 : 1}' "$LW/q" || return 0
    fi
    "${VWARD_NDMC:-ndmc}" -c "show running-config" 2>/dev/null | tr -d '\r' > "$LW/rc"
    grep -q '^dns-proxy' "$LW/rc" || return 0
    awk '/^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1)} /^!/ {ctx = 0}
        ctx && $1 == "route" && $2 == "object-group" {print $3 "\t" $4}' "$LW/rc" > "$LW/routes"
    lf_tab=$(printf '\t')
    : > "$LW/keep"
    # 1. Lists moved before: back to their tunnel when it answers; forgotten when someone
    #    routed them elsewhere since.
    if [ -s "$LISTS_FALLBACK" ]; then
        while IFS="$lf_tab" read -r g from to at; do
            [ -n "$g" ] && [ -n "$from" ] && [ -n "$to" ] || continue
            case "$g$from$to$at" in *[!A-Za-z0-9_.-]*) continue ;; esac
            grep -Fqx "$g$lf_tab$to" "$LW/routes" || continue
            # Its first tunnel was deleted: nowhere to come back to, the move is forgotten.
            if [ -s "$LW/rc" ] && ! grep -qx "interface $from" "$LW/rc"; then
                echo "$NOW_TEXT|LIST_FALLBACK_FORGOTTEN|list=$g|on=$to|gone=$from" >> "$LOG"
                continue
            fi
            ok=$(awk -F '\t' -v n="$from" '$1 == n {print $5}' "$LW/q")
            if [ ! -e "$RETURN_OFF" ] && [ "${ok:-0}" -ge "$RETURN_STREAK" ] 2>/dev/null && lists_move "$g" "$from"; then
                LISTS_BACK=$((LISTS_BACK + 1))
                echo "$NOW_TEXT|LIST_RETURN|list=$g|to=$from|from=$to" >> "$LOG"
                continue
            fi
            printf '%s\t%s\t%s\t%s\n' "$g" "$from" "$to" "$at" >> "$LW/keep"
        done < "$LISTS_FALLBACK"
    fi
    # 2. Lists on a tunnel that stopped answering.
    if [ ! -e "$FALLBACK_OFF" ]; then
        while IFS="$lf_tab" read -r g t; do
            case "$g" in ''|"$ADAPTIVE_GROUP"|*[!A-Za-z0-9_.-]*) continue ;; esac
            [ "$g" != "${VWARD_POLICY_GROUP:-}" ] || continue
            fails=$(awk -F '\t' -v n="$t" '$1 == n {print $11}' "$LW/q")
            [ "${fails:-0}" -ge 2 ] 2>/dev/null || continue
            alt=$(lists_best "$t")
            [ -n "$alt" ] && lists_move "$g" "$alt" || continue
            LISTS_MOVED=$((LISTS_MOVED + 1))
            echo "$NOW_TEXT|LIST_FALLBACK|list=$g|to=$alt|from=$t" >> "$LOG"
            # A list moved on again keeps its first tunnel; one back on it is forgotten.
            from=$(awk -F '\t' -v g="$g" '$1 == g {print $2; exit}' "$LW/keep")
            awk -F '\t' -v g="$g" '$1 != g' "$LW/keep" > "$LW/k2" && mv -f "$LW/k2" "$LW/keep"
            [ "${from:-$t}" = "$alt" ] || printf '%s\t%s\t%s\t%s\n' "$g" "${from:-$t}" "$alt" "$NOW" >> "$LW/keep"
        done < "$LW/routes"
    fi
    # Written only when it changes: the state directory is on the USB stick.
    if [ ! -s "$LW/keep" ]; then
        rm -f "$LISTS_FALLBACK"
    elif [ "$(cat "$LW/keep")" != "$(cat "$LISTS_FALLBACK" 2>/dev/null)" ]; then
        cp "$LW/keep" "$LISTS_FALLBACK.tmp.$$" && mv -f "$LISTS_FALLBACK.tmp.$$" "$LISTS_FALLBACK"
    fi
    return 0
}

LISTS_MOVED=0
LISTS_BACK=0
QUALITY_MAP="${VWARD_TUNNEL_QUALITY_DIR:-/tmp/vward-tunnel-quality}/map"

# «Выбирать лучший туннель» (off by default: a switch breaks open connections): VWARD's routes
# go to a tunnel clearly better by the criterion (30%), after it stays better 15 minutes,
# at most once in 30 minutes. The state is in RAM: after a reboot it starts over.
AUTO_CONF="${VWARD_ETC:-/opt/etc/vward}/tunnel-auto.conf"
QSTATE=${VWARD_TUNNEL_AUTO_STATE:-/tmp/vward-tunnel-auto}
AUTO_BETTER=30
AUTO_HOLD=900
AUTO_GAP=1800
QUALITY_FROM=""

auto_conf()
{
    v=$(awk -F= -v k="$1" '$1 == k {print substr($0, index($0, "=") + 1); exit}' "$AUTO_CONF" 2>/dev/null)
    printf '%s\n' "${v:-$2}"
}

# quality_pick CRITERION: the tunnel clearly better than the current one, or nothing. Only
# tunnels with 15 samples and answering now. Score, lower is better:
#   ping      average + 2 × jitter + 20 × loss%
#   speed     10000 / Mbit/s + 20 × loss% (only tunnels with a measured speed)
#   balanced  (average + jitter + 20 × loss%) / (1 + Mbit/s / 50), the speed where measured
quality_pick()
{
    "$QUALITY" summary 2>/dev/null | awk -F '\t' -v cur="$VWARD_TUNNEL_INTERFACE" -v c="$1" -v pct="$AUTO_BETTER" '
        $6 >= 15 && $5 >= 2 && $3 < 100 && $8 != "-" {
            j = ($9 == "-" ? 0 : $9); sp = ($12 == "" || $12 == "-" ? 0 : $12 + 0)
            if (c == "ping") s = $8 + 2 * j + 20 * $7
            else if (c == "speed") { if (sp <= 0) next; s = 10000 / sp + 20 * $7 }
            else { s = $8 + j + 20 * $7; if (sp > 0) s = s / (1 + sp / 50) }
            if ($1 == cur) { cs = s; have = 1 }
            else if (best == "" || s < bs) { best = $1; bs = s }
        }
        END { if (best != "" && have && bs <= cs * (100 - pct) / 100) print best }'
}

quality_step()
{
    if [ "$MODE" != AUTO ] || [ "$(auto_conf ENABLED 0)" != 1 ] || [ ! -x "$QUALITY" ] || [ ! -x "$HELPER" ]; then
        rm -f "$QSTATE"
        return 0
    fi
    Q_BETTER="" Q_SINCE=0 Q_LAST=0 Q_FROM="" Q_TO=""
    if [ -f "$QSTATE" ]; then
        while IFS='=' read -r K V; do
            case "$K" in BETTER) Q_BETTER=$V ;; SINCE) Q_SINCE=$V ;; LAST) Q_LAST=$V ;; FROM) Q_FROM=$V ;; TO) Q_TO=$V ;; esac
        done < "$QSTATE"
    fi
    case "$Q_SINCE" in ''|*[!0-9]*) Q_SINCE=0 ;; esac
    case "$Q_LAST" in ''|*[!0-9]*) Q_LAST=0 ;; esac
    b=$(quality_pick "$(auto_conf CRITERION balanced)")
    if [ -z "$b" ]; then
        Q_BETTER="" Q_SINCE=0
    elif [ "$b" != "$Q_BETTER" ]; then
        Q_BETTER=$b Q_SINCE=$NOW
    elif [ $((NOW - Q_SINCE)) -ge "$AUTO_HOLD" ] && [ $((NOW - Q_LAST)) -ge "$AUTO_GAP" ]; then
        if switch_to "$b"; then
            ACTION="QUALITY_SWITCH"
            FALLBACK_TO=$b QUALITY_FROM=$VWARD_TUNNEL_INTERFACE
            Q_FROM=$VWARD_TUNNEL_INTERFACE Q_TO=$b Q_LAST=$NOW Q_BETTER="" Q_SINCE=0
        else
            ACTION="QUALITY_SWITCH_ERROR"
        fi
    fi
    # In RAM: rewritten every minute is fine.
    printf 'BETTER=%s\nSINCE=%s\nLAST=%s\nFROM=%s\nTO=%s\n' "$Q_BETTER" "$Q_SINCE" "$Q_LAST" "$Q_FROM" "$Q_TO" > "$QSTATE.tmp.$$" &&
        mv -f "$QSTATE.tmp.$$" "$QSTATE"
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
# The first tunnel was deleted since: nothing to come back to.
# An empty answer (ndmc failed) proves nothing and keeps the memory.
FB_RC=""
[ -z "$FALLBACK_FROM" ] || FB_RC=$("${VWARD_NDMC:-ndmc}" -c "show running-config" 2>/dev/null | tr -d '\r')
if [ -n "$FALLBACK_FROM" ] && [ -n "$FB_RC" ] && ! printf '%s\n' "$FB_RC" | grep -qx "interface $FALLBACK_FROM"; then
    echo "$(date '+%Y-%m-%d %H:%M:%S')|FALLBACK_FORGOTTEN|gone=$FALLBACK_FROM" >> "$LOG"
    FALLBACK_FROM="" FALLBACK_AT=0
    rm -f "$FALLBACK"
fi

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
            engine_kick "$VWARD_TUNNEL_INTERFACE"
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
    } > "$TMP" &&

    mv "$TMP" "$STATE" || rm -f "$TMP"

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
                        # The tunnel answers, but the guard took it down: it must not stay
                        # switched off in Keenetic once the guard forgets it did that.
                        if [ "$CONFIG_STATE" != "up" ] &&
                           ! "${VWARD_NDMC:-ndmc}" -c "interface $VWARD_TUNNEL_INTERFACE up" >/dev/null 2>&1; then
                            ACTION="FAILOPEN_RESTORE_UP_ERROR"
                        fi
                    else
                        ACTION="WOULD_RESTORE"
                    fi

                    [ "$ACTION" = "FAILOPEN_RESTORE_UP_ERROR" ] || FAILOPEN_ACTIVE=0
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
                    [ -n "$FALLBACK_FROM" ] || quality_step
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

                            # A tunnel of VWARD's own engine: its program starts afresh first;
                            # only a tunnel that stays silent after it goes direct.
                            elif [ "$MODE" = "AUTO" ] && engine_of "$VWARD_TUNNEL_INTERFACE" >/dev/null &&
                                 { engine_kick "$VWARD_TUNNEL_INTERFACE" kick; sleep "${VWARD_GUARD_KICK_WAIT:-10}"; wg_ok; }; then

                                DOWN_STREAK=0
                                ACTION="ENGINE_RESTARTED"

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

                            # An engine tunnel: a restart, and when its server still does not
                            # answer, another server of its subscription (VLESS failover).
                            engine_kick "$VWARD_TUNNEL_INTERFACE" kick
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
    } > "$TMP" &&

    mv "$TMP" "$STATE" || rm -f "$TMP"
fi


lists_fallback

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
        echo "$NOW_TEXT|$ACTION|health=$WG_STATUS|config=$CONFIG_STATE|age=$AGE|down_streak=$DOWN_STREAK|active=$FAILOPEN_ACTIVE${FALLBACK_TO:+|to=$FALLBACK_TO}${FALLBACK_FROM:+|from=$FALLBACK_FROM}${QUALITY_FROM:+|from=$QUALITY_FROM}" \
            >> "$LOG"
        ;;
esac


echo "ACTION=$ACTION"
echo "Health=$WG_STATUS ConfigState=$CONFIG_STATE Age=${AGE}s"
echo "DownStreak=$DOWN_STREAK FailOpenActive=$FAILOPEN_ACTIVE"
echo "Mode=$MODE"
echo "ListsMoved=$LISTS_MOVED ListsBack=$LISTS_BACK"

exit 0
