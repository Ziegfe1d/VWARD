#!/bin/sh
# VWARD Panel configuration writer.
#
# The only path through which the Panel changes persistent settings.  Every
# operation validates its input against a fixed allowlist, backs the target up,
# writes atomically, verifies the result and records one audit line.  Router
# configuration (FQDN groups) is changed under the shared route change lock and
# rolled back when Keenetic rejects the command or the result does not verify.
#
# Output: "result=changed|unchanged" on success, "error=<code>" on failure.
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
# Who acts: the owner through the Panel, unless an agent calling this helper said who it is.
VWARD_ACTOR=${VWARD_ACTOR:-panel-owner}
export VWARD_ACTOR

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
TUNNEL_FALLBACK_FLAG="$ETC/tunnel-fallback.disabled"
TUNNEL_RETURN_FLAG="$ETC/tunnel-return.disabled"
TUNNEL_AUTO_CONF="$ETC/tunnel-auto.conf"
LISTS_CONF="$ETC/route-engine/domain-lists.conf"
JOURNAL_CONF=${VWARD_JOURNAL_CONF:-$ETC/journal.conf}
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
# VWARD's own tunnel engine (AmneziaWG 3.x the firmware cannot): tunnels it holds.
AWG_ENGINE=${VWARD_AWG_ENGINE_BIN:-/opt/bin/vward-awg-engine.sh}
AWG_TUNNELS=${VWARD_AWG_ETC:-/opt/etc/vward/awg-engine}/tunnels.tsv
# VLESS servers (Xray on a Keenetic «OpkgTun» connection, like the AmneziaWG engine).
VLESS_ENGINE=${VWARD_VLESS_ENGINE_BIN:-/opt/bin/vward-vless-engine.sh}
VLESS_TUNNELS=${VWARD_VLESS_ETC:-/opt/etc/vward/vless-engine}/tunnels.tsv
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
# The download of the official AdGuard Home build (ext-agh-official).
AO_TMP=
# An uploaded .conf holds the private key: it goes away with the helper.
CONF_FILE=
# The request body of ndm_secret while it is sent.
NS_FILE=

# The tunnel and mask of an «ip route» line: Keenetic writes a one-address route without its mask
# («ip route 1.2.3.4 OpkgTun2 auto»); read with $5 it belonged to no tunnel (a Viva 2026-10-12).
ROUTE_AWK='function rdev() {return $4 ~ /^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$/ ? $5 : $4}
function rmask() {return $4 ~ /^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$/ ? $4 : "255.255.255.255"}'

# An engine's reason= line (the refused Keenetic command and its answer) goes on to the
# Panel; it replaces any refusal of our own, so die does not add a second one.
relay_reason() {
    RELAY_REASON=$(printf '%s\n' "$1" | grep '^reason=' | tail -n 1 | cut -c8-)
    [ -z "$RELAY_REASON" ] || printf 'reason=%s\n' "$RELAY_REASON"
    NDM_CMD=
}

# A rejected router command leaves the router's own reply (one line, no quotes or
# control characters) on a reason= line just before the error line.
die() {
    # The command Keenetic refused (never a key: those go through ndm_secret) and its answer.
    # A DoH address carries its owner's token: only its host is shown (Smart DNS lines).
    die_r=
    [ "$1" != router_rejected ] || [ -z "${NDM_CMD:-}" ] ||
        die_r="$(printf '%s' "$NDM_CMD" | sed 's#\(https://[^/ ]*\)/[^ ]*#\1/…#g' | cut -c1-120): ${NDM_REPLY:-no answer}"
    [ -z "$die_r" ] || printf 'reason=%s\n' "$die_r"
    # The journal keeps every refusal with the router's answer (fix.30: a failed tunnel
    # creation left only «rc=1»).
    die_r=${die_r:-${RELAY_REASON:-}}
    audit "${OP:-helper} ${ARG1:-} error=$1${die_r:+ reason=$die_r}"
    printf 'error=%s\n' "$1"; exit "${2:-1}"
}

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
    [ -z "$JOURNAL" ] || rm -f "$JOURNAL.failed" "$JOURNAL.owned" "$JOURNAL.still"
    [ -z "$JOURNAL" ] || rm -f "$JOURNAL" "$JOURNAL.moves" "$JOURNAL.nets" "$JOURNAL.doh" "$JOURNAL.agh" "$JOURNAL.agh.inc" "$JOURNAL.agh.undo"
    [ -z "$DEVCONF_ORIG" ] || rm -f "$DEVCONF_ORIG"
    [ "$POLICY_LOCKED" != 1 ] || rm -rf "$POLICY_STATE/lock"
    [ "$LOCKED" != 1 ] || rm -rf "${CHANGE_LOCK:?}"
    [ "$EDIT_LOCKED" != 1 ] || rm -rf "${EDIT_LOCK:?}"
    [ -z "$AO_TMP" ] || rm -rf "${AO_TMP:?}"
    [ "$EXT_LOCKED" != 1 ] || rm -rf "${EXT_STATE:?}/lock"
    [ -z "${AGH_PLANNED:-}" ] || "$DNS_GUARD" planned-done >/dev/null 2>&1 || :
    # A component operation that failed: its own steps undone, the mark and the lock go.
    if [ "${COMP_LOCKED:-0}" = 1 ]; then comp_undo; rm -f "$COMP_PENDING"; rm -rf "${COMP_LOCK:?}"; fi
    # The owner's AdGuard Home login the Panel handed over: gone with the operation that used it.
    [ "${OP:-}" != agh-component ] || case "${VWARD_AGH_CRED_FILE:-}" in /tmp/vward-agh-cred.*) rm -f "$VWARD_AGH_CRED_FILE" ;; esac
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

# A change done (a background job finishes after its request) drops the Panel's short cache
# of the router's answers, so the next page shows the router as it is now.
done_ok() {
    [ "$2" != changed ] || rm -rf "${VWARD_CONSOLE_CACHE_DIR:-/tmp/vward-console-cache}" "${VWARD_KCACHE:-${VWARD_ROOT_PREFIX:-}/tmp/vward-keenetic}/running-config" 2>/dev/null
    audit "$1 result=$2"; printf 'result=%s\n' "$2"; exit 0
}

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

# dir_lock DIR: the lock DIR for this process, waiting up to 10 s for another holder.
# A holder that is gone (its pid dead), or a lock without a pid for 3 s (its holder was
# killed between mkdir and writing the pid), is taken over.
dir_lock() {
    dl_n=0 dl_nopid=0
    while ! mkdir "$1" 2>/dev/null; do
        dl_old=
        read -r dl_old 2>/dev/null < "$1/pid" || :
        if [ -n "$dl_old" ] && ! kill -0 "$dl_old" 2>/dev/null; then
            rm -rf "${1:?}"
            continue
        fi
        if [ -z "$dl_old" ]; then
            dl_nopid=$((dl_nopid + 1))
            [ "$dl_nopid" -lt 3 ] || { rm -rf "${1:?}"; dl_nopid=0; continue; }
        else
            dl_nopid=0
        fi
        dl_n=$((dl_n + 1))
        [ "$dl_n" -lt 10 ] || return 1
        sleep 1
    done
    echo $$ > "$1/pid"
}

change_lock() {
    dir_lock "$CHANGE_LOCK" || die route_change_busy 75
    LOCKED=1
}

# Quick edits of VWARD's own files (read, change, write back) go one at a time: two tabs
# or quick clicks must not lose each other's change.
EDIT_LOCK=${VWARD_CONSOLE_EDIT_LOCK:-/tmp/vward-console-edit.lock}
EDIT_LOCKED=0
edit_lock() {
    dir_lock "$EDIT_LOCK" || die route_change_busy 75
    EDIT_LOCKED=1
}

ndm() {
    out=$("$NDMC" -c "$1" 2>&1)
    rc=$?
    if [ "$rc" -ne 0 ] || printf '%s\n' "$out" | grep -Eqi '(^|[^a-z])(error|failed|invalid|unknown command|not found|no such entry)'; then
        NDM_CMD=$(printf '%s' "$1" | tr -d '\r\n"\\')
        # Keenetic's whole answer, its lines joined: the last one alone was often a bare «[»
        # and the reason above it was lost (Smart DNS and route refusals, Viva 2026-10-19).
        # sed, not tr: Keenetic's BusyBox tr has no [:print:] and kept only the letters of the
        # class (Viva 2026-10-21); the terminal's «ESC[K» goes too (fix.33.1).
        NDM_REPLY=$(printf '%s\n' "$out" | tr -d '\r"\\' | sed 's/\x1b\[[0-9;]*[A-Za-z]//g;s/\[K//g;s/[^[:print:]]/ /g' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//;/^$/d' | awk 'length($0) > 1 || $0 !~ /^[][]$/' | tr '\n' '|' | sed 's/|$//;s/|/ \/ /g' | cut -c1-400)
        return 1
    fi
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
    "$NDMC" -c "show running-config" > "$RUNCFG" 2>/dev/null && [ -s "$RUNCFG" ] && return 0
    # A busy Keenetic does not answer for a moment («Не сохранено: не удалось прочитать
    # конфигурацию роутера» while the VPN agent moved lists, Viva 2026-10-16): once more.
    sleep "${VWARD_SNAPSHOT_RETRY:-3}"
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
    # A batch (the VPN agent moving many lists at once) saves once at its end itself: 19 lists
    # were 19 saves in a minute and the busy Keenetic stopped answering (Viva 2026-10-16).
    [ "${VWARD_SAVE_LATER:-0}" != 1 ] || return 0
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

# op_list_domain add|remove|exclude|unexclude GROUP DOMAIN: edit a Keenetic
# domain list (domain-listN).  Verified from the router's configuration and
# undone when it does not match; AdaptiveAuto and VWARD's own group are not
# edited here.
op_list_domain() {
    case "$1" in
        add) ld_kind=include; ld_want=1 ;;
        remove) ld_kind=include; ld_want=0 ;;
        exclude) ld_kind=exclude; ld_want=1 ;;
        unexclude) ld_kind=exclude; ld_want=0 ;;
        *) die invalid_operation 64 ;;
    esac
    printf '%s\n' "$2" | grep -Eq '^[A-Za-z0-9._-]{1,64}$' || die invalid_group 64
    valid_domain "$3" || die invalid_domain 64
    load_profile_base
    # AdaptiveAuto is the route engine's; VWARD's own group is edited in «Мои домены».
    [ "$2" != "$ADAPTIVE_GROUP" ] && [ "$2" != "${VWARD_POLICY_GROUP:-}" ] || die invalid_group 64
    change_lock
    snapshot
    grep -q "^object-group fqdn $2\$" "$RUNCFG" || die list_not_found
    ld_has() {
        awk -v g="$2" -v d="$3" -v k="$ld_kind" '
            /^object-group fqdn / {cur=$3; next}
            /^!/ {cur=""; next}
            cur==g && $1==k && tolower($2)==d {found=1}
            END {exit found ? 0 : 1}' "$RUNCFG"
    }
    ld_have=0; ld_has "$@" && ld_have=1
    [ "$ld_want" != "$ld_have" ] || done_ok "list-domain $1 $2 $3" unchanged
    if [ "$ld_want" = 1 ]; then ld_cmd="object-group fqdn $2 $ld_kind $3"; ld_undo="no $ld_cmd"
    else ld_cmd="no object-group fqdn $2 $ld_kind $3"; ld_undo="object-group fqdn $2 $ld_kind $3"; fi
    ndm "$ld_cmd" || die router_rejected
    snapshot
    ld_have=0; ld_has "$@" && ld_have=1
    [ "$ld_want" = "$ld_have" ] || { ndm "$ld_undo"; die verification_failed; }
    save_router || die config_save_failed
    done_ok "list-domain $1 $2 $3" changed
}

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
           mkdir -p "$(dirname "$2")" && printf 'disabled from VWARD Panel %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" > "$2" || die write_failed ;;
        *) die invalid_value 64 ;;
    esac
    done_ok "$1 enabled=$3" changed
}

# tunnel-auto enabled 0|1 | criterion balanced|speed|ping | speed off|night|6h: the tunnel
# guard's choice by quality and the quality script's speed measurement.
op_tunnel_auto() {
    case "$1:$2" in
        enabled:0|enabled:1|criterion:balanced|criterion:speed|criterion:ping|speed:off|speed:night|speed:6h) ;;
        enabled:*|criterion:*|speed:*) die invalid_value 64 ;;
        *) die invalid_setting 64 ;;
    esac
    ta_key=$(printf '%s' "$1" | tr 'a-z' 'A-Z')
    set_kv "$TUNNEL_AUTO_CONF" "$ta_key" "$2" 0644 || done_ok "tunnel-auto $1=$2" unchanged
    done_ok "tunnel-auto $1=$2" changed
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
        CHECK_INTERVAL_MIN) case "$2" in 1|2|5|10|15|30) ;; *) die invalid_value 64 ;; esac ;;
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
        update_method) case "$2" in full|files) ;; *) die invalid_value 64 ;; esac ;;
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

# The Keenetic group "Мои домены" adds to.  Discovery picks it alone only while one
# group routes to the tunnel; with several (lists of Telegram, YouTube...) the owner
# chooses one of them, and the choice is pinned in device.conf.
policy_group_candidates() {
    awk -v i="$VWARD_TUNNEL_INTERFACE" -v d="$VWARD_TUNNEL_DEVICE" -v a="$ADAPTIVE_GROUP" '
        $1=="route" && $2=="object-group" && ($4==i || $4==d) && $3!=a && !s[$3]++ {print $3}' "$RUNCFG"
}

op_policy_group() {
    case "$1" in ''|*[!A-Za-z0-9_.-]*) die invalid_value 64 ;; esac
    [ "$1" != "$ADAPTIVE_GROUP" ] || die invalid_value 64
    load_profile_base
    snapshot
    policy_group_candidates | grep -qxF "$1" || die group_not_routed
    change_lock
    set_kv "$VWARD_DEVICE_CONFIG" VWARD_POLICY_GROUP "$1" 0600 || done_ok "policy-group $1" unchanged
    rm -f "$VWARD_DEVICE_MAP_CACHE"
    (
        unset VWARD_POLICY_GROUP
        vward_profile_load >/dev/null 2>&1 && [ "$VWARD_POLICY_GROUP" = "$1" ]
    ) || die profile_verification_failed
    done_ok "policy-group $1" changed
}

