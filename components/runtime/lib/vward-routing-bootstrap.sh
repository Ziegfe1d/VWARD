#!/bin/sh
# First control-state publication is metadata only. Native legacy data is
# observed/imported by the existing version-last state-set/J2 compiler.

vrl_init_parent() {
    # Called in the coordinator and in its final publisher. Actual kernel
    # identity, not inherited $$, authorizes the still-held shared locks.
    [ "${vrb_edit:-0}" = 1 ] && [ "${vrb_change:-0}" = 1 ] || return 75
    : "${vrl_root:?}" "${vrb_edit_path:?}" "${vrb_change_path:?}" "${vrj2_me:?}" "${vrj2_start:?}" "${vrj2_boot:?}"
    [ ! -e "$vrl_root" ] && [ ! -L "$vrl_root" ] || return 75
    for vrl_ip_lock in "$vrb_edit_path" "$vrb_change_path"; do
        vrj_dir "$vrl_ip_lock" && vrj2_file "$vrl_ip_lock/owner" && vrj2_file "$vrl_ip_lock/owner.sha" &&
            [ "$(vr2_hash "$vrl_ip_lock/owner")" = "$(cat "$vrl_ip_lock/owner.sha")" ] &&
            [ "$(cat "$vrl_ip_lock/owner")" = "$(printf '%s\t%s\t%s' "$vrj2_me" "$vrj2_start" "$vrj2_boot")" ] &&
            [ "$(cat "$vrl_ip_lock/pid")" = "$vrj2_me" ] &&
            [ "$(cat "$vrl_ip_lock/pid_start")" = "$vrj2_start" ] &&
            [ "$(vward_lock_boot_id "$vrl_ip_lock/boot")" = "$vrj2_boot" ] || return 75
    done
    vlg_boot="$vrj2_boot" vward_lock_gate_live "$vrj2_boot.$vrj2_me.$vrj2_start" || return 75
    [ ! -e "${VWARD_ROOT_PREFIX:-}/tmp/vward-update-requested" ] && [ ! -L "${VWARD_ROOT_PREFIX:-}/tmp/vward-update-requested" ] &&
        [ ! -e "${VWARD_ROOT_PREFIX:-}/tmp/vward-update.lock" ] && [ ! -L "${VWARD_ROOT_PREFIX:-}/tmp/vward-update.lock" ] || return 75
    vward_routing_legacy_recovery_gate
}
vrl_init_base() {
    vrl_paths_bind || return 75
    [ "$#" -eq 1 ] && [ "$1" = "$vrl_root/journal" ] || return 75
    [ ! -e "$vrl_root" ] && [ ! -L "$vrl_root" ] || return 75
    vrl_ib_path=${vrl_root%/*}
    while [ "$vrl_ib_path" != "${VWARD_ROOT_PREFIX:-}/opt" ]; do
        [ -d "$vrl_ib_path" ] && [ ! -L "$vrl_ib_path" ] && [ -O "$vrl_ib_path" ] || return 75
        # shellcheck disable=SC2012
        case $(ls -ldn "$vrl_ib_path" | awk '{print substr($1,1,10)}') in
            drwx------|drwxr-xr-x|drwxr-x---|drwx--x--x) ;; *) return 75 ;;
        esac
        vrl_ib_path=${vrl_ib_path%/*}
        [ -n "$vrl_ib_path" ] || return 75
    done
    [ -d "$vrl_ib_path" ] && [ -O "$vrl_ib_path" ]
}
vrl_init_seal_valid() (
    : "${vrb_op:?}"
    [ "$#" -eq 1 ] && vrj_dir "$1" && vrj_dir "$1/.bootstrap" && vrj_dir "$1/journal" || return 75
    vrb_legacy_empty "$1/decision" && vrj2_file "$1/.bootstrap/decision" &&
        vrj2_file "$1/.bootstrap/decision.sha" &&
        [ "$(vr2_hash "$1/.bootstrap/decision")" = "$(cat "$1/.bootstrap/decision.sha")" ] || return 75
    vrl_is_tmp=$(mktemp "${VWARD_ROOT_PREFIX:-}/tmp/vward-root-seal.XXXXXX") || return 75
    trap 'rm -f "$vrl_is_tmp"' EXIT
    vrb_state_image "$1/decision" "$vrl_is_tmp" &&
        cmp -s "$1/.bootstrap/decision" "$vrl_is_tmp" || return 75
    vrj2_file "$1/.bootstrap/parent" && vrj2_file "$1/.bootstrap/parent.sha" &&
        [ "$(vr2_hash "$1/.bootstrap/parent")" = "$(cat "$1/.bootstrap/parent.sha")" ] &&
        [ "$(cat "$1/.bootstrap/parent")" = "$(printf '%s\t%s\t%s\t%s' "$vrb_op" "$vrj2_me" "$vrj2_start" "$vrj2_boot")" ]
)
vrl_init_publish() (
    umask 077
    [ "$#" -eq 1 ] || return 75
    case $1 in "${vrl_root%/*}/.routing-init."*) ;; *) return 75 ;; esac
    vrl_init_parent && vrl_init_seal_valid "$1" || return 75
    vrb_self_admit routing-publisher || return 75
    # This ACTUAL final utility owns the SAME CHANGE election. An old writer
    # cannot reclaim the dead coordinator's CHANGE while this process survives.
    vward_lock_gate_enter "$vrb_change_path" || return 75
    trap 'vward_lock_gate_leave "$vrb_change_path"' EXIT
    IFS=' ' read -r vrl_ip_pid _ < /proc/self/stat || return 75
    vrl_ip_start=$(vrj2_pid_start "$vrl_ip_pid") || return 75
    mkdir "$1/.bootstrap/workers" || return 1
    printf '%s\n' "$vrj2_boot" > "$1/.bootstrap/workers/$vrj2_boot.$vrl_ip_pid.$vrl_ip_start" &&
        vr2_hash "$1/.bootstrap/workers/$vrj2_boot.$vrl_ip_pid.$vrl_ip_start" > "$1/.bootstrap/workers/$vrj2_boot.$vrl_ip_pid.$vrl_ip_start.sha" &&
        printf '%s\t%s\t%s\n' "$vrl_ip_pid" "$vrl_ip_start" "$vrj2_boot" > "$1/.bootstrap/publisher" &&
        vr2_hash "$1/.bootstrap/publisher" > "$1/.bootstrap/publisher.sha" && vrj2_flush || return 1
    vrl_init_parent && vrl_init_seal_valid "$1" || return 75
    # BusyBox/GNU -nT refuses replacing an existing destination and never nests
    # the candidate inside a foreign directory. Parent still verifies inode
    # transfer and source absence: a no-clobber success is NOT publication ACK.
    exec mv -nT "$1" "$vrl_root"
)
vrl_init_root() {
    vrl_init_parent || return 75
    vrl_boot_stage=$(mktemp -d "${vrl_root%/*}/.routing-init.XXXXXX") || return 1
    mkdir "$vrl_boot_stage/decision" "$vrl_boot_stage/journal" "$vrl_boot_stage/.bootstrap" || return 1
    for vrl_ir_key in $(vrb_state_names); do : > "$vrl_boot_stage/decision/$vrl_ir_key.tsv" || return 1;done
    printf 'schema\t1\n' > "$vrl_boot_stage/decision/choices.tsv" &&
        printf 'routing-state\t0\n' > "$vrl_boot_stage/decision/version.tsv" &&
        vrb_state_image "$vrl_boot_stage/decision" "$vrl_boot_stage/.bootstrap/decision" &&
        vr2_hash "$vrl_boot_stage/.bootstrap/decision" > "$vrl_boot_stage/.bootstrap/decision.sha" &&
        printf '%s\t%s\t%s\t%s\n' "$vrb_op" "$vrj2_me" "$vrj2_start" "$vrj2_boot" > "$vrl_boot_stage/.bootstrap/parent" &&
        vr2_hash "$vrl_boot_stage/.bootstrap/parent" > "$vrl_boot_stage/.bootstrap/parent.sha" && vrj2_flush || return 1
    # Numeric metadata only. The candidate is on the same installed filesystem.
    # shellcheck disable=SC2012
    vrl_ir_inode=$(ls -di "$vrl_boot_stage" | awk '{print $1}') || return 75
    vrl_init_publish "$vrl_boot_stage" || return 75
    [ ! -e "$vrl_boot_stage" ] && [ ! -L "$vrl_boot_stage" ] && vrj_dir "$vrl_root" || return 75
    # shellcheck disable=SC2012
    [ "$(ls -di "$vrl_root" | awk '{print $1}')" = "$vrl_ir_inode" ] &&
        vrl_init_seal_valid "$vrl_root" || return 75
    printf 'acknowledged-root-transfer\n' > "$vrl_root/.bootstrap/completion" &&
        vr2_hash "$vrl_root/.bootstrap/completion" > "$vrl_root/.bootstrap/completion.sha" && vrj2_flush
}
vrl_init_quiet() {
    if [ -n "${vrl_boot_stage:-}" ] && { [ -e "$vrl_boot_stage/.bootstrap" ] || [ -L "$vrl_boot_stage/.bootstrap" ]; }; then
        vrb_publish_quiet "$vrl_boot_stage/.bootstrap" || return 75
    fi
    if [ -e "$vrl_root/.bootstrap" ] || [ -L "$vrl_root/.bootstrap" ]; then
        vrb_publish_quiet "$vrl_root/.bootstrap" || return 75
    fi
}
vward_routing_live_bootstrap() (
    umask 077
    [ "$#" -eq 1 ] && vrj2_id "$1" || return 75
    vrl_bind
    vrl_envelope "${VWARD_ROOT_PREFIX:-}/opt/var/lib/vward/routing/journal" "$1" bootstrap || return 75
    vrb_legacy_migrate_locked
)
