#!/bin/sh
# VWARD Console configuration writer.
#
# The only path through which the Console changes persistent settings.  Every
# operation validates its input against a fixed allowlist, backs the target up,
# writes atomically, verifies the result and records one audit line.  Router
# configuration (FQDN groups) is changed under the shared route change lock and
# rolled back when Keenetic rejects the command or the result does not verify.
#
# Output: "result=changed|unchanged" on success, "error=<code>" on failure.
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

ETC=${VWARD_CONSOLE_ETC:-/opt/etc/vward}
ROUTE_STATE=${VWARD_ROUTE_STATE:-/opt/var/lib/vward/route-engine}
BACKUP_DIR=${VWARD_CONSOLE_BACKUP_DIR:-/opt/var/backups/vward/console-config}
AUDIT_LOG=${VWARD_CONSOLE_AUDIT_LOG:-/opt/var/log/vward/console-audit.log}
CHANGE_LOCK=${VWARD_ROUTE_CHANGE_LOCK:-/tmp/vward-route-change.lock}
NDMC=${VWARD_NDMC:-ndmc}
BACKUP_KEEP=20
ADAPTIVE_GROUP=AdaptiveAuto

FORCE_FILE="$ETC/route-engine/force-vpn.conf"
CATEGORY_FILE="$ETC/route-engine/categories.tsv"
TUNNEL_GUARD_FLAG="$ETC/tunnel-guard.disabled"
LISTS_CONF="$ETC/route-engine/domain-lists.conf"
LISTS_STATE="$ETC/route-engine/domain-lists"
WAN_GUARD_FLAG="$ETC/wan-guard.disabled"
ADAPTIVE_FLAG="$ETC/route-engine/adaptive.disabled"
CLASSIFIER_FILE="$ETC/route-engine/domain-classifier.conf"
IP_EXCLUDED=${VWARD_POLICY_EXCLUDED:-$ETC/policy-sync/excluded.categories}
AUTH_CONF=${VWARD_CONSOLE_AUTH_CONF:-$ETC/console/auth.conf}
WIFI_FILE=${VWARD_WIFI_CLIENT_GUARD_CONF:-$ETC/wifi-client-guard.conf}
WAN_PARAM_FILE=${VWARD_WAN_GUARD_CONF:-$ETC/wan-guard.conf}
UPDATE_FILE=${VWARD_UPDATE_CONFIG:-$ETC/update.conf}
POLICY_STATE=${VWARD_POLICY_STATE:-/opt/var/lib/vward/policy-sync}
TUNNEL_GUARD_STATE=${VWARD_TUNNEL_GUARD_STATE:-/opt/var/lib/vward/tunnel-guard/state}
TUNNEL_HEALTH_STATE=${VWARD_TUNNEL_HEALTH_STATE:-/tmp/vward-tunnel-health/state}
ROUTE_ENGINE_INIT=${VWARD_ROUTE_ENGINE_INIT:-/opt/etc/init.d/S91vward-route-engine}
POLICY_SYNC_BIN=${VWARD_POLICY_SYNC_BIN:-/opt/bin/vward-policy-sync.sh}
COMPONENT_REGISTRY=${VWARD_COMPONENT_REGISTRY:-/opt/share/vward/updater/current/component-registry.json}
COMPONENT_STATE=${VWARD_COMPONENT_STATE:-/opt/etc/vward/components}
JQ=${JQ:-jq}
PERSIST="$ROUTE_STATE/adaptive-persist.txt"
ADAPTIVE="$ROUTE_STATE/adaptive-domains.txt"
REFRESH_TS="$ROUTE_STATE/groups-refresh"

LOCKED=0
POLICY_LOCKED=0
RUNCFG=
TMPFILE=
JOURNAL=
DEVCONF_ORIG=
DEVCONF_EXISTED=
TXN=0
# An uploaded .conf holds the private key: it goes away with the helper.
CONF_FILE=
# The request body of ndm_secret while it is sent.
NS_FILE=

die() { printf 'error=%s\n' "$1"; exit "${2:-1}"; }

cleanup() {
    if [ "$TXN" = 1 ]; then
        TXN=0
        tunnel_undo || { audit "tunnel rollback incomplete"; printf 'error=rollback_incomplete\n'; }
    fi
    [ -z "$TMPFILE" ] || rm -f "$TMPFILE"
    [ -z "$CONF_FILE" ] || rm -f "$CONF_FILE" "$CONF_FILE.raw"
    [ -z "$NS_FILE" ] || rm -f "$NS_FILE"
    [ -z "$TMPFILE" ] || rm -f "$TMPFILE.raw"
    [ -z "$RUNCFG" ] || rm -f "$RUNCFG"
    [ -z "$JOURNAL" ] || rm -f "$JOURNAL" "$JOURNAL.moves" "$JOURNAL.doh" "$JOURNAL.agh" "$JOURNAL.agh.inc" "$JOURNAL.agh.undo"
    [ -z "$DEVCONF_ORIG" ] || rm -f "$DEVCONF_ORIG"
    [ "$POLICY_LOCKED" != 1 ] || rm -rf "$POLICY_STATE/lock"
    [ "$LOCKED" != 1 ] || rm -rf "${CHANGE_LOCK:?}"
    command -v vward_admission_leave >/dev/null 2>&1 && vward_admission_leave 2>/dev/null
    return 0
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

audit() {
    mkdir -p "$(dirname "$AUDIT_LOG")" 2>/dev/null
    printf '%s|CONSOLE_CONFIG|%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*" >> "$AUDIT_LOG" 2>/dev/null
    return 0
}

done_ok() { audit "$1 result=$2"; printf 'result=%s\n' "$2"; exit 0; }

valid_domain() {
    printf '%s\n' "$1" | awk 'length($0)<4||length($0)>253||index($0,".")==0{exit 1}
        {n=split($0,a,".");if(a[n]!~/^[a-z][a-z0-9-]*[a-z0-9]$/)exit 1
         for(i=1;i<=n;i++)if(length(a[i])<1||length(a[i])>63||a[i]!~/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/)exit 1;exit 0}'
}

valid_int_range() {
    case "$1" in '') return 1 ;; -) return 1 ;; esac
    case "${1#-}" in *[!0-9]*|'') return 1 ;; 0?*) return 1 ;; esac
    [ "${#1}" -le 7 ] || return 1
    [ "$1" -ge "$2" ] && [ "$1" -le "$3" ]
}

# ---------- Files ----------

backup_file() {
    [ -f "$1" ] || return 0
    mkdir -p "$BACKUP_DIR" || return 1
    base=$(basename "$1")
    cp -p "$1" "$BACKUP_DIR/$base.$(date '+%Y%m%d-%H%M%S').$$" || return 1
    ls -1t "$BACKUP_DIR/$base".* 2>/dev/null | tail -n +$((BACKUP_KEEP + 1)) | while IFS= read -r old; do rm -f "$old"; done
    return 0
}

# install_tmp TARGET DEFAULT_MODE: atomically replace TARGET with $TMPFILE,
# keeping the mode of the existing file.
install_tmp() {
    mode=$2
    # Keenetic's BusyBox stat has no -c, so the mode comes from ls.
    [ -f "$1" ] && mode=$(ls -ln "$1" 2>/dev/null | awk '{m=0; for (i=2;i<=10;i++) m=m*2+(substr($1,i,1)!="-"); printf "%o\n", m}')
    [ -n "$mode" ] || mode=$2
    chmod "$mode" "$TMPFILE" && mv "$TMPFILE" "$1" || return 1
    TMPFILE=
}

new_tmp() {
    mkdir -p "$(dirname "$1")" || return 1
    TMPFILE=$(mktemp "$1.console.XXXXXX" 2>/dev/null) || { TMPFILE=; return 1; }
}

# set_kv FILE KEY VALUE DEFAULT_MODE: replace or append KEY=VALUE.
set_kv() {
    if [ -f "$1" ] && [ "$(awk -F= -v k="$2" '$1==k{print substr($0,index($0,"=")+1);exit}' "$1")" = "$3" ] &&
       grep -q "^$2=" "$1"; then
        return 3
    fi
    backup_file "$1" || die backup_failed
    new_tmp "$1" || die write_failed
    if [ -f "$1" ]; then
        awk -F= -v k="$2" -v v="$3" '$1==k{if(!s)print k "=" v;s=1;next}{print}END{if(!s)print k "=" v}' "$1" > "$TMPFILE"
    else
        printf '%s=%s\n' "$2" "$3" > "$TMPFILE"
    fi || die write_failed
    install_tmp "$1" "$4" || die write_failed
    [ "$(awk -F= -v k="$2" '$1==k{print substr($0,index($0,"=")+1);exit}' "$1")" = "$3" ] || die verification_failed
}

# ---------- Router configuration ----------

change_lock() {
    n=0
    while ! mkdir "$CHANGE_LOCK" 2>/dev/null; do
        old=$(cat "$CHANGE_LOCK/pid" 2>/dev/null)
        if [ -n "$old" ] && ! kill -0 "$old" 2>/dev/null; then
            rm -rf "${CHANGE_LOCK:?}"
            continue
        fi
        n=$((n + 1))
        [ "$n" -ge 10 ] && die route_change_busy 75
        sleep 1
    done
    LOCKED=1
    echo $$ > "$CHANGE_LOCK/pid"
}

ndm() {
    out=$("$NDMC" -c "$1" 2>&1)
    rc=$?
    [ "$rc" -eq 0 ] || return 1
    printf '%s\n' "$out" | grep -Eqi '(^|[^a-z])(error|failed|invalid|unknown command|not found|no such entry)' && return 1
    return 0
}

# ndm_secret COMMAND: a command that holds a key (WireGuard private or
# preshared).  It reaches the router in the body of an RCI request, read from a
# root-only file, never in a process's arguments, which any process list shows.
ndm_secret() {
    case "$1" in *'"'*|*"$(printf '\134')"*) return 1 ;; esac
    NS_FILE=$(umask 077; mktemp /tmp/vward-console-rci.XXXXXX 2>/dev/null) || { NS_FILE=; return 1; }
    printf '[{"parse":"%s"}]\n' "$1" > "$NS_FILE" || return 1
    ns_out=$("${VWARD_CURL_BIN:-curl}" -fsS --max-time 15 -H 'Content-Type: application/json' \
        --data-binary "@$NS_FILE" "${VWARD_RCI_BASE:-http://127.0.0.1:79/rci}/" 2>/dev/null)
    ns_rc=$?
    rm -f "$NS_FILE"; NS_FILE=
    [ "$ns_rc" -eq 0 ] || return 1
    # Keenetic answers 200 either way: a refused command carries status "error".
    printf '%s\n' "$ns_out" | "$JQ" -e 'type == "array" and length > 0 and ([.. | objects | select(.status? == "error")] | length == 0)' >/dev/null 2>&1
}