op_tunnel() {
    case "$1" in ''|*[!A-Za-z0-9_./:-]*) die invalid_tunnel 64 ;; esac
    [ "${#1}" -le 64 ] || die invalid_tunnel 64
    # Not load_profile: the group of «Мои домены» is found from the routes when the profile
    # cannot tell (the old tunnel lost its settings with the USB stick, Viva 2026-10-18:
    # «группа маршрутизации не найдена» and no way to move off the dead tunnel).
    load_profile_base
    case "${VWARD_POLICY_GROUP:-}" in "$ADAPTIVE_GROUP"|*[!A-Za-z0-9_.-]*) VWARD_POLICY_GROUP= ;; esac
    OLD_IF=$VWARD_TUNNEL_INTERFACE OLD_DEV=$VWARD_TUNNEL_DEVICE GROUP=${VWARD_POLICY_GROUP:-} NEW_IF=$1
    [ "$NEW_IF" != "$OLD_IF" ] || done_ok "tunnel $NEW_IF" unchanged
    # tunnel NEW [all|own]: all moves every list and subnet of the old tunnel too.  A tunnel
    # left without settings carries nothing, so its routes always come along (Viva 2026-10-19:
    # 19 lists stayed on the dead OpkgTun2 after the switch).
    case "${2:-own}" in all) MOVE_ALL=1 ;; own) MOVE_ALL=0 ;; *) die invalid_arguments 64 ;; esac
    case "$OLD_IF" in OpkgTun[0-9]|OpkgTun[0-9][0-9]) engine_tunnel "$OLD_IF" || MOVE_ALL=1 ;; esac
    [ "$(awk -F= '$1=="FAILOPEN_ACTIVE"{print $2}' "$TUNNEL_GUARD_STATE" 2>/dev/null)" != 1 ] || die failopen_active

    rm -f "$VWARD_DEVICE_MAP_CACHE"
    map=$(vward_device_map 2>/dev/null) || die router_config_unavailable
    NEW_DEV=$(vward_map_vpns "$map" "${VWARD_WAN_DEVICE:-}" | awk -v n="$NEW_IF" '$1==n {print $2; exit}')
    vward_valid_ifname "$NEW_DEV" || die unknown_tunnel 64
    # A tunnel switched off carries nothing: the lists would lose their route.
    [ "$(vward_interface_state "$NEW_IF" 2>/dev/null | head -n 1)" != down ] || die tunnel_off 64

    change_lock
    mkdir -p "$POLICY_STATE" && vward_lock_take "$POLICY_STATE/lock" || die policy_sync_busy 75
    POLICY_LOCKED=1
    JOURNAL=$(mktemp /tmp/vward-console-tunnel.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    DEVCONF_ORIG=$(mktemp /tmp/vward-console-devconf.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    TXN=1
    snapshot
    [ -n "$GROUP" ] || GROUP=$(awk -v g2="$ADAPTIVE_GROUP" -v i="$OLD_IF" -v d="$OLD_DEV" '
        /^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1)} /^!/ {ctx = 0}
        ctx && $1 == "route" && $2 == "object-group" && $3 != g2 && ($4 == i || $4 == d) && $3 ~ /^[A-Za-z0-9_.-]+$/ {print $3; exit}' "$RUNCFG")

    # ctx<TAB>group<TAB>target<TAB>options for every VWARD group routed to the old tunnel.
    moves=$(awk -v g1="$GROUP" -v g2="$ADAPTIVE_GROUP" -v i="$OLD_IF" -v d="$OLD_DEV" -v all="$MOVE_ALL" '
        /^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1) ? "dns-proxy" : ""}
        /^!/ {ctx = ""}
        $1=="route" && $2=="object-group" && ($3==g1 || $3==g2 || (all == 1 && $3 ~ /^[A-Za-z0-9_.-]+$/)) && ($4==i || $4==d) {
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
    # 3a. Static subnets of the old tunnel (all only).  The routes policy-sync owns stay
    #     with it: --reconcile below moves them itself.
    : > "$JOURNAL.nets"
    if [ "$MOVE_ALL" = 1 ]; then
        awk -v i="$OLD_IF" -v d="$OLD_DEV" -v own="$POLICY_STATE/owned.dynamic.routes" "$ROUTE_AWK"'
            function plen(m,   a, n, k, b) {n = split(m, a, "."); b = 0
                for (k = 1; k <= n; k++) {while (a[k] >= 128) {b++; a[k] = (a[k] - 128) * 2} }
                return b}
            BEGIN {while ((getline l < own) > 0) o[l] = 1}
            $1 == "ip" && $2 == "route" && (rdev() == i || rdev() == d) && !(($3 "/" plen(rmask())) in o) {print $3 " " rmask() " " rdev()}' "$RUNCFG" > "$JOURNAL.nets"
    fi
    while read -r net mask t; do
        [ -n "$net" ] || continue
        nt=$NEW_IF; [ "$t" = "$OLD_DEV" ] && [ "$OLD_DEV" != "$OLD_IF" ] && nt=$NEW_DEV
        if ! subnet_present "$net" "$mask" "$nt"; then
            ndm "ip route $net $mask $nt auto" || die router_rejected
            echo "no ip route $net $mask $nt" >> "$JOURNAL"
        fi
        ndm "no ip route $net $mask $t" || die router_rejected
        echo "ip route $net $mask $t auto" >> "$JOURNAL"
    done < "$JOURNAL.nets"
    if [ -s "$JOURNAL.nets" ]; then
        snapshot
        while read -r net mask t; do
            [ -z "$net" ] || ! subnet_present "$net" "$mask" "$t" || die verification_failed
        done < "$JOURNAL.nets"
    fi
    nets=$(grep -c . "$JOURNAL.nets")

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
        BEGIN {v["VWARD_TUNNEL_INTERFACE"]=i; v["VWARD_TUNNEL_DEVICE"]=d; if (g != "") v["VWARD_POLICY_GROUP"]=g}
        { k=$0; sub(/=.*/, "", k); if (k in v) { if (!(k in done)) print k "=" v[k]; done[k]=1; next } print }
        END {for (k in v) if (!(k in done)) print k "=" v[k]}' > "$TMPFILE" || die write_failed
    install_tmp "$VWARD_DEVICE_CONFIG" 0600 || die write_failed
    rm -f "$VWARD_DEVICE_MAP_CACHE"
    (
        unset VWARD_TUNNEL_INTERFACE VWARD_TUNNEL_DEVICE VWARD_POLICY_GROUP
        vward_profile_load >/dev/null 2>&1 &&
            [ "$VWARD_TUNNEL_INTERFACE" = "$NEW_IF" ] && [ "$VWARD_TUNNEL_DEVICE" = "$NEW_DEV" ] &&
            { [ -z "$GROUP" ] || [ "$VWARD_POLICY_GROUP" = "$GROUP" ]; }
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
    # The owner chose this tunnel: the guard does not take the routes back anywhere else.
    [ "${VWARD_TUNNEL_BY_GUARD:-}" = 1 ] || rm -f "${VWARD_TUNNEL_FALLBACK_STATE:-/opt/var/lib/vward/tunnel-guard/fallback}"
    done_ok "tunnel $OLD_IF($OLD_DEV) -> $NEW_IF($NEW_DEV) group=$GROUP routes=$moved subnets=$nets" changed
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

group_routes() {
    awk -v g="$1" '/^[^ \t!]/ {ctx=($1=="dns-proxy" && NF==1)} /^!/ {ctx=0}
        ctx && $1=="route" && $2=="object-group" && $3==g {
            o=""; for(k=5;k<=NF;k++) o=o (o==""?"":" ") $k
            print $4 "\t" (o==""?"-":o)
        }' "$RUNCFG" | sort
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

# doh_remove LINE: doh_remove_once, again when Keenetic kept the line (fix.34.1, r5): 25.10
# 14:58:01 «domain-list10 error=doh_remove_failed», the same change 55 s later went through -
# Keenetic was still taking another «https upstream» out. Up to 3 tries, VWARD_DOH_RETRY_DELAY
# seconds apart (3); a line gone meanwhile counts as removed; «other lines affected» is final.
doh_remove() {
    dr_try=1
    doh_remove_once "$1"; dr_res=$?
    while [ "$dr_res" = 1 ] && [ "$dr_try" -lt 3 ]; do
        sleep "${VWARD_DOH_RETRY_DELAY:-3}"
        dr_try=$((dr_try + 1))
        snapshot
        if doh_present "$1"; then doh_remove_once "$1"; dr_res=$?; else dr_res=0; fi
    done
    [ "$dr_try" = 1 ] || audit "doh_remove tries=$dr_try rc=$dr_res"
    return "$dr_res"
}

doh_remove_once() {
    # doh_remove_once LINE: take one Smart DNS line out.  Keenetic's delete syntax is
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
    case "$AGH_ERR" in adguard_auth_required|adguard_unavailable|upstream_file_unsupported|smartdns_not_configured) ;; *) AGH_ERR=smartdns_agh_failed ;; esac
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
    if [ -n "${VWARD_SERVICE_ID:-}" ]; then
        sr_row=$(service_row "$VWARD_SERVICE_ID")
        [ "$(printf '%s' "$sr_row" | cut -f2)" = "$G" ] && service_owned "$G" || die service_reference_only 64
    fi
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
        [ -z "${VWARD_SERVICE_ID:-}" ] || service_claim "$G"
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
    [ -z "${VWARD_SERVICE_ID:-}" ] || service_claim "$G"
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

# ---------- Services (catalog from iplist) ----------
# A service switched on is a Keenetic domain list VWARD makes itself (domain-listN,
# described with the service's name), routed like any other list, so it shows in
# Keenetic's own web interface too.  enabled.tsv: ID<TAB>GROUP<TAB>auto|TUNNEL.
SERVICES_ETC="$ETC/services"
SERVICES_STATE="$SERVICES_ETC/enabled.tsv"
SERVICES_BUNDLED=${VWARD_SERVICES_BUNDLED:-/opt/share/vward/console/services-catalog.json}
SERVICES_FETCHED=${VWARD_SERVICES_FETCHED:-/opt/var/lib/vward/services/catalog.json}
SERVICES_URL=${VWARD_SERVICES_URL:-https://raw.githubusercontent.com/Ziegfe1d/VWARD/services-catalog/services-catalog.json}
SERVICE_LIMIT=300

# services_valid FILE: the catalog shape the Panel relies on; names and domains
# that go into Keenetic commands are checked again where they are used.
services_valid() {
    [ -s "$1" ] && [ "$(wc -c < "$1")" -le 524288 ] || return 1
    "$JQ" -e '.schema == 1 and (.services | type) == "array" and (.services | length) > 0 and
        all(.services[]; (.id | type) == "string" and (.title | type) == "string" and (.title | length) <= 64 and
            (.category | type) == "string" and (.domains | type) == "array" and (.domains | length) > 0)' "$1" >/dev/null 2>&1 || return 1
    # Entware jq has no regex functions: names are checked here.
    ! "$JQ" -r '.services[].id' "$1" | grep -Evq '^[a-z0-9][a-z0-9.@_-]{0,62}$' || return 1
    ! "$JQ" -r '.services[].title' "$1" | grep -Eq '["\\[:cntrl:]]|^$'
}

services_catalog() {
    if services_valid "$SERVICES_FETCHED"; then echo "$SERVICES_FETCHED"
    elif services_valid "$SERVICES_BUNDLED"; then echo "$SERVICES_BUNDLED"
    else return 1; fi
}

service_row() { [ -f "$SERVICES_STATE" ] && awk -F'\t' -v i="$1" '$1 == i {print; exit}' "$SERVICES_STATE"; }

# service_state_set ID [GROUP PIN]: replace or drop the service's row.
service_state_set() {
    mkdir -p "$SERVICES_ETC" || die write_failed
    new_tmp "$SERVICES_STATE" || die write_failed
    { [ -f "$SERVICES_STATE" ] && awk -F'\t' -v i="$1" '$1 != i' "$SERVICES_STATE"
      [ -z "${2:-}" ] || printf '%s\t%s\t%s\n' "$1" "$2" "$3"; } > "$TMPFILE" || die write_failed
    install_tmp "$SERVICES_STATE" 0644 || die write_failed
}

free_list_name() {
    n=0
    while [ "$n" -lt 100 ]; do
        grep -qx "object-group fqdn domain-list$n" "$RUNCFG" || { echo "domain-list$n"; return 0; }
        n=$((n + 1))
    done
    return 1
}

# service_adopt TITLE DOMAINS: Keenetic's lists that already are this service (fix.34.1, b), the
# most complete first: «HITS GROUP» per line. The same description (case and spaces aside), or 80 %
# of the catalog's domains in it. Lists of other services switched on are not taken. Before, «on»
# without its row in enabled.tsv made another list: after the reinstall of 18.10 YouTube was
# domain-list1, 24 and 25. service_adopt=0 in domain-lists.conf turns it off.
service_adopt() {
    [ "$(awk -F= '$1 == "service_adopt" {print $2; exit}' "$LISTS_CONF" 2>/dev/null)" != 0 ] || return 0
    sa_taken=$([ ! -f "$SERVICES_STATE" ] || cut -f2 "$SERVICES_STATE" | tr '\n' ' ')
    awk -v t="$1" -v tk="$sa_taken" '
        function norm(x) {x = tolower(x); gsub(/["[:space:]]/, "", x); return x}
        BEGIN {n = split(tk, a, " "); for (i = 1; i <= n; i++) taken[a[i]] = 1}
        NR == FNR {want[tolower($0)] = 1; nw++; next}
        /^object-group fqdn / {g = $3; if (!(g in taken)) order[++ng] = g; next}
        /^!/ {g = ""; next}
        g == "" {next}
        $1 == "description" {d = $0; sub(/^[[:space:]]*description[[:space:]]*/, "", d); same[g] = norm(d) == norm(t)}
        $1 == "include" && (tolower($2) in want) {hit[g]++}
        END {for (i = 1; i <= ng; i++) {g = order[i]; if (same[g] || (nw > 0 && hit[g] * 100 >= 80 * nw)) print hit[g] + 0, g}}
    ' "$2" "$RUNCFG" | sort -k1,1nr -k2,2
}

group_domains() {
    awk -v g="$1" '/^object-group fqdn / {cur = $3; next} /^!/ {cur = ""} cur == g && $1 == "include" {print tolower($2)}' "$RUNCFG" | sort -u
}

# service_domains ID OUT: the catalog's domains of a service, each one checked.
# A catalog match and enabled.tsv are references, never proof of ownership.
# Record the group VWARD actually created; an owner edit or reused ID revokes it.
service_signature() {
    { awk -v g="$1" '/^object-group fqdn / {cur=$3; next} /^!/ {cur=""}
          cur==g {sub(/^[[:space:]]+/, ""); if (NF) print}' "$RUNCFG"
      group_routes "$1" | sed 's/^/route=/'
    } | sort
}

service_owned() {
    valid_group "$1" || return 1
    so_file="$SERVICES_ETC/owned/$1"
    [ -f "$so_file" ] && [ ! -L "$so_file" ] && [ -O "$so_file" ] || return 1
    so_meta=$(ls -ln "$so_file" 2>/dev/null | awk '{print $1}')
    case "$so_meta" in -rw-------|-r--------) ;; *) return 1 ;; esac
    grep -qx "object-group fqdn $1" "$RUNCFG" || return 1
    service_signature "$1" | cmp -s - "$so_file"
}

service_claim() {
    mkdir -p "$SERVICES_ETC/owned" || die write_failed
    chmod 0700 "$SERVICES_ETC/owned" || die write_failed
    new_tmp "$SERVICES_ETC/owned/$1" || die write_failed
    service_signature "$1" > "$TMPFILE" || die write_failed
    install_tmp "$SERVICES_ETC/owned/$1" 0600 || die write_failed
}

service_domains() {
    "$JQ" -r --arg i "$1" '.services[] | select(.id == $i) | .domains[]' "$SV_CAT" > "$2" 2>/dev/null || return 1
    [ -s "$2" ] || return 1
    while IFS= read -r d; do valid_domain "$d" || return 1; done < "$2"
    sort -u "$2" -o "$2"
}

# Categories pinned to a tunnel: CATEGORY<TAB>TUNNEL. A service on «Автоматически» of such a
# category goes through that tunnel; a service pinned itself keeps its own.
SERVICES_CATS="$SERVICES_ETC/categories.tsv"

# service_target PIN ID: the route a list gets. "vpn" is VWARD's tunnel, as in domain-list.
service_target() {
    [ "$1" = auto ] || { echo "$1"; return 0; }
    st_c=$("$JQ" -r --arg i "$2" '.services[] | select(.id == $i) | .category' "$SV_CAT" 2>/dev/null | head -n 1)
    st_t=$(awk -F'\t' -v c="$st_c" '$1 == c {print $2; exit}' "$SERVICES_CATS" 2>/dev/null)
    if [ -n "$st_c" ] && [ -n "$st_t" ] && is_tunnel "$st_t"; then echo "$st_t"; else echo vpn; fi
}

# Route the list through a second helper run: domain-list takes care of Smart DNS
# lines and AdGuard Home rows the same way as for Keenetic's own lists.
service_route() {
    sr_out=$(VWARD_SERVICE_ID="$sv_id" sh "$0" domain-list "$1" "$2" 2>/dev/null | tail -n 1)
    case "$sr_out" in result=*) return 0 ;; esac
    SR_ERR=${sr_out#error=}
    case "$SR_ERR" in ''|*[!a-z0-9_]*) SR_ERR=router_rejected ;; esac
    return 1
}

release_lock() {
    [ "$LOCKED" = 1 ] || return 0
    rm -rf "${CHANGE_LOCK:?}"
    LOCKED=0
}

# service-category CATEGORY auto|TUNNEL: pin a catalog category to a tunnel; its services on
# «Автоматически» move there now (auto: back to VWARD's tunnel, the check by tunnels then
# chooses again).
op_service_category() {
    printf '%s\n' "$1" | grep -Eq '^[a-z0-9][a-z0-9_-]{0,31}$' || die invalid_category 64
    case "$2" in auto) ;; ''|*[!A-Za-z0-9_.-]*) die invalid_value 64 ;; esac
    SV_CAT=$(services_catalog) || die services_unavailable
    "$JQ" -e --arg c "$1" 'any(.categories[]?; .id == $c)' "$SV_CAT" >/dev/null 2>&1 || die invalid_category 64
    load_profile_base
    [ "$2" = auto ] || is_tunnel "$2" || die unknown_tunnel 64
    snapshot
    sc_bad=$("$JQ" -r --arg c "$1" '.services[] | select(.category == $c) | .id' "$SV_CAT" |
        while IFS= read -r sc_id; do
            sc_row=$(service_row "$sc_id")
            [ "$(printf '%s' "$sc_row" | cut -f3)" = auto ] || continue
            sc_g=$(printf '%s' "$sc_row" | cut -f2)
            service_owned "$sc_g" || echo "$sc_g"
        done)
    [ -z "$sc_bad" ] || die service_reference_only 64
    sc_cur=$(awk -F'\t' -v c="$1" '$1 == c {print $2; exit}' "$SERVICES_CATS" 2>/dev/null)
    [ "${sc_cur:-auto}" != "$2" ] || done_ok "service-category $1 $2" unchanged
    mkdir -p "$SERVICES_ETC" || die write_failed
    new_tmp "$SERVICES_CATS" || die write_failed
    { [ ! -f "$SERVICES_CATS" ] || awk -F'\t' -v c="$1" '$1 != c' "$SERVICES_CATS"
      [ "$2" = auto ] || printf '%s\t%s\n' "$1" "$2"; } > "$TMPFILE" || die write_failed
    install_tmp "$SERVICES_CATS" 0644 || die write_failed
    sc_ids=$(mktemp /tmp/vward-console-category.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    "$JQ" -r --arg c "$1" '.services[] | select(.category == $c) | .id' "$SV_CAT" > "$sc_ids" 2>/dev/null
    sc_n=0
    : > "$sc_ids.on"
    [ ! -f "$SERVICES_STATE" ] || [ ! -s "$sc_ids" ] || awk -F'\t' 'NR == FNR {c[$1] = 1; next} ($1 in c) && $3 == "auto" {print $1 "\t" $2}' "$sc_ids" "$SERVICES_STATE" > "$sc_ids.on"
    while IFS="$(printf '\t')" read -r sv_id G; do
        [ -n "$G" ] || continue
        service_route "$G" "$(service_target auto "$sv_id")" || { rm -f "$sc_ids" "$sc_ids.on"; die "$SR_ERR"; }
        sc_n=$((sc_n + 1))
    done < "$sc_ids.on"
    rm -f "$sc_ids" "$sc_ids.on"
    done_ok "service-category $1 $2 moved=$sc_n" changed
}

op_service() {
    # service on ID auto|TUNNEL | tunnel ID auto|TUNNEL | off ID
    sv_op=$1 sv_id=$2 sv_to=${3:-}
    printf '%s\n' "$sv_id" | grep -Eq '^[a-z0-9][a-z0-9.@_-]{0,62}$' || die invalid_service 64
    case "$sv_op" in
        on|tunnel)
            case "$sv_to" in auto) ;; ''|*[!A-Za-z0-9_.-]*) die invalid_value 64 ;; esac ;;
        off) [ -z "$sv_to" ] || die usage 64 ;;
        *) die invalid_operation 64 ;;
    esac
    SV_CAT=$(services_catalog) || die services_unavailable
    load_profile_base
    [ "$sv_to" = auto ] || [ "$sv_op" = off ] || is_tunnel "$sv_to" || die unknown_tunnel 64
    row=$(service_row "$sv_id")
    G=$(printf '%s' "$row" | cut -f2)
    if [ -n "$row" ]; then
        snapshot
        if ! service_owned "$G"; then
            if [ "$sv_op" = off ]; then
                service_state_set "$sv_id"
                done_ok "service off $sv_id reference-only" changed
            fi
            die service_reference_only 64
        fi
    fi

    if [ "$sv_op" = tunnel ]; then
        [ -n "$row" ] || die service_not_enabled 64
        service_state_set "$sv_id" "$G" "$sv_to"
        service_route "$G" "$(service_target "$sv_to" "$sv_id")" || die "$SR_ERR"
        done_ok "service tunnel $sv_id $G $sv_to" changed
    fi

    if [ "$sv_op" = off ]; then
        [ -n "$row" ] || done_ok "service off $sv_id" unchanged
        snapshot
        if grep -qx "object-group fqdn $G" "$RUNCFG"; then
            # The route off first (Smart DNS lines come back), then the list goes.
            service_route "$G" bypass || die "$SR_ERR"
            change_lock
            snapshot
            service_owned "$G" || die service_reference_only 64
            t=$(group_route "$G"); t=${t%%"$(printf '\t')"*}
            [ -z "$t" ] || ndm "dns-proxy no route object-group $G $t" || die router_rejected
            ndm "no object-group fqdn $G" || die router_rejected
            snapshot
            ! grep -qx "object-group fqdn $G" "$RUNCFG" || die verification_failed
            save_router || die config_save_failed
            rm -f "${LISTS_STATE:?}/${G:?}" "$SERVICES_ETC/owned/$G"
        fi
        service_state_set "$sv_id"
        done_ok "service off $sv_id $G" changed
    fi

    # on: already on means a new tunnel.
    if [ -n "$row" ]; then
        service_state_set "$sv_id" "$G" "$sv_to"
        service_route "$G" "$(service_target "$sv_to" "$sv_id")" || die "$SR_ERR"
        done_ok "service on $sv_id $G $sv_to" changed
    fi
    "$JQ" -e --arg i "$sv_id" 'any(.services[]; .id == $i)' "$SV_CAT" >/dev/null 2>&1 || die unknown_service 64
    title=$("$JQ" -r --arg i "$sv_id" '.services[] | select(.id == $i) | .title' "$SV_CAT")
    case "$title" in ''|*'"'*|*"$(printf '\134')"*) die unknown_service 64 ;; esac
    change_lock
    JOURNAL=$(mktemp /tmp/vward-console-service.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    service_domains "$sv_id" "$JOURNAL.doh" || die unknown_service 64
    n=$(grep -c . "$JOURNAL.doh")
    [ "$n" -le "$SERVICE_LIMIT" ] || die service_too_big 64
    snapshot
    sv_found=$(service_adopt "$title" "$JOURNAL.doh")
    if [ -n "$sv_found" ]; then
        # The list is there already: it is taken, not made again; the others are duplicates.
        G=$(printf '%s\n' "$sv_found" | awk 'NR == 1 {print $2}')
        sv_dups=$(printf '%s\n' "$sv_found" | awk 'NR > 1 {printf "%s%s", c, $2; c = ","}')
        # Do not repoint, refresh or delete a group discovered by similarity.
        die service_reference_only 64
    fi
    G=$(free_list_name) || die no_free_list
    TXN=1
    ndm "object-group fqdn $G" || die router_rejected
    echo "no object-group fqdn $G" >> "$JOURNAL"
    ndm "object-group fqdn $G description \"$title\"" || die router_rejected
    while IFS= read -r d; do
        ndm "object-group fqdn $G include $d" || die list_limit
    done < "$JOURNAL.doh"
    snapshot
    group_domains "$G" | cmp -s - "$JOURNAL.doh" || die verification_failed
    save_router || die config_save_failed
    service_claim "$G"
    TXN=0
    service_state_set "$sv_id" "$G" "$sv_to"
    release_lock
    if ! service_route "$G" "$(service_target "$sv_to" "$sv_id")"; then
        # Without its route the list is of no use: it goes, and the service stays off.
        change_lock
        ndm "no object-group fqdn $G" && save_router
        service_state_set "$sv_id"
        rm -f "$SERVICES_ETC/owned/$G"
        die "$SR_ERR"
    fi
    done_ok "service on $sv_id $G $sv_to domains=$n" changed
}

