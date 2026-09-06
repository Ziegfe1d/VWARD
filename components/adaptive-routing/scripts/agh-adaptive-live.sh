#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

GROUP="AdaptiveAuto"

WAN="eth3"
WG="nwg1"
DNS="9.9.9.10"

STATE_DIR="/opt/var/lib/adaptive-live"

MANUAL="$STATE_DIR/manual-domains.txt"
ADAPTIVE="$STATE_DIR/adaptive-domains.txt"
PERSIST="$STATE_DIR/adaptive-persist.txt"
REFRESH_TS="$STATE_DIR/groups-refresh"

EVENT_LOG="/opt/var/log/adaptive-live-events.log"

LOCK="/tmp/agh-adaptive-live.lock"
CHANGE_LOCK="/tmp/adaptive-route-change.lock"

RAW="/tmp/adaptive-live-dns.$$"

CONNECT_TIMEOUT=2
MAX_TIME=3

# Изменения групп перечитываем максимум раз в минуту.
GROUP_REFRESH=60

# Обычный DIRECT-домен можно перепроверить уже через минуту.
DIRECT_COOLDOWN=60

# Ошибки "не работает нигде" не долбим постоянно.
FAIL_COOLDOWN=300

# Домен в AdaptiveAuto при следующем использовании
# может быть проверен на возврат ISP уже через минуту.
ADAPTIVE_RECHECK=60

TCP_PID=""

mkdir -p "$STATE_DIR"


# ------------------------------------------------------------
# LOCK
# ------------------------------------------------------------

if ! mkdir "$LOCK" 2>/dev/null; then

    OLD_PID=$(cat "$LOCK/pid" 2>/dev/null)

    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Adaptive Live already running PID=$OLD_PID"
        exit 0
    fi

    rm -rf "$LOCK"
    mkdir "$LOCK" || exit 1
fi

echo $$ > "$LOCK/pid"


cleanup()
{
    [ -n "$TCP_PID" ] && kill "$TCP_PID" 2>/dev/null
    [ -n "$TCP_PID" ] && wait "$TCP_PID" 2>/dev/null

    rm -f "$RAW"
    rm -rf "$LOCK"

    echo "$(date '+%Y-%m-%d %H:%M:%S')|STOP" >> "$EVENT_LOG"
}

trap cleanup EXIT INT TERM


# ------------------------------------------------------------
# CONFIG SETS
# ------------------------------------------------------------

refresh_sets()
{
    NOW=$(date +%s)
    LAST=0

    [ -f "$REFRESH_TS" ] &&
        LAST=$(cat "$REFRESH_TS" 2>/dev/null)

    case "$LAST" in
        ''|*[!0-9]*) LAST=0 ;;
    esac

    if [ $((NOW - LAST)) -lt "$GROUP_REFRESH" ] &&
       [ -f "$MANUAL" ] &&
       [ -f "$ADAPTIVE" ]; then
        return 0
    fi

    CFG="/tmp/adaptive-live-running.$$"
    ALL="/tmp/adaptive-live-all.$$"

    if ! ndmc -c "show running-config" > "$CFG" 2>/dev/null ||
       [ ! -s "$CFG" ]; then
        rm -f "$CFG" "$ALL"
        return 1
    fi

    awk '
        /^object-group fqdn / {
            g=$3
            next
        }

        /^!/ {
            g=""
            next
        }

        g!="" && $1=="include" {
            print g "|" tolower($2)
        }
    ' "$CFG" > "$ALL"

    awk -F'|' '
        $1=="AdaptiveAuto" {
            print $2
        }
    ' "$ALL" |
    sort -u > "${ADAPTIVE}.new"

    awk -F'|' '
        $1!="AdaptiveAuto" {
            print $2
        }
    ' "$ALL" |
    sort -u > "${MANUAL}.new"

    mv "${ADAPTIVE}.new" "$ADAPTIVE"
    mv "${MANUAL}.new" "$MANUAL"

    echo "$NOW" > "$REFRESH_TS"

    rm -f "$CFG" "$ALL"
}


