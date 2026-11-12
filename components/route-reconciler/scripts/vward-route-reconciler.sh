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
vward_component_gate route-reconciler
# Autopodbor in Go takes names out of AdaptiveAuto itself (owner 11.11.2026): one writer.
if command -v vward_core_adaptive_pid >/dev/null 2>&1 && vward_core_adaptive_pid >/dev/null; then
    echo "Autopodbor in Go runs: it reconciles AdaptiveAuto itself"
    exit 0
fi
# fix.33.2 (WP-C): started by cron, 35 s after the minute's agents; upkeep waits while Keenetic
# answers slowly (at most 30 minutes in a row).
command -v vward_spread >/dev/null 2>&1 && vward_spread "${VWARD_RECONCILER_SPREAD:-35}"
if command -v vward_keenetic_busy >/dev/null 2>&1 && vward_defer route-reconciler 1800 vward_keenetic_busy; then
    echo "Deferred: the router is busy"
    exit 0
fi
vward_admission_enter route-reconciler || exit $?

GROUP="AdaptiveAuto"
WAN="$VWARD_WAN_DEVICE"
WG="$VWARD_TUNNEL_DEVICE"
DNS="$VWARD_PROBE_DNS"

STATE="/opt/var/lib/vward/route-engine"
LOG="/opt/var/log/vward-route-engine-events.log"

LOCK="/tmp/vward-route-reconciler-maint.lock"
CHANGE="/tmp/vward-route-change.lock"
TARGETS="/tmp/vward-route-reconciler-targets.$$"
CURSOR="$STATE/maint-cursor"
PERSIST="$STATE/adaptive-persist.txt"
# Names removed since Keenetic last saved its configuration; the last save of this script.
CONFIG_DIRTY="$STATE/keenetic-config.dirty"
CONFIG_SAVED="$STATE/keenetic-config.saved"
CONFIG_SAVE_EVERY_MIN=${VWARD_RECONCILER_SAVE_EVERY_MIN:-60}

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

    rm -rf "${LOCK:?}"
    mkdir "$LOCK" || exit 1
fi

echo $$ > "$LOCK/pid"