# services-refresh: the catalog of the day (iplist, built by VWARD's workflow),
# kept only when it is valid; the lists of services switched on follow it.
op_services_refresh() {
    mkdir -p "$(dirname "$SERVICES_FETCHED")" || die write_failed
    new_tmp "$SERVICES_FETCHED" || die write_failed
    # Through vward_fetch of the device profile: when curl crashes on HTTPS, the TLS of
    # uclient-fetch or of the VLESS module's Xray downloads (no crash on every refresh).
    command -v vward_fetch >/dev/null 2>&1 ||
        { [ ! -r "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}" ] || . "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}"; } 2>/dev/null
    # No -f: the HTTP status tells «not published» (404) from a download that failed.
    if command -v vward_fetch >/dev/null 2>&1; then
        VWARD_CURL_BIN=${VWARD_CURL_BIN:-$(command -v curl)}
        sv_code=$(vward_fetch -sS --connect-timeout 10 --max-time 60 --max-filesize 524288 -o "$TMPFILE" -w '%{http_code}' "$SERVICES_URL" 2>/dev/null)
    else
        sv_code=$("${VWARD_CURL_BIN:-curl}" --http1.1 -sS --connect-timeout 10 --max-time 60 --max-filesize 524288 -o "$TMPFILE" -w '%{http_code}' "$SERVICES_URL" 2>/dev/null)
    fi || die download_failed
    case "$sv_code" in
        200) ;;
        # The daily catalog is not published (its branch or workflow is missing): not an error,
        # the lists keep following the catalog of the package, one line in the journal.
        404) rm -f "${TMPFILE:?}"; TMPFILE=
             done_ok "services-refresh catalog not published, the package catalog is used" unchanged ;;
        *) die download_failed ;;
    esac
    services_valid "$TMPFILE" || die catalog_invalid
    if [ -f "$SERVICES_FETCHED" ] && cmp -s "$TMPFILE" "$SERVICES_FETCHED"; then
        rm -f "${TMPFILE:?}"; TMPFILE=; fetched=unchanged
    else
        install_tmp "$SERVICES_FETCHED" 0644 || die write_failed; fetched=changed
    fi
    [ -s "$SERVICES_STATE" ] || done_ok "services-refresh catalog=$fetched" "$fetched"
    SV_CAT=$SERVICES_FETCHED
    change_lock
    JOURNAL=$(mktemp /tmp/vward-console-service.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    snapshot
    moved=0
    : > "$JOURNAL.owned"
    while IFS="$(printf '\t')" read -r id grp pin; do
        grep -qx "object-group fqdn $grp" "$RUNCFG" || continue
        service_owned "$grp" || continue
        echo "$grp" >> "$JOURNAL.owned"
        service_domains "$id" "$JOURNAL.doh" || continue
        [ "$(grep -c . "$JOURNAL.doh")" -le "$SERVICE_LIMIT" ] || continue
        group_domains "$grp" > "$JOURNAL.moves"
        comm -13 "$JOURNAL.moves" "$JOURNAL.doh" | while IFS= read -r d; do ndm "object-group fqdn $grp include $d" || exit 1; done || die list_limit
        comm -23 "$JOURNAL.moves" "$JOURNAL.doh" | while IFS= read -r d; do ndm "no object-group fqdn $grp include $d" || exit 1; done || die router_rejected
        cmp -s "$JOURNAL.moves" "$JOURNAL.doh" || moved=$((moved + 1))
    done < "$SERVICES_STATE"
    [ "$moved" = 0 ] || save_router || die config_save_failed
    if [ "$moved" != 0 ]; then
        snapshot
        while IFS="$(printf '\t')" read -r id grp pin; do
            # Only groups that had a valid claim before refresh are re-signed below.
            grep -Fxq "$grp" "$JOURNAL.owned" 2>/dev/null || continue
            service_claim "$grp"
        done < "$SERVICES_STATE"
    fi
    [ "$moved" = 0 ] && [ "$fetched" = unchanged ] && done_ok "services-refresh" unchanged
    done_ok "services-refresh catalog=$fetched lists=$moved" changed
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
          ko = substr(line, 1, i - 1); v = substr(line, i + 1)
          sub(/[ \t]+$/, "", ko); sub(/^[ \t]+/, "", v); k = tolower(ko)
          if (ko ~ /^[A-Za-z0-9_]+$/) print "name." k "=" ko
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
    # Newer AmneziaWG gives a range (25-35); Keenetic takes one value, the lower one.
    ka=$(conf_get peer.persistentkeepalive "$cp_raw")
    case "$ka" in *-*) ka_hi=${ka#*-} ka=${ka%%-*}; valid_int_range "$ka_hi" 0 65535 || die conf_keepalive 64 ;; esac
    [ -z "$ka" ] || valid_int_range "$ka" 0 65535 || die conf_keepalive 64
    # Every setting has a home, none is dropped: Keenetic's own commands, VWARD's AmneziaWG
    # engine (vward-awg: AmneziaWG 3.x, KeeneticOS 5.1 has no command for it), or the
    # computer's wg-quick (Table, PostUp...: the router does these itself; named in the Panel).
    # A setting neither Keenetic nor the engine knows stops the import, by name: without it
    # the tunnel would connect differently from the file, or not at all.
    cp_where=$(awk -F= '/^(if|peer)\./ {print $1}' "$cp_raw" | awk '!s[$0]++' | while IFS= read -r k; do
        case "$k" in
            if.privatekey|if.address|if.dns|if.mtu|if.listenport|if.jc|if.jmin|if.jmax|if.s[1-4]|if.h[1-4]|if.i[1-5]) ;;
            peer.publickey|peer.presharedkey|peer.allowedips|peer.endpoint|peer.persistentkeepalive) ;;
            if.headerprotectionkey|if.contentpaddingaddition|if.rekeyaftertime|if.rekeytimeout|if.rejectaftertime|if.keepalivetimeout|if.maxhandshakeattempts|if.randomtrailers|if.disablecookies) echo engine ;;
            if.table|if.preup|if.postup|if.predown|if.postdown|if.saveconfig|if.fwmark) echo "host $k" ;;
            *) echo "unknown $k" ;;
        esac
    done)
    # The file's own spelling of a setting (PostUp, not postup); a name awk could not keep, as is.
    cp_names() {
        printf '%s\n' "$cp_where" | sed -n "s/^$1 [a-z]*\.//p" | while IFS= read -r k; do
            o=$(conf_get "name.$k" "$cp_raw"); printf '%s\n' "${o:-$k}"
        done | tr -cd 'A-Za-z0-9_.\n-' | head -n 20 | tr '\n' ',' | sed 's/,$//'
    }
    unknown=$(cp_names unknown)
    [ -z "$unknown" ] || { rm -f "$cp_raw"; printf 'reason=%s\n' "$unknown"; die conf_unknown_setting 64; }
    hostonly=$(cp_names host)
    allowed=$(conf_get peer.allowedips "$cp_raw"); [ -n "$allowed" ] || allowed=0.0.0.0/0

    {
        echo "private=$priv"; echo "peer=$pub"; [ -z "$psk" ] || echo "psk=$psk"
        echo "address=$ip $mask"; echo "endpoint=$host:$port"
        [ -z "$mtu" ] || echo "mtu=$mtu"
        [ -z "$ka" ] || [ "$ka" = 0 ] || echo "keepalive=$ka"
        [ -z "$hostonly" ] || echo "hostonly=$hostonly"
        ! printf '%s\n' "$cp_where" | grep -qx engine || echo "engine=1"
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
      vward_map_tunnels "$(vward_device_map 2>/dev/null)" | awk '{print $1}'
      # The engine's tunnels (Keenetic «OpkgTun» connections) take lists like any tunnel.
      [ ! -f "$AWG_TUNNELS" ] || awk -F'\t' '{print $2}' "$AWG_TUNNELS"
      [ ! -f "$VLESS_TUNNELS" ] || awk -F'\t' '{print $2}' "$VLESS_TUNNELS"; } | awk 'NF && !s[$0]++'
}
# An engine's tunnel whose settings are gone has no adapter, so no place in the map: Keenetic
# still has it, and it must be deletable (Viva 2026-10-18: «туннель не найден»). Asked only then.
is_tunnel() {
    tunnel_names | grep -qxF -- "$1" && return 0
    case "$1" in OpkgTun[0-9]|OpkgTun[0-9][0-9]) ;; *) return 1 ;; esac
    command -v vward_keenetic_config >/dev/null 2>&1 &&
        vward_keenetic_config 2>/dev/null | grep -qx "interface $1"
}
# engine_tunnel NAME: the tunnel is one of VWARD's engines; ENG is that engine.
engine_tunnel() {
    for et in "$AWG_TUNNELS:$AWG_ENGINE" "$VLESS_TUNNELS:$VLESS_ENGINE"; do
        [ -f "${et%%:*}" ] && awk -F'\t' -v p="$1" '$2 == p {f = 1} END {exit f ? 0 : 1}' "${et%%:*}" && { ENG=${et#*:}; return 0; }
    done
    return 1
}

free_tunnel_name() {
    n=0
    while [ "$n" -lt 32 ]; do
        grep -qx "interface Wireguard$n" "$RUNCFG" || { printf 'Wireguard%s\n' "$n"; return 0; }
        n=$((n + 1))
    done
    return 1
}

# address_taken IFACE ADDRESS: another interface of the running configuration already has
# this IPv4 address (Keenetic refuses two tunnels with one address, and a half-applied
# create would only end in a rollback).
address_taken() {
    awk -v skip="$1" -v a="$2" '
        /^[^ \t!]/ {cur = ($1 == "interface") ? $2 : ""}
        cur != "" && cur != skip && $1 == "ip" && $2 == "address" {ip = $3; sub(/\/.*/, "", ip); if (ip == a) {print cur; f = 1; exit}}
        END {exit f ? 0 : 1}' "$RUNCFG"
}

apply_plan() {
    # apply_plan IFACE PLAN ADDRESS: interface settings and its one peer.
    ndm_secret "interface $1 wireguard private-key $(conf_get private "$2")" || die conf_rejected_key
    ndm "interface $1 ip address $3" || die conf_rejected_address
    m=$(conf_get mtu "$2"); [ -z "$m" ] || ndm "interface $1 ip mtu $m" || die conf_rejected_mtu
    a=$(conf_get asc "$2")
    # AP_AWG_SOFT=1: a refused AmneziaWG line returns 3 (the caller hands the file to
    # VWARD's engine) instead of ending the job.
    if [ -n "$a" ]; then ndm "interface $1 wireguard asc $a" || { [ "${AP_AWG_SOFT:-0}" = 1 ] && return 3; die conf_rejected_awg; }
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

# step NAME: where a tunnel job stands; the Panel's progress window reads these lines.
step() { printf 'step=%s\n' "$1"; }

# create_on_engine: the new tunnel goes to VWARD's AmneziaWG engine on a Keenetic «OpkgTun»
# connection (a format the firmware has no command for, or one it refused).
create_on_engine() {
    [ -x "$AWG_ENGINE" ] || die engine_unavailable
    snapshot
    ! address_taken - "$(conf_get address "$PLAN" | awk '{print $1}')" || die tunnel_address_taken 64
    engine_add "$tc_arg" "$tc_file" "$tc_keep"
    case "$(printf '%s\n' "$en_out" | tail -n 1)" in
        result=changed) ;;
        error=*) relay_reason "$en_out"
                 en_err=$(printf '%s\n' "$en_out" | sed -n 's/^error=//p' | tail -n 1)
                 case "$en_err" in ''|*[!a-z0-9_]*) en_err=engine_failed ;; esac
                 die "$en_err" ;;
        *) die engine_failed ;;
    esac
    rm -f "$VWARD_DEVICE_MAP_CACHE"
    printf '%s\n' "$en_out" | grep -E '^info\.(name|handshake)=' | head -n 2
    tunnel_summary "$PLAN"
    done_ok "tunnel-conf create engine $(printf '%s\n' "$en_out" | sed -n 's/^info\.name=//p') endpoint=$(conf_get endpoint "$PLAN")" changed
}

# engine_add DESCRIPTION FILE [keep]: the engine's add; its steps reach the job's output on fd 3.
# «keep»: the owner chose to keep the tunnel although the server did not answer.
engine_add() {
    exec 3>&1
    en_out=$("$AWG_ENGINE" add "$1" "$2" ${3:+"$3"} 2>/dev/null)
    exec 3>&-
}

# tunnel_kind NAME: firmware | awg | vless - who holds the tunnel.
tunnel_kind() {
    if engine_tunnel "$1"; then
        [ "$ENG" = "$VLESS_ENGINE" ] && [ "$VLESS_ENGINE" != "$AWG_ENGINE" ] && echo vless || echo awg
    else echo firmware; fi
}

# tunnel_dups PLAN: «info.same» is the tunnel that already has this server key (the same
# configuration), «info.sameaddr» the interface that already has this address in the tunnel.
# The Panel asks before it replaces or adds; the keys themselves are never printed.
tunnel_dups() {
    td_peer=$(conf_get peer "$1"); td_addr=$(conf_get address "$1" | awk '{print $1}')
    td_same=$(awk -v k="$td_peer" '/^[^ \t!]/ {cur = ($1 == "interface") ? $2 : ""}
        cur != "" && $1 == "wireguard" && $2 == "peer" && $3 == k {print cur; exit}' "$RUNCFG")
    if [ -z "$td_same" ] && [ -f "$AWG_TUNNELS" ]; then
        td_same=$(while IFS="$(printf '\t')" read -r td_n td_name _; do
            tr -d '\r' 2>/dev/null < "${AWG_TUNNELS%/*}/t$td_n.conf" |
                awk -F= -v k="$td_peer" 'tolower($1) ~ /^[ \t]*publickey[ \t]*$/ {v = substr($0, index($0, "=") + 1); gsub(/[ \t]/, "", v); if (v == k) f = 1} END {exit f ? 0 : 1}' &&
                { printf '%s\n' "$td_name"; break; }
        done < "$AWG_TUNNELS")
    fi
    td_have=$(awk -v skip=- -v a="$td_addr" '/^[^ \t!]/ {cur = ($1 == "interface") ? $2 : ""}
        cur != "" && $1 == "ip" && $2 == "address" {ip = $3; sub(/\/.*/, "", ip); if (ip == a) {print cur; exit}}' "$RUNCFG")
    [ -z "$td_same" ] || { printf 'info.same=%s\n' "$td_same"; printf 'info.samekind=%s\n' "$(tunnel_kind "$td_same")"; }
    [ -z "$td_have" ] || {
        printf 'info.sameaddr=%s\n' "$td_have"
        if is_tunnel "$td_have"; then printf 'info.sameaddrkind=%s\n' "$(tunnel_kind "$td_have")"; else printf 'info.sameaddrkind=other\n'; fi
    }
}

tunnel_summary() {
    # Plain facts about a plan for the Panel, never the keys.
    printf 'info.endpoint=%s\n' "$(conf_get endpoint "$1")"
    printf 'info.address=%s\n' "$(conf_get address "$1" | awk '{print $1}')"
    printf 'info.mtu=%s\n' "$(conf_get mtu "$1")"
    printf 'info.keepalive=%s\n' "$(conf_get keepalive "$1")"
    printf 'info.awg=%s\n' "$([ -n "$(conf_get asc "$1")" ] && echo 1 || echo 0)"
    printf 'info.allowed=%s\n' "$(sed -n 's/^allow=//p' "$1" | tr '\n' ',' | sed 's/,$//')"
    printf 'info.hostonly=%s\n' "$(conf_get hostonly "$1")"
    printf 'info.engine=%s\n' "$(conf_get engine "$1")"
}

# op_vless_server servers|select NAME [I]: the servers of a VLESS tunnel's subscription (name,
# address, time to answer, which one now), or the move of the tunnel to server I.
op_vless_server() {
    [ -x "$VLESS_ENGINE" ] || die engine_unavailable
    case "$2" in OpkgTun[0-9]) ;; *) die invalid_tunnel 64 ;; esac
    case "$1" in
        servers) vs_out=$("$VLESS_ENGINE" list "$2" 2>/dev/null) ;;
        # A country on or off, or failover between countries (fix.28.2).
        countries) case "$3:$4" in cross:0|cross:1|--:0|--:1|[A-Z][A-Z]:0|[A-Z][A-Z]:1) ;; *) die invalid_value 64 ;; esac
                vs_out=$("$VLESS_ENGINE" countries "$2" "$3" "$4" 2>/dev/null) ;;
        select) case "$3" in ''|*[!0-9]*) die invalid_value 64 ;; esac
                load_profile_base
                vs_out=$("$VLESS_ENGINE" select "$2" "$3" 2>/dev/null) ;;
        *) die invalid_operation 64 ;;
    esac
    case "$(printf '%s\n' "$vs_out" | tail -n 1)" in
        result=checked) printf '%s\n' "$vs_out" | grep '^info\.'; done_ok "vless-server servers $2" checked ;;
        result=changed) printf '%s\n' "$vs_out" | grep '^info\.'; done_ok "vless-server $1 $2 $3 ${4:-}" changed ;;
        error=*) relay_reason "$vs_out"
                 vs_err=$(printf '%s\n' "$vs_out" | sed -n 's/^error=//p' | tail -n 1)
                 case "$vs_err" in ''|*[!a-z0-9_]*) vs_err=engine_failed ;; esac
                 die "$vs_err" ;;
        # An answer the Panel does not know: its last line goes with the error to the journal.
        *) RELAY_REASON=$(printf '%s\n' "$vs_out" | tail -n 1 | tr -cd 'A-Za-z0-9=._:/ -' | cut -c1-120)
           die engine_failed ;;
    esac
}

# op_tunnel_vless check|create FILE [DESCRIPTION] [keep]: the servers of the links or subscription
# (never the ids), or a new tunnel of the chosen one («#server=N» in FILE).
op_tunnel_vless() {
    [ -x "$VLESS_ENGINE" ] || die engine_unavailable
    case "$1" in
        check)
            vl_out=$("$VLESS_ENGINE" servers "$2" 2>/dev/null) ;;
        create)
            vl_desc=$3
            case "$vl_desc" in @/*) vl_f=${vl_desc#@}; vl_desc=$(cat "$vl_f" 2>/dev/null); rm -f "$vl_f" ;; esac
            case "$vl_desc" in *'"'*|*"$(printf '\134')"*) die invalid_description 64 ;; esac
            [ "${#vl_desc}" -le 64 ] || die invalid_description 64
            load_profile_base
            exec 3>&1
            vl_out=$("$VLESS_ENGINE" add "$vl_desc" "$2" ${4:+"$4"} 2>/dev/null)
            exec 3>&- ;;
        *) die vless_replace_unsupported 64 ;;
    esac
    case "$(printf '%s\n' "$vl_out" | tail -n 1)" in
        result=checked) printf '%s\n' "$vl_out" | grep '^info\.'; done_ok "tunnel-conf check vless" checked ;;
        result=changed)
            rm -f "$VWARD_DEVICE_MAP_CACHE"
            printf '%s\n' "$vl_out" | grep -E '^info\.(name|handshake)=' | head -n 2
            done_ok "tunnel-conf create vless $(printf '%s\n' "$vl_out" | sed -n 's/^info\.name=//p')" changed ;;
        error=*) relay_reason "$vl_out"
                 vl_err=$(printf '%s\n' "$vl_out" | sed -n 's/^error=//p' | tail -n 1)
                 case "$vl_err" in ''|*[!a-z0-9_]*) vl_err=engine_failed ;; esac
                 die "$vl_err" ;;
        *) die engine_failed ;;
    esac
}

op_tunnel_conf() {
    # tunnel-conf check|replace|create FILE [NAME | DESCRIPTION]
    tc_mode=$1 tc_file=$2 tc_arg=${3:-} tc_keep=${4:-}
    case "$tc_keep" in ""|keep) ;; *) die invalid_value 64 ;; esac
    case "$tc_file" in /*) ;; *) die invalid_value 64 ;; esac
    [ -f "$tc_file" ] && [ ! -L "$tc_file" ] || die conf_empty 64
    CONF_FILE=$tc_file
    # vless:// or trojan:// links or a subscription's address: VWARD's VLESS engine.
    if tr -d '\r' < "$tc_file" | grep -v '^#' | awk 'NF {print $1; exit}' | grep -Eq '^(vless|trojan|https?)://'; then
        op_tunnel_vless "$tc_mode" "$tc_file" "$tc_arg" "$tc_keep"
    fi
    PLAN=$(mktemp /tmp/vward-console-plan.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    TMPFILE=$PLAN
    CONF_FILE=$tc_file
    conf_parse "$tc_file" "$PLAN"
    load_profile_base
    case "$tc_mode" in
        check)
            snapshot
            tunnel_summary "$PLAN"
            tunnel_dups "$PLAN"
            done_ok "tunnel-conf check" checked ;;
        replace)
            vward_valid_ndm_name "$tc_arg" && is_tunnel "$tc_arg" || die unknown_tunnel 64
            # A tunnel of VWARD's AmneziaWG engine: the engine swaps its file and restarts it
            # (the old file comes back when the server does not answer). VLESS: a new tunnel.
            if engine_tunnel "$tc_arg"; then
                [ "$ENG" = "$AWG_ENGINE" ] && [ -x "$AWG_ENGINE" ] || die engine_replace_unsupported 64
                snapshot
                ! address_taken "$tc_arg" "$(conf_get address "$PLAN" | awk '{print $1}')" || die tunnel_address_taken 64
                exec 3>&1
                en_out=$("$AWG_ENGINE" replace "$tc_arg" "$tc_file" ${tc_keep:+"$tc_keep"} 2>/dev/null)
                exec 3>&-
                case "$(printf '%s\n' "$en_out" | tail -n 1)" in
                    result=changed) ;;
                    error=*) relay_reason "$en_out"
                             en_err=$(printf '%s\n' "$en_out" | sed -n 's/^error=//p' | tail -n 1)
                             case "$en_err" in ''|*[!a-z0-9_]*) en_err=engine_failed ;; esac
                             die "$en_err" ;;
                    *) die engine_failed ;;
                esac
                rm -f "$VWARD_DEVICE_MAP_CACHE" "$TUNNEL_HEALTH_STATE"
                printf '%s\n' "$en_out" | grep '^info\.handshake=' | head -n 1
                tunnel_summary "$PLAN"
                done_ok "tunnel-conf replace engine $tc_arg endpoint=$(conf_get endpoint "$PLAN")" changed
            fi
            [ "$(conf_get engine "$PLAN")" != 1 ] || die engine_replace_unsupported 64
            change_lock
            JOURNAL=$(mktemp /tmp/vward-console-tunnel.XXXXXX 2>/dev/null) || die temporary_file_unavailable
            TXN=1
            snapshot
            ! address_taken "$tc_arg" "$(conf_get address "$PLAN" | awk '{print $1}')" || die tunnel_address_taken 64
            # «keep»: the owner chose to keep the configuration though the server may not answer.
            if [ "$tc_keep" != keep ]; then
                step test
                tunnel_test "$PLAN"
            fi
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
            step router
            for op in $old_peers; do
                [ "$op" = "$new_peer" ] || ndm "no interface $tc_arg wireguard peer $op" || die router_rejected
            done
            apply_plan "$tc_arg" "$PLAN" "$(conf_get address "$PLAN")"
            step handshake
            if [ "$tc_keep" = keep ]; then
                handshake_ok "$tc_arg" || printf 'info.handshake=none\n'
            else
                handshake_ok "$tc_arg" || die tunnel_no_handshake
            fi
            step save
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
            [ "$(conf_get engine "$PLAN")" != 1 ] || create_on_engine
            change_lock
            JOURNAL=$(mktemp /tmp/vward-console-tunnel.XXXXXX 2>/dev/null) || die temporary_file_unavailable
            TXN=1
            snapshot
            ! address_taken - "$(conf_get address "$PLAN" | awk '{print $1}')" || die tunnel_address_taken 64
            NEW_IF=$(free_tunnel_name) || die no_free_tunnel
            step router
            ndm "interface $NEW_IF" || die router_rejected
            echo "no interface $NEW_IF" >> "$JOURNAL"
            ndm "interface $NEW_IF description \"$tc_arg\"" || die invalid_description
            ndm "interface $NEW_IF security-level public" || die router_rejected
            ndm "interface $NEW_IF ip tcp adjust-mss pmtu" || :
            AP_AWG_SOFT=1
            if ! apply_plan "$NEW_IF" "$PLAN" "$(conf_get address "$PLAN")"; then
                # The firmware refused this AmneziaWG format (2.0 ranges, S3/S4, I1-I5 on an
                # older KeeneticOS): its interface is taken back and VWARD's engine holds it.
                TXN=0
                tunnel_undo || die rollback_incomplete
                [ -x "$AWG_ENGINE" ] || die conf_rejected_awg
                audit "tunnel-conf create $NEW_IF: AmneziaWG refused by the firmware, engine instead"
                printf 'info.engine=firmware_refused\n'
                rm -rf "${CHANGE_LOCK:?}"; LOCKED=0
                create_on_engine
            fi
            AP_AWG_SOFT=0
            step handshake
            if [ "$tc_keep" = keep ]; then
                handshake_ok "$NEW_IF" || printf 'info.handshake=none\n'
            else
                handshake_ok "$NEW_IF" || die tunnel_no_handshake
            fi
            step save
            save_router || die config_save_failed
            TXN=0
            store_conf "$NEW_IF" "$tc_file" || audit "tunnel $NEW_IF conf not stored"
            rm -f "$VWARD_DEVICE_MAP_CACHE"
            printf 'info.name=%s\n' "$NEW_IF"
            tunnel_summary "$PLAN"
            done_ok "tunnel-conf create $NEW_IF endpoint=$(conf_get endpoint "$PLAN")" changed ;;
        adopt)
            # A tunnel Keenetic took from an AmneziaWG 3.x file without its header
            # protection: the same file (its server key matches) goes to VWARD's engine
            # under the same name, the lists and subnets move over, the dead one goes.
            vward_valid_ndm_name "$tc_arg" || die unknown_tunnel 64
            snapshot
            grep -qx "interface $tc_arg" "$RUNCFG" || die unknown_tunnel 64
            [ "$(conf_get engine "$PLAN")" = 1 ] || die conf_not_awg3 64
            tunnel_block "$tc_arg" | awk -v p="$(conf_get peer "$PLAN")" '$1 == "wireguard" && $2 == "peer" && $3 == p {f = 1} END {exit f ? 0 : 1}' ||
                die conf_other_tunnel 64
            ad_desc=$(tunnel_block "$tc_arg" | sed -n 's/^ *description *//p' | head -n 1 | tr -d '"\\')
            [ -n "$ad_desc" ] || ad_desc=$tc_arg
            [ -x "$AWG_ENGINE" ] || die engine_unavailable
            engine_add "$ad_desc" "$tc_file"
            case "$(printf '%s\n' "$en_out" | tail -n 1)" in
                result=changed) ;;
                error=*) relay_reason "$en_out"
                         en_err=$(printf '%s\n' "$en_out" | sed -n 's/^error=//p' | tail -n 1)
                         case "$en_err" in ''|*[!a-z0-9_]*) en_err=engine_failed ;; esac
                         die "$en_err" ;;
                *) die engine_failed ;;
            esac
            ad_new=$(printf '%s\n' "$en_out" | sed -n 's/^info\.name=//p' | head -n 1)
            rm -f "$VWARD_DEVICE_MAP_CACHE"
            printf 'info.name=%s\n' "$ad_new"
            # The VWARD tunnel itself moves first; then lists and subnets, and the old one goes.
            step move
            if [ "$tc_arg" = "$VWARD_TUNNEL_INTERFACE" ]; then
                ad_r=$(sh "$0" tunnel "$ad_new" 2>/dev/null | tail -n 1)
                case "$ad_r" in result=*) ;; *) die adopt_move_failed ;; esac
            fi
            ad_r=$(sh "$0" tunnel-delete "$tc_arg" "$ad_new" 2>/dev/null | tail -n 1)
            case "$ad_r" in result=*) ;; *) die adopt_move_failed ;; esac
            tunnel_summary "$PLAN"
            done_ok "tunnel-conf adopt $tc_arg -> $ad_new" changed ;;
        *) die invalid_operation 64 ;;
    esac
}

