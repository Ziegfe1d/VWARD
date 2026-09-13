#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

GROUP="AdaptiveAuto"
WAN="eth3"
WG="nwg1"
DNS="9.9.9.10"

AGH_LOG="/opt/etc/AdGuardHome/data/querylog.json"
SKIP_FILE="/opt/etc/vward/route-engine/skip-domains.conf"

STATE_DIR="/opt/var/lib/vward/route-discovery"
LOG="/opt/var/log/vward-route-discovery.log"

RUNCFG="/tmp/vward-route-discovery.running.$$"
KNOWN="/tmp/vward-route-discovery.known.$$"
RECENT="/tmp/vward-route-discovery.recent.$$"

LOCK="/tmp/vward-route-discovery.lock"

RECENT_LINES=800
MAX_PROBES=4
RECHECK_SEC=3600

# Пока только наблюдение.
AUTO_ADD="${AUTO_ADD:-0}"

mkdir -p "$STATE_DIR"

if ! mkdir "$LOCK" 2>/dev/null; then
    OLD_PID=$(cat "$LOCK/pid" 2>/dev/null)

    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Already running: PID $OLD_PID"
        exit 0
    fi

    echo "Removing stale lock: $LOCK"
    rm -rf "$LOCK"
    mkdir "$LOCK" 2>/dev/null || exit 1
fi

echo $$ > "$LOCK/pid"

cleanup()
{
    rm -rf "$LOCK"
    rm -f "$RUNCFG" "$KNOWN" "$RECENT"
}
trap cleanup EXIT INT TERM

# Не мешаем ночному полному аудиту.
if [ -d /tmp/vward-policy-sync.lock ]; then
    NIGHT_PID=$(cat /tmp/vward-policy-sync.lock/pid 2>/dev/null)

    if [ -n "$NIGHT_PID" ] && kill -0 "$NIGHT_PID" 2>/dev/null; then
        echo "Night VPN audit is running (PID $NIGHT_PID); discovery skipped."
        exit 0
    fi

    echo "Removing stale night-audit lock"
    rm -rf /tmp/vward-policy-sync.lock
fi

[ -f "$AGH_LOG" ] || {
    echo "AGH query log not found: $AGH_LOG"
    exit 1
}

NOW=$(date +%s)

ndmc -c "show running-config" > "$RUNCFG" 2>/dev/null

# Все уже вручную организованные FQDN-группы считаем неприкосновенными.
: > "$KNOWN"

for G in $(grep '^object-group fqdn ' "$RUNCFG" | awk '{print $3}'); do
    sed -n "/^object-group fqdn $G/,/^!/p" "$RUNCFG" |
    awk '
        $1=="include" {
            d=tolower($2)
            sub(/^\*\./,"",d)
            print d
        }
    '
done | sort -u > "$KNOWN"

# Последние реально запрошенные через AdGuard Home хосты.
# Сначала самые свежие.
tail -n "$RECENT_LINES" "$AGH_LOG" 2>/dev/null |
awk '
{
    line=$0

    if (match(line, /"QH":"[^"]+"/)) {
        h=substr(line,RSTART+6,RLENGTH-7)
        h=tolower(h)
        sub(/\.$/,"",h)

        if (index(h,".") > 0 &&
            h ~ /^[a-z0-9][a-z0-9._-]*[a-z0-9]$/) {

            # Храним именно ПОСЛЕДНЕЕ состояние домена.
            last[h]=NR

            if (line ~ /"IsFiltered":true/)
                filtered[h]=1
            else
                filtered[h]=0
        }
    }
}

END {
    for (h in last) {
        # В Adaptive Discovery попадают только
        # НЕ заблокированные самим AdGuard Home домены.
        if (!filtered[h])
            print last[h],h
    }
}
' |
sort -nr |
awk '{print $2}' > "$RECENT"

in_domain_file()
{
    H="$1"
    F="$2"

    [ -s "$F" ] || return 1

    awk -v h="$H" '
    {
        d=tolower($0)
        if (h==d ||
           (length(h)>length(d) &&
            substr(h,length(h)-length(d))=="." d)) {
            found=1
            exit
        }
    }
    END { exit found ? 0 : 1 }
    ' "$F"
}