cleanup()
{
    # The shared HTTPS turn this run holds (probe_run), before anything else.
    ! command -v rc_turn_give >/dev/null 2>&1 || rc_turn_give
    rm -rf "${LOCK:?}"
    rm -f "$TARGETS"
    vward_admission_leave 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM


# One look at Keenetic's configuration a run (fix.33.2, WP-C): the copy the agents share
# (vward_keenetic_config), read fresh only when there is none; the check before each removal
# takes the same list. Keenetic is asked again only when a removal is refused (the name may be
# gone meanwhile). VWARD_RECONCILER_ONE_LOOK=0: a fresh read each time, as before.
adaptive_names()
{
    # The groups through RCI when proven (owner 08.11): a fresh read every time, 0.1 s instead of a
    # whole configuration; otherwise as before.
    if [ "${VWARD_RECONCILER_ONE_LOOK:-1}" = 1 ] && command -v vward_keenetic_part >/dev/null 2>&1 &&
       AN_CFG=$(vward_keenetic_part groups) && [ -n "$AN_CFG" ]; then
        :
    elif [ "${VWARD_RECONCILER_ONE_LOOK:-1}" = 1 ] && [ "${1:-}" != fresh ] &&
       command -v vward_keenetic_config >/dev/null 2>&1; then
        AN_CFG=$(vward_keenetic_config) && [ -n "$AN_CFG" ] ||
            AN_CFG=$(vward_running_config) || return 1
    else
        AN_CFG=$(vward_running_config) || return 1
    fi
    [ -n "$AN_CFG" ] || return 1
    # A successful transport may still return an error instead of configuration.
    printf '%s\n' "$AN_CFG" | awk '
        /^[[:space:]]*(Command::|[Ee][Rr][Rr][Oo][Rr][: ]|[Ff]ailed[: ])/ {bad=1}
        /^(object-group fqdn |dns-proxy$|interface |ip |system$)/ {seen=1}
        END {exit bad || !seen}' || return 1
    printf '%s\n' "$AN_CFG" |
    sed -n '/^object-group fqdn AdaptiveAuto/,/^!/p' |
    awk '$1=="include"{print $2}' |
    sort -u
    AN_CFG=
}

adaptive_names > "$TARGETS" || { echo "CONFIG_UNKNOWN: reconciliation skipped"; exit 1; }

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

    # One process for the whole list (it was sed|tr|awk per line: 18 processes for 6 lines).
    # A line: its first word before «#», any case; «*.example» is example and its subdomains.
    FVM_H=$H awk '
        BEGIN { h = ENVIRON["FVM_H"] }
        {
            sub(/#.*/, "")
            d = tolower($1)
            if (d == "") next
            if (substr(d, 1, 2) == "*.") d = substr(d, 3)
            if (h == d || (length(h) > length(d) && substr(h, length(h) - length(d)) == "." d)) { found = 1; exit }
        }
        END { exit !found }
    ' "$F"
}

# The shared HTTPS turn (vward_tls_take, P0-1) is taken once and kept across the checks of a
# run (CI #814: take/done around each of the 5 checks cost 82 processes, budget 64), in THIS
# shell - never in a $(...) subshell, which would hold it under its own short-lived PID.
# A check starts on the held turn only while it still ends within RC_TURN_HOLD (10) seconds of
# the take (held + a check's 3 s limit). A download (vward_fetch: updater, lists) waits 20 s for
# the turn, so it always gets it; a site check of the route engine waits 5 s when curl works and
# may get «could not check» (UNKNOWN: no state, tried again in 60 s) - as before, when this run
# took the turn again at once after each check. Past the limit the turn is given back and taken
# again only a second later (a waiter tries once a second, so it gets the turn first: nobody
# starves). Not held while nothing uses it: given back at the start of each name (before its
# name lookups), after a removal's checks (before ndmc), before vward_isp_control (it takes its
# own) and at the end of the run (cleanup). A removal's two checks run in $(...) children of
# this shell: they use its turn (curl in a descendant of the owner), never give it back
# (RC_BORROW) and run no curl once a crash is noted (a broken curl crashes once).
RC_TURN=0 RC_TURN_T0= RC_TURN_RC=0 RC_NOW= RC_BORROW=0
RC_TURN_HOLD=${VWARD_RECONCILER_TURN_HOLD:-10}
case "$RC_TURN_HOLD" in ''|*[!0-9]*) RC_TURN_HOLD=10 ;; esac

# rc_now: RC_NOW = seconds since boot in hundredths, no process; empty when unreadable (then
# nothing is held: every check takes and gives back the turn, as before).
rc_now()
{
    RC_NOW=
    read -r rc_up _ 2>/dev/null < "${VWARD_UPTIME_FILE:-/proc/uptime}" || return 1
    case "$rc_up" in [0-9]*.[0-9][0-9]) ;; *) return 1 ;; esac
    RC_NOW=${rc_up%.*}${rc_up#*.}
    case "$RC_NOW" in *[!0-9]*) RC_NOW=; return 1 ;; esac
    # No leading zero: «0.05» would read as octal in $((...)).
    while :; do case "$RC_NOW" in 0?*) RC_NOW=${RC_NOW#0} ;; *) break ;; esac; done
}

# rc_broken: a crash of curl noted within the hour (find only for a flag that exists: no
# process on the healthy path; an old flag left in /tmp does not count).
rc_broken()
{
    [ -e "${VWARD_TLS_BROKEN_FLAG:-/tmp/vward-curl-tls.broken}" ] && vward_https_broken
}

# rc_turn_fits [N]: N more checks (3 s each, 1 by default) on the held turn still end within
# RC_TURN_HOLD; a crash noted meanwhile (by a borrowing child) - never.
rc_turn_fits()
{
    rc_broken && return 1
    rc_now || return 1
    case "$RC_TURN_T0" in ''|*[!0-9]*) return 1 ;; esac
    [ "$RC_NOW" -ge "$RC_TURN_T0" ] || return 1
    [ $((RC_NOW - RC_TURN_T0 + 300 * ${1:-1})) -le $((RC_TURN_HOLD * 100)) ]
}