load_profile_base() {
    lib=${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}
    [ -r "$lib" ] || die profile_unavailable
    . "$lib"
    vward_profile_load >/dev/null 2>&1 || die profile_unavailable
}

load_profile() {
    load_profile_base
    case "${VWARD_POLICY_GROUP:-}" in ''|"$ADAPTIVE_GROUP") die policy_group_unavailable ;; esac
    case "$VWARD_POLICY_GROUP" in *[!A-Za-z0-9_.-]*) die policy_group_unavailable ;; esac
}

snapshot() {
    [ -n "$RUNCFG" ] || RUNCFG=$(mktemp /tmp/vward-console-config.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    "$NDMC" -c "show running-config" > "$RUNCFG" 2>/dev/null && [ -s "$RUNCFG" ] || die router_config_unavailable
}

in_group() {
    awk -v g="$1" -v d="$2" '
        /^object-group fqdn / {cur=$3; next}
        /^!/ {cur=""; next}
        cur==g && $1=="include" && tolower($2)==d {found=1}
        END {exit found ? 0 : 1}' "$RUNCFG"
}

group_set() {
    # group_set GROUP DOMAIN add|remove
    if [ "$3" = add ]; then ndm "object-group fqdn $1 include $2"; else ndm "no object-group fqdn $1 include $2"; fi
}

save_router() {
    ndm "system configuration save" || return 1
    mkdir -p "$ROUTE_STATE" 2>/dev/null && echo 0 > "$REFRESH_TS" 2>/dev/null
    return 0
}

drop_line() {
    # drop_line FILE DOMAIN: remove exact line (case-insensitive) from a state list.
    [ -f "$1" ] || return 3
    grep -Fqix -- "$2" "$1" || return 3
    new_tmp "$1" || return 1
    grep -Fvix -- "$2" "$1" > "$TMPFILE"
    install_tmp "$1" 0644
}

route_group_change() {
    # route_group_change GROUP DOMAIN add|remove: verified, rolled back on failure.
    snapshot
    want=0; [ "$3" = add ] && want=1
    have=0; in_group "$1" "$2" && have=1
    [ "$want" != "$have" ] || return 3
    if ! group_set "$1" "$2" "$3"; then
        die router_rejected
    fi
    snapshot
    have=0; in_group "$1" "$2" && have=1
    if [ "$want" != "$have" ]; then
        if [ "$3" = add ]; then group_set "$1" "$2" remove; else group_set "$1" "$2" add; fi
        die verification_failed
    fi
    return 0
}

# ---------- Operations ----------

op_route_domain() {
    case "$1" in add|remove) ;; *) die invalid_operation 64 ;; esac
    valid_domain "$2" || die invalid_domain 64
    load_profile
    change_lock
    route_group_change "$VWARD_POLICY_GROUP" "$2" "$1" || done_ok "route-domain $1 $2" unchanged
    save_router || die config_save_failed
    done_ok "route-domain $1 $2 group=$VWARD_POLICY_GROUP" changed
}

op_adaptive() {
    case "$1" in remove|pin) ;; *) die invalid_operation 64 ;; esac
    valid_domain "$2" || die invalid_domain 64
    [ "$1" = remove ] || load_profile
    change_lock
    changed=0 router=0
    if [ "$1" = pin ]; then
        route_group_change "$VWARD_POLICY_GROUP" "$2" add && router=1
    fi
    route_group_change "$ADAPTIVE_GROUP" "$2" remove && router=1
    # The persist list is authoritative: the reconciler re-adds anything left in it.
    drop_line "$PERSIST" "$2"; case $? in 0) changed=1 ;; 3) ;; *) die write_failed ;; esac
    drop_line "$ADAPTIVE" "$2"; case $? in 0) changed=1 ;; 3) ;; *) die write_failed ;; esac
    if [ "$router" = 1 ]; then
        save_router || die config_save_failed
        changed=1
    fi
    [ "$changed" = 1 ] || done_ok "adaptive $1 $2" unchanged
    done_ok "adaptive $1 $2" changed
}

op_force_vpn() {
    case "$1" in add|remove) ;; *) die invalid_operation 64 ;; esac
    valid_domain "$2" || die invalid_domain 64
    present=0
    [ -f "$FORCE_FILE" ] && sed 's/#.*//' "$FORCE_FILE" | awk '{print tolower($1)}' | grep -Fqx -- "$2" && present=1
    if [ "$1" = add ]; then
        [ "$present" = 0 ] || done_ok "force-vpn add $2" unchanged
        [ ! -f "$FORCE_FILE" ] || [ "$(grep -c . "$FORCE_FILE")" -lt 500 ] || die list_full
        backup_file "$FORCE_FILE" || die backup_failed
        new_tmp "$FORCE_FILE" || die write_failed
        { [ ! -f "$FORCE_FILE" ] || cat "$FORCE_FILE"; printf '%s\n' "$2"; } > "$TMPFILE" || die write_failed
    else
        [ "$present" = 1 ] || done_ok "force-vpn remove $2" unchanged
        backup_file "$FORCE_FILE" || die backup_failed
        new_tmp "$FORCE_FILE" || die write_failed
        awk -v d="$2" '{x=$0;sub(/#.*/,"",x);split(x,f," ");if(tolower(f[1])==d)next;print}' "$FORCE_FILE" > "$TMPFILE" || die write_failed
    fi
    install_tmp "$FORCE_FILE" 0644 || die write_failed
    done_ok "force-vpn $1 $2" changed
}

op_domain_category() {
    printf '%s\n' "$1" | grep -Eq '^[a-z0-9][a-z0-9-]{0,39}$' || die invalid_category 64
    case "$2" in 0|1) ;; *) die invalid_value 64 ;; esac
    [ -f "$CATEGORY_FILE" ] || die config_unavailable
    cur=$(awk -F'|' -v c="$1" '$1==c&&NF>=5{print $5;exit}' "$CATEGORY_FILE")
    [ -n "$cur" ] || die invalid_category 64
    [ "$cur" != "$2" ] || done_ok "domain-category $1=$2" unchanged
    backup_file "$CATEGORY_FILE" || die backup_failed
    new_tmp "$CATEGORY_FILE" || die write_failed
    awk -F'|' -v OFS='|' -v c="$1" -v v="$2" '$1==c&&NF>=5{$5=v}{print}' "$CATEGORY_FILE" > "$TMPFILE" || die write_failed
    install_tmp "$CATEGORY_FILE" 0644 || die write_failed
    [ "$(awk -F'|' -v c="$1" '$1==c{print $5;exit}' "$CATEGORY_FILE")" = "$2" ] || die verification_failed
    done_ok "domain-category $1=$2" changed
}

# op_guard_flag NAME FLAG-FILE 0|1: a guard is disabled while its flag file exists.
op_guard_flag() {
    case "$3" in
        1) [ -e "$2" ] || done_ok "$1 enabled" unchanged
           rm -f "$2" || die write_failed ;;
        0) [ ! -e "$2" ] || done_ok "$1 disabled" unchanged
           mkdir -p "$(dirname "$2")" && printf 'disabled from VWARD Console %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" > "$2" || die write_failed ;;
        *) die invalid_value 64 ;;
    esac
    done_ok "$1 enabled=$3" changed
}

op_wifi() {
    case "$1" in
        ENABLED|CONTROL_ENABLED) case "$2" in 0|1) ;; *) die invalid_value 64 ;; esac ;;
        WINDOW_SEC) valid_int_range "$2" 3600 604800 || die invalid_value 64 ;;
        BAND_SWITCH_WARN|WEAK_5G_SAMPLE_WARN) valid_int_range "$2" 1 1000 || die invalid_value 64 ;;
        WEAK_5G_RSSI) valid_int_range "$2" -95 -40 || die invalid_value 64 ;;
        *) die invalid_setting 64 ;;
    esac
    set_kv "$WIFI_FILE" "$1" "$2" 0644 || done_ok "wifi $1=$2" unchanged
    done_ok "wifi $1=$2" changed
}

# wan-param KEY VALUE: recovery limits of the internet guard, same ranges as vward-wan-guard.sh.
op_wan_param() {
    case "$1" in
        CONFIRM_FAILURES|MAX_RENEW_HOUR) valid_int_range "$2" 1 10 || die invalid_value 64 ;;
        RENEW_COOLDOWN) valid_int_range "$2" 60 7200 || die invalid_value 64 ;;
        BOUNCE_COOLDOWN) valid_int_range "$2" 300 21600 || die invalid_value 64 ;;
        MAX_BOUNCE_HOUR) valid_int_range "$2" 1 6 || die invalid_value 64 ;;
        MAX_BOUNCE_DAY) valid_int_range "$2" 1 24 || die invalid_value 64 ;;
        *) die invalid_setting 64 ;;
    esac
    set_kv "$WAN_PARAM_FILE" "$1" "$2" 0644 || done_ok "wan-param $1=$2" unchanged
    done_ok "wan-param $1=$2" changed
}

op_update() {
    [ -f "$UPDATE_FILE" ] || die config_unavailable
    case "$1" in
        install_time)
            # One install time: the window opens then and closes an hour later.
            printf '%s\n' "$2" | grep -Eq '^([01][0-9]|2[0-3]):[0-5][0-9]$' || die invalid_value 64
            end=$(printf '%s\n' "$2" | awk -F: '{printf "%02d:%s\n", ($1 + 1) % 24, $2}')
            a=0; b=0
            set_kv "$UPDATE_FILE" safe_window_start "$2" 0600 && a=1
            set_kv "$UPDATE_FILE" safe_window_end "$end" 0600 && b=1
            [ "$a$b" != 00 ] || done_ok "update install_time=$2" unchanged
            done_ok "update install_time=$2" changed ;;
        safe_window_start|safe_window_end)
            printf '%s\n' "$2" | grep -Eq '^([01][0-9]|2[0-3]):[0-5][0-9]$' || die invalid_value 64
            other=safe_window_end; [ "$1" = safe_window_end ] && other=safe_window_start
            [ "$(awk -F= -v k="$other" '$1==k{print $2;exit}' "$UPDATE_FILE")" != "$2" ] || die invalid_window 64 ;;
        check_interval_seconds) valid_int_range "$2" 300 86400 || die invalid_value 64 ;;
        apply_window) case "$2" in window|any) ;; *) die invalid_value 64 ;; esac ;;
        *) die invalid_setting 64 ;;
    esac
    set_kv "$UPDATE_FILE" "$1" "$2" 0600 || done_ok "update $1=$2" unchanged
    done_ok "update $1=$2" changed
}