is_manual_known()
{
    H="$1"

    grep -Fxq "$H" "$MANUAL" 2>/dev/null &&
        return 0

    # Поддержка явных wildcard-записей.
    awk -v h="$H" '
        /^\*\./ {
            d=substr($0,3)

            if (length(h)>length(d) &&
                substr(h,length(h)-length(d))=="." d) {
                found=1
                exit
            }
        }

        END {
            exit found ? 0 : 1
        }
    ' "$MANUAL"
}


is_adaptive()
{
    grep -Fxq "$1" "$ADAPTIVE" 2>/dev/null
}


is_special()
{
    H="$1"
    F="/opt/etc/adaptive-route/skip-domains.conf"

    [ -f "$F" ] || return 1

    awk -v h="$H" '
        {
            d=tolower($0)

            if (d=="" || substr(d,1,1)=="#")
                next

            if (h==d ||
               (length(h)>length(d) &&
                substr(h,length(h)-length(d))=="." d)) {
                found=1
                exit
            }
        }

        END {
            exit found ? 0 : 1
        }
    ' "$F"
}


# ------------------------------------------------------------
# STATE
# ------------------------------------------------------------

state_file()
{
    echo "$STATE_DIR/$(echo "$1" | tr '/:*?' '____').state"
}


save_state()
{
    H="$1"
    STATUS="$2"

    STATE=$(state_file "$H")
    TMP="${STATE}.tmp.$$"

    {
        echo "HOST=$H"
        echo "STATUS=$STATUS"
        echo "LAST_CHECK=$(date +%s)"
    } > "$TMP"

    mv "$TMP" "$STATE"
}


regular_cooldown()
{
    H="$1"
    STATE=$(state_file "$H")

    [ -f "$STATE" ] || return 1

    STATUS=$(awk -F= '$1=="STATUS"{print $2}' "$STATE")
    LAST=$(awk -F= '$1=="LAST_CHECK"{print $2}' "$STATE")

    case "$LAST" in
        ''|*[!0-9]*) return 1 ;;
    esac

    NOW=$(date +%s)
    AGE=$((NOW - LAST))

    case "$STATUS" in

        DIRECT_OK)
            [ "$AGE" -lt "$DIRECT_COOLDOWN" ] &&
                return 0
            ;;

        AGH_BLOCKED|NO_IPV4|ISP_FAIL_WG_FAIL|ISP_FAIL_WG_UNSTABLE)
            [ "$AGE" -lt "$FAIL_COOLDOWN" ] &&
                return 0
            ;;

    esac

    return 1
}


adaptive_due()
{
    H="$1"
    STATE=$(state_file "$H")

    [ -f "$STATE" ] || return 0

    LAST=$(awk -F= '$1=="LAST_CHECK"{print $2}' "$STATE")

    case "$LAST" in
        ''|*[!0-9]*) return 0 ;;
    esac

    NOW=$(date +%s)
    AGE=$((NOW - LAST))

    [ "$AGE" -ge "$ADAPTIVE_RECHECK" ]
}


# ------------------------------------------------------------
# DNS / NETWORK TEST
# ------------------------------------------------------------

agh_blocked()
{
    H="$1"

    OUT=$(nslookup "$H" 192.168.1.1 2>&1)

    echo "$OUT" |
    grep -qE 'Address [0-9]+: (0\.0\.0\.0|::)$'
}


resolve_ipv4()
{
    /opt/bin/adaptive-resolve4.sh "$1" 2>/dev/null |
    awk '
        /^Address [0-9]+:/ &&
        $3 ~ /^[0-9]+\./ {
            ip=$3
        }

        END {
            print ip
        }
    '
}


