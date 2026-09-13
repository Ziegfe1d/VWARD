#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

GROUP="AdaptiveAuto"
WAN="eth3"
WG="nwg1"
DNS="9.9.9.10"

STATE="/opt/var/lib/vward/route-engine"
LOG="/opt/var/log/vward-route-engine-events.log"

LOCK="/tmp/vward-route-reconciler-maint.lock"
CHANGE="/tmp/vward-route-change.lock"
TARGETS="/tmp/vward-route-reconciler-targets.$$"
CURSOR="$STATE/maint-cursor"
PERSIST="$STATE/adaptive-persist.txt"

HYST_DIR="/opt/var/lib/vward/route-reconciler"
DIRECT_OK_THRESHOLD=3
DIRECT_OK_MIN_INTERVAL=240

MAX_PER_RUN=8

mkdir -p "$STATE"
mkdir -p "$HYST_DIR"

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
    rm -f "$TARGETS"
}
trap cleanup EXIT INT TERM


ndmc -c "show running-config" 2>/dev/null |
sed -n '/^object-group fqdn AdaptiveAuto/,/^!/p' |
awk '$1=="include"{print $2}' |
sort -u > "$TARGETS"

TOTAL=$(wc -l < "$TARGETS")
[ "$TOTAL" -eq 0 ] && {
    echo 1 > "$CURSOR"
    exit 0
}

POS=1
[ -f "$CURSOR" ] && POS=$(cat "$CURSOR" 2>/dev/null)

case "$POS" in
    ''|*[!0-9]*) POS=1 ;;
esac

[ "$POS" -gt "$TOTAL" ] && POS=1

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


probe()
{
    H="$1"
    IFACE="$2"
    IP="$3"

    PR=$(probe_result "$H" "$IFACE" "$IP")

    OLDIFS="$IFS"
    IFS='|'
    set -- $PR
    PRC="$1"
    PCODE="$2"
    IFS="$OLDIFS"

    case "$PRC" in
        ''|*[!0-9]*) return 1 ;;
    esac

    [ "$PRC" -eq 0 ] || return 1
    [ "$PCODE" != "000" ] || return 1
    [ "$PCODE" != "451" ] || return 1

    return 0
}


classify_isp_vs_vpn()
{
    H="$1"
    IP="$2"

    IR=$(probe_result "$H" "$WAN" "$IP")
    VR=$(probe_result "$H" "$WG" "$IP")

    OLDIFS="$IFS"
    IFS='|'
    set -- $IR
    IRC="$1"
    IC="$2"
    IT="$3"
    set -- $VR
    VRC="$1"
    VC="$2"
    VT="$3"
    IFS="$OLDIFS"

    CLASS="UNKNOWN"

    if [ "$IRC" -eq 0 ]; then
        case "$IC" in
            2??|3??)
                CLASS="ISP_OK"
                ;;

            451)
                if [ "$VRC" -eq 0 ]; then
                    case "$VC" in
                        2??|3??|4??)
                            [ "$VC" = "451" ] || CLASS="ISP_BAD"
                            ;;
                    esac
                fi
                ;;

            4??)
                if [ "$VRC" -eq 0 ]; then
                    if [ "$VC" = "$IC" ]; then
                        CLASS="ISP_OK"
                    else
                        case "$VC" in
                            2??|3??) CLASS="ISP_BAD" ;;
                            *)       CLASS="UNKNOWN" ;;
                        esac
                    fi
                fi
                ;;

            5??)
                CLASS="UNKNOWN"
                ;;

            *)
                CLASS="UNKNOWN"
                ;;
        esac

    else
        if [ "$VRC" -eq 0 ]; then
            case "$VC" in
                2??|3??|4??)
                    [ "$VC" = "451" ] || CLASS="ISP_BAD"
                    ;;
            esac
        fi
    fi

    echo "$CLASS|$IRC|$IC|$VRC|$VC"
}

save_state()
{
    H="$1"
    STATUS="$2"

    SAFE=$(echo "$H" | tr '/:*?' '____')
    F="$STATE/$SAFE.state"
    T="$F.tmp.$$"

    {
        echo "HOST=$H"
        echo "STATUS=$STATUS"
        echo "LAST_CHECK=$(date +%s)"
    } > "$T"

    mv "$T" "$F"
}

