#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
# Who acts, for the journals of the programs it asks (one decision, one agent).
VWARD_ACTOR=network-agent
export VWARD_ACTOR


VWARD_PROFILE_LIB=${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}
[ -r "$VWARD_PROFILE_LIB" ] || { echo "VWARD device profile library is unavailable" >&2; exit 1; }
. "$VWARD_PROFILE_LIB"
vward_profile_load || exit 1
VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
[ -r "$VWARD_ADMISSION_LIB" ] || { echo "VWARD runtime admission library is unavailable" >&2; exit 1; }
. "$VWARD_ADMISSION_LIB"
vward_component_gate tunnel-guard
vward_admission_enter tunnel-health || exit $?

# One clock read for the whole run, the quality check and the device map included.
# shellcheck disable=SC2046
set -- $(date '+%s %Y-%m-%d %H:%M:%S')
NOW_EPOCH=$1
NOW_TEXT="$2 $3"
VWARD_NOW=$NOW_EPOCH
export VWARD_NOW

# The tunnels' modules (AmneziaWG, VLESS) are kept running by the components agent.

# Every VPN connection pinged through its own device: the quality table of the Panel and
# the guard's choice of a fallback tunnel. In RAM; a few seconds, all tunnels at once.
[ ! -x /opt/bin/vward-tunnel-quality.sh ] || /opt/bin/vward-tunnel-quality.sh >/dev/null 2>&1 || :

# The health snapshot is rebuilt every minute, so it lives in RAM, not on USB.
DIR="${VWARD_TUNNEL_HEALTH_DIR:-/tmp/vward-tunnel-health}"
STATE="$DIR/state"
RCI_CACHE="$DIR/interface-rci-cache"
LOG="/opt/var/log/vward-tunnel-health.log"
LOCK="/tmp/vward-tunnel-health-watch.lock"

WG_IF="$VWARD_TUNNEL_DEVICE"

# Healthy WG only needs an NDM snapshot periodically.
# Any anomaly forces an immediate refresh.
RCI_REFRESH_INTERVAL=900

[ -d "$DIR" ] || mkdir -p "$DIR"

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


OLD_STATUS="UNKNOWN"
FAIL_COUNT=0
OK_COUNT=0

if [ -f "$STATE" ]; then
    while IFS='=' read -r K V; do
        case "$K" in
            STATUS) OLD_STATUS=$V ;;
            FAIL_COUNT) FAIL_COUNT=$V ;;
            OK_COUNT) OK_COUNT=$V ;;
        esac
    done < "$STATE"
fi

case "$FAIL_COUNT" in
    ''|*[!0-9]*) FAIL_COUNT=0 ;;
esac

case "$OK_COUNT" in
    ''|*[!0-9]*) OK_COUNT=0 ;;
esac


probe()
{
    URL="$1"

    curl --http1.1 -4 -k \
      --noproxy '*' \
      --interface "$WG_IF" \
      --connect-timeout "${VWARD_PROBE_CONNECT:-4}" \
      --max-time "${VWARD_PROBE_MAX:-8}" \
      -sS -o /dev/null \
      "$URL" >/dev/null 2>&1
}




# ------------------------------------------------------------
# LOCAL INTERFACE STATE
# ------------------------------------------------------------

IF_EXISTS=0
CARRIER="unknown"
ADDR=""
FLAGS=""
LOCAL_IF_OK=0

if [ -d "/sys/class/net/$WG_IF" ]; then
    IF_EXISTS=1
    CARRIER=unknown
    [ ! -r "/sys/class/net/$WG_IF/carrier" ] || read -r CARRIER 2>/dev/null < "/sys/class/net/$WG_IF/carrier" || CARRIER=unknown

    # One process a minute instead of five: the address taken apart by the shell, the UP
    # flag read from sysfs (IFF_UP = 1), `ip link` only where sysfs has no flags.
    ADDR=$(ip -4 addr show dev "$WG_IF" 2>/dev/null)
    case "$ADDR" in
        *" inet "*) ADDR=${ADDR#* inet }; ADDR=${ADDR%% *} ;;
        *) ADDR= ;;
    esac

    UP_FLAG=0
    if [ -r "/sys/class/net/$WG_IF/flags" ] && read -r FLAGS 2>/dev/null < "/sys/class/net/$WG_IF/flags"; then
        case "$FLAGS" in 0x*) [ $((FLAGS & 1)) -eq 0 ] || UP_FLAG=1 ;; esac
    else
        case "$(ip link show "$WG_IF" 2>/dev/null)" in *UP*) UP_FLAG=1 ;; esac
    fi

    if [ "$CARRIER" = "1" ] && [ -n "$ADDR" ] && [ "$UP_FLAG" = 1 ]; then
        LOCAL_IF_OK=1
    fi
