#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

WAN="eth3"
WG="nwg1"
DNS="9.9.9.10"

CONNECT_TIMEOUT=2
MAX_TIME=3
SUCCESS_THRESHOLD=3

STATE_DIR="/opt/var/lib/vpn-audit"
LOG="/opt/var/log/vpn-audit.log"
SUMMARY_LOG="/opt/var/log/vpn-audit-summary.log"

RUNCFG="/tmp/vpn-audit-running.$$"
TARGETS="/tmp/vpn-audit-targets.$$"
CURRENT_TARGETS="/tmp/vpn-audit-current.$$"
CANDIDATES="$STATE_DIR/candidates.txt"
LOCK="/tmp/vpn-domain-audit.lock"

mkdir -p "$STATE_DIR" /opt/var/log

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
    rm -f "$RUNCFG" "$TARGETS" "$CURRENT_TARGETS"
}

trap cleanup EXIT INT TERM


# Exact FQDN-group parser. Group names are compared as fields, so
# domain-list1 can never absorb domain-list10..domain-list19.
group_members()
{
    G="$1"
    FILE="$2"

    awk -v wanted="$G" '
        $1=="object-group" && $2=="fqdn" {
            active=($3==wanted)
            next
        }

        /^!/ {
            active=0
            next
        }

        active && $1=="include" {
            print tolower($2)
        }
    ' "$FILE"
}

START_EPOCH=$(date +%s)
START_TEXT=$(date '+%Y-%m-%d %H:%M:%S')

if ! ndmc -c "show running-config" > "$RUNCFG" 2>/dev/null ||
   [ ! -s "$RUNCFG" ]; then
    echo "ERROR: cannot read running-config"
    exit 1
fi

WG_GROUPS=$(
    sed -n '/^dns-proxy/,/^!/p' "$RUNCFG" |
    awk '$1=="route" &&
         $2=="object-group" &&
         $4=="Wireguard1" {print $3}'
)

: > "$TARGETS"

for GROUP in $WG_GROUPS; do
    group_members "$GROUP" "$RUNCFG" |
    awk -v g="$GROUP" '{
        print g "|" $0
    }'
done | sort -u | awk -F'|' '!seen[$2]++' > "$TARGETS"

TOTAL=$(wc -l < "$TARGETS")

CHECKED=0
OK=0
FAIL=0
UNKNOWN_COUNT=0
NODNS=0
SKIPPED=0

echo "===== VPN DIRECT-ACCESS AUDIT ====="
echo "Started: $START_TEXT"
echo "Targets: $TOTAL"
echo "WAN: $WAN"
echo "DNS: $DNS"
echo "Timeout: ${CONNECT_TIMEOUT}/${MAX_TIME}s"
echo "Mode: READ-ONLY"
echo

