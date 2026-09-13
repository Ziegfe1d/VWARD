#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

WAN="eth3"
WG="nwg1"

AUDIT="/opt/bin/vward-policy-audit.sh"

STATE_DIR="/opt/var/lib/vward/policy-audit"
LIVE_STATE="/opt/var/lib/vward/route-engine"

CANDIDATES="$STATE_DIR/candidates.txt"

LOG="/opt/var/log/vward-policy-reconcile.log"
EVENT_LOG="/opt/var/log/vward-route-engine-events.log"

LOCK="/tmp/vward-policy-sync.lock"

CFG="/tmp/vpn-reconcile-running.$$"
MEMBERS="/tmp/vpn-reconcile-members.$$"
ROLLBACK="/tmp/vpn-reconcile-rollback.$$"
POSTSAVE="/tmp/vpn-reconcile-postsave.$$"

MAX_AGE=14400
DRY_RUN="${DRY_RUN:-0}"

BACKUP_DIR="/opt/var/backups/vpn-reconcile"

mkdir -p \
    "$STATE_DIR" \
    "$LIVE_STATE" \
    "$BACKUP_DIR"

# ============================================================
# LOCK
# ============================================================

if ! mkdir "$LOCK" 2>/dev/null; then

    OLD="$(cat "$LOCK/pid" 2>/dev/null)"

    if [ -n "$OLD" ] &&
       kill -0 "$OLD" 2>/dev/null; then

        echo "Night audit/reconcile already running PID=$OLD"
        exit 0
    fi

    rm -rf "$LOCK"

    mkdir "$LOCK" || exit 1
fi

echo $$ > "$LOCK/pid"

cleanup()
{
    rm -f \
        "$CFG" \
        "$MEMBERS" \
        "$ROLLBACK" \
        "$POSTSAVE"

    rm -rf "$LOCK"
}

trap cleanup EXIT INT TERM


# ============================================================
# HELPERS
# ============================================================

force_vpn_match()
{
    H=$(echo "$1" | tr 'A-Z' 'a-z')
    F="/opt/etc/vward/route-engine/force-vpn.conf"

    [ -f "$F" ] || return 1

    while IFS= read -r L; do
        D=$(echo "$L" | sed 's/#.*//' | tr 'A-Z' 'a-z' | awk '{print $1}')
        [ -n "$D" ] || continue

        case "$D" in
            \*.*) D="${D#*.}" ;;
        esac

        case "$H" in
            "$D"|*."$D") return 0 ;;
        esac
    done < "$F"

    return 1
}

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

# Keenetic/ndmc can report a semantic CLI error in text even when the
# process exit code is zero. Treat both transport and semantic errors
# as failures before any change is accepted into rollback state.
ndm_cmd()
{
    CMD="$1"

    NDM_LAST_OUT="$(ndmc -c "$CMD" 2>&1)"
    NDM_LAST_RC=$?

    [ "$NDM_LAST_RC" -eq 0 ] || return 1

    printf '%s\n' "$NDM_LAST_OUT" |
    grep -Eqi 'error\[|syntax error|not found|no such entry' &&
        return 1

    return 0
}


# Returns:
#   0 - membership exists
#   1 - membership is absent
#   2 - running-config could not be verified
membership_state()
{
    G="$1"
    H=$(printf '%s\n' "$2" | tr 'A-Z' 'a-z')
    VCFG="/tmp/vpn-reconcile-verify.$$"

    if ! ndmc -c "show running-config" > "$VCFG" 2>/dev/null ||
       [ ! -s "$VCFG" ]; then
        rm -f "$VCFG"
        return 2
    fi

    if group_members "$G" "$VCFG" | grep -Fxq "$H"; then
        rm -f "$VCFG"
        return 0
    fi

    rm -f "$VCFG"
    return 1
}