probe()
{
    P_HOST="$1"
    P_IFACE="$2"
    P_IP="$3"

    OUT=$(
        curl -4 -k \
          --noproxy '*' \
          --interface "$P_IFACE" \
          --resolve "$P_HOST:443:$P_IP" \
          --connect-timeout 2 \
          --max-time 3 \
          -A "Mozilla/5.0" \
          -sS \
          -o /dev/null \
          -w '%{http_code}|%{time_total}' \
          "https://$P_HOST/" 2>/dev/null
    )

    P_RC=$?
    P_CODE=${OUT%%|*}
    P_TIME=${OUT#*|}

    [ -z "$P_CODE" ] && P_CODE="000"
    [ -z "$P_TIME" ] && P_TIME="-"

    [ "$P_RC" -eq 0 ] && [ "$P_CODE" != "000" ]
}

write_state()
{
    S_HOST="$1"
    S_STATUS="$2"
    S_CODE="$3"
    S_TIME="$4"

    SAFE=$(echo "$S_HOST" | sed 's/[^A-Za-z0-9._-]/_/g')
    STATE="$STATE_DIR/$SAFE.state"
    TMP="$STATE.tmp.$$"

    {
        echo "HOST=$S_HOST"
        echo "STATUS=$S_STATUS"
        echo "LAST_PROBE=$NOW"
        echo "LAST_CODE=$S_CODE"
        echo "LAST_TIME=$S_TIME"
    } > "$TMP"

    mv "$TMP" "$STATE"
}

RECENT_COUNT=$(wc -l < "$RECENT")
PROBED=0
DIRECT_OK=0
BOTH_FAIL=0
WOULD_ADD=0
ADDED=0
NO_IPV4=0
SKIPPED_KNOWN=0
SKIPPED_SPECIAL=0
SKIPPED_FRESH=0
DIRTY=0

echo "===== AGH ADAPTIVE DISCOVERY ====="
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Recent unique hosts: $RECENT_COUNT"
echo "Maximum probes: $MAX_PROBES"
echo "AUTO_ADD=$AUTO_ADD"
echo

while read HOST; do
    [ -z "$HOST" ] && continue

    case "$HOST" in
        *.in-addr.arpa|*.ip6.arpa|*.local|*.lan|*.invalid)
            continue
            ;;
    esac

    if in_domain_file "$HOST" "$KNOWN"; then
        SKIPPED_KNOWN=$((SKIPPED_KNOWN + 1))
        continue
    fi

    if in_domain_file "$HOST" "$SKIP_FILE"; then
        SKIPPED_SPECIAL=$((SKIPPED_SPECIAL + 1))
        continue
    fi

    SAFE=$(echo "$HOST" | sed 's/[^A-Za-z0-9._-]/_/g')
    STATE="$STATE_DIR/$SAFE.state"

    LAST_PROBE=0

    if [ -f "$STATE" ]; then
        LAST_PROBE=$(awk -F= '$1=="LAST_PROBE"{print $2}' "$STATE" 2>/dev/null)
    fi

    case "$LAST_PROBE" in
        ''|*[!0-9]*) LAST_PROBE=0 ;;
    esac

    if [ "$LAST_PROBE" -gt 0 ] &&
       [ $((NOW - LAST_PROBE)) -lt "$RECHECK_SEC" ]; then
        SKIPPED_FRESH=$((SKIPPED_FRESH + 1))
        continue
    fi

    [ "$PROBED" -ge "$MAX_PROBES" ] && break
    PROBED=$((PROBED + 1))

    IP=$(
        nslookup "$HOST" "$DNS" 2>/dev/null |
        awk '/^Address [0-9]+:/ &&
             $3 ~ /^[0-9]+\./ {
                 ip=$3
             }
             END {print ip}'
    )

    if [ -z "$IP" ]; then
        NO_IPV4=$((NO_IPV4 + 1))
        write_state "$HOST" "NO_IPV4" "000" "-"
        printf "%-42s NO_IPV4\n" "$HOST"
        continue
    fi

    # Если ISP отвечает хоть каким-нибудь HTTP-кодом,
    # сеть до сервера считается доступной.
    if probe "$HOST" "$WAN" "$IP"; then
        DIRECT_OK=$((DIRECT_OK + 1))
        write_state "$HOST" "DIRECT_OK" "$P_CODE" "$P_TIME"

        printf "%-42s ISP_OK  HTTP=%s time=%s\n" \
            "$HOST" "$P_CODE" "$P_TIME"
        continue
    fi

    D1_CODE="$P_CODE"

    # Повторяем прямую проверку, чтобы не реагировать
    # на единичный сетевой сбой.
    sleep 1

    if probe "$HOST" "$WAN" "$IP"; then
        DIRECT_OK=$((DIRECT_OK + 1))
        write_state "$HOST" "DIRECT_OK_RETRY" "$P_CODE" "$P_TIME"

        printf "%-42s ISP_OK_RETRY HTTP=%s\n" \
            "$HOST" "$P_CODE"
        continue
    fi

    # ISP дважды не прошёл. Теперь проверяем тот же IP через WG.
    if ! probe "$HOST" "$WG" "$IP"; then
        BOTH_FAIL=$((BOTH_FAIL + 1))
        write_state "$HOST" "ISP_FAIL_WG_FAIL" "$P_CODE" "$P_TIME"

        printf "%-42s ISP_FAIL + WG_FAIL\n" "$HOST"
        continue
    fi

    WG1_CODE="$P_CODE"

    sleep 1

    if ! probe "$HOST" "$WG" "$IP"; then
        BOTH_FAIL=$((BOTH_FAIL + 1))
        write_state "$HOST" "ISP_FAIL_WG_UNSTABLE" "$P_CODE" "$P_TIME"

        printf "%-42s ISP_FAIL + WG_UNSTABLE\n" "$HOST"
        continue
    fi

    # Два FAIL через ISP + два OK через WG.
    WOULD_ADD=$((WOULD_ADD + 1))

    if [ "$AUTO_ADD" = "1" ]; then

        OUT=$(ndmc -c "object-group fqdn $GROUP include $HOST" 2>&1)
        RC=$?

        if [ "$RC" -eq 0 ]; then
            ADDED=$((ADDED + 1))
            DIRTY=1

            write_state "$HOST" "AUTO_VPN" "$P_CODE" "$P_TIME"

            # Форсируем новый DNS-запрос через Keenetic,
            # чтобы FQDN-маршрут быстрее получил IP.
            nslookup "$HOST" 192.168.1.1 >/dev/null 2>&1

            printf "%-42s ADDED_TO_%s\n" "$HOST" "$GROUP"

            echo "$(date '+%Y-%m-%d %H:%M:%S')|$HOST|AUTO_VPN|$GROUP" \
                >> "$LOG"
        else
            write_state "$HOST" "ADD_ERROR" "000" "-"

            printf "%-42s ADD_ERROR rc=%s\n" "$HOST" "$RC"

            echo "$(date '+%Y-%m-%d %H:%M:%S')|$HOST|ADD_ERROR|$RC|$OUT" \
                >> "$LOG"
        fi

    else
        write_state "$HOST" "WOULD_ADD" "$P_CODE" "$P_TIME"

        printf "%-42s WOULD_ADD_TO_%s\n" "$HOST" "$GROUP"

        echo "$(date '+%Y-%m-%d %H:%M:%S')|$HOST|WOULD_ADD|$GROUP" \
            >> "$LOG"
    fi

done < "$RECENT"

if [ "$DIRTY" = "1" ]; then
    ndmc -c "system configuration save" >/dev/null 2>&1
fi

echo
echo "===== SUMMARY ====="
echo "Recent:          $RECENT_COUNT"
echo "Probed:          $PROBED"
echo "ISP OK:          $DIRECT_OK"
echo "ISP+WG fail:     $BOTH_FAIL"
echo "No IPv4:         $NO_IPV4"
echo "Would add:       $WOULD_ADD"
echo "Actually added:  $ADDED"
echo "Known skipped:   $SKIPPED_KNOWN"
echo "Special skipped: $SKIPPED_SPECIAL"
echo "Fresh skipped:   $SKIPPED_FRESH"

exit 0