fi


# ------------------------------------------------------------
# REAL WG TRAFFIC
# ------------------------------------------------------------

P1=0
P2=0

# Through HTTP: whether pages pass needs no TLS, and Entware's OpenSSL 3.5.5 crashes on some
# routers («Illegal instruction», a Viva, 2026-10-11): every check through it said «dead».
probe "http://1.1.1.1/cdn-cgi/trace" && P1=1
probe "http://1.0.0.1/cdn-cgi/trace" && P2=1

NET_OK=0

if [ "$P1" -eq 1 ] || [ "$P2" -eq 1 ]; then
    NET_OK=1
fi


# ------------------------------------------------------------
# CACHED KEENETIC STATE
# ------------------------------------------------------------

CONFIG_STATE="unknown"
LINK_STATE="unknown"
ONLINE_STATE="unknown"
HS=999999
LAST_RCI=0

if [ -f "$RCI_CACHE" ]; then
    while IFS='=' read -r K V; do
        case "$K" in
            CONFIG_STATE) CONFIG_STATE=$V ;;
            LINK_STATE) LINK_STATE=$V ;;
            ONLINE_STATE) ONLINE_STATE=$V ;;
            HANDSHAKE_AGE) HS=$V ;;
            LAST_RCI) LAST_RCI=$V ;;
        esac
    done < "$RCI_CACHE"
fi

[ -n "$CONFIG_STATE" ] || CONFIG_STATE="unknown"
[ -n "$LINK_STATE" ] || LINK_STATE="unknown"
[ -n "$ONLINE_STATE" ] || ONLINE_STATE="unknown"

case "$HS" in
    ''|*[!0-9]*) HS=999999 ;;
esac

case "$LAST_RCI" in
    ''|*[!0-9]*) LAST_RCI=0 ;;
esac

RCI_AGE=$((NOW_EPOCH - LAST_RCI))

case "$RCI_AGE" in
    -*)
        RCI_AGE=999999
        ;;
esac


# ------------------------------------------------------------
# RCI REFRESH POLICY
# ------------------------------------------------------------

NEED_RCI=0

[ "$LAST_RCI" -eq 0 ] && NEED_RCI=1
[ "$RCI_AGE" -ge "$RCI_REFRESH_INTERVAL" ] && NEED_RCI=1

# Any real/local anomaly gets an immediate authoritative snapshot.
[ "$LOCAL_IF_OK" -ne 1 ] && NEED_RCI=1
[ "$NET_OK" -ne 1 ] && NEED_RCI=1
[ "$OLD_STATUS" != "UP" ] && NEED_RCI=1

RCI_REFRESHED=0
RCI_OK=0

if [ "$NEED_RCI" -eq 1 ]; then

    # RCI first: ndmc would add a session line to the router's log every time.
    INFO=$(vward_interface_state "$VWARD_TUNNEL_INTERFACE" 2>/dev/null)

    if [ -n "$INFO" ]; then

        # Four lines, read by the shell.
        CONFIG_STATE= LINK_STATE= ONLINE_STATE= HS=
        { read -r CONFIG_STATE; read -r LINK_STATE; read -r ONLINE_STATE; read -r HS; } <<EOF_INFO