op_tunnel_state() {
    # tunnel-state up|down|restart NAME: at once, as Keenetic's own switch (owner 2026-10-12: no
    # window, no waiting). The server's answer is not waited for: the tunnel's status shows
    # «подключение» until it comes. «Выключить» stops the engine's program too and saves;
    # «Включить» starts it and saves; «Перезапустить» turns the tunnel off and on, nothing saved.
    # The default tunnel is not switched off.
    load_profile_base
    vward_valid_ndm_name "$2" && is_tunnel "$2" || die unknown_tunnel 64
    case "$1" in restart|up|down) ;; *) die invalid_operation 64 ;; esac
    change_lock
    if [ "$1" = down ]; then
        [ "$2" != "$VWARD_TUNNEL_INTERFACE" ] || die main_tunnel 64
        if engine_tunnel "$2"; then
            [ -x "$ENG" ] || die engine_unavailable
            "$ENG" disable "$2" 2>/dev/null | tail -n 1 | grep -q '^result=' || die engine_failed
        fi
        ndm "interface $2 down" || { ! engine_tunnel "$2" || "$ENG" enable "$2" >/dev/null 2>&1; die router_rejected; }
        save_router || die config_save_failed
        rm -f "$VWARD_DEVICE_MAP_CACHE" "$TUNNEL_HEALTH_STATE"
        done_ok "tunnel-state down $2" changed
    fi
    if engine_tunnel "$2"; then
        [ -x "$ENG" ] || die engine_unavailable
        [ "$1" = restart ] || { "$ENG" enable "$2" >/dev/null 2>&1; ndm "interface $2 up" || die router_rejected; }
        "$ENG" start "$2" 2>/dev/null | tail -n 1 | grep -q '^result=' || die engine_start_failed
    else
        if [ "$1" = restart ]; then
            ndm "interface $2 down" || die router_rejected
            sleep 2
        fi
        ndm "interface $2 up" || die router_rejected
    fi
    [ "$1" != up ] || save_router || die config_save_failed
    rm -f "$VWARD_DEVICE_MAP_CACHE" "$TUNNEL_HEALTH_STATE"
    done_ok "tunnel-state $1 $2" changed
}