remove_adaptive()
{
    H="$1"

    if ! mkdir "$CHANGE" 2>/dev/null; then
        OLD=$(cat "$CHANGE/pid" 2>/dev/null)

        if [ -n "$OLD" ] && ! kill -0 "$OLD" 2>/dev/null; then
            rm -rf "$CHANGE"
            mkdir "$CHANGE" || return 1
        else
            return 1
        fi
    fi

    echo $$ > "$CHANGE/pid"
    # FINAL_GUARD_V3_MAINT

    if ! ndmc -c "show running-config" 2>/dev/null |
         sed -n '/^object-group fqdn AdaptiveAuto/,/^!/p' |
         awk '$1=="include"{print $2}' |
         grep -Fxq "$H"; then
        rm -rf "$CHANGE"
        return 0
    fi

    if force_vpn_match "$H"; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_FORCE_VPN|$H" >> "$LOG"
        rm -rf "$CHANGE"
        return 0
    fi

    MIP=$(
        /opt/bin/vward-route-resolve4.sh "$H" 2>/dev/null |
        awk '/^Address [0-9]+:/ &&
             $3 ~ /^[0-9]+\./ {ip=$3}
             END {print ip}'
    )

    if [ -z "$MIP" ]; then
        CLASS="UNKNOWN"
        IRC="-"
        IC="000"
        VRC="-"
        VC="000"
    else
        CR=$(classify_isp_vs_vpn "$H" "$MIP")

        OLDIFS="$IFS"
        IFS='|'
        set -- $CR
        CLASS="$1"
        IRC="$2"
        IC="$3"
        VRC="$4"
        VC="$5"
        IFS="$OLDIFS"
    fi

    case "$CLASS" in
        ISP_OK)
            ;;

        ISP_BAD)
            SAFE_H=$(echo "$H" | tr '/:*?' '____')
            rm -f "$HYST_DIR/$SAFE_H.state"
            save_state "$H" "ADAPTIVE_ISP_BAD"
            echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_ISP_BAD|$H|ISP=$IC|VPN=$VC" >> "$LOG"
            rm -rf "$CHANGE"
            return 0
            ;;

        *)
            SAFE_H=$(echo "$H" | tr '/:*?' '____')
            rm -f "$HYST_DIR/$SAFE_H.state"
            save_state "$H" "ADAPTIVE_ISP_UNKNOWN"
            echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_ISP_UNKNOWN|$H|ISP=$IC|VPN=$VC" >> "$LOG"
            rm -rf "$CHANGE"
            return 0
            ;;
    esac

    # --------------------------------------------------------
    # DIRECT recovery hysteresis:
    # минимум 3 успешные проверки с интервалом >= 240 сек.
    # --------------------------------------------------------

    SAFE_H=$(echo "$H" | tr '/:*?' '____')
    HF="$HYST_DIR/$SAFE_H.state"

    HSTREAK=0
    LAST_OK=0

    if [ -f "$HF" ]; then
        HSTREAK=$(awk -F= '$1=="DIRECT_OK_STREAK"{print $2;exit}' "$HF")
        LAST_OK=$(awk -F= '$1=="LAST_SUCCESS"{print $2;exit}' "$HF")
    fi

    case "$HSTREAK" in
        ''|*[!0-9]*) HSTREAK=0 ;;
    esac

    case "$LAST_OK" in
        ''|*[!0-9]*) LAST_OK=0 ;;
    esac

    NOW_OK=$(date +%s)

    if [ "$LAST_OK" -gt 0 ] &&
       [ $((NOW_OK - LAST_OK)) -lt "$DIRECT_OK_MIN_INTERVAL" ]; then

        echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_DIRECT_CONFIRM_WAIT|$H|streak=$HSTREAK" >> "$LOG"

        rm -rf "$CHANGE"
        return 0
    fi

    if [ "$HSTREAK" -lt "$DIRECT_OK_THRESHOLD" ]; then
        HSTREAK=$((HSTREAK + 1))
    fi

    HTMP="$HF.tmp.$$"

    {
        echo "HOST=$H"
        echo "DIRECT_OK_STREAK=$HSTREAK"
        echo "LAST_SUCCESS=$NOW_OK"
    } > "$HTMP"

    mv "$HTMP" "$HF"

    if [ "$HSTREAK" -lt "$DIRECT_OK_THRESHOLD" ]; then

        save_state "$H" "ADAPTIVE_DIRECT_CONFIRM_$HSTREAK"

        echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_DIRECT_CONFIRM|$H|streak=$HSTREAK/$DIRECT_OK_THRESHOLD" >> "$LOG"

        rm -rf "$CHANGE"
        return 0
    fi

    # --------------------------------------------------------
    # Transactional AdaptiveAuto -> DIRECT
    # --------------------------------------------------------

    if [ ! -f "$PERSIST" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|PERSIST_MISSING_MAINT|$H" >> "$LOG"
        rm -rf "$CHANGE"
        return 1
    fi

    PBACK_DIR="/opt/var/backups/vward/route-reconciler"
    mkdir -p "$PBACK_DIR"

    PBACK="$PBACK_DIR/persist-$(date '+%Y%m%d-%H%M%S')-${SAFE_H}-$$.txt"

    if ! cp -p "$PERSIST" "$PBACK"; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|PERSIST_BACKUP_ERROR|$H" >> "$LOG"
        rm -rf "$CHANGE"
        return 1
    fi

    PTMP="${PERSIST}.new.$$"

    if ! awk -v h="$H" '$0 != h {print}' "$PERSIST" > "$PTMP"; then
        rm -f "$PTMP"
        rm -rf "$CHANGE"
        return 1
    fi

    if ndmc -c \
       "no object-group fqdn $GROUP include $H" \
       >/dev/null 2>&1; then

        if ! ndmc -c \
           "system configuration save" \
           >/dev/null 2>&1; then

            rm -f "$PTMP"

            ROLLBACK_ERROR=0

            ndmc -c \
                "object-group fqdn $GROUP include $H" \
                >/dev/null 2>&1 || ROLLBACK_ERROR=1

            ndmc -c \
                "system configuration save" \
                >/dev/null 2>&1 || ROLLBACK_ERROR=1

            echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_SAVE_ROLLBACK|$H|error=$ROLLBACK_ERROR" >> "$LOG"

            rm -rf "$CHANGE"
            return 1
        fi

        # Конфигурация Keenetic уже успешно сохранена.
        # Теперь коммитим persistent state.
        if ! mv "$PTMP" "$PERSIST"; then

            ndmc -c \
                "object-group fqdn $GROUP include $H" \
                >/dev/null 2>&1 || true

            ndmc -c \
                "system configuration save" \
                >/dev/null 2>&1 || true

            cp -p "$PBACK" "$PERSIST" 2>/dev/null || true

            echo "$(date '+%Y-%m-%d %H:%M:%S')|PERSIST_COMMIT_ROLLBACK|$H" >> "$LOG"

            rm -rf "$CHANGE"
            return 1
        fi

        save_state "$H" "DIRECT_OK"
        rm -f "$HYST_DIR/$SAFE_H.state"
        echo 0 > "$STATE/groups-refresh"

        echo "$(date '+%Y-%m-%d %H:%M:%S')|AUTO_DIRECT_MAINT|$H" >> "$LOG"
        echo "AUTO_DIRECT: $H"

    else

        rm -f "$PTMP"
        echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_REMOVE_ERROR|$H" >> "$LOG"
    fi

    rm -rf "$CHANGE"
}

