#!/bin/sh
# First control-state publication is metadata only. Native legacy data is
# observed/imported by the existing version-last state-set/J2 compiler.

vrl_init_parent() {
    # Called in the coordinator and in its final publisher. Actual kernel
    # identity, not inherited $$, authorizes the still-held shared locks.
    [ "${vrb_edit:-0}" = 1 ] && [ "${vrb_change:-0}" = 1 ] || return 75
    : "${vrl_root:?}" "${vrb_edit_path:?}" "${vrb_change_path:?}" "${vrj2_me:?}" "${vrj2_start:?}" "${vrj2_boot:?}"
    vrl_init_ancestry || return 75
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
    vrl_init_ancestry
}
vrl_init_ancestry() (
    # Recheck before preparation AND inside the final leased publisher.
    # Candidate and destination are fixed siblings under this same ancestry;
    # an earlier check cannot authorize a later replacement by an alias.
    : "${vrl_root:?}"
    [ "$vrl_root" = "${VWARD_ROOT_PREFIX:-}/opt/var/lib/vward/routing" ] || return 75
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
)
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
vrl_init_prepare() {
    # A failed read/compile cannot strand an unusable canonical root. These
    # observations are the SAME importer, prepared under the real shared locks;
    # only the acknowledged-root owner may execute their metadata-only J2.
    : "${vrl_etc:?}"
    vrl_init_parent && vrj2_file "$vrl_etc/device.conf" || return 75
    vrl_map_prepare || return 75
    vrl_observation_read || return 75
    mkdir "$1/journal/.migrations" || return 1
    vrl_ip_work=$1/journal/.migrations/$vrb_op
    vrb_legacy_prepare "$vrl_ip_work" "$1/decision" || return 75
    vrb_compile_state_set "$vrl_ip_work/stage" "$1/decision" "$vrl_ip_work/after" "$vrl_ip_work/lowered" '' || return 75
}
# Observation0: the exact empty decision every first transfer publishes.
vrl_init_empty() {
    for vrl_ie_key in $(vrb_state_names); do : > "$1/$vrl_ie_key.tsv" || return 1;done
    printf 'schema\t1\n' > "$1/choices.tsv" && printf 'routing-state\t0\n' > "$1/version.tsv"
}
vrl_init_root() {
    vrl_init_parent || return 75
    vrl_boot_stage=$(mktemp -d "${vrl_root%/*}/.routing-init.XXXXXX") || return 1
    mkdir "$vrl_boot_stage/decision" "$vrl_boot_stage/journal" "$vrl_boot_stage/.bootstrap" || return 1
    vrl_init_empty "$vrl_boot_stage/decision" &&
        vrb_state_image "$vrl_boot_stage/decision" "$vrl_boot_stage/.bootstrap/decision" &&
        vr2_hash "$vrl_boot_stage/.bootstrap/decision" > "$vrl_boot_stage/.bootstrap/decision.sha" &&
        printf '%s\t%s\t%s\t%s\n' "$vrb_op" "$vrj2_me" "$vrj2_start" "$vrj2_boot" > "$vrl_boot_stage/.bootstrap/parent" &&
        vr2_hash "$vrl_boot_stage/.bootstrap/parent" > "$vrl_boot_stage/.bootstrap/parent.sha" && vrj2_flush || return 1
    vrl_init_prepare "$vrl_boot_stage" || return 75
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
    : "${vrb_j:?}"
    # Inode transfer preserved the staged decision/source generation. The real
    # executor still takes a fresh generation/CAS before any metadata write.
    vrb_execute2 "$vrb_j/.migrations/$vrb_op/lowered"
)

