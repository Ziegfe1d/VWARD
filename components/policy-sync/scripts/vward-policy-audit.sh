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
vward_admission_enter policy-audit || exit $?

WAN="$VWARD_WAN_DEVICE"
WG="$VWARD_TUNNEL_DEVICE"
DNS="$VWARD_PROBE_DNS"

CONNECT_TIMEOUT=2
MAX_TIME=3

# tunnel_answers: the tunnel carries traffic at all (the VPN agent's probes, 1.1.1.1 / 1.0.0.1).
tunnel_answers() {
    for ta_ip in ${VWARD_AUDIT_TUNNEL_PROBES:-1.1.1.1 1.0.0.1}; do
        curl --http1.1 -4 --noproxy '*' --interface "$WG" --connect-timeout 4 --max-time 8 \
            -s -o /dev/null "http://$ta_ip/cdn-cgi/trace" 2>/dev/null && return 0
    done
    return 1
}
SUCCESS_THRESHOLD=3

# Keenetic busy (fix.34; Viva 25.10: the run at 00:10 took 26-36 min over ~500 sites, 273 of 491
# not passed, 60 -> 19 passed, as the night's false «Интернет»): the sites go in portions, and
# between portions the run waits while vward_busy says so, at most AUDIT_PAUSE_MAX seconds in all.
# Which sites and how they are judged does not change. VWARD_AUDIT_PAUSE=0 turns it off.
AUDIT_PORTION=${VWARD_AUDIT_PORTION:-20}
AUDIT_PAUSE_STEP=${VWARD_AUDIT_PAUSE_STEP:-15}
AUDIT_PAUSE_MAX=${VWARD_AUDIT_PAUSE_MAX:-600}
PAUSED=0
PAUSES=0
audit_pause()
{
    [ "${VWARD_AUDIT_PAUSE:-1}" = 1 ] || return 0
    command -v vward_busy >/dev/null 2>&1 || return 0
    ap_in=0
    while [ "$PAUSED" -lt "$AUDIT_PAUSE_MAX" ] && vward_busy; do
        [ "$ap_in" = 1 ] || PAUSES=$((PAUSES + 1))
        ap_in=1
        sleep "$AUDIT_PAUSE_STEP"
        PAUSED=$((PAUSED + AUDIT_PAUSE_STEP))
    done
    return 0
}

# Why a site did not pass, for the summary line only (diagnostics; the judging is above).
REASONS=
audit_reason()
{
    case "$CLASS" in
        ISP_OK) return 0 ;;
    esac
    if [ "$CLASS" = UNKNOWN ] && [ "${NEED_VPN:-0}" = 1 ] && [ "${VPN_RC:-0}" -ne 0 ]; then
        ar=vpn_down
    else
        case "$ISP_RC" in
            0) case "$CODE" in 451) ar=http_451 ;; 4??) ar=http_4xx ;; 5??) ar=http_5xx ;; *) ar=http_other ;; esac ;;
            6) ar=isp_dns ;;
            7) ar=isp_refused ;;
            28) ar=isp_timeout ;;
            35|60) ar=isp_tls ;;
            52|56) ar=isp_reset ;;
            *) ar=isp_rc$ISP_RC ;;
        esac
    fi
    REASONS="$REASONS $ar"
}

STATE_DIR="/opt/var/lib/vward/policy-audit"
LOG="/opt/var/log/vward-policy-audit.log"
SUMMARY_LOG="/opt/var/log/vward-policy-audit-summary.log"

RUNCFG="/tmp/vward-policy-audit-running.$$"
TARGETS="/tmp/vward-policy-audit-targets.$$"
CURRENT_TARGETS="/tmp/vward-policy-audit-current.$$"
CANDIDATES="$STATE_DIR/candidates.txt"
LOCK="/tmp/vward-policy-sync.lock"

mkdir -p "$STATE_DIR" /opt/var/log

if ! mkdir "$LOCK" 2>/dev/null; then
    OLD_PID=$(cat "$LOCK/pid" 2>/dev/null)

    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Already running: PID $OLD_PID"
        exit 0
    fi

    echo "Removing stale lock: $LOCK"
    rm -rf "${LOCK:?}"
    mkdir "$LOCK" 2>/dev/null || exit 1
fi

