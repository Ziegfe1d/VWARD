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
        map) : "${vrl_map:?}";printf '%s\n' "$vrl_map" ;;
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
# vrj_* fields are set by vrj_ls/vrj_slurp (journal library).
# shellcheck disable=SC2154
vrl_path_gate() {
    # /opt itself is the existing trusted Entware mount boundary. Below it,
    # reject aliases and writable-by-others directories; never follow a reused
    # metadata leaf or accept an API-provided path as a destination.
    case $1 in
        "$vrb_e/"*|"$vrl_etc/services/"*|"$vrl_etc/device.conf"|"$vrl_etc/smartdns.conf"|\
        "$vrl_etc/route-engine/domain-lists/"*|"$vrl_etc/route-engine/domain-lists.dns/"*|\
        "${VWARD_ROOT_PREFIX:-}/opt/var/lib/vward/services/catalog.json"|\
        "${VWARD_ROOT_PREFIX:-}/opt/share/vward/console/services-catalog.json"|\
        "${VWARD_ROOT_PREFIX:-}/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh"|\
        "${VWARD_ROOT_PREFIX:-}/opt/var/lib/vward/route-engine/adaptive-persist.txt") vrl_pg_stop=${VWARD_ROOT_PREFIX:-}/opt ;;
        "${VWARD_ROOT_PREFIX:-}/tmp/"*) vrl_pg_stop=${VWARD_ROOT_PREFIX:-}/tmp ;;
        *) return 75 ;;
    esac
    case $1 in */../*|*/./*|*/..|*/.|*//*) return 75 ;; esac
    # One ls for the whole ancestor chain (was one per directory; same
    # builtin tests and allowed modes for every directory, so row order is
    # irrelevant). A newline would split a row: refuse it, as the old
    # multi-line check did. No subshell: callers only test the status.
    case $1 in *'