# ip-category NAME 0|1: 0 excludes the IP category from VPN routes.
op_ip_category() {
    printf '%s\n' "$1" | grep -Eq '^[a-z0-9][a-z0-9._-]{0,63}$' || die invalid_category 64
    case "$2" in 0|1) ;; *) die invalid_value 64 ;; esac
    have=0; [ -f "$IP_EXCLUDED" ] && grep -Fqx -- "$1" "$IP_EXCLUDED" && have=1
    [ "$2" = 0 ] && [ "$have" = 1 ] && done_ok "ip-category $1=0" unchanged
    [ "$2" = 1 ] && [ "$have" = 0 ] && done_ok "ip-category $1=1" unchanged
    backup_file "$IP_EXCLUDED" || die backup_failed
    new_tmp "$IP_EXCLUDED" || die write_failed
    { [ ! -f "$IP_EXCLUDED" ] || grep -Fvx -- "$1" "$IP_EXCLUDED"; [ "$2" = 1 ] || printf '%s\n' "$1"; } > "$TMPFILE"
    [ "$(grep -c . "$TMPFILE")" -le 500 ] || die list_full
    install_tmp "$IP_EXCLUDED" 0644 || die write_failed
    done_ok "ip-category $1=$2" changed
}

# update-feed beta|dev: which branch's signed feed the updater follows.  Only the
# branch in a standard raw.githubusercontent.com URL is replaced; the signed
# channel, the key and the anti-replay checks stay as they are.
op_update_feed() {
    case "$1" in beta|dev) ;; *) die invalid_value 64 ;; esac
    [ -f "$UPDATE_FILE" ] || die config_unavailable
    url=$(awk -F= '$1=="manifest_url"{print substr($0,index($0,"=")+1);exit}' "$UPDATE_FILE")
    new=$(printf '%s\n' "$url" | sed -n -E "s#^(https://raw\.githubusercontent\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/)(beta|dev)(/updates/[a-z0-9-]+/update-manifest\.json)\$#\1$1\3#p")
    [ -n "$new" ] || die custom_manifest_url
    set_kv "$UPDATE_FILE" manifest_url "$new" 0600 || done_ok "update-feed $1" unchanged
    done_ok "update-feed $1" changed
}

# ---------- Tunnel for routes ----------
#
# Moves VWARD's routing to another WireGuard tunnel: the Keenetic DNS routes of
# the policy group and AdaptiveAuto are re-pointed (new route first, then the old
# one is withdrawn), device.conf records the tunnel and pins the policy group,
# and the profile must load with it.  While TXN=1 any exit (error or signal)
# undoes the executed steps in reverse order through the EXIT trap.  policy-sync
# then moves its own IP routes (owned.interface).

tunnel_undo() {
    # Undo the router steps recorded in the journal, newest first.  Every step is
    # attempted; returns 1 when any of them failed.
    undo_rc=0
    if [ -n "$JOURNAL" ] && [ -s "$JOURNAL" ]; then
        awk '{a[NR]=$0} END{for (i=NR;i>0;i--) print a[i]}' "$JOURNAL" |
            { bad=0; while IFS= read -r undo; do
                case "$undo" in
                    "DOH-REMOVE "*) doh_remove "${undo#DOH-REMOVE }" || bad=1 ;;
                    "AGH-PUT "*) agh_control smartdns-put "${undo#AGH-PUT }" >/dev/null || bad=1 ;;
                    "AGH-TAKE "*) f=${undo#AGH-TAKE }; cut -f1 "$f" > "$f.inc" && agh_control smartdns-take "$f.inc" "$f.undo" >/dev/null || bad=1 ;;
                    *" private-key "*|*" preshared-key "*) ndm_secret "$undo" || bad=1 ;;
                    *) ndm "$undo" || bad=1 ;;
                esac
              done; exit "$bad"; } || undo_rc=1
    fi
    case "$DEVCONF_EXISTED" in
        1) cp -p "$DEVCONF_ORIG" "$VWARD_DEVICE_CONFIG" || undo_rc=1 ;;
        0) rm -f "$VWARD_DEVICE_CONFIG" || undo_rc=1 ;;
    esac
    rm -f "$VWARD_DEVICE_MAP_CACHE"
    return "$undo_rc"
}

route_present() {
    # route_present GROUP TARGET: a DNS route of GROUP to TARGET exists.
    awk -v g="$1" -v t="$2" '$1=="route" && $2=="object-group" && $3==g && $4==t {f=1} END{exit f ? 0 : 1}' "$RUNCFG"
}

op_tunnel() {
    case "$1" in ''|*[!A-Za-z0-9_./:-]*) die invalid_tunnel 64 ;; esac
    [ "${#1}" -le 64 ] || die invalid_tunnel 64
    load_profile
    OLD_IF=$VWARD_TUNNEL_INTERFACE OLD_DEV=$VWARD_TUNNEL_DEVICE GROUP=$VWARD_POLICY_GROUP NEW_IF=$1
    [ "$NEW_IF" != "$OLD_IF" ] || done_ok "tunnel $NEW_IF" unchanged
    [ "$(awk -F= '$1=="FAILOPEN_ACTIVE"{print $2}' "$TUNNEL_GUARD_STATE" 2>/dev/null)" != 1 ] || die failopen_active

    rm -f "$VWARD_DEVICE_MAP_CACHE"
    map=$(vward_device_map 2>/dev/null) || die router_config_unavailable
    NEW_DEV=$(vward_map_tunnels "$map" | awk -v n="$NEW_IF" '$1==n {print $2; exit}')
    vward_valid_ifname "$NEW_DEV" || die unknown_tunnel 64

    change_lock
    mkdir -p "$POLICY_STATE" && vward_lock_take "$POLICY_STATE/lock" || die policy_sync_busy 75
    POLICY_LOCKED=1
    JOURNAL=$(mktemp /tmp/vward-console-tunnel.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    DEVCONF_ORIG=$(mktemp /tmp/vward-console-devconf.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    TXN=1
    snapshot

    # ctx<TAB>group<TAB>target<TAB>options for every VWARD group routed to the old tunnel.
    moves=$(awk -v g1="$GROUP" -v g2="$ADAPTIVE_GROUP" -v i="$OLD_IF" -v d="$OLD_DEV" '
        /^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1) ? "dns-proxy" : ""}
        /^!/ {ctx = ""}
        $1=="route" && $2=="object-group" && ($3==g1 || $3==g2) && ($4==i || $4==d) {
            opt = ""; for (k = 5; k <= NF; k++) opt = opt (opt == "" ? "" : " ") $k
            print (ctx == "" ? "-" : ctx) "\t" $3 "\t" $4 "\t" (opt == "" ? "-" : opt)
        }' "$RUNCFG")
    tab=$(printf '\t')
    printf '%s\n' "$moves" | while IFS="$tab" read -r ctx g t opt; do
        [ -n "$g" ] || continue
        case "$opt" in -|auto|reject|"auto reject"|"reject auto") ;; *) exit 1 ;; esac
    done || die unsupported_route

    # 1. New routes first, so the groups never lose their route.
    printf '%s\n' "$moves" > "$JOURNAL.moves"
    while IFS="$tab" read -r ctx g t opt; do
        [ -n "$g" ] || continue
        p=; [ "$ctx" = - ] || p="$ctx "
        o=; [ "$opt" = - ] || o=" $opt"
        nt=$NEW_IF; [ "$t" = "$OLD_DEV" ] && [ "$OLD_DEV" != "$OLD_IF" ] && nt=$NEW_DEV
        route_present "$g" "$nt" && continue
        ndm "${p}route object-group $g $nt$o" || die router_rejected
        echo "${p}no route object-group $g $nt" >> "$JOURNAL"
    done < "$JOURNAL.moves"
    # 2. Withdraw the old routes.
    while IFS="$tab" read -r ctx g t opt; do
        [ -n "$g" ] || continue
        p=; [ "$ctx" = - ] || p="$ctx "
        o=; [ "$opt" = - ] || o=" $opt"
        ndm "${p}no route object-group $g $t" || die router_rejected
        echo "${p}route object-group $g $t$o" >> "$JOURNAL"
    done < "$JOURNAL.moves"
    # 3. The router must show exactly the new routing.
    snapshot
    while IFS="$tab" read -r ctx g t opt; do
        [ -n "$g" ] || continue
        nt=$NEW_IF; [ "$t" = "$OLD_DEV" ] && [ "$OLD_DEV" != "$OLD_IF" ] && nt=$NEW_DEV
        route_present "$g" "$nt" && ! route_present "$g" "$t" || die verification_failed
    done < "$JOURNAL.moves"
    moved=$(grep -c . "$JOURNAL.moves")

    # 4. device.conf: the tunnel, and the policy group pinned so discovery no
    #    longer depends on which tunnel its route points to.
    DEVCONF_EXISTED=0
    if [ -f "$VWARD_DEVICE_CONFIG" ]; then
        cp -p "$VWARD_DEVICE_CONFIG" "$DEVCONF_ORIG" || die backup_failed
        DEVCONF_EXISTED=1
    fi
    backup_file "$VWARD_DEVICE_CONFIG" || die backup_failed
    new_tmp "$VWARD_DEVICE_CONFIG" || die write_failed
    { [ ! -f "$VWARD_DEVICE_CONFIG" ] || cat "$VWARD_DEVICE_CONFIG"; } | awk -v i="$NEW_IF" -v d="$NEW_DEV" -v g="$GROUP" '
        BEGIN {v["VWARD_TUNNEL_INTERFACE"]=i; v["VWARD_TUNNEL_DEVICE"]=d; v["VWARD_POLICY_GROUP"]=g}
        { k=$0; sub(/=.*/, "", k); if (k in v) { if (!(k in done)) print k "=" v[k]; done[k]=1; next } print }
        END {for (k in v) if (!(k in done)) print k "=" v[k]}' > "$TMPFILE" || die write_failed
    install_tmp "$VWARD_DEVICE_CONFIG" 0600 || die write_failed
    rm -f "$VWARD_DEVICE_MAP_CACHE"
    (
        unset VWARD_TUNNEL_INTERFACE VWARD_TUNNEL_DEVICE VWARD_POLICY_GROUP
        vward_profile_load >/dev/null 2>&1 &&
            [ "$VWARD_TUNNEL_INTERFACE" = "$NEW_IF" ] && [ "$VWARD_TUNNEL_DEVICE" = "$NEW_DEV" ] &&
            [ "$VWARD_POLICY_GROUP" = "$GROUP" ]
    ) || die profile_verification_failed

    # 5. Persist the router configuration; nothing half-applied survives a reboot.
    save_router || die config_save_failed
    TXN=0

    # 6. Runtime state belonged to the previous tunnel.
    if [ -s "$POLICY_STATE/owned.dynamic.routes" ] && [ ! -s "$POLICY_STATE/owned.interface" ]; then
        echo "$OLD_IF" > "$POLICY_STATE/owned.interface"
    fi
    rm -f "$TUNNEL_GUARD_STATE" "$TUNNEL_HEALTH_STATE"
    rm -rf "$POLICY_STATE/lock"; POLICY_LOCKED=0
    rm -rf "${CHANGE_LOCK:?}"; LOCKED=0
    [ ! -x "$ROUTE_ENGINE_INIT" ] || "$ROUTE_ENGINE_INIT" restart </dev/null >/dev/null 2>&1 || true
    # IP routes follow in the background (policy-sync withdraws them from the old device).
    [ ! -x "$POLICY_SYNC_BIN" ] || (trap '' HUP; exec "$POLICY_SYNC_BIN" --reconcile) </dev/null >/dev/null 2>&1 &
    done_ok "tunnel $OLD_IF($OLD_DEV) -> $NEW_IF($NEW_DEV) group=$GROUP routes=$moved" changed
}

