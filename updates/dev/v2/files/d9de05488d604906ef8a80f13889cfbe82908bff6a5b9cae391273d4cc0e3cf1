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
vward_component_gate route-engine
vward_admission_enter route-engine || exit $?

GROUP="AdaptiveAuto"

WAN="$VWARD_WAN_DEVICE"
WG="$VWARD_TUNNEL_DEVICE"
DNS="$VWARD_PROBE_DNS"

STATE_DIR="/opt/var/lib/vward/route-engine"

MANUAL="$STATE_DIR/manual-domains.txt"
ADAPTIVE="$STATE_DIR/adaptive-domains.txt"
PERSIST="$STATE_DIR/adaptive-persist.txt"
REFRESH_TS="$STATE_DIR/groups-refresh"

EVENT_LOG="/opt/var/log/vward-route-engine-events.log"
QUALITY=${VWARD_TUNNEL_QUALITY_BIN:-/opt/bin/vward-tunnel-quality.sh}

LOCK="/tmp/vward-route-engine.lock"
CHANGE_LOCK="/tmp/vward-route-change.lock"
# Present: AdaptiveAuto adds nothing new; domains already in it stay (Panel switch).
ADAPTIVE_DISABLED="${VWARD_ADAPTIVE_DISABLED_FLAG:-/opt/etc/vward/route-engine/adaptive.disabled}"

RAW="/tmp/vward-route-engine-dns.$$"
HOSTS="/tmp/vward-route-engine-hosts.$$"

# Results of ordinary domain checks change every few minutes and are cheap to
# repeat, so they live in RAM. Only AdaptiveAuto decisions stay on USB.
VOLATILE_DIR="${VWARD_ROUTE_VOLATILE_STATE:-/tmp/vward-route-engine-state}"
# Smart DNS (DNS-over-HTTPS bound to domains) answers with a proxy address that
# must stay on the provider: AdaptiveAuto never takes those domains.
SMARTDNS="$VOLATILE_DIR/smartdns-domains.txt"

# Domain lists routed around the tunnel whose watch switch is on (Panel):
# when their service fails on that path, the list is moved into the tunnel
# through the Panel writer, the same way as the manual switch.
LISTS_CONF="${VWARD_DOMAIN_LISTS_CONF:-/opt/etc/vward/route-engine/domain-lists.conf}"
LIST_WATCH_MAP="$VOLATILE_DIR/list-watch.map"
SKIP_DOMAINS="/opt/etc/vward/route-engine/skip-domains.conf"
HINTS="/opt/etc/vward/route-engine/hints.conf"
LIST_WATCH_COOLDOWN=60
LIST_WATCH_FAILS=2
CONSOLE_CONFIG_BIN="${VWARD_CONSOLE_CONFIG_BIN:-/opt/bin/vward-console-config.sh}"

# A name seen again within this many seconds is not handled again: every
# handler has a cooldown of at least a minute.
DEDUP_WINDOW=30

CONNECT_TIMEOUT=2
MAX_TIME=3

# Изменения групп перечитываем максимум раз в минуту.
GROUP_REFRESH=300

# Обычный DIRECT-домен можно перепроверить уже через минуту.
DIRECT_COOLDOWN=60

# Ошибки "не работает нигде" не долбим постоянно.
FAIL_COOLDOWN=300

# Домен в AdaptiveAuto при следующем использовании
# может быть проверен на возврат ISP уже через минуту.
ADAPTIVE_RECHECK=60

TCP_PID=""
AWK_PID=""

# Where the DNS queries are caught.  The queries to the router come in on the LAN bridge;
# «-i any» made tcpdump die with SIGSEGV in libpcap on the router (seen twice after
# reboots and while tunnels came up: 73 and 151 restarts, and the engine's startup check
# failed for want of a live tcpdump).  «any» stays as the second choice, used after
# three quick deaths on the LAN device.
CAP_LAN=${VWARD_LAN_DEVICE:-}
vward_valid_ifname "$CAP_LAN" 2>/dev/null || CAP_LAN=any
CAP_IF=$CAP_LAN
CAP_FAILS=0

# What catches them: vward-dnscap, VWARD's own static program (no libpcap: Entware's
# libpcap 1.10.6 made tcpdump die at every start on MIPS), else tcpdump.  The choices are
# tried in turn after three quick deaths: dnscap and tcpdump on the LAN device, then «any».
DNSCAP=${VWARD_DNSCAP_BIN:-/opt/share/vward/dnscap/vward-dnscap}
SENTINEL_CTL=${VWARD_SENTINEL_CTL:-/opt/bin/vward-sentinel.sh}
DNSCAP_TRY=${VWARD_DNSCAP_TRY:-/tmp/vward-dnscap-install.try}
CAP_N=0
CAP_TOOL=
CAP_LAST=
CAP_HAD_DNSCAP=0

cap_choices()
{
    for CC_IF in "$CAP_LAN" any; do
        [ ! -x "$DNSCAP" ] || echo "dnscap:$CC_IF"
        ! command -v tcpdump >/dev/null 2>&1 || echo "tcpdump:$CC_IF"
        [ "$CAP_LAN" != any ] || break
    done
}

