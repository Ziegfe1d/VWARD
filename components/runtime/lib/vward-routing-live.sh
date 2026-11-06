#!/bin/sh
# Fixed installed binding for the SAME typed-plan/J2 executor. Definitions only.
# The ordinary console remains the outer entrypoint. No API parameter or new
# environment executable selector chooses a backend; DATA binding is unchanged.

vrl_paths_bind() {
    VWARD_ROOT_PREFIX=${VWARD_ROOT_PREFIX-}
    case $VWARD_ROOT_PREFIX in ''|/*) ;; *) return 75 ;; esac
    case $VWARD_ROOT_PREFIX in */../*|*/./*|*/..|*/.|*//*) return 75 ;; esac
    vrl_root=${VWARD_ROOT_PREFIX:-}/opt/var/lib/vward/routing
    vrl_etc=${VWARD_ROOT_PREFIX:-}/opt/etc/vward
}

vrl_ready() {
    vrl_paths_bind || return 75
    [ "$#" -eq 1 ] && [ "$1" = "$vrl_root/journal" ] || return 75
    vrj_dir "${1%/journal}" && vrj_dir "$1" && vrj_dir "${1%/journal}/decision" || return 75
    command -v vward_routing_console_group_locked >/dev/null 2>&1 &&
        command -v vward_lock_take >/dev/null 2>&1 || return 75
}