'*) return 75 ;; esac
    vrl_pg_parent=${1%/*};vrl_pg_n=0;set --
    while [ "$vrl_pg_parent" != "$vrl_pg_stop" ]; do
        [ -d "$vrl_pg_parent" ] && [ ! -L "$vrl_pg_parent" ] && [ -O "$vrl_pg_parent" ] || return 75
        set -- "$@" "$vrl_pg_parent";vrl_pg_n=$((vrl_pg_n+1))
        vrl_pg_parent=${vrl_pg_parent%/*}
        [ -n "$vrl_pg_parent" ] || return 75
    done
    if [ "$#" -gt 0 ]; then
        vrj_lsmodes "$@" || return 75
        [ "$vrj_lcount" = "$vrl_pg_n" ] || return 75
        for vrl_pg_m in $vrj_lmodes; do
            case $vrl_pg_m in drwx------|drwxr-xr-x|drwxr-x---|drwx--x--x) ;; *) return 75 ;; esac
        done
    fi
    [ -d "$vrl_pg_stop" ] && [ -O "$vrl_pg_stop" ]
}

vrl_refresh() {
    vrl_ready "$vrb_j" || return 75
    vrl_observation_read
}
vrl_observation_read() {
    : "${vrl_cache:?}" "${vrl_ndmc:?}"
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
vrl_dns_observe() { vrl_agh_observe; }

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
        dns-scope:keenetic) vrl_refresh && vrb_https_scope "$vrl_cache/running-config" > "$3" ;;
        dns-scope:agh) vrl_refresh && vrb_agh_scope "$vrl_cache/agh.json" > "$3" ;;
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
    if [ "$2" = group ] || [ "$2" = dns-scope ]; then
        # Use the scope from the SAME sealed G0/G1 snapshot as this journal
        # transition; another query here would be a different, unbound Gi.
        vrb_outcome_scope_hash "$1" "$2" "$3" > "$4"
    else vrb_scope_read "$2" "$3" "$vrb_t/current" && vr2_hash "$vrb_t/current" > "$4";fi
}
vrl_context() {
    [ "${vrb_inside:-}" = locked-native ] &&
        [ "$vrb_e" = "${VWARD_ROOT_PREFIX:-}/opt/var/lib/vward/routing" ] &&
        [ "$vrb_j" = "$vrb_e/journal" ] &&
        # Fixed directory shape: proven once per coordinator (memo below).
        { [ "${vrl_ready_memo:-}" = "$vrb_j|${vrj2_me:-}" ] || { vrl_ready "$vrb_j" && vrl_ready_memo="$vrb_j|${vrj2_me:-}"; }; } &&
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
    vrl_requests_quiet || return 75
    vrl_ack_call=;vrl_fresh_reuse=
    if [ "$1" = 'system configuration save' ] && [ -n "${vrb_transport_fresh:-}" ] && [ "$vrb_transport_fresh" = "$vrb_op" ]; then
        # The batch readback just verified is the pre-save observation:
        # only journal records were written since (no dispatch).
        vrb_transport_fresh=
        vrj2_file "$vrl_cache/running-config" || return 75
    else
        vrb_transport_fresh=
        vrl_refresh || return 75
    fi
    vrl_nc_save=0
    if [ "$1" = 'system configuration save' ]; then
        case $vrb_role in save|baseline-save) ;; *) return 75 ;; esac
        vrl_nc_save=1
    else
        [ "$vrb_role" != save ] && [ "$vrb_role" != baseline-save ] || return 75
        vrl_nc_scope=$(vrj2_step_row "$vrb_j/$vrb_op" "$vrb_active_step" | cut -f4,5) || return 75
        case $vrl_nc_scope in
            "$(printf 'group\t')"*)
                if [ "$vrb_role" = inverse ]; then vrl_nc_expected=$vrb_t/inverse.expected
                else vrl_nc_expected=$vrb_t/expected;fi
                vrb_native_compile "$1" "$vrl_cache/running-config" "$vrl_nc_expected" "$vrb_t" || return 75
                IFS="$(printf '\t')" read -r _vrl_kind vrl_nc_group _vrl_value _vrl_neg < "$vrb_t/native.command" || return 75
                [ "$vrl_nc_scope" = "$(printf 'group\t%s' "$vrl_nc_group")" ] || return 75 ;;
            "$(printf 'dns-scope\tkeenetic')")
                if [ "$vrb_role" = inverse ]; then vrl_nc_expected=$vrb_t/dns.inverse.expected
                else vrl_nc_expected=$vrb_t/dns.expected;fi
                vrb_native_dns_compile "$1" "$vrl_cache/running-config" "$vrl_nc_expected" "$vrb_t" || return 75 ;;
            *) return 75 ;;
        esac
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
        vrl_fresh_reuse=$vrb_op:after-save
    else
        if [ "$vrl_nc_scope" = "$(printf 'dns-scope\tkeenetic')" ]; then
            vrb_https_scope "$vrl_cache/running-config" > "$vrl_call/readback" || return 75
            vrl_nc_post=$vrb_t/dns.next
        else
            vrb_cfg_image "$vrl_cache/running-config" "$vrl_nc_group" > "$vrl_call/readback" || return 75
            vrl_nc_post=$vrb_t/native.next
        fi
        cmp -s "$vrl_call/readback" "$vrl_nc_post" &&
            vr2_hash "$vrl_call/readback" > "$vrl_call/readback.sha" || return 75
    fi
    vrb_worker_context || return 75
    printf '%s\n' acknowledged-readback > "$vrl_call/completion" &&
        vr2_hash "$vrl_call/completion" > "$vrl_call/completion.sha" && vrj2_flush || return 1
    rm -f "$vrl_call/request.pending" && vrj2_flush || return 75
    if [ "$vrl_nc_save" != 1 ] && [ "$vrl_nc_scope" != "$(printf 'dns-scope\tkeenetic')" ]; then
        vrl_ack_call=$vrl_call;vrl_ack_group=$vrl_nc_group;vrl_ack_op=$vrb_op;vrl_ack_step=$vrb_active_step
        IFS=' ' read -r vrl_ack_pid _ < /proc/self/stat || return 75
        vrl_ack_start=$(vrj2_pid_start "$vrl_ack_pid") || return 75
    fi
}
# One native batch for ONE group step (owner decision 08.11.2026), forward
# role only. No running-config read here: the coordinator's fresh read taken
# immediately before the batch is the CAS observation (its cached copy must
# still show this group at its plan pre-image), and its ONE shared readback
# after the batch is the proof (vrl_transport_complete). Every command is in
# the closed grammar of vrb_native_compile, its prefix image is bound by the
# immutable plan row, and its receipt (dispatched.<prefix>) is written by the
# leased runner immediately before that command is sent. Each ndmc child
# registers its own lease before exec, so an orphan transport stays visible to
# the quiet checks. The first refused/failed command stops the batch; its
# request stays pending (unknown, never compensated automatically).
vrl_group_batch() {
    : "${vrb_t:?}" "${vrb_write_row:?}" "${vrl_cache:?}"
    [ "$#" -eq 2 ] && [ "${vrb_role:-}" = forward ] && [ "$vrb_active_step" = "$1" ] || return 75
    vrl_gb_step=$1;vrl_gb_group=$2
    case $vrl_gb_group in domain-list[0-9]|domain-list[0-9][0-9]) ;; *) return 75 ;; esac
    vrb_worker_context && vrl_requests_quiet || return 75
    vrl_ack_call=
    vrj2_file "$vrl_cache/running-config" && vrb_single_link "$vrl_cache/running-config" || return 75
    vrb_cfg_image "$vrl_cache/running-config" "$vrl_gb_group" > "$vrb_t/current" || return 3
    cmp -s "$vrb_t/current" "$vrb_t/pre.$vrl_gb_step" || return 3
    # Ordered prefix digests from the plan row (lower2: one per command).
    vrl_gb_checks=$(printf '%s\n' "$vrb_write_row" | cut -f10) || return 3
    vrl_gb_post=$(printf '%s\n' "$vrb_write_row" | cut -f7) || return 3
    vrl_gb_prefixes=;vrl_gb_rest=$vrl_gb_checks,
    while [ -n "$vrl_gb_rest" ]; do
        vrl_gb_item=${vrl_gb_rest%%,*};vrl_gb_rest=${vrl_gb_rest#*,}
        case $vrl_gb_item in prefix:*) vrl_gb_prefixes="$vrl_gb_prefixes ${vrl_gb_item#prefix:}" ;; esac
    done
    vrl_call=$(mktemp -d "$vrb_j/$vrb_op/native.XXXXXX") || return 1
    : > "$vrl_call/command";vrl_gb_n=0;vrl_gb_left=$vrl_gb_prefixes
    while IFS="$(printf '\t')" read -r vrl_gb_k vrl_gb_g vrl_gb_v vrl_gb_a; do
        [ "$vrl_gb_g" = "$vrl_gb_group" ] || return 3
        case $vrl_gb_v in ''|*[!A-Za-z0-9_.:-]*) return 3 ;; esac
        case $vrl_gb_k:$vrl_gb_a in
            create:add) vrl_gb_c="object-group fqdn $vrl_gb_g" ;;
            delete:remove) vrl_gb_c="no object-group fqdn $vrl_gb_g" ;;
            include:add) vrl_gb_c="object-group fqdn $vrl_gb_g include $vrl_gb_v" ;;
            include:remove) vrl_gb_c="no object-group fqdn $vrl_gb_g include $vrl_gb_v" ;;
            route:add) vrl_gb_c="dns-proxy route object-group $vrl_gb_g $vrl_gb_v auto" ;;
            route:remove) vrl_gb_c="dns-proxy no route object-group $vrl_gb_g $vrl_gb_v auto" ;;
            *) return 3 ;;
        esac
        case $vrl_gb_c in *[!A-Za-z0-9_.\ :-]*) return 3 ;; esac
        [ "${#vrl_gb_c}" -le 2048 ] || return 3
        vrl_gb_left=${vrl_gb_left# };[ -n "$vrl_gb_left" ] || return 3
        vrl_gb_h=${vrl_gb_left%% *};vrl_gb_left=${vrl_gb_left#"$vrl_gb_h"}
        case $vrl_gb_h in *[!0-9a-f]*) return 3 ;; esac
        [ "${#vrl_gb_h}" -eq 64 ] || return 3
        vrl_gb_n=$((vrl_gb_n+1))
        printf '%s\t%s\n' "$vrl_gb_h" "$vrl_gb_c" >> "$vrl_call/command" || return 1
    done < "$vrb_t/commands.$vrl_gb_step"
    # Exactly one prefix per command; the last is the plan post-image.
    [ "$vrl_gb_n" -gt 0 ] && [ -z "${vrl_gb_left# }" ] && [ "$vrl_gb_h" = "$vrl_gb_post" ] || return 3
    vrb_self_admit routing-publisher || return 75
    IFS=' ' read -r vrb_pub_pid _ < /proc/self/stat || return 75
    vward_pid_start_var "$vrb_pub_pid" || return 75;vrb_pub_start=$VA_PS
    [ -e "$vrb_j/$vrb_op/workers" ] || mkdir "$vrb_j/$vrb_op/workers" || return 1
    vrj_dir "$vrb_j/$vrb_op/workers" || return 75
    # Every lease holds this boot id: one digest serves every lease of the batch.
    printf '%s\n' "$vrj2_boot" > "$vrl_call/boot" && vrl_gb_bsha=$(vr2_hash "$vrl_call/boot") || return 1
    vrl_gb_lease=$vrb_j/$vrb_op/workers/$vrj2_boot.$vrb_pub_pid.$vrb_pub_start
    printf '%s\n' "$vrj2_boot" > "$vrl_gb_lease" && printf '%s\n' "$vrl_gb_bsha" > "$vrl_gb_lease.sha" || return 1
    vrl_gb_plansha=$(cat "$vrb_j/$vrb_op/plan.sha") || return 75
    # Receipts (content fixed by issuer and prefix): staged privately and
    # digested at once, published one by one right before their command.
    mkdir "$vrl_call/receipts" || return 1
    vrl_gb_i=0
    while IFS="$(printf '\t')" read -r vrl_gb_h _vrl_gb_c; do
        vrl_gb_i=$((vrl_gb_i+1))
        printf 'dispatched\t2\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$vrb_op" "$vrl_gb_step" "$vrl_gb_h" "$vrb_pub_pid" "$vrb_pub_start" "$vrj2_boot" "$vrl_gb_plansha" > "$vrl_call/receipts/$vrl_gb_i" || return 1
    done < "$vrl_call/command"
    vrl_gb_sums=$(cd "$vrl_call/receipts" && LC_ALL=C sha256sum $(vrl_gb_seq "$vrl_gb_n")) || return 1
    vr2_hash "$vrl_call/command" > "$vrl_call/command.sha" &&
        printf '%s\n' "$vrb_t/post.$vrl_gb_step" > "$vrl_call/expected.path" &&
        cp "$vrb_t/post.$vrl_gb_step" "$vrl_call/expected" &&
        printf '%s\t%s\n' group "$vrl_gb_group" > "$vrl_call/scope" &&
        printf '%s\n' pending > "$vrl_call/request.pending" && vrj2_flush || return 1
    vrb_worker_context || return 75
    vrl_gb_i=0;vrl_gb_sent=0
    while IFS="$(printf '\t')" read -r vrl_gb_h vrl_gb_c; do
        vrl_gb_i=$((vrl_gb_i+1))
        vrl_gb_sl=${vrl_gb_sums%%"$vrj_nl"*};vrl_gb_sums=${vrl_gb_sums#"$vrl_gb_sl"};vrl_gb_sums=${vrl_gb_sums#"$vrj_nl"}
        [ "${vrl_gb_sl#*  }" = "$vrl_gb_i" ] || return 75
        vrl_gb_rsha=${vrl_gb_sl%%  *}
        case $vrl_gb_rsha in *[!0-9a-f]*) return 75 ;; esac
        [ "${#vrl_gb_rsha}" -eq 64 ] || return 75
        vrl_gb_receipt=$vrb_j/$vrb_op/step.$vrl_gb_step/dispatched.$vrl_gb_h
        [ ! -e "$vrl_gb_receipt" ] && [ ! -L "$vrl_gb_receipt" ] && [ ! -e "$vrl_gb_receipt.sha" ] && [ ! -L "$vrl_gb_receipt.sha" ] || return 75
        vrb_worker_context || return 75
        while IFS= read -r vrl_gb_line; do printf '%s\n' "$vrl_gb_line"; done < "$vrl_call/receipts/$vrl_gb_i" > "$vrl_gb_receipt" &&
            printf '%s\n' "$vrl_gb_rsha" > "$vrl_gb_receipt.sha" || return 1
        printf '%s\n' "$vrl_gb_i" > "$vrl_call/sent" || return 1
        vrl_gb_rc=0
        (
            IFS=' ' read -r vrl_gc_pid _ < /proc/self/stat || exit 75
            vward_pid_start_var "$vrl_gc_pid" || exit 75
            printf '%s\n' "$vrj2_boot" > "$vrb_j/$vrb_op/workers/$vrj2_boot.$vrl_gc_pid.$VA_PS" &&
                printf '%s\n' "$vrl_gb_bsha" > "$vrb_j/$vrb_op/workers/$vrj2_boot.$vrl_gc_pid.$VA_PS.sha" || exit 75
            [ ! -e "$VWARD_ROOT_PREFIX/tmp/vward-update-requested" ] && [ ! -L "$VWARD_ROOT_PREFIX/tmp/vward-update-requested" ] &&
                [ ! -e "$VWARD_ROOT_PREFIX/tmp/vward-update.lock" ] && [ ! -L "$VWARD_ROOT_PREFIX/tmp/vward-update.lock" ] || exit 75
            exec "$vrl_ndmc" -c "$vrl_gb_c"
        ) > "$vrl_call/stdout.$vrl_gb_i" 2> "$vrl_call/stderr.$vrl_gb_i" || vrl_gb_rc=$?
        # A failed/lost reply is UNKNOWN even if the readback later matches:
        # stop here, keep the request pending, never replay or compensate.
        [ "$vrl_gb_rc" = 0 ] && ! grep -Eqi '(^|[^a-z])(error|failed|invalid|unknown command)([^a-z]|$)' "$vrl_call/stdout.$vrl_gb_i" "$vrl_call/stderr.$vrl_gb_i" || return 75
        vrl_gb_sent=$vrl_gb_i
    done < "$vrl_call/command"
    [ "$vrl_gb_sent" = "$vrl_gb_n" ] || return 75
    printf '%s\n' sent-ok > "$vrl_call/status" && vrj2_flush || return 1
}
vrl_gb_seq() { vrl_gs_i=0;while [ "$vrl_gs_i" -lt "$1" ]; do vrl_gs_i=$((vrl_gs_i+1));printf '%s\n' "$vrl_gs_i";done; }
# Resolve every batch request of this operation from the coordinator's ONE
# shared readback FRESH (a sealed stage): a batch whose every command was
# acknowledged (status sent-ok) and whose group now equals its expected plan
# image gets the acknowledged-readback completion and leaves pending. Anything
# else stays pending: the requests are then not quiet and the step unknown.
vrl_transport_complete() {
    [ "$#" -eq 1 ] && vr2_stage_valid "$1" || return 75
    for vrl_tc_call in "$vrb_j/$vrb_op"/native.*; do
        [ -d "$vrl_tc_call" ] && [ ! -L "$vrl_tc_call" ] || continue
        [ -e "$vrl_tc_call/request.pending" ] && [ -e "$vrl_tc_call/scope" ] || continue
        vrj2_file "$vrl_tc_call/status" && vrj2_file "$vrl_tc_call/scope" && vrj2_file "$vrl_tc_call/expected" || continue
        [ "$(cat "$vrl_tc_call/status")" = sent-ok ] || continue
        [ "$(vr2_hash "$vrl_tc_call/command")" = "$(cat "$vrl_tc_call/command.sha")" ] || continue
        IFS="$(printf '\t')" read -r vrl_tc_kind vrl_tc_group < "$vrl_tc_call/scope" || continue
        [ "$vrl_tc_kind" = group ] || continue
        vrb_cfg_image "$1/native.cfg" "$vrl_tc_group" > "$vrl_tc_call/readback" || continue
        cmp -s "$vrl_tc_call/readback" "$vrl_tc_call/expected" || continue
        vr2_hash "$vrl_tc_call/readback" > "$vrl_tc_call/readback.sha" &&
            printf '%s\n' acknowledged-readback > "$vrl_tc_call/completion" &&
            vr2_hash "$vrl_tc_call/completion" > "$vrl_tc_call/completion.sha" && vrj2_flush || return 1
        rm -f "$vrl_tc_call/request.pending" || return 75
    done
    vrj2_flush
}
vrl_requests_quiet() {
    for vrl_rq_request in "$vrb_j/$vrb_op"/native.*/request.pending \
        "$vrb_j/$vrb_op"/dns-evidence/*/request.pending \
        "$vrb_j/$vrb_op"/dns-inverse.*/evidence/request.pending; do
        [ ! -e "$vrl_rq_request" ] && [ ! -L "$vrl_rq_request" ] && continue
        # Inside ONE batch only: an own group batch whose every command was
        # acknowledged waits for the coordinator's shared readback. Any other
        # unresolved request (failed/lost, per-command, DNS) is not quiet.
        [ "${vrb_batch_mode:-}" = 1 ] && vrl_rq_batch_acked "${vrl_rq_request%/request.pending}" || return 75
    done
}
vrl_rq_batch_acked() {
    case $1 in "$vrb_j/$vrb_op"/native.*) ;; *) return 1 ;; esac
    [ -d "$1" ] && [ ! -L "$1" ] && vrj2_file "$1/scope" && vrj2_file "$1/status" || return 1
    vrj_slurp "$1/status";[ "$vrj_sv" = sent-ok ]
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
    vrj2_release || :
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
    # Forward admission belongs to the actual pipeline/server/migration entry:
    # each checks journal2_gate BEFORE plan/state/native writes. Repeating that
    # global gate here would also prevent explicit own recovery from inspecting
    # an unknown operation. Lock reclaim/worker/updater quiet checks are separate.
    vrl_cache=$(mktemp -d "${VWARD_ROOT_PREFIX:-}/tmp/vward-routing-live.XXXXXX") || return 1
    vrj_dir "$vrl_cache" || return 75
    # Per-request seal memo in this coordinator's private cache (see
    # vr2_seal_valid): removed with the cache, never shared between requests.
    : > "$vrl_cache/.seal-memo" || return 1
    vr2_seal_memo=$vrl_cache/.seal-memo
    VWARD_KCACHE=$vrl_cache;RUNCFG=$vrl_cache/running-config
    VWARD_CONSOLE_ETC=$vrl_etc
    VWARD_ROUTING_AGH_IMAGE=$vrl_cache/agh.json
    VWARD_ROUTING_AGH_DOMAINS=$vrl_cache/agh-domains
    vrl_map=${VWARD_ROOT_PREFIX:-}/tmp/vward-device-map.tsv
    VWARD_DEVICE_MAP_CACHE=$vrl_map
    export VWARD_KCACHE RUNCFG VWARD_CONSOLE_ETC VWARD_ROUTING_AGH_IMAGE VWARD_ROUTING_AGH_DOMAINS VWARD_DEVICE_MAP_CACHE
    if [ "${3:-}" = bootstrap ]; then vrl_init_root || return 75;fi
    vrb_revocations_gate "$vrb_j" "$vrb_e/decision" || return 75
}