# ---- Root0: explicit owner inspection / abort / own J2 compensation ----
# A coordinator killed after the leased no-clobber transfer leaves the
# canonical ROOT at observation0: every ordinary request and every legacy
# write gate then refuses (version != 2). Nothing here completes, adopts or
# replays that bootstrap. inspect only reads. abort moves the WHOLE root,
# byte-exact, to a fixed quarantine sibling (never deletes) and only when it
# is provably this transfer's own, unwritten and every actor of it is dead.
# The next ordinary request then performs a fresh first import.
vrl_r0_dead() {
    # BOOT.PID.START must be PROVEN gone; live or unknown fails closed.
    vrl_r0_rc=0;vlg_boot=$vrl_r0_boot vward_lock_gate_live "$1" || vrl_r0_rc=$?
    [ "$vrl_r0_rc" = 1 ]
}
vrl_r0_sealed() {
    vrj2_file "$1" && vrj2_file "$1.sha" && [ "$(vr2_hash "$1")" = "$(cat "$1.sha")" ]
}
vrl_r0_lock_dead() {
    # An existing journal short lock is only historical if its owner is gone.
    [ -e "$1" ] || [ -L "$1" ] || return 0
    vrj_dir "$1" || return 1
    for vrl_r0_lf in pid pid_start; do vrj2_file "$1/$vrl_r0_lf" || return 1;done
    vrl_r0_lb=$(vward_lock_boot_id "$1/boot") || return 1
    vrl_r0_dead "$vrl_r0_lb.$(cat "$1/pid").$(cat "$1/pid_start")"
}
vrl_r0_gate_dead() {
    # Election claims (BOOT.PID.START) and their final-utility leases.
    [ -e "$1" ] || [ -L "$1" ] || return 0
    vward_lock_gate_dir "$1" || return 1
    for vrl_r0_g in "$1"/* "$1"/.[!.]* "$1"/..?*; do
        [ -e "$vrl_r0_g" ] || [ -L "$vrl_r0_g" ] || continue
        vward_lock_gate_dir "$vrl_r0_g" && vrl_r0_dead "${vrl_r0_g##*/}" &&
            vlg_boot=$vrl_r0_boot vward_lock_gate_quiet "$vrl_r0_g" || return 1
    done
}
vrl_r0_only() {
    # DIR NAME...: DIR holds no entry outside NAME... (hidden ones included).
    vrl_r0_dir=$1;shift
    for vrl_r0_e in "$vrl_r0_dir"/* "$vrl_r0_dir"/.[!.]* "$vrl_r0_dir"/..?*; do
        [ -e "$vrl_r0_e" ] || [ -L "$vrl_r0_e" ] || continue
        vrl_r0_ok=0
        for vrl_r0_n in "$@"; do [ "${vrl_r0_e##*/}" != "$vrl_r0_n" ] || vrl_r0_ok=1;done
        [ "$vrl_r0_ok" = 1 ] || return 1
    done
}
# Prints one class: absent|ready|foreign|live|journal-unresolved|modified|
# abortable; for abortable/journal-unresolved also the stage and own op ID
# (from the sealed parent, never from a caller).
vrl_r0_classify() (
    umask 077
    vrl_paths_bind || return 75
    r=$vrl_root
    if [ ! -e "$r" ] && [ ! -L "$r" ]; then printf 'absent\n';return 0;fi
    if [ -L "$r" ] || [ ! -d "$r" ] || [ ! -O "$r" ]; then printf 'foreign\n';return 0;fi
    IFS= read -r vrl_r0_boot < /proc/sys/kernel/random/boot_id || return 75
    if vrj2_file "$r/decision/version.tsv" 2>/dev/null &&
        [ "$(cat "$r/decision/version.tsv")" = "$(printf 'routing-state\t2')" ]; then
        # Version-last state-set already published, but its own bootstrap J2
        # step never finished: only explicit compensation may resolve it.
        if vrl_r0_sealed "$r/.bootstrap/parent" 2>/dev/null &&
            IFS="$(printf '\t')" read -r op _ < "$r/.bootstrap/parent" && vrj2_id "$op" &&
            vrj2_ready "$r/journal" "$op" 2>/dev/null; then
            case $(cat "$r/journal/$op/state") in
                pending|unknown) printf 'journal-unresolved\tpublished\t%s\n' "$op";return 0 ;;
            esac
        fi
        printf 'ready\n';return 0
    fi
    if ! { vrj_dir "$r" && vrj_dir "$r/decision" && vrj_dir "$r/journal" && vrj_dir "$r/.bootstrap" &&
        vrl_r0_only "$r" decision journal .bootstrap &&
        vrl_r0_only "$r/.bootstrap" decision decision.sha parent parent.sha workers publisher publisher.sha completion completion.sha &&
        vrl_r0_sealed "$r/.bootstrap/parent" && vrl_r0_sealed "$r/.bootstrap/decision"; }; then printf 'foreign\n';return 0;fi
    IFS="$(printf '\t')" read -r op pid start boot extra < "$r/.bootstrap/parent" || { printf 'foreign\n';return 0; }
    if ! { vrj2_id "$op" && [ -z "$extra" ] &&
        [ "$(cat "$r/.bootstrap/parent")" = "$(printf '%s\t%s\t%s\t%s' "$op" "$pid" "$start" "$boot")" ]; }; then printf 'foreign\n';return 0;fi
    case $pid:$start in *[!0-9:]*|:*|*:) printf 'foreign\n';return 0 ;; esac
    # Every actor of THIS transfer: coordinator, final publisher, leases.
    vrl_r0_dead "$boot.$pid.$start" || { printf 'live\n';return 0; }
    if [ -e "$r/.bootstrap/publisher" ] || [ -L "$r/.bootstrap/publisher" ]; then
        vrl_r0_sealed "$r/.bootstrap/publisher" || { printf 'foreign\n';return 0; }
        IFS="$(printf '\t')" read -r p_pid p_start p_boot p_extra < "$r/.bootstrap/publisher" || { printf 'foreign\n';return 0; }
        [ -z "$p_extra" ] || { printf 'foreign\n';return 0; }
        case $p_pid:$p_start in *[!0-9:]*|:*|*:) printf 'foreign\n';return 0 ;; esac
        vrl_r0_dead "$p_boot.$p_pid.$p_start" || { printf 'live\n';return 0; }
    fi
    vrb_publish_quiet "$r/.bootstrap" || { printf 'live\n';return 0; }
    if ! { vrl_r0_lock_dead "$r/journal/.lock" && vrl_r0_gate_dead "$r/journal/.lock.gate"; }; then printf 'live\n';return 0;fi
    # Journal: only this transfer's prepared migration and, optionally, its
    # own J2 operation. Any other operation means the root was used.
    if ! { vrl_r0_only "$r/journal" .migrations .lock .lock.gate "$op" && vrj_dir "$r/journal/.migrations" &&
        vrl_r0_only "$r/journal/.migrations" "$op"; }; then printf 'foreign\n';return 0;fi
    stage=unacknowledged
    if [ -e "$r/.bootstrap/completion" ] || [ -L "$r/.bootstrap/completion" ]; then
        if ! { vrl_r0_sealed "$r/.bootstrap/completion" &&
            [ "$(cat "$r/.bootstrap/completion")" = acknowledged-root-transfer ]; }; then printf 'foreign\n';return 0;fi
        stage=acknowledged
    fi
    if [ -e "$r/journal/$op" ] || [ -L "$r/journal/$op" ]; then
        vrj2_ready "$r/journal" "$op" || { printf 'foreign\n';return 0; }
        vrb_publish_quiet "$r/journal/$op" || { printf 'live\n';return 0; }
        case $(cat "$r/journal/$op/state") in
            planned)
                # A plan with no begun step never wrote; any step record is
                # resolved only by the existing explicit compensation.
                for vrl_r0_s in "$r/journal/$op"/step.*; do
                    [ ! -e "$vrl_r0_s" ] && [ ! -L "$vrl_r0_s" ] && continue
                    printf 'journal-unresolved\t%s\t%s\n' "$stage" "$op";return 0
                done
                stage=planned ;;
            pending|unknown) printf 'journal-unresolved\t%s\t%s\n' "$stage" "$op";return 0 ;;
            compensated) vward_journal2_gate "$r/journal" || { printf 'journal-unresolved\t%s\t%s\n' "$stage" "$op";return 0; }
                stage=compensated ;;
            *) printf 'modified\n';return 0 ;;
        esac
    fi
    # Unwritten: current decision == sealed image == fresh observation0.
    t=$(mktemp -d "${VWARD_ROOT_PREFIX:-}/tmp/vward-root0.XXXXXX") || return 75
    trap 'rm -rf "$t"' EXIT
    mkdir "$t/empty" && vrl_init_empty "$t/empty" && vrb_state_image "$t/empty" "$t/expected" || return 75
    if vrb_state_image "$r/decision" "$t/current" 2>/dev/null &&
        cmp -s "$t/current" "$r/.bootstrap/decision" && cmp -s "$t/expected" "$r/.bootstrap/decision"; then
        printf 'abortable\t%s\t%s\n' "$stage" "$op"
    else printf 'modified\n';fi
)
vrl_r0_publish() (
    # Final utility leased in the SAME CHANGE election as the bootstrap
    # publisher: a dead coordinator cannot leave a late mover behind it.
    umask 077
    [ "$#" -eq 2 ] || return 75
    case $1 in "${vrl_root%/*}/.routing-root0."*) ;; *) return 75 ;; esac
    vrb_self_admit routing-publisher || return 75
    vward_lock_gate_enter "$vrb_change_path" || return 75
    trap 'vward_lock_gate_leave "$vrb_change_path"' EXIT
    [ "$(vrl_r0_classify | cut -f1,3)" = "$(printf 'abortable\t%s' "$2")" ] || return 75
    [ ! -e "$1" ] && [ ! -L "$1" ] || return 75
    exec mv -nT "$vrl_root" "$1"
)
vward_routing_root0() (
    umask 077
    [ "$#" -eq 1 ] || return 2
    vrl_paths_bind || return 75
    case $1 in
        inspect)
            vrl_r0=$(vrl_r0_classify) || return 75
            printf 'root0=%s\n' "$(printf '%s\n' "$vrl_r0" | cut -f1)"
            case $vrl_r0 in *"$(printf '\t')"*) printf 'root0_stage=%s\nroot0_op=%s\n' \
                "$(printf '%s\n' "$vrl_r0" | cut -f2)" "$(printf '%s\n' "$vrl_r0" | cut -f3)" ;; esac
            vrl_r0_n=0
            for vrl_r0_c in "${vrl_root%/*}"/.routing-init.*; do
                [ -e "$vrl_r0_c" ] || [ -L "$vrl_r0_c" ] || continue;vrl_r0_n=$((vrl_r0_n+1))
            done
            printf 'root0_candidates=%s\n' "$vrl_r0_n" ;;
        abort|compensate)
            # Cheap refusal first; the decision is re-proven under the locks.
            vrl_r0=$(vrl_r0_classify) || return 75
            case $1:$vrl_r0 in
                abort:abortable*|compensate:journal-unresolved*) ;;
                *) printf 'root0=%s\n' "$(printf '%s\n' "$vrl_r0" | cut -f1)";return 75 ;;
            esac
            vrl_r0_op=$(printf '%s\n' "$vrl_r0" | cut -f3);vrj2_id "$vrl_r0_op" || return 75
            if [ "$1" = compensate ]; then
                # The EXISTING explicit J2 compensation of this own operation:
                # immutable pre-images, fresh CAS, no forward replay.
                vward_routing_live_recover "$vrl_r0_op" compensate;return $?
            fi
            vrl_bind
            vrl_r0_tmp=$(mktemp -d "${VWARD_ROOT_PREFIX:-}/tmp/vward-routing-request.XXXXXX") || return 75
            vrl_r0_nonce=${vrl_r0_tmp##*.};rmdir "$vrl_r0_tmp" || return 75
            vrl_envelope "$vrl_root/journal" "a-$vrl_r0_nonce" || return 75
            vrl_r0=$(vrl_r0_classify) || return 75
            [ "$(printf '%s\n' "$vrl_r0" | cut -f1,3)" = "$(printf 'abortable\t%s' "$vrl_r0_op")" ] || {
                printf 'root0=%s\n' "$(printf '%s\n' "$vrl_r0" | cut -f1)";return 75; }
            vrl_r0_q=${vrl_root%/*}/.routing-root0.$vrl_r0_op
            [ ! -e "$vrl_r0_q" ] && [ ! -L "$vrl_r0_q" ] || return 75
            # shellcheck disable=SC2012
            vrl_r0_inode=$(ls -di "$vrl_root" | awk '{print $1}') || return 75
            vrl_r0_publish "$vrl_r0_q" "$vrl_r0_op" || return 75
            [ ! -e "$vrl_root" ] && [ ! -L "$vrl_root" ] && vrj_dir "$vrl_r0_q" || return 75
            # shellcheck disable=SC2012
            [ "$(ls -di "$vrl_r0_q" | awk '{print $1}')" = "$vrl_r0_inode" ] || return 75
            vrj2_flush
            printf 'root0=quarantined\nroot0_op=%s\n' "$vrl_r0_op" ;;
        *) return 2 ;;
    esac
)