# Closed destinations, independent of labels/names submitted by a caller.
vrl_local_path() {
    case $1:$2 in
        manifest:resources|manifest:proofs|manifest:choices|manifest:policies|manifest:tombstones|manifest:saved|manifest:queue|manifest:evidence|manifest:version|manifest:bindings|manifest:context|manifest:upstreams)
            printf '%s/decision/%s.tsv\n' "$vrb_e" "$2" ;;
        nativeproof:domain-list[0-9]|nativeproof:domain-list[0-9][0-9]) printf '%s/services/owned/%s\n' "$vrl_etc" "$2" ;;
        registry:enabled) printf '%s/services/enabled.tsv\n' "$vrl_etc" ;;
        *) return 75 ;;
    esac
}
vrl_legacy_source() {
    case $1 in
        cfg) vrb_native_path ;;
        dev) printf '%s/device.conf\n' "$vrl_etc" ;;
        map) printf '%s/tmp/vward-device-map.tsv\n' "${VWARD_ROOT_PREFIX:-}" ;;
        enabled) printf '%s/services/enabled.tsv\n' "$vrl_etc" ;;
        categories) printf '%s/services/categories.tsv\n' "$vrl_etc" ;;
        persist) printf '%s/opt/var/lib/vward/route-engine/adaptive-persist.txt\n' "${VWARD_ROOT_PREFIX:-}" ;;
        catalog-fetched) printf '%s/opt/var/lib/vward/services/catalog.json\n' "${VWARD_ROOT_PREFIX:-}" ;;
        catalog-bundled) printf '%s/opt/share/vward/console/services-catalog.json\n' "${VWARD_ROOT_PREFIX:-}" ;;
        owned:*) printf '%s/services/owned/%s\n' "$vrl_etc" "${1#owned:}" ;;
        list:*) printf '%s/route-engine/domain-lists/%s\n' "$vrl_etc" "${1#list:}" ;;
        obs-dnsproof:*) printf '%s/route-engine/domain-lists.dns/%s\n' "$vrl_etc" "${1#obs-dnsproof:}" ;;
        obs-smartdns-profile) printf '%s/smartdns.conf\n' "$vrl_etc" ;;
        *) return 75 ;;
    esac
}
vrl_publication_label() {
    case $1 in
        "$vrl_cache/running-config") printf 'cfg\n' ;;
        "$vrl_cache/agh.json") printf 'obs-agh-image\n' ;;
        "$vrl_etc/services/enabled.tsv") printf 'enabled\n' ;;
        "$vrl_etc/services/owned/"*)
            case ${1##*/} in domain-list[0-9]|domain-list[0-9][0-9]) printf 'owned:%s\n' "${1##*/}" ;; *) return 75 ;; esac ;;
        "$vrb_e/decision/"*.tsv)
            vrl_pl_key=${1##*/};vrl_pl_key=${vrl_pl_key%.tsv}
            [ "$(vrl_local_path manifest "$vrl_pl_key")" = "$1" ] || return 75
            printf 'v2-%s\n' "$vrl_pl_key" ;;
        *) return 75 ;;
    esac
}
vrl_path_gate() (
    # /opt itself is the existing trusted Entware mount boundary. Below it,
    # reject aliases and writable-by-others directories; never follow a reused
    # metadata leaf or accept an API-provided path as a destination.
    case $1 in
        "$vrb_e/"*|"$vrl_etc/services/"*|"$vrl_etc/device.conf"|"$vrl_etc/smartdns.conf"|\
        "$vrl_etc/route-engine/domain-lists/"*|"$vrl_etc/route-engine/domain-lists.dns/"*|\
        "${VWARD_ROOT_PREFIX:-}/opt/var/lib/vward/services/catalog.json"|\
        "${VWARD_ROOT_PREFIX:-}/opt/share/vward/console/services-catalog.json"|\
        "${VWARD_ROOT_PREFIX:-}/opt/var/lib/vward/route-engine/adaptive-persist.txt") vrl_pg_stop=${VWARD_ROOT_PREFIX:-}/opt ;;
        "${VWARD_ROOT_PREFIX:-}/tmp/"*) vrl_pg_stop=${VWARD_ROOT_PREFIX:-}/tmp ;;
        *) return 75 ;;
    esac
    case $1 in */../*|*/./*|*/..|*/.|*//*) return 75 ;; esac
    vrl_pg_parent=${1%/*}
    while [ "$vrl_pg_parent" != "$vrl_pg_stop" ]; do
        [ -d "$vrl_pg_parent" ] && [ ! -L "$vrl_pg_parent" ] && [ -O "$vrl_pg_parent" ] || return 75
        # shellcheck disable=SC2012
        case $(ls -ldn "$vrl_pg_parent" | awk '{print substr($1,1,10)}') in
            drwx------|drwxr-xr-x|drwxr-x---|drwx--x--x) ;; *) return 75 ;;
        esac
        vrl_pg_parent=${vrl_pg_parent%/*}
        [ -n "$vrl_pg_parent" ] || return 75
    done
    [ -d "$vrl_pg_stop" ] && [ -O "$vrl_pg_stop" ]
)

vrl_refresh() {
    vrl_ready "$vrb_j" || return 75
    vrl_dns_observe || return 75
    vrl_rf_tmp=$(mktemp "$vrl_cache/.native-read.XXXXXX") || return 1
    if ! "$vrl_ndmc" -c 'show running-config' > "$vrl_rf_tmp" 2> "$vrl_rf_tmp.stderr"; then
        rm -f "$vrl_rf_tmp";return 75
    fi
    if [ ! -s "$vrl_rf_tmp" ] || ! awk '
        /^[[:space:]]*(Command::|[Ee][Rr][Rr][Oo][Rr][: ]|[Ff]ailed[: ])/ {bad=1}
        /^(object-group fqdn |dns-proxy$|interface |ip |system$)/ {seen=1}
        END {exit bad || !seen}' "$vrl_rf_tmp"; then rm -f "$vrl_rf_tmp";return 75;fi
    # The actual owner writes shared observations itself: an unleased cp/tr
    # child must not replace a later coordinator's cache after parent death.
    vrl_rf_dest=$vrl_cache/running-config
    if [ -e "$vrl_rf_dest" ] || [ -L "$vrl_rf_dest" ]; then
        vrj2_file "$vrl_rf_dest" && vrb_single_link "$vrl_rf_dest" || return 75
    fi
    vrl_observation_copy "$vrl_rf_tmp" > "$vrl_rf_dest" || return 1
    rm -f "$vrl_rf_tmp" "$vrl_rf_tmp.stderr"
}
vrl_dns_observe() {
    # Installed AGH is not an empty DNS store. Its actual read/POST adapter is
    # required before that scope can run; never infer absence from a failed API.
    # No connected caller/package activation is installed in this checkpoint.
    [ "${VWARD_ADGUARD_CONFIG:-${VWARD_ROOT_PREFIX:-}/opt/etc/AdGuardHome/AdGuardHome.yaml}" = "${VWARD_ROOT_PREFIX:-}/opt/etc/AdGuardHome/AdGuardHome.yaml" ] || return 75
    for vrl_do_path in "${VWARD_ROOT_PREFIX:-}/opt/etc/AdGuardHome" "${VWARD_ROOT_PREFIX:-}/opt/bin/AdGuardHome"; do
        [ ! -e "$vrl_do_path" ] && [ ! -L "$vrl_do_path" ] || return 75
    done
    if [ -e "$vrl_cache/agh-domains" ] || [ -L "$vrl_cache/agh-domains" ]; then
        vrj2_file "$vrl_cache/agh-domains" && vrb_single_link "$vrl_cache/agh-domains" || return 75
    fi
    : > "$vrl_cache/agh-domains"
}
vrl_observation_copy() {
    vrl_oc_cr=$(printf '\r')
    while IFS= read -r vrl_oc_line || [ -n "$vrl_oc_line" ]; do
        vrl_oc_line=${vrl_oc_line%"$vrl_oc_cr"}
        printf '%s\n' "$vrl_oc_line" || return 1
    done < "$1"
}
vrl_scope_read() (
    case $1:$2 in
        group:*) vrl_refresh && vrb_cfg_image "$vrl_cache/running-config" "$2" > "$3" ;;
        saved:routing-state) vrb_state_image "$vrb_e/decision" "$3" ;;
        *)
            vrl_sr_path=$(vrl_local_path "$1" "$2") || return 75
            vrl_path_gate "$vrl_sr_path" || return 75
            if [ ! -e "$vrl_sr_path" ] && [ ! -L "$vrl_sr_path" ]; then printf '%s\n' - > "$3"
            else vrb_owned_data_file "$vrl_sr_path" && cat "$vrl_sr_path" > "$3";fi ;;
    esac
)
vrl_worker_scope_before() {
    # Prediction input only. The existing physical NDMC preflight still forces
    # a NEW native read and validates the compiled prefix immediately before
    # dispatch; this cached observation never authorizes a native mutation.
    [ "$1" = group ] && vrj2_file "$vrl_cache/running-config" &&
        vrb_cfg_image "$vrl_cache/running-config" "$2" > "$3"
}
vrl_worker_scope_after() {
    # Return the actual transport's verified readback once, in its SAME caller
    # process. Do not query again and accidentally bind a later image to its ACK.
    IFS=' ' read -r vrl_ra_pid _ < /proc/self/stat || return 75
    [ "$#" -eq 3 ] && [ "$1" = group ] && [ "${vrl_ack_group:-}" = "$2" ] &&
        [ "${vrl_ack_op:-}" = "$vrb_op" ] && [ "${vrl_ack_step:-}" = "$vrb_active_step" ] &&
        [ "${vrl_ack_pid:-}" = "$vrl_ra_pid" ] &&
        [ "${vrl_ack_start:-}" = "$(vrj2_pid_start "$vrl_ra_pid")" ] || return 75
    case ${vrl_ack_call:-} in "$vrb_j/$vrb_op/native."*) ;; *) return 75 ;; esac
    vrl_ra_call=$vrl_ack_call;vrl_ack_call=
    vrj2_file "$vrl_ra_call/completion" && vrj2_file "$vrl_ra_call/completion.sha" &&
        [ "$(vr2_hash "$vrl_ra_call/completion")" = "$(cat "$vrl_ra_call/completion.sha")" ] &&
        [ "$(cat "$vrl_ra_call/completion")" = acknowledged-readback ] &&
        vrj2_file "$vrl_ra_call/readback" && vrb_single_link "$vrl_ra_call/readback" &&
        vrj2_file "$vrl_ra_call/readback.sha" &&
        [ "$(vr2_hash "$vrl_ra_call/readback")" = "$(cat "$vrl_ra_call/readback.sha")" ] &&
        [ ! -e "$vrl_ra_call/request.pending" ] && [ ! -L "$vrl_ra_call/request.pending" ] || return 75
    vrl_observation_copy "$vrl_ra_call/readback" > "$3"
}
vrl_parent_scope_hash() {
    : "${vrb_t:?}"
    if [ "$2" = group ]; then
        # Use the scope from the SAME sealed G0/G1 snapshot as this journal
        # transition; another query here would be a different, unbound Gi.
        vrb_outcome_scope_hash "$1" "$2" "$3" > "$4"
    else vrb_scope_read "$2" "$3" "$vrb_t/current" && vr2_hash "$vrb_t/current" > "$4";fi
}
vrl_context() {
    [ "${vrb_inside:-}" = locked-native ] &&
        [ "$vrb_e" = "${VWARD_ROOT_PREFIX:-}/opt/var/lib/vward/routing" ] &&
        [ "$vrb_j" = "$vrb_e/journal" ] && vrl_ready "$vrb_j" &&
        vward_routing_legacy_recovery_gate
}

# This is the actual final NDMC process: after registration it execs transport
# in the SAME PID. Its durable PID/start/BOOT lease survives parent-only death.
# A request receipt proves only dispatch. Only the waiting owner may record
# successful transport completion AND fresh readback; matching bytes do not ACK.
vrl_native_exec() (
    vrb_worker_context && vrb_self_admit routing-publisher || return 75
    : "${vrb_t:?}"
    IFS=' ' read -r vrb_pub_pid _ < /proc/self/stat || return 75
    vrb_pub_start=$(vrj2_pid_start "$vrb_pub_pid") || return 75
    [ -e "$vrb_j/$vrb_op/workers" ] || mkdir "$vrb_j/$vrb_op/workers" || return 1
    vrj_dir "$vrb_j/$vrb_op/workers" || return 75
    printf '%s\n' "$vrj2_boot" > "$vrb_j/$vrb_op/workers/$vrj2_boot.$vrb_pub_pid.$vrb_pub_start" &&
        vr2_hash "$vrb_j/$vrb_op/workers/$vrj2_boot.$vrb_pub_pid.$vrb_pub_start" > "$vrb_j/$vrb_op/workers/$vrj2_boot.$vrb_pub_pid.$vrb_pub_start.sha" || return 1
    vrj2_flush || return 1
    [ "$(cat "$vrl_call/command")" = "$1" ] &&
        [ "$(vr2_hash "$vrl_call/command")" = "$(cat "$vrl_call/command.sha")" ] || return 75
    # Consumed by the shared dispatch/scope receipt verifier.
    # shellcheck disable=SC2034
    vrb_pub_mode=0600
    if [ "$vrb_role" != save ] && [ "$vrb_role" != baseline-save ]; then
        vrb_dispatch_mark "$vrb_t/config.next" "$vrl_cache/running-config" || return 75
    fi
    vrb_worker_context || return 75
    # No shell or transport child can remain unregistered past this point.
    exec "$vrl_ndmc" -c "$1"
)
vrl_native_ndm() {
    [ "$#" -eq 1 ] && vrb_worker_context || return 75
    vrl_ack_call=
    vrl_refresh || return 75
    vrl_nc_save=0
    if [ "$1" = 'system configuration save' ]; then
        case $vrb_role in save|baseline-save) ;; *) return 75 ;; esac
        vrl_nc_save=1
    else
        [ "$vrb_role" != save ] && [ "$vrb_role" != baseline-save ] || return 75
        if [ "$vrb_role" = inverse ]; then vrl_nc_expected=$vrb_t/inverse.expected
        else vrl_nc_expected=$vrb_t/expected;fi
        vrb_native_compile "$1" "$vrl_cache/running-config" "$vrl_nc_expected" "$vrb_t" || return 75
        IFS="$(printf '\t')" read -r _vrl_kind vrl_nc_group _vrl_value _vrl_neg < "$vrb_t/native.command" || return 75
        vrj2_step_row "$vrb_j/$vrb_op" "$vrb_active_step" | awk -F'\t' -v g="$vrl_nc_group" '$4=="group" && $5==g{ok=1}END{exit ok?0:1}' || return 75
    fi
    vrl_call=$(mktemp -d "$vrb_j/$vrb_op/native.XXXXXX") || return 1
    printf '%s\n' "$1" > "$vrl_call/command" && vr2_hash "$vrl_call/command" > "$vrl_call/command.sha" &&
        printf '%s\n' pending > "$vrl_call/request.pending" &&
        vr2_hash "$vrl_cache/running-config" > "$vrl_call/config.before.sha" && vrj2_flush || return 1
    vrl_nc_rc=0
    vrl_native_exec "$1" > "$vrl_call/stdout" 2> "$vrl_call/stderr" || vrl_nc_rc=$?
    # A failed/lost transport reply is UNKNOWN even if its postimage matches.
    # Do not remove pending, replay, or compensate from this branch.
    [ "$vrl_nc_rc" = 0 ] && ! grep -Eqi '(^|[^a-z])(error|failed|invalid|unknown command)([^a-z]|$)' "$vrl_call/stdout" "$vrl_call/stderr" || return 75
    vrb_worker_context || return 75
    vrl_refresh || return 75
    if [ "$vrl_nc_save" = 1 ]; then
        [ "$(vr2_hash "$vrl_cache/running-config")" = "$(cat "$vrl_call/config.before.sha")" ] || return 75
        vrl_last_save=$vrl_call
    else
        vrb_cfg_image "$vrl_cache/running-config" "$vrl_nc_group" > "$vrl_call/readback" &&
            cmp -s "$vrl_call/readback" "$vrb_t/native.next" &&
            vr2_hash "$vrl_call/readback" > "$vrl_call/readback.sha" || return 75
    fi
    vrb_worker_context || return 75
    printf '%s\n' acknowledged-readback > "$vrl_call/completion" &&
        vr2_hash "$vrl_call/completion" > "$vrl_call/completion.sha" && vrj2_flush || return 1
    rm -f "$vrl_call/request.pending" && vrj2_flush || return 75
    if [ "$vrl_nc_save" != 1 ]; then
        vrl_ack_call=$vrl_call;vrl_ack_group=$vrl_nc_group;vrl_ack_op=$vrb_op;vrl_ack_step=$vrb_active_step
        IFS=' ' read -r vrl_ack_pid _ < /proc/self/stat || return 75
        vrl_ack_start=$(vrj2_pid_start "$vrl_ack_pid") || return 75
    fi
}
vrl_saved() {
    case ${vrl_last_save:-} in "$vrb_j/$vrb_op/native."*) ;; *) return 75 ;; esac
    vrj2_file "$vrl_last_save/completion" && vrj2_file "$vrl_last_save/completion.sha" &&
        [ "$(vr2_hash "$vrl_last_save/completion")" = "$(cat "$vrl_last_save/completion.sha")" ] &&
        [ "$(cat "$vrl_last_save/completion")" = acknowledged-readback ] &&
        [ "$(cat "$vrl_last_save/command")" = 'system configuration save' ] &&
        [ ! -e "$vrl_last_save/request.pending" ] && [ ! -L "$vrl_last_save/request.pending" ]
}
vrl_cleanup() {
    vrl_clean_quiet=1
    if [ -d "$vrb_j/$vrb_op" ]; then vrb_publish_quiet "$vrb_j/$vrb_op" || vrl_clean_quiet=0;fi
    if command -v vrl_init_quiet >/dev/null 2>&1; then vrl_init_quiet || vrl_clean_quiet=0;fi
    if [ "$vrl_clean_quiet" = 1 ]; then
        [ "$vrb_change" != 1 ] || vrb_shared_unlock "$vrb_change_path"
        [ "$vrb_edit" != 1 ] || vrb_shared_unlock "$vrb_edit_path"
    fi
    vrb_reap_publisher_slots
    if [ "$vrl_clean_quiet" = 1 ] && [ -n "${vrl_cache:-}" ]; then
        case $vrl_cache in "${VWARD_ROOT_PREFIX:-}/tmp/vward-routing-live."*)
            vrj_dir "$vrl_cache" && rm -rf "$vrl_cache" ;; esac
    fi
    vrb_self_leave "$vrb_coord_slot"
    vward_admission_leave
}
vrl_envelope() {
    umask 077
    vrl_paths_bind || return 75
    case $#:${3:-} in
        2:) vrl_ready "$1" || return 75 ;;
        3:bootstrap) vrl_init_base "$1" || return 75 ;;
        *) return 75 ;;
    esac
    vrj2_id "$2" || return 75
    vrb_j=$1;vrb_e=${1%/journal};vrb_op=$2
    vrl_etc=${VWARD_ROOT_PREFIX:-}/opt/etc/vward
    vrl_ndmc=${NDMC:-${VWARD_NDMC:-ndmc}}
    command -v "$vrl_ndmc" >/dev/null 2>&1 || return 75
    # Consumed/reset by the existing runtime admission library and its workers.
    export VWARD_BACKGROUND=1 VWARD_ADMISSION_OWNED=0 VWARD_ADMISSION_SLOT=
    vward_admission_enter routing-live || return 75
    vrb_self_admit routing-coordinator || { vward_admission_leave;return 75; }
    vrb_coord_slot=${vrb_registered_slot:?}
    IFS=' ' read -r vrj2_me _ < /proc/self/stat || return 75
    # The shared worker/election context checks this actual starttime.
    # shellcheck disable=SC2034
    vrj2_start=$(vrj2_pid_start "$vrj2_me") || return 75
    IFS= read -r vrj2_boot < /proc/sys/kernel/random/boot_id || return 75
    vrb_edit_path=${VWARD_ROOT_PREFIX:-}/tmp/vward-console-edit.lock
    vrb_change_path=${VWARD_ROOT_PREFIX:-}/tmp/vward-route-change.lock
    vrb_edit=0;vrb_change=0;vrb_inside=;vrb_role=;vrb_active_step=;vrl_cache=;vrl_last_save=;vrl_ack_call=
    # Consumed by the bootstrap publisher/quiet checker in its separate module.
    # shellcheck disable=SC2034
    vrl_boot_stage=
    trap vrl_cleanup EXIT
    trap 'exit 143' HUP INT TERM
    vrb_shared_lock "$vrb_edit_path" || return 75;vrb_edit=1
    vrb_shared_lock "$vrb_change_path" || return 75;vrb_change=1
    [ ! -e "${VWARD_ROOT_PREFIX:-}/tmp/vward-update-requested" ] && [ ! -L "${VWARD_ROOT_PREFIX:-}/tmp/vward-update-requested" ] &&
        [ ! -e "${VWARD_ROOT_PREFIX:-}/tmp/vward-update.lock" ] && [ ! -L "${VWARD_ROOT_PREFIX:-}/tmp/vward-update.lock" ] || return 75
    vward_routing_legacy_recovery_gate || return 75
    if [ "${3:-}" = bootstrap ]; then vrl_init_root || return 75;fi
    # Forward admission belongs to the actual pipeline/server/migration entry:
    # each checks journal2_gate BEFORE plan/state/native writes. Repeating that
    # global gate here would also prevent explicit own recovery from inspecting
    # an unknown operation. Lock reclaim/worker/updater quiet checks are separate.
    vrl_cache=$(mktemp -d "${VWARD_ROOT_PREFIX:-}/tmp/vward-routing-live.XXXXXX") || return 1
    vrj_dir "$vrl_cache" || return 75
    VWARD_KCACHE=$vrl_cache;RUNCFG=$vrl_cache/running-config
    VWARD_CONSOLE_ETC=$vrl_etc
    VWARD_ROUTING_AGH_IMAGE=$vrl_cache/agh.json
    VWARD_ROUTING_AGH_DOMAINS=$vrl_cache/agh-domains
    export VWARD_KCACHE RUNCFG VWARD_CONSOLE_ETC VWARD_ROUTING_AGH_IMAGE VWARD_ROUTING_AGH_DOMAINS
    vrb_revocations_gate "$vrb_j" "$vrb_e/decision" || return 75
}

# Bind fixed functions only inside this explicitly invoked coordinator process.
# No caller can submit a function name, physical destination or transport mode.
# Fixed callbacks below are invoked indirectly by the shared executor.
# shellcheck disable=SC2317
vrl_bind() {
    vrb_runtime_ready() { vrl_ready "$@"; }
    vrb_pipeline_ready() { vrl_ready "$1" && vward_routing_state_gate 2 "${1%/journal}/decision"; }
    vrb_envelope() { vrl_envelope "$@"; }
    vrb_backend_context() { vrl_context; }
    vrb_execution_context() { vrb_inside=locked-native; }
    vrb_execution_evidence() { printf 'native\n'; }
    vrb_activation() { printf 'live\n'; }
    vrb_data_ancestry() { vrl_path_gate "$@"; }
    vrb_local_path() { vrl_local_path "$@"; }
    vrb_publication_label() { vrl_publication_label "$@"; }
    vrb_scope_read() { vrl_scope_read "$@"; }
    vrb_worker_scope_before() { vrl_worker_scope_before "$@"; }
    vrb_worker_scope_after() { vrl_worker_scope_after "$@"; }
    vrb_parent_scope_hash() { vrl_parent_scope_hash "$@"; }
    vrb_legacy_source() { vrl_legacy_source "$@"; }
    vrb_native_path() { printf '%s/running-config\n' "$vrl_cache"; }
    vrb_transport_refresh() { vrl_refresh; }
    vrb_transport_saved() { vrl_saved; }
    ndm() { vrl_native_ndm "$@" || return 75; }
    snapshot() { vrl_refresh; }
}

vward_routing_live_service() (
    umask 077
    [ "$#" -eq 6 ] || return 2
    vrl_bind
    vward_routing_pipeline2 "${VWARD_ROOT_PREFIX:-}/opt/var/lib/vward/routing/journal" "$@"
)

vward_routing_live_recover() (
    umask 077
    [ "$#" -eq 2 ] || return 2
    vrl_bind
    vward_routing_pipeline_recover2 "${VWARD_ROOT_PREFIX:-}/opt/var/lib/vward/routing/journal" "$@"
)