$INFO
EOF_INFO

        [ -n "$CONFIG_STATE" ] || CONFIG_STATE="unknown"
        [ -n "$LINK_STATE" ] || LINK_STATE="unknown"
        [ -n "$ONLINE_STATE" ] || ONLINE_STATE="unknown"

        case "$HS" in
            ''|*[!0-9]*) HS=999999 ;;
        esac

        CTMP="$RCI_CACHE.tmp.$$"

        {
            echo "CONFIG_STATE=$CONFIG_STATE"
            echo "LINK_STATE=$LINK_STATE"
            echo "ONLINE_STATE=$ONLINE_STATE"
            echo "HANDSHAKE_AGE=$HS"
            echo "LAST_RCI=$NOW_EPOCH"
        } > "$CTMP" &&
        mv "$CTMP" "$RCI_CACHE"

        LAST_RCI=$NOW_EPOCH
        RCI_AGE=0
        RCI_REFRESHED=1
        RCI_OK=1
    fi
fi


# ------------------------------------------------------------
# HEALTH DECISION
# ------------------------------------------------------------

IF_OK="$LOCAL_IF_OK"

HS_OK=0
[ "$HS" -le 300 ] && HS_OK=1

# Real traffic remains the primary criterion.
GOOD=0

if [ "$IF_OK" -eq 1 ] &&
   [ "$NET_OK" -eq 1 ]; then
    GOOD=1
fi

# Keenetic must carry it too: an OpkgTun switched off or without link in Keenetic routes nothing,
# while its program (Xray) still answers through the adapter.
if [ "$CONFIG_STATE" = down ] || [ "$LINK_STATE" = down ]; then
    GOOD=0
fi


if [ "$GOOD" -eq 1 ]; then

    FAIL_COUNT=0
    OK_COUNT=$((OK_COUNT + 1))

    if [ "$OLD_STATUS" = "DOWN" ] ||
       [ "$OLD_STATUS" = "RECOVERING" ]; then

        if [ "$OK_COUNT" -ge 2 ]; then
            STATUS="UP"
        else
            STATUS="RECOVERING"
        fi

    else
        STATUS="UP"
    fi

else

    OK_COUNT=0
    FAIL_COUNT=$((FAIL_COUNT + 1))

    if [ "$FAIL_COUNT" -ge 2 ]; then
        STATUS="DOWN"
    else
        STATUS="DEGRADED"
    fi
fi


TMP_STATE="$STATE.tmp.$$"

{
    echo "STATUS=$STATUS"
    echo "LAST_CHECK=$NOW_EPOCH"
    echo "FAIL_COUNT=$FAIL_COUNT"
    echo "OK_COUNT=$OK_COUNT"

    # Kept for the previous tunnel-guard state format.
    echo "CONFIG_STATE=${CONFIG_STATE:-unknown}"
    echo "LINK_STATE=${LINK_STATE:-unknown}"
    echo "ONLINE_STATE=${ONLINE_STATE:-unknown}"

    echo "INTERFACE_OK=$IF_OK"
    echo "LOCAL_IF_EXISTS=$IF_EXISTS"
    echo "LOCAL_CARRIER=$CARRIER"
    echo "LOCAL_ADDRESS=${ADDR:-none}"

    echo "HANDSHAKE_AGE=$HS"
    echo "HANDSHAKE_OK=$HS_OK"

    echo "PROBE_1=$P1"
    echo "PROBE_2=$P2"
    echo "NETWORK_OK=$NET_OK"

    echo "RCI_REFRESHED=$RCI_REFRESHED"
    echo "RCI_OK=$RCI_OK"
    echo "RCI_LAST=$LAST_RCI"
    echo "RCI_AGE=$RCI_AGE"
} > "$TMP_STATE" &&

mv "$TMP_STATE" "$STATE" || rm -f "$TMP_STATE"


if [ "$STATUS" != "$OLD_STATUS" ]; then
    echo "$NOW_TEXT|$OLD_STATUS->$STATUS|if=$IF_OK|hs=$HS|p1=$P1|p2=$P2|rci=$RCI_REFRESHED" \
        >> "$LOG"
fi