# ---------- Domain lists: around the tunnel or through it ----------
#
# A list routed around the tunnel (to the ISP, often with a Smart DNS such as
# Aeternia answering for some of its domains) can be moved into the tunnel and
# back.  Into the tunnel, the Smart DNS lines for the list's domains are taken
# out too: their answers point at the Smart DNS proxy, which does not serve
# connections arriving from the tunnel.  The previous route and those lines are
# kept in $LISTS_STATE/<group> and put back on return.  Every router step is
# journaled and undone in reverse on any failure, like op_tunnel.

valid_group() {
    case "$1" in ''|*[!A-Za-z0-9_.-]*) return 1 ;; esac
    [ "${#1}" -le 64 ] && [ "$1" != "$ADAPTIVE_GROUP" ]
}

group_route() {
    # group_route GROUP: "target<TAB>options" of the group's dns-proxy route.
    awk -v g="$1" '
        /^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1)}
        /^!/ {ctx = 0}
        ctx && $1 == "route" && $2 == "object-group" && $3 == g {
            o = ""; for (k = 5; k <= NF; k++) o = o (o == "" ? "" : " ") $k
            print $4 "\t" (o == "" ? "-" : o); exit
        }' "$RUNCFG"
}

doh_lines() {
    # All dns-proxy https upstream lines, without indentation.
    awk '/^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1)} /^!/ {ctx = 0}
        ctx && $1 == "https" && $2 == "upstream" {sub(/^[ \t]+/, ""); print}' "$RUNCFG"
}

group_doh_lines() {
    # Smart DNS lines whose domain is a domain of GROUP or below one.
    { awk -v g="$1" '/^object-group fqdn / {cur = $3; next} /^!/ {cur = ""}
        cur == g && $1 == "include" {print "I " tolower($2)}' "$RUNCFG"
      doh_lines | awk '$(NF-1) == "domain" {print "D " $0}'; } |
    awk '$1 == "I" {inc[$2] = 1; next}
        {line = substr($0, 3); d = tolower($NF)
         while (d != "") { if (d in inc) {print line; break}
                           i = index(d, "."); d = i ? substr(d, i + 1) : "" }}'
}

doh_present() { doh_lines | grep -qxF -- "$1"; }

doh_remove() {
    # doh_remove LINE: take one Smart DNS line out.  Keenetic's delete syntax is
    # not documented for per-domain upstreams, so the forms are tried in turn and
    # each is verified; a form that also took other lines puts them back.
    # Returns 0 removed, 1 not removable, 2 other lines were affected.
    set -- "$1" $1
    dr_url=$4 dr_dom=$(eval "printf '%s' \"\${$#}\"")
    dr_on=$(printf '%s\n' "$1" | awk '{for (i = 1; i < NF; i++) if ($i == "on") {print $(i+1); exit}}')
    dr_before=$(mktemp /tmp/vward-console-doh.XXXXXX 2>/dev/null) || return 1
    snapshot; doh_lines > "$dr_before"
    dr_rc=1
    dr_other_lost=0
    for dr_form in "no $1" ${dr_on:+"no https upstream $dr_url on $dr_on domain $dr_dom"} "no https upstream $dr_url domain $dr_dom"; do
        ndm "dns-proxy $dr_form" || :
        snapshot
        while IFS= read -r dr_other; do
            [ "$dr_other" != "$1" ] || continue
            doh_present "$dr_other" && continue
            ndm "dns-proxy $dr_other" || :
            dr_other_lost=1
        done < "$dr_before"
        [ "$dr_other_lost" = 0 ] || snapshot
        doh_present "$1" || { dr_rc=0; break; }
    done
    rm -f "$dr_before"
    if [ "$dr_other_lost" = 1 ]; then
        # An unsafe form: leave the line as it was, the caller aborts.
        doh_present "$1" || ndm "dns-proxy $1" || :
        return 2
    fi
    return "$dr_rc"
}

# Smart DNS kept in AdGuard Home ([/domain/]https://...): the rows of a list sent
# into a tunnel go out there as they do in Keenetic, through the Ads component,
# which holds the AdGuard Home login and reads every change back.
ADS_CONTROL=${VWARD_ADS_CONTROL_BIN:-/opt/bin/vward-ads-privacy-control.sh}
agh_control() {
    [ -x "$ADS_CONTROL" ] || { AGH_ERR=smartdns_agh_unavailable; return 1; }
    ac_out=$("$ADS_CONTROL" agh "$@" 2>&1) && printf '%s\n' "$ac_out" | grep -qx 'CONTROL=PASS' && return 0
    AGH_ERR=$(printf '%s\n' "$ac_out" | sed -n 's/^ERROR=//p' | head -n 1)
    case "$AGH_ERR" in adguard_auth_required|adguard_unavailable|upstream_file_unsupported) ;; *) AGH_ERR=smartdns_agh_failed ;; esac
    return 1
}

agh_take() {
    # agh_take GROUP OUT: take the AdGuard Home Smart DNS rows of GROUP; pairs to OUT.
    : > "$2"
    awk -v g="$1" '/^object-group fqdn / {cur = $3; next} /^!/ {cur = ""} cur == g && $1 == "include" {print tolower($2)}' "$RUNCFG" > "$2.inc"
    command -v vward_agh_smartdns_domains >/dev/null 2>&1 || return 0
    # Nothing of the list in AdGuard Home: AdGuard Home is not asked at all.
    vward_agh_smartdns_domains | awk 'NR == FNR {inc[$1] = 1; next}
        {d = $1; while (d != "") {if (d in inc) {f = 1; exit} i = index(d, "."); d = i ? substr(d, i + 1) : ""}}
        END {exit f ? 0 : 1}' "$2.inc" - || return 0
    agh_control smartdns-take "$2.inc" "$2"
}

wan_route_target() {
    # Where a list goes around the tunnel when nothing was recorded: the target
    # other lists already use for the ISP, else the WAN interface.
    t=$(awk -v w="$VWARD_WAN_INTERFACE" '/^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1)} /^!/ {ctx = 0}
        ctx && $1 == "route" && $2 == "object-group" && ($4 == "ISP" || $4 == w) {print $4; exit}' "$RUNCFG")
    printf '%s\n' "${t:-$VWARD_WAN_INTERFACE}"
}

op_domain_list() {
    # domain-list GROUP vpn|bypass|TUNNEL: vpn is the VWARD tunnel.
    valid_group "$1" || die invalid_group 64
    case "$2" in ''|*[!A-Za-z0-9_.-]*) die invalid_value 64 ;; esac
    load_profile_base
    G=$1 TUN=$VWARD_TUNNEL_INTERFACE
    vward_valid_ndm_name "$TUN" || die tunnel_unavailable
    case "$2" in
        vpn|bypass) ;;
        *) is_tunnel "$2" || die unknown_tunnel 64; TUN=$2 ;;
    esac
    change_lock
    JOURNAL=$(mktemp /tmp/vward-console-lists.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    TXN=1
    snapshot
    grep -qx "object-group fqdn $G" "$RUNCFG" || die unknown_group 64
    tab=$(printf '\t')
    cur=$(group_route "$G")
    cur_t=${cur%%"$tab"*} cur_o=${cur#*"$tab"}
    [ -n "$cur" ] || cur_o=-
    saved="$LISTS_STATE/$G"

    if [ "$2" != bypass ] && [ "$cur_t" != "$TUN" ] && [ -n "$cur_t" ] && is_tunnel "$cur_t"; then
        # From one tunnel to another: only the route moves, Smart DNS lines are already out.
        ndm "dns-proxy route object-group $G $TUN auto" || die router_rejected
        echo "dns-proxy no route object-group $G $TUN" >> "$JOURNAL"
        ndm "dns-proxy no route object-group $G $cur_t" || die router_rejected
        o=; [ "$cur_o" = - ] || o=" $cur_o"
        echo "dns-proxy route object-group $G $cur_t$o" >> "$JOURNAL"
        snapshot
        route_present "$G" "$TUN" && ! route_present "$G" "$cur_t" || die verification_failed
        save_router || die config_save_failed
        TXN=0
        done_ok "domain-list $G $2 route=$cur_t->$TUN" changed
    fi

    if [ "$2" != bypass ]; then
        [ "$cur_t" != "$TUN" ] || { TXN=0; done_ok "domain-list $G $2" unchanged; }
        group_doh_lines "$G" > "$JOURNAL.doh"
        # 1. The tunnel route first, so the list never loses its route.
        ndm "dns-proxy route object-group $G $TUN auto" || die router_rejected
        echo "dns-proxy no route object-group $G $TUN" >> "$JOURNAL"
        if [ -n "$cur_t" ]; then
            ndm "dns-proxy no route object-group $G $cur_t" || die router_rejected
            o=; [ "$cur_o" = - ] || o=" $cur_o"
            echo "dns-proxy route object-group $G $cur_t$o" >> "$JOURNAL"
        fi
        # 2. Smart DNS answers would send the tunnel to the Smart DNS proxy.
        while IFS= read -r L; do
            [ -n "$L" ] || continue
            doh_remove "$L"; rc=$?
            [ "$rc" = 0 ] || { [ "$rc" = 2 ] && die doh_remove_unsafe; die doh_remove_failed; }
            echo "dns-proxy $L" >> "$JOURNAL"
        done < "$JOURNAL.doh"
        # 2b. The same rows kept in AdGuard Home.
        agh_take "$G" "$JOURNAL.agh" || die "$AGH_ERR"
        [ ! -s "$JOURNAL.agh" ] || echo "AGH-PUT $JOURNAL.agh" >> "$JOURNAL"
        # 3. Verify, then remember how to come back.
        snapshot
        route_present "$G" "$TUN" || die verification_failed
        [ -z "$cur_t" ] || ! route_present "$G" "$cur_t" || die verification_failed
        while IFS= read -r L; do [ -z "$L" ] || ! doh_present "$L" || die verification_failed; done < "$JOURNAL.doh"
        new_tmp "$saved" || die write_failed
        { printf 'route=%s\t%s\n' "${cur_t:--}" "$cur_o"; sed -n 's/^./doh=&/p' "$JOURNAL.doh"; sed -n 's/^./agh=&/p' "$JOURNAL.agh"; } > "$TMPFILE" || die write_failed
        install_tmp "$saved" 0600 || die write_failed
        detail="route=${cur_t:--}->$TUN doh=$(grep -c . "$JOURNAL.doh") agh=$(grep -c . "$JOURNAL.agh")"
    else
        rt=$(sed -n 's/^route=//p' "$saved" 2>/dev/null)
        if [ -n "$rt" ]; then new_t=${rt%%"$tab"*} new_o=${rt#*"$tab"}; else new_t=$(wan_route_target) new_o=auto; fi
        { [ -n "$cur_t" ] && is_tunnel "$cur_t"; } || { TXN=0; done_ok "domain-list $G bypass" unchanged; }
        TUN=$cur_t
        sed -n 's/^doh=//p' "$saved" 2>/dev/null > "$JOURNAL.doh"
        if [ "$new_t" != - ]; then
            o=; [ "$new_o" = - ] || o=" $new_o"
            ndm "dns-proxy route object-group $G $new_t$o" || die router_rejected
            echo "dns-proxy no route object-group $G $new_t" >> "$JOURNAL"
        fi
        ndm "dns-proxy no route object-group $G $TUN" || die router_rejected
        echo "dns-proxy route object-group $G $TUN auto" >> "$JOURNAL"
        while IFS= read -r L; do
            [ -n "$L" ] || continue
            doh_present "$L" && continue
            out=$("$NDMC" -c "dns-proxy $L" 2>&1)
            case "$out" in *"limit exceeded"*) die doh_limit ;; esac
            printf '%s\n' "$out" | grep -Eqi '(^|[^a-z])(error|failed|invalid|unknown command|not found)' && die router_rejected
            echo "DOH-REMOVE $L" >> "$JOURNAL"
        done < "$JOURNAL.doh"
        sed -n 's/^agh=//p' "$saved" 2>/dev/null > "$JOURNAL.agh"
        if [ -s "$JOURNAL.agh" ]; then
            agh_control smartdns-put "$JOURNAL.agh" || die "$AGH_ERR"
            echo "AGH-TAKE $JOURNAL.agh" >> "$JOURNAL"
        fi
        snapshot
        [ "$new_t" = - ] || route_present "$G" "$new_t" || die verification_failed
        ! route_present "$G" "$TUN" || die verification_failed
        while IFS= read -r L; do [ -z "$L" ] || doh_present "$L" || die verification_failed; done < "$JOURNAL.doh"
        detail="route=$TUN->$new_t doh=$(grep -c . "$JOURNAL.doh") agh=$(grep -c . "$JOURNAL.agh")"
    fi

    save_router || die config_save_failed
    TXN=0
    [ "$2" != bypass ] || rm -f "$saved"
    done_ok "domain-list $G $2 $detail" changed
}

op_domain_list_watch() {
    valid_group "$1" || die invalid_group 64
    case "$2" in 0|1) ;; *) die invalid_value 64 ;; esac
    set_kv "$LISTS_CONF" "watch.$1" "$2" 0644 || done_ok "domain-list-watch $1 $2" unchanged
    # The route engine rebuilds its watch map on the next group refresh.
    mkdir -p "$ROUTE_STATE" 2>/dev/null && echo 0 > "$REFRESH_TS" 2>/dev/null
    done_ok "domain-list-watch $1 $2" changed
}