vrl_cold_map_bind() {
    : "${vrl_cache:?}"
    # A surviving discovery may write only this unique private observation.
    # It has no shared-map publication authority or mutable request path.
    vrl_map=$vrl_cache/device-map.tsv
    VWARD_DEVICE_MAP_CACHE=$vrl_map
    export VWARD_DEVICE_MAP_CACHE
}

vrl_map_prepare() {
    vrl_mp_map=$(vrl_legacy_source map) || return 75
    if [ ! -e "$vrl_mp_map" ] && [ ! -L "$vrl_mp_map" ]; then
        # The existing discovery writes only a unique private RAM observation;
        # a child surviving its parent cannot replace a newer shared map.
        vrb_data_ancestry "$vrl_mp_map" || return 75
        vrl_cold_map_bind || return 75
        vrl_mp_map=$(vrl_legacy_source map) || return 75
        (vward_device_map >/dev/null) || return 75
    fi
    [ -f "$vrl_mp_map" ] && [ ! -L "$vrl_mp_map" ] && [ -O "$vrl_mp_map" ] && [ -r "$vrl_mp_map" ] || return 75
    # Public interface-map data may be0644; other users cannot supply its bytes.
    # shellcheck disable=SC2012
    case $(ls -ldn "$vrl_mp_map" | awk '{print substr($1,1,10)}') in
        -rw-------|-r--------|-rw-r--r--|-r--r--r--) ;; *) return 75 ;;
    esac
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
    vrb_transport_refresh() {
        # The read vrl_native_ndm took right after this operation's save is
        # the post-save observation; nothing was dispatched since.
        if [ -n "${vrl_fresh_reuse:-}" ] && [ "$vrl_fresh_reuse" = "$vrb_op:after-save" ]; then vrl_fresh_reuse=;return 0;fi
        vrl_fresh_reuse=;vrl_refresh
    }
    vrb_group_batch() { vrl_group_batch "$@"; }
    vrb_converged_record() { vrl_converged_record "$@"; }
    vrb_transport_complete() { vrl_transport_complete "$@"; }
    vrb_transport_saved() { vrl_saved; }
    vrb_agh_path() { printf '%s/agh.json\n' "$vrl_cache"; }
    vrb_agh_session() { vrl_agh_session "$@"; }
    vrb_scope_derived_deltas() { vrl_agh_derived_deltas "$@"; }
    vrb_transport_requests_quiet() { vrl_requests_quiet; }
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