# DNS rules of the tunnel after a boot (fix.34.1, r6). 25.10 after a reboot Keenetic's DNS proxy
# took 1 of the 16 «ip name-server <server> <domain> on <tunnel>» lines of the configuration (the
# live ndnproxymain.conf), Instagram did not resolve; «no» and the same line again fixed it. Once
# a boot, the tunnel UP for DNS_RULES_UP_MIN minutes and the router up for 5: every such line of
# the running configuration must be in the live file (its server and domain on one line); the
# missing ones are given again, up to 3 tries a minute apart (none found: «unknown», nothing done). State in RAM (/tmp/vward-dns-rules).
# dns_rules_check=0 in domain-lists.conf turns it off.
dns_rules_check()
{
    DR=${VWARD_DNS_RULES_STATE:-/tmp/vward-dns-rules}
    DR_LOG=${VWARD_DNS_RULES_LOG:-$LOG}
    DR_RESULT='' DR_TRIES=0
    [ ! -r "$DR" ] || while IFS='=' read -r K V; do
        case "$K" in RESULT) DR_RESULT=$V ;; TRIES) DR_TRIES=$V ;; esac
    done < "$DR"
    case "$DR_RESULT" in ok|gave_up|no_live_file|unknown|off) return 0 ;; esac
    case "$DR_TRIES" in ''|*[!0-9]*) DR_TRIES=0 ;; esac
    DR_CONF=${VWARD_DOMAIN_LISTS_CONF:-/opt/etc/vward/route-engine/domain-lists.conf}
    if [ "$(awk -F= '$1 == "dns_rules_check" {print $2; exit}' "$DR_CONF" 2>/dev/null)" = 0 ]; then
        printf 'RESULT=off\n' > "$DR"
        return 0
    fi
    DR_UP=
    read -r DR_UP _ 2>/dev/null < "${VWARD_UPTIME_FILE:-/proc/uptime}" || return 0
    DR_UP=${DR_UP%%.*}
    case "$DR_UP" in ''|*[!0-9]*) return 0 ;; esac
    [ "$DR_UP" -ge "${VWARD_DNS_RULES_DELAY:-300}" ] || return 0

    DR_LIVE=
    for f in ${VWARD_NDNPROXY_CONF:-/var/ndnproxymain.conf /tmp/ndnproxymain.conf}; do
        [ -r "$f" ] && { DR_LIVE=$f; break; }
    done
    if [ -z "$DR_LIVE" ]; then
        # Nothing to compare with: nothing is done (a check that cannot see says so, not «ok»).
        printf 'RESULT=no_live_file\nAT=%s\n' "$NOW_EPOCH" > "$DR"
        echo "$NOW_TEXT|DNS_RULES result=no_live_file" >> "$DR_LOG"
        return 0
    fi
    DR_RUN=$(vward_running_config 2>/dev/null) || return 0
    [ -n "$DR_RUN" ] || return 0
    DR_RULES=$(printf '%s\n' "$DR_RUN" | tr -d '\r' | awk -v t="$VWARD_TUNNEL_INTERFACE" '
        $1 == "ip" && $2 == "name-server" && NF == 6 && $5 == "on" && $6 == t {print $3, tolower($4)}')
    DR_RUN=
    DR_WANT=$(printf '%s\n' "$DR_RULES" | grep -c .)
    DR_MISS=$(printf '%s\n' "$DR_RULES" | awk '
        function tok(l,  a, n, i) {n = split(tolower(l), a, /[^a-z0-9._-]+/); for (i = 1; i <= n; i++) {sub(/[.]+$/, "", a[i]); if (a[i] != "") have[FNR, a[i]] = 1}}
        NR == FNR {if (NF == 2) {srv[++m] = $1; dom[m] = $2}; next}
        {tok($0); lines = FNR}
        END {
            for (r = 1; r <= m; r++) {
                s = srv[r]; sub(/:[0-9]+$/, "", s); found = 0
                for (l = 1; l <= lines && !found; l++) if (have[l, s] && have[l, dom[r]]) found = 1
                if (!found) print srv[r], dom[r]
            }
        }' - "$DR_LIVE")
    DR_MISSN=$(printf '%s\n' "$DR_MISS" | grep -c .)
    DR_LIVEN=$((DR_WANT - DR_MISSN))
    if [ "$DR_MISSN" -eq 0 ]; then
        DR_RES=no
        DR_FIRST=$(printf '%s\n' "$DR_RULES" | awk 'NF == 2 {print $2; exit}')
        if [ -z "$DR_FIRST" ] || "${VWARD_NSLOOKUP:-nslookup}" "$DR_FIRST" 127.0.0.1 2>/dev/null |
            awk '/^Name:/ {n = 1; next} n && /[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+/ {ok = 1} END {exit !ok}'; then
            DR_RES=yes
        fi
        printf 'RESULT=ok\nCONFIG=%s\nLIVE=%s\nTRIES=%s\nRESOLVES=%s\nAT=%s\n' "$DR_WANT" "$DR_LIVEN" "$DR_TRIES" "$DR_RES" "$NOW_EPOCH" > "$DR"
        echo "$NOW_TEXT|DNS_RULES result=ok config=$DR_WANT live=$DR_LIVEN tries=$DR_TRIES resolves=$DR_RES" >> "$DR_LOG"
        return 0
    fi
    if [ "$DR_LIVEN" -eq 0 ]; then
        # Not one rule found: the file may be written otherwise than read here. Nothing is done.
        printf 'RESULT=unknown\nCONFIG=%s\nLIVE=0\nAT=%s\n' "$DR_WANT" "$NOW_EPOCH" > "$DR"
        echo "$NOW_TEXT|DNS_RULES result=unknown config=$DR_WANT live=0 file=$DR_LIVE" >> "$DR_LOG"
        return 0
    fi
    if [ "$DR_TRIES" -ge 3 ]; then
        printf 'RESULT=gave_up\nCONFIG=%s\nLIVE=%s\nTRIES=%s\nAT=%s\n' "$DR_WANT" "$DR_LIVEN" "$DR_TRIES" "$NOW_EPOCH" > "$DR"
        echo "$NOW_TEXT|DNS_RULES result=gave_up config=$DR_WANT live=$DR_LIVEN tries=$DR_TRIES" >> "$DR_LOG"
        return 0
    fi
    DR_FIX=0
    while read -r S D; do
        [ -n "$D" ] || continue
        ndmc -c "no ip name-server $S $D on $VWARD_TUNNEL_INTERFACE" >/dev/null 2>&1
        ndmc -c "ip name-server $S $D on $VWARD_TUNNEL_INTERFACE" >/dev/null 2>&1 && DR_FIX=$((DR_FIX + 1))
    done <<EOF_DR
$DR_MISS
EOF_DR
    command -v vward_keenetic_dirty >/dev/null 2>&1 && vward_keenetic_dirty
    DR_TRIES=$((DR_TRIES + 1))
    printf 'RESULT=reapplied\nCONFIG=%s\nLIVE=%s\nTRIES=%s\nAT=%s\n' "$DR_WANT" "$DR_LIVEN" "$DR_TRIES" "$NOW_EPOCH" > "$DR"
    echo "$NOW_TEXT|DNS_RULES result=mismatch config=$DR_WANT live=$DR_LIVEN reapplied=$DR_FIX try=$DR_TRIES missing=$(printf '%s\n' "$DR_MISS" | awk 'NF == 2 {printf "%s%s", c, $2; c = ","}')" >> "$DR_LOG"
}

# DNS rules of the tunnel after a boot: once the tunnel has been UP a few minutes.
if [ "$STATUS" = UP ] && [ "$OK_COUNT" -ge "${DNS_RULES_UP_MIN:-3}" ] && [ -n "${VWARD_TUNNEL_INTERFACE:-}" ]; then
    dns_rules_check
fi


echo "WG_STATUS=$STATUS"
echo "Interface=$IF_OK Network=$NET_OK HandshakeAge=$HS"
echo "Probe1=$P1 Probe2=$P2"
echo "FailCount=$FAIL_COUNT OkCount=$OK_COUNT"
echo "RCI_Refreshed=$RCI_REFRESHED RCI_Age=$RCI_AGE"

exit 0
