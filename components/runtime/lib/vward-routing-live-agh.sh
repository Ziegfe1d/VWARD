#!/bin/sh
# Fixed live AGH binding: existing component worker/common client, actual final
# curl PID and real HTTP completion. No backend/address is an action argument.
vrl_agh_library_load() {
    : "${vrl_etc:?}"
    [ "${vrl_agh_loaded:-0}" = 1 ] && return 0
    vrl_al_lib=${VWARD_ROOT_PREFIX:-}/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh
    vrl_path_gate "$vrl_al_lib" || return 75
    [ -f "$vrl_al_lib" ] && [ ! -L "$vrl_al_lib" ] && [ -O "$vrl_al_lib" ] && [ -r "$vrl_al_lib" ] || return 75
    # Installed signed helper is0644. Never source a group/world-writable file.
    # shellcheck disable=SC2012
    case $(ls -ldn "$vrl_al_lib" | awk '{print substr($1,1,10)}') in
        -rw-r--r--|-rwxr-xr-x|-r-xr-xr-x|-rw-------|-r--------) ;; *) return 75 ;;
    esac
    vrl_al_path=$PATH
    # The signed component library defines helpers; no CLI/daemon is sourced.
    # shellcheck source=/dev/null
    . "$vrl_al_lib" || return 75
    PATH=$vrl_al_path;export PATH
    export ADS_DEVICE_CONFIG="${VWARD_ADS_DEVICE_CONFIG:-$vrl_etc/device.conf}"
    export ADS_AGH_AUTH_FILE="${VWARD_ADS_AGH_AUTH_FILE:-${VWARD_ADS_ETC:-$vrl_etc/ads-privacy-guard}/agh-api.auth}"
    [ -x "$ADS_CURL" ] && [ -x "$ADS_JQ" ] || return 75
    vrl_agh_loaded=1
}
vrl_agh_get() {
    [ "$#" -eq 1 ] && vrl_agh_library_load || return 75
    ads_agh_api GET dns_info "$1" || return 75
    vrj2_file "$1" && vrb_single_link "$1" && "$ADS_JQ" -e '
        type=="object" and (.upstream_dns|type)=="array" and all(.upstream_dns[];type=="string")
        and ((.upstream_dns_file // "")|type)=="string"' "$1" >/dev/null || return 75
}
vrl_agh_observe() {
    : "${vrl_cache:?}"
    vrl_ao_present=0
    [ -z "${AGH_API_BASE:-}" ] || vrl_ao_present=1
    for vrl_ao_path in "${VWARD_ADGUARD_CONFIG:-${VWARD_ROOT_PREFIX:-}/opt/etc/AdGuardHome/AdGuardHome.yaml}" \
        "${VWARD_ROOT_PREFIX:-}/opt/etc/AdGuardHome" "${VWARD_ROOT_PREFIX:-}/opt/bin/AdGuardHome"; do
        if [ -e "$vrl_ao_path" ] || [ -L "$vrl_ao_path" ];then vrl_ao_present=1;fi
    done
    if [ "$vrl_ao_present" = 0 ]; then
        [ ! -e "$vrl_cache/agh.json" ] && [ ! -L "$vrl_cache/agh.json" ] || return 75
        : > "$vrl_cache/agh-domains";return $?
    fi
    vrl_agh_library_load || return 75
    vrl_ao_tmp=$(mktemp "$vrl_cache/.agh-read.XXXXXX") || return 1
    vrl_agh_get "$vrl_ao_tmp" || return 75
    "$ADS_JQ" -ceS '.' "$vrl_ao_tmp" > "$vrl_ao_tmp.canonical" || return 75
    vrl_observation_copy "$vrl_ao_tmp.canonical" > "$vrl_cache/agh.json" || return 1
    "$ADS_JQ" -r '.upstream_dns[] | select(startswith("[/") and contains("/]")) |
        .[2:index("/]")] | split("/")[] | ascii_downcase' "$vrl_ao_tmp" > "$vrl_ao_tmp.domains" || return 75
    vrl_observation_copy "$vrl_ao_tmp.domains" > "$vrl_cache/agh-domains" || return 1
    rm -f "$vrl_ao_tmp" "$vrl_ao_tmp.canonical" "$vrl_ao_tmp.domains"
}
vrl_agh_derived_deltas() (
    [ "$3:$4" = dns-scope:agh ] || return 0
    # The legacy domain projection really changes with upstream_dns. Permit
    # ONLY the deterministic bytes from each SAME sealed API observation;
    # merely allowlisting label "agh" would hide a foreign input replacement.
    for vrl_ad_stage in "$1" "$2"; do
        vr2_stage_valid "$vrl_ad_stage" || return 75
        "${JQ:-jq}" -r '.upstream_dns[] | select(startswith("[/") and contains("/]")) |
            .[2:index("/]")] | split("/")[] | ascii_downcase' "$vrl_ad_stage/agh.json" > "$vrl_ad_stage/.agh-derived" || return 75
        vrl_ad_hash=$(vr2_hash "$vrl_ad_stage/.agh-derived") || return 75
        awk -v h="$vrl_ad_hash" -v uid="$(id -u)" '$1=="agh" {
            if(NF!=7 || $2!=h || $6!="-rw-------" || $7!=uid)bad=1;n++
        }END{exit bad || n!=1}' "$vrl_ad_stage/inputs.fp" || return 75
    done
    printf 'agh\n'
)
vrl_agh_exec() (
    : "${vrb_j:?}" "${vrb_op:?}" "${vrj2_boot:?}"
    vrb_worker_context && vrb_self_admit routing-publisher || return 75
    IFS=' ' read -r vrb_pub_pid _ < /proc/self/stat || return 75
    vrb_pub_start=$(vrj2_pid_start "$vrb_pub_pid") || return 75
    [ -e "$vrb_j/$vrb_op/workers" ] || mkdir "$vrb_j/$vrb_op/workers" || return 1
    vrj_dir "$vrb_j/$vrb_op/workers" || return 75
    printf '%s\n' "$vrj2_boot" > "$vrb_j/$vrb_op/workers/$vrj2_boot.$vrb_pub_pid.$vrb_pub_start" &&
        vr2_hash "$vrb_j/$vrb_op/workers/$vrj2_boot.$vrb_pub_pid.$vrb_pub_start" > "$vrb_j/$vrb_op/workers/$vrj2_boot.$vrb_pub_pid.$vrb_pub_start.sha" && vrj2_flush || return 1
    # shellcheck disable=SC2034
    vrb_pub_mode=0600
    [ "$(vr2_hash "$W/transport.body.json")" = "$(cat "$W/transport.body.sha")" ] &&
        vrb_dispatch_mark "$W/transport.predicted.json" "$(vrb_agh_path)" && vrb_worker_context || return 75
    # Authentication is private config, not argv. The actual curl replaces its
    # registered publisher in the SAME PID; there is no unleased pipeline child.
    exec "$ADS_CURL" -K "$W/transport.auth" -f -sS -X POST --connect-timeout 3 --max-time 15 \
        -H 'Content-Type: application/json' --data-binary "@$W/transport.body.json" \
        "$vrl_ah_base/dns_config" -o "$W/transport.response"
)
vrl_agh_post() {
    : "${vrb_role:?}"
    [ "$#" -eq 3 ] && [ "$1" = dns_config ] && vrb_worker_context && vrl_requests_quiet || return 75
    "$ADS_JQ" -e 'keys==["upstream_dns"] and (.upstream_dns|type)=="array" and
        all(.upstream_dns[];type=="string")' "$2" >/dev/null || return 75
    case $2:$vrb_role in
        "$W/body.json:forward"|"$W/plan.json:forward") vrl_ah_expected=$W/dns.json;vrl_ah_planned=$W/plan.json ;;
        "$W/back.json:inverse") vrl_ah_expected=$W/plan.json;vrl_ah_planned=$W/dns.json ;;
        *) return 75 ;; # No automatic helper inverse after an uncertain request.
    esac
    vrl_agh_get "$W/transport.before.json" &&
        "$ADS_JQ" -e '(.upstream_dns_file // "")==""' "$W/transport.before.json" >/dev/null &&
        vrb_agh_scope "$W/transport.before.json" > "$W/transport.current" &&
        vrb_agh_scope "$vrl_ah_expected" > "$W/transport.expected" &&
        cmp -s "$W/transport.current" "$W/transport.expected" &&
        vrb_agh_scope "$2" > "$W/transport.body.json" &&
        vrb_agh_scope "$vrl_ah_planned" > "$W/transport.planned" &&
        cmp -s "$W/transport.body.json" "$W/transport.planned" || return 75
    # Full predicted configuration only binds the dispatch scope. HTTP owns
    # upstream_dns alone and preserves every other server setting.
    # shellcheck disable=SC2016
    "$ADS_JQ" -cS --slurpfile n "$W/transport.body.json" '.upstream_dns=$n[0].upstream_dns' \
        "$W/transport.before.json" > "$W/transport.predicted.json" &&
        vr2_hash "$W/transport.body.json" > "$W/transport.body.sha" || return 1
    vrl_ah_base=$(ads_agh_api_base) || return 75
    ads_agh_curl_conf > "$W/transport.auth" || return 75
    printf '%s\n' pending > "$VWARD_AGH_RECOVERY_DIR/request.pending" && vrj2_flush || return 1
    vrl_ah_rc=0;vrl_agh_exec > "$W/transport.stdout" 2> "$W/transport.stderr" || vrl_ah_rc=$?
    [ "$vrl_ah_rc" = 0 ] && vrb_worker_context || return 75
    vrl_agh_get "$W/transport.after.json" &&
        vrb_agh_scope "$W/transport.after.json" > "$W/transport.readback" &&
        cmp -s "$W/transport.readback" "$W/transport.planned" &&
        "$ADS_JQ" -e '(.upstream_dns_file // "")==""' "$W/transport.after.json" >/dev/null || return 75
    vrb_worker_context || return 75
    printf '%s\n' acknowledged-readback > "$VWARD_AGH_RECOVERY_DIR/completion" &&
        vr2_hash "$VWARD_AGH_RECOVERY_DIR/completion" > "$VWARD_AGH_RECOVERY_DIR/completion.sha" && vrj2_flush || return 1
    rm -f "$VWARD_AGH_RECOVERY_DIR/request.pending" && vrj2_flush || return 75
    printf '{}\n' > "$3"
}
vrl_agh_session() (
    umask 077
    [ "$#" -eq 7 ] && [ "$1" = "$(vrb_agh_path)" ] && vrb_worker_context && vrl_agh_library_load || return 75
    AG_SET=$2;A1=$3;A2=$4;W=$5;VWARD_AGH_RECOVERY_DIR=$6
    case $AG_SET in smartdns-put|smartdns-take-pairs|guarded-back) ;; *) return 2 ;; esac
    case $W in "$vrb_j/$vrb_op/dns-evidence/call."*|"$vrb_j/$vrb_op/dns-inverse."*/call) ;; *) return 75 ;; esac
    vrj_dir "$W" && vrj_dir "$VWARD_AGH_RECOVERY_DIR" && vrj2_file "$A1" || return 75
    CONTROL_LOCK=${VWARD_ROOT_PREFIX:-}/tmp/vward-ads-control.lock;CL_HELD=0
    ads_lock_acquire "$CONTROL_LOCK" 30 || return 75;CL_HELD=1
    trap 'ads_lock_release "$CONTROL_LOCK"' EXIT
    export AG_SET A1 A2 CL_HELD VWARD_AGH_RECOVERY_DIR
    # Fixed callbacks used by the SAME existing component worker.
    # shellcheck disable=SC2317
    ads_agh_api_get() { [ "$1" = dns_info ] && vrl_agh_get "$2"; }
    # shellcheck disable=SC2317
    ads_agh_api_post() { vrl_agh_post "$@"; }
    # Diagnostics are already captured privately in W/result.
    # shellcheck disable=SC2317
    ads_log() { :; }
    if [ "$AG_SET" = guarded-back ]; then
        cp "$A1" "$W/dns.json" && cp "$A2" "$W/plan.json" || return 1
        cp "$A2" "$VWARD_AGH_RECOVERY_DIR/dns.before.json" && cp "$A1" "$VWARD_AGH_RECOVERY_DIR/dns.planned.json" || return 1
        agh_guarded_back > "$W/result" 2>&1
    else (ads_smartdns_locked) > "$W/result" 2>&1;fi
)