op_tunnel_delete() {
    # tunnel-delete NAME TARGET [move]: move its lists and subnets to TARGET (bypass, vpn
    # or another tunnel), then remove the interface.  The VWARD tunnel stays.  move: only
    # the lists and subnets, the tunnel stays (a tunnel without settings, fix.32).
    load_profile_base
    case "${3:-}" in ''|move) ;; *) die invalid_arguments 64 ;; esac
    [ "${3:-}" != move ] || OP=tunnel-move
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
    # Moving only: the routes of the IP categories belong to policy-sync, which follows the
    # default tunnel itself (--reconcile below); a subnet Keenetic refuses is told, not fatal.
    if [ "${3:-}" = move ]; then
        awk -v i="$1" -v own="$POLICY_STATE/owned.dynamic.routes" "$ROUTE_AWK"'
            function plen(m,   a, n, k, b) {n = split(m, a, "."); b = 0
                for (k = 1; k <= n; k++) {while (a[k] >= 128) {b++; a[k] = (a[k] - 128) * 2} }
                return b}
            BEGIN {while ((getline l < own) > 0) o[l] = 1}
            $1 == "ip" && $2 == "route" && rdev() == i {if (($3 "/" plen(rmask())) in o) print $3 " " rmask() > "/dev/stderr"; else print $3 " " rmask()}' "$RUNCFG" > "$JOURNAL.nets" 2> "$JOURNAL.owned"
    else
        awk -v i="$1" "$ROUTE_AWK"' $1 == "ip" && $2 == "route" && rdev() == i {print $3 " " rmask()}' "$RUNCFG" > "$JOURNAL.nets"
    fi
    : > "$JOURNAL.failed"
    while IFS= read -r net; do
        [ -n "$net" ] || continue
        if [ "${3:-}" = move ]; then
            if [ "$td_to" != - ] && ! subnet_present "${net% *}" "${net#* }" "$td_to"; then
                ndm "ip route $net $td_to auto" || { echo "$net|$NDM_REPLY" >> "$JOURNAL.failed"; continue; }
                echo "no ip route $net $td_to" >> "$JOURNAL"
            fi
            # Keenetic keeps one route per subnet: the new one replaced the old, whose removal is
            # then refused. Told only if the old one is still there after the move (below).
            if ! ndm "no ip route $net $1"; then
                echo "$net|$NDM_REPLY" >> "$JOURNAL.failed"
                continue
            fi
            echo "ip route $net $1 auto" >> "$JOURNAL"
            continue
        fi
        if [ "$td_to" != - ]; then
            ndm "ip route $net $td_to auto" || die router_rejected
            echo "no ip route $net $td_to" >> "$JOURNAL"
        fi
        ndm "no ip route $net $1" || die router_rejected
        echo "ip route $net $1 auto" >> "$JOURNAL"
    done < "$JOURNAL.nets"
    snapshot
    while IFS= read -r g; do [ -z "$g" ] || ! route_present "$g" "$1" || die verification_failed; done < "$JOURNAL.lists"
    if [ "${3:-}" = move ]; then
        # Not moved: only what is still on the old tunnel after the move (Viva 2026-10-19: 450
        # «refused», all of them on the default tunnel afterwards). Its new route is taken back.
        : > "$JOURNAL.still"
        while IFS='|' read -r tf_net tf_why; do
            [ -n "$tf_net" ] || continue
            subnet_present "${tf_net% *}" "${tf_net#* }" "$1" || continue
            echo "$tf_net|$tf_why" >> "$JOURNAL.still"
            [ "$td_to" = - ] || ndm "no ip route $tf_net $td_to" || :
        done < "$JOURNAL.failed"
        mv "$JOURNAL.still" "$JOURNAL.failed"
        td_lists=$(grep -c . "$JOURNAL.lists") td_fail=$(grep -c . "$JOURNAL.failed") td_own=$(grep -c . "$JOURNAL.owned")
        td_nets=$(( $(grep -c . "$JOURNAL.nets") - td_fail ))
        # Each refused subnet with Keenetic's own answer (the first 20).
        head -n 20 "$JOURNAL.failed" | while IFS='|' read -r tf_net tf_why; do audit "tunnel-move $1 subnet $tf_net refused: ${tf_why:-no answer}"; done
        [ $((td_lists + td_nets)) -gt 0 ] || { TXN=0; rm -f "$JOURNAL.lists" "$JOURNAL.nets" "$JOURNAL.failed" "$JOURNAL.owned"
            [ "$td_fail" = 0 ] || die router_rejected; done_ok "tunnel-move $1 nothing to move ip_categories=$td_own" unchanged; }
        save_router || die config_save_failed
        TXN=0
        rm -f "$JOURNAL.lists" "$JOURNAL.nets" "$JOURNAL.failed" "$JOURNAL.owned"
        # The IP categories' routes follow the default tunnel through policy-sync.
        if [ "$td_own" != 0 ] && [ -x "$POLICY_SYNC_BIN" ]; then
            (trap '' HUP; exec "$POLICY_SYNC_BIN" --reconcile) </dev/null >/dev/null 2>&1 &
        fi
        echo "info.moved=lists:$td_lists,subnets:$td_nets,failed:$td_fail,ip_categories:$td_own"
        done_ok "tunnel-move $1 lists=$td_lists subnets=$td_nets failed=$td_fail ip_categories=$td_own to=$2" changed
    fi
    ! awk -v i="$1" "$ROUTE_AWK"' $1 == "ip" && $2 == "route" && rdev() == i {f = 1} END {exit f ? 0 : 1}' "$RUNCFG" || die verification_failed
    # Last step: nothing depends on the interface any more.
    if engine_tunnel "$1"; then
        er_out=$("$ENG" remove "$1" 2>/dev/null)
        # The engine's reason (the refused Keenetic command and its answer) goes to the Panel.
        printf '%s\n' "$er_out" | tail -n 1 | grep -q '^result=' || { relay_reason "$er_out"; die router_rejected; }
    else
        ndm "no interface $1" || die router_rejected
    fi
    snapshot
    ! grep -qx "interface $1" "$RUNCFG" || die verification_failed
    save_router || die config_save_failed
    TXN=0
    td_lists=$(grep -c . "$JOURNAL.lists") td_nets=$(grep -c . "$JOURNAL.nets")
    rm -f "${TUNNEL_STORE:?}/$1/"*.conf "$VWARD_DEVICE_MAP_CACHE" "$JOURNAL.lists" "$JOURNAL.nets"
    rmdir "${TUNNEL_STORE:?}/$1" 2>/dev/null
    # The guard's memory of lists moved off this tunnel: nothing to come back to any more.
    td_gd=${TUNNEL_GUARD_STATE%/*}
    if [ -s "$td_gd/lists-fallback" ]; then
        awk -F '\t' -v t="$1" '$2 != t' "$td_gd/lists-fallback" > "$td_gd/lists-fallback.tmp.$$" &&
            mv -f "$td_gd/lists-fallback.tmp.$$" "$td_gd/lists-fallback"
        [ -s "$td_gd/lists-fallback" ] || rm -f "$td_gd/lists-fallback"
    fi
    grep -qx "FROM=$1" "$td_gd/fallback" 2>/dev/null && rm -f "$td_gd/fallback"
    done_ok "tunnel-delete $1 lists=$td_lists subnets=$td_nets to=$2" changed
}

subnet_present() {
    awk -v n="$1" -v m="$2" -v i="$3" "$ROUTE_AWK"'
        $1 == "ip" && $2 == "route" && $3 == n && rmask() == m && rdev() == i {f = 1} END {exit f ? 0 : 1}' "$RUNCFG"
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
    # The home, the provider's shared and reserved ranges never go into a tunnel: the router's
    # own answers there (an SSH session, the Panel, DNS) would follow them.
    [ "$2" = remove ] || ! printf '%s/%s\n' "$ts_net" "$ts_bits" | awk -F'[./]' '
        BEGIN {split("0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 198.18.0.0/15 224.0.0.0/3", r, " ")
            for (i in r) {split(r[i], q, "[./]"); rs[i] = ((q[1] * 256 + q[2]) * 256 + q[3]) * 256 + q[4]; re[i] = rs[i] + 2 ^ (32 - q[5]) - 1}}
        {s = ((($1 * 256 + $2) * 256 + $3) * 256 + $4); z = 2 ^ (32 - $5); s = int(s / z) * z; e = s + z - 1
         for (i in r) if (s <= re[i] && e >= rs[i]) exit 0; exit 1}' || die private_subnet 64
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
    case "$1" in manual|auto|prerestore|prereset|prelist) ;; *) die invalid_value 64 ;; esac
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

# list clear|delete GROUP: a whole list emptied, or removed from Keenetic with its route and
# exclusions; a copy of VWARD's settings first, every router step undone on a failure.
# AdaptiveAuto belongs to the route engine and a catalog service's list goes with the service
# («Сервисы»); VWARD's own list («Мои домены») is only cleared.
op_list() {
    case "$1" in clear|delete) ;; merge) op_list_merge "$2" "$3" ;; *) die invalid_operation 64 ;; esac
    printf '%s\n' "$2" | grep -Eq '^[A-Za-z0-9._-]{1,64}$' || die invalid_group 64
    load_profile_base
    [ "$2" != "$ADAPTIVE_GROUP" ] || die invalid_group 64
    [ "$1" = clear ] || [ "$2" != "${VWARD_POLICY_GROUP:-}" ] || die invalid_group 64
    ! awk -F '\t' -v g="$2" '$2 == g {f = 1} END {exit f ? 0 : 1}' "$SERVICES_STATE" 2>/dev/null || die service_list 64
    change_lock
    snapshot
    grep -qx "object-group fqdn $2" "$RUNCFG" || die list_not_found
    ( op_backup_create prelist ) >/dev/null || die backup_failed
    JOURNAL=$(mktemp /tmp/vward-console-list.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    TXN=1
    if [ "$1" = clear ]; then
        group_domains "$2" > "$JOURNAL.doh"
        [ -s "$JOURNAL.doh" ] || { TXN=0; done_ok "list clear $2" unchanged; }
        while IFS= read -r d; do
            ndm "no object-group fqdn $2 include $d" || die router_rejected
            echo "object-group fqdn $2 include $d" >> "$JOURNAL"
        done < "$JOURNAL.doh"
        snapshot
        [ -z "$(group_domains "$2")" ] || die verification_failed
    else
        lr=$(group_route "$2"); lr_t=${lr%%"$(printf '\t')"*}; lr_o=${lr#*"$(printf '\t')"}
        [ "$lr_o" != - ] || lr_o=
        # The list as it is, to put back: description, domains, exclusions, then its route.
        awk -v g="$2" '/^object-group fqdn / {cur = $3; next} /^!/ {cur = ""}
            cur == g && ($1 == "include" || $1 == "exclude" || $1 == "description") {sub(/^[ \t]+/, ""); print "object-group fqdn " g " " $0}' "$RUNCFG" > "$JOURNAL.moves"
        if [ -n "$lr_t" ]; then
            ndm "dns-proxy no route object-group $2 $lr_t" || die router_rejected
            echo "dns-proxy route object-group $2 $lr_t${lr_o:+ $lr_o}" >> "$JOURNAL"
        fi
        ndm "no object-group fqdn $2" || die router_rejected
        { echo "object-group fqdn $2"; cat "$JOURNAL.moves"; } | awk '{a[NR] = $0} END {for (i = NR; i > 0; i--) print a[i]}' >> "$JOURNAL"
        snapshot
        ! grep -qx "object-group fqdn $2" "$RUNCFG" || die verification_failed
    fi
    save_router || die config_save_failed
    TXN=0
    if [ "$1" = delete ]; then
        rm -f "${LISTS_STATE:?}/${2:?}"
        [ ! -f "$LISTS_CONF" ] || { grep -v "^[a-z_]*\.$2=" "$LISTS_CONF" > "$LISTS_CONF.$$" && cat "$LISTS_CONF.$$" > "$LISTS_CONF"; rm -f "$LISTS_CONF.$$"; }
    fi
    done_ok "list $1 $2" changed
}

# list merge SRC DST: two lists of one service (Viva 2026-10-19: «Youtube» and «YouTube»).
# SRC's domains go into DST, then SRC goes away with its route; DST keeps its own route.
op_list_merge() {
    for lm in "$1" "$2"; do printf '%s\n' "$lm" | grep -Eq '^[A-Za-z0-9._-]{1,64}$' || die invalid_group 64; done
    [ "$1" != "$2" ] || die invalid_group 64
    load_profile_base
    for lm in "$1" "$2"; do [ "$lm" != "$ADAPTIVE_GROUP" ] || die invalid_group 64; done
    [ "$1" != "${VWARD_POLICY_GROUP:-}" ] || die invalid_group 64
    ! awk -F '\t' -v g="$1" '$2 == g {f = 1} END {exit f ? 0 : 1}' "$SERVICES_STATE" 2>/dev/null || die service_list 64
    change_lock
    snapshot
    grep -qx "object-group fqdn $1" "$RUNCFG" && grep -qx "object-group fqdn $2" "$RUNCFG" || die list_not_found
    ( op_backup_create prelist ) >/dev/null || die backup_failed
    JOURNAL=$(mktemp /tmp/vward-console-list.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    TXN=1
    group_domains "$2" > "$JOURNAL.have"
    group_domains "$1" | awk -v f="$JOURNAL.have" 'BEGIN {while ((getline l < f) > 0) h[l] = 1} !($0 in h)' > "$JOURNAL.doh"
    lm_n=$(grep -c . "$JOURNAL.doh")
    [ $(( $(grep -c . "$JOURNAL.have") + lm_n )) -le "$SERVICE_LIMIT" ] || die list_too_long
    while IFS= read -r d; do
        [ -n "$d" ] || continue
        ndm "object-group fqdn $2 include $d" || die router_rejected
        echo "no object-group fqdn $2 include $d" >> "$JOURNAL"
    done < "$JOURNAL.doh"
    lr=$(group_route "$1"); lr_t=${lr%%"$(printf '\t')"*}; lr_o=${lr#*"$(printf '\t')"}
    [ "$lr_o" != - ] || lr_o=
    awk -v g="$1" '/^object-group fqdn / {cur = $3; next} /^!/ {cur = ""}
        cur == g && ($1 == "include" || $1 == "exclude" || $1 == "description") {sub(/^[ \t]+/, ""); print "object-group fqdn " g " " $0}' "$RUNCFG" > "$JOURNAL.moves"
    if [ -n "$lr_t" ]; then
        ndm "dns-proxy no route object-group $1 $lr_t" || die router_rejected
        echo "dns-proxy route object-group $1 $lr_t${lr_o:+ $lr_o}" >> "$JOURNAL"
    fi
    ndm "no object-group fqdn $1" || die router_rejected
    { echo "object-group fqdn $1"; cat "$JOURNAL.moves"; } | awk '{a[NR] = $0} END {for (i = NR; i > 0; i--) print a[i]}' >> "$JOURNAL"
    snapshot
    ! grep -qx "object-group fqdn $1" "$RUNCFG" || die verification_failed
    while IFS= read -r d; do
        [ -z "$d" ] || group_domains "$2" | grep -qxF "$d" || die verification_failed
    done < "$JOURNAL.doh"
    save_router || die config_save_failed
    TXN=0
    rm -f "${LISTS_STATE:?}/${1:?}" "$JOURNAL.have" "$JOURNAL.doh" "$JOURNAL.moves"
    [ ! -f "$LISTS_CONF" ] || { grep -v "^[a-z_]*\.$1=" "$LISTS_CONF" > "$LISTS_CONF.$$" && cat "$LISTS_CONF.$$" > "$LISTS_CONF"; rm -f "$LISTS_CONF.$$"; }
    done_ok "list merge $1 into $2 domains=$lm_n" changed
}

# ---- Очистка ----
# What VWARD may clean, its own files only: ID|DIR|KEEP|PATTERN (the newest KEEP entries
# stay, so the last copy of every kind is never removed). The owner's backups
# («Резервные копии»), settings and tunnel keys are not here.
BACKUPS_ROOT=${VWARD_BACKUPS_ROOT:-/opt/var/backups/vward}
LOG_ROOT=${VWARD_LOG_ROOT:-/opt/var/log}
cleanup_groups() {
    cat <<CG
archive|$LOG_ROOT/vward/archive|0|*.gz
diagnostics|$LOG_ROOT/vward/diagnostics|0|*
forensics|$BACKUPS_ROOT/forensics|1|*
legacy|$BACKUPS_ROOT/legacy-scripts|0|*
packages|$BACKUPS_ROOT/ext-update|1|*
settings|$BACKUP_DIR|1|*
ads|$BACKUPS_ROOT/ads-privacy-guard|1|publish-*
ads|$BACKUPS_ROOT/ads-privacy-guard/manual|1|*
ads|$BACKUPS_ROOT/ads-privacy-guard/settings|1|*
ads|$BACKUPS_ROOT/ads-privacy-guard/source-settings|1|*
CG
}
# cleanup_old DIR KEEP PATTERN: the entries that may go, oldest last.
cleanup_old() {
    [ -d "$1" ] || return 0
    ( cd "$1" && ls -1td -- $3 2>/dev/null ) | tail -n +$(($2 + 1)) | grep -v '/'
}
op_cleanup() {
    case "$1" in sizes|all|archive|diagnostics|forensics|legacy|packages|settings|ads) ;; *) die invalid_value 64 ;; esac
    if [ "$1" = sizes ]; then
        cleanup_groups | while IFS='|' read -r cg_id cg_dir cg_keep cg_pat; do
            cleanup_old "$cg_dir" "$cg_keep" "$cg_pat" | while IFS= read -r cg_n; do
                du -sk "$cg_dir/$cg_n" 2>/dev/null | awk -v id="$cg_id" '{print id, $1}'
            done
        done | awk '{s[$1] += $2} END {for (k in s) printf "size=%s:%d\n", k, s[k]}'
        # The live journals: shown, compressed by «Сжать журналы», never deleted here.
        printf 'size=journals:%s\n' "$(ls -ln "$LOG_ROOT"/vward-*.log "$LOG_ROOT"/vward/*.log 2>/dev/null | awk '{s += $5} END {printf "%d", s / 1024}')"
        printf 'result=unchanged\n'; exit 0
    fi
    cl_n=0 cl_list=$(cleanup_groups)
    set -f
    while IFS='|' read -r cg_id cg_dir cg_keep cg_pat; do
        [ "$1" = all ] || [ "$1" = "$cg_id" ] || continue
        set +f; cg_old=$(cleanup_old "$cg_dir" "$cg_keep" "$cg_pat"); set -f
        for cg_n in $cg_old; do
            rm -rf "${cg_dir:?}/${cg_n:?}" && cl_n=$((cl_n + 1))
        done
    done <<CL
$cl_list
CL
    set +f
    [ "$cl_n" -gt 0 ] || done_ok "cleanup $1" unchanged
    done_ok "cleanup $1 removed=$cl_n" changed
}

# ---- Сброс настроек ----
# reset settings: the switches and parameters as after installation (a copy of the settings
# first); tunnels, lists, subnets, routes, the update channel and the Panel's login stay.
op_reset() {
    [ "$1" = settings ] || die invalid_value 64
    ( op_backup_create prereset ) >/dev/null || die backup_failed
    rs_route=
    [ ! -e "$COMPONENT_STATE/route-engine.disabled" ] || rs_route=1
    rm -f "$TUNNEL_GUARD_FLAG" "$TUNNEL_FALLBACK_FLAG" "$TUNNEL_RETURN_FLAG" "$WAN_GUARD_FLAG" "$ADAPTIVE_FLAG" \
        "$ETC/agents.conf" "$TUNNEL_AUTO_CONF" "$JOURNAL_CONF" "$COMPONENT_STATE"/*.disabled 2>/dev/null
    [ ! -f "$LISTS_CONF" ] || set_kv "$LISTS_CONF" smartdns_guard 1 0644 || true
    [ ! -f "$EXT_CONF" ] || { set_kv "$EXT_CONF" AGH_AUTO 0 0600; set_kv "$EXT_CONF" ENTWARE_AUTO 0 0600; } || true
    [ -z "$rs_route" ] || [ ! -x "$ROUTE_ENGINE_INIT" ] || "$ROUTE_ENGINE_INIT" start </dev/null >/dev/null 2>&1 || true
    mkdir -p "$ROUTE_STATE" 2>/dev/null && echo 0 > "$REFRESH_TS" 2>/dev/null
    done_ok "reset settings" changed
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

# smartdns-domain add|remove DOMAIN: the domain resolved by Smart DNS in AdGuard Home,
# through the upstream already serving most Smart DNS domains (Aeternia and the like);
# remove takes it and its subdomains out.  Keenetic's own Smart DNS rows are not touched.
# Smart DNS without AdGuard Home (fix.30): the owner's own DoH server (smartdns-server), else the
# server already used by Keenetic's own Smart DNS lines; a line per domain in Keenetic, which
# holds at most 8 of them.
SMARTDNS_CONF=${VWARD_SMARTDNS_CONF:-$ETC/smartdns.conf}
SMARTDNS_KEENETIC_MAX=8
smartdns_url() {
    su=$(awk -F= '$1 == "SMARTDNS_URL" {print substr($0, index($0, "=") + 1); exit}' "$SMARTDNS_CONF" 2>/dev/null)
    [ -n "$su" ] || su=$(doh_lines | awk '$(NF-1) == "domain" {n[$3]++} END {for (u in n) if (n[u] > m) {m = n[u]; b = u}; print b}')
    [ -n "$su" ] && printf '%s\n' "$su"
}
# keenetic_smartdns add|remove DOMAIN
keenetic_smartdns() {
    load_profile_base
    change_lock
    snapshot
    ks_have=$(doh_lines | awk -v d="$2" '$(NF-1) == "domain" && tolower($NF) == d')
    if [ "$1" = add ]; then
        [ -z "$ks_have" ] || done_ok "smartdns-domain add $2 keenetic" unchanged
        ks_url=$(smartdns_url) || die smartdns_not_configured
        ks_used=$(doh_lines | awk '$(NF-1) == "domain"' | grep -c .)
        [ "$ks_used" -lt "$SMARTDNS_KEENETIC_MAX" ] || { RELAY_REASON="used $ks_used of $SMARTDNS_KEENETIC_MAX"; die smartdns_keenetic_full; }
        # The form of the lines already there for this server, else the documented one.
        ks_src=same-server
        ks_tpl=$(doh_lines | awk -v u="$ks_url" '$3 == u && $(NF-1) == "domain" {NF -= 1; print; exit}')
        # Another server's lines show the form this router takes («dnsm on ISP»).
        [ -n "$ks_tpl" ] || { ks_src=other-server; ks_tpl=$(doh_lines | awk -v u="$ks_url" '$(NF-1) == "domain" {$3 = u; NF -= 1; print; exit}'); }
        [ -n "$ks_tpl" ] || { ks_src=default; ks_tpl="https upstream $ks_url dnsm on $(wan_route_target) domain"; }
        # Keenetic refused a form (fix.33: the default one, with 0 of 8 used, Viva 2026-10-19):
        # the shorter forms in turn; each refusal goes to the journal with Keenetic's answer.
        ks_line=
        for ks_try in "$ks_tpl $2" "https upstream $ks_url dnsm domain $2" "https upstream $ks_url domain $2"; do
            if ndm "dns-proxy $ks_try"; then ks_line=$ks_try; break; fi
            audit "smartdns-domain add $2 keenetic refused form=$(printf '%s' "$ks_try" | sed 's#\(https://[^/ ]*\)/[^ ]*#\1/…#g') used=$ks_used/$SMARTDNS_KEENETIC_MAX source=$ks_src: ${NDM_REPLY:-no answer}"
            # No «dns-proxy https» at all: Keenetic's DNS-over-HTTPS component is not installed
            # (Viva 2026-10-21) - no other form helps, the owner is told what to install.
            case "$NDM_REPLY" in *"no such command: https"*) RELAY_REASON="no dns-proxy https"; die smartdns_doh_component ;; esac
        done
        [ -n "$ks_line" ] || die router_rejected
        snapshot
        doh_present "$ks_line" || die verification_failed
        audit "smartdns-domain add $2 keenetic accepted form=$(printf '%s' "$ks_line" | sed 's#\(https://[^/ ]*\)/[^ ]*#\1/…#g') used=$((ks_used + 1))/$SMARTDNS_KEENETIC_MAX source=$ks_src"
    else
        [ -n "$ks_have" ] || return 0
        printf '%s\n' "$ks_have" | while IFS= read -r ks_line; do
            doh_remove "$ks_line" || exit 1
        done || die router_rejected
    fi
    save_router || die config_save_failed
}
# smartdns-store auto|keenetic|agh: where new Smart DNS domains go (fix.32) - the owner's
# choice; auto: AdGuard Home while it works, else Keenetic.
smartdns_store() {
    ss_v=$(awk -F= '$1 == "SMARTDNS_STORE" {print $2; exit}' "$SMARTDNS_CONF" 2>/dev/null)
    case "$ss_v" in keenetic|agh) echo "$ss_v" ;; *) echo auto ;; esac
}
op_smartdns_store() {
    case "$1" in auto|keenetic|agh) ;; *) die invalid_value 64 ;; esac
    [ "$(smartdns_store)" != "$1" ] || done_ok "smartdns-store $1" unchanged
    # AdGuard Home chosen: it must be there to take them.
    [ "$1" != agh ] || [ -r "${VWARD_ADGUARD_CONFIG:-/opt/etc/AdGuardHome/AdGuardHome.yaml}" ] || die adguard_unavailable
    new_tmp "$SMARTDNS_CONF" || die write_failed
    { grep -v '^SMARTDNS_STORE=' "$SMARTDNS_CONF" 2>/dev/null; [ "$1" = auto ] || printf 'SMARTDNS_STORE=%s\n' "$1"; } > "$TMPFILE" || die write_failed
    if [ -s "$TMPFILE" ]; then install_tmp "$SMARTDNS_CONF" 0600 || die write_failed; else rm -f "$SMARTDNS_CONF"; fi
    done_ok "smartdns-store $1" changed
}
op_smartdns_domain() {
    case "$1" in add|remove) ;; *) die invalid_operation 64 ;; esac
    valid_domain "$2" || die invalid_domain 64
    JOURNAL=$(umask 077; mktemp /tmp/vward-console-smartdns.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    if [ "$1" = add ] && [ "$(smartdns_store)" = keenetic ]; then
        keenetic_smartdns add "$2"
        done_ok "smartdns-domain add $2 keenetic" changed
    fi
    if [ "$1" = add ]; then
        # The server chosen in the Panel; «auto» (the one AdGuard Home has most) only without one:
        # a freshly installed AdGuard Home has none and refused every domain (Viva 2026-10-19).
        # Read from the file only: smartdns_url's fallback reads Keenetic's configuration, which
        # is not loaded on this path (its awk then waited for standard input, found by the test).
        sd_u=$(awk -F= '$1 == "SMARTDNS_URL" {print substr($0, index($0, "=") + 1); exit}' "$SMARTDNS_CONF" 2>/dev/null)
        [ -n "$sd_u" ] || sd_u=auto
        printf '%s\t%s\n' "$2" "$sd_u" > "$JOURNAL.agh" || die write_failed
        agh_control smartdns-put "$JOURNAL.agh" && done_ok "smartdns-domain add $2" changed
        # The owner keeps Smart DNS in AdGuard Home: no quiet move to Keenetic.
        [ "$(smartdns_store)" != agh ] || die "$AGH_ERR"
        # No AdGuard Home, or one not connected to VWARD: Keenetic itself. One connected but not
        # set up for Smart DNS says so (the owner chose to keep Smart DNS there).
        case "$AGH_ERR" in smartdns_agh_unavailable|adguard_unavailable|adguard_auth_required) ;; *) die "$AGH_ERR" ;; esac
        keenetic_smartdns add "$2"
        done_ok "smartdns-domain add $2 keenetic" changed
    fi
    printf '%s\n' "$2" > "$JOURNAL.agh.inc" || die write_failed
    sd_agh=0
    if agh_control smartdns-take "$JOURNAL.agh.inc" "$JOURNAL.agh"; then [ ! -s "$JOURNAL.agh" ] || sd_agh=1; fi
    sd_k=0
    snapshot
    ! doh_lines | awk -v d="$2" '$(NF-1) == "domain" && tolower($NF) == d {f = 1} END {exit f ? 0 : 1}' || { keenetic_smartdns remove "$2"; sd_k=1; }
    [ "$sd_agh$sd_k" != 00 ] || done_ok "smartdns-domain remove $2" unchanged
    done_ok "smartdns-domain remove $2" changed
}
# smartdns-server set|clear: the owner's own Smart DNS server, a DoH address. It comes on stdin
# (it may hold a personal token) and is never printed, logged or passed to another program here.
op_smartdns_server() {
    case "$1" in
        set) IFS= read -r ss_url || die invalid_value 64
             printf '%s\n' "$ss_url" | grep -Eq '^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~/-]{0,200})?$' || die invalid_value 64
             new_tmp "$SMARTDNS_CONF" || die write_failed
             { grep -v '^SMARTDNS_URL=' "$SMARTDNS_CONF" 2>/dev/null; printf 'SMARTDNS_URL=%s\n' "$ss_url"; } > "$TMPFILE" || die write_failed
             cmp -s "$TMPFILE" "$SMARTDNS_CONF" && done_ok "smartdns-server set" unchanged
             install_tmp "$SMARTDNS_CONF" 0600 || die write_failed
             done_ok "smartdns-server set" changed ;;
        clear) grep -q '^SMARTDNS_URL=' "$SMARTDNS_CONF" 2>/dev/null || done_ok "smartdns-server clear" unchanged
             new_tmp "$SMARTDNS_CONF" || die write_failed
             grep -v '^SMARTDNS_URL=' "$SMARTDNS_CONF" > "$TMPFILE"
             if [ -s "$TMPFILE" ]; then install_tmp "$SMARTDNS_CONF" 0600 || die write_failed; else rm -f "$SMARTDNS_CONF" || die write_failed; fi
             done_ok "smartdns-server clear" changed ;;
        *) die invalid_operation 64 ;;
    esac
}

# ai ID|all vpn|vpn:TUNNEL|dns|isp: the way of an AI service of the catalog (owner 2026-10-17):
# VPN - the service's list through a tunnel («Сервисы»); Smart DNS - no list, its main domains
# answered by Smart DNS; provider - neither. Each step is a run of this helper that checks itself.
# ai_main ID: the service's own main domains for Smart DNS, as the catalog names them - never
# cut to the second level (aistudio.google.com gave google.com: all of Google through Smart
# DNS, fix.30). The service's own name first, then the names with its brand, then its own
# short domains; the hosts of shared platforms (CDN, telemetry, a big company's other
# services) only when they carry the brand; a name inside one already taken is left out; at
# most 4 (Keenetic holds 8 Smart DNS domains in all).
AI_SHARED=" google.com googleapis.com gstatic.com microsoft.com microsoftapp.net live.net msedge.net a-msedge.net azureedge.net github.com githubusercontent.com amazonaws.com cloudfront.net cloudflare.com cloudflareaccess.com facebook.com fbcdn.net apple.com akamaized.net fastly.net fastly-edge.com datadoghq.com auth0.com adjust.com cloudinary.com appspot.com cloudfunctions.net todesktop.com "
ai_main() {
    "$JQ" -r --arg i "$1" '.services[] | select(.id == $i) | ([$i] + .domains)[]' "$SV_CAT" 2>/dev/null |
        awk -v id="$1" -v shared="$AI_SHARED" '
            BEGIN {brand = id; sub(/[.].*/, "", brand); if (length(brand) < 4) brand = ""}
            {d = tolower($0)} d !~ /^[a-z0-9-]+([.][a-z0-9-]+)+$/ {next}
            seen[d]++ {next}
            {n = split(d, l, "."); root = l[n - 1] "." l[n]; own = brand != "" && index(d, brand)}
            d != id && !own && index(shared, " " root " ") && index(id, root) == 0 {next}
            {print (d == id ? 0 : own ? 1 : n == 2 ? 2 : 3) "\t" n "\t" d}' |
        sort -k1,1n -k2,2n -k3,3 | cut -f3 |
        awk '{for (k in got) if (length($0) > length(k) && substr($0, length($0) - length(k)) == "." k) next; got[$0] = 1; print}' | head -n 4
}
ai_step() {
    as_all=$(sh "$0" "$@" </dev/null 2>/dev/null)
    as_out=$(printf '%s\n' "$as_all" | tail -n 1)
    case "$as_out" in result=*) AI_RES=${as_out#result=}; return 0 ;; esac
    AI_ERR=${as_out#error=}; case "$AI_ERR" in ''|*[!a-z0-9_]*) AI_ERR=helper_failed ;; esac
    # Keenetic's own answer goes on to the Panel and the journal (fix.30 showed only «отклонил»).
    relay_reason "$as_all"
    return 1
}
# The AI services the owner sent to Smart DNS when Keenetic had no room (8 of 8): the Panel
# says when room frees up («Перевести»). One id a line.
AI_WAIT=${VWARD_AI_WAIT:-$ETC/smartdns-wait}
ai_wait() {
    [ -f "$AI_WAIT" ] || [ "$1" = add ] || return 0
    { [ ! -f "$AI_WAIT" ] || grep -vxF -- "$2" "$AI_WAIT"; [ "$1" != add ] || printf '%s\n' "$2"; } > "$AI_WAIT.$$" 2>/dev/null &&
        mv -f "$AI_WAIT.$$" "$AI_WAIT"
    [ -s "$AI_WAIT" ] || rm -f "$AI_WAIT"
}
# ai ID|all WAY [keep]: keep - the owner's answer to «no room in Smart DNS»: the service still
# waits for Smart DNS.
op_ai() {
    SV_CAT=$(services_catalog) || die services_unavailable
    case "$2" in vpn|dns|isp) ai_to=auto ;; vpn:*) ai_to=${2#vpn:}; vward_valid_ndm_name "$ai_to" || die invalid_value 64 ;; *) die invalid_value 64 ;; esac
    case "${3:-}" in ''|keep) ;; *) die invalid_value 64 ;; esac
    if [ "$1" = all ]; then
        ai_ids=$("$JQ" -r '.services[] | select(.category == "ai") | .id' "$SV_CAT")
    else
        printf '%s\n' "$1" | grep -Eq '^[a-z0-9][a-z0-9.@_-]{0,62}$' || die invalid_service 64
        "$JQ" -e --arg i "$1" 'any(.services[]; .id == $i and .category == "ai")' "$SV_CAT" >/dev/null 2>&1 || die unknown_service 64
        ai_ids=$1
    fi
    ai_n=0 ai_left=
    for ai_id in $ai_ids; do
        ai_on=$(service_row "$ai_id")
        case "$2" in
            vpn*) if [ -n "$ai_on" ]; then ai_step service tunnel "$ai_id" "$ai_to" || die "$AI_ERR"
                  else ai_step service on "$ai_id" "$ai_to" || die "$AI_ERR"; fi
                  [ "${3:-}" = keep ] || ai_wait del "$ai_id" ;;
            dns)
                # The domains first, the VPN list after: with no room (Keenetic's 8 Smart DNS
                # lines taken, fix.31) the service stays as it was and its new lines go again.
                ai_added= ai_full=0
                for ai_d in $(ai_main "$ai_id"); do
                    if ai_step smartdns-domain add "$ai_d"; then
                        [ "$AI_RES" != changed ] || ai_added="$ai_added $ai_d"
                    elif [ "$AI_ERR" = smartdns_keenetic_full ]; then ai_full=1; break
                    else die "$AI_ERR"; fi
                done
                if [ "$ai_full" = 1 ]; then
                    for ai_d in $ai_added; do ai_step smartdns-domain remove "$ai_d" || :; done
                    ai_wait add "$ai_id"
                    ai_left="$ai_left${ai_left:+,}$ai_id"
                    continue
                fi
                [ -z "$ai_on" ] || ai_step service off "$ai_id" || die "$AI_ERR"
                ai_wait del "$ai_id" ;;
            *) [ -z "$ai_on" ] || ai_step service off "$ai_id" || die "$AI_ERR"
               for ai_d in $(ai_main "$ai_id"); do ai_step smartdns-domain remove "$ai_d" || die "$AI_ERR"; done
               [ "${3:-}" = keep ] || ai_wait del "$ai_id" ;;
        esac
        ai_n=$((ai_n + 1))
    done
    if [ -n "$ai_left" ]; then
        # One service: the Panel asks which way instead; several: the rest is asked about.
        printf 'info.left=%s\n' "$ai_left"
        [ "$1" = all ] && [ "$ai_n" -gt 0 ] || die smartdns_keenetic_full
    fi
    done_ok "ai $1 $2 services=$ai_n${ai_left:+ left=$ai_left}" changed
}

# smartdns-guard 0|1: 0 lets AdaptiveAuto take Smart DNS domains again.
op_smartdns_guard() {
    case "$1" in 0|1) ;; *) die invalid_value 64 ;; esac
    set_kv "$LISTS_CONF" smartdns_guard "$1" 0644 || done_ok "smartdns-guard $1" unchanged
    mkdir -p "$ROUTE_STATE" 2>/dev/null && echo 0 > "$REFRESH_TS" 2>/dev/null
    done_ok "smartdns-guard $1" changed
}

# journal keep DAYS | size MB: how long and how much of the technical journals is kept
# (housekeeping applies it every hour; MB 0: no limit but the USB drive).
op_journal() {
    case "$1:$2" in
        keep:1|keep:3|keep:7|keep:30|keep:180|keep:365) jk=KEEP_DAYS ;;
        size:0|size:1|size:5|size:10|size:30) jk=MAX_MB ;;
        *) die invalid_value 64 ;;
    esac
    set_kv "$JOURNAL_CONF" "$jk" "$2" 0644 || done_ok "journal $1=$2" unchanged
    done_ok "journal $1=$2" changed
}

# op_agents_mode AGENT MODE: «Наблюдение | Действие» (fix.28.6). all sets every agent (their own
# choices go); one agent: its own choice. Read by vward_agent_mode (the admission library).
op_agents_mode() {
    case "$1:$2" in
        all:act|all:watch) ;;
        network:act|network:watch|components:act|components:watch|updates:act|updates:watch|maintenance:act|maintenance:watch) ;;
        *) die invalid_value 64 ;;
    esac
    am_conf=${VWARD_AGENTS_CONF:-$ETC/agents.conf}
    if [ "$1" = all ]; then
        am_old=$(cat "$am_conf" 2>/dev/null)
        [ "$am_old" != "all=$2" ] || done_ok "agents-mode all=$2" unchanged
        [ ! -f "$am_conf" ] || backup_file "$am_conf" || die backup_failed
        new_tmp "$am_conf" || die write_failed
        printf 'all=%s\n' "$2" > "$TMPFILE" || die write_failed
        install_tmp "$am_conf" 0644 || die write_failed
        done_ok "agents-mode all=$2" changed
    fi
    set_kv "$am_conf" "$1" "$2" 0644 || done_ok "agents-mode $1=$2" unchanged
    done_ok "agents-mode $1=$2" changed
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
    # Back on: the components that went off with it (their flag says «with ID») come back
    # too, with what they need; one the owner switched off by itself stays off.
    if [ "$2" = 1 ] && [ -d "$COMPONENT_STATE" ]; then
        for f in "$COMPONENT_STATE"/*.disabled; do
            [ -f "$f" ] || continue
            c=${f##*/}; c=${c%.disabled}
            [ "$c" != "$1" ] && grep -q "(with $1)\$" "$f" 2>/dev/null || continue
            set_ids="$set_ids