# Sets CAP_TOOL and CAP_IF from choice CAP_N (wrapped); CAP_TOOL is empty with none.
cap_pick()
{
    # shellcheck disable=SC2046
    set -- $(cap_choices)
    CAP_TOOL=
    CAP_HAD_DNSCAP=0
    [ ! -x "$DNSCAP" ] || CAP_HAD_DNSCAP=1
    [ "$#" -gt 0 ] || return 1
    CAP_N=$((CAP_N % $#))
    shift "$CAP_N"
    # Another program or device (vward-dnscap arrived): its own count of quick deaths.
    [ -z "$CAP_LAST" ] || [ "$CAP_LAST" = "$1" ] || CAP_FAILS=0
    CAP_LAST=$1
    CAP_TOOL=${1%%:*}
    CAP_IF=${1#*:}
}

# A capture that keeps dying without vward-dnscap: fetch it in the background (pinned
# SHA-256, the sentinel branch), at most every 10 minutes.
cap_fetch_dnscap()
{
    [ ! -x "$DNSCAP" ] && [ -x "$SENTINEL_CTL" ] || return 0
    CF_NOW=$(date +%s)
    CF_LAST=$(cat "$DNSCAP_TRY" 2>/dev/null)
    case "$CF_LAST" in ''|*[!0-9]*) CF_LAST=0 ;; esac
    [ $((CF_NOW - CF_LAST)) -ge 600 ] || return 0
    echo "$CF_NOW" > "$DNSCAP_TRY" 2>/dev/null
    "$SENTINEL_CTL" install-dnscap </dev/null >/dev/null 2>&1 &
}

mkdir -p "$STATE_DIR" "$VOLATILE_DIR"


# ------------------------------------------------------------
# LOCK
# ------------------------------------------------------------

if ! mkdir "$LOCK" 2>/dev/null; then

    OLD_PID=$(cat "$LOCK/pid" 2>/dev/null)

    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Adaptive Live already running PID=$OLD_PID"
        exit 0
    fi

    rm -rf "${LOCK:?}"
    mkdir "$LOCK" || exit 1
fi

echo $$ > "$LOCK/pid"


cleanup()
{
    [ -n "$TCP_PID" ] && kill "$TCP_PID" 2>/dev/null
    [ -n "$TCP_PID" ] && wait "$TCP_PID" 2>/dev/null
    [ -n "$AWK_PID" ] && kill "$AWK_PID" 2>/dev/null
    classifier_stop 2>/dev/null

    rm -f "$RAW" "$HOSTS"
    rm -rf "${LOCK:?}"
    vward_admission_leave 2>/dev/null || true

    echo "$(date '+%Y-%m-%d %H:%M:%S')|STOP" >> "$EVENT_LOG"
}

trap cleanup EXIT
trap 'exit 1' HUP INT TERM


# ------------------------------------------------------------
# CONFIG SETS
# ------------------------------------------------------------

refresh_sets()
{
    NOW=${QNOW:-$(date +%s)}
    LAST=0

    [ -f "$REFRESH_TS" ] &&
        read -r LAST 2>/dev/null < "$REFRESH_TS"

    case "$LAST" in
        ''|*[!0-9]*) LAST=0 ;;
    esac

    if [ $((NOW - LAST)) -lt "$GROUP_REFRESH" ] &&
       [ -f "$MANUAL" ] &&
       [ -f "$ADAPTIVE" ] &&
       [ -f "$SMARTDNS" ]; then
        return 0
    fi

    CFG="/tmp/vward-route-engine-running.$$"
    ALL="/tmp/vward-route-engine-all.$$"

    if ! vward_running_config > "$CFG" ||
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

    list_watch_map "$CFG" "$ALL"

    mkdir -p "$VOLATILE_DIR" 2>/dev/null
    if [ "$(awk -F= '$1 == "smartdns_guard" {print $2; exit}' "$LISTS_CONF" 2>/dev/null)" = 0 ]; then
        : > "$SMARTDNS"
    else
        # Smart DNS lives in Keenetic (DoH rows) or in AdGuard Home ([/domain/]https://...).
        {
            awk '
                /^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1)}
                ctx && $1 == "https" && $2 == "upstream" && $(NF-1) == "domain" {print tolower($NF)}
            ' "$CFG"
            vward_agh_smartdns_domains
        } | sort -u > "$SMARTDNS"
    fi

    # Unchanged lists are not rewritten on USB.
    for L in "$ADAPTIVE" "$MANUAL"; do
        if cmp -s "$L.new" "$L"; then
            rm -f "$L.new"
        else
            mv "$L.new" "$L"
        fi
    done

    echo "$NOW" > "$REFRESH_TS"

    rm -f "$CFG" "$ALL"
}


is_manual_known()
{
    H="$1"

    [ -f "$MANUAL" ] || return 1

    # Exact name or an explicit "*." wildcard entry.
    awk -v h="$H" '
        $0 == h {
            found=1
            exit
        }

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
    F="/opt/etc/vward/route-engine/skip-domains.conf"

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

# Sets SF_OPT (USB), SF_TMP (RAM) and SF (the copy to read) for a domain.
state_path()
{
    case "$1" in
        *[/:*?]*) SF_NAME=$(echo "$1" | tr '/:*?' '____') ;;
        *) SF_NAME=$1 ;;
    esac

    SF_OPT="$STATE_DIR/$SF_NAME.state"
    SF_TMP="$VOLATILE_DIR/$SF_NAME.state"

    # The newer copy wins: policy reconcile publishes DIRECT_OK on USB.
    if [ -f "$SF_TMP" ] &&
       { [ ! -f "$SF_OPT" ] || [ "$SF_TMP" -nt "$SF_OPT" ]; }; then
        SF=$SF_TMP
    else
        SF=$SF_OPT
    fi
}


