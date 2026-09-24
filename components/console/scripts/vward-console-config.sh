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

die() { printf 'error=%s\n' "$1"; exit "${2:-1}"; }

cleanup() {
    if [ "$TXN" = 1 ]; then
        TXN=0
        tunnel_undo || { audit "tunnel rollback incomplete"; printf 'error=rollback_incomplete\n'; }
    fi
    [ -z "$TMPFILE" ] || rm -f "$TMPFILE"
    [ -z "$RUNCFG" ] || rm -f "$RUNCFG"
    [ -z "$JOURNAL" ] || rm -f "$JOURNAL" "$JOURNAL.moves" "$JOURNAL.doh"
    [ -z "$DEVCONF_ORIG" ] || rm -f "$DEVCONF_ORIG"
    [ "$POLICY_LOCKED" != 1 ] || rm -rf "$POLICY_STATE/lock"
    [ "$LOCKED" != 1 ] || rm -rf "$CHANGE_LOCK"
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
            rm -rf "$CHANGE_LOCK"
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

op_update() {
    [ -f "$UPDATE_FILE" ] || die config_unavailable
    case "$1" in
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
    mkdir -p "$POLICY_STATE" && mkdir "$POLICY_STATE/lock" 2>/dev/null || die policy_sync_busy 75
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
        echo "$OLD_DEV" > "$POLICY_STATE/owned.interface"
    fi
    rm -f "$TUNNEL_GUARD_STATE" "$TUNNEL_HEALTH_STATE"
    rm -rf "$POLICY_STATE/lock"; POLICY_LOCKED=0
    rm -rf "$CHANGE_LOCK"; LOCKED=0
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

wan_route_target() {
    # Where a list goes around the tunnel when nothing was recorded: the target
    # other lists already use for the ISP, else the WAN interface.
    t=$(awk -v w="$VWARD_WAN_INTERFACE" '/^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1)} /^!/ {ctx = 0}
        ctx && $1 == "route" && $2 == "object-group" && ($4 == "ISP" || $4 == w) {print $4; exit}' "$RUNCFG")
    printf '%s\n' "${t:-$VWARD_WAN_INTERFACE}"
}

op_domain_list() {
    valid_group "$1" || die invalid_group 64
    case "$2" in vpn|bypass) ;; *) die invalid_value 64 ;; esac
    load_profile_base
    G=$1 TUN=$VWARD_TUNNEL_INTERFACE
    vward_valid_ndm_name "$TUN" || die tunnel_unavailable
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

    if [ "$2" = vpn ]; then
        [ "$cur_t" != "$TUN" ] || { TXN=0; done_ok "domain-list $G vpn" unchanged; }
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
        # 3. Verify, then remember how to come back.
        snapshot
        route_present "$G" "$TUN" || die verification_failed
        [ -z "$cur_t" ] || ! route_present "$G" "$cur_t" || die verification_failed
        while IFS= read -r L; do [ -z "$L" ] || ! doh_present "$L" || die verification_failed; done < "$JOURNAL.doh"
        new_tmp "$saved" || die write_failed
        { printf 'route=%s\t%s\n' "${cur_t:--}" "$cur_o"; sed -n 's/^./doh=&/p' "$JOURNAL.doh"; } > "$TMPFILE" || die write_failed
        install_tmp "$saved" 0600 || die write_failed
        detail="route=${cur_t:--}->$TUN doh=$(grep -c . "$JOURNAL.doh")"
    else
        rt=$(sed -n 's/^route=//p' "$saved" 2>/dev/null)
        if [ -n "$rt" ]; then new_t=${rt%%"$tab"*} new_o=${rt#*"$tab"}; else new_t=$(wan_route_target) new_o=auto; fi
        [ "$cur_t" = "$TUN" ] || { TXN=0; done_ok "domain-list $G bypass" unchanged; }
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
        snapshot
        [ "$new_t" = - ] || route_present "$G" "$new_t" || die verification_failed
        ! route_present "$G" "$TUN" || die verification_failed
        while IFS= read -r L; do [ -z "$L" ] || doh_present "$L" || die verification_failed; done < "$JOURNAL.doh"
        detail="route=$TUN->$new_t doh=$(grep -c . "$JOURNAL.doh")"
    fi

    save_router || die config_save_failed
    TXN=0
    [ "$2" = vpn ] || rm -f "$saved"
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

[ "$#" -ge 2 ] && [ "$#" -le 3 ] || die usage 64
OP=$1; shift
case "$OP" in tunnel-guard|wan-guard|tunnel|update-feed|adaptive-mode|classifier|console-auth) [ "$#" -eq 1 ] || die usage 64 ;; *) [ "$#" -eq 2 ] || die usage 64 ;; esac
ARG1=$(printf '%s' "$1" | tr 'A-Z' 'a-z')
ARG2=${2:-}
case "$OP" in wifi|update|tunnel|domain-list|domain-list-watch) ARG1=$1 ;; esac
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
    update-feed) op_update_feed "$ARG1" ;;
    tunnel) op_tunnel "$ARG1" ;;
    domain-list) op_domain_list "$ARG1" "$ARG2" ;;
    domain-list-watch) op_domain_list_watch "$ARG1" "$ARG2" ;;
    wifi) op_wifi "$ARG1" "$ARG2" ;;
    update) op_update "$ARG1" "$ARG2" ;;
    *) die invalid_operation 64 ;;
esac