probe_result()
{
    H="$1"
    IFACE="$2"
    IP="$3"

    OUT=$(
        curl -4 \
          --noproxy '*' \
          --interface "$IFACE" \
          --resolve "$H:443:$IP" \
          --connect-timeout 2 \
          --max-time 3 \
          -A "Mozilla/5.0" \
          -sS \
          -o /dev/null \
          -w '%{http_code}|%{time_total}' \
          "https://$H/" 2>/dev/null
    )

    RC=$?
    CODE=${OUT%%|*}
    TIME=${OUT#*|}

    [ -n "$CODE" ] || CODE="000"
    [ -n "$TIME" ] || TIME="-"

    echo "$RC|$CODE|$TIME"
}


classify_isp_vs_vpn()
{
    H="$1"
    IP="$2"

    IR=$(probe_result "$H" "$WAN" "$IP")

    OLDIFS="$IFS"
    IFS='|'
    set -- $IR
    IRC="$1"
    IC="$2"
    IT="$3"
    IFS="$OLDIFS"

    VC="000"
    VRC="-"
    CLASS="UNKNOWN"
    NEED_VPN=0

    if [ "$IRC" -eq 0 ]; then
        case "$IC" in
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

        VR=$(probe_result "$H" "$WG" "$IP")

        OLDIFS="$IFS"
        IFS='|'
        set -- $VR
        VRC="$1"
        VC="$2"
        VT="$3"
        IFS="$OLDIFS"

        if [ "$IRC" -ne 0 ]; then

            if [ "$VRC" -eq 0 ]; then
                case "$VC" in
                    2??|3??|4??)
                        [ "$VC" = "451" ] || CLASS="ISP_BAD"
                        ;;
                esac
            fi

        else

            case "$IC" in
                451)
                    if [ "$VRC" -eq 0 ] &&
                       [ "$VC" != "451" ]; then
                        case "$VC" in
                            2??|3??|4??) CLASS="ISP_BAD" ;;
                        esac
                    fi
                    ;;

                4??)
                    if [ "$VRC" -eq 0 ] &&
                       [ "$VC" = "$IC" ]; then
                        CLASS="ISP_OK"
                    elif [ "$VRC" -eq 0 ]; then
                        case "$VC" in
                            2??|3??) CLASS="ISP_BAD" ;;
                            *) CLASS="UNKNOWN" ;;
                        esac
                    fi
                    ;;
            esac
        fi
    fi

    echo "$CLASS|$IRC|$IC|$VRC|$VC|$IT"
}


get_threshold()
{
    awk -F= '
    $1=="SUCCESS_THRESHOLD" {
        v=$2
        gsub(/"/,"",v)
        gsub(/[[:space:]]/,"",v)
        print v
        exit
    }
    ' "$AUDIT"
}


# ============================================================
# AUDIT THRESHOLD
# ============================================================

SUCCESS_THRESHOLD="$(get_threshold)"

case "$SUCCESS_THRESHOLD" in
    ''|*[!0-9]*)
        echo "ERROR: invalid SUCCESS_THRESHOLD"
        exit 1
        ;;
esac

if [ "$SUCCESS_THRESHOLD" -lt 2 ]; then
    echo "ERROR: unsafe SUCCESS_THRESHOLD=$SUCCESS_THRESHOLD"
    exit 1
fi


# ============================================================
# RUNNING CONFIG
# ============================================================

if ! ndmc -c "show running-config" > "$CFG" 2>/dev/null ||
   [ ! -s "$CFG" ]; then

    echo "ERROR: cannot read running-config"
    exit 1
fi


# ============================================================
# BUILD CURRENT WIREGUARD1 MEMBERSHIP
#
# Только группы, реально маршрутизируемые через nwg1.
# AdaptiveAuto исключён — у него собственный автомат.
# ============================================================

WG_GROUPS=$(
    awk '
    $1=="route" &&
    $2=="object-group" &&
    $4=="nwg1" &&
    $3!="AdaptiveAuto" {
        print $3
    }
    ' "$CFG" |
    sort -u
)

: > "$MEMBERS"

for G in $WG_GROUPS; do
    group_members "$G" "$CFG" |
    awk -v g="$G" '{
        print g "|" $0
    }' >> "$MEMBERS"
done

sort -u "$MEMBERS" -o "$MEMBERS"