$(component_closure "$c" 1)" || die registry_unavailable
        done
        set_ids=$(printf '%s\n' "$set_ids" | awk 'NF && !seen[$0]++')
    fi
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
            printf 'disabled from VWARD Panel %s (with %s)\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$1" > "$flag" || die write_failed
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

# ---------- Updates of other software ----------
# Entware packages (AdGuard Home among them) and the Keenetic firmware.  A
# package is installed only from the list the last check found, after a copy
# of its files and of the opkg database; if a check that passed before fails
# after, the copy goes back.  The firmware is only switched between automatic
# and manual and between channels: installing it reboots the router.

EXT_CONF=${VWARD_EXT_UPDATE_CONF:-$ETC/ext-update.conf}
EXT_STATE=${VWARD_EXT_UPDATE_STATE:-/opt/var/lib/vward/ext-update}
EXT_BACKUP=${VWARD_EXT_UPDATE_BACKUP:-/opt/var/backups/vward/ext-update}
OPKG=${VWARD_OPKG:-opkg}
# Package files are named as opkg lists them (/opt/...); EXT_R is where that tree lives.
EXT_R=${VWARD_EXT_ROOT:-}
# Their failure takes the shell, the package manager or SSH with them: never
# automatic, by hand only with a second confirmation.
EXT_CRITICAL=" libc libgcc libpthread librt libssp libstdcpp busybox opkg entware-opt entware-release entware-upgrade dropbear "
EXT_MIN_FREE_KB=20480
OPKG_STATUS=/opt/lib/opkg/status
OPKG_INFO=/opt/lib/opkg/info

EXT_LOCKED=0
DNS_GUARD=${VWARD_ADS_DNS_GUARD_BIN:-/opt/bin/vward-ads-privacy-dns-guard.sh}
AGH_PLANNED=
# One package operation at a time, whoever started it (the console or the daily run).
ext_lock() {
    [ "$EXT_LOCKED" = 1 ] && return 0
    mkdir -p "$EXT_STATE" && vward_lock_take "$EXT_STATE/lock" || die ext_update_busy 75
    EXT_LOCKED=1
}

ext_critical() { case "$EXT_CRITICAL" in *" $1 "*) return 0 ;; esac; return 1; }
valid_pkg() { printf '%s\n' "$1" | grep -Eq '^[a-z0-9][a-z0-9+._-]{0,63}$'; }

# ext_firmware_refresh: the firmware's version, channel and update state.
# Keenetic may answer the first check-update with empty fields while it checks
# in the background: asked again a few times, then the installed version alone
# (show version) rather than nothing.
ext_firmware_refresh() {
    mkdir -p "$EXT_STATE" || return 1
    fr_rci=${VWARD_RCI_BASE:-http://127.0.0.1:79/rci}
    fr_try=0
    while :; do
        "${VWARD_CURL_BIN:-curl}" --fail --silent --connect-timeout 3 --max-time 30 -X POST \
            -H 'Content-Type: application/json' -d '[{"parse":"components check-update"}]' \
            "$fr_rci/" > "$EXT_STATE/firmware.raw" 2>/dev/null
        "$JQ" -e '.[0].parse | (.release | type) == "string" and .release != ""' "$EXT_STATE/firmware.raw" >/dev/null 2>&1 && break
        fr_try=$((fr_try + 1))
        [ "$fr_try" -lt "${VWARD_FW_TRIES:-6}" ] || break
        sleep "${VWARD_FW_TRY_DELAY:-5}"
    done
    if "$JQ" -e '.[0].parse | (.release | type) == "string" and .release != ""' "$EXT_STATE/firmware.raw" >/dev/null 2>&1; then
        # check-update names the release on offer, not the one installed (the Panel said «5.1.7
        # installed» on a router with 5.1.6, a Viva 2026-10-12): installed from show version.
        fr_ver=$("${VWARD_CURL_BIN:-curl}" --fail --silent --connect-timeout 3 --max-time 15 "$fr_rci/show/version" 2>/dev/null |
            "$JQ" -c 'select((.release | type) == "string" and .release != "") | {release, title}' 2>/dev/null)
        "$JQ" --argjson v "${fr_ver:-null}" '.[0].parse |
            (.["update-available"] == true) as $up |
            {release: ($v.release // (if $up then null else .release end)), title: ($v.title // (if $up then null else .title end)),
             available: (if $up then {release, title} else null end),
             channel: (.sandbox // ""), update_available: $up,
             auto_update: (.["auto-update-enabled"] == true), checked: (.timestamp // ""),
             channels: [.sandboxes[]? | select(type == "object") | {name, version}]}' "$EXT_STATE/firmware.raw"
    else
        "${VWARD_CURL_BIN:-curl}" --fail --silent --connect-timeout 3 --max-time 15 "$fr_rci/show/version" 2>/dev/null |
        "$JQ" -e 'select((.release | type) == "string" and .release != "") |
            {release, title, channel: (.sandbox // ""), update_available: null, auto_update: null, checked: "", channels: []}'
    fi > "$EXT_STATE/firmware.json.tmp" 2>/dev/null && [ -s "$EXT_STATE/firmware.json.tmp" ] &&
    mv -f "$EXT_STATE/firmware.json.tmp" "$EXT_STATE/firmware.json" || { rm -f "$EXT_STATE/firmware.json.tmp"; return 1; }
    rm -f "$EXT_STATE/firmware.raw"
}

# ext_upgradable: refresh the list of packages with a newer version (name, installed, new).
# On the official build of AdGuard Home (ext-agh-official) its Entware package is not offered:
# opkg would bring back the build that cannot run here.
ext_upgradable() {
    agh_official_adopt
    eu_hold=; [ ! -s "$EXT_STATE/agh-official" ] || eu_hold=adguardhome-go
    "$OPKG" list-upgradable 2>/dev/null |
        awk -F' - ' -v hold="$eu_hold" 'NF >= 3 && $1 ~ /^[a-z0-9][a-z0-9+._-]*$/ && $1 != hold {print $1 "\t" $2 "\t" $3}' > "$EXT_STATE/upgradable.tsv.tmp" &&
        mv -f "$EXT_STATE/upgradable.tsv.tmp" "$EXT_STATE/upgradable.tsv"
}

# ---------- AdGuard Home: the official build ----------
# Entware's AdGuard Home for mipsel is built for a processor with an FPU: on the MIPS 1004Kc of
# Keenetic Viva it dies at once on an illegal instruction (exit 132; v0.107.73, 2026-10-16), and
# DNS went past AdGuard Home for a day. AdGuard's own «softfloat» build runs. VWARD installs that
# build, pinned to a version and checksums it knows, after a copy of the old file; a build that
# does not start is taken back. Newer pins come with VWARD releases.
AGH_OFFICIAL_VERSION=v0.107.73
AGH_OFFICIAL_BASE=${VWARD_AGH_OFFICIAL_BASE:-https://github.com/AdguardTeam/AdGuardHome/releases/download}
AGH_OFFICIAL_MIN_FREE_KB=81920

# agh_official_arch: the build for this router (AdGuard's name), or nothing.
agh_official_arch() {
    [ -z "${VWARD_AGH_ARCH:-}" ] || { printf '%s\n' "$VWARD_AGH_ARCH"; return 0; }
    # The same test as the tunnel engines and sentinel (fix.33: «mips» only and a byte order
    # that had to be read gave «нет сборки» on a Viva the engines found mipsle on).
    oa_m=$(uname -m 2>/dev/null)
    case "$oa_m" in
        mips*) ;;
        *) audit "ext-agh-official arch: uname=${oa_m:-none}"; return 1 ;;
    esac
    # Byte order from an ELF header (byte 5: 1 little, 2 big); unreadable - little (the MIPS
    # routers Keenetic makes are little-endian).
    oa_e=$(dd if=/bin/sh bs=1 skip=5 count=1 2>/dev/null | od -An -tu1 2>/dev/null | tr -d ' ')
    case "$oa_m:$oa_e" in
        mipsel*|mipsle*|*:1|*:) echo mipsle_softfloat ;;
        *) audit "ext-agh-official arch: uname=$oa_m byte_order=$oa_e (big-endian, no build)"; return 1 ;;
    esac
}

# agh_official_pin ARCH: «archive-sha256 binary-sha256» of the pinned version.
agh_official_pin() {
    case "$1" in
        mipsle_softfloat) echo "${VWARD_AGH_OFFICIAL_PIN:-b56692f9f85676693116c3f4e4922210b6a96c072b8dfa81711185bbabf49bd9 8f316aebdd65aac0090edf005fdb007b9c1bffb28f316f549f79c26a2c479311}" ;;
        *) return 1 ;;
    esac
}

agh_official_bin() { vward_agh_binary 2>/dev/null || echo "$EXT_R/opt/sbin/AdGuardHome"; }

# agh_official_adopt: AdGuard Home already is the pinned official file (put by hand): recorded,
# so its Entware package is no longer offered.
agh_official_adopt() {
    [ ! -s "$EXT_STATE/agh-official" ] || return 0
    command -v vward_agh_binary >/dev/null 2>&1 || return 0
    oo_arch=$(agh_official_arch) && oo_pin=$(agh_official_pin "$oo_arch") || return 0
    oo_bin=$(vward_agh_binary) || return 0
    [ "$(sha256sum "$oo_bin" 2>/dev/null | cut -d' ' -f1)" = "${oo_pin#* }" ] || return 0
    printf 'version=%s\narch=%s\nat=%s\nby=found\n' "$AGH_OFFICIAL_VERSION" "$oo_arch" "$(date +%s)" > "$EXT_STATE/agh-official"
}

ao_note() {
    command -v vward_note >/dev/null 2>&1 ||
        { [ ! -r "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}" ] || . "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}"; } 2>/dev/null
    command -v vward_note >/dev/null 2>&1 || return 0
    vward_note "$1" "$2" "$3" d-agh
}

# ao_up: AdGuard Home running a minute after its start (it loads its lists first).
ao_up() {
    ao_w=0
    while :; do
        "${VWARD_PIDOF_BIN:-pidof}" AdGuardHome >/dev/null 2>&1 && return 0
        [ "$ao_w" -lt "${VWARD_AGH_START_WAIT:-60}" ] || return 1
        sleep 5; ao_w=$((ao_w + 5))
    done
}

# op_ext_agh_official repair|install|status
#   repair   (the components agent) only when the installed program cannot run;
#   install  (the Panel, the daily run) the pinned version when another one is installed.
op_ext_agh_official() {
    case "$1" in repair|install|status) ;; *) die invalid_value 64 ;; esac
    mkdir -p "$EXT_STATE" || die write_failed
    ao_arch=$(agh_official_arch) || ao_arch=
    ao_pin=; [ -z "$ao_arch" ] || ao_pin=$(agh_official_pin "$ao_arch") || ao_pin=
    if [ "$1" = status ]; then
        ao_cur=; [ ! -r "$EXT_STATE/agh-official" ] || ao_cur=$(sed -n 's/^version=//p' "$EXT_STATE/agh-official")
        printf 'arch=%s\npinned=%s\ninstalled=%s\n' "${ao_arch:-none}" "$([ -n "$ao_pin" ] && echo "$AGH_OFFICIAL_VERSION")" "$ao_cur"
        exit 0
    fi
    ext_lock
    if [ -z "$ao_pin" ]; then
        audit "ext-agh-official no build for ${ao_arch:-$(uname -m 2>/dev/null)}"
        [ "$1" != repair ] || ao_note err "AdGuard Home: нет подходящей сборки" \
            "Программа AdGuard Home не запускается на этом роутере, а официальной сборки для его процессора VWARD не знает. Установите AdGuard Home вручную."
        die agh_no_build
    fi
    ao_bin=$(agh_official_bin)
    ao_old=; [ ! -x "$ao_bin" ] || ao_old=$("$ao_bin" --version 2>/dev/null | sed -n 's/.*version //p' | head -n 1)
    if [ "$1" = repair ] && [ -n "$ao_old" ]; then
        done_ok "ext-agh-official not needed: $ao_old runs" unchanged
    fi
    if [ "$1" = install ] && [ "$ao_old" = "$AGH_OFFICIAL_VERSION" ] &&
       [ "$(sha256sum "$ao_bin" 2>/dev/null | cut -d' ' -f1)" = "${ao_pin#* }" ]; then
        agh_official_adopt
        done_ok "ext-agh-official $AGH_OFFICIAL_VERSION installed already" unchanged
    fi
    free=$(df -k "$EXT_R/opt" 2>/dev/null | awk 'NR == 2 {print $4}')
    case "$free" in ''|*[!0-9]*) free=0 ;; esac
    [ "$free" -ge "$AGH_OFFICIAL_MIN_FREE_KB" ] || die no_space

    echo "Загрузка AdGuard Home $AGH_OFFICIAL_VERSION ($ao_arch)..."
    AO_TMP=$(mktemp -d "$EXT_R/opt/tmp/vward-agh.XXXXXX" 2>/dev/null) || { mkdir -p "$EXT_R/opt/tmp" && AO_TMP=$(mktemp -d "$EXT_R/opt/tmp/vward-agh.XXXXXX"); } || die write_failed
    ao_url="$AGH_OFFICIAL_BASE/$AGH_OFFICIAL_VERSION/AdGuardHome_linux_$ao_arch.tar.gz"
    if ! "${VWARD_CURL_BIN:-curl}" --fail --silent --show-error --location --connect-timeout 15 --max-time 900 \
            -o "$AO_TMP/agh.tar.gz" "$ao_url" 2>"$AO_TMP/curl.err"; then
        audit "ext-agh-official download failed: $(tail -n 1 "$AO_TMP/curl.err" | cut -c1-160)"
        [ "$1" != repair ] || ao_note err "AdGuard Home не запускается" \
            "VWARD не смог скачать официальную сборку AdGuard Home (нет связи с GitHub). Попробует снова через сутки, или нажмите «Установить» на странице AdGuard Home."
        die download_failed
    fi
    [ "$(sha256sum "$AO_TMP/agh.tar.gz" | cut -d' ' -f1)" = "${ao_pin% *}" ] || { audit "ext-agh-official archive checksum mismatch"; die checksum_mismatch; }
    tar -xzf "$AO_TMP/agh.tar.gz" -C "$AO_TMP" 2>/dev/null || die unpack_failed
    rm -f "$AO_TMP/agh.tar.gz"
    ao_new=$(find "$AO_TMP" -type f -name AdGuardHome | head -n 1)
    [ -n "$ao_new" ] && [ "$(sha256sum "$ao_new" | cut -d' ' -f1)" = "${ao_pin#* }" ] || { audit "ext-agh-official binary checksum mismatch"; die checksum_mismatch; }
    chmod 0755 "$ao_new"
    "$ao_new" --version >/dev/null 2>&1 || { audit "ext-agh-official $AGH_OFFICIAL_VERSION does not run here"; die agh_build_broken; }
    echo "Контрольные суммы совпали, сборка запускается."

    dir="$EXT_BACKUP/$(date '+%Y%m%d-%H%M%S')-agh-official"
    mkdir -p "$dir" || die backup_failed
    [ ! -f "$ao_bin" ] || cp -a "$ao_bin" "$dir/AdGuardHome" || { rm -rf "${dir:?}"; die backup_failed; }
    audit "ext-agh-official ${ao_old:-broken} -> $AGH_OFFICIAL_VERSION backup=$dir"
    ao_init=${VWARD_AGH_INIT:-/opt/etc/init.d/S99adguardhome}
    # A first installation from «Компоненты» (fix.32): only the file; agh-component sets it up
    # and starts it itself.
    if [ "${VWARD_AGH_NOSTART:-0}" = 1 ] && [ -z "$ao_old" ]; then
        mkdir -p "$(dirname "$ao_bin")" && cp "$ao_new" "$ao_bin.vward-new" && mv -f "$ao_bin.vward-new" "$ao_bin" ||
            { rm -f "$ao_bin.vward-new"; die write_failed; }
        printf 'version=%s\narch=%s\nat=%s\nby=%s\n' "$AGH_OFFICIAL_VERSION" "$ao_arch" "$(date +%s)" "$1" > "$EXT_STATE/agh-official"
        ext_record adguardhome none "$AGH_OFFICIAL_VERSION" ok
        done_ok "ext-agh-official none -> $AGH_OFFICIAL_VERSION" changed
    fi
    AGH_PLANNED=1
    "$DNS_GUARD" planned 600 >/dev/null 2>&1 || :
    [ ! -x "$ao_init" ] || "$ao_init" stop </dev/null >/dev/null 2>&1 || :
    # Beside the target first, then renamed: a running file is never rewritten.
    mkdir -p "$(dirname "$ao_bin")" && cp "$ao_new" "$ao_bin.vward-new" && mv -f "$ao_bin.vward-new" "$ao_bin" ||
        { rm -f "$ao_bin.vward-new"; die write_failed; }
    [ ! -x "$ao_init" ] || "$ao_init" start </dev/null >/dev/null 2>&1 || :
    if ao_up; then
        printf 'version=%s\narch=%s\nat=%s\nby=%s\n' "$AGH_OFFICIAL_VERSION" "$ao_arch" "$(date +%s)" "$1" > "$EXT_STATE/agh-official"
        ext_upgradable || :
        ext_record adguardhome "${ao_old:-broken}" "$AGH_OFFICIAL_VERSION" ok
        [ "$1" != repair ] || ao_note ok "AdGuard Home снова работает" \
            "Установлена официальная сборка AdGuard Home $AGH_OFFICIAL_VERSION для процессора этого роутера; настройки и списки прежние. Прежний файл сохранён."
        echo "Установлено: AdGuard Home $AGH_OFFICIAL_VERSION"
        done_ok "ext-agh-official ${ao_old:-broken} -> $AGH_OFFICIAL_VERSION" changed
    fi
    # The new build does not stay up: a working old file goes back, a broken one is pointless.
    echo "AdGuard Home не запустился"
    if [ -n "$ao_old" ] && [ -f "$dir/AdGuardHome" ]; then
        cp -a "$dir/AdGuardHome" "$ao_bin.vward-new" && mv -f "$ao_bin.vward-new" "$ao_bin"
        [ ! -x "$ao_init" ] || "$ao_init" restart </dev/null >/dev/null 2>&1 || :
        ext_record adguardhome "$ao_old" "$AGH_OFFICIAL_VERSION" rolled_back
        die upgrade_rolled_back
    fi
    ext_record adguardhome broken "$AGH_OFFICIAL_VERSION" failed
    [ "$1" != repair ] || ao_note err "AdGuard Home не запускается" \
        "Официальная сборка AdGuard Home $AGH_OFFICIAL_VERSION установлена, но не запускается: вероятно, повреждены настройки AdGuard Home. Журнал: Система → Журналы."
    die agh_start_failed
}

op_ext_check() {
    ext_lock
    echo "Проверка пакетов Entware..."
    orc=0
    "$OPKG" update > "$EXT_STATE/opkg-update.log" 2>&1 || orc=$?
    ext_upgradable || die write_failed
    n=$(wc -l < "$EXT_STATE/upgradable.tsv" | tr -d ' ')
    if [ "$orc" -eq 0 ]; then echo "Пакеты: обновлений $n"; else echo "Пакеты: список скачан не полностью (opkg $orc), обновлений $n"; fi
    echo "Проверка прошивки Keenetic..."
    frc=0
    ext_firmware_refresh || frc=1
    if [ "$frc" -eq 0 ]; then
        "$JQ" -r '"Прошивка: " + .title + (if .update_available then ", есть обновление" else ", обновлений нет" end)' "$EXT_STATE/firmware.json"
    else
        echo "Прошивка: роутер не ответил"
    fi
    printf 'checked_at=%s\nopkg_rc=%s\nfirmware_ok=%s\n' "$(date +%s)" "$orc" "$((1 - frc))" > "$EXT_STATE/check.state"
    [ "$orc" -eq 0 ] || die feed_unavailable
    done_ok "ext-check upgradable=$n" changed
}

# ext_health: one line per check that passes now.
ext_health() {
    "$JQ" -n 1 >/dev/null 2>&1 && echo jq
    # The update engine checks VWARD's signatures with openssl (Ed25519): an Entware openssl
    # that crashes on it (3.5.5 on MIPS, Viva 2026-10-04) is taken back like any other failure.
    eh_t=$(mktemp -d /tmp/vward-ext-ossl.XXXXXX 2>/dev/null) && {
        printf 'vward' > "$eh_t/m"
        "${VWARD_OPENSSL_BIN:-openssl}" genpkey -algorithm ED25519 -out "$eh_t/k" >/dev/null 2>&1 &&
            "${VWARD_OPENSSL_BIN:-openssl}" pkeyutl -sign -inkey "$eh_t/k" -rawin -in "$eh_t/m" -out "$eh_t/s" >/dev/null 2>&1 &&
            "${VWARD_OPENSSL_BIN:-openssl}" pkeyutl -verify -inkey "$eh_t/k" -rawin -in "$eh_t/m" -sigfile "$eh_t/s" >/dev/null 2>&1 && echo openssl
        rm -rf "${eh_t:?}"
    }
    "${VWARD_CURL_BIN:-curl}" --version >/dev/null 2>&1 && echo curl
    [ -n "${VWARD_DNS_SERVER:-}" ] && "${VWARD_NSLOOKUP_BIN:-nslookup}" "${VWARD_HEALTH_HOST:-keenetic.com}" "$VWARD_DNS_SERVER" >/dev/null 2>&1 && echo dns
    [ -n "${VWARD_CONSOLE_PORT:-}" ] && "${VWARD_CURL_BIN:-curl}" --fail --silent --max-time 5 \
        "http://127.0.0.1:$VWARD_CONSOLE_PORT/cgi-bin/api.cgi?action=ping" 2>/dev/null | grep -q '"ok":true' && echo console
    return 0
}