# ---------- Tunnels: replace a configuration, create, delete, subnets ----------
#
# A WireGuard/AmneziaWG .conf is parsed into a plan of Keenetic commands.  A
# new configuration is always proven first on a temporary interface: only
# after its server answers a handshake is it written into the target tunnel,
# so a bad file never touches a working tunnel.  Keenetic hides the private
# key in its configuration, so VWARD keeps each applied .conf (root-only, the
# last three) to be able to go back.  The running configuration is saved only
# after the tunnel answers; until then a router reboot also restores it.

TUNNEL_STORE="$ETC/tunnels"
TEST_ADDRESS="192.0.2.254 255.255.255.255"
HANDSHAKE_WAIT=${VWARD_TUNNEL_HANDSHAKE_WAIT:-30}

wg_key() { printf '%s\n' "$1" | grep -Eq '^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=$'; }

prefix_mask() {
    awk -v p="$1" 'BEGIN { if (p !~ /^[0-9]+$/ || p > 32) exit 1
        for (i = 0; i < 4; i++) { b = (p >= 8) ? 8 : (p > 0 ? p : 0); p -= b; m = m (i ? "." : "") (256 - 2 ^ (8 - b)) % 256 }
        print m }'
}

conf_get() { sed -n "s/^$1=//p" "$2" | head -n 1; }