# rc_turn_give: the turn given back (only ours, by vward_tls_done) with the last curl result.
rc_turn_give()
{
    [ "$RC_TURN" = 1 ] || return 0
    RC_TURN=0
    # A child's crash under this turn (its code never reaches here): no «works» note over it.
    ! rc_broken || RC_TURN_RC=143
    vward_tls_done "$RC_TURN_RC"
}

# rc_turn_check [N]: before N checks of a removal - a turn held past the limit is given back
# now, and a second passes before anyone here asks again (a waiter gets it first).
rc_turn_check()
{
    [ "$RC_TURN" = 1 ] || return 0
    rc_turn_fits "${1:-1}" && return 0
    rc_turn_give
    sleep 1
}

# rc_turn_name: the start of a name - the turn is given back before its name lookups (a slow
# DNS is no reason to keep others waiting); past the limit a second passes as above.
rc_turn_name()
{
    [ "$RC_TURN" = 1 ] || return 0
    if rc_turn_fits; then
        rc_turn_give
    else
        rc_turn_give
        sleep 1
    fi
}

# probe_run HOST IFACE IP: PRC|PCODE|PTIME of one check, in this shell. PRC 2 with PCODE 000:
# the check did not run (curl broken within the hour, the turn not given).
probe_run()
{
    H="$1"
    IFACE="$2"
    IP="$3"
    PRC=2 PCODE=000 PTIME=-

    # A turn held past the limit is given back first; after that the next take waits a second
    # (a waiter tries once a second: it gets the turn first). A borrowing child (probe_result
    # under a held turn) only runs its curl: the owner judges the time and gives it back.
    if [ "$RC_BORROW" = 1 ]; then
        ! rc_broken || return 0
    elif [ "$RC_TURN" = 1 ] && ! rc_turn_fits; then
        rc_turn_give
        sleep 1
    fi
    # curl crashed on HTTPS within the hour (Entware's OpenSSL 3.5.5 on some MIPS routers):
    # «could not check», and no crash again (the router emulator's broken environment, fix.24).
    # vward_tls_take refuses such a curl itself (1, no process while no crash was ever noted)
    # and gives no turn within its wait (2): could not check either way.
    if [ "$RC_TURN" != 1 ]; then
        if command -v vward_tls_take >/dev/null 2>&1; then
            vward_tls_take || return 0
            RC_TURN=1 RC_TURN_RC=0
            rc_now || :
            RC_TURN_T0=$RC_NOW
        elif vward_https_broken; then
            return 0
        fi
    fi

    OUT=$(
        curl --http1.1 -4 \
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

    PRC=$?
    RC_TURN_RC=$PRC
    # A crash (a signal of curl's own fault) is noted for an hour, as vward_fetch does, and the
    # turn is given back at once (vward_tls_done notes it).
    case "$PRC" in
        132|134|135|136|139)
            if [ "$RC_TURN" = 1 ] && [ "$RC_BORROW" != 1 ]; then RC_TURN=0; vward_tls_done "$PRC"
            else : > "${VWARD_TLS_BROKEN_FLAG:-/tmp/vward-curl-tls.broken}" 2>/dev/null; fi ;;
    esac
    PCODE=${OUT%%|*}
    PTIME=${OUT#*|}

    [ -n "$PCODE" ] || PCODE="000"
    [ -n "$PTIME" ] || PTIME="-"
    return 0
}

# probe_result HOST IFACE IP: «RC|CODE|TIME» of one check, for $(...) callers. Under a turn
# this run holds the child borrows it (never gives it back); otherwise it takes its own and gives
# it back before it ends - a child never leaves a turn behind under its own PID.
probe_result()
{
    [ "$RC_TURN" != 1 ] || RC_BORROW=1
    probe_run "$@"
    [ "$RC_BORROW" = 1 ] || rc_turn_give
    echo "$PRC|$PCODE|$PTIME"
}


# probe HOST IFACE IP: 0 - the site answered; 1 - the check ran and failed; 2 - it did not run
# or its end says nothing about the site (P0-2: never a failure state). PROBE_RC = the same.
probe()
{
    probe_run "$1" "$2" "$3"
    PROBE_RC=2
    isp_check_ran "$PRC" || return 2
    PROBE_RC=1
    [ "$PRC" -eq 0 ] || return 1
    [ "$PCODE" != "000" ] || return 1
    [ "$PCODE" != "451" ] || return 1
    PROBE_RC=0
    return 0
}


# isp_check_ran RC: curl's exit code is a result about the network (as the route engine's probe_ran).
isp_check_ran()
{
    case "$1" in ''|*[!0-9]*|2|27|43|126|127) return 1 ;; esac
    [ "$1" -lt 128 ]
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
            # 400/401/403/404: the server itself answered - the site is reachable directly
            # (owner 02.11: 403 is a real answer, not a reason for the VPN).
            2??|3??|400|401|403|404)
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

    elif isp_check_ran "$IRC"; then
        # The direct check ran and failed (P0-2): only then is it ISP_BAD. Not run, crashed or
        # stopped from outside (2, 27, 43, 126/127, 128 and up) stays UNKNOWN.
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