# ext_restart PLAN_FILE: restart the enabled services of the packages in the plan.
ext_restart() {
    while IFS="$(printf '\t')" read -r rp_pkg rp_rest; do
        "$OPKG" files "$rp_pkg" 2>/dev/null
    done < "$1" | awk 'index($0, "/opt/etc/init.d/S") == 1 && substr($0, 17) ~ /^S[0-9][0-9]/' | sort -u |
    while IFS= read -r rp_init; do
        [ -x "$EXT_R$rp_init" ] && grep -q '^ENABLED=yes' "$EXT_R$rp_init" 2>/dev/null || continue
        echo "Перезапуск $(basename "$rp_init")"
        "$EXT_R$rp_init" restart </dev/null >/dev/null 2>&1 || true
    done
}

# ext_restore DIR: put the copied files back.  Copied beside the target first
# and renamed into place, so a running program (busybox itself) is never rewritten.
ext_restore() {
    rs_fail=0
    while IFS= read -r rs_f; do
        [ -e "$1/files/$rs_f" ] || [ -L "$1/files/$rs_f" ] || continue
        rs_tmp="$EXT_R/$rs_f.vward-restore.$$"
        mkdir -p "$(dirname "$EXT_R/$rs_f")" && cp -a "$1/files/$rs_f" "$rs_tmp" && mv -f "$rs_tmp" "$EXT_R/$rs_f" ||
            { rm -f "$rs_tmp"; rs_fail=1; }
    done < "$1/files.list"
    return "$rs_fail"
}

ext_record() {
    printf '%s\t%s\t%s\t%s\t%s\n' "$(date +%s)" "$1" "$2" "$3" "$4" >> "$EXT_STATE/history.tsv"
    tail -n 50 "$EXT_STATE/history.tsv" > "$EXT_STATE/history.tsv.tmp" && mv -f "$EXT_STATE/history.tsv.tmp" "$EXT_STATE/history.tsv"
}

# op_ext_upgrade PACKAGE CONFIRM
op_ext_upgrade() {
    valid_pkg "$1" || die invalid_value 64
    ext_lock
    line=$(awk -F'\t' -v p="$1" '$1 == p {print; exit}' "$EXT_STATE/upgradable.tsv" 2>/dev/null)
    [ -n "$line" ] || die not_upgradable
    from=$(printf '%s\n' "$line" | cut -f2); to=$(printf '%s\n' "$line" | cut -f3)
    ! ext_critical "$1" || [ "$2" = critical ] || die confirmation_required
    free=$(df -k "$EXT_R/opt" 2>/dev/null | awk 'NR == 2 {print $4}')
    case "$free" in ''|*[!0-9]*) free=0 ;; esac
    [ "$free" -ge "$EXT_MIN_FREE_KB" ] || die no_space
    load_profile_base

    dir="$EXT_BACKUP/$(date '+%Y%m%d-%H%M%S')-$1"
    mkdir -p "$dir" || die backup_failed
    # What opkg would change: the package and the dependencies it pulls up.
    "$OPKG" upgrade --noaction "$1" 2>/dev/null |
        awk '$1 == "Upgrading" && $3 == "on" {print $2 "\t" $6 "\t" $8}
             $1 == "Installing" {n = $2; v = $3; gsub(/[()]/, "", v); print n "\tnew\t" v}' |
        sed 's/\.\.\.$//' > "$dir/plan.tsv"
    awk -F'\t' -v p="$1" '$1 == p {f = 1} END {exit !f}' "$dir/plan.tsv" || printf '%s\t%s\t%s\n' "$1" "$from" "$to" >> "$dir/plan.tsv"
    echo "Будет обновлено:"; awk -F'\t' '{print "  " $1 ": " $2 " -> " $3}' "$dir/plan.tsv"
    while IFS="$(printf '\t')" read -r bp_pkg bp_rest; do
        valid_pkg "$bp_pkg" || continue
        "$OPKG" files "$bp_pkg" 2>/dev/null | grep '^/'
        for bp_info in "$EXT_R$OPKG_INFO/$bp_pkg".*; do [ -e "$bp_info" ] && echo "${bp_info#"$EXT_R"}"; done
    done < "$dir/plan.tsv" > "$dir/files.all"
    echo "$OPKG_STATUS" >> "$dir/files.all"
    while IFS= read -r bp_f; do [ -f "$EXT_R$bp_f" ] || [ -L "$EXT_R$bp_f" ] && printf '%s\n' "${bp_f#/}"; done < "$dir/files.all" | sort -u > "$dir/files.list"
    # A plain copy: BusyBox tar may be built without -T.
    while IFS= read -r bp_f; do
        mkdir -p "$dir/files/$(dirname "$bp_f")" && cp -a "$EXT_R/$bp_f" "$dir/files/$bp_f" || { rm -rf "${dir:?}"; die backup_failed; }
    done < "$dir/files.list"
    echo "Копия файлов: $(wc -l < "$dir/files.list" | tr -d ' ') шт."
    ext_health > "$dir/health.before"
    audit "ext-upgrade $1 $from -> $to backup=$dir"

    # AdGuard Home is about to be replaced: out of the DNS chain first, back at once after
    # (cleanup does it at any exit), nobody waits on a DNS being restarted.
    if grep -q '^adguardhome' "$dir/plan.tsv"; then
        AGH_PLANNED=1
        "$DNS_GUARD" planned 600 >/dev/null 2>&1 || :
    fi
    # AdGuard Home's settings (its rules, lists, clients and login) never go with an update:
    # a copy before, put back when the package replaced or dropped them (fix.32).
    eu_yaml=${VWARD_ADGUARD_CONFIG:-/opt/etc/AdGuardHome/AdGuardHome.yaml}
    eu_keep=
    if grep -q '^adguardhome' "$dir/plan.tsv" && [ -s "$EXT_R$eu_yaml" ]; then
        cp -a "$EXT_R$eu_yaml" "$dir/AdGuardHome.yaml.keep" && chmod 0600 "$dir/AdGuardHome.yaml.keep" && eu_keep=1
    fi
    urc=0
    "$OPKG" upgrade "$1" > "$dir/opkg.log" 2>&1 || urc=$?
    tail -n 5 "$dir/opkg.log"
    if [ -n "$eu_keep" ] && ! cmp -s "$dir/AdGuardHome.yaml.keep" "$EXT_R$eu_yaml"; then
        cp -a "$dir/AdGuardHome.yaml.keep" "$EXT_R$eu_yaml" && echo "Настройки AdGuard Home сохранены"
        audit "ext-upgrade $1 AdGuard Home settings put back after the package"
    fi
    ext_restart "$dir/plan.tsv"
    # Services need a moment after a restart.
    hw=0; while :; do
        ext_health > "$dir/health.after"
        missing=$(grep -vxF -f "$dir/health.after" "$dir/health.before" | tr '\n' ' ')
        [ -n "$missing" ] && [ "$hw" -lt "${VWARD_EXT_HEALTH_WAIT:-30}" ] || break
        sleep 5; hw=$((hw + 5))
    done
    if [ "$urc" -eq 0 ] && [ -z "$missing" ]; then
        ext_upgradable || true
        ext_record "$1" "$from" "$to" ok
        echo "Установлено: $1 $to"
        done_ok "ext-upgrade $1 $from -> $to" changed
    fi

    echo "Проверка не прошла (${missing:-opkg $urc}), возвращаю прежнюю версию"
    ext_restore "$dir" || { ext_record "$1" "$from" "$to" rollback_failed; die rollback_failed; }
    ext_restart "$dir/plan.tsv"
    ext_upgradable || true
    ext_record "$1" "$from" "$to" rolled_back
    die upgrade_rolled_back
}

# op_ext_auto agh|entware 0|1: install found updates automatically.
op_ext_auto() {
    case "$1" in agh) k=AGH_AUTO ;; entware) k=ENTWARE_AUTO ;; *) die invalid_value 64 ;; esac
    case "$2" in 0|1) ;; *) die invalid_value 64 ;; esac
    set_kv "$EXT_CONF" "$k" "$2" 0600 || done_ok "ext-auto $1=$2" unchanged
    done_ok "ext-auto $1=$2" changed
}

# op_firmware auto 0|1 | channel stable|preview|draft: Keenetic's own settings.
op_firmware() {
    ext_firmware_refresh || die router_unavailable
    case "$1" in
        auto)
            case "$2" in 0) cmd=disable; want=false ;; 1) cmd=enable; want=true ;; *) die invalid_value 64 ;; esac
            [ "$("$JQ" -r .auto_update "$EXT_STATE/firmware.json")" != "$want" ] || done_ok "firmware auto=$2" unchanged
            ndm "components auto-update $cmd" || die router_rejected ;;
        channel)
            case "$2" in stable|preview|draft) ;; *) die invalid_value 64 ;; esac
            [ "$("$JQ" -r .channel "$EXT_STATE/firmware.json")" != "$2" ] || done_ok "firmware channel=$2" unchanged
            ndm "components auto-update channel $2" || die router_rejected ;;
        *) die invalid_value 64 ;;
    esac
    save_router || die router_save_failed
    ext_firmware_refresh || true
    done_ok "firmware $1=$2" changed
}

# op_ext_daily: the daily check, then the updates the user left to VWARD.
op_ext_daily() {
    ext_lock
    ( trap - EXIT; op_ext_check ) || true
    cp -f "$EXT_STATE/upgradable.tsv" "$EXT_STATE/upgradable.tsv.daily" 2>/dev/null || : > "$EXT_STATE/upgradable.tsv.daily"
    kv_agh=0; kv_ent=0
    [ -r "$EXT_CONF" ] && {
        kv_agh=$(sed -n 's/^AGH_AUTO=//p' "$EXT_CONF" | tail -n 1)
        kv_ent=$(sed -n 's/^ENTWARE_AUTO=//p' "$EXT_CONF" | tail -n 1)
    }
    n=0
    while IFS="$(printf '\t')" read -r dp_pkg dp_from dp_to; do
        ext_critical "$dp_pkg" && continue
        case "$dp_pkg" in adguardhome-go) [ "$kv_agh" = 1 ] || continue ;; *) [ "$kv_ent" = 1 ] || continue ;; esac
        # Observation mode of the updates agent (fix.28.6): proposed, not installed.
        vward_agent_acts updates "ext-upgrade:$dp_pkg" "Установить обновление $dp_pkg $dp_from → $dp_to" || continue
        echo "Автоматически: $dp_pkg"
        ( trap - EXIT; op_ext_upgrade "$dp_pkg" auto ) || true
        n=$((n + 1))
    done 2>/dev/null < "$EXT_STATE/upgradable.tsv.daily"
    # The official AdGuard Home build: a newer pin from a VWARD release, when updates are automatic.
    if [ "$kv_agh" = 1 ] && [ -s "$EXT_STATE/agh-official" ] &&
       [ "$(sed -n 's/^version=//p' "$EXT_STATE/agh-official")" != "$AGH_OFFICIAL_VERSION" ] &&
       vward_agent_acts updates agh-official "Обновить AdGuard Home до $AGH_OFFICIAL_VERSION (официальная сборка)"; then
        echo "Автоматически: AdGuard Home $AGH_OFFICIAL_VERSION"
        ( trap - EXIT; op_ext_agh_official install ) || true
        n=$((n + 1))
    fi
    done_ok "ext-daily automatic=$n" changed
}

# ---------- Компоненты (fix.32) ----------
# One operation on a component at a time (COMP_LOCK). Its mark on the flash (COMP_PENDING) says
# what was being done; a power loss in the middle leaves it, and «component-recover» (the
# components agent after a reboot) finishes the same operation - each step can be repeated.
# A failed step undoes what this operation made and the reason goes to the journal.
COMP_ETC="$ETC/component-ops"
COMP_PENDING="$COMP_ETC/pending"
COMP_LOCK=${VWARD_COMPONENT_OP_LOCK:-/tmp/vward-component-op.lock}
COMP_LOCKED=0
COMP_UNDO=
AGH_DIR=${VWARD_AGH_DIR:-/opt/etc/AdGuardHome}
AGH_YAML=${VWARD_ADGUARD_CONFIG:-$AGH_DIR/AdGuardHome.yaml}
AGH_INIT_FILE=${VWARD_AGH_INIT:-/opt/etc/init.d/S99adguardhome}
AGH_OFF_FLAG=${VWARD_AGH_DISABLED:-$COMPONENT_STATE/adguardhome.disabled}
AGH_AUTH_FILE=${VWARD_ADS_AGH_AUTH_FILE:-/opt/etc/vward/ads-privacy-guard/agh-api.auth}
AGH_BACKUPS=${VWARD_AGH_BACKUPS:-/opt/var/backups/vward/adguardhome}
AGH_WEB_PORT=${VWARD_AGH_WEB_PORT:-3000}
AGH_DNS_PORT=${VWARD_AGH_DNS_PORT:-65053}

comp_begin() {
    mkdir -p "$COMP_ETC" || die write_failed
    dir_lock "$COMP_LOCK" || die component_busy 75
    echo $$ > "$COMP_LOCK/pid" 2>/dev/null
    COMP_LOCKED=1
    printf 'op=%s\nat=%s\n' "$1" "$(date +%s)" > "$COMP_PENDING.tmp" && mv -f "$COMP_PENDING.tmp" "$COMP_PENDING" || die write_failed
    audit "component-op $1 started"
}
# comp_end: done, the mark goes.
comp_end() { rm -f "$COMP_PENDING"; COMP_UNDO=; }
# comp_undo: run at exit of a failed operation - the steps registered by comp_will, newest first.
comp_undo() {
    [ -n "$COMP_UNDO" ] || return 0
    printf '%s\n' "$COMP_UNDO" | awk 'NF {a[++n] = $0} END {for (i = n; i > 0; i--) print a[i]}' |
        while IFS= read -r cu_cmd; do eval "$cu_cmd" >/dev/null 2>&1 || :; done
    audit "component-op rolled back"
    COMP_UNDO=
    rm -f "$COMP_PENDING"
}
comp_will() { COMP_UNDO="$COMP_UNDO
$1"; }

# port_free PORT: nobody listens on it (TCP or UDP, v4 or v6).
port_free() {
    pf_hex=$(printf '%04X' "$1")
    ! awk -v h=":$pf_hex" 'FNR > 1 && $2 ~ h "$" {f = 1} END {exit !f}' \
        "${VWARD_PROC_NET:-/proc/net}/tcp" "${VWARD_PROC_NET:-/proc/net}/tcp6" \
        "${VWARD_PROC_NET:-/proc/net}/udp" "${VWARD_PROC_NET:-/proc/net}/udp6" 2>/dev/null
}
# port_pick FROM: the first free port from FROM on (20 tries).
port_pick() {
    pp=$1
    while [ "$pp" -lt $(($1 + 20)) ]; do port_free "$pp" && { echo "$pp"; return 0; }; pp=$((pp + 1)); done
    return 1
}

agh_bin_now() { command -v vward_agh_binary >/dev/null 2>&1 && vward_agh_binary 2>/dev/null || { [ -x "$EXT_R/opt/sbin/AdGuardHome" ] && echo "$EXT_R/opt/sbin/AdGuardHome"; }; }
agh_running() { "${VWARD_PIDOF_BIN:-pidof}" AdGuardHome >/dev/null 2>&1; }
agh_wait() {
    aw=0
    while :; do
        "$@" && return 0
        [ "$aw" -lt "${VWARD_AGH_START_WAIT:-60}" ] || return 1
        sleep 2; aw=$((aw + 2))
    done
}
agh_stopped() { ! agh_running; }

# agh_init_write: Entware's own form of a start script, when the program came without one.
agh_init_write() {
    [ -f "$AGH_INIT_FILE" ] && return 0
    mkdir -p "$(dirname "$AGH_INIT_FILE")" || return 1
    cat > "$AGH_INIT_FILE.tmp" <<AGHINIT || return 1
#!/bin/sh
# Written by VWARD (Компоненты → AdGuard Home).
ENABLED=yes
PROCS=AdGuardHome
ARGS="--no-check-update -c $AGH_YAML -w $AGH_DIR"
PREARGS=""
DESC=\$PROCS
PATH=/opt/sbin:/opt/bin:/opt/usr/sbin:/opt/usr/bin:/usr/sbin:/usr/bin:/sbin:/bin
. /opt/etc/init.d/rc.func
AGHINIT
    chmod 0755 "$AGH_INIT_FILE.tmp" && mv -f "$AGH_INIT_FILE.tmp" "$AGH_INIT_FILE"
}

# agh_creds: the login VWARD keeps for AdGuard Home, else one the Panel passed in a file
# (VWARD_AGH_CRED_FILE, 0600, removed by the caller). VWARD never makes up an account.
agh_creds() {
    for ac in "${VWARD_AGH_CRED_FILE:-}" "$AGH_AUTH_FILE"; do
        [ -n "$ac" ] && [ -s "$ac" ] && [ ! -L "$ac" ] || continue
        ac_line=$(head -n 1 "$ac")
        case "$ac_line" in ?*:?*) printf '%s\n' "$ac_line"; return 0 ;; esac
    done
    return 1
}