# Sets ST_STATUS and ST_LAST from the state of a domain (empty when none).
read_state()
{
    ST_STATUS=""
    ST_LAST=""

    state_path "$1"
    [ -f "$SF" ] || return 1

    while IFS='=' read -r K V; do
        case "$K" in
            STATUS) ST_STATUS=$V ;;
            LAST_CHECK) ST_LAST=$V ;;
        esac
    done < "$SF"

    return 0
}


save_state()
{
    H="$1"
    STATUS="$2"

    state_path "$H"

    case "$STATUS" in
        AUTO_VPN|BROKEN|ADAPTIVE_*)
            STATE=$SF_OPT
            OTHER=$SF_TMP
            ;;
        *)
            STATE=$SF_TMP
            OTHER=$SF_OPT
            ;;
    esac

    TMP="${STATE}.tmp.$$"

    {
        echo "HOST=$H"
        echo "STATUS=$STATUS"
        echo "LAST_CHECK=${QNOW:-$(date +%s)}"
    } > "$TMP" &&

    mv "$TMP" "$STATE" || rm -f "$TMP"

    [ ! -e "$OTHER" ] || rm -f "$OTHER"
}


regular_cooldown()
{
    H="$1"

    # PREV_STATUS: the last result, so that only changes reach the event log.
    read_state "$H" || { PREV_STATUS=""; return 1; }
    PREV_STATUS=$ST_STATUS
    STATUS=$ST_STATUS
    LAST=$ST_LAST

    case "$LAST" in
        ''|*[!0-9]*) return 1 ;;
    esac

    NOW=${QNOW:-$(date +%s)}
    AGE=$((NOW - LAST))

    case "$STATUS" in

        DIRECT_OK)
            [ "$AGE" -lt "$DIRECT_COOLDOWN" ] &&
                return 0
            ;;

        AGH_BLOCKED|NO_IPV4|ISP_FAIL_WG_FAIL|ISP_FAIL_WG_UNSTABLE|ISP_FAIL_ALT_OK)
            [ "$AGE" -lt "$FAIL_COOLDOWN" ] &&
                return 0
            ;;

    esac

    return 1
}


adaptive_due()
{
    H="$1"

    read_state "$H" || return 0
    LAST=$ST_LAST

    case "$LAST" in
        ''|*[!0-9]*) return 0 ;;
    esac

    NOW=${QNOW:-$(date +%s)}
    AGE=$((NOW - LAST))

    [ "$AGE" -ge "$ADAPTIVE_RECHECK" ]
}


# ------------------------------------------------------------
# DNS / NETWORK TEST
# ------------------------------------------------------------

agh_blocked()
{
    H="$1"

    OUT=$(nslookup "$H" $VWARD_DNS_SERVER 2>&1)

    echo "$OUT" |
    grep -qE 'Address [0-9]+: (0\.0\.0\.0|::)$'
}