# ============================================================
# START
# ============================================================

NOW="$(date +%s)"

CHECKED=0
CONFIRMED=0

REMOVED_HOSTS=0
REMOVED_MEMBERSHIPS=0

AGH_SKIPPED=0
STALE_SKIPPED=0
THRESHOLD_SKIPPED=0
NOT_MEMBER_SKIPPED=0

ERRORS=0
DIRTY=0

: > "$ROLLBACK"
: > "$POSTSAVE"

echo "===== NIGHT VPN -> ISP RECONCILE ====="
echo "Mode: $([ "$DRY_RUN" = "1" ] && echo DRY-RUN || echo AUTO)"
echo "Threshold: $SUCCESS_THRESHOLD"

if [ ! -s "$CANDIDATES" ]; then

    echo "Candidates: 0"
    echo
    echo "Nothing to reconcile."
    exit 0
fi

echo "Candidates: $(wc -l < "$CANDIDATES")"
echo


# ============================================================
# PROCESS AUDIT CANDIDATES ONLY
# ============================================================

while IFS='|' read -r HOST CAND_GROUP CAND_STREAK CAND_CODE CAND_TIME; do

    if force_vpn_match "$HOST"; then
        echo "PINNED_FORCE_VPN: $HOST"
        continue
    fi

    [ -n "$HOST" ] || continue

    case "$HOST" in
        *'*'*)
            continue
            ;;
    esac

    case "$CAND_STREAK" in
        ''|*[!0-9]*)
            continue
            ;;
    esac

    if [ "$CAND_STREAK" -lt "$SUCCESS_THRESHOLD" ]; then
        THRESHOLD_SKIPPED=$((THRESHOLD_SKIPPED + 1))
        continue
    fi

    SAFE="$(echo "$HOST" | tr '/:*?' '____')"

    STATE="$STATE_DIR/$SAFE.state"

    [ -f "$STATE" ] || continue

    LAST_RESULT="$(
        awk -F= '
        $1=="LAST_RESULT" {
            print $2
            exit
        }
        ' "$STATE"
    )"

    LAST_CHECK="$(
        awk -F= '
        $1=="LAST_CHECK" {
            print $2
            exit
        }
        ' "$STATE"
    )"

    CURRENT_STREAK="$(
        awk -F= '
        $1=="OK_STREAK" {
            print $2
            exit
        }
        ' "$STATE"
    )"

    [ "$LAST_RESULT" = "DIRECT_OK" ] || continue

    case "$LAST_CHECK" in
        ''|*[!0-9]*)
            continue
            ;;
    esac

    case "$CURRENT_STREAK" in
        ''|*[!0-9]*)
            CURRENT_STREAK=0
            ;;
    esac

    if [ "$CURRENT_STREAK" -lt "$SUCCESS_THRESHOLD" ]; then
        THRESHOLD_SKIPPED=$((THRESHOLD_SKIPPED + 1))
        continue
    fi

    AGE=$((NOW - LAST_CHECK))

    if [ "$AGE" -gt "$MAX_AGE" ]; then
        STALE_SKIPPED=$((STALE_SKIPPED + 1))
        continue
    fi

    # --------------------------------------------------------
    # Проверяем, что домен всё ещё реально находится хотя бы
    # в одной nwg1 FQDN-группе.
    # --------------------------------------------------------

    GROUPS=$(
        awk -F'|' -v h="$HOST" '
        $2==h {
            print $1
        }
        ' "$MEMBERS"
    )

    if [ -z "$GROUPS" ]; then
        NOT_MEMBER_SKIPPED=$((NOT_MEMBER_SKIPPED + 1))
        continue
    fi

    CHECKED=$((CHECKED + 1))

    # --------------------------------------------------------
    # Не трогаем домен, если AdGuard блокирует его локально.
    # --------------------------------------------------------

    AGH="$(nslookup "$HOST" 192.168.1.1 2>&1)"

    if echo "$AGH" |
       grep -qE 'Address [0-9]+: (0\.0\.0\.0|::)$'; then

        AGH_SKIPPED=$((AGH_SKIPPED + 1))
        continue
    fi

    # --------------------------------------------------------
    # Независимый DNS + DIRECT ISP probe.
    # --------------------------------------------------------

    IP=$(
        /opt/bin/vward-route-resolve4.sh \
            "$HOST" 2>/dev/null |
        awk '
        /^Address [0-9]+:/ &&
        $3 ~ /^[0-9]+\./ {
            ip=$3
        }
        END {
            print ip
        }
        '
    )

    [ -n "$IP" ] || continue

    CR=$(classify_isp_vs_vpn "$HOST" "$IP")

    OLDIFS="$IFS"
    IFS='|'
    set -- $CR
    CLASS="$1"
    ISP_RC="$2"
    ISP_CODE="$3"
    VPN_RC="$4"
    VPN_CODE="$5"
    ISP_TIME="$6"
    IFS="$OLDIFS"

    case "$CLASS" in
        ISP_OK)
            ;;

        ISP_BAD)
            echo "KEEP_VPN: $HOST | ISP=$ISP_CODE | VPN=$VPN_CODE"
            continue
            ;;

        *)
            echo "UNKNOWN: $HOST | ISP=$ISP_CODE | VPN=$VPN_CODE"
            continue
            ;;
    esac

    CONFIRMED=$((CONFIRMED + 1))

    echo "CONFIRMED_DIRECT: $HOST | streak=$CURRENT_STREAK | ISP=$ISP_CODE | VPN=$VPN_CODE | ${ISP_TIME}s"

    if [ "$DRY_RUN" = "1" ]; then

        for G in $GROUPS; do
            echo "WOULD_REMOVE: $G | $HOST"
        done

        continue
    fi

    # --------------------------------------------------------
    # TRANSACTION PER HOST
    #
    # Удаляем домен из ВСЕХ nwg1-групп, иначе дубль
    # продолжит отправлять его через VPN.
    # --------------------------------------------------------

    HOST_REMOVED="/tmp/vpn-reconcile-host-removed.$$"

    : > "$HOST_REMOVED"

    HOST_ERROR=0

    for G in $GROUPS; do

        if ! ndm_cmd "no object-group fqdn $G include $HOST"; then
            echo "REMOVE_NDM_ERROR: $G | $HOST | $NDM_LAST_OUT"
            HOST_ERROR=1
            break
        fi

        membership_state "$G" "$HOST"
        MEMBER_RC=$?

        if [ "$MEMBER_RC" -eq 1 ]; then
            echo "$G|$HOST" >> "$HOST_REMOVED"
        else
            echo "REMOVE_VERIFY_ERROR: $G | $HOST | state=$MEMBER_RC"
            HOST_ERROR=1
            break
        fi

    done

    # --------------------------------------------------------
    # Если хотя бы одно удаление не получилось —
    # возвращаем только подтверждённо удалённые memberships.
    # --------------------------------------------------------

    if [ "$HOST_ERROR" -ne 0 ]; then

        echo "REMOVE_ERROR: $HOST"
        echo "ROLLBACK_HOST: $HOST"

        HOST_ROLLBACK_ERRORS=0

        while IFS='|' read -r RG RH; do

            [ -n "$RG" ] || continue

            if ndm_cmd "object-group fqdn $RG include $RH"; then
                membership_state "$RG" "$RH"
                MEMBER_RC=$?

                if [ "$MEMBER_RC" -ne 0 ]; then
                    HOST_ROLLBACK_ERRORS=$((HOST_ROLLBACK_ERRORS + 1))
                fi
            else
                HOST_ROLLBACK_ERRORS=$((HOST_ROLLBACK_ERRORS + 1))
            fi

        done < "$HOST_REMOVED"

        rm -f "$HOST_REMOVED"

        [ "$HOST_ROLLBACK_ERRORS" -eq 0 ] ||
            echo "ROLLBACK_HOST_ERRORS=$HOST_ROLLBACK_ERRORS"

        ERRORS=$((ERRORS + 1))
        continue
    fi

    HOST_MEMBERSHIPS="$(
        wc -l < "$HOST_REMOVED"
    )"

    cat "$HOST_REMOVED" >> "$ROLLBACK"

    # Локальный backup только реально изменённых memberships.
    BACKUP_FILE="$BACKUP_DIR/memberships-$(date '+%Y%m%d-%H%M%S')-${SAFE}-$$.txt"

    cp "$HOST_REMOVED" "$BACKUP_FILE"

    rm -f "$HOST_REMOVED"

    REMOVED_HOSTS=$((REMOVED_HOSTS + 1))
    REMOVED_MEMBERSHIPS=$((REMOVED_MEMBERSHIPS + HOST_MEMBERSHIPS))
    DIRTY=1

    echo "$HOST|$HOST_MEMBERSHIPS" >> "$POSTSAVE"

    echo "PENDING_DIRECT: $HOST | memberships=$HOST_MEMBERSHIPS"