conf_parse() {
    # conf_parse FILE PLAN: validated plan lines (key=value) or error=conf_<what>.
    [ -s "$1" ] && [ "$(wc -c < "$1")" -le 16384 ] || die conf_empty 64
    cp_raw="$2.raw"
    awk '
        { sub(/\r$/, ""); line = $0; sub(/^[ \t]+/, "", line); sub(/[ \t]+$/, "", line) }
        line == "" || substr(line, 1, 1) == "#" || substr(line, 1, 1) == ";" { next }
        line ~ /^\[/ { sec = tolower(line); if (sec == "[peer]") peers++; next }
        { i = index(line, "="); if (!i) { print "error=conf_syntax"; exit }
          k = tolower(substr(line, 1, i - 1)); v = substr(line, i + 1)
          sub(/[ \t]+$/, "", k); sub(/^[ \t]+/, "", v)
          if (sec == "[interface]") print "if." k "=" v
          else if (sec == "[peer]" && peers == 1) print "peer." k "=" v
          else if (sec != "[peer]") { print "error=conf_syntax"; exit } }
        END { if (peers != 1) print "error=conf_peer_count" }' "$1" > "$cp_raw" || die conf_syntax 64
    err=$(sed -n 's/^error=//p' "$cp_raw" | head -n 1)
    [ -z "$err" ] || { rm -f "$cp_raw"; die "$err" 64; }

    priv=$(conf_get if.privatekey "$cp_raw"); wg_key "$priv" || die conf_key_private 64
    pub=$(conf_get peer.publickey "$cp_raw"); wg_key "$pub" || die conf_public_key 64
    psk=$(conf_get peer.presharedkey "$cp_raw"); [ -z "$psk" ] || wg_key "$psk" || die conf_preshared_key 64

    addr=$(conf_get if.address "$cp_raw" | tr ',' '\n' | sed 's/^ *//; s/ *$//' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(/[0-9]+)?$' | head -n 1)
    [ -n "$addr" ] || die conf_address 64
    ip=${addr%/*}; bits=32; [ "$ip" = "$addr" ] || bits=${addr#*/}
    printf '%s\n' "$ip" | awk -F. '{for (i = 1; i <= 4; i++) if ($i > 255) exit 1}' || die conf_address 64
    mask=$(prefix_mask "$bits") || die conf_address 64

    ep=$(conf_get peer.endpoint "$cp_raw")
    host=${ep%:*} port=${ep##*:}
    case "$host" in ''|*[!A-Za-z0-9.-]*) die conf_endpoint 64 ;; esac
    case "$port" in ''|*[!0-9]*) die conf_endpoint 64 ;; esac
    [ "$port" -ge 1 ] && [ "$port" -le 65535 ] || die conf_endpoint 64

    mtu=$(conf_get if.mtu "$cp_raw")
    [ -z "$mtu" ] || valid_int_range "$mtu" 1280 1500 || die conf_mtu 64
    ka=$(conf_get peer.persistentkeepalive "$cp_raw")
    [ -z "$ka" ] || valid_int_range "$ka" 0 65535 || die conf_keepalive 64
    allowed=$(conf_get peer.allowedips "$cp_raw"); [ -n "$allowed" ] || allowed=0.0.0.0/0

    {
        echo "private=$priv"; echo "peer=$pub"; [ -z "$psk" ] || echo "psk=$psk"
        echo "address=$ip $mask"; echo "endpoint=$host:$port"
        [ -z "$mtu" ] || echo "mtu=$mtu"
        [ -z "$ka" ] || [ "$ka" = 0 ] || echo "keepalive=$ka"
    } > "$2" || die write_failed
    printf '%s\n' "$allowed" | tr ',' '\n' | sed 's/^ *//; s/ *$//' | while IFS= read -r a; do
        case "$a" in
            ::/0) echo "allow=:: 0" ;;
            *:*|'') ;;
            */*) m=$(prefix_mask "${a#*/}") || exit 1; echo "allow=${a%/*} $m" ;;
            *) echo "allow=$a 255.255.255.255" ;;
        esac
    done >> "$2" || die conf_allowed_ips 64

    # AmneziaWG, in Keenetic's order: jc jmin jmax s1 s2 h1 h2 h3 h4 [s3 s4 [i1..i5]].
    if [ -n "$(conf_get if.jc "$cp_raw")" ]; then
        asc=""
        for k in jc jmin jmax s1 s2; do
            v=$(conf_get "if.$k" "$cp_raw"); [ -n "$v" ] || v=0
            case "$v" in *[!0-9]*) die conf_awg 64 ;; esac
            asc="$asc $v"
        done
        n=1
        for k in h1 h2 h3 h4; do
            v=$(conf_get "if.$k" "$cp_raw"); [ -n "$v" ] || v=$n
            n=$((n + 1))
            printf '%s\n' "$v" | grep -Eq '^[0-9]+(-[0-9]+)?$' || die conf_awg 64
            asc="$asc $v"
        done
        s3=$(conf_get if.s3 "$cp_raw") s4=$(conf_get if.s4 "$cp_raw") ilast=0
        for n in 1 2 3 4 5; do [ -z "$(conf_get "if.i$n" "$cp_raw")" ] || ilast=$n; done
        if [ -n "$s3$s4" ] || [ "$ilast" != 0 ]; then
            for v in "${s3:-0}" "${s4:-0}"; do
                case "$v" in *[!0-9]*) die conf_awg 64 ;; esac
                asc="$asc $v"
            done
            n=1
            while [ "$n" -le "$ilast" ]; do
                v=$(conf_get "if.i$n" "$cp_raw")
                case "$v" in *'"'*|*"$(printf '\134')"*) die conf_awg 64 ;; esac
                [ "${#v}" -le 4096 ] || die conf_awg 64
                asc="$asc \"$v\""
                n=$((n + 1))
            done
        fi
        echo "asc=${asc# }" >> "$2"
    fi
    rm -f "$cp_raw"
}

tunnel_block() {
    # tunnel_block NAME: the interface block of the running configuration.
    awk -v n="interface $1" '$0 == n {on = 1; next} on && /^!/ {exit} on {print}' "$RUNCFG"
}

tunnel_names() {
    { printf '%s\n' "${VWARD_TUNNEL_INTERFACE:-}"
      vward_map_tunnels "$(vward_device_map 2>/dev/null)" | awk '{print $1}'; } | awk 'NF && !s[$0]++'
}
is_tunnel() { tunnel_names | grep -qxF -- "$1"; }

free_tunnel_name() {
    n=0
    while [ "$n" -lt 32 ]; do
        grep -qx "interface Wireguard$n" "$RUNCFG" || { printf 'Wireguard%s\n' "$n"; return 0; }
        n=$((n + 1))
    done
    return 1
}

apply_plan() {
    # apply_plan IFACE PLAN ADDRESS: interface settings and its one peer.
    ndm_secret "interface $1 wireguard private-key $(conf_get private "$2")" || die conf_rejected_key
    ndm "interface $1 ip address $3" || die conf_rejected_address
    m=$(conf_get mtu "$2"); [ -z "$m" ] || ndm "interface $1 ip mtu $m" || die conf_rejected_mtu
    a=$(conf_get asc "$2")
    if [ -n "$a" ]; then ndm "interface $1 wireguard asc $a" || die conf_rejected_awg
    else ndm "no interface $1 wireguard asc" || :; fi
    p=$(conf_get peer "$2")
    ndm "interface $1 wireguard peer $p" || die conf_rejected_peer
    ndm "interface $1 wireguard peer $p endpoint $(conf_get endpoint "$2")" || die conf_rejected_endpoint
    k=$(conf_get keepalive "$2")
    ndm "interface $1 wireguard peer $p keepalive-interval ${k:-25}" || die conf_rejected_keepalive
    s=$(conf_get psk "$2"); [ -z "$s" ] || ndm_secret "interface $1 wireguard peer $p preshared-key $s" || die conf_rejected_preshared_key
    sed -n 's/^allow=//p' "$2" | while IFS= read -r al; do
        ndm "interface $1 wireguard peer $p allow-ips $al" || exit 1
    done || die conf_rejected_allowed_ips
    ndm "interface $1 wireguard peer $p connect" || die conf_rejected_connect
    ndm "interface $1 up" || die conf_rejected_up
}

handshake_ok() {
    # handshake_ok IFACE: the server answered within the wait.
    hs_curl=${VWARD_CURL_BIN:-curl} hs_w=0
    while [ "$hs_w" -le "$HANDSHAKE_WAIT" ]; do
        "$hs_curl" -s --max-time 3 "${VWARD_RCI_BASE:-http://127.0.0.1:79/rci}/show/interface?name=$1" 2>/dev/null |
            "$JQ" -e '[.wireguard.peer[]? | select(.online == true and ((.["last-handshake"] // 999999) | tonumber) < 120)] | length > 0' >/dev/null 2>&1 && return 0
        sleep 2
        hs_w=$((hs_w + 2))
    done
    return 1
}

tunnel_test() {
    # tunnel_test PLAN: prove the configuration on a temporary interface, then remove it.
    TMP_IF=$(free_tunnel_name) || die no_free_tunnel
    ndm "interface $TMP_IF" || die router_rejected
    echo "no interface $TMP_IF" >> "$JOURNAL"
    ndm "interface $TMP_IF description \"VWARD test\"" || :
    apply_plan "$TMP_IF" "$1" "$TEST_ADDRESS"
    handshake_ok "$TMP_IF" || die tunnel_no_handshake
    ndm "no interface $TMP_IF" || die router_rejected
    grep -vx "no interface $TMP_IF" "$JOURNAL" > "$JOURNAL.t"; mv -f "$JOURNAL.t" "$JOURNAL"
    snapshot
}

store_conf() {
    # store_conf IFACE FILE: keep the applied .conf, the last three, root-only.
    sc_dir="$TUNNEL_STORE/$1"
    (umask 077; mkdir -p "$sc_dir") || return 1
    if [ -f "$sc_dir/current.conf" ]; then
        [ ! -f "$sc_dir/prev1.conf" ] || mv -f "$sc_dir/prev1.conf" "$sc_dir/prev2.conf"
        mv -f "$sc_dir/current.conf" "$sc_dir/prev1.conf"
    fi
    cp "$2" "$sc_dir/current.conf" && chmod 0600 "$sc_dir/current.conf"
}

tunnel_summary() {
    # Plain facts about a plan for the Console, never the keys.
    printf 'info.endpoint=%s\n' "$(conf_get endpoint "$1")"
    printf 'info.address=%s\n' "$(conf_get address "$1" | awk '{print $1}')"
    printf 'info.mtu=%s\n' "$(conf_get mtu "$1")"
    printf 'info.keepalive=%s\n' "$(conf_get keepalive "$1")"
    printf 'info.awg=%s\n' "$([ -n "$(conf_get asc "$1")" ] && echo 1 || echo 0)"
    printf 'info.allowed=%s\n' "$(sed -n 's/^allow=//p' "$1" | tr '\n' ',' | sed 's/,$//')"
}

op_tunnel_conf() {
    # tunnel-conf check|replace|create FILE [NAME | DESCRIPTION]
    tc_mode=$1 tc_file=$2 tc_arg=${3:-}
    case "$tc_file" in /*) ;; *) die invalid_value 64 ;; esac
    [ -f "$tc_file" ] && [ ! -L "$tc_file" ] || die conf_empty 64
    PLAN=$(mktemp /tmp/vward-console-plan.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    TMPFILE=$PLAN
    CONF_FILE=$tc_file
    conf_parse "$tc_file" "$PLAN"
    load_profile_base
    case "$tc_mode" in
        check)
            tunnel_summary "$PLAN"
            done_ok "tunnel-conf check" checked ;;
        replace)
            vward_valid_ndm_name "$tc_arg" && is_tunnel "$tc_arg" || die unknown_tunnel 64
            change_lock
            JOURNAL=$(mktemp /tmp/vward-console-tunnel.XXXXXX 2>/dev/null) || die temporary_file_unavailable
            TXN=1
            snapshot
            tunnel_test "$PLAN"
            new_peer=$(conf_get peer "$PLAN")
            # Undo, replayed newest first: the new peer out, then the old lines back.
            tunnel_block "$tc_arg" | awk -v i="$tc_arg" '
                $1 == "wireguard" && $2 == "peer" {peer = $3; print "interface " i " wireguard peer " peer; next}
                peer != "" && /^        [a-z]/ {sub(/^ +/, ""); print "interface " i " wireguard peer " peer " " $0; next}
                /^    !/ {peer = ""; next}
                $1 == "wireguard" && $2 == "asc" {sub(/^ +/, ""); print "interface " i " " $0; next}
                $1 == "ip" && ($2 == "address" || $2 == "mtu") {sub(/^ +/, ""); print "interface " i " " $0}' > "$JOURNAL.old"
            old_peers=$(tunnel_block "$tc_arg" | awk '$1 == "wireguard" && $2 == "peer" {print $3}')
            prev="$TUNNEL_STORE/$tc_arg/current.conf"
            if [ -f "$prev" ]; then
                PREVPLAN=$(mktemp /tmp/vward-console-plan.XXXXXX 2>/dev/null) || die temporary_file_unavailable
                if ( conf_parse "$prev" "$PREVPLAN" ) >/dev/null 2>&1; then
                    echo "interface $tc_arg wireguard private-key $(conf_get private "$PREVPLAN")" >> "$JOURNAL"
                fi
                rm -f "$PREVPLAN"
            fi
            cat "$JOURNAL.old" >> "$JOURNAL"
            echo "no interface $tc_arg wireguard peer $new_peer" >> "$JOURNAL"
            for op in $old_peers; do
                [ "$op" = "$new_peer" ] || ndm "no interface $tc_arg wireguard peer $op" || die router_rejected
            done
            apply_plan "$tc_arg" "$PLAN" "$(conf_get address "$PLAN")"
            handshake_ok "$tc_arg" || die tunnel_no_handshake
            save_router || die config_save_failed
            TXN=0
            store_conf "$tc_arg" "$tc_file" || audit "tunnel $tc_arg conf not stored"
            rm -f "$JOURNAL.old" "$TUNNEL_HEALTH_STATE"
            tunnel_summary "$PLAN"
            done_ok "tunnel-conf replace $tc_arg endpoint=$(conf_get endpoint "$PLAN")" changed ;;
        create)
            case "$tc_arg" in @/*) tc_desc_file=${tc_arg#@}; tc_arg=$(cat "$tc_desc_file" 2>/dev/null); rm -f "$tc_desc_file" ;; esac
            case "$tc_arg" in *'"'*|*"$(printf '\134')"*) die invalid_description 64 ;; esac
            [ -n "$tc_arg" ] && [ "${#tc_arg}" -le 64 ] || die invalid_description 64
            change_lock
            JOURNAL=$(mktemp /tmp/vward-console-tunnel.XXXXXX 2>/dev/null) || die temporary_file_unavailable
            TXN=1
            snapshot
            NEW_IF=$(free_tunnel_name) || die no_free_tunnel
            ndm "interface $NEW_IF" || die router_rejected
            echo "no interface $NEW_IF" >> "$JOURNAL"
            ndm "interface $NEW_IF description \"$tc_arg\"" || die invalid_description
            ndm "interface $NEW_IF security-level public" || die router_rejected
            ndm "interface $NEW_IF ip tcp adjust-mss pmtu" || :
            apply_plan "$NEW_IF" "$PLAN" "$(conf_get address "$PLAN")"
            handshake_ok "$NEW_IF" || die tunnel_no_handshake
            save_router || die config_save_failed
            TXN=0
            store_conf "$NEW_IF" "$tc_file" || audit "tunnel $NEW_IF conf not stored"
            rm -f "$VWARD_DEVICE_MAP_CACHE"
            printf 'info.name=%s\n' "$NEW_IF"
            tunnel_summary "$PLAN"
            done_ok "tunnel-conf create $NEW_IF endpoint=$(conf_get endpoint "$PLAN")" changed ;;
        *) die invalid_operation 64 ;;
    esac
}

op_tunnel_delete() {
    # tunnel-delete NAME TARGET: move its lists and subnets to TARGET (bypass, vpn
    # or another tunnel), then remove the interface.  The VWARD tunnel stays.
    load_profile_base
    vward_valid_ndm_name "$1" && is_tunnel "$1" || die unknown_tunnel 64
    [ "$1" != "$VWARD_TUNNEL_INTERFACE" ] || die main_tunnel 64
    case "$2" in
        bypass) td_to=- ;;
        vpn) td_to=$VWARD_TUNNEL_INTERFACE ;;
        *) vward_valid_ndm_name "$2" && is_tunnel "$2" && [ "$2" != "$1" ] || die unknown_tunnel 64
           td_to=$2 ;;
    esac
    change_lock
    JOURNAL=$(mktemp /tmp/vward-console-tunnel.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    TXN=1
    snapshot
    td_wan=$(wan_route_target)
    # dns-proxy lists: the new route first, then the old one out.
    awk -v i="$1" '/^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1)} /^!/ {ctx = 0}
        ctx && $1 == "route" && $2 == "object-group" && $4 == i {print $3}' "$RUNCFG" > "$JOURNAL.lists"
    while IFS= read -r g; do
        [ -n "$g" ] || continue
        nt=$td_to; [ "$nt" != - ] || nt=$td_wan
        ndm "dns-proxy route object-group $g $nt auto" || die router_rejected
        echo "dns-proxy no route object-group $g $nt" >> "$JOURNAL"
        ndm "dns-proxy no route object-group $g $1" || die router_rejected
        echo "dns-proxy route object-group $g $1 auto" >> "$JOURNAL"
    done < "$JOURNAL.lists"
    # Static subnets: to another tunnel, or simply out (the default route is the provider).
    awk -v i="$1" '$1 == "ip" && $2 == "route" && $5 == i {print $3 " " $4}' "$RUNCFG" > "$JOURNAL.nets"
    while IFS= read -r net; do
        [ -n "$net" ] || continue
        if [ "$td_to" != - ]; then
            ndm "ip route $net $td_to auto" || die router_rejected
            echo "no ip route $net $td_to" >> "$JOURNAL"
        fi
        ndm "no ip route $net $1" || die router_rejected
        echo "ip route $net $1 auto" >> "$JOURNAL"
    done < "$JOURNAL.nets"
    snapshot
    while IFS= read -r g; do [ -z "$g" ] || ! route_present "$g" "$1" || die verification_failed; done < "$JOURNAL.lists"
    ! awk -v i="$1" '$1 == "ip" && $2 == "route" && $5 == i {f = 1} END {exit f ? 0 : 1}' "$RUNCFG" || die verification_failed
    # Last step: nothing depends on the interface any more.
    ndm "no interface $1" || die router_rejected
    snapshot
    ! grep -qx "interface $1" "$RUNCFG" || die verification_failed
    save_router || die config_save_failed
    TXN=0
    td_lists=$(grep -c . "$JOURNAL.lists") td_nets=$(grep -c . "$JOURNAL.nets")
    rm -f "${TUNNEL_STORE:?}/$1/"*.conf "$VWARD_DEVICE_MAP_CACHE" "$JOURNAL.lists" "$JOURNAL.nets"
    rmdir "${TUNNEL_STORE:?}/$1" 2>/dev/null
    done_ok "tunnel-delete $1 lists=$td_lists subnets=$td_nets to=$2" changed
}

subnet_present() {
    awk -v n="$1" -v m="$2" -v i="$3" '$1 == "ip" && $2 == "route" && $3 == n && $4 == m && $5 == i {f = 1} END {exit f ? 0 : 1}' "$RUNCFG"
}

op_tunnel_subnet() {
    # tunnel-subnet NAME add|remove CIDR (IPv4, /8 or narrower).
    load_profile_base
    vward_valid_ndm_name "$1" && is_tunnel "$1" || die unknown_tunnel 64
    ts_net=${3%/*} ts_bits=32
    [ "$ts_net" = "$3" ] || ts_bits=${3#*/}
    printf '%s\n' "$ts_net" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' || die invalid_subnet 64
    printf '%s\n' "$ts_net" | awk -F. '{for (i = 1; i <= 4; i++) if ($i > 255) exit 1}' || die invalid_subnet 64
    ts_mask=$(prefix_mask "$ts_bits") || die invalid_subnet 64
    [ "$ts_bits" -ge 8 ] || die invalid_subnet 64
    change_lock
    snapshot
    ts_have=0; subnet_present "$ts_net" "$ts_mask" "$1" && ts_have=1
    case "$2" in
        add) [ "$ts_have" = 0 ] || done_ok "tunnel-subnet $1 add $3" unchanged
             ndm "ip route $ts_net $ts_mask $1 auto" || die router_rejected ;;
        remove) [ "$ts_have" = 1 ] || done_ok "tunnel-subnet $1 remove $3" unchanged
             ndm "no ip route $ts_net $ts_mask $1" || die router_rejected ;;
        *) die invalid_value 64 ;;
    esac
    snapshot
    ts_now=0; subnet_present "$ts_net" "$ts_mask" "$1" && ts_now=1
    [ "$ts_now" != "$ts_have" ] || die verification_failed
    save_router || die config_save_failed
    done_ok "tunnel-subnet $1 $2 $ts_net/$ts_bits" changed
}