resolve_ipv4()
{
    /opt/bin/vward-route-resolve4.sh "$1" 2>/dev/null |
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


# alt_tunnel HOST IP: another tunnel of the router that answers (the tunnel quality samples)
# and opens HOST twice; its name. Several tunnels: a site blocked through VWARD's tunnel may
# open through another one - the Panel says which (a list of that tunnel takes it).
alt_tunnel()
{
    [ -x "$QUALITY" ] || return 1
    for AT in $("$QUALITY" summary 2>/dev/null | awk -F '\t' -v w="$WG" '$2 != w && $5 >= 2 && $3 < 100 {print $1 ":" $2}'); do
        AT_NAME=${AT%%:*} AT_DEV=${AT#*:}
        vward_valid_ifname "$AT_DEV" 2>/dev/null || continue
        probe "$1" "$AT_DEV" "$2" || continue
        sleep 1
        probe "$1" "$AT_DEV" "$2" || continue
        echo "$AT_NAME"
        return 0
    done
    return 1
}


# ------------------------------------------------------------
# CHANGE LOCK
# ------------------------------------------------------------

change_lock()
{
    N=0
    NOPID=0

    while ! mkdir "$CHANGE_LOCK" 2>/dev/null; do

        OLD=
        read -r OLD 2>/dev/null < "$CHANGE_LOCK/pid" || :

        if [ -n "$OLD" ] &&
           ! kill -0 "$OLD" 2>/dev/null; then

            rm -rf "${CHANGE_LOCK:?}"
            continue
        fi

        # No pid for 3 s: its holder was killed between mkdir and writing the pid.
        if [ -z "$OLD" ]; then
            NOPID=$((NOPID + 1))
            if [ "$NOPID" -ge 3 ]; then
                rm -rf "${CHANGE_LOCK:?}"
                NOPID=0
                continue
            fi
        else
            NOPID=0
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
    rm -rf "${CHANGE_LOCK:?}"
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


# A name Keenetic takes in "object-group fqdn ... include": lower-case letters,
# digits, dots and inner hyphens, no empty label, at most 253 characters.
# Anything else is refused by the router ("argument parse error").
valid_fqdn()
{
    case "$1" in
        ''|*[!a-z0-9.-]*|.*|*.|*..*|-*|*-|*-.*|*.-*) return 1 ;;
    esac
    [ "${#1}" -le 253 ]
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

    CFG="/tmp/vward-route-restore-cfg.$$"
    CUR="/tmp/vward-route-restore-cur.$$"
    WANT="/tmp/vward-route-restore-want.$$"

    if ! vward_running_config > "$CFG" ||
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
    SKIPPED=0
    FAILS=0

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
            # A saved name the router would refuse is not sent at all.
            if ! valid_fqdn "$H"; then
                SKIPPED=$((SKIPPED + 1))
                continue
            fi
            if OUT=$(ndmc -c "object-group fqdn $GROUP include $H" 2>&1); then
                ADDED=$((ADDED + 1))
            else
                RC=1
                FAILS=$((FAILS + 1))
                # The router's own words for the first few, to know why.
                [ "$FAILS" -gt 3 ] ||
                    echo "$(date '+%Y-%m-%d %H:%M:%S')|PERSIST_RESTORE_FAIL|$H|$(printf '%s' "$OUT" | tr '\n|' '  ' | cut -c1-160)" \
                        >> "$EVENT_LOG"
            fi
        fi
    done < "$WANT"

    rm -f "$CFG" "$CUR" "$WANT"

    echo 0 > "$REFRESH_TS"

    change_unlock

    if [ "$RC" -eq 0 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|PERSIST_RESTORE_OK|added=$ADDED|removed=$REMOVED|skipped=$SKIPPED" \
            >> "$EVENT_LOG"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S')|PERSIST_RESTORE_PARTIAL|added=$ADDED|removed=$REMOVED|skipped=$SKIPPED|failed=$FAILS" \
            >> "$EVENT_LOG"
    fi

    return "$RC"
}

# ADD TO VPN
# ------------------------------------------------------------

add_adaptive()
{
    H="$1"

    if [ -e "$ADAPTIVE_DISABLED" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|ADD_SKIP_ADAPTIVE_OFF|$H" >> "$EVENT_LOG"
        return 0
    fi

    change_lock || return 1
    # FINAL_GUARD_V4_ADD
    echo 0 > "$REFRESH_TS"
    refresh_sets

    if is_manual_known "$H" || parent_list_match "$H" "$MANUAL" || \
       is_special "$H" || parent_list_match "$H" "/opt/etc/vward/route-engine/skip-domains.conf" || \
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

    DIRECT_RC=$P_RC
    DIRECT_CODE=$P_CODE
    DIRECT_TIME=$P_TIME

    if ! probe "$H" "$WG" "$GIP"; then
        save_state "$H" "ISP_FAIL_WG_FAIL"
        echo "$(date '+%Y-%m-%d %H:%M:%S')|ADD_ABORT_WG_FAIL|$H" >> "$EVENT_LOG"
        change_unlock
        return 0
    fi

    VPN_RC=$P_RC
    VPN_CODE=$P_CODE
    VPN_TIME=$P_TIME

    OUT=$(ndmc -c "object-group fqdn $GROUP include $H" 2>&1)
    RC=$?

    if [ "$RC" -eq 0 ]; then


        echo "$H" >> "$ADAPTIVE"
        sort -u "$ADAPTIVE" -o "$ADAPTIVE"

        persist_sync_cache

        echo 0 > "$REFRESH_TS"

        save_state "$H" "AUTO_VPN"

        # Помогаем Keenetic сразу наполнить runtime FQDN IP.
        nslookup "$H" $VWARD_DNS_SERVER >/dev/null 2>&1

        echo "$(date '+%Y-%m-%d %H:%M:%S')|AUTO_VPN|$H|$GROUP|reason=DIRECT_UNAVAILABLE_VPN_OK|ip=$GIP|dns=IPV4_OK|adguard=NOT_BLOCKED|direct_rc=$DIRECT_RC|direct_http=$DIRECT_CODE|direct_time=$DIRECT_TIME|vpn_rc=$VPN_RC|vpn_http=$VPN_CODE|vpn_time=$VPN_TIME" \
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
    # vward-route-reconciler.sh with 3-step hysteresis.
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

# Logs a check result only when it differs from the previous one: a domain
# that stays DIRECT_OK is re-checked every minute and would flood the log.
event_result()
{
    [ "$1" = "$PREV_STATUS" ] && return 0

    echo "$(date '+%Y-%m-%d %H:%M:%S')|$2" >> "$EVENT_LOG"
}


handle_new()
{
    HOST="$1"

    regular_cooldown "$HOST" && return


    if agh_blocked "$HOST"; then

        save_state "$HOST" "AGH_BLOCKED"

        event_result AGH_BLOCKED "AGH_BLOCKED|$HOST"

        return
    fi


    IP=$(resolve_ipv4 "$HOST")

    if [ -z "$IP" ]; then

        save_state "$HOST" "NO_IPV4"

        event_result NO_IPV4 "NO_IPV4|$HOST"

        return
    fi


    # ISP работает -> DIRECT.
    if probe "$HOST" "$WAN" "$IP"; then

        save_state "$HOST" "DIRECT_OK"

        event_result DIRECT_OK "DIRECT_OK|$HOST|$P_CODE|$P_TIME"

        return
    fi


    # Подтверждаем ISP FAIL второй раз.
    sleep 1

    if probe "$HOST" "$WAN" "$IP"; then

        save_state "$HOST" "DIRECT_OK"

        event_result DIRECT_OK "DIRECT_OK_RETRY|$HOST|$P_CODE|$P_TIME"

        return
    fi


    # ISP FAIL x2. Проверяем WG.
    if ! probe "$HOST" "$WG" "$IP"; then

        if ALT=$(alt_tunnel "$HOST" "$IP"); then
            save_state "$HOST" "ISP_FAIL_ALT_OK"
            event_result ISP_FAIL_ALT_OK "ISP_FAIL_ALT_OK|$HOST|tunnel=$ALT"
            return
        fi

        save_state "$HOST" "ISP_FAIL_WG_FAIL"

        event_result ISP_FAIL_WG_FAIL "ISP_FAIL_WG_FAIL|$HOST"

        return
    fi


    # Подтверждаем WG второй раз.
    sleep 1

    if ! probe "$HOST" "$WG" "$IP"; then

        save_state "$HOST" "ISP_FAIL_WG_UNSTABLE"

        event_result ISP_FAIL_WG_UNSTABLE "ISP_FAIL_WG_UNSTABLE|$HOST"

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

# classify_host HOST: one pass over every list a DNS name is checked against.
# A process per list per name was the engine's main CPU cost on the router.
# Prints "W <group>" for a watched list and one tag per list holding the name
# or a parent: M my domains, S Smart DNS, K skip list, H hints.  A "*.name"
# entry covers subdomains only.
classify_host()
{
    # The resident classifier answers in a fraction of a millisecond; the scan below
    # (every list read again for one name) only without it.
    # (Alive first: writing to a FIFO nobody reads would end this shell with SIGPIPE.)
    if [ "${CLS_READY:-0}" = 1 ] && kill -0 "$CLS_PID" 2>/dev/null && printf '%s\n' "$1" >&7 2>/dev/null; then
        # shellcheck disable=SC2086
        while IFS= read $CLS_T -r CLS_LINE <&8; do
            [ "$CLS_LINE" != . ] || return 0
            printf '%s\n' "$CLS_LINE"
        done
        # The classifier is gone: this name by the scan, the next ones after a restart.
        : > "$CLS_DIR/dead" 2>/dev/null
    fi
    classify_scan "$1"
}

classify_scan()
{
    CH_FILES=""
    for CH_F in "$LIST_WATCH_MAP" "$MANUAL" "$SMARTDNS" "$SKIP_DOMAINS" "$HINTS"; do
        [ -s "$CH_F" ] && CH_FILES="$CH_FILES $CH_F"
    done
    [ -n "$CH_FILES" ] || return 0

    # shellcheck disable=SC2086 # paths are VWARD's own, without spaces
    awk -v h="$1" -v w="$LIST_WATCH_MAP" -v m="$MANUAL" -v s="$SMARTDNS" -v k="$SKIP_DOMAINS" '
        FNR == 1 {
            tag = FILENAME == w ? "W" : FILENAME == m ? "M" : FILENAME == s ? "S" : FILENAME == k ? "K" : "H"
        }

        tag in hit { next }

        tag == "W" {
            n = length($1)
            if (h == $1 || (length(h) > n && substr(h, length(h) - n) == "." $1)) {
                hit[tag] = 1
                print "W " $2
            }
            next
        }

        {
            d = tolower($0)
            gsub(/^[ \t]+|[ \t]+$/, "", d)

            if (d == "" || substr(d, 1, 1) == "#")
                next

            sub_only = 0
            if (substr(d, 1, 2) == "*.") {
                d = substr(d, 3)
                sub_only = 1
            }

            if ((!sub_only && h == d) ||
                (length(h) > length(d) && substr(h, length(h) - length(d)) == "." d)) {
                hit[tag] = 1
                print tag
            }
        }
    ' $CH_FILES
}

# Resident classifier: one awk holds every list in memory (a hash per list) and answers
# one name at a time over a FIFO: the tags, then ".". On the router a scan of the lists for
# every new name took a quarter of a CPU core (the hints alone are thousands of lines).
# It is started again when a list changes (a file newer than its stamp) or it died.
CLS_READY=0
CLS_PID=""
# An awk that answers a line as soon as it has it: BusyBox's (the router's own); mawk
# holds its input until a block is full unless it is told it is interactive.
CLS_AWK=awk
if busybox awk 'BEGIN {}' </dev/null >/dev/null 2>&1; then
    CLS_AWK="busybox awk"
elif awk -W interactive 'BEGIN {}' </dev/null >/dev/null 2>&1; then
    CLS_AWK="awk -W interactive"
fi
# A classifier that does not answer within 5 s is treated as dead (read -t where the shell
# has it: BusyBox's does), so the live path never waits on it.
CLS_T=""
(read -t 1 CLS_X < /dev/null) 2>/dev/null
[ "$?" != 1 ] || CLS_T="-t 5"

classifier_stop()
{
    [ "$CLS_READY" = 1 ] && exec 7>&- 8<&-
    [ -z "$CLS_PID" ] || kill "$CLS_PID" 2>/dev/null
    CLS_READY=0
    CLS_PID=""
}

classifier_start()
{
    classifier_stop
    CLS_DIR=${CLS_DIR:-$VOLATILE_DIR/classifier}
    [ -d "$CLS_DIR" ] || mkdir -p "$CLS_DIR" || return 1
    rm -f "$CLS_DIR/req" "$CLS_DIR/resp" "$CLS_DIR/dead"
    mkfifo "$CLS_DIR/req" "$CLS_DIR/resp" || return 1
    : > "$CLS_DIR/stamp"
    # shellcheck disable=SC2086 # CLS_AWK is a command and its options
    $CLS_AWK -v w="$LIST_WATCH_MAP" -v m="$MANUAL" -v s="$SMARTDNS" -v k="$SKIP_DOMAINS" -v hf="$HINTS" '
        function load(f, tag,    line, d, n) {
            n = 0
            while ((getline line < f) > 0) {
                n++
                if (tag == "W") {
                    split(line, x, " ")
                    if (x[1] != "" && !(x[1] in wline)) { wline[x[1]] = n; wgroup[x[1]] = x[2] }
                    continue
                }
                d = tolower(line)
                gsub(/^[ \t]+|[ \t]+$/, "", d)
                if (d == "" || substr(d, 1, 1) == "#") continue
                if (substr(d, 1, 2) == "*.") sub_only[tag, substr(d, 3)] = 1
                else exact[tag, d] = 1
            }
            close(f)
            if (n) have[tag] = 1
        }
        BEGIN {
            load(w, "W"); load(m, "M"); load(s, "S"); load(k, "K"); load(hf, "H")
            print "ready"; fflush()
        }
        {
            h = $1
            # W: the first line (in the file) naming h or one of its parents.
            best = 0; g = ""; t = h
            while (1) {
                if ((t in wline) && (best == 0 || wline[t] < best)) { best = wline[t]; g = wgroup[t] }
                i = index(t, "."); if (!i) break; t = substr(t, i + 1)
            }
            if (best) print "W " g
            split("M S K H", tags, " ")
            for (j = 1; j <= 4; j++) {
                tag = tags[j]
                if (!(tag in have)) continue
                hit = ((tag, h) in exact)
                t = h
                while (!hit && (i = index(t, "."))) {
                    t = substr(t, i + 1)
                    hit = ((tag, t) in exact) || ((tag, t) in sub_only)
                }
                if (hit) print tag
            }
            print "."; fflush()
        }
    ' < "$CLS_DIR/req" > "$CLS_DIR/resp" 2>/dev/null &
    CLS_PID=$!
    exec 7>"$CLS_DIR/req" 8<"$CLS_DIR/resp" || { kill "$CLS_PID" 2>/dev/null; CLS_PID=""; return 1; }
    # shellcheck disable=SC2086
    IFS= read $CLS_T -r CLS_LINE <&8 && [ "$CLS_LINE" = ready ] || { CLS_READY=1; classifier_stop; return 1; }
    CLS_READY=1
}

# classifier_check: started when missing, dead, or older than one of its lists.
classifier_check()
{
    if [ "$CLS_READY" = 1 ] && [ ! -e "$CLS_DIR/dead" ] && kill -0 "$CLS_PID" 2>/dev/null; then
        for CLS_F in "$LIST_WATCH_MAP" "$MANUAL" "$SMARTDNS" "$SKIP_DOMAINS" "$HINTS"; do
            [ ! "$CLS_F" -nt "$CLS_DIR/stamp" ] || { classifier_start; return; }
        done
        return 0
    fi
    classifier_start
}

# ------------------------------------------------------------
# HINT / PRELOAD V5
# ------------------------------------------------------------

hint_direct_fresh()
{
    H="$1"

    read_state "$H" || return 1
    HS=$ST_STATUS
    HL=$ST_LAST

    [ "$HS" = "DIRECT_OK" ] || return 1

    case "$HL" in
        ''|*[!0-9]*) return 1 ;;
    esac

    AGE=$((${QNOW:-$(date +%s)} - HL))

    [ "$AGE" -lt 21600 ]
}


hint_direct_known()
{
    H="$1"

    read_state "$H" || return 1

    [ "$ST_STATUS" = "DIRECT_OK" ]
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

    if [ -e "$ADAPTIVE_DISABLED" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|HINT_SKIP_ADAPTIVE_OFF|$H" >> "$EVENT_LOG"
        return 0
    fi

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
       parent_list_match "$H" "/opt/etc/vward/route-engine/skip-domains.conf" || \
       is_adaptive "$H" || \
       ! parent_list_match "$H" "/opt/etc/vward/route-engine/hints.conf"; then

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

        nslookup "$H" $VWARD_DNS_SERVER >/dev/null 2>&1

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
    # внешний hint является только сигналом к адаптивной проверке.
    # Решение принимает обычный Adaptive Live:
    # ISP FAIL x2 + WG OK x2 -> VPN, иначе DIRECT/наблюдение.
    echo "$(date '+%Y-%m-%d %H:%M:%S')|HINT_ADAPTIVE_CHECK|$HOST" \
        >> "$EVENT_LOG"
    handle_new "$HOST"
}

list_watch_map()
{
    # "domain group" for each watched list whose DNS route avoids the tunnel.
    [ -s "$LISTS_CONF" ] || { rm -f "$LIST_WATCH_MAP"; return 0; }

    awk -F= '$1 ~ /^watch\./ && $2 == "1" {print substr($1, 7)}' "$LISTS_CONF" > "$LIST_WATCH_MAP.watch"

    awk -v tun="$VWARD_TUNNEL_INTERFACE" -v dev="$WG" -v w="$LIST_WATCH_MAP.watch" '
        BEGIN {while ((getline g < w) > 0) watched[g] = 1}
        FILENAME == ARGV[1] {
            if ($0 ~ /^[^ \t!]/) ctx = ($1 == "dns-proxy" && NF == 1)
            if ($0 ~ /^!/) ctx = 0
            if (ctx && $1 == "route" && $2 == "object-group" && ($3 in watched) && $4 != tun && $4 != dev)
                around[$3] = 1
            next
        }
        {split($0, f, "|"); if (f[1] in around) print f[2], f[1]}
    ' "$1" "$2" > "$LIST_WATCH_MAP.new" &&

    mv -f "$LIST_WATCH_MAP.new" "$LIST_WATCH_MAP" || rm -f "$LIST_WATCH_MAP.new"
    rm -f "$LIST_WATCH_MAP.watch"
}


list_watch_check()
{
    # A watched list's service is checked the way the client reaches it: the
    # router's DNS answer (Smart DNS included) through the ISP.  Failure is a
    # dead connection, 451, or a redirect to a region/blocked page; 403 is not,
    # Cloudflare answers it to any script.
    # The group comes from classify_host on the live path.
    if [ "$#" -ge 2 ]; then
        LW_G=$2
    else
        [ -s "$LIST_WATCH_MAP" ] || return 0
        LW_G=$(awk -v h="$1" '{
            n = length($1)
            if (h == $1 || (length(h) > n && substr(h, length(h) - n) == "." $1)) {print $2; exit}
        }' "$LIST_WATCH_MAP")
    fi
    [ -n "$LW_G" ] || return 0

    LW_ST="$VOLATILE_DIR/list-watch.$LW_G"
    LW_NOW=${QNOW:-$(date +%s)}
    LW_LAST=0
    LW_FAILS=0
    [ -f "$LW_ST" ] && read -r LW_LAST LW_FAILS 2>/dev/null < "$LW_ST"
    case "$LW_LAST" in ''|*[!0-9]*) LW_LAST=0 ;; esac
    case "$LW_FAILS" in ''|*[!0-9]*) LW_FAILS=0 ;; esac
    [ $((LW_NOW - LW_LAST)) -ge "$LIST_WATCH_COOLDOWN" ] || return 0

    LW_IP=$(resolve_ipv4 "$1")
    [ -n "$LW_IP" ] || return 0

    LW_OUT=$(
        curl -4 \
            --noproxy '*' \
            --interface "$WAN" \
            --resolve "$1:443:$LW_IP" \
            --connect-timeout "$CONNECT_TIMEOUT" \
            --max-time "$MAX_TIME" \
            -A "Mozilla/5.0" \
            -s \
            -o /dev/null \
            -w '%{http_code} %{redirect_url}' \
            "https://$1/" 2>/dev/null
    )
    LW_CODE=${LW_OUT%% *}
    LW_LOC=${LW_OUT#* }
    [ -n "$LW_CODE" ] || LW_CODE=000

    case "$LW_CODE:$(printf '%s' "$LW_LOC" | tr 'A-Z' 'a-z')" in
        000:*|451:*|*unavailable*|*region*|*restricted*|*not-available*|*blocked*)
            LW_FAILS=$((LW_FAILS + 1))
            ;;
        *)
            echo "$LW_NOW 0" > "$LW_ST"
            return 0
            ;;
    esac

    echo "$LW_NOW $LW_FAILS" > "$LW_ST"
    echo "$(date '+%Y-%m-%d %H:%M:%S')|LIST_BYPASS_FAIL|$1|$LW_G|code=$LW_CODE|location=$LW_LOC|fails=$LW_FAILS" >> "$EVENT_LOG"
    [ "$LW_FAILS" -ge "$LIST_WATCH_FAILS" ] || return 0

    if ! wg_quick_ok; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|LIST_AUTO_VPN_SKIP|$1|$LW_G|reason=WG_DOWN" >> "$EVENT_LOG"
        return 0
    fi

    LW_RES=$("$CONSOLE_CONFIG_BIN" domain-list "$LW_G" vpn 2>/dev/null | tail -n 1)
    echo "$(date '+%Y-%m-%d %H:%M:%S')|LIST_AUTO_VPN|$1|$LW_G|$LW_RES" >> "$EVENT_LOG"
    rm -f "$LW_ST"
    echo 0 > "$REFRESH_TS"
}


handle_host()
{
    case "$1" in
        *[A-Z]*) HOST=$(echo "$1" | tr 'A-Z' 'a-z') ;;
        *) HOST=$1 ;;
    esac
    HOST=${HOST%.}

    [ -z "$HOST" ] && return

    case "$HOST" in
        localhost|*.local|*.lan|*.invalid|*.in-addr.arpa|*.ip6.arpa)
            return
            ;;
    esac

    case "$HOST" in
        *.*) ;;
        *) return ;;
    esac

    # Service names (_dmarc...), odd tcpdump tokens and the like never reach Keenetic.
    valid_fqdn "$HOST" || return




    refresh_sets

    classifier_check
    HOST_LISTS=$(classify_host "$HOST")
    # Tags (M, S, K, H...) and watched lists ("W group") apart, in the shell:
    # three processes less per query.
    HOST_TAGS= HOST_WATCH=
    while IFS= read -r HL_LINE; do
        case "$HL_LINE" in
            "W "*) HOST_WATCH="$HOST_WATCH${HOST_WATCH:+
}${HL_LINE#W }" ;;
            *) HOST_TAGS="$HOST_TAGS$HL_LINE" ;;
        esac
    done <<EOF_LISTS
