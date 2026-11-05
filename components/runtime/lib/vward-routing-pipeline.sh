#!/bin/sh
# B execution rehearsal ONLY. Functions, no entrypoint or installed caller.
# The ONLY transport is the fixed built-in DATA emulator below. No executable
# path from API/environment, no native CLI invocation, no production permission.
# JDIR/.emu owns running.cfg, decision/, services/, and all fault files. Loading
# this library cannot enable a writer. Even poisoned NDMC/curl are never called.

vrb_legacy_gate() (
    # Recovery is an admission barrier, not an optional M/S/A contribution.
    # Never repair/replay another controller's transaction from this path.
    for vrb_legacy_dir in "$1/backup" "$1/backup/service-transactions" "$1/backup-recovery"; do
        if [ -e "$vrb_legacy_dir" ] || [ -L "$vrb_legacy_dir" ]; then
            [ -d "$vrb_legacy_dir" ] && [ ! -L "$vrb_legacy_dir" ] &&
                [ -r "$vrb_legacy_dir" ] && [ -x "$vrb_legacy_dir" ] || return 75
        fi
    done
    for vrb_legacy_item in "$1/backup/service-transactions"/* "$1/backup-recovery"/smartdns.*; do
        [ ! -e "$vrb_legacy_item" ] && [ ! -L "$vrb_legacy_item" ] || return 75
    done
)

vrb_worker_context() {
    [ "${vrb_inside:-}" = locked-emulator ] && vrj_dir "$vrb_j" &&
        vrb_data_ancestry "$vrb_edit_path/owner" && vrb_data_ancestry "$vrb_change_path/owner" &&
        vrj2_ready "$vrb_j" "$vrb_op" &&
        { [ "$(cat "$vrb_j/$vrb_op/state")" = pending ] || [ "$(cat "$vrb_j/$vrb_op/state")" = unknown ]; } &&
        [ "$(cat "$vrb_edit_path/owner" 2>/dev/null)" = "$(printf '%s\t%s\t%s' "${vrj2_me:-}" "${vrj2_start:-}" "${vrj2_boot:-}")" ] &&
        [ "$(cat "$vrb_change_path/owner" 2>/dev/null)" = "$(printf '%s\t%s\t%s' "${vrj2_me:-}" "${vrj2_start:-}" "${vrj2_boot:-}")" ] &&
        [ "$(vr2_hash "$vrb_edit_path/owner")" = "$(cat "$vrb_edit_path/owner.sha")" ] &&
        [ "$(vr2_hash "$vrb_change_path/owner")" = "$(cat "$vrb_change_path/owner.sha")" ] &&
        [ "$(vward_lock_boot_id "$vrb_edit_path/boot")" = "${vrj2_boot:-}" ] &&
        [ "$(vward_lock_boot_id "$vrb_change_path/boot")" = "${vrj2_boot:-}" ] &&
        [ "$(cat /proc/sys/kernel/random/boot_id)" = "${vrj2_boot:-}" ] &&
        vlg_boot="$vrj2_boot" vward_lock_gate_live "$vrj2_boot.$vrj2_me.$vrj2_start" &&
        [ "$(cat "$vrb_coord_slot/pid" 2>/dev/null)" = "${vrj2_me:-}" ] &&
        [ "$(cat "$vrb_coord_slot/pid_start" 2>/dev/null)" = "${vrj2_start:-}" ] &&
        [ ! -e "$VWARD_ROOT_PREFIX/tmp/vward-update-requested" ] && [ ! -L "$VWARD_ROOT_PREFIX/tmp/vward-update-requested" ] &&
        [ ! -e "$VWARD_ROOT_PREFIX/tmp/vward-update.lock" ] && [ ! -L "$VWARD_ROOT_PREFIX/tmp/vward-update.lock" ] &&
        vrb_legacy_gate "$vrb_e" || return 75
    case ${vrb_role:-} in
        forward)
            [ "$(cat "$vrb_j/$vrb_op/state")" = pending ] &&
                [ "$(cat "$vrb_j/$vrb_op/step.$vrb_active_step/state" 2>/dev/null)" = pending ] ;;
        inverse)
            [ "$(cat "$vrb_j/$vrb_op/step.$vrb_active_step/state" 2>/dev/null)" = compensating ] ;;
        save) [ "$(cat "$vrb_j/$vrb_op/state")" = pending ] && [ "$(cat "$vrb_j/$vrb_op/save" 2>/dev/null)" = pending ] ;;
        baseline-save) [ "$(cat "$vrb_j/$vrb_op/rollback-save" 2>/dev/null)" = pending ] ;;
        *) return 75 ;;
    esac
}

# Same two-phase updater admission record as the existing library, but the
# kernel PID of this coordinator/publisher rather than POSIX $$ of its parent.
# Registration is called directly (never through command substitution).
vrb_self_admit() {
    case $1 in routing-coordinator|routing-publisher) ;; *) return 2 ;; esac
    vrb_sa_root=${VWARD_ROOT_PREFIX:?}/tmp
    vrb_data_ancestry "$vrb_sa_root/vward-runtime-active/lease" || return 75
    [ ! -e "$vrb_sa_root/vward-update-requested" ] && [ ! -L "$vrb_sa_root/vward-update-requested" ] &&
        [ ! -e "$vrb_sa_root/vward-update.lock" ] && [ ! -L "$vrb_sa_root/vward-update.lock" ] || return 75
    vrj_dir "$vrb_sa_root/vward-runtime-active" || return 75
    IFS=' ' read -r vrb_sa_pid _ < /proc/self/stat || return 1
    vrb_sa_start=$(vrj2_pid_start "$vrb_sa_pid") || return 1
    vrb_registered_slot=$vrb_sa_root/vward-runtime-active/$1.$vrb_sa_pid.$vrb_sa_start
    mkdir "$vrb_registered_slot" || return 75
    printf '%s\n' "$vrb_sa_pid" > "$vrb_registered_slot/pid" &&
        printf '%s\n' "$vrb_sa_start" > "$vrb_registered_slot/pid_start" &&
        printf '%s\n' "$1" > "$vrb_registered_slot/component" || return 1
    if [ -e "$vrb_sa_root/vward-update-requested" ] || [ -L "$vrb_sa_root/vward-update-requested" ] ||
       [ -e "$vrb_sa_root/vward-update.lock" ] || [ -L "$vrb_sa_root/vward-update.lock" ]; then
        vrb_self_leave "$vrb_registered_slot" || return 1
        return 75
    fi
}
vrb_self_leave() {
    vrb_data_ancestry "$1/pid" || return 75
    vrj_dir "$1" || return 75
    IFS=' ' read -r vrb_sd_pid _ < /proc/self/stat || return 1
    vrb_sd_start=$(vrj2_pid_start "$vrb_sd_pid") || return 1
    [ "$(cat "$1/pid")" = "$vrb_sd_pid" ] && [ "$(cat "$1/pid_start")" = "$vrb_sd_start" ] || return 75
    rm -f "$1/pid" "$1/pid_start" "$1/component" && rmdir "$1"
}
vrb_reap_publisher_slots() (
    for vrb_rs_slot in "${VWARD_ROOT_PREFIX:?}/tmp/vward-runtime-active"/routing-publisher.*; do
        [ ! -e "$vrb_rs_slot" ] && [ ! -L "$vrb_rs_slot" ] && continue
        vrj_dir "$vrb_rs_slot" && vrj2_file "$vrb_rs_slot/pid" && vrj2_file "$vrb_rs_slot/pid_start" && vrj2_file "$vrb_rs_slot/component" || return 75
        vrb_rs_pid=$(cat "$vrb_rs_slot/pid");vrb_rs_start=$(cat "$vrb_rs_slot/pid_start")
        case $vrb_rs_pid:$vrb_rs_start in *[!0-9:]*|:*|*:) return 75 ;; esac
        [ "${vrb_rs_slot##*/}" = "routing-publisher.$vrb_rs_pid.$vrb_rs_start" ] &&
            [ "$(cat "$vrb_rs_slot/component")" = routing-publisher ] || return 75
        vrb_rs_live=$(vrj2_pid_start "$vrb_rs_pid") || vrb_rs_live=
        if kill -0 "$vrb_rs_pid" 2>/dev/null && { [ -z "$vrb_rs_live" ] || [ "$vrb_rs_live" = "$vrb_rs_start" ]; }; then continue;fi
        vrb_rs_old=$vrb_rs_slot.reap.$vrj2_me
        [ ! -e "$vrb_rs_old" ] && [ ! -L "$vrb_rs_old" ] || return 75
        mv "$vrb_rs_slot" "$vrb_rs_old" || return 75
        rm -f "$vrb_rs_old/pid" "$vrb_rs_old/pid_start" "$vrb_rs_old/component" && rmdir "$vrb_rs_old" || return 75
    done
)