# agh_wizard WEB DNS: the first-run setup of a fresh AdGuard Home with the owner's login,
# through its own setup API; the password goes by stdin, never argv.
agh_wizard() {
    aw_bin=$(agh_bin_now) || die agh_not_installed
    mkdir -p "$AGH_DIR" || die write_failed
    "$aw_bin" --no-check-update -c "$AGH_YAML" -w "$AGH_DIR" -p "$1" </dev/null >/dev/null 2>&1 &
    aw_pid=$!
    comp_will "kill $aw_pid"
    aw_base="http://127.0.0.1:$1/control/install"
    agh_wait "${VWARD_CURL_BIN:-curl}" --fail --silent --max-time 3 -o /dev/null "$aw_base/get_addresses" || { kill "$aw_pid" 2>/dev/null; die agh_start_failed; }
    aw_code=$(agh_creds | "$JQ" -Rc --argjson w "$1" --argjson d "$2" '
        (index(":")) as $i | {web: {ip: "0.0.0.0", port: $w}, dns: {ip: "0.0.0.0", port: $d},
         username: .[:$i], password: .[$i + 1:]}' |
        "${VWARD_CURL_BIN:-curl}" --silent --max-time 30 -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' --data-binary @- "$aw_base/configure" 2>/dev/null)
    [ "$aw_code" = 200 ] || { kill "$aw_pid" 2>/dev/null; audit "agh-component wizard http=$aw_code"; die agh_setup_failed; }
    agh_wait test -s "$AGH_YAML" || { kill "$aw_pid" 2>/dev/null; die agh_setup_failed; }
    kill "$aw_pid" 2>/dev/null; agh_wait agh_stopped || kill -9 "$aw_pid" 2>/dev/null
    wait "$aw_pid" 2>/dev/null || :
}

# agh_backup: a copy of AdGuard Home's settings (its rules, lists and clients live there).
agh_backup() {
    [ -s "$AGH_YAML" ] || return 0
    ab_dir="$AGH_BACKUPS/$(date '+%Y%m%d-%H%M%S')"
    mkdir -p "$ab_dir" && cp -a "$AGH_YAML" "$ab_dir/AdGuardHome.yaml" || die backup_failed
    chmod 0600 "$ab_dir/AdGuardHome.yaml"
    ls -1d "$AGH_BACKUPS"/*/ 2>/dev/null | sort | head -n -5 | while IFS= read -r ab_old; do rm -rf "${ab_old:?}"; done
    echo "Копия настроек AdGuard Home: $ab_dir"
    audit "agh-component backup $ab_dir"
}

# Smart DNS domains held by AdGuard Home go to Keenetic's own Smart DNS while it is off
# (8 lines at most there): the list is kept to take them back.
AGH_SDNS_MOVED="$COMP_ETC/agh-smartdns.moved"
agh_smartdns_out() {
    command -v vward_agh_smartdns_domains >/dev/null 2>&1 || return 0
    vward_agh_smartdns_domains | awk '!s[$0]++' > "$COMP_ETC/agh-smartdns.all" || return 0
    : > "$AGH_SDNS_MOVED.tmp"
    so_n=0 so_left=0
    while IFS= read -r so_d; do
        [ -n "$so_d" ] || continue
        if [ "$(sh "$0" smartdns-keenetic add "$so_d" 2>/dev/null | tail -n 1)" = result=changed ]; then
            echo "$so_d" >> "$AGH_SDNS_MOVED.tmp"; so_n=$((so_n + 1))
        else
            so_left=$((so_left + 1))
        fi
    done < "$COMP_ETC/agh-smartdns.all"
    mv -f "$AGH_SDNS_MOVED.tmp" "$AGH_SDNS_MOVED"
    rm -f "$COMP_ETC/agh-smartdns.all"
    echo "smartdns_moved=$so_n smartdns_left=$so_left"
}
agh_smartdns_back() {
    [ -s "$AGH_SDNS_MOVED" ] || return 0
    while IFS= read -r sb_d; do
        [ -z "$sb_d" ] || sh "$0" smartdns-keenetic remove "$sb_d" >/dev/null 2>&1 || :
    done < "$AGH_SDNS_MOVED"
    rm -f "$AGH_SDNS_MOVED"
}

agh_off_steps() {
    # DNS first: Keenetic must not point at a program that stops.
    [ ! -x "$DNS_GUARD" ] || "$DNS_GUARD" release >/dev/null 2>&1 || die dns_release_failed
    comp_will "[ ! -x '$DNS_GUARD' ] || '$DNS_GUARD' apply"
    : > "$AGH_OFF_FLAG"
    comp_will "rm -f '$AGH_OFF_FLAG'; [ ! -f '$AGH_INIT_FILE' ] || { chmod 0755 '$AGH_INIT_FILE'; '$AGH_INIT_FILE' start; }"
    [ ! -x "$AGH_INIT_FILE" ] || "$AGH_INIT_FILE" stop </dev/null >/dev/null 2>&1 || :
    agh_wait agh_stopped || { "${VWARD_KILLALL_BIN:-killall}" AdGuardHome 2>/dev/null; agh_wait agh_stopped || die agh_stop_failed; }
    # Not started at boot either: Entware skips a start script that is not executable.
    [ ! -f "$AGH_INIT_FILE" ] || chmod 0644 "$AGH_INIT_FILE"
    agh_smartdns_out
}
agh_on_steps() {
    [ -f "$AGH_INIT_FILE" ] || agh_init_write || die write_failed
    chmod 0755 "$AGH_INIT_FILE"
    rm -f "$AGH_OFF_FLAG"
    agh_running || "$AGH_INIT_FILE" start </dev/null >/dev/null 2>&1 || :
    agh_wait agh_running || die agh_start_failed
    agh_smartdns_back
    # Back into Keenetic's DNS chain on the guard's next look once it answers.
    [ ! -x "$DNS_GUARD" ] || "$DNS_GUARD" apply >/dev/null 2>&1 || :
}

# agh-component install|enable|disable|remove|reset|reinstall [backup]
op_agh_component() {
    case "$1" in install|enable|disable|remove|reset|reinstall) ;; *) die invalid_operation 64 ;; esac
    case "${2:-}" in ''|backup|nobackup) ;; *) die invalid_value 64 ;; esac
    load_profile_base
    comp_begin "agh-$1${2:+ $2}"
    case "$1" in
        disable)
            agh_bin_now >/dev/null || die agh_not_installed
            agh_off_steps
            comp_end
            vward_note info "AdGuard Home выключен" "DNS роутера идёт без AdGuard Home, реклама не блокируется. Домены Smart DNS перенесены в Keenetic, сколько поместилось (до 8)." d-agh 2>/dev/null || :
            done_ok "agh-component disable" changed ;;
        enable)
            agh_bin_now >/dev/null || die agh_not_installed
            agh_on_steps
            comp_end
            done_ok "agh-component enable" changed ;;
        install|reinstall|reset)
            # Checks before anything is changed: the build for this processor, the space, the ports.
            ai_arch=$(agh_official_arch) && [ -n "$(agh_official_pin "$ai_arch")" ] ||
                { RELAY_REASON="uname=$(uname -m 2>/dev/null) arch=${ai_arch:-none}"; die agh_no_build; }
            ai_had=$(agh_bin_now) || ai_had=
            [ "$1" = install ] || [ -n "$ai_had" ] || die agh_not_installed
            [ "$1" != install ] || [ -z "$ai_had" ] || [ ! -s "$AGH_YAML" ] || { comp_end; done_ok "agh-component install: installed already" unchanged; }
            free=$(df -k "$EXT_R/opt" 2>/dev/null | awk 'NR == 2 {print $4}'); case "$free" in ''|*[!0-9]*) free=0 ;; esac
            [ -n "$ai_had" ] || [ "$free" -ge "$AGH_OFFICIAL_MIN_FREE_KB" ] || die no_space
            # A new setup of AdGuard Home needs the owner's login: kept by VWARD or given now.
            ai_need=1; [ ! -s "$AGH_YAML" ] || [ "$1" = reset ] || ai_need=0
            [ "$ai_need" = 0 ] || agh_creds >/dev/null || die agh_credentials_required
            [ "${2:-}" != backup ] || agh_backup
            if [ "$1" = reinstall ] || [ "$1" = reset ]; then
                [ ! -x "$DNS_GUARD" ] || "$DNS_GUARD" release >/dev/null 2>&1 || :
                [ ! -x "$AGH_INIT_FILE" ] || "$AGH_INIT_FILE" stop </dev/null >/dev/null 2>&1 || :
                agh_wait agh_stopped || "${VWARD_KILLALL_BIN:-killall}" AdGuardHome 2>/dev/null || :
            fi
            if [ "$1" = reset ] && [ -s "$AGH_YAML" ]; then
                # Settings out of the way (kept beside, put back if the new setup fails).
                mv -f "$AGH_YAML" "$AGH_YAML.vward-reset" || die write_failed
                comp_will "mv -f '$AGH_YAML.vward-reset' '$AGH_YAML'"
            fi
            if [ -z "$ai_had" ] || [ "$1" = reinstall ]; then
                [ -n "$ai_had" ] || comp_will "rm -f '$EXT_R/opt/sbin/AdGuardHome'"
                ai_out=$(VWARD_AGH_NOSTART=$([ -z "$ai_had" ] && echo 1 || echo 0) sh "$0" ext-agh-official install 2>/dev/null | tail -n 1)
                case "$ai_out" in result=*) ;; *) RELAY_REASON=${ai_out#error=}; die "${ai_out#error=}" ;; esac
            fi
            if [ ! -f "$AGH_INIT_FILE" ]; then comp_will "rm -f '$AGH_INIT_FILE'"; agh_init_write || die write_failed; fi
            if [ ! -s "$AGH_YAML" ]; then
                ai_web=$(port_pick "$AGH_WEB_PORT") || die no_free_port
                ai_dns=$(port_pick "$AGH_DNS_PORT") || die no_free_port
                comp_will "rm -f '$AGH_YAML'"
                agh_wizard "$ai_web" "$ai_dns"
                # The login the owner gave is the one VWARD keeps (as «Подключить VWARD»).
                if [ -n "${VWARD_AGH_CRED_FILE:-}" ] && [ -s "$VWARD_AGH_CRED_FILE" ]; then
                    mkdir -p "$(dirname "$AGH_AUTH_FILE")" && (umask 077; head -n 1 "$VWARD_AGH_CRED_FILE" > "$AGH_AUTH_FILE.tmp") &&
                        chmod 0600 "$AGH_AUTH_FILE.tmp" && mv -f "$AGH_AUTH_FILE.tmp" "$AGH_AUTH_FILE" || die write_failed
                fi
                echo "Веб-интерфейс AdGuard Home: порт $ai_web, DNS: порт $ai_dns"
            fi
            agh_on_steps
            rm -f "$AGH_YAML.vward-reset"
            # Ad blocking back on when VWARD switched it off with the program.
            if grep -q "(with adguardhome)\$" "$COMPONENT_STATE/ads-privacy-guard.disabled" 2>/dev/null; then sh "$0" component ads-privacy-guard 1 >/dev/null 2>&1 || :; fi
            comp_end
            vward_note ok "AdGuard Home работает" "Программа установлена и подключена к VWARD: Keenetic начнёт отправлять в неё DNS-запросы в течение нескольких минут." d-agh 2>/dev/null || :
            done_ok "agh-component $1" changed ;;
        remove)
            agh_bin_now >/dev/null || [ -f "$AGH_INIT_FILE" ] || die agh_not_installed
            [ "${2:-}" != backup ] || agh_backup
            agh_off_steps
            for ar_b in $(agh_bin_now) "$EXT_R/opt/sbin/AdGuardHome" "$EXT_R/opt/bin/AdGuardHome"; do rm -f "$ar_b"; done
            rm -f "$AGH_INIT_FILE" "$AGH_OFF_FLAG" "$EXT_STATE/agh-official"
            [ ! -d "$AGH_DIR" ] || rm -rf "${AGH_DIR:?}"
            # Ad blocking has nothing to work with: off, with a note it went with the program.
            if [ ! -e "$COMPONENT_STATE/ads-privacy-guard.disabled" ]; then
                sh "$0" component ads-privacy-guard 0 >/dev/null 2>&1 &&
                    printf 'disabled from VWARD Panel %s (with adguardhome)\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" > "$COMPONENT_STATE/ads-privacy-guard.disabled" 2>/dev/null || :
            fi
            comp_end
            vward_note warn "AdGuard Home удалён" "Реклама выключена: ей нужен AdGuard Home. Домены Smart DNS перенесены в Keenetic, сколько поместилось (до 8). Установить снова: Компоненты → AdGuard Home." d-agh 2>/dev/null || :
            done_ok "agh-component remove" changed ;;
    esac
}

# smartdns-keenetic add|remove DOMAIN: only Keenetic's own Smart DNS line (AdGuard Home off).
op_smartdns_keenetic() {
    case "$1" in add|remove) ;; *) die invalid_operation 64 ;; esac
    valid_domain "$2" || die invalid_domain 64
    keenetic_smartdns "$1" "$2"
    done_ok "smartdns-keenetic $1 $2" changed
}

# ---- Modules: AmneziaWG, VLESS ----
# module-component awg|vless disable [TUNNEL|direct] | enable: the module's tunnels off (the
# agent leaves them off), their lists and subnets to the default tunnel and back on enable.
# The default tunnel itself in the module: TUNNEL takes over as the default (with all its
# routes), «direct» leaves them where they are - they go via the provider while it is off.
MOD_FLAG() { echo "$COMPONENT_STATE/module-$1.disabled"; }
mod_tunnels() {
    case "$1" in awg) mt_f=$AWG_TUNNELS ;; vless) mt_f=$VLESS_TUNNELS ;; *) return 1 ;; esac
    [ -f "$mt_f" ] && awk -F '\t' '$2 ~ /^[A-Za-z0-9_.-]+$/ {print $2}' "$mt_f"
}
op_module_component() {
    case "$1" in awg|vless) ;; *) die invalid_component 64 ;; esac
    case "$2" in enable|disable) ;; *) die invalid_operation 64 ;; esac
    load_profile_base
    mc_flag=$(MOD_FLAG "$1") mc_saved="$COMP_ETC/module-$1.routes"
    comp_begin "module-$1-$2${3:+ $3}"
    if [ "$2" = disable ]; then
        mc_list=$(mod_tunnels "$1")
        case " $(echo $mc_list) " in
            *" $VWARD_TUNNEL_INTERFACE "*)
                case "${3:-}" in
                    direct) ;;
                    ''|*[!A-Za-z0-9_.-]*) die default_tunnel_in_module 64 ;;
                    *) case " $(echo $mc_list) " in *" $3 "*) die invalid_tunnel 64 ;; esac
                       mc_out=$(sh "$0" tunnel "$3" all 2>/dev/null | tail -n 1)
                       case "$mc_out" in result=*) ;; *) die "${mc_out#error=}" ;; esac
                       load_profile_base ;;
                esac ;;
        esac
        # Where each list and subnet of the module's tunnels was: kept to bring it back.
        snapshot
        : > "$mc_saved.tmp"
        for mc_t in $mc_list; do
            awk -v i="$mc_t" '/^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1)} /^!/ {ctx = 0}
                ctx && $1 == "route" && $2 == "object-group" && $4 == i {print "list\t" $3 "\t" i}' "$RUNCFG" >> "$mc_saved.tmp"
            awk -v i="$mc_t" "$ROUTE_AWK"' $1 == "ip" && $2 == "route" && rdev() == i {print "net\t" $3 " " rmask() "\t" i}' "$RUNCFG" >> "$mc_saved.tmp"
        done
        [ -s "$mc_saved" ] && [ ! -s "$mc_saved.tmp" ] && rm -f "$mc_saved.tmp" || mv -f "$mc_saved.tmp" "$mc_saved"
        mc_moved=0
        for mc_t in $mc_list; do
            [ "$mc_t" != "$VWARD_TUNNEL_INTERFACE" ] || continue
            mc_out=$(sh "$0" tunnel-delete "$mc_t" vpn move 2>/dev/null | tail -n 1)
            case "$mc_out" in result=changed) mc_moved=$((mc_moved + 1)) ;; result=*) ;; *) die "${mc_out#error=}" ;; esac
            mc_out=$(sh "$0" tunnel-state down "$mc_t" 2>/dev/null | tail -n 1)
            case "$mc_out" in result=*) ;; *) die "${mc_out#error=}" ;; esac
        done
        : > "$mc_flag"
        comp_end
        done_ok "module-component $1 disable tunnels=$(echo $mc_list | wc -w) moved=$mc_moved" changed
    fi
    rm -f "$mc_flag"
    for mc_t in $(mod_tunnels "$1"); do
        [ "$mc_t" != "$VWARD_TUNNEL_INTERFACE" ] || continue
        mc_out=$(sh "$0" tunnel-state up "$mc_t" 2>/dev/null | tail -n 1)
        case "$mc_out" in result=*) ;; *) die "${mc_out#error=}" ;; esac
    done
    # The lists and subnets go back where they were, while they are still on the default tunnel.
    if [ -s "$mc_saved" ]; then
        snapshot
        mc_tab=$(printf '\t')
        while IFS="$mc_tab" read -r mc_k mc_v mc_t; do
            case "$mc_k" in
                list) [ "$(group_route "$mc_v" | cut -f1)" = "$VWARD_TUNNEL_INTERFACE" ] || continue
                      sh "$0" domain-list "$mc_v" "$mc_t" >/dev/null 2>&1 || : ;;
                net) mc_net=${mc_v% *} mc_mask=${mc_v#* }
                     subnet_present "$mc_net" "$mc_mask" "$VWARD_TUNNEL_INTERFACE" || continue
                     mc_len=$(echo "$mc_mask" | awk -F. '{b = 0; for (i = 1; i <= 4; i++) {x = $i; while (x >= 128) {b++; x = (x - 128) * 2}} print b}')
                     sh "$0" tunnel-subnet "$VWARD_TUNNEL_INTERFACE" remove "$mc_net/$mc_len" >/dev/null 2>&1 &&
                         sh "$0" tunnel-subnet "$mc_t" add "$mc_net/$mc_len" >/dev/null 2>&1 || : ;;
            esac
        done < "$mc_saved"
        rm -f "$mc_saved"
    fi
    comp_end
    done_ok "module-component $1 enable" changed
}

# component-recover now: after a reboot, an operation the power cut in the middle is done again.
op_component_recover() {
    [ -s "$COMP_PENDING" ] || done_ok "component-recover nothing" unchanged
    cr_op=$(sed -n 's/^op=//p' "$COMP_PENDING")
    rm -f "$COMP_PENDING"
    audit "component-recover $cr_op"
    # The operation runs as a helper of its own: this one lets go of its admission first.
    command -v vward_admission_leave >/dev/null 2>&1 && vward_admission_leave 2>/dev/null
    case "$cr_op" in
        agh-disable|agh-enable|agh-remove) exec sh "$0" agh-component "${cr_op#agh-}" nobackup ;;
        agh-install*|agh-reinstall*|agh-reset*) cr_a=${cr_op#agh-}; exec sh "$0" agh-component "${cr_a%% *}" nobackup ;;
        module-awg-*|module-vless-*) cr_m=${cr_op#module-}; cr_w=${cr_m#*-}; exec sh "$0" module-component "${cr_m%%-*}" ${cr_w} ;;
    esac
    done_ok "component-recover unknown" unchanged
}

# ---------- Entry ----------

# An uploaded .conf goes away with the helper whatever happens next, a refused
# or failed call included: it holds the tunnel's private key.
if [ "${1:-}" = tunnel-conf ]; then
    case "${3:-}" in /*) [ ! -f "$3" ] || [ -L "$3" ] || CONF_FILE=$3 ;; esac
fi
[ "$#" -ge 2 ] && [ "$#" -le 5 ] || die usage 64
OP=$1; shift
case "$OP" in
    tunnel-guard|tunnel-fallback|tunnel-return|wan-guard|update-feed|adaptive-mode|classifier|console-auth|console-devices|smartdns-guard|backup-create|backup-restore|ext-check|ext-daily|ext-agh-official|policy-group|services-refresh|cleanup|reset|smartdns-server|smartdns-store) [ "$#" -eq 1 ] || die usage 64 ;;
    tunnel) [ "$#" -ge 1 ] && [ "$#" -le 2 ] || die usage 64 ;;
    tunnel-conf) [ "$#" -ge 2 ] && [ "$#" -le 4 ] || die usage 64 ;;
    tunnel-subnet|list-domain) [ "$#" -eq 3 ] || die usage 64 ;;
    tunnel-delete) [ "$#" -eq 2 ] || [ "$#" -eq 3 ] || die usage 64 ;;
    vless-server) [ "$#" -ge 2 ] && [ "$#" -le 4 ] || die usage 64 ;;
    service|ai) [ "$#" -eq 2 ] || [ "$#" -eq 3 ] || die usage 64 ;;
    wifi-host) [ "$#" -eq 3 ] || die usage 64 ;;
    list) [ "$#" -eq 2 ] || [ "$#" -eq 3 ] || die usage 64 ;;
    agh-component|module-component) [ "$#" -ge 1 ] && [ "$#" -le 3 ] || die usage 64 ;;
    smartdns-keenetic) [ "$#" -eq 2 ] || die usage 64 ;;
    component-recover) [ "$#" -eq 1 ] || die usage 64 ;;
    *) [ "$#" -eq 2 ] || die usage 64 ;;
esac
ARG1=$(printf '%s' "$1" | tr 'A-Z' 'a-z')
ARG2=${2:-}
case "$OP" in wifi|update|wan-param|tunnel|policy-group|domain-list|domain-list-watch|tunnel-conf|tunnel-delete|tunnel-subnet|backup-restore|wifi-host) ARG1=$1 ;; esac
case "$OP" in ext-upgrade|ext-auto|firmware) ARG2=$(printf '%s' "$ARG2" | tr 'A-Z' 'a-z') ;; esac
ARG3=${3:-}
ARG4=${4:-}
case "$OP" in route-domain|force-vpn|adaptive|smartdns-domain) ARG2=$(printf '%s' "$ARG2" | tr 'A-Z' 'a-z') ;; esac
case "$OP" in list-domain) ARG3=$(printf '%s' "$ARG3" | tr 'A-Z' 'a-z') ;; esac

# VWARD switched off as a whole («Отключить VWARD»): nothing changes until it is on again
# (a copy of the settings and a look for updates of other software are no change).
case "$OP" in backup-create|ext-check|journal|cleanup) ;; *) [ ! -e "$COMPONENT_STATE/vward.off" ] || die vward_off 75 ;; esac

ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
[ -r "$ADMISSION_LIB" ] || die admission_unavailable
. "$ADMISSION_LIB"
command -v vward_agent_acts >/dev/null 2>&1 || vward_agent_acts() { return 0; }
vward_admission_enter console-config || die updater_busy 75

case "$OP" in
    force-vpn|domain-category|tunnel-guard|tunnel-fallback|tunnel-return|tunnel-auto|wan-guard|component|\
    adaptive-mode|classifier|ip-category|console-auth|console-devices|update-feed|domain-list-watch|\
    smartdns-guard|smartdns-domain|wifi|update|wan-param|wifi-host|service|service-category|services-refresh|ext-auto|firmware|journal|agents-mode|cleanup|reset)
        edit_lock ;;
esac

case "$OP" in
    route-domain) op_route_domain "$ARG1" "$ARG2" ;;
    force-vpn) op_force_vpn "$ARG1" "$ARG2" ;;
    adaptive) op_adaptive "$ARG1" "$ARG2" ;;
    domain-category) op_domain_category "$ARG1" "$ARG2" ;;
    tunnel-guard) op_guard_flag tunnel-guard "$TUNNEL_GUARD_FLAG" "$ARG1" ;;
    tunnel-fallback) op_guard_flag tunnel-fallback "$TUNNEL_FALLBACK_FLAG" "$ARG1" ;;
    tunnel-return) op_guard_flag tunnel-return "$TUNNEL_RETURN_FLAG" "$ARG1" ;;
    tunnel-auto) op_tunnel_auto "$ARG1" "$ARG2" ;;
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
    tunnel) op_tunnel "$ARG1" "$ARG2" ;;
    policy-group) op_policy_group "$ARG1" ;;
    domain-list) op_domain_list "$ARG1" "$ARG2" ;;
    domain-list-watch) op_domain_list_watch "$ARG1" "$ARG2" ;;
    smartdns-guard) op_smartdns_guard "$ARG1" ;;
    smartdns-domain) op_smartdns_domain "$ARG1" "$ARG2" ;;
    wifi) op_wifi "$ARG1" "$ARG2" ;;
    update) op_update "$ARG1" "$ARG2" ;;
    wan-param) op_wan_param "$ARG1" "$ARG2" ;;
    tunnel-conf) op_tunnel_conf "$ARG1" "$ARG2" "$ARG3" "$ARG4" ;;
    vless-server) op_vless_server "$ARG1" "$ARG2" "$ARG3" "$ARG4" ;;
    backup-create) op_backup_create "$ARG1" ;;
    wifi-host) op_wifi_host "$ARG1" "$ARG2" "$ARG3" ;;
    backup-restore) op_backup_restore "$ARG1" ;;
    cleanup) op_cleanup "$ARG1" ;;
    smartdns-server) op_smartdns_server "$ARG1" ;;
    ai) op_ai "$ARG1" "$ARG2" "$ARG3" ;;
    list) op_list "$ARG1" "$ARG2" "$ARG3" ;;
    agh-component) op_agh_component "$ARG1" "$ARG2" ;;
    module-component) op_module_component "$ARG1" "$ARG2" "$ARG3" ;;
    smartdns-keenetic) op_smartdns_keenetic "$ARG1" "$ARG2" ;;
    smartdns-store) op_smartdns_store "$ARG1" ;;
    component-recover) op_component_recover ;;
    reset) op_reset "$ARG1" ;;
    tunnel-delete) op_tunnel_delete "$ARG1" "$ARG2" "$ARG3" ;;
    tunnel-state) op_tunnel_state "$ARG1" "$ARG2" ;;
    tunnel-subnet) op_tunnel_subnet "$ARG1" "$ARG2" "$ARG3" ;;
    list-domain) op_list_domain "$ARG1" "$ARG2" "$ARG3" ;;
    service) op_service "$ARG1" "$ARG2" "$ARG3" ;;
    service-category) op_service_category "$ARG1" "$ARG2" ;;
    services-refresh) op_services_refresh ;;
    ext-check) op_ext_check ;;
    ext-daily) op_ext_daily ;;
    ext-upgrade) op_ext_upgrade "$ARG1" "$ARG2" ;;
    ext-auto) op_ext_auto "$ARG1" "$ARG2" ;;
    ext-agh-official) op_ext_agh_official "$ARG1" ;;
    journal) op_journal "$ARG1" "$ARG2" ;;
    agents-mode) op_agents_mode "$ARG1" "$ARG2" ;;
    firmware) op_firmware "$ARG1" "$ARG2" ;;
    *) die invalid_operation 64 ;;
esac