DONE=0

while [ "$DONE" -lt "$MAX_PER_RUN" ] &&
      [ "$DONE" -lt "$TOTAL" ]; do

    [ "$POS" -gt "$TOTAL" ] && POS=1

    H=$(sed -n "${POS}p" "$TARGETS")

    POS=$((POS + 1))
    DONE=$((DONE + 1))

    [ -z "$H" ] && continue

    AGH=$(nslookup "$H" 192.168.1.1 2>&1)

    if echo "$AGH" |
       grep -qE 'Address [0-9]+: (0\.0\.0\.0|::)$'; then
        save_state "$H" "ADAPTIVE_AGH_BLOCKED"
        continue
    fi

    IP=$(
        /opt/bin/vward-route-resolve4.sh "$H" 2>/dev/null |
        awk '/^Address [0-9]+:/ &&
             $3 ~ /^[0-9]+\./ {ip=$3}
             END {print ip}'
    )

    [ -n "$IP" ] || {
        save_state "$H" "ADAPTIVE_NO_IPV4"
        continue
    }

    # DIRECT должен подтвердиться дважды.
    if probe "$H" "$WAN" "$IP"; then
        sleep 1

        if probe "$H" "$WAN" "$IP"; then
            remove_adaptive "$H"
            continue
        fi
    fi

    # ISP не восстановился — проверяем текущий VPN.
    if probe "$H" "$WG" "$IP"; then
        save_state "$H" "AUTO_VPN"
        echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_VPN_OK|$H" >> "$LOG"
    else
        save_state "$H" "BROKEN"
        echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_BROKEN|$H" >> "$LOG"
    fi

done

[ "$POS" -gt "$TOTAL" ] && POS=1
echo "$POS" > "$CURSOR"

echo "Checked=$DONE Total=$TOTAL Next=$POS"