# A final DATA publisher is the leased process itself (exec, no untracked mv
# child). A dead operation cannot leave a child able to publish after recovery.
# Durable intent remains after death; quiet checks never infer death from PID
# alone. This certifies DATA publication, not completion of a remote transport.
vrb_single_link() {
    # Only the numeric metadata field is read; filename text is never parsed.
    # Keenetic's stat may lack -c, whereas ls -ldn is supported on both stores.
    # shellcheck disable=SC2012
    [ "$(LC_ALL=C ls -ldn "$1" | awk '{print $2}')" = 1 ]
}
# Only numeric mode/owner metadata is parsed; filename bytes are not fields.
# shellcheck disable=SC2012
vrb_owned_data_file() {
    if [ "$1" = "$vrb_e/services/enabled.tsv" ]; then
        [ -f "$1" ] && [ ! -L "$1" ] && [ -O "$1" ] && [ -r "$1" ] || return 75
        # Registry contains public IDs/targets. Only this exact legacy file
        # accepts 0644; private proofs/URLs/decision files remain private.
        case $(ls -ldn "$1" | awk '{print substr($1,1,10)}') in -rw-------|-r--------|-rw-r--r--) ;; *) return 75 ;; esac
        [ "$(wc -c < "$1")" -le 1048576 ]
    else vrj2_file "$1";fi
}
# shellcheck disable=SC2012
vrb_publication_mode() (
    vrb_pm_dest=$1
    case $vrb_pm_dest in
        "$vrb_e/running.cfg") vrb_pm_label=cfg ;;
        "$vrb_e/agh.json") vrb_pm_label=obs-agh-image ;;
        "$vrb_e/services/enabled.tsv") vrb_pm_label=enabled ;;
        "$vrb_e/services/owned/"*) vrb_pm_label=owned:${vrb_pm_dest##*/} ;;
        "$vrb_e/route-engine/domain-lists/"*) vrb_pm_label=list:${vrb_pm_dest##*/} ;;
        "$vrb_e/route-engine/domain-lists.dns/"*) vrb_pm_label=obs-dnsproof:${vrb_pm_dest##*/} ;;
        "$vrb_e/smartdns.conf") vrb_pm_label=obs-smartdns-profile ;;
        "$vrb_e/decision/"*.tsv) vrb_pm_key=${vrb_pm_dest##*/};vrb_pm_label=v2-${vrb_pm_key%.tsv} ;;
        "$vrb_e/saved.cfg")
            case ${vrb_role:-} in save|baseline-save) ;; *) return 75 ;; esac
            if [ -e "$1" ] || [ -L "$1" ]; then
                vrj2_file "$1" && [ "$(ls -ldn "$1" | awk '{print substr($1,1,10)}')" = -rw------- ] || return 75
            fi
            printf '%s\n' 0600;return 0 ;;
        *) return 75 ;;
    esac
    vrj2_file "$vrb_t/inputs.fp" || return 75
    vrb_pm_hash=$(vr2_hash "$vrb_t/inputs.fp") || return 75
    vrj2_step_row "$vrb_j/$vrb_op" "$vrb_active_step" | awk -F'\t' -v h="$vrb_pm_hash" '
        {n=split($10,a,",");for(i=1;i<=n;i++)if(a[i]=="attrs:" h)ok=1}END{exit ok?0:1}' || return 75
    vrb_pm_old=$(awk -v l="$vrb_pm_label" '$1==l {
        if(NF==7)print $6 " " $7;else if($2=="absent")print "absent";else exit 2;n++}
        END{if(n>1)exit 2;if(!n)print "absent"}' "$vrb_t/inputs.fp") || return 75
    vrb_pm_current=absent
    if [ -e "$1" ] || [ -L "$1" ]; then
        vrb_owned_data_file "$1" && vrb_single_link "$1" || return 75
        vrb_pm_current=$(ls -ldn "$1" | awk '{print substr($1,1,10),$3}') || return 75
    fi
    vrb_pm_uid=$(id -u) || return 75
    if [ "$vrb_pm_old" = absent ]; then
        if [ "$vrb_pm_current" != absent ]; then
            [ "$vrb_role" = inverse ] && [ "$vrb_pm_current" = "-rw------- $vrb_pm_uid" ] || return 75
        fi
        printf '%s\n' 0600;return 0
    fi
    case $vrb_pm_old in
        "-rw------- $vrb_pm_uid") vrb_pm_mode=0600 ;;
        "-r-------- $vrb_pm_uid") vrb_pm_mode=0400 ;;
        "-rw-r--r-- $vrb_pm_uid") [ "$vrb_pm_label" = enabled ] || return 75;vrb_pm_mode=0644 ;;
        *) return 75 ;;
    esac
    if [ "$vrb_pm_current" = absent ]; then
        [ "$vrb_role" = inverse ] || return 75
        if [ "$(cat "$vrb_t/post.$vrb_active_step")" != - ]; then
            # A sealed state-set deletion authorizes restoration of this exact
            # absent leaf; it does not authorize creating any other file.
            vrb_state_step_valid "$vrb_t" "$vrb_j/$vrb_op" "$vrb_active_step" &&
                awk -F'\t' -v k="${vrb_pm_label#v2-}" '$1==k&&$2=="-"{ok=1}END{exit ok?0:1}' "$vrb_t/state/post" || return 75
        fi
    else [ "$vrb_pm_current" = "$vrb_pm_old" ] || return 75;fi
    printf '%s\n' "$vrb_pm_mode"
)
vrb_target_hash() {
    if [ ! -e "$1" ] && [ ! -L "$1" ]; then printf '%s\n' - | sha256sum | awk '{print $1}'
    else vrb_owned_data_file "$1" && vrb_single_link "$1" && vr2_hash "$1";fi
}
vrb_capture_image() (
    [ "$#" -eq 2 ] && vrj_dir "${2%/*}" && vrb_owned_data_file "$1" && vrb_single_link "$1" || return 75
    vrb_ci_hash=$(vr2_hash "$1") || return 75
    cat "$1" > "$2" || return 1
    [ "$(vr2_hash "$2")" = "$vrb_ci_hash" ] && [ "$(vr2_hash "$1")" = "$vrb_ci_hash" ] || return 75
)
vrb_content_cas() {
    [ "$(vrb_target_hash "$1")" = "$2" ] && return 0
    # A known preflight refusal never becomes "lost ACK + matching post".
    if vrj2_seq "${vrb_active_step:-}" && printf '%s\n' content-cas > "$vrb_j/$vrb_op/step.$vrb_active_step/rejected"; then vrj2_flush || :;fi
    return 75
}
vrb_data_ancestry() (
    : "${vrb_e:?}"
    case $1 in "$vrb_e/"*) ;; *) return 75 ;; esac
    case $1 in */../*|*/./*|*/..|*/.) return 75 ;; esac
    vrb_da_parent=${1%/*}
    while [ "$vrb_da_parent" != "$vrb_e" ]; do
        vrj_dir "$vrb_da_parent" || return 75
        vrb_da_parent=${vrb_da_parent%/*}
        [ -n "$vrb_da_parent" ] || return 75
    done
    vrj_dir "$vrb_e"
)
vrb_publish() (
    [ "$#" -eq 3 ] || return 2
    case $3 in *[!0-9a-f]*) return 2 ;; esac
    [ "${#3}" -eq 64 ] || return 2
    vrb_worker_context || return 75
    vrb_self_admit routing-publisher || return 75
    if [ "$1" != - ]; then vrj2_file "$1" && vrb_single_link "$1" || return 75;fi
    vrb_data_ancestry "$2" || return 75
    if [ -e "$2" ] || [ -L "$2" ]; then
        vrb_owned_data_file "$2" && vrb_single_link "$2" || return 75
    fi
    vrb_pub_mode=$(vrb_publication_mode "$2") || return 75
    vrb_content_cas "$2" "$3" || return 75
    [ "$1" = - ] || chmod "$vrb_pub_mode" "$1" || return 1
    if [ ! -e "$vrb_j/$vrb_op/workers" ]; then mkdir "$vrb_j/$vrb_op/workers" || return 1;fi
    vrj_dir "$vrb_j/$vrb_op/workers" || return 75
    IFS=' ' read -r vrb_pub_pid _ < /proc/self/stat || return 1
    vrb_pub_start=$(vrj2_pid_start "$vrb_pub_pid") || return 1
    cat /proc/sys/kernel/random/boot_id > "$vrb_j/$vrb_op/workers/$vrj2_boot.$vrb_pub_pid.$vrb_pub_start" || return 1
    vr2_hash "$vrb_j/$vrb_op/workers/$vrj2_boot.$vrb_pub_pid.$vrb_pub_start" > "$vrb_j/$vrb_op/workers/$vrj2_boot.$vrb_pub_pid.$vrb_pub_start.sha" || return 1
    vrj2_flush || return 1
    if [ -f "$vrb_e/publish-pause" ]; then
        printf '%s\t%s\n' "$vrb_pub_pid" "$vrb_pub_start" > "$vrb_e/publish-waiting" || return 1
        while [ -f "$vrb_e/publish-pause" ]; do sleep 0.05;done
    fi
    vrb_worker_context || return 75
    vrb_data_ancestry "$2" || return 75
    [ "$(vrb_publication_mode "$2")" = "$vrb_pub_mode" ] || return 75
    vrb_content_cas "$2" "$3" || return 75
    vrb_dm_file=;vrb_dm_scope=;vrb_dm_new=0
    vrb_dispatch_mark "$1" "$2" || return 75
    if ! vrb_worker_context || ! vrb_data_ancestry "$2" ||
       [ "$(vrb_publication_mode "$2")" != "$vrb_pub_mode" ] || ! vrb_content_cas "$2" "$3" ||
       { [ "$vrb_role" != save ] && [ "$vrb_role" != baseline-save ] && [ "$(vrb_dispatch_scope "$1" "$2")" != "$vrb_dm_scope" ]; }; then
        # A subsequent final guard refusal withdraws this attempt BEFORE exec.
        # Save has its separate journal phase, with no physical-step receipt.
        if [ "$vrb_role" != save ] && [ "$vrb_role" != baseline-save ] && [ "$vrb_dm_new" = 1 ]; then
            rm -f "$vrb_dm_file" "$vrb_dm_file.sha" && vrj2_flush || return 1
        fi
        return 75
    fi
    if [ "$1" = - ]; then exec rm -f "$2";fi
    exec mv "$1" "$2"
)
vrb_publish_quiet() (
    [ ! -L "$1/workers" ] || return 75
    [ -e "$1/workers" ] || return 0
    vrj_dir "$1/workers" || return 75
    vrb_pq_boot=$(cat /proc/sys/kernel/random/boot_id) || return 75
    for vrb_pq_lease in "$1/workers"/*; do
        [ ! -e "$vrb_pq_lease" ] && [ ! -L "$vrb_pq_lease" ] && continue
        vrj2_file "$vrb_pq_lease" || return 75
        case $vrb_pq_lease in *.sha) vrj2_file "${vrb_pq_lease%.sha}" || return 75;continue ;; esac
        vrj2_file "$vrb_pq_lease.sha" && [ "$(vr2_hash "$vrb_pq_lease")" = "$(cat "$vrb_pq_lease.sha")" ] || return 75
        vrb_pq_key=${vrb_pq_lease##*/}
        vrb_pq_key_boot=${vrb_pq_key%%.*};vrb_pq_key=${vrb_pq_key#*.}
        vrb_pq_pid=${vrb_pq_key%%.*};vrb_pq_start=${vrb_pq_key#*.}
        case $vrb_pq_pid:$vrb_pq_start in *[!0-9:]*|:*|*:) return 75 ;; esac
        # A different boot proves all publishers of that boot gone. Same boot
        # needs both PID and starttime; an unparseable live PID remains unknown.
        vrb_pq_oldboot=$(cat "$vrb_pq_lease")
        [ "$vrb_pq_key_boot" = "$vrb_pq_oldboot" ] || return 75
        printf '%s\n' "$vrb_pq_oldboot" | grep -Eq '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$' || return 75
        vrb_pq_live=0;vlg_boot="$vrb_pq_boot" vward_lock_gate_live "$vrb_pq_oldboot.$vrb_pq_pid.$vrb_pq_start" || vrb_pq_live=$?
        [ "$vrb_pq_live" = 1 ] || return 75
    done
)
vrb_publish_image() (
    [ "$#" -eq 3 ] || return 2
    # Fresh private temporary leaf avoids following a reused .new symlink.
    vrb_data_ancestry "$2" || return 75
    vrb_pi_tmp=$(mktemp "${2%/*}/.image.XXXXXX") || return 1
    cat "$1" > "$vrb_pi_tmp" || return 1
    vrb_publish "$vrb_pi_tmp" "$2" "$3"
)
vrb_data_ready() {
    # Existing emulator gate, same private files; live paths are never selected.
    vrd_ready "$1" && vrj_dir "$1/.emu/decision" && vrj_dir "$1/.emu/services" || return 75
    for vrb_file in "$1/.emu"/decision/*.tsv; do
        [ ! -e "$vrb_file" ] && [ ! -L "$vrb_file" ] && continue
        vrj2_file "$vrb_file" || return 75
    done
    command -v vward_admission_enter >/dev/null 2>&1 &&
        command -v vward_routing_console_group_locked >/dev/null 2>&1 || return 75
}
vrb_pipeline_ready() {
    vrb_data_ready "$1" || return 75
    case $(cat "$1/.emu/decision/version.tsv") in
        "$(printf 'routing-state\t1')"|"$(printf 'routing-state\t2')") ;; *) return 75 ;;
    esac
}

# SAME public lock directories and pid layout as the existing console. Its
# real dir_lock helper remains the acquiring worker; no nested CLI is used.
# A legacy/unproven abandoned lock is not silently reclaimed by the new path.
vrb_shared_lock() {
    if [ -e "$1" ] || [ -L "$1" ]; then
        vrj_dir "$1" && vrj2_file "$1/owner" && vrj2_file "$1/owner.sha" || return 75
        [ "$(vr2_hash "$1/owner")" = "$(cat "$1/owner.sha")" ] || return 75
        IFS="$(printf '\t')" read -r vrb_sl_pid vrb_sl_start vrb_sl_boot vrb_sl_extra < "$1/owner" || return 75
        case $vrb_sl_pid:$vrb_sl_start in *[!0-9:]*|:*|*:) return 75 ;; esac
        [ -z "$vrb_sl_extra" ] && [ "$(cat "$1/pid")" = "$vrb_sl_pid" ] &&
            [ "$(cat "$1/pid_start")" = "$vrb_sl_start" ] && [ "$(vward_lock_boot_id "$1/boot")" = "$vrb_sl_boot" ] || return 75
        vrb_sl_now_boot=$(cat /proc/sys/kernel/random/boot_id) || return 75
        vrb_sl_live=0;vlg_boot="$vrb_sl_now_boot" vward_lock_gate_live "$vrb_sl_boot.$vrb_sl_pid.$vrb_sl_start" || vrb_sl_live=$?
        [ "$vrb_sl_live" = 1 ] || return 75
        for vrb_sl_op in "$vrb_j"/*; do
            [ -d "$vrb_sl_op" ] || continue
            [ ! -L "$vrb_sl_op" ] || return 75
            vrb_publish_quiet "$vrb_sl_op" || return 75
        done
    fi
    dir_lock "$1" || return 75
    [ "$(cat "$1/pid")" = "$vrj2_me" ] && vrj_dir "$1" || return 75
    printf '%s\n' "$vrj2_me" > "$1/pid" && printf '%s\n' "$vrj2_start" > "$1/pid_start" &&
        printf '%s\t%s\t%s\n' "$vrj2_me" "$vrj2_start" "$vrj2_boot" > "$1/owner" && vr2_hash "$1/owner" > "$1/owner.sha"
}
vrb_shared_unlock() {
    [ ! -L "$1" ] && [ "$(cat "$1/owner" 2>/dev/null)" = "$(printf '%s\t%s\t%s' "$vrj2_me" "$vrj2_start" "$vrj2_boot")" ] &&
        [ "$(cat "$1/pid" 2>/dev/null)" = "$vrj2_me" ] && [ "$(cat "$1/pid_start" 2>/dev/null)" = "$vrj2_start" ] || return 75
    vward_lock_release "$1"
}
vrb_local_path() {
    case $1:$2 in
        manifest:resources|manifest:proofs|manifest:choices|manifest:policies|manifest:tombstones|manifest:saved|manifest:queue|manifest:evidence|manifest:version|manifest:bindings|manifest:context|manifest:upstreams) printf '%s/decision/%s.tsv\n' "$vrb_e" "$2" ;;
        nativeproof:domain-list[0-9]|nativeproof:domain-list[0-9][0-9]) printf '%s/services/owned/%s\n' "$vrb_e" "$2" ;;
        registry:enabled) printf '%s/services/enabled.tsv\n' "$vrb_e" ;;
        saved:raw*) vrb_legacy_scope "$2" path ;;
        *) return 2 ;;
    esac
}
vrb_scope_read() (
    case $1:$2 in saved:routing-state) vrb_state_image "$vrb_e/decision" "$3";return $? ;; esac
    case $1 in
        group) vrb_cfg_image "$vrb_e/running.cfg" "$2" > "$3" ;;
        dns-scope)
            case $2 in
                keenetic) vrb_https_scope "$vrb_e/running.cfg" > "$3" ;;
                agh) vrj2_file "$vrb_e/agh.json" && vrb_agh_scope "$vrb_e/agh.json" > "$3" ;;
                *) return 2 ;;
            esac ;;
        *)
            vrb_path=$(vrb_local_path "$1" "$2") || return 2
            if [ ! -e "$vrb_path" ] && [ ! -L "$vrb_path" ]; then printf '%s\n' - > "$3"
            else vrb_owned_data_file "$vrb_path" && cat "$vrb_path" > "$3";fi ;;
    esac
)
# A single fixed emulator command. Existing console group_set/worker construct
# the actual native command; this parses only the closed supported command set.
vrb_emu_ndm() (
    vrb_worker_context || return 75
    printf '%s\n' "$1" >> "$vrb_e/calls"
    [ ! -f "$vrb_e/refuse" ] || [ "$(cat "$vrb_e/refuse")" != "$1" ] || return 1
    case $1 in 'dns-proxy https upstream '*|'dns-proxy no https upstream '*) vrb_emu_dns_command "$1";return $? ;; esac
    if [ "$1" = 'system configuration save' ]; then
        [ ! -e "$vrb_e/save-fails" ] || return 1
        vrb_save_pre=$(vrb_target_hash "$vrb_e/saved.cfg") || return 75
        vrb_capture_image "$vrb_e/running.cfg" "$vrb_t/save.source" || return 75
        vrb_publish_image "$vrb_t/save.source" "$vrb_e/saved.cfg" "$vrb_save_pre" || return 75
        return 0
    fi
    # No eval, shell splitting only after the closed alphabet is validated.
    case $1 in ''|*[!A-Za-z0-9_.\ -]*) return 2 ;; esac
    # shellcheck disable=SC2086
    set -- $1
    vrb_neg=add
    if [ "$1" = no ]; then vrb_neg=remove;shift;fi
    case $1:$2 in
        object-group:fqdn)
            vrb_group=$3
            if [ "$#" -eq 3 ]; then
                vrb_kind=create;[ "$vrb_neg" = add ] || vrb_kind=delete;vrb_value=-
            elif [ "$#" -eq 5 ] && [ "$4" = include ]; then vrb_kind=include;vrb_value=$5
            else return 2;fi ;;
        dns-proxy:route|dns-proxy:no)
            shift
            if [ "$1" = no ]; then vrb_neg=remove;shift;fi
            [ "$#" -eq 5 ] && [ "$1:$2:$5" = route:object-group:auto ] || return 2
            vrb_group=$3;vrb_value=$4;vrb_kind=route ;;
        *) return 2 ;;
    esac
    case $vrb_group in domain-list[0-9]|domain-list[0-9][0-9]) ;; *) return 2 ;; esac
    vrb_capture_image "$vrb_e/running.cfg" "$vrb_t/config.before" || return 75
    vrb_cfg_image "$vrb_t/config.before" "$vrb_group" > "$vrb_t/native.current" || return 3
    if [ "$vrb_role" = inverse ]; then vrb_native_expected=$vrb_t/inverse.expected
    else vrb_native_expected=$vrb_t/expected;fi
    cmp -s "$vrb_t/native.current" "$vrb_native_expected" || return 75
    vrb_prefix_apply "$vrb_t/native.current" "$vrb_kind" "$vrb_group" "$vrb_value" "$vrb_neg" > "$vrb_t/native.next" || return 3
    # Replace exactly one group and its routes, preserving every other byte.
    awk -v g="$vrb_group" '
        FILENAME==ARGV[1] {
            if($0=="-")absent=1
            else if($0!~/^group=/) {
                if($0~/^route=/){v=substr($0,7);gsub(/\t/," ",v);routes=routes "    route object-group " g " " v "\n"}
                else body=body "    " $0 "\n"
            }next
        }
        /^object-group fqdn / {skip=($3==g)}
        skip {if($0=="!")skip=0;next}
        /^dns-proxy$/ {dns=1;print;printf "%s",routes;next}
        /^!/ {dns=0}
        dns && $1=="route" && $2=="object-group" && $3==g {next}
        {print}
        END{if(!absent)printf "object-group fqdn %s\n%s!\n",g,body}' \
        "$vrb_t/native.next" "$vrb_t/config.before" > "$vrb_t/config.next" || return 1
    vrb_publish "$vrb_t/config.next" "$vrb_e/running.cfg" "$(vr2_hash "$vrb_t/config.before")" || return 75
    if [ -f "$vrb_e/foreign-after" ] && [ "$(cat "$vrb_e/foreign-after")" = "$vrb_kind" ]; then
        # DATA fault injection represents an EXTERNAL edit after our issued
        # command. It must not alter our candidate or receive our receipt.
        awk -v g="$vrb_group" '{print} $0=="object-group fqdn " g {print "    include owner-edit.example"}' \
            "$vrb_e/running.cfg" > "$vrb_t/foreign.next" &&
            cat "$vrb_t/foreign.next" > "$vrb_e/running.cfg" || return 1
    fi
    [ ! -f "$vrb_e/lost" ] || [ "$(cat "$vrb_e/lost")" != "$vrb_kind" ] || return 28
    return 0
)

vrb_write_scope() (
    vrb_role=forward;vrb_active_step=$3
    vrb_worker_context || return 75
    # Outer worker identity plus a distinct durable lease for EVERY final
    # publisher (vrb_publish). Killing this shell alone does not prove its
    # descendants quiet. A future LIVE transport still needs its own receipt.
    IFS=' ' read -r vrb_worker_pid _ < /proc/self/stat || return 1
    vrb_worker_start=$(vrj2_pid_start "$vrb_worker_pid") || return 1
    printf '%s\t%s\t%s\n' "$vrb_worker_pid" "$vrb_worker_start" "$vrj2_boot" > "$vrb_j/$vrb_op/worker" &&
        vr2_hash "$vrb_j/$vrb_op/worker" > "$vrb_j/$vrb_op/worker.sha" || return 1
    vrj2_flush || return 1
    trap 'rm -f "$vrb_j/$vrb_op/worker" "$vrb_j/$vrb_op/worker.sha"' EXIT
    vrb_write_kind=$1;vrb_write_id=$2;vrb_write_step=$3;vrb_write_dir=$4
    vrb_write_row=$(vrj2_step_row "$vrb_j/$vrb_op" "$vrb_write_step") || return 2
    [ "$(vr2_hash "$vrb_t/pre.$vrb_write_step")" = "$(printf '%s\n' "$vrb_write_row" | cut -f6)" ] &&
        [ "$(vr2_hash "$vrb_t/post.$vrb_write_step")" = "$(printf '%s\n' "$vrb_write_row" | cut -f7)" ] || return 3
    case $vrb_write_kind in
        saved)
            if [ "$vrb_write_id" = routing-state ]; then vrb_state_write forward;return $?;fi
            vrb_path=$(vrb_local_path saved "$vrb_write_id") || return 2
            vrb_scope_read saved "$vrb_write_id" "$vrb_t/current" && cmp -s "$vrb_t/current" "$vrb_t/pre.$vrb_write_step" || return 75
            [ ! -f "$vrb_e/local-fails" ] || [ "$(cat "$vrb_e/local-fails")" != "$vrb_write_id" ] || return 1
            vrb_publish_image "$vrb_t/post.$vrb_write_step" "$vrb_path" "$(vr2_hash "$vrb_t/pre.$vrb_write_step")" ;;
        dns-scope) vrb_dns_write "$vrb_write_id" "$vrb_write_step" ;;
        group)
            vrb_command_sha=$(vr2_hash "$vrb_t/commands.$vrb_write_step") || return 3
            printf '%s\n' "$vrb_write_row" | awk -F'\t' -v h="$vrb_command_sha" '
                {n=split($10,a,",");for(i=1;i<=n;i++)if(a[i]=="commands:" h)ok=1}END{exit ok?0:1}' || return 3
            # Re-read before EVERY native command. Prefixes were authorised by
            # the immutable parent plan before the FIRST command, not invented
            # after a lost reply. No whole running-config per domain is needed.
            cp "$vrb_t/pre.$vrb_write_step" "$vrb_t/expected"
            while IFS="$(printf '\t')" read -r vrb_k vrb_g vrb_v vrb_a; do
                vrb_scope_read group "$vrb_g" "$vrb_t/current" || return 3
                cmp -s "$vrb_t/current" "$vrb_t/expected" || return 3
                vrb_prefix_apply "$vrb_t/expected" "$vrb_k" "$vrb_g" "$vrb_v" "$vrb_a" > "$vrb_t/expected.next" || return 3
                _vrb_write_rc=0
                vward_routing_console_group_locked "$vrb_k" "$vrb_g" "$vrb_v" "$vrb_a" || _vrb_write_rc=$?
                [ "$_vrb_write_rc" != 75 ] || return 75
                vrb_scope_read group "$vrb_g" "$vrb_t/current" || return 3
                cmp -s "$vrb_t/current" "$vrb_t/expected.next" || return 3
                mv "$vrb_t/expected.next" "$vrb_t/expected" || return 1
            done < "$vrb_t/commands.$vrb_write_step" ;;
        *)
            vrb_path=$(vrb_local_path "$vrb_write_kind" "$vrb_write_id") || return 2
            # Refuse a replaced scope, including permission/symlink changes.
            vrb_scope_read "$vrb_write_kind" "$vrb_write_id" "$vrb_t/current" || return 3
            cmp -s "$vrb_t/current" "$vrb_t/pre.$vrb_write_step" || return 3
            [ ! -f "$vrb_e/local-fails" ] || [ "$(cat "$vrb_e/local-fails")" != "$vrb_write_id" ] || return 1
            if [ "$(cat "$vrb_t/$vrb_write_dir.$vrb_write_step")" = - ]; then vrb_publish - "$vrb_path" "$(vr2_hash "$vrb_t/pre.$vrb_write_step")"
            else
                vrb_publish_image "$vrb_t/$vrb_write_dir.$vrb_write_step" "$vrb_path" "$(vr2_hash "$vrb_t/pre.$vrb_write_step")"
            fi ;;
    esac
)

# Explicit OFF recovery; inspect never writes/replays a pending backend. A
# compensate request is bounded by immutable own post/prefix and fresh CAS.
# Unknown foreign edits keep their bytes and the private parent barrier.

vrb_inverse_group() (
    # CURRENT was just authorised by journal2_compensating. Every command has
    # its own fresh equality check so an intervening foreign edit stops us.
    vrb_inv_g=$1;vrb_inv_n=$2;vrb_active_step=$2;vrb_role=inverse
    cp "$vrb_t/current" "$vrb_t/inverse.expected" || return 1
    : > "$vrb_t/inverse.commands"
    if [ "$(cat "$vrb_t/current")" = - ]; then
        printf 'create\t%s\t-\tadd\n' "$1" >> "$vrb_t/inverse.commands"
    fi
    for vrb_inv_direction in remove add; do
        if [ "$vrb_inv_direction" = remove ]; then vrb_left=$vrb_t/pre.$2;vrb_right=$vrb_t/current
        else vrb_left=$vrb_t/current;vrb_right=$vrb_t/pre.$2;fi
        awk 'FILENAME==ARGV[1]{seen[$0]=1;next}!($0 in seen)&&/^(include |route=)/{print}' "$vrb_left" "$vrb_right" |
            while IFS= read -r vrb_line; do
                case $vrb_line in
                    'include '*) printf 'include\t%s\t%s\t%s\n' "$1" "${vrb_line#include }" "$vrb_inv_direction" ;;
                    route=*) vrb_value=${vrb_line#route=};vrb_value=${vrb_value%%"$(printf '\t')"*}
                        printf 'route\t%s\t%s\t%s\n' "$1" "$vrb_value" "$vrb_inv_direction" ;;
                esac
            done >> "$vrb_t/inverse.commands"
    done
    if [ "$(cat "$vrb_t/pre.$2")" = - ]; then printf 'delete\t%s\t-\tremove\n' "$1" >> "$vrb_t/inverse.commands";fi
    while IFS="$(printf '\t')" read -r vrb_k vrb_g vrb_v vrb_a; do
        vrb_scope_read group "$vrb_inv_g" "$vrb_t/check" || return 3
        cmp -s "$vrb_t/check" "$vrb_t/inverse.expected" || return 75
        vrb_prefix_apply "$vrb_t/inverse.expected" "$vrb_k" "$vrb_g" "$vrb_v" "$vrb_a" > "$vrb_t/inverse.next" || return 3
        vward_routing_console_group_locked "$vrb_k" "$vrb_g" "$vrb_v" "$vrb_a" || :
        vrb_scope_read group "$vrb_inv_g" "$vrb_t/check" || return 3
        cmp -s "$vrb_t/check" "$vrb_t/inverse.next" || return 3
        mv "$vrb_t/inverse.next" "$vrb_t/inverse.expected" || return 1
    done < "$vrb_t/inverse.commands"
    cmp -s "$vrb_t/inverse.expected" "$vrb_t/pre.$vrb_inv_n"
)

# Common operation envelope: existing admission, then EDIT, then CHANGE. The
# journal acquires only its short lock inside these locks, never a nested CLI.
vrb_envelope() {
    # This owns the operation context (environment, traps and private state),
    # including direct internal rehearsals under a permissive caller umask.
    umask 077
    vrb_data_ready "$1" && vrj2_id "$2" || return 75
    vrb_j=$1;vrb_e=$1/.emu;vrb_op=$2
    for vrb_parent in "$vrb_e/root" "$vrb_e/root/tmp" "$vrb_e/services/owned"; do
        if [ ! -e "$vrb_parent" ] && [ ! -L "$vrb_parent" ]; then mkdir "$vrb_parent" || return 1;fi
        vrj_dir "$vrb_parent" || return 75
    done
    VWARD_ROOT_PREFIX=$vrb_e/root;VWARD_COMPONENT_STATE=$vrb_e/components;VWARD_CPU_DIR=$vrb_e/cpu
    VWARD_BACKGROUND=1;VWARD_ADMISSION_OWNED=0;VWARD_ADMISSION_SLOT=
    export VWARD_ROOT_PREFIX VWARD_COMPONENT_STATE VWARD_CPU_DIR VWARD_BACKGROUND VWARD_ADMISSION_OWNED VWARD_ADMISSION_SLOT
    vward_admission_enter routing-rehearsal || return 75
    vrb_self_admit routing-coordinator || { vward_admission_leave;return 75; }
    vrb_coord_slot=$vrb_registered_slot
    vrb_edit=0;vrb_change=0;vrb_inside=;vrb_role=;vrb_active_step=
    vrb_edit_path=$VWARD_ROOT_PREFIX/tmp/vward-console-edit.lock
    vrb_change_path=$VWARD_ROOT_PREFIX/tmp/vward-route-change.lock
    IFS=' ' read -r vrj2_me _ < /proc/self/stat || return 1
    vrj2_start=$(vrj2_pid_start "$vrj2_me") || return 1
    IFS= read -r vrj2_boot < /proc/sys/kernel/random/boot_id || return 1
    trap '[ "$vrb_change" != 1 ] || vrb_shared_unlock "$vrb_change_path"
          [ "$vrb_edit" != 1 ] || vrb_shared_unlock "$vrb_edit_path"
          vrb_reap_publisher_slots
          vrb_self_leave "$vrb_coord_slot"
          vward_admission_leave' EXIT
    trap 'exit 143' HUP INT TERM
    vrb_shared_lock "$vrb_edit_path" || return 75;vrb_edit=1
    vrb_shared_lock "$vrb_change_path" || return 75;vrb_change=1
    vrb_legacy_gate "$vrb_e" || return 75
    vrb_revocations_gate "$vrb_j" "$vrb_e/decision" || return 75
    VWARD_CONSOLE_ETC=$vrb_e;VWARD_ROUTE_STATE=$vrb_e/route
    VWARD_KCACHE=$vrb_e;VWARD_DEVICE_CONFIG=$vrb_e/device.conf
    VWARD_DEVICE_MAP_CACHE=$vrb_e/device-map.tsv
    VWARD_SERVICES_FETCHED=$vrb_e/catalog.json;VWARD_SERVICES_BUNDLED=$vrb_e/missing
    VWARD_ROUTING_AGH_DOMAINS=$vrb_e/agh-domains
    VWARD_ROUTING_AGH_IMAGE=$vrb_e/agh.json
    VWARD_CONSOLE_BACKUP_DIR=$vrb_e/backup
    export VWARD_CONSOLE_ETC VWARD_ROUTE_STATE VWARD_KCACHE VWARD_DEVICE_CONFIG VWARD_DEVICE_MAP_CACHE \
        VWARD_SERVICES_FETCHED VWARD_SERVICES_BUNDLED VWARD_ROUTING_AGH_DOMAINS VWARD_ROUTING_AGH_IMAGE VWARD_CONSOLE_BACKUP_DIR
    ndm() { vrb_emu_ndm "$@"; }
    RUNCFG=$vrb_e/running-config
    export RUNCFG
    # Fixed DATA adapters called by the imported console helpers.
    # shellcheck disable=SC2317
    snapshot() { cp "$vrb_e/running.cfg" "$RUNCFG"; }
    # shellcheck disable=SC2317
    audit() { :; }
}

vrb_fresh_stage() {
    # One coherent snapshot per logical scope delta, not per include command.
    if [ -e "$vrb_t/reader" ] || [ -L "$vrb_t/reader" ]; then
        vrb_bootstrap_plan "$vrb_t" || return 75
        vward_routing_bootstrap_read2 "$vrb_t/fresh" "$vrb_e/decision" > "$vrb_t/read.status" || return 3
    else vward_routing_consistent_read2 "$vrb_t/fresh" "$vrb_e/decision" > "$vrb_t/read.status" || return 3;fi
    cat "$vrb_t/fresh/generation"
}
vrb_probe_deltas() {
    # An expiry/reboot is never an own Gi. Only a changed exact A record or
    # that record's three probe facts can account for its derived status.
    case $3:$4 in manifest:evidence|manifest:context|saved:routing-state) ;; *) return 0 ;; esac
    awk -F'\t' '
        {side=(FILENAME==ARGV[1] || FILENAME==ARGV[2])?"b":"a"}
        FILENAME==ARGV[1] || FILENAME==ARGV[3] {
            if($1=="A"){refs[$2]=1;e[side SUBSEP $2]=e[side SUBSEP $2] $0 "\n"}next
        }
        $1~/^probe(-boot|-until)?:/ {k=$1;sub(/^[^:]*:/,"",k);refs[k]=1;c[side SUBSEP k]=c[side SUBSEP k] $0 "\n"}
        END{for(r in refs)if(e["b" SUBSEP r]!=e["a" SUBSEP r] || c["b" SUBSEP r]!=c["a" SUBSEP r])print "obs-probe:" r}' \
        "$1/decision/evidence.tsv" "$1/decision/context.tsv" "$2/decision/evidence.tsv" "$2/decision/context.tsv"
}

# A new hash is not automatically an own Gi. Verify that ONLY the declared
# scope changed. A concurrent decision/profile/queue edit closes the operation,
# even when the backend happened to reach this step's expected postimage.
vrb_delta_valid() (
    [ "$#" -eq 4 ] && vr2_stage_valid "$1" && vr2_stage_valid "$2" || return 2
    case $3 in
        saved)
            if [ "$4" = routing-state ]; then vrb_allowed=state-set
            else vrb_allowed=$(vrb_legacy_scope "$4" label) || return 2;fi ;;
        group) vrb_allowed=cfg ;;
        nativeproof) vrb_allowed=owned:$4 ;;
        manifest) vrb_allowed=v2-$4 ;;
        registry) [ "$4" = enabled ] || return 2;vrb_allowed=enabled ;;
        dns-scope)
            case $4 in keenetic) vrb_allowed=cfg ;; agh) vrb_allowed=obs-agh-image ;; *) return 2 ;; esac ;;
        *) return 2 ;;
    esac
    vrb_probe_deltas "$@" > "$1/.probe-deltas" || return 3
    awk -v allowed="$vrb_allowed" -v uid="$(id -u)" '
        FILENAME==ARGV[1] {probe[$1]=1;next}
        FILENAME==ARGV[2] {before_n[$1]++;k=$1 SUBSEP before_n[$1];before[k]=$1 " " $2 " " $3 " " $6 " " $7;bmode[k]=$6;buid[k]=$7;label[k]=$1;next}
        {after_n[$1]++;k=$1 SUBSEP after_n[$1];after[k]=$1 " " $2 " " $3 " " $6 " " $7;amode[k]=$6;auid[k]=$7;label[k]=$1}
        END{for(k in label) {
            own=(label[k]==allowed || (label[k] in probe) || (allowed=="state-set" && label[k]~/^v2-(version|choices|bindings|context|resources|proofs|upstreams|policies|tombstones|saved|queue|evidence)$/))
            if(before[k]!=after[k] && !own)bad=1
            if(own) {
                if(bmode[k]!="" && amode[k]!="" && (bmode[k]!=amode[k] || buid[k]!=auid[k]))bad=1
                if(bmode[k]=="" && amode[k]!="" && (amode[k]!="-rw-------" || auid[k]!=uid))bad=1
            }
        }exit bad?1:0}' \
        "$1/.probe-deltas" "$1/inputs.fp" "$2/inputs.fp" || return 3
    if [ "$3" = group ]; then
        for vrb_side in "$1" "$2"; do
            awk -v g="$4" '
                /^object-group fqdn / {skip=($3==g)}
                skip {if($0=="!")skip=0;next}
                /^dns-proxy$/ {dns=1}
                /^!/ {dns=0}
                dns && $1=="route" && $2=="object-group" && $3==g {next}
                {print}' "$vrb_side/native.cfg" > "$vrb_side/.outside" || return 2
        done
        cmp -s "$1/.outside" "$2/.outside" || return 3
    fi
    if [ "$3:$4" = dns-scope:keenetic ]; then
        for vrb_side in "$1" "$2"; do
            awk '/^dns-proxy$/ {dns=1} /^[^ \t]/ && $0!="dns-proxy" {dns=0}
                dns && $1=="https" && $2=="upstream" {next}{print}' "$vrb_side/native.cfg" > "$vrb_side/.outside" || return 2
        done
        cmp -s "$1/.outside" "$2/.outside" || return 3
    elif [ "$3:$4" = dns-scope:agh ]; then
        for vrb_side in "$1" "$2"; do
            "${JQ:-jq}" -ceS 'del(.upstream_dns)' "$vrb_side/agh.json" > "$vrb_side/.outside" || return 2
        done
        cmp -s "$1/.outside" "$2/.outside" || return 3
    fi
)

# JDIR OPID SID ACTION TARGET DNS EXPECTED_REV. All paths for the simulated
# sources are bound below to JDIR/.emu; inherited profile/cache paths cannot
# point this coordinator at a router. No new caller is wired into the Panel.
vward_routing_pipeline2() (
    umask 077
    [ "$#" -eq 7 ] || return 2
    vrb_pipeline_ready "$1" || return 75
    vrb_envelope "$1" "$2" || return 75
    vward_routing_state_gate 2 "$vrb_e/decision" || return 75
    vward_journal2_gate "$vrb_j" || return 75
    vrb_t=$(mktemp -d "$vrb_j/.operation.XXXXXX") || return 1
    # Keep compiled sidecars after failure/crash: recovery never reconstructs a
    # more permissive plan from newly changed policy or an untrusted cache.
    mkdir "$vrb_t/stage" "$vrb_t/project" "$vrb_t/fresh" "$vrb_t/lowered" || return 1
    # The reader expects running-config. Real data file is bound by a copy,
    # never a symlink; refreshes below use only the emulator file.
    cp "$vrb_e/running.cfg" "$vrb_e/running-config" || return 1
    vward_routing_consistent_read2 "$vrb_t/stage" "$vrb_e/decision" > "$vrb_t/read.status" || return 3
    vward_routing_choice "$vrb_t/stage/decision/choices.tsv" "$3" "$4" "$5" "$6" "$7" > "$vrb_t/choices.next" || return 75
    vward_routing_project2 "$vrb_t/stage" "$3" "$vrb_t/choices.next" "$vrb_t/project" || return 3
    vward_routing_plan2 "$vrb_t/stage" "$vrb_t/project" "$vrb_op" > "$vrb_t/typed" || return 3
    if grep -q '^hold' "$vrb_t/typed"; then
        # A denied preview is presentation data, never a journal/capability.
        # Keep the same DTO while refusing before any physical compilation.
        cp "$vrb_t/stage/inputs.fp" "$vrb_t/lowered/inputs.fp" &&
            cp "$vrb_t/stage/generation" "$vrb_t/lowered/generation" &&
            cp "$vrb_t/project/choices.tsv" "$vrb_t/lowered/choices.after" || return 3
        : > "$vrb_t/lowered/resources.after"
        head -n1 "$vrb_t/typed" > "$vrb_t/lowered/plan" || return 3
        vrb_outcome_bind "$vrb_t/stage" "$vrb_t/lowered" "$vrb_t/project" &&
            vrb_outcome_emit "$vrb_t/stage" "$vrb_t/lowered" blocked || return 3
        cp "$vrb_t/lowered/outcome.json" "$vrb_t/outcome.json" &&
            cp "$vrb_t/lowered/outcome.json.sha" "$vrb_t/outcome.json.sha" || return 3
        printf 'outcome\tblocked\tdesired-only\tunknown\tfalse\temulated\n';return 75
    fi
    vward_routing_lower2 "$vrb_t/stage" "$vrb_t/typed" "$vrb_t/lowered" || return 75
    vrb_parent=$vrb_t
    vrb_outcome_bind "$vrb_parent/stage" "$vrb_parent/lowered" "$vrb_parent/project" || return 75
    vrb_result=0;vrb_execute2 "$vrb_parent/lowered" || vrb_result=$?
    vrb_outcome_stage=$vrb_parent/lowered/fresh
    [ -e "$vrb_outcome_stage/generation" ] || vrb_outcome_stage=$vrb_parent/stage
    vrb_outcome_emit "$vrb_outcome_stage" "$vrb_parent/lowered" || return 3
    if [ -d "$vrb_j/$vrb_op/prepared" ] && cmp -s "$vrb_parent/lowered/plan" "$vrb_j/$vrb_op/plan"; then
        cp "$vrb_parent/lowered/outcome.json" "$vrb_j/$vrb_op/prepared/outcome.json" &&
            cp "$vrb_parent/lowered/outcome.json.sha" "$vrb_j/$vrb_op/prepared/outcome.json.sha" || return 3
    fi
    return "$vrb_result"
)

# One executor for service choices AND server lifecycle plans. This internal
# function has no transport selection and still requires the OFF DATA envelope.
vrb_execute2() {
    [ "$#" -eq 1 ] && vrj_dir "$1" && vrb_data_ready "$vrb_j" || return 75
    vrb_t=$1
    if [ -e "$vrb_t/reader" ] || [ -L "$vrb_t/reader" ]; then vrb_bootstrap_plan "$vrb_t" || return 75
    else vward_routing_state_gate 2 "$vrb_e/decision" || return 75;fi
    if ! grep -q '^step' "$vrb_t/plan"; then
        printf 'outcome\tunchanged\tconfigured\tverified\tfalse\temulated\n';return 0
    fi
    mkdir "$vrb_t/fresh" || return 1
    vward_journal2_plan "$vrb_j" "$vrb_op" "$vrb_t/plan" || return 75
    if [ -e "$vrb_t/withdrawal" ] || [ -L "$vrb_t/withdrawal" ]; then
        vrj2_file "$vrb_t/withdrawal" || return 75
        vrb_withdraw_hash=$(vr2_hash "$vrb_t/withdrawal") || return 75
        awk -F'\t' -v h="$vrb_withdraw_hash" '$1=="step"&&$4=="manifest"&&$5=="tombstones" {
            n=split($10,a,",");for(i=1;i<=n;i++)if(a[i]=="revocations:" h)ok=1}END{exit ok?0:1}' "$vrb_t/plan" || return 75
        cp "$vrb_t/withdrawal" "$vrb_j/$vrb_op/withdrawal" &&
            printf '%s\n' "$vrb_withdraw_hash" > "$vrb_j/$vrb_op/withdrawal.sha" && vrj2_flush || return 1
    fi
    # Bind sidecars to journal plan before writes. SHA comparisons happen again
    # immediately before use; the journal hash commits to exact pre/post bytes.
    cp -R "$vrb_t" "$vrb_j/$vrb_op/prepared" || return 1
    vrb_inside=locked-emulator
    vrb_gen=$(cat "$vrb_t/generation")
    while IFS="$(printf '\t')" read -r vrb_tag vrb_n _vrb_action vrb_kind vrb_id vrb_pre vrb_post _vrb_proof _vrb_refs _vrb_checks _vrb_inverse; do
        [ "$vrb_tag" = step ] || continue
        cp "$vrb_e/running.cfg" "$vrb_e/running-config" || return 1
        vrb_now=$(vrb_fresh_stage) || return 3
        if [ "$vrb_now" != "$vrb_gen" ]; then
            vward_journal2_unknown "$vrb_j" "$vrb_op" input-changed-before-step
            printf 'outcome\tunknown\tdesired-only\tunknown\tfalse\temulated\n';return 3
        fi
        rm -rf "$vrb_t/before" || return 1
        cp -R "$vrb_t/fresh" "$vrb_t/before" || return 1
        [ "$(vr2_hash "$vrb_t/pre.$vrb_n")" = "$vrb_pre" ] &&
            [ "$(vr2_hash "$vrb_t/post.$vrb_n")" = "$vrb_post" ] || return 3
        vrb_scope_read "$vrb_kind" "$vrb_id" "$vrb_t/current" || return 3
        vr2_hash "$vrb_t/current" > "$vrb_t/current.hash"
        if [ "$(cat "$vrb_t/current.hash")" = "$vrb_post" ] &&
            ! vrb_dispatch_valid "$vrb_j" "$vrb_op" "$vrb_n" forward "$vrb_post"; then
            vward_journal2_unknown "$vrb_j" "$vrb_op" matching-image-not-dispatched
            printf 'outcome\tunknown\tdesired-only\tunknown\tfalse\temulated\n';return 3
        fi
        vward_journal2_begin "$vrb_j" "$vrb_op" "$vrb_n" "$vrb_gen" "$vrb_t/current.hash" || return 75
        vrb_rc=0;vrb_write_scope "$vrb_kind" "$vrb_id" "$vrb_n" post || vrb_rc=$?
        cp "$vrb_e/running.cfg" "$vrb_e/running-config" || return 1
        vrb_gen=$(vrb_fresh_stage) || { vward_journal2_unknown "$vrb_j" "$vrb_op" readback-unavailable;return 3; }
        if ! vrb_delta_valid "$vrb_t/before" "$vrb_t/fresh" "$vrb_kind" "$vrb_id"; then
            vward_journal2_unknown "$vrb_j" "$vrb_op" input-changed-during-step
            printf 'outcome\tunknown\tdesired-only\tunknown\tfalse\temulated\n';return 3
        fi
        vrb_scope_read "$vrb_kind" "$vrb_id" "$vrb_t/current" || return 3
        vr2_hash "$vrb_t/current" > "$vrb_t/current.hash"
        if [ "$vrb_rc" = 75 ] || { [ "$vrb_kind:$vrb_id" = dns-scope:agh ] && [ "$vrb_rc" != 0 ]; }; then
            vward_journal2_unknown "$vrb_j" "$vrb_op" unconfirmed-or-refused-write
            printf 'outcome\tunknown\tdesired-only\tunknown\tfalse\temulated\n';return 3
        fi
        if [ "$(cat "$vrb_t/current.hash")" = "$vrb_post" ] &&
            ! vrb_dispatch_valid "$vrb_j" "$vrb_op" "$vrb_n" forward "$vrb_post"; then
            vward_journal2_unknown "$vrb_j" "$vrb_op" matching-image-not-dispatched
            printf 'outcome\tunknown\tdesired-only\tunknown\tfalse\temulated\n';return 3
        fi
        vward_journal2_finish "$vrb_j" "$vrb_op" "$vrb_n" "$vrb_gen" "$vrb_t/current.hash" || {
            vward_journal2_unknown "$vrb_j" "$vrb_op" incomplete-step
            printf 'outcome\tunknown\tdesired-only\tunknown\tfalse\temulated\n';return 3;
        }
        # Transport status alone is not proof; readback above is authoritative.
        [ "$vrb_rc" = 0 ] || printf 'lost-reply\t%s\tverified-postimage\n' "$vrb_n" >> "$vrb_t/events"
    done < "$vrb_t/plan"
    vward_journal2_saved "$vrb_j" "$vrb_op" pending || return 1
    vrb_role=save
    vrb_publish_quiet "$vrb_j/$vrb_op" || return 75
    vrb_ndm_save=0
    awk -F'\t' '$1=="step"&&($4=="group" || ($4=="dns-scope" && $5=="keenetic")){found=1}END{exit found?0:1}' "$vrb_t/plan" && vrb_ndm_save=1
    if [ "$vrb_ndm_save" = 1 ] && ! ndm 'system configuration save'; then
        vward_journal2_saved "$vrb_j" "$vrb_op" failed
        vward_journal2_unknown "$vrb_j" "$vrb_op" save-failed
        printf 'outcome\tunknown\tdesired-only\tunknown\tfalse\temulated\n';return 3
    fi
    if [ "$vrb_ndm_save" = 1 ] && ! cmp -s "$vrb_e/running.cfg" "$vrb_e/saved.cfg"; then
        vward_journal2_unknown "$vrb_j" "$vrb_op" save-readback-mismatch;return 3
    fi
    cp "$vrb_e/running.cfg" "$vrb_e/running-config" || return 1
    vrb_now=$(vrb_fresh_stage) || { vward_journal2_unknown "$vrb_j" "$vrb_op" save-generation-unavailable;return 3; }
    if [ "$vrb_now" != "$vrb_gen" ]; then
        vward_journal2_unknown "$vrb_j" "$vrb_op" input-changed-on-save
        printf 'outcome\tunknown\tdesired-only\tunknown\tfalse\temulated\n';return 3
    fi
    vward_journal2_saved "$vrb_j" "$vrb_op" 'done' &&
        vward_journal2_commit "$vrb_j" "$vrb_op" "$vrb_gen" || return 3
    printf 'outcome\tcommitted\tconfigured\tverified\tfalse\temulated\n'
}

vward_routing_pipeline_recover2() (
    umask 077
    [ "$#" -eq 3 ] || return 2
    case $3 in inspect|compensate) ;; *) return 2 ;; esac
    vrb_envelope "$1" "$2" || return 75
    vrj2_ready "$vrb_j" "$vrb_op" || return 75
    [ ! -e "$vrb_j/$vrb_op/withdrawal" ] && [ ! -L "$vrb_j/$vrb_op/withdrawal" ] || return 75
    vrj2_gate_except "$vrb_j" "$vrb_op" || return 75
    case $(cat "$vrb_j/$vrb_op/state") in planned|pending|unknown) ;; *) return 75 ;; esac
    vrb_publish_quiet "$vrb_j/$vrb_op" || return 75
    # An acknowledged DATA write is distinct from an unresolved request. Do
    # not race compensation with a POST whose completion is still unproven.
    for vrb_request in "$vrb_j/$vrb_op"/dns-evidence/*/request.pending "$vrb_j/$vrb_op"/dns-inverse.*/evidence/request.pending; do
        [ ! -e "$vrb_request" ] && [ ! -L "$vrb_request" ] || return 75
    done
    if [ -e "$vrb_j/$vrb_op/worker" ] || [ -L "$vrb_j/$vrb_op/worker" ]; then
        vrj2_file "$vrb_j/$vrb_op/worker" && vrj2_file "$vrb_j/$vrb_op/worker.sha" &&
            [ "$(vr2_hash "$vrb_j/$vrb_op/worker")" = "$(cat "$vrb_j/$vrb_op/worker.sha")" ] || return 75
        IFS="$(printf '\t')" read -r vrb_pid vrb_start vrb_worker_boot vrb_extra < "$vrb_j/$vrb_op/worker" || return 75
        case $vrb_pid:$vrb_start in *[!0-9:]*|:*|*:) return 75 ;; esac
        [ -z "$vrb_extra" ] || return 75
        printf '%s\n' "$vrb_worker_boot" | grep -Eq '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$' || return 75
        vrb_worker_live=0;vlg_boot="$vrj2_boot" vward_lock_gate_live "$vrb_worker_boot.$vrb_pid.$vrb_start" || vrb_worker_live=$?
        [ "$vrb_worker_live" = 1 ] || return 75
    fi
    vrb_t=$vrb_j/$vrb_op/prepared
    vrj_dir "$vrb_t" && cmp -s "$vrb_t/plan" "$vrb_j/$vrb_op/plan" || return 75
    if [ -e "$vrb_t/reader" ] || [ -L "$vrb_t/reader" ]; then vrb_bootstrap_plan "$vrb_t" || return 75
    else vward_routing_state_gate 2 "$vrb_e/decision" || return 75;fi
    if [ "$3" = inspect ]; then
        printf 'outcome\tunknown\tdesired-only\tunknown\tfalse\temulated\n';return 3
    fi
    vward_journal2_unknown "$vrb_j" "$vrb_op" explicit-compensation || return 75
    vrb_inside=locked-emulator
    vrb_n=$(awk -F'\t' '$1=="step"{n++}END{print n+0}' "$vrb_t/plan")
    while [ "$vrb_n" -gt 0 ]; do
        vrb_row=$(vrj2_step_row "$vrb_j/$vrb_op" "$vrb_n") || return 75
        vrb_kind=$(printf '%s\n' "$vrb_row" | cut -f4);vrb_id=$(printf '%s\n' "$vrb_row" | cut -f5)
        [ "$(vr2_hash "$vrb_t/pre.$vrb_n")" = "$(printf '%s\n' "$vrb_row" | cut -f6)" ] &&
            [ "$(vr2_hash "$vrb_t/post.$vrb_n")" = "$(printf '%s\n' "$vrb_row" | cut -f7)" ] || return 75
        if [ -e "$vrb_j/$vrb_op/step.$vrb_n" ]; then
            vrj2_step_valid "$vrb_j" "$vrb_op" "$vrb_n" || return 75
            vrb_scope_read "$vrb_kind" "$vrb_id" "$vrb_t/current" || return 3
            vr2_hash "$vrb_t/current" > "$vrb_t/current.hash"
            if ! cmp -s "$vrb_t/current" "$vrb_t/pre.$vrb_n"; then
                if [ "$(cat "$vrb_j/$vrb_op/step.$vrb_n/state")" = compensating ] &&
                    vrb_dispatch_valid "$vrb_j" "$vrb_op" "$vrb_n" inverse "$(cat "$vrb_t/current.hash")"; then :
                else
                    vrb_dispatch_valid "$vrb_j" "$vrb_op" "$vrb_n" forward "$(cat "$vrb_t/current.hash")" || return 75
                    vward_journal2_compensating "$vrb_j" "$vrb_op" "$vrb_n" "$vrb_t/current.hash" || return 75
                fi
                if [ "$vrb_kind" = group ]; then
                    # Inverse from a proven own prefix, preserving other groups.
                    # Derive set difference to the EXACT saved baseline. No CLI
                    # or policy recomputation and no forward command replay.
                    vrb_inverse_group "$vrb_id" "$vrb_n" || return 3
                elif [ "$vrb_kind" = dns-scope ]; then
                    vrb_dns_inverse "$vrb_id" "$vrb_n" || return 3
                elif [ "$vrb_kind:$vrb_id" = saved:routing-state ]; then
                    vrb_role=inverse;vrb_active_step=$vrb_n
                    vrb_state_write inverse || return 3
                else
                    vrb_path=$(vrb_local_path "$vrb_kind" "$vrb_id") || return 2
                    vrb_scope_read "$vrb_kind" "$vrb_id" "$vrb_t/check" || return 3
                    cmp -s "$vrb_t/check" "$vrb_t/current" || return 75
                    if [ "$(cat "$vrb_t/pre.$vrb_n")" = - ]; then
                        vrb_role=inverse;vrb_active_step=$vrb_n
                        vrb_publish - "$vrb_path" "$(vr2_hash "$vrb_t/current")" || return 1
                    else
                        vrb_role=inverse;vrb_active_step=$vrb_n
                        vrb_publish_image "$vrb_t/pre.$vrb_n" "$vrb_path" "$(vr2_hash "$vrb_t/current")" || return 1
                    fi
                fi
            fi
            cp "$vrb_e/running.cfg" "$vrb_e/running-config" || return 1
            vrb_gen=$(vrb_fresh_stage) || return 3
            vrb_scope_read "$vrb_kind" "$vrb_id" "$vrb_t/current" || return 3
            vr2_hash "$vrb_t/current" > "$vrb_t/current.hash"
            vward_journal2_compensated "$vrb_j" "$vrb_op" "$vrb_n" "$vrb_gen" "$vrb_t/current.hash" || return 75
        fi
        vrb_n=$((vrb_n-1))
    done
    vward_journal2_rollback_saved "$vrb_j" "$vrb_op" pending || return 1
    vrb_role=baseline-save
    vrb_ndm_save=0
    while IFS="$(printf '\t')" read -r vrb_tag vrb_n _vrb_action vrb_kind vrb_id _vrb_rest; do
        [ "$vrb_tag" = step ] || continue
        [ -e "$vrb_j/$vrb_op/step.$vrb_n/inverse.from" ] || continue
        case $vrb_kind:$vrb_id in group:*|dns-scope:keenetic) vrb_ndm_save=1 ;; esac
    done < "$vrb_t/plan"
    if [ "$vrb_ndm_save" = 1 ]; then
        ndm 'system configuration save' || return 3
        cmp -s "$vrb_e/running.cfg" "$vrb_e/saved.cfg" || return 3
    fi
    vward_journal2_rollback_saved "$vrb_j" "$vrb_op" 'done' || return 1
    mkdir "$vrb_t/baseline" 2>/dev/null || vrj_dir "$vrb_t/baseline" || return 1
    while IFS="$(printf '\t')" read -r vrb_tag vrb_n _vrb_action vrb_kind vrb_id _vrb_rest; do
        [ "$vrb_tag" = step ] || continue
        vrb_scope_read "$vrb_kind" "$vrb_id" "$vrb_t/baseline/actual" || return 3
        vr2_hash "$vrb_t/baseline/actual" > "$vrb_t/baseline/step.$vrb_n" || return 3
    done < "$vrb_t/plan"
    vrb_gen=$(vrb_fresh_stage) || return 3
    printf '%s\n' "$vrb_gen" > "$vrb_t/baseline/generation"
    vward_journal2_abort "$vrb_j" "$vrb_op" "$vrb_gen" "$vrb_t/baseline" || return 75
    printf 'outcome\tcompensated\tdesired-only\tbaseline\tfalse\temulated\n'
)