probe()
{
    H="$1"
    IFACE="$2"
    IP="$3"

    OUT=$(
        curl -4 \
            --noproxy '*' \
            --interface "$IFACE" \
            --resolve "$H:443:$IP" \
            --connect-timeout "$CONNECT_TIMEOUT" \
            --max-time "$MAX_TIME" \
            -A "Mozilla/5.0" \
            -sS \
            -o /dev/null \
            -w '%{http_code}|%{time_total}' \
            "https://$H/" 2>/dev/null
    )

    P_RC=$?
    P_CODE=${OUT%%|*}
    P_TIME=${OUT#*|}

    [ -z "$P_CODE" ] && P_CODE="000"
    [ -z "$P_TIME" ] && P_TIME="-"

    # Любой реальный HTTP-ответ означает доступность сети.
    # 451 отдельно считаем подозрительным блоком.
    [ "$P_RC" -eq 0 ] &&
    [ "$P_CODE" != "000" ] &&
    [ "$P_CODE" != "451" ]
}


# ------------------------------------------------------------
# CHANGE LOCK
# ------------------------------------------------------------

change_lock()
{
    N=0

    while ! mkdir "$CHANGE_LOCK" 2>/dev/null; do

        OLD=$(cat "$CHANGE_LOCK/pid" 2>/dev/null)

        if [ -n "$OLD" ] &&
           ! kill -0 "$OLD" 2>/dev/null; then

            rm -rf "$CHANGE_LOCK"
            continue
        fi

        sleep 1
        N=$((N + 1))

        [ "$N" -ge 10 ] && return 1
    done

    echo $$ > "$CHANGE_LOCK/pid"
    return 0
}


change_unlock()
{
    rm -rf "$CHANGE_LOCK"
}


# ------------------------------------------------------------
# ------------------------------------------------------------
# AUTHORITATIVE ADAPTIVE PERSISTENCE
# ------------------------------------------------------------

persist_sync_cache()
{
    TMPP="${PERSIST}.new.$$"

    grep -v '^[[:space:]]*$' "$ADAPTIVE" 2>/dev/null |
    tr '[:upper:]' '[:lower:]' |
    sort -u > "$TMPP"

    if mv "$TMPP" "$PERSIST"; then
        return 0
    fi

    rm -f "$TMPP"
    return 1
}


restore_adaptive_from_persist()
{
    if [ ! -f "$PERSIST" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|PERSIST_MISSING_START" \
            >> "$EVENT_LOG"
        return 1
    fi

    change_lock || {
        echo "$(date '+%Y-%m-%d %H:%M:%S')|PERSIST_RESTORE_LOCK_FAIL" \
            >> "$EVENT_LOG"
        return 1
    }

    CFG="/tmp/adaptive-restore-cfg.$$"
    CUR="/tmp/adaptive-restore-cur.$$"
    WANT="/tmp/adaptive-restore-want.$$"

    if ! ndmc -c "show running-config" > "$CFG" 2>/dev/null ||
       [ ! -s "$CFG" ]; then

        rm -f "$CFG" "$CUR" "$WANT"
        change_unlock

        echo "$(date '+%Y-%m-%d %H:%M:%S')|PERSIST_RESTORE_CONFIG_FAIL" \
            >> "$EVENT_LOG"

        return 1
    fi

    sed -n '/^object-group fqdn AdaptiveAuto/,/^!/p' "$CFG" |
    sed -n 's/^[[:space:]]*include[[:space:]][[:space:]]*//p' |
    tr '[:upper:]' '[:lower:]' |
    sort -u > "$CUR"

    grep -v '^[[:space:]]*$' "$PERSIST" |
    tr '[:upper:]' '[:lower:]' |
    sort -u > "$WANT"

    RC=0
    ADDED=0
    REMOVED=0

    while IFS= read -r H; do
        [ -n "$H" ] || continue

        if ! grep -Fxq "$H" "$WANT"; then
            if ndmc -c \
              "no object-group fqdn $GROUP include $H" \
              >/dev/null 2>&1; then
                REMOVED=$((REMOVED + 1))
            else
                RC=1
            fi
        fi
    done < "$CUR"

    while IFS= read -r H; do
        [ -n "$H" ] || continue

        if ! grep -Fxq "$H" "$CUR"; then
            if ndmc -c \
              "object-group fqdn $GROUP include $H" \
              >/dev/null 2>&1; then
                ADDED=$((ADDED + 1))
            else
                RC=1
            fi
        fi
    done < "$WANT"

    rm -f "$CFG" "$CUR" "$WANT"

    echo 0 > "$REFRESH_TS"

    change_unlock

    if [ "$RC" -eq 0 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|PERSIST_RESTORE_OK|added=$ADDED|removed=$REMOVED" \
            >> "$EVENT_LOG"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S')|PERSIST_RESTORE_PARTIAL|added=$ADDED|removed=$REMOVED" \
            >> "$EVENT_LOG"
    fi

    return "$RC"
}

# ADD TO VPN
# ------------------------------------------------------------

add_adaptive()
{
    H="$1"

    change_lock || return 1
    # FINAL_GUARD_V4_ADD
    echo 0 > "$REFRESH_TS"
    refresh_sets

    if is_manual_known "$H" || parent_list_match "$H" "$MANUAL" || \
       is_special "$H" || parent_list_match "$H" "/opt/etc/adaptive-route/skip-domains.conf" || \
       is_adaptive "$H"; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|ADD_ABORT_STATE|$H" >> "$EVENT_LOG"
        change_unlock
        return 0
    fi

    if agh_blocked "$H"; then
        save_state "$H" "AGH_BLOCKED"
        echo "$(date '+%Y-%m-%d %H:%M:%S')|ADD_ABORT_AGH|$H" >> "$EVENT_LOG"
        change_unlock
        return 0
    fi

    GIP=$(resolve_ipv4 "$H")

    if [ -z "$GIP" ]; then
        change_unlock
        return 0
    fi

    if probe "$H" "$WAN" "$GIP"; then
        save_state "$H" "DIRECT_OK"
        echo "$(date '+%Y-%m-%d %H:%M:%S')|ADD_ABORT_DIRECT_RECOVERED|$H" >> "$EVENT_LOG"
        change_unlock
        return 0
    fi

    if ! probe "$H" "$WG" "$GIP"; then
        save_state "$H" "ISP_FAIL_WG_FAIL"
        echo "$(date '+%Y-%m-%d %H:%M:%S')|ADD_ABORT_WG_FAIL|$H" >> "$EVENT_LOG"
        change_unlock
        return 0
    fi

    OUT=$(ndmc -c "object-group fqdn $GROUP include $H" 2>&1)
    RC=$?

    if [ "$RC" -eq 0 ]; then


        echo "$H" >> "$ADAPTIVE"
        sort -u "$ADAPTIVE" -o "$ADAPTIVE"

        persist_sync_cache

        echo 0 > "$REFRESH_TS"

        save_state "$H" "AUTO_VPN"

        # Помогаем Keenetic сразу наполнить runtime FQDN IP.
        nslookup "$H" 192.168.1.1 >/dev/null 2>&1

        echo "$(date '+%Y-%m-%d %H:%M:%S')|AUTO_VPN|$H|$GROUP" \
            >> "$EVENT_LOG"

        echo "AUTO_VPN: $H"

        change_unlock
        return 0
    fi

    echo "$(date '+%Y-%m-%d %H:%M:%S')|ADD_ERROR|$H|rc=$RC|$OUT" \
        >> "$EVENT_LOG"

    change_unlock
    return 1
}


# ------------------------------------------------------------
# REMOVE FROM VPN -> DIRECT
# ------------------------------------------------------------

remove_adaptive()
{
    H="$1"

    # Removal from AdaptiveAuto is owned exclusively by
    # adaptive-auto-maint.sh with 3-step hysteresis.
    return 0
}


# ------------------------------------------------------------
# DOMAIN ALREADY IN ADAPTIVEAUTO
# ------------------------------------------------------------

handle_adaptive()
{
    HOST="$1"

    adaptive_due "$HOST" || return

    echo "$(date '+%Y-%m-%d %H:%M:%S')|RECHECK_ADAPTIVE|$HOST" \
        >> "$EVENT_LOG"

    if agh_blocked "$HOST"; then

        save_state "$HOST" "ADAPTIVE_AGH_BLOCKED"

        echo "$(date '+%Y-%m-%d %H:%M:%S')|ADAPTIVE_AGH_BLOCKED|$HOST" \
            >> "$EVENT_LOG"

        return
    fi

    IP=$(resolve_ipv4 "$HOST")

    if [ -z "$IP" ]; then

        save_state "$HOST" "ADAPTIVE_NO_IPV4"

        echo "$(date '+%Y-%m-%d %H:%M:%S')|ADAPTIVE_NO_IPV4|$HOST" \
            >> "$EVENT_LOG"

        return
    fi


    # ISP success №1
    if probe "$HOST" "$WAN" "$IP"; then

        sleep 1

        # ISP success №2
        if probe "$HOST" "$WAN" "$IP"; then

            remove_adaptive "$HOST"
            return
        fi

        save_state "$HOST" "ADAPTIVE_DIRECT_UNSTABLE"

        echo "$(date '+%Y-%m-%d %H:%M:%S')|DIRECT_UNSTABLE|$HOST" \
            >> "$EVENT_LOG"

        return
    fi


    # ISP не работает -> проверяем текущий VPN.
    if probe "$HOST" "$WG" "$IP"; then

        save_state "$HOST" "AUTO_VPN"

        echo "$(date '+%Y-%m-%d %H:%M:%S')|VPN_OK|$HOST" \
            >> "$EVENT_LOG"

        return
    fi

    sleep 1

    if probe "$HOST" "$WG" "$IP"; then

        save_state "$HOST" "AUTO_VPN"

        echo "$(date '+%Y-%m-%d %H:%M:%S')|VPN_OK_RETRY|$HOST" \
            >> "$EVENT_LOG"

        return
    fi


    # Не работает ни ISP, ни VPN.
    # Ничего не удаляем: просто отмечаем.
    save_state "$HOST" "BROKEN"

    echo "$(date '+%Y-%m-%d %H:%M:%S')|BROKEN_ISP_AND_VPN|$HOST" \
        >> "$EVENT_LOG"
}


# ------------------------------------------------------------
# NEW / UNKNOWN DOMAIN
# ------------------------------------------------------------

handle_new()
{
    HOST="$1"

    regular_cooldown "$HOST" && return


    if agh_blocked "$HOST"; then

        save_state "$HOST" "AGH_BLOCKED"

        echo "$(date '+%Y-%m-%d %H:%M:%S')|AGH_BLOCKED|$HOST" \
            >> "$EVENT_LOG"

        return
    fi


    IP=$(resolve_ipv4 "$HOST")

    if [ -z "$IP" ]; then

        save_state "$HOST" "NO_IPV4"

        echo "$(date '+%Y-%m-%d %H:%M:%S')|NO_IPV4|$HOST" \
            >> "$EVENT_LOG"

        return
    fi


    # ISP работает -> DIRECT.
    if probe "$HOST" "$WAN" "$IP"; then

        save_state "$HOST" "DIRECT_OK"

        echo "$(date '+%Y-%m-%d %H:%M:%S')|DIRECT_OK|$HOST|$P_CODE|$P_TIME" \
            >> "$EVENT_LOG"

        return
    fi


    # Подтверждаем ISP FAIL второй раз.
    sleep 1

    if probe "$HOST" "$WAN" "$IP"; then

        save_state "$HOST" "DIRECT_OK"

        echo "$(date '+%Y-%m-%d %H:%M:%S')|DIRECT_OK_RETRY|$HOST|$P_CODE|$P_TIME" \
            >> "$EVENT_LOG"

        return
    fi


    # ISP FAIL x2. Проверяем WG.
    if ! probe "$HOST" "$WG" "$IP"; then

        save_state "$HOST" "ISP_FAIL_WG_FAIL"

        echo "$(date '+%Y-%m-%d %H:%M:%S')|ISP_FAIL_WG_FAIL|$HOST" \
            >> "$EVENT_LOG"

        return
    fi


    # Подтверждаем WG второй раз.
    sleep 1

    if ! probe "$HOST" "$WG" "$IP"; then

        save_state "$HOST" "ISP_FAIL_WG_UNSTABLE"

        echo "$(date '+%Y-%m-%d %H:%M:%S')|ISP_FAIL_WG_UNSTABLE|$HOST" \
            >> "$EVENT_LOG"

        return
    fi


    # ISP FAIL x2 + WG OK x2.
    add_adaptive "$HOST"
}


# ------------------------------------------------------------
# EVENT
# ------------------------------------------------------------

parent_list_match()
{
    H="$1"
    FILE="$2"

    [ -s "$FILE" ] || return 1

    awk -v h="$H" '
    {
        d=tolower($0)
        gsub(/^[ \t]+|[ \t]+$/, "", d)

        if (d=="" || substr(d,1,1)=="#")
            next

        sub(/^\\*\\./, "", d)

        if (h==d ||
           (length(h)>length(d) &&
            substr(h,length(h)-length(d))=="." d)) {
            found=1
            exit
        }
    }

    END {
        exit found ? 0 : 1
    }
    ' "$FILE"
}

# ------------------------------------------------------------
# HINT / PRELOAD V5
# ------------------------------------------------------------

hint_direct_fresh()
{
    H="$1"
    F=$(state_file "$H")

    [ -f "$F" ] || return 1

    HS=$(awk -F= '$1=="STATUS"{print $2}' "$F")
    HL=$(awk -F= '$1=="LAST_CHECK"{print $2}' "$F")

    [ "$HS" = "DIRECT_OK" ] || return 1

    case "$HL" in
        ''|*[!0-9]*) return 1 ;;
    esac

    AGE=$(($(date +%s) - HL))

    [ "$AGE" -lt 21600 ]
}


hint_direct_known()
{
    H="$1"
    F=$(state_file "$H")

    [ -f "$F" ] || return 1

    HS=$(awk -F= '$1=="STATUS"{print $2}' "$F")

    [ "$HS" = "DIRECT_OK" ]
}

wg_quick_probe()
{
    curl -4 -k \
      --noproxy '*' \
      --interface "$WG" \
      --connect-timeout 1 \
      --max-time 2 \
      -sS -o /dev/null \
      "https://1.1.1.1/cdn-cgi/trace" \
      >/dev/null 2>&1
}


wg_quick_ok()
{
    # Один успех достаточен.
    # WG_DOWN подтверждаем только двумя провалами подряд.
    wg_quick_probe && return 0

    sleep 1

    wg_quick_probe && return 0

    return 1
}

add_hint_adaptive()
{
    H="$1"

    change_lock || return 1

    echo 0 > "$REFRESH_TS"
    refresh_sets

    # Состояние могло измениться, пока ждали lock.
    if hint_direct_fresh "$H"; then
        change_unlock
        return 0
    fi

    if is_manual_known "$H" || \
       parent_list_match "$H" "$MANUAL" || \
       is_special "$H" || \
       parent_list_match "$H" "/opt/etc/adaptive-route/skip-domains.conf" || \
       is_adaptive "$H" || \
       ! parent_list_match "$H" "/opt/etc/adaptive-route/hints.conf"; then

        change_unlock
        return 0
    fi

    if agh_blocked "$H"; then
        save_state "$H" "AGH_BLOCKED"
        echo "$(date '+%Y-%m-%d %H:%M:%S')|HINT_AGH_BLOCKED|$H" >> "$EVENT_LOG"
        change_unlock
        return 0
    fi

    # WG HEALTH GATE V5.3
    if ! wg_quick_ok; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|HINT_WG_UNAVAILABLE|$H" >> "$EVENT_LOG"

        change_unlock

        # Не создаём чёрную дыру в AdaptiveAuto.
        # Передаём домен обычному Live:
        # DIRECT -> WG probes -> безопасное решение.
        handle_new "$H"
        return 0
    fi

    OUT=$(ndmc -c "object-group fqdn $GROUP include $H" 2>&1)
    RC=$?

    if [ "$RC" -eq 0 ]; then

        echo "$H" >> "$ADAPTIVE"
        sort -u "$ADAPTIVE" -o "$ADAPTIVE"

        persist_sync_cache

        echo 0 > "$REFRESH_TS"

        save_state "$H" "AUTO_VPN"

        nslookup "$H" 192.168.1.1 >/dev/null 2>&1

        echo "$(date '+%Y-%m-%d %H:%M:%S')|HINT_AUTO_VPN|$H|$GROUP" >> "$EVENT_LOG"
        echo "HINT_AUTO_VPN: $H"

        change_unlock
        return 0
    fi

    echo "$(date '+%Y-%m-%d %H:%M:%S')|HINT_ADD_ERROR|$H|rc=$RC" >> "$EVENT_LOG"

    change_unlock
    return 1
}


handle_hint()
{
    HOST="$1"

    # Если DIRECT недавно был подтверждён,
    # не загоняем домен обратно в VPN вслепую.
    if hint_direct_known "$HOST"; then

        regular_cooldown "$HOST" && return

        if agh_blocked "$HOST"; then
            save_state "$HOST" "AGH_BLOCKED"
            return
        fi

        IP=$(resolve_ipv4 "$HOST")

        if [ -n "$IP" ] && probe "$HOST" "$WAN" "$IP"; then
            save_state "$HOST" "DIRECT_OK"

            echo "$(date '+%Y-%m-%d %H:%M:%S')|HINT_DIRECT_OK|$HOST|$P_CODE|$P_TIME" \
                >> "$EVENT_LOG"

            return
        fi

        # DIRECT перестал работать:
        # Hint позволяет сразу вернуть VPN.
        save_state "$HOST" "HINT_DIRECT_FAIL"

        add_hint_adaptive "$HOST"
        return
    fi

    # Первый вход или DIRECT давно не подтверждался:
    # сразу VPN, без предварительной серии ISP/WG-проб.
    add_hint_adaptive "$HOST"
}

handle_host()
{
    HOST=$(echo "$1" | tr 'A-Z' 'a-z')
    HOST=${HOST%.}

    [ -z "$HOST" ] && return

    case "$HOST" in
        localhost|*.local|*.lan|*.invalid|*.in-addr.arpa|*.ip6.arpa)
            return
            ;;
    esac

    echo "$HOST" | grep -q '\.' || return




    refresh_sets


    # Все ручные Keenetic FQDN-группы live-контур не меняет.
    if is_manual_known "$HOST" || parent_list_match "$HOST" "$MANUAL"; then
        return
    fi


    # AdaptiveAuto обслуживается двусторонне.
    if is_adaptive "$HOST"; then
        handle_adaptive "$HOST"
        return
    fi


    # Aeternia / специальные исключения.
    if is_special "$HOST" || parent_list_match "$HOST" "/opt/etc/adaptive-route/skip-domains.conf"; then
        return
    fi



    # Hint / Preload V5
    if parent_list_match "$HOST" "/opt/etc/adaptive-route/hints.conf"; then
        handle_hint "$HOST"
        return
    fi

    handle_new "$HOST"
}


# ------------------------------------------------------------
# MAIN LIVE LOOP
# ------------------------------------------------------------

echo "$(date '+%Y-%m-%d %H:%M:%S')|START" >> "$EVENT_LOG"

# USB state is authoritative for AdaptiveAuto.
restore_adaptive_from_persist

refresh_sets

while :; do

    rm -f "$RAW"
    mkfifo "$RAW" || exit 1


    tcpdump -ni any -l -vv \
        'src net 192.168.1.0/24 and not src host 192.168.1.1 and dst host 192.168.1.1 and (udp dst port 53 or tcp dst port 53)' \
        > "$RAW" 2>/dev/null &

    TCP_PID=$!


    while IFS= read -r LINE; do

        HOST=$(
            echo "$LINE" |
            awk '
                {
                    for (i=1; i<NF; i++) {

                        if ($i=="A?" ||
                            $i=="AAAA?" ||
                            $i=="HTTPS?") {

                            h=$(i+1)
                            sub(/\.$/,"",h)

                            print h
                            exit
                        }
                    }
                }
            '
        )

        [ -n "$HOST" ] &&
            handle_host "$HOST"

    done < "$RAW"


    wait "$TCP_PID" 2>/dev/null
    TCP_PID=""

    rm -f "$RAW"

    echo "$(date '+%Y-%m-%d %H:%M:%S')|TCPDUMP_RESTART" \
        >> "$EVENT_LOG"

    sleep 2

done