# safe_name NAME: SAFE_NAME = NAME with / : * ? as _ (a file name). A plain name needs no
# process (echo|tr only for a name with one of them, or a backslash echo may read).
safe_name()
{
    case "$1" in
        *[/:*?\\]*) SAFE_NAME=$(echo "$1" | tr '/:*?' '____') ;;
        *) SAFE_NAME=$1 ;;
    esac
}

save_state()
{
    H="$1"
    STATUS="$2"

    safe_name "$H"
    SAFE=$SAFE_NAME
    F="$STATE/$SAFE.state"
    T="$F.tmp.$$"

    {
        echo "HOST=$H"
        echo "STATUS=$STATUS"
        echo "LAST_CHECK=$(date +%s)"
    } > "$T" &&

    mv "$T" "$F" || rm -f "$T"
}

remove_adaptive()
{
    H="$1"

    vward_lock_take "$CHANGE" || return 1
    # FINAL_GUARD_V3_MAINT

    if { [ "${VWARD_RECONCILER_ONE_LOOK:-1}" = 1 ] && ! grep -Fxq "$H" "$TARGETS"; } ||
       { [ "${VWARD_RECONCILER_ONE_LOOK:-1}" != 1 ] && AN_CHECK=$(adaptive_names fresh) && ! printf '%s\n' "$AN_CHECK" | grep -Fxq "$H"; }; then
        vward_lock_release "$CHANGE"
        return 0
    fi

    if force_vpn_match "$H"; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_FORCE_VPN|$H" >> "$LOG"
        vward_lock_release "$CHANGE"
        return 0
    fi

    # The address the direct checks just used (the loop resolved it a moment ago); resolved
    # here only when not given.
    MIP=${2:-}
    [ -n "$MIP" ] || MIP=$(
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
        # Its two checks run in $(...) children: on this run's turn while both fit within the
        # limit, otherwise the turn is given back first and each child takes and gives its own.
        rc_turn_check 2
        CR=$(classify_isp_vs_vpn "$H" "$MIP")
        # Router changes follow: the turn is not held during them.
        rc_turn_give

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
            safe_name "$H"; SAFE_H=$SAFE_NAME
            rm -f "$HYST_DIR/$SAFE_H.state"
            save_state "$H" "ADAPTIVE_ISP_BAD"
            echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_ISP_BAD|$H|ISP=$IC|VPN=$VC" >> "$LOG"
            vward_lock_release "$CHANGE"
            return 0
            ;;

        *)
            safe_name "$H"; SAFE_H=$SAFE_NAME
            rm -f "$HYST_DIR/$SAFE_H.state"
            save_state "$H" "ADAPTIVE_ISP_UNKNOWN"
            echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_ISP_UNKNOWN|$H|ISP=$IC|VPN=$VC" >> "$LOG"
            vward_lock_release "$CHANGE"
            return 0
            ;;
    esac

    # --------------------------------------------------------
    # DIRECT recovery hysteresis:
    # минимум 3 успешные проверки с интервалом >= 240 сек.
    # --------------------------------------------------------

    safe_name "$H"; SAFE_H=$SAFE_NAME
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

        vward_lock_release "$CHANGE"
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
    } > "$HTMP" &&

    mv "$HTMP" "$HF" || rm -f "$HTMP"

    if [ "$HSTREAK" -lt "$DIRECT_OK_THRESHOLD" ]; then

        save_state "$H" "ADAPTIVE_DIRECT_CONFIRM_$HSTREAK"

        echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_DIRECT_CONFIRM|$H|streak=$HSTREAK/$DIRECT_OK_THRESHOLD" >> "$LOG"

        vward_lock_release "$CHANGE"
        return 0
    fi

    # --------------------------------------------------------
    # Transactional AdaptiveAuto -> DIRECT
    # --------------------------------------------------------

    if [ ! -f "$PERSIST" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|PERSIST_MISSING_MAINT|$H" >> "$LOG"
        vward_lock_release "$CHANGE"
        return 1
    fi

    PBACK_DIR="/opt/var/backups/vward/route-reconciler"
    mkdir -p "$PBACK_DIR"

    PBACK="$PBACK_DIR/persist-$(date '+%Y%m%d-%H%M%S')-${SAFE_H}-$$.txt"

    if ! cp -p "$PERSIST" "$PBACK"; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|PERSIST_BACKUP_ERROR|$H" >> "$LOG"
        vward_lock_release "$CHANGE"
        return 1
    fi

    PTMP="${PERSIST}.new.$$"

    if ! awk -v h="$H" '$0 != h {print}' "$PERSIST" > "$PTMP"; then
        rm -f "$PTMP"
        vward_lock_release "$CHANGE"
        return 1
    fi

    if ndmc -c \
       "no object-group fqdn $GROUP include $H" \
       >/dev/null 2>&1; then

        # The USB list is what the route engine restores at every start, so it is the record:
        # committed now. Keenetic's own saved configuration follows at most once an hour (end of
        # the run) - a save per removed name was 20-27 flash writes an hour on a Viva (13.10).
        if ! mv "$PTMP" "$PERSIST"; then

            ndmc -c \
                "object-group fqdn $GROUP include $H" \
                >/dev/null 2>&1 || true

            cp -p "$PBACK" "$PERSIST" 2>/dev/null || true

            echo "$(date '+%Y-%m-%d %H:%M:%S')|PERSIST_COMMIT_ROLLBACK|$H" >> "$LOG"

            vward_lock_release "$CHANGE"
            return 1
        fi

        : > "$CONFIG_DIRTY"

        save_state "$H" "DIRECT_OK"
        rm -f "$HYST_DIR/$SAFE_H.state"
        echo 0 > "$STATE/groups-refresh"

        echo "$(date '+%Y-%m-%d %H:%M:%S')|AUTO_DIRECT_MAINT|$H" >> "$LOG"
        echo "AUTO_DIRECT: $H"

    elif [ "${VWARD_RECONCILER_ONE_LOOK:-1}" = 1 ] && AN_CHECK=$(adaptive_names fresh) && ! printf '%s\n' "$AN_CHECK" | grep -Fxq "$H"; then

        # Refused because the name is already gone (removed after this run looked): done.
        if ! mv "$PTMP" "$PERSIST" 2>/dev/null; then
            rm -f "$PTMP"
            echo "$(date '+%Y-%m-%d %H:%M:%S')|PERSIST_COMMIT_ERROR|$H" >> "$LOG"
            vward_lock_release "$CHANGE"
            return 1
        fi
        save_state "$H" "DIRECT_OK"
        rm -f "$HYST_DIR/$SAFE_H.state"
        echo "$(date '+%Y-%m-%d %H:%M:%S')|AUTO_DIRECT_MAINT|$H|already_gone" >> "$LOG"

    else

        rm -f "$PTMP"
        echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_REMOVE_ERROR|$H" >> "$LOG"
    fi

    vward_lock_release "$CHANGE"
}