while IFS='|' read GROUP HOST; do

    [ -z "$HOST" ] && continue

    # Wildcard/FQDN-маски напрямую curl/nslookup не тестируем.
    case "$HOST" in
        *'*'*)
            SKIPPED=$((SKIPPED + 1))
            echo "$(date '+%Y-%m-%d %H:%M:%S')|$HOST|$GROUP|SKIPPED_PATTERN|000|-|0" >> "$LOG"
            continue
            ;;
    esac

    CHECKED=$((CHECKED + 1))

    SAFE=$(echo "$HOST" | tr '/:*?' '____')
    STATE="$STATE_DIR/$SAFE.state"

    OLD_STREAK=0

    if [ -f "$STATE" ]; then
        OLD_STREAK=$(awk -F= '$1=="OK_STREAK" {print $2}' "$STATE" 2>/dev/null)
    fi

    case "$OLD_STREAK" in
        ''|*[!0-9]*) OLD_STREAK=0 ;;
    esac

    IP=$(
        /opt/bin/adaptive-resolve4.sh "$HOST" 2>/dev/null |
        awk '/^Address [0-9]+:/ &&
             $3 ~ /^[0-9]+\./ {ip=$3}
             END {print ip}'
    )

    RESULT="NO_IPV4"
    CLASS="NO_IPV4"
    CODE="000"
    TIME="-"
    VPN_CODE="000"
    OK_STREAK=0

    if [ -n "$IP" ]; then

        ISP_OUT=$(
            curl -4 \
                --noproxy '*' \
                --interface "$WAN" \
                --resolve "$HOST:443:$IP" \
                --connect-timeout "$CONNECT_TIMEOUT" \
                --max-time "$MAX_TIME" \
                -A "Mozilla/5.0" \
                -sS \
                -o /dev/null \
                -w '%{http_code}|%{time_total}' \
                "https://$HOST/" 2>/dev/null
        )

        ISP_RC=$?
        CODE=${ISP_OUT%%|*}
        TIME=${ISP_OUT#*|}

        [ -n "$CODE" ] || CODE="000"
        [ -n "$TIME" ] || TIME="-"

        NEED_VPN=0

        if [ "$ISP_RC" -eq 0 ]; then
            case "$CODE" in
                2??|3??)
                    CLASS="ISP_OK"
                    ;;
                5??)
                    CLASS="UNKNOWN"
                    ;;
                *)
                    NEED_VPN=1
                    ;;
            esac
        else
            NEED_VPN=1
        fi

        if [ "$NEED_VPN" -eq 1 ]; then

            VPN_OUT=$(
                curl -4 \
                    --noproxy '*' \
                    --interface "$WG" \
                    --resolve "$HOST:443:$IP" \
                    --connect-timeout "$CONNECT_TIMEOUT" \
                    --max-time "$MAX_TIME" \
                    -A "Mozilla/5.0" \
                    -sS \
                    -o /dev/null \
                    -w '%{http_code}|%{time_total}' \
                    "https://$HOST/" 2>/dev/null
            )

            VPN_RC=$?
            VPN_CODE=${VPN_OUT%%|*}

            [ -n "$VPN_CODE" ] || VPN_CODE="000"

            if [ "$ISP_RC" -ne 0 ]; then

                if [ "$VPN_RC" -eq 0 ]; then
                    case "$VPN_CODE" in
                        2??|3??|4??)
                            if [ "$VPN_CODE" != "451" ]; then
                                CLASS="ISP_BAD"
                            else
                                CLASS="UNKNOWN"
                            fi
                            ;;
                        *) CLASS="UNKNOWN" ;;
                    esac
                else
                    CLASS="UNKNOWN"
                fi

            else

                case "$CODE" in
                    451)
                        if [ "$VPN_RC" -eq 0 ] &&
                           [ "$VPN_CODE" != "451" ]; then
                            case "$VPN_CODE" in
                                2??|3??|4??) CLASS="ISP_BAD" ;;
                                *) CLASS="UNKNOWN" ;;
                            esac
                        else
                            CLASS="UNKNOWN"
                        fi
                        ;;

                    4??)
                        if [ "$VPN_RC" -eq 0 ] &&
                           [ "$VPN_CODE" = "$CODE" ]; then
                            CLASS="ISP_OK"
                        elif [ "$VPN_RC" -eq 0 ]; then
                            case "$VPN_CODE" in
                                2??|3??) CLASS="ISP_BAD" ;;
                                *) CLASS="UNKNOWN" ;;
                            esac
                        else
                            CLASS="UNKNOWN"
                        fi
                        ;;

                    *)
                        CLASS="UNKNOWN"
                        ;;
                esac
            fi
        fi

        case "$CLASS" in
            ISP_OK)
                RESULT="DIRECT_OK"
                OK_STREAK=$((OLD_STREAK + 1))
                OK=$((OK + 1))
                ;;

            ISP_BAD)
                RESULT="DIRECT_FAIL"
                OK_STREAK=0
                FAIL=$((FAIL + 1))
                ;;

            *)
                RESULT="DIRECT_UNKNOWN"
                OK_STREAK=0
                UNKNOWN_COUNT=$((UNKNOWN_COUNT + 1))
                ;;
        esac

    else
        NODNS=$((NODNS + 1))
    fi

    TMP="${STATE}.tmp.$$"

    {
        echo "HOST=$HOST"
        echo "GROUP=$GROUP"
        echo "OK_STREAK=$OK_STREAK"
        echo "LAST_RESULT=$RESULT"
        echo "LAST_CLASS=$CLASS"
        echo "LAST_CODE=$CODE"
        echo "LAST_VPN_CODE=$VPN_CODE"
        echo "LAST_TIME=$TIME"
        echo "LAST_CHECK=$(date +%s)"
    } > "$TMP"

    mv "$TMP" "$STATE"

    echo "$HOST" >> "$CURRENT_TARGETS"

    echo "$(date '+%Y-%m-%d %H:%M:%S')|$HOST|$GROUP|$RESULT|$CODE|$TIME|$OK_STREAK" \
        >> "$LOG"