# ---------- Backups of VWARD's own settings ----------
#
# A snapshot holds /opt/etc/vward (settings, domain lists state, Smart DNS and
# tunnel configurations, AdGuard Home login) without the nightly catalogs, the
# AdaptiveAuto domains, and the router's running configuration as a reference
# copy.  Snapshots are root-only; the newest seven are kept.  A restore puts the
# VWARD files back (after a snapshot of the current state); the router
# configuration is never applied automatically.

SNAPSHOT_DIR=${VWARD_SNAPSHOT_DIR:-/opt/var/backups/vward/snapshots}
SNAPSHOT_KEEP=7

snapshot_name_ok() { printf '%s\n' "$1" | grep -Eq '^vward-[0-9]{8}-[0-9]{6}(-[a-z]+)?\.tar\.gz$'; }

op_backup_create() {
    # backup-create manual|auto|prerestore: auto only when the newest is a day old.
    case "$1" in manual|auto|prerestore) ;; *) die invalid_value 64 ;; esac
    (umask 077; mkdir -p "$SNAPSHOT_DIR") || die write_failed
    if [ "$1" = auto ]; then
        bc_last=$(ls -1 "$SNAPSHOT_DIR" 2>/dev/null | grep -E '^vward-[0-9]{8}-[0-9]{6}' | sort | tail -n 1)
        if [ -n "$bc_last" ]; then
            bc_age=$(( $(date +%s) - $(date -r "$SNAPSHOT_DIR/$bc_last" +%s 2>/dev/null || echo 0) ))
            [ "$bc_age" -ge 82800 ] || done_ok "backup-create auto" unchanged
        fi
    fi
    bc_stage=$(mktemp -d /tmp/vward-backup.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    TMPFILE=$bc_stage.tar.gz
    mkdir -p "$bc_stage/etc" "$bc_stage/state" || die write_failed
    ( cd "$ETC" && tar -cf - . ) | ( cd "$bc_stage/etc" && tar -xf - ) || { rm -rf "${bc_stage:?}"; die backup_failed; }
    # Regenerated every night, and large.
    rm -f "$bc_stage/etc/route-engine/hints-catalog.tsv" "$bc_stage/etc/route-engine/hints-includes.tsv"
    [ ! -f "$PERSIST" ] || cp "$PERSIST" "$bc_stage/state/adaptive-persist.txt"
    "$NDMC" -c "show running-config" > "$bc_stage/router-running-config.txt" 2>/dev/null || rm -f "$bc_stage/router-running-config.txt"
    { echo "created=$(date '+%Y-%m-%dT%H:%M:%S%z')"; echo "kind=$1"
      echo "version=$(sed -n 1p "${VWARD_VERSION_FILE:-/opt/share/vward/VERSION}" 2>/dev/null)"; } > "$bc_stage/backup.meta"
    bc_name="vward-$(date '+%Y%m%d-%H%M%S')"
    [ "$1" = manual ] || bc_name="$bc_name-$1"
    ( umask 077; cd "$bc_stage" && tar -czf "$TMPFILE" . ) || { rm -rf "${bc_stage:?}"; die backup_failed; }
    rm -rf "${bc_stage:?}"
    tar -tzf "$TMPFILE" >/dev/null 2>&1 || die backup_failed
    chmod 0600 "$TMPFILE" && mv -f "$TMPFILE" "$SNAPSHOT_DIR/$bc_name.tar.gz" || die write_failed
    TMPFILE=
    ls -1 "$SNAPSHOT_DIR" 2>/dev/null | grep -E '^vward-[0-9]{8}-[0-9]{6}.*\.tar\.gz$' | sort -r | awk -v k="$SNAPSHOT_KEEP" 'NR > k' |
        while IFS= read -r old; do rm -f "$SNAPSHOT_DIR/$old"; done
    printf 'info.name=%s.tar.gz\n' "$bc_name"
    done_ok "backup-create $1 $bc_name" changed
}