echo $$ > "$LOCK/pid"

cleanup()
{
    rm -rf "${LOCK:?}"
    rm -f "$RUNCFG" "$TARGETS" "$CURRENT_TARGETS"
    vward_admission_leave 2>/dev/null || true
}

trap cleanup EXIT
trap 'exit 1' HUP INT TERM


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

# A site is judged through the tunnel: with the tunnel down every check through it fails and
# 271 sites came out «unknown» (Viva 2026-10-19, the default tunnel without settings). Then
# nothing is checked; the mark asks for a run once the tunnel answers again (housekeeping).
RECHECK="$STATE_DIR/recheck"
TH_STATUS=$(awk -F= '$1 == "STATUS" {print $2; exit}' "${VWARD_TUNNEL_HEALTH_STATE:-/tmp/vward-tunnel-health/state}" 2>/dev/null)
case "$TH_STATUS" in
    UP|DEGRADED) ;;
    *) echo "$START_TEXT|SKIPPED_TUNNEL_DOWN|tunnel=${VWARD_TUNNEL_INTERFACE:-?}|health=${TH_STATUS:-none}" >> "$SUMMARY_LOG"
       : > "$RECHECK"
       echo "SKIPPED: the tunnel does not answer (${TH_STATUS:-no health state})"
       exit 75 ;;
esac
VPN_FAILS=0

if ! vward_running_config > "$RUNCFG" ||
   [ ! -s "$RUNCFG" ]; then
    echo "ERROR: cannot read running-config"
    exit 1
fi

WG_GROUPS=$(
    sed -n '/^dns-proxy/,/^!/p' "$RUNCFG" |
    awk -v wg="$WG" -v wgi="${VWARD_TUNNEL_INTERFACE:-}" '$1=="route" &&
         $2=="object-group" &&
         ($4==wg || ($4==wgi && wgi!="")) {print $3}'
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
    [ $((CHECKED % AUDIT_PORTION)) -ne 0 ] || audit_pause

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
        /opt/bin/vward-route-resolve4.sh "$HOST" 2>/dev/null |
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
            curl --http1.1 -4 \
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
                curl --http1.1 -4 \
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
            # Ten sites in a row silent through the tunnel: the tunnel itself went down - when it
            # fails the VPN agent's own probes too (fix.33.1: a run of dead sites in the list cut
            # the audit short at the same place every hour, the tunnel up).
            if [ "$VPN_RC" -eq 0 ]; then VPN_FAILS=0; else VPN_FAILS=$((VPN_FAILS + 1)); fi
            if [ "$VPN_FAILS" -ge "${VWARD_AUDIT_TUNNEL_FAILS:-10}" ] && tunnel_answers; then
                VPN_FAILS=0
            fi
            if [ "$VPN_FAILS" -ge "${VWARD_AUDIT_TUNNEL_FAILS:-10}" ]; then
                echo "$(date '+%Y-%m-%d %H:%M:%S')|ABORTED_TUNNEL_DOWN|tunnel=${VWARD_TUNNEL_INTERFACE:-?}|checked=$CHECKED" >> "$SUMMARY_LOG"
                : > "$RECHECK"
                echo "ABORTED: the tunnel stopped answering"
                exit 75
            fi

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
        audit_reason

    else
        NODNS=$((NODNS + 1))
        REASONS="$REASONS nodns"
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
    } > "$TMP" &&

    mv "$TMP" "$STATE" || rm -f "$TMP"

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

# shellcheck disable=SC2086 # one reason a word
REASON_SUM=$(printf '%s\n' $REASONS | sort | uniq -c | sort -rn | awk 'NF == 2 {printf "%s%s:%s", s, $2, $1; s = ","}')
echo "Reasons:     ${REASON_SUM:-none}"
echo "Paused:      ${PAUSED}s (${PAUSES} times)"

echo "$END_TEXT|duration=${ELAPSED}s|targets=$TOTAL|checked=$CHECKED|ok=$OK|fail=$FAIL|unknown=${UNKNOWN_COUNT}|nodns=$NODNS|skipped=$SKIPPED|candidates=$CANDIDATE_COUNT|paused=${PAUSED}s|reasons=${REASON_SUM:-none}" \
    >> "$SUMMARY_LOG"

exit 0