# The default tunnel not in service (the agent VPN says DOWN, or its device is gone): a site that
# does not open directly cannot be judged through it, so it is neither checked nor marked broken
# (Viva 2026-10-18: 167 «MAINT_BROKEN» through the dead OpkgTun2 in one evening).
TUN_DOWN=0
TUN_HEALTH=${VWARD_TUNNEL_HEALTH_STATE:-/tmp/vward-tunnel-health/state}
[ ! -r "$TUN_HEALTH" ] || [ "$(sed -n 's/^STATUS=//p' "$TUN_HEALTH" | head -n 1)" != DOWN ] || TUN_DOWN=1
[ -z "$WG" ] || [ ! -d "${VWARD_SYSFS_NET:-/sys/class/net}/lo" ] || [ -d "${VWARD_SYSFS_NET:-/sys/class/net}/$WG" ] || TUN_DOWN=1
TUN_SKIPPED=0

DONE=0

while [ "$DONE" -lt "$MAX_PER_RUN" ] &&
      [ "$DONE" -lt "$TOTAL" ]; do

    [ "$POS" -gt "$TOTAL" ] && POS=1

    H=$(sed -n "${POS}p" "$TARGETS")

    POS=$((POS + 1))
    DONE=$((DONE + 1))

    [ -z "$H" ] && continue
    rc_turn_name

    AGH=$(nslookup "$H" $VWARD_DNS_SERVER 2>&1)

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
            remove_adaptive "$H" "$IP"
            continue
        fi
    fi

    # The direct check did not run (the turn not given, curl broken or crashed, stopped from
    # outside): nothing is known about the name - no state, no VPN check (P0-2).
    if [ "$PROBE_RC" = 2 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_PROBE_UNKNOWN|$H|iface=wan|rc=$PRC" >> "$LOG"
        continue
    fi

    # The direct check failed: does it work at all (01.11: api.ozon.ru, wb.ru «broken», ISP=000)?
    # If the control sites fail too, no name is judged for the rest of this run (no marks, no load).
    ISPC=0
    ! command -v vward_isp_control >/dev/null 2>&1 || { rc_turn_give; vward_isp_control; ISPC=$?; }
    if [ "$ISPC" = 1 ]; then
        save_state "$H" "ADAPTIVE_ISP_UNRELIABLE"
        echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_ISP_PROBE_UNRELIABLE|$H|left=$((MAX_PER_RUN - DONE))" >> "$LOG"
        break
    fi

    # ISP не восстановился — проверяем текущий VPN.
    if [ "$TUN_DOWN" = 1 ]; then
        TUN_SKIPPED=$((TUN_SKIPPED + 1))
    elif probe "$H" "$WG" "$IP"; then
        save_state "$H" "AUTO_VPN"
        echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_VPN_OK|$H" >> "$LOG"
    elif [ "$PROBE_RC" = 2 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_PROBE_UNKNOWN|$H|iface=vpn|rc=$PRC" >> "$LOG"
    else
        save_state "$H" "BROKEN"
        echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_BROKEN|$H" >> "$LOG"
    fi

done
rc_turn_give

[ "$TUN_SKIPPED" = 0 ] || echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_TUNNEL_DOWN|skipped=$TUN_SKIPPED" >> "$LOG"

[ "$POS" -gt "$TOTAL" ] && POS=1
echo "$POS" > "$CURSOR"

# One save for every name removed within the hour (the route engine restores AdaptiveAuto from
# the USB list at every start, so a reboot before it loses nothing).
if [ -e "$CONFIG_DIRTY" ] && [ -z "$(find "$CONFIG_SAVED" -mmin "-$CONFIG_SAVE_EVERY_MIN" 2>/dev/null)" ]; then
    if ndmc -c "system configuration save" >/dev/null 2>&1; then
        rm -f "$CONFIG_DIRTY"; : > "$CONFIG_SAVED"
        echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_CONFIG_SAVED" >> "$LOG"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S')|MAINT_CONFIG_SAVE_FAILED" >> "$LOG"
    fi
fi

echo "Checked=$DONE Total=$TOTAL Next=$POS"