done < "$CANDIDATES"


# ============================================================
# SAVE / GLOBAL ROLLBACK
# ============================================================

if [ "$DIRTY" -eq 1 ]; then

    if ndm_cmd "system configuration save"; then

        echo 0 > "$LIVE_STATE/groups-refresh"

        # Конфигурация успешно сохранена.
        # Только теперь публикуем DIRECT-state.
        while IFS='|' read -r PH PM; do

            [ -n "$PH" ] || continue

            PSAFE=$(echo "$PH" | tr '/:*?' '____')
            PLF="$LIVE_STATE/$PSAFE.state"
            PLT="$PLF.tmp.$$"

            {
                echo "HOST=$PH"
                echo "STATUS=DIRECT_OK"
                echo "LAST_CHECK=$(date +%s)"
            } > "$PLT"

            mv "$PLT" "$PLF"

            echo "AUTO_DIRECT: $PH | memberships=$PM"

            echo "$(date '+%Y-%m-%d %H:%M:%S')|$PH|AUTO_DIRECT|memberships=$PM" \
                >> "$LOG"

            echo "$(date '+%Y-%m-%d %H:%M:%S')|AUTO_DIRECT_NIGHT|$PH|memberships=$PM" \
                >> "$EVENT_LOG"

        done < "$POSTSAVE"


    else

        echo "CONFIG_SAVE_ERROR: $NDM_LAST_OUT"
        echo "GLOBAL_ROLLBACK_START"

        ROLLBACK_ERRORS=0

        while IFS='|' read -r G H; do

            [ -n "$G" ] || continue

            if ndm_cmd "object-group fqdn $G include $H"; then
                membership_state "$G" "$H"
                MEMBER_RC=$?

                if [ "$MEMBER_RC" -ne 0 ]; then
                    ROLLBACK_ERRORS=$((ROLLBACK_ERRORS + 1))
                fi
            else
                ROLLBACK_ERRORS=$((ROLLBACK_ERRORS + 1))
            fi

        done < "$ROLLBACK"

        ndm_cmd "system configuration save" || true

        echo 0 > "$LIVE_STATE/groups-refresh"

        echo "GLOBAL_ROLLBACK_ERRORS=$ROLLBACK_ERRORS"

        exit 1
    fi
fi


# ============================================================
# SUMMARY
# ============================================================

echo
echo "===== SUMMARY ====="
echo "Candidates:          $(wc -l < "$CANDIDATES")"
echo "Eligible checked:    $CHECKED"
echo "Confirmed DIRECT:    $CONFIRMED"
echo "Removed hosts:       $REMOVED_HOSTS"
echo "Removed memberships: $REMOVED_MEMBERSHIPS"
echo "AGH skipped:         $AGH_SKIPPED"
echo "Stale skipped:       $STALE_SKIPPED"
echo "Threshold skipped:   $THRESHOLD_SKIPPED"
echo "Not-member skipped:  $NOT_MEMBER_SKIPPED"
echo "Errors:              $ERRORS"
echo "Mode:                $([ "$DRY_RUN" = "1" ] && echo DRY-RUN || echo AUTO)"

if [ "$ERRORS" -gt 0 ]; then
    exit 1
fi

exit 0