$HOST_LISTS
EOF_LISTS

    list_watch_check "$HOST" "$HOST_WATCH"


    # Все ручные Keenetic FQDN-группы live-контур не меняет.
    # Smart DNS: адрес прокси общий для всех его доменов, в VPN его не отправляем.
    case "$HOST_TAGS" in
        *M*|*S*) return ;;
    esac

    # AdaptiveAuto обслуживается двусторонне.
    if is_adaptive "$HOST"; then
        handle_adaptive "$HOST"
        return
    fi

    # Aeternia / специальные исключения.
    case "$HOST_TAGS" in
        *K*) return ;;
    esac

    # Hint / Preload V5
    case "$HOST_TAGS" in
        *H*)
            handle_hint "$HOST"
            return
            ;;
    esac

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

    rm -f "$RAW" "$HOSTS"
    mkfifo "$RAW" || exit 1
    mkfifo "$HOSTS" || exit 1


    CAPTURE_FILTER="src net $VWARD_LAN_SUBNET and not src host $VWARD_DNS_SERVER and dst host $VWARD_DNS_SERVER and (udp dst port 53 or tcp dst port 53)"
    read -r CAP_UP _ < "${VWARD_UPTIME_FILE:-/proc/uptime}"; CAP_T0=${CAP_UP%.*}
    cap_pick
    case "$CAP_TOOL" in
        dnscap)
            "$DNSCAP" "$CAP_IF" "$VWARD_LAN_SUBNET" "$VWARD_DNS_SERVER" > "$RAW" 2>/dev/null & ;;
        tcpdump)
            tcpdump -ni "$CAP_IF" -l -vv \
                "$CAPTURE_FILTER" \
                > "$RAW" 2>/dev/null & ;;
        *)
            # Nothing to capture with: the reader still needs its writer to end.
            : > "$RAW" & ;;
    esac

    TCP_PID=$!


    # One awk for the whole capture: takes the query name from each line and
    # drops names already handled within DEDUP_WINDOW seconds, so a DNS query
    # costs no process of its own.  The query's time comes along (QNOW): the
    # checks of the query use it instead of starting date each.
    awk -v window="$DEDUP_WINDOW" '
        {
            now=systime()

            for (i=1; i<NF; i++) {

                if ($i=="A?" ||
                    $i=="AAAA?" ||
                    $i=="HTTPS?") {

                    h=tolower($(i+1))
                    sub(/\.$/,"",h)

                    if (h!="" && (!(h in seen) || now-seen[h]>=window)) {
                        seen[h]=now
                        print h, now
                        fflush()
                    }

                    break
                }
            }

            if (++lines % 2000 == 0)
                for (k in seen)
                    if (now-seen[k]>=window)
                        delete seen[k]
        }
    ' < "$RAW" > "$HOSTS" &

    AWK_PID=$!


    while IFS=' ' read -r HOST QNOW; do

        case "$QNOW" in ''|*[!0-9]*) QNOW= ;; esac
        [ -n "$HOST" ] &&
            handle_host "$HOST"

    done < "$HOSTS"


    wait "$TCP_PID" 2>/dev/null
    TCP_PID=""
    wait "$AWK_PID" 2>/dev/null
    AWK_PID=""

    rm -f "$RAW" "$HOSTS"

    # A capture that lived under 10 s is a quick death: the pause grows (2, 4, 8 ... 60 s)
    # instead of a restart every 2 s, and the second interface is tried after three.
    read -r CAP_UP _ < "${VWARD_UPTIME_FILE:-/proc/uptime}"
    if [ $((${CAP_UP%.*} - CAP_T0)) -lt 10 ]; then
        CAP_FAILS=$((CAP_FAILS + 1))
        cap_fetch_dnscap
        if [ "$CAP_FAILS" -ge 3 ]; then
            CAP_N=$((CAP_N + 1))
            CAP_FAILS=0
        fi
    else
        CAP_FAILS=0
    fi
    CAP_PAUSE=2
    [ "$CAP_FAILS" -gt 0 ] && CAP_PAUSE=$((2 << CAP_FAILS))
    [ "$CAP_PAUSE" -le 60 ] || CAP_PAUSE=60
    # vward-dnscap just arrived: it is the first choice, at once.
    [ "$CAP_HAD_DNSCAP" = 1 ] || [ ! -x "$DNSCAP" ] || { CAP_N=0; CAP_FAILS=0; CAP_PAUSE=1; }

    echo "$(date '+%Y-%m-%d %H:%M:%S')|TCPDUMP_RESTART|if=$CAP_IF|quick=$CAP_FAILS|tool=${CAP_TOOL:-none}" \
        >> "$EVENT_LOG"

    sleep "$CAP_PAUSE"

done