done < "$TARGETS"

# Кандидатами считаются только домены, которые всё ещё находятся
# в текущих WireGuard-группах и получили нужное число DIRECT_OK подряд.
: > "$CANDIDATES"

while IFS='|' read GROUP HOST; do

    [ -z "$HOST" ] && continue

    case "$HOST" in
        *'*'*) continue ;;
    esac

    SAFE=$(echo "$HOST" | tr '/:*?' '____')
    STATE="$STATE_DIR/$SAFE.state"

    [ -f "$STATE" ] || continue

    OK_STREAK=$(awk -F= '$1=="OK_STREAK" {print $2}' "$STATE" 2>/dev/null)
    LAST_RESULT=$(awk -F= '$1=="LAST_RESULT" {print $2}' "$STATE" 2>/dev/null)
    LAST_CODE=$(awk -F= '$1=="LAST_CODE" {print $2}' "$STATE" 2>/dev/null)
    LAST_TIME=$(awk -F= '$1=="LAST_TIME" {print $2}' "$STATE" 2>/dev/null)

    case "$OK_STREAK" in
        ''|*[!0-9]*) OK_STREAK=0 ;;
    esac

    if [ "$LAST_RESULT" = "DIRECT_OK" ] &&
       [ "$OK_STREAK" -ge "$SUCCESS_THRESHOLD" ]; then

        echo "$HOST|$GROUP|$OK_STREAK|$LAST_CODE|$LAST_TIME" \
            >> "$CANDIDATES"
    fi

done < "$TARGETS"

END_EPOCH=$(date +%s)
END_TEXT=$(date '+%Y-%m-%d %H:%M:%S')
ELAPSED=$((END_EPOCH - START_EPOCH))

MINUTES=$((ELAPSED / 60))
SECONDS=$((ELAPSED % 60))

CANDIDATE_COUNT=0
[ -s "$CANDIDATES" ] && CANDIDATE_COUNT=$(wc -l < "$CANDIDATES")

echo
echo "===== AUDIT SUMMARY ====="
echo "Started:     $START_TEXT"
echo "Finished:    $END_TEXT"
echo "Duration:    ${MINUTES}m ${SECONDS}s"
echo "Targets:     $TOTAL"
echo "Checked:     $CHECKED"
echo "DIRECT_OK:   $OK"
echo "DIRECT_FAIL: $FAIL"
echo "UNKNOWN:     $UNKNOWN_COUNT"
echo "NO_IPV4:     $NODNS"
echo "Skipped:     $SKIPPED"
echo "Candidates:  $CANDIDATE_COUNT"
echo
echo "No routes or FQDN groups were changed."

echo "$END_TEXT|duration=${ELAPSED}s|targets=$TOTAL|checked=$CHECKED|ok=$OK|fail=$FAIL|unknown=${UNKNOWN_COUNT}|nodns=$NODNS|skipped=$SKIPPED|candidates=$CANDIDATE_COUNT" \
    >> "$SUMMARY_LOG"

exit 0