# Repeat fast path (owner decision 08.11.2026: "повтор без изменений — сравнить
# нужно с есть и выйти без журнала и записи"). A convergence receipt
# ROOT/.converged is written ONLY by the full coordinator, under EDIT/CHANGE,
# after it PROVED for one exact request that the same request on generation G
# plans no step (a full-path "unchanged", or a verified commit whose own
# re-plan on its readback is empty and which touched no compiled input). A
# later identical request answers "unchanged" read-only when ALL hold:
#   the same request and the same installed code; no updater barrier; the
#   journal holds exactly the operations it held then (a new/unknown/pending
#   operation, ours or foreign, always takes the full path); a fresh native
#   read + AGH observation + the strict fingerprint of every planner input
#   give G again; the observed tunnel health equals the stored context.
# G covers native config, decision files, profile/map/catalog/categories,
# proofs, legacy recovery evidence and probe freshness; equal G means the
# strict snapshot and therefore the deterministic plan are the same. Anything
# unproven (missing/altered receipt, read failure) silently takes the full
# path, which keeps every lock, CAS and journal guard. Nothing is written here
# except a private RAM scratch directory that is removed.
vrl_converged_code() {
    vrl_cc_lib=${VWARD_ROOT_PREFIX:-}/opt/lib/vward
    vrl_cc_sum=$(LC_ALL=C sha256sum "$vrl_cc_lib"/*.sh "$vrl_cc_lib/routing-capabilities.tsv" "$0" 2>/dev/null | sha256sum) || return 1
    vrl_cc_sum=${vrl_cc_sum%% *}
    case $vrl_cc_sum in *[!0-9a-f]*|'') return 1 ;; esac
    [ "${#vrl_cc_sum}" -eq 64 ] || return 1
    printf '%s\n' "$vrl_cc_sum"
}
vrl_converged_journal() {
    vrl_cj=
    for vrl_cj_op in "$1"/*; do
        [ -e "$vrl_cj_op" ] || [ -L "$vrl_cj_op" ] || continue
        vrl_cj_name=${vrl_cj_op##*/}
        vrj2_id "$vrl_cj_name" || return 1
        vrl_cj="$vrl_cj$vrl_cj_name "
    done
    printf '%s\n' "$vrl_cj"
}
# Observed tunnel health in compiled-context form (sorted VPN: rows).
vrl_converged_health() {
    vrl_ch_dev=$1;vrl_ch_map=$2
    vrl_ch_wan=$(awk -F= '$1=="VWARD_WAN_DEVICE"{if(++n>1)exit 2;print $2}' "$vrl_ch_dev") || return 1
    vrl_ch_wan_name=$(awk -F= '$1=="VWARD_WAN_INTERFACE"{if(++n>1)exit 2;print $2}END{if(n!=1)exit 2}' "$vrl_ch_dev") || return 1
    vward_valid_ndm_name "$vrl_ch_wan_name" || return 1
    vrj_slurp "$vrl_ch_map";vrl_ch_mapv=$vrj_sv
    vrl_ch_vpns=$(vward_map_vpns "$vrl_ch_mapv" "$vrl_ch_wan" | awk -v wan="$vrl_ch_wan_name" '$1!=wan') || return 1
    vrl_ch_rows=;vrl_ch_n=0
    while read -r vrl_ch_vpn _vrl_ch_kernel; do
        [ -n "$vrl_ch_vpn" ] || continue
        vrl_ch_n=$((vrl_ch_n+1));[ "$vrl_ch_n" -le 128 ] || return 1
        vrl_ch_state=$(vrl_interface_observe "$vrl_ch_vpn") || return 1
        vrl_ch_rows="${vrl_ch_rows}VPN:$vrl_ch_vpn$vrj_tab$vrl_ch_state$vrj_nl"
    done <<VRLCH
$vrl_ch_vpns
VRLCH
    printf '%s' "$vrl_ch_rows" | LC_ALL=C sort
}
vrl_converged_try() (
    umask 077
    [ "$#" -eq 4 ] || return 1
    : "${vrl_root:?}" "${vrl_etc:?}"
    vrl_cv=$vrl_root/.converged
    [ -f "$vrl_cv" ] && [ ! -L "$vrl_cv" ] && [ -O "$vrl_cv" ] && vrj2_file "$vrl_cv" && vrb_single_link "$vrl_cv" || return 1
    [ ! -e "${VWARD_ROOT_PREFIX:-}/tmp/vward-update-requested" ] && [ ! -L "${VWARD_ROOT_PREFIX:-}/tmp/vward-update-requested" ] &&
        [ ! -e "${VWARD_ROOT_PREFIX:-}/tmp/vward-update.lock" ] && [ ! -L "${VWARD_ROOT_PREFIX:-}/tmp/vward-update.lock" ] || return 1
    vrl_cv_n=0;vrl_cv_req=;vrl_cv_gen=;vrl_cv_jr=;vrl_cv_code=;vrl_cv_out=;vrl_cv_head=
    while IFS="$vrj_tab" read -r vrl_cv_k vrl_cv_a vrl_cv_b vrl_cv_c vrl_cv_d vrl_cv_e vrl_cv_f; do
        vrl_cv_n=$((vrl_cv_n+1))
        case $vrl_cv_n:$vrl_cv_k in
            1:converged) [ "$vrl_cv_a" = 1 ] && [ -z "$vrl_cv_b$vrl_cv_c$vrl_cv_d$vrl_cv_e$vrl_cv_f" ] || return 1;vrl_cv_head=1 ;;
            2:request) [ -z "$vrl_cv_e$vrl_cv_f" ] || return 1;vrl_cv_req="$vrl_cv_a|$vrl_cv_b|$vrl_cv_c|$vrl_cv_d" ;;
            3:generation) [ -z "$vrl_cv_b" ] && vrj2_gen "$vrl_cv_a" || return 1;vrl_cv_gen=$vrl_cv_a ;;
            4:journal) [ -z "$vrl_cv_b" ] || return 1;vrl_cv_jr=$vrl_cv_a ;;
            5:code) [ -z "$vrl_cv_b" ] || return 1;vrl_cv_code=$vrl_cv_a ;;
            6:outcome) [ "$vrl_cv_a" = unchanged ] && [ "$vrl_cv_b:$vrl_cv_c:$vrl_cv_d" = configured:verified:false ] &&
                    [ "$vrl_cv_e" = native ] && [ -z "$vrl_cv_f" ] || return 1
                vrl_cv_out="outcome$vrj_tab$vrl_cv_a$vrj_tab$vrl_cv_b$vrj_tab$vrl_cv_c$vrj_tab$vrl_cv_d$vrj_tab$vrl_cv_e" ;;
            *) return 1 ;;
        esac
    done < "$vrl_cv"
    [ "$vrl_cv_n" = 6 ] && [ -n "$vrl_cv_head" ] && [ -n "$vrl_cv_out" ] || return 1
    [ "$vrl_cv_req" = "$1|$2|$3|$4" ] || return 1
    [ "$(vrl_converged_journal "$vrl_root/journal")" = "$vrl_cv_jr " ] || return 1
    [ "$(vrl_converged_code)" = "$vrl_cv_code" ] || return 1
    vrl_map=${VWARD_ROOT_PREFIX:-}/tmp/vward-device-map.tsv
    [ -f "$vrl_map" ] && [ ! -L "$vrl_map" ] && [ -O "$vrl_map" ] && [ -r "$vrl_map" ] || return 1
    vrl_ndmc=${NDMC:-${VWARD_NDMC:-ndmc}}
    command -v "$vrl_ndmc" >/dev/null 2>&1 || return 1
    vrl_cache=$(mktemp -d "${VWARD_ROOT_PREFIX:-}/tmp/vward-routing-converged.XXXXXX") || return 1
    trap 'rm -rf "$vrl_cache"' EXIT
    vrj_dir "$vrl_cache" || return 1
    # Same observation binding as the coordinator envelope (vrl_envelope).
    VWARD_KCACHE=$vrl_cache;RUNCFG=$vrl_cache/running-config;VWARD_CONSOLE_ETC=$vrl_etc
    VWARD_ROUTING_AGH_IMAGE=$vrl_cache/agh.json;VWARD_ROUTING_AGH_DOMAINS=$vrl_cache/agh-domains
    VWARD_DEVICE_MAP_CACHE=$vrl_map
    export VWARD_KCACHE RUNCFG VWARD_CONSOLE_ETC VWARD_ROUTING_AGH_IMAGE VWARD_ROUTING_AGH_DOMAINS VWARD_DEVICE_MAP_CACHE
    vrl_observation_read || return 1
    mkdir "$vrl_cache/fp" || return 1
    vward_routing_fingerprint_read2 "$vrl_cache/fp" "$vrl_root/decision" > "$vrl_cache/fp.status" || return 1
    vrj_slurp "$vrl_cache/fp/generation";[ "$vrj_sv" = "$vrl_cv_gen" ] || return 1
    vrl_cv_health=$(vrl_converged_health "$vrl_etc/device.conf" "$vrl_map") || return 1
    vrl_cv_ctx=;vrl_cv_line=
    while IFS= read -r vrl_cv_line || [ -n "$vrl_cv_line" ]; do
        case $vrl_cv_line in VPN:*) vrl_cv_ctx="$vrl_cv_ctx$vrl_cv_line$vrj_nl" ;; esac
    done < "$vrl_root/decision/context.tsv"
    [ "$vrl_cv_health" = "${vrl_cv_ctx%"$vrj_nl"}" ] || return 1
    # The journal is re-listed last: an operation that started meanwhile wins.
    [ "$(vrl_converged_journal "$vrl_root/journal")" = "$vrl_cv_jr " ] || return 1
    printf '%s\n' "$vrl_cv_out"
)
# Called by the full coordinator, under EDIT/CHANGE, at the end of a request:
# SID MODE TARGET DNS STAGE PLAN RESULT. STAGE is the verified final stage, PLAN
# the executed (lowered) plan, RESULT unchanged|committed. Any doubt writes no
# receipt and removes an old one (the next repeat then takes the full path).
vrl_converged_record() {
    [ "$#" -eq 7 ] || return 0
    vrl_cr=$vrl_root/.converged
    vrl_cr_ok=0
    if [ "${vrl_inputs_unchanged:-0}" = 1 ] && vr2_stage_valid "$5" && vrj2_file "$6"; then
        case $7 in
            unchanged) ! grep -q '^step' "$6" && vrl_cr_ok=1 ;;
            committed)
                # Own re-plan on the readback is empty (outcome model known,
                # configured verified) and no compiled input was written.
                if vrj2_file "${6%/plan}/outcome.json" &&
                    "${JQ:-jq}" -e '.operation.state=="committed" and (.configured.state=="verified" or .configured.state=="mixed")' "${6%/plan}/outcome.json" >/dev/null 2>&1 &&
                    awk -F'\t' '$1=="step" && !($4=="group" || $4=="nativeproof" || $4=="registry" || ($4=="manifest" && ($5=="resources" || $5=="proofs" || $5=="choices"))){bad=1}END{exit bad?1:0}' "$6"; then
                    vrl_cr_ok=1
                fi ;;
        esac
    fi
    if [ "$vrl_cr_ok" != 1 ]; then rm -f "$vrl_cr" 2>/dev/null;return 0;fi
    vrl_cr_gen=$(cat "$5/generation") && vrj2_gen "$vrl_cr_gen" || { rm -f "$vrl_cr";return 0; }
    vrl_cr_jr=$(vrl_converged_journal "$vrl_root/journal") || { rm -f "$vrl_cr";return 0; }
    vrl_cr_code=$(vrl_converged_code) || { rm -f "$vrl_cr";return 0; }
    case "$1$2$3$4" in *"$vrj_tab"*|*"$vrj_nl"*) rm -f "$vrl_cr";return 0 ;; esac
    vrl_cr_tmp=$vrl_cr.tmp.$$
    if ! { printf 'converged\t1\n';printf 'request\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4"
           printf 'generation\t%s\n' "$vrl_cr_gen";printf 'journal\t%s\n' "${vrl_cr_jr% }"
           printf 'code\t%s\n' "$vrl_cr_code";printf 'outcome\tunchanged\tconfigured\tverified\tfalse\tnative\n'; } > "$vrl_cr_tmp" ||
       ! mv -f "$vrl_cr_tmp" "$vrl_cr"; then rm -f "$vrl_cr_tmp" "$vrl_cr" 2>/dev/null;fi
    return 0
}