op_backup_restore() {
    # backup-restore NAME: VWARD files back as they were in the snapshot.
    snapshot_name_ok "$1" || die invalid_backup 64
    br_file="$SNAPSHOT_DIR/$1"
    [ -f "$br_file" ] && [ ! -L "$br_file" ] || die unknown_backup 64
    br_stage=$(mktemp -d /tmp/vward-restore.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    tar -xzf "$br_file" -C "$br_stage" 2>/dev/null || { rm -rf "${br_stage:?}"; die backup_damaged; }
    [ -d "$br_stage/etc" ] && [ -f "$br_stage/backup.meta" ] || { rm -rf "${br_stage:?}"; die backup_damaged; }
    # Nothing outside the snapshot's etc/ and state/ is taken; no links.
    if find "$br_stage" -type l | grep -q .; then rm -rf "${br_stage:?}"; die backup_damaged; fi
    # The current state first, so the restore itself can be undone.
    ( op_backup_create prerestore ) >/dev/null || { rm -rf "${br_stage:?}"; die backup_failed; }
    # The update key stays the installed one: a snapshot must not change who signs updates.
    rm -f "$br_stage/etc/update-public.pem"
    ( cd "$br_stage/etc" && tar -cf - . ) | ( cd "$ETC" && tar -xf - ) || { rm -rf "${br_stage:?}"; die restore_failed; }
    if [ -f "$br_stage/state/adaptive-persist.txt" ]; then
        mkdir -p "$ROUTE_STATE" && cp "$br_stage/state/adaptive-persist.txt" "$PERSIST" || { rm -rf "${br_stage:?}"; die restore_failed; }
    fi
    rm -rf "${br_stage:?}"
    rm -f "$VWARD_DEVICE_MAP_CACHE"
    mkdir -p "$ROUTE_STATE" 2>/dev/null && echo 0 > "$REFRESH_TS" 2>/dev/null
    done_ok "backup-restore $1" changed
}

# ---------- Wi-Fi clients: name and internet access ----------
#
# wifi-host MAC name @FILE      the device's name in Keenetic ("known host"),
#                               which also registers it; the name comes from a
#                               file so it may hold spaces and Cyrillic.
# wifi-host MAC access permit|deny   internet access of the device.
op_wifi_host() {
    wh_mac=$(printf '%s' "$1" | tr 'A-F' 'a-f')
    printf '%s\n' "$wh_mac" | grep -Eq '^([0-9a-f]{2}:){5}[0-9a-f]{2}$' || die invalid_mac 64
    change_lock
    snapshot
    case "$2" in
        name)
            case "$3" in @/*) wh_name=$(cat "${3#@}" 2>/dev/null); rm -f "${3#@}" ;; *) die invalid_value 64 ;; esac
            case "$wh_name" in ''|*'"'*|*"$(printf '\134')"*) die invalid_name 64 ;; esac
            [ "${#wh_name}" -le 64 ] || die invalid_name 64
            if awk -v m="$wh_mac" -v n="$wh_name" '$1 == "known" && $2 == "host" && tolower($NF) == m {l = $0; sub(/^known host "?/, "", l); sub(/"? [^ ]+$/, "", l); if (l == n) f = 1} END {exit f ? 0 : 1}' "$RUNCFG"; then
                done_ok "wifi-host $wh_mac name" unchanged
            fi
            ndm "known host \"$wh_name\" $wh_mac" || die router_rejected
            snapshot
            awk -v m="$wh_mac" '$1 == "known" && $2 == "host" && tolower($NF) == m {f = 1} END {exit f ? 0 : 1}' "$RUNCFG" || die verification_failed ;;
        access)
            case "$3" in permit|deny) ;; *) die invalid_value 64 ;; esac
            wh_now=$(awk -v m="$wh_mac" '$1 == "host" && tolower($2) == m && ($3 == "permit" || $3 == "deny") {print $3}' "$RUNCFG" | tail -n 1)
            [ "$wh_now" != "$3" ] || done_ok "wifi-host $wh_mac access $3" unchanged
            ndm "ip hotspot host $wh_mac $3" || die router_rejected
            snapshot
            [ "$(awk -v m="$wh_mac" '$1 == "host" && tolower($2) == m && ($3 == "permit" || $3 == "deny") {print $3}' "$RUNCFG" | tail -n 1)" = "$3" ] || die verification_failed ;;
        *) die invalid_setting 64 ;;
    esac
    save_router || die config_save_failed
    done_ok "wifi-host $wh_mac $2" changed
}

# smartdns-guard 0|1: 0 lets AdaptiveAuto take Smart DNS domains again.
op_smartdns_guard() {
    case "$1" in 0|1) ;; *) die invalid_value 64 ;; esac
    set_kv "$LISTS_CONF" smartdns_guard "$1" 0644 || done_ok "smartdns-guard $1" unchanged
    mkdir -p "$ROUTE_STATE" 2>/dev/null && echo 0 > "$REFRESH_TS" 2>/dev/null
    done_ok "smartdns-guard $1" changed
}

# ---------- Components ----------
#
# Disabling a component also disables everything that requires it running
# (requires_running, transitively); enabling one also enables what it requires.
# Core components are never disabled.  Files stay installed; entry points check
# <id>.disabled through vward_component_gate.

component_closure() {
    # component_closure ID 0|1: the affected component ids, one per line.
    "$JQ" -r --arg id "$1" --arg mode "$2" '
        . as $r
        | def step($s):
            if $mode == "0" then [$r.components[] | select(any(.requires_running[]?; IN($s[]))) | .id]
            else [$r.components[] | select(.id | IN($s[])) | .requires_running[]?] end;
        [$id] | until((step(.) - .) == []; . + (step(.) - .) | unique) | .[]' "$COMPONENT_REGISTRY"
}

op_component() {
    case "$1" in ''|*[!a-z0-9-]*) die invalid_component 64 ;; esac
    case "$2" in 0|1) ;; *) die invalid_value 64 ;; esac
    [ -r "$COMPONENT_REGISTRY" ] || die registry_unavailable
    "$JQ" -e --arg id "$1" 'any(.components[]; .id == $id)' "$COMPONENT_REGISTRY" >/dev/null 2>&1 || die invalid_component 64
    set_ids=$(component_closure "$1" "$2") || die registry_unavailable
    if [ "$2" = 0 ]; then
        for c in $set_ids; do
            "$JQ" -e --arg id "$c" 'any(.components[]; .id == $id and .core == true)' "$COMPONENT_REGISTRY" >/dev/null &&
                die core_component 64
        done
        # A guard that holds the tunnel down must restore it before it stops.
        case " $(echo $set_ids) " in *" tunnel-guard "*)
            [ "$(awk -F= '$1=="FAILOPEN_ACTIVE"{print $2}' "$TUNNEL_GUARD_STATE" 2>/dev/null)" != 1 ] || die failopen_active ;;
        esac
    fi
    changed=
    mkdir -p "$COMPONENT_STATE" || die write_failed
    for c in $set_ids; do
        flag="$COMPONENT_STATE/$c.disabled"
        if [ "$2" = 0 ] && [ ! -e "$flag" ]; then
            printf 'disabled from VWARD Console %s (with %s)\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$1" > "$flag" || die write_failed
            changed="$changed $c"
        elif [ "$2" = 1 ] && [ -e "$flag" ]; then
            rm -f "$flag" || die write_failed
            changed="$changed $c"
        fi
    done
    [ -n "$changed" ] || done_ok "component $1 enabled=$2" unchanged
    # The route engine is a daemon; the other components are driven by cron.
    case " $changed " in *" route-engine "*)
        if [ -x "$ROUTE_ENGINE_INIT" ]; then
            if [ "$2" = 0 ]; then "$ROUTE_ENGINE_INIT" stop; else "$ROUTE_ENGINE_INIT" start; fi </dev/null >/dev/null 2>&1 || true
        fi ;;
    esac
    echo "affected=$(echo $changed | tr ' ' ',')"
    done_ok "component $1 enabled=$2 affected=$(echo $changed | tr ' ' ',')" changed
}

# ---------- Entry ----------

# An uploaded .conf goes away with the helper whatever happens next, a refused
# or failed call included: it holds the tunnel's private key.
if [ "${1:-}" = tunnel-conf ]; then
    case "${3:-}" in /*) [ ! -f "$3" ] || [ -L "$3" ] || CONF_FILE=$3 ;; esac
fi
[ "$#" -ge 2 ] && [ "$#" -le 4 ] || die usage 64
OP=$1; shift
case "$OP" in
    tunnel-guard|wan-guard|tunnel|update-feed|adaptive-mode|classifier|console-auth|console-devices|smartdns-guard|backup-create|backup-restore) [ "$#" -eq 1 ] || die usage 64 ;;
    tunnel-conf) [ "$#" -eq 2 ] || [ "$#" -eq 3 ] || die usage 64 ;;
    tunnel-subnet) [ "$#" -eq 3 ] || die usage 64 ;;
    wifi-host) [ "$#" -eq 3 ] || die usage 64 ;;
    *) [ "$#" -eq 2 ] || die usage 64 ;;
esac
ARG1=$(printf '%s' "$1" | tr 'A-Z' 'a-z')
ARG2=${2:-}
case "$OP" in wifi|update|wan-param|tunnel|domain-list|domain-list-watch|tunnel-conf|tunnel-delete|tunnel-subnet|backup-restore|wifi-host) ARG1=$1 ;; esac
ARG3=${3:-}
case "$OP" in route-domain|force-vpn|adaptive) ARG2=$(printf '%s' "$ARG2" | tr 'A-Z' 'a-z') ;; esac

ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
[ -r "$ADMISSION_LIB" ] || die admission_unavailable
. "$ADMISSION_LIB"
vward_admission_enter console-config || die updater_busy 75

case "$OP" in
    route-domain) op_route_domain "$ARG1" "$ARG2" ;;
    force-vpn) op_force_vpn "$ARG1" "$ARG2" ;;
    adaptive) op_adaptive "$ARG1" "$ARG2" ;;
    domain-category) op_domain_category "$ARG1" "$ARG2" ;;
    tunnel-guard) op_guard_flag tunnel-guard "$TUNNEL_GUARD_FLAG" "$ARG1" ;;
    wan-guard) op_guard_flag wan-guard "$WAN_GUARD_FLAG" "$ARG1" ;;
    component) op_component "$ARG1" "$ARG2" ;;
    adaptive-mode) op_guard_flag adaptive "$ADAPTIVE_FLAG" "$ARG1" ;;
    classifier) case "$ARG1" in 0|1) ;; *) die invalid_value 64 ;; esac
        set_kv "$CLASSIFIER_FILE" CLASSIFIER_ENABLED "$ARG1" 0600 || done_ok "classifier enabled=$ARG1" unchanged
        done_ok "classifier enabled=$ARG1" changed ;;
    ip-category) op_ip_category "$ARG1" "$ARG2" ;;
    console-auth) case "$ARG1" in 0|1) ;; *) die invalid_value 64 ;; esac
        set_kv "$AUTH_CONF" AUTH_ENABLED "$ARG1" 0600 || done_ok "console-auth enabled=$ARG1" unchanged
        done_ok "console-auth enabled=$ARG1" changed ;;
    # Only devices registered in Keenetic may open VWARD.  Recovery over SSH:
    # vward-console-config.sh console-devices 0
    console-devices) case "$ARG1" in 0|1) ;; *) die invalid_value 64 ;; esac
        set_kv "$AUTH_CONF" DEVICES_ONLY "$ARG1" 0600 || done_ok "console-devices only_registered=$ARG1" unchanged
        done_ok "console-devices only_registered=$ARG1" changed ;;
    update-feed) op_update_feed "$ARG1" ;;
    tunnel) op_tunnel "$ARG1" ;;
    domain-list) op_domain_list "$ARG1" "$ARG2" ;;
    domain-list-watch) op_domain_list_watch "$ARG1" "$ARG2" ;;
    smartdns-guard) op_smartdns_guard "$ARG1" ;;
    wifi) op_wifi "$ARG1" "$ARG2" ;;
    update) op_update "$ARG1" "$ARG2" ;;
    wan-param) op_wan_param "$ARG1" "$ARG2" ;;
    tunnel-conf) op_tunnel_conf "$ARG1" "$ARG2" "$ARG3" ;;
    backup-create) op_backup_create "$ARG1" ;;
    wifi-host) op_wifi_host "$ARG1" "$ARG2" "$ARG3" ;;
    backup-restore) op_backup_restore "$ARG1" ;;
    tunnel-delete) op_tunnel_delete "$ARG1" "$ARG2" ;;
    tunnel-subnet) op_tunnel_subnet "$ARG1" "$ARG2" "$ARG3" ;;
    *) die invalid_operation 64 ;;
esac
