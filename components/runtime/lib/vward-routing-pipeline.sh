#!/bin/sh
# B execution rehearsal ONLY. Functions, no entrypoint or installed caller.
# The ONLY transport is the fixed built-in DATA emulator below. No executable
# path from API/environment, no native CLI invocation, no production permission.
# JDIR/.emu owns running.cfg, decision/, services/, and all fault files. Loading
# this library cannot enable a writer. Even poisoned NDMC/curl are never called.

vrb_worker_context() {
    [ "${vrb_inside:-}" = locked-emulator ] && vrj_dir "$vrb_j" &&
        vrj2_ready "$vrb_j" "$vrb_op" &&
        { [ "$(cat "$vrb_j/$vrb_op/state")" = pending ] || [ "$(cat "$vrb_j/$vrb_op/state")" = unknown ]; } &&
        [ "$(cat "$vrb_j/.edit/.lock/owner" 2>/dev/null)" = "$(printf '%s\t%s' "${vrj2_me:-}" "${vrj2_start:-}")" ] &&
        [ "$(cat "$vrb_j/.change/.lock/owner" 2>/dev/null)" = "$(printf '%s\t%s' "${vrj2_me:-}" "${vrj2_start:-}")" ] || return 75
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
vrb_pipeline_ready() {
    # Existing emulator gate, same private files; live paths are never selected.
    vrd_ready "$1" && vrj_dir "$1/.emu/decision" && vrj_dir "$1/.emu/services" || return 75
    for vrb_file in "$1/.emu"/decision/*.tsv; do vrj2_file "$vrb_file" || return 75;done
    case $(cat "$1/.emu/decision/version.tsv") in
        "$(printf 'routing-state\t1')"|"$(printf 'routing-state\t2')") ;; *) return 75 ;;
    esac
    command -v vward_admission_enter >/dev/null 2>&1 &&
        command -v vward_routing_console_group_locked >/dev/null 2>&1 || return 75
}
vrb_local_path() {
    case $1:$2 in
        manifest:resources|manifest:proofs|manifest:choices) printf '%s/decision/%s.tsv\n' "$vrb_e" "$2" ;;
        nativeproof:domain-list[0-9]|nativeproof:domain-list[0-9][0-9]) printf '%s/services/owned/%s\n' "$vrb_e" "$2" ;;
        registry:enabled) printf '%s/services/enabled.tsv\n' "$vrb_e" ;;
        *) return 2 ;;
    esac
}
vrb_scope_read() (
    case $1 in
        group) vrb_cfg_image "$vrb_e/running.cfg" "$2" > "$3" ;;
        *)
            vrb_path=$(vrb_local_path "$1" "$2") || return 2
            if [ ! -e "$vrb_path" ] && [ ! -L "$vrb_path" ]; then printf '%s\n' - > "$3"
            else vrj2_file "$vrb_path" && cat "$vrb_path" > "$3";fi ;;
    esac
)
# A single fixed emulator command. Existing console group_set/worker construct
# the actual native command; this parses only the closed supported command set.
vrb_emu_ndm() (
    vrb_worker_context || return 75
    printf '%s\n' "$1" >> "$vrb_e/calls"
    [ ! -f "$vrb_e/refuse" ] || [ "$(cat "$vrb_e/refuse")" != "$1" ] || return 1
    if [ "$1" = 'system configuration save' ]; then
        [ ! -e "$vrb_e/save-fails" ] || return 1
        cp "$vrb_e/running.cfg" "$vrb_e/saved.cfg" || return 1
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
    vrb_cfg_image "$vrb_e/running.cfg" "$vrb_group" > "$vrb_t/native.current" || return 3
    vrb_prefix_apply "$vrb_t/native.current" "$vrb_kind" "$vrb_group" "$vrb_value" "$vrb_neg" > "$vrb_t/native.next" || return 3
    if [ -f "$vrb_e/foreign-after" ] && [ "$(cat "$vrb_e/foreign-after")" = "$vrb_kind" ]; then
        printf '%s\n' 'include owner-edit.example' >> "$vrb_t/native.next"
    fi
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
        "$vrb_t/native.next" "$vrb_e/running.cfg" > "$vrb_t/config.next" || return 1
    mv "$vrb_t/config.next" "$vrb_e/running.cfg" || return 1
    [ ! -f "$vrb_e/lost" ] || [ "$(cat "$vrb_e/lost")" != "$vrb_kind" ] || return 28
    return 0
)

vrb_write_scope() (
    vrb_role=forward;vrb_active_step=$3
    vrb_worker_context || return 75
    # Durable worker lease covers the shell that can perform a final rename.
    # Its children only prepare scratch; after killing this shell they cannot
    # publish. A future LIVE transport needs its own lease before exec; this
    # emulator receipt deliberately does not certify such a transport.
    IFS=' ' read -r vrb_worker_pid _ < /proc/self/stat || return 1
    vrb_worker_start=$(vrj2_pid_start "$vrb_worker_pid") || return 1
    printf '%s\t%s\n' "$vrb_worker_pid" "$vrb_worker_start" > "$vrb_j/$vrb_op/worker" || return 1
    vrj2_flush || return 1
    trap 'rm -f "$vrb_j/$vrb_op/worker"' EXIT
    vrb_write_kind=$1;vrb_write_id=$2;vrb_write_step=$3;vrb_write_dir=$4
    vrb_write_row=$(vrj2_step_row "$vrb_j/$vrb_op" "$vrb_write_step") || return 2
    [ "$(vr2_hash "$vrb_t/pre.$vrb_write_step")" = "$(printf '%s\n' "$vrb_write_row" | cut -f6)" ] &&
        [ "$(vr2_hash "$vrb_t/post.$vrb_write_step")" = "$(printf '%s\n' "$vrb_write_row" | cut -f7)" ] || return 3
    case $vrb_write_kind in
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
            if [ "$(cat "$vrb_t/$vrb_write_dir.$vrb_write_step")" = - ]; then rm -f "$vrb_path"
            else
                cp "$vrb_t/$vrb_write_dir.$vrb_write_step" "$vrb_path.new" &&
                    chmod 0600 "$vrb_path.new" && mv "$vrb_path.new" "$vrb_path"
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
    vrb_pipeline_ready "$1" && vrj2_id "$2" || return 75
    vrb_j=$1;vrb_e=$1/.emu;vrb_op=$2
    for vrb_parent in "$vrb_e/root" "$vrb_e/root/tmp" "$vrb_e/services/owned"; do
        if [ ! -e "$vrb_parent" ] && [ ! -L "$vrb_parent" ]; then mkdir "$vrb_parent" || return 1;fi
        vrj_dir "$vrb_parent" || return 75
    done
    VWARD_ROOT_PREFIX=$vrb_e/root;VWARD_COMPONENT_STATE=$vrb_e/components;VWARD_CPU_DIR=$vrb_e/cpu
    VWARD_BACKGROUND=1;VWARD_ADMISSION_OWNED=0;VWARD_ADMISSION_SLOT=
    export VWARD_ROOT_PREFIX VWARD_COMPONENT_STATE VWARD_CPU_DIR VWARD_BACKGROUND VWARD_ADMISSION_OWNED VWARD_ADMISSION_SLOT
    vward_admission_enter routing-rehearsal || return 75
    vrb_edit=0;vrb_change=0;vrb_inside=;vrb_role=;vrb_active_step=
    trap '[ "$vrb_change" != 1 ] || vrj2_unlock "$vrb_j/.change"
          [ "$vrb_edit" != 1 ] || vrj2_unlock "$vrb_j/.edit"
          vward_admission_leave' EXIT
    trap 'exit 143' HUP INT TERM
    for vrb_lock in .edit .change; do
        if [ ! -e "$vrb_j/$vrb_lock" ] && [ ! -L "$vrb_j/$vrb_lock" ]; then mkdir "$vrb_j/$vrb_lock" || return 1;fi
        vrj_dir "$vrb_j/$vrb_lock" || return 75
    done
    vrj2_lock "$vrb_j/.edit" || return 75;vrb_edit=1
    vrj2_lock "$vrb_j/.change" || return 75;vrb_change=1
    VWARD_CONSOLE_ETC=$vrb_e;VWARD_ROUTE_STATE=$vrb_e/route
    VWARD_KCACHE=$vrb_e;VWARD_DEVICE_CONFIG=$vrb_e/device.conf
    VWARD_DEVICE_MAP_CACHE=$vrb_e/device-map.tsv
    VWARD_SERVICES_FETCHED=$vrb_e/catalog.json;VWARD_SERVICES_BUNDLED=$vrb_e/missing
    VWARD_ROUTING_AGH_DOMAINS=$vrb_e/agh-domains
    VWARD_CONSOLE_BACKUP_DIR=$vrb_e/backup
    export VWARD_CONSOLE_ETC VWARD_ROUTE_STATE VWARD_KCACHE VWARD_DEVICE_CONFIG VWARD_DEVICE_MAP_CACHE \
        VWARD_SERVICES_FETCHED VWARD_SERVICES_BUNDLED VWARD_ROUTING_AGH_DOMAINS VWARD_CONSOLE_BACKUP_DIR
    ndm() { vrb_emu_ndm "$@"; }
}

vrb_fresh_stage() {
    # One coherent snapshot per logical scope delta, not per include command.
    vward_routing_consistent_read2 "$vrb_t/fresh" "$vrb_e/decision" > "$vrb_t/read.status" || return 3
    cat "$vrb_t/fresh/generation"
}

# JDIR OPID SID ACTION TARGET DNS EXPECTED_REV. All paths for the simulated
# sources are bound below to JDIR/.emu; inherited profile/cache paths cannot
# point this coordinator at a router. No new caller is wired into the Panel.
vward_routing_pipeline2() (
    umask 077
    [ "$#" -eq 7 ] || return 2
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
        printf 'outcome\tblocked\tdesired-only\tunknown\tfalse\temulated\n';return 75
    fi
    vward_routing_lower2 "$vrb_t/stage" "$vrb_t/typed" "$vrb_t/lowered" || return 75
    vrb_t=$vrb_t/lowered
    if ! grep -q '^step' "$vrb_t/plan"; then
        printf 'outcome\tunchanged\tconfigured\tverified\tfalse\temulated\n';return 0
    fi
    mkdir "$vrb_t/fresh" || return 1
    vward_journal2_plan "$vrb_j" "$vrb_op" "$vrb_t/plan" || return 75
    # Bind sidecars to journal plan before writes. SHA comparisons happen again
    # immediately before use; the journal hash commits to exact pre/post bytes.
    cp -R "$vrb_t" "$vrb_j/$vrb_op/prepared" || return 1
    vrb_inside=locked-emulator
    vrb_gen=$(cat "$vrb_t/generation")
    while IFS="$(printf '\t')" read -r vrb_tag vrb_n _vrb_action vrb_kind vrb_id vrb_pre vrb_post _vrb_proof _vrb_refs _vrb_checks _vrb_inverse; do
        [ "$vrb_tag" = step ] || continue
        [ "$(vr2_hash "$vrb_t/pre.$vrb_n")" = "$vrb_pre" ] &&
            [ "$(vr2_hash "$vrb_t/post.$vrb_n")" = "$vrb_post" ] || return 3
        vrb_scope_read "$vrb_kind" "$vrb_id" "$vrb_t/current" || return 3
        vr2_hash "$vrb_t/current" > "$vrb_t/current.hash"
        vward_journal2_begin "$vrb_j" "$vrb_op" "$vrb_n" "$vrb_gen" "$vrb_t/current.hash" || return 75
        vrb_rc=0;vrb_write_scope "$vrb_kind" "$vrb_id" "$vrb_n" post || vrb_rc=$?
        cp "$vrb_e/running.cfg" "$vrb_e/running-config" || return 1
        vrb_gen=$(vrb_fresh_stage) || { vward_journal2_unknown "$vrb_j" "$vrb_op" readback-unavailable;return 3; }
        vrb_scope_read "$vrb_kind" "$vrb_id" "$vrb_t/current" || return 3
        vr2_hash "$vrb_t/current" > "$vrb_t/current.hash"
        vward_journal2_finish "$vrb_j" "$vrb_op" "$vrb_n" "$vrb_gen" "$vrb_t/current.hash" || {
            vward_journal2_unknown "$vrb_j" "$vrb_op" incomplete-step
            printf 'outcome\tunknown\tdesired-only\tunknown\tfalse\temulated\n';return 3;
        }
        # Transport status alone is not proof; readback above is authoritative.
        [ "$vrb_rc" = 0 ] || printf 'lost-reply\t%s\tverified-postimage\n' "$vrb_n" >> "$vrb_t/events"
    done < "$vrb_t/plan"
    vward_journal2_saved "$vrb_j" "$vrb_op" pending || return 1
    vrb_role=save
    if ! ndm 'system configuration save'; then
        vward_journal2_saved "$vrb_j" "$vrb_op" failed
        vward_journal2_unknown "$vrb_j" "$vrb_op" save-failed
        printf 'outcome\tunknown\tdesired-only\tunknown\tfalse\temulated\n';return 3
    fi
    cmp -s "$vrb_e/running.cfg" "$vrb_e/saved.cfg" || return 3
    vward_journal2_saved "$vrb_j" "$vrb_op" 'done' &&
        vward_journal2_commit "$vrb_j" "$vrb_op" "$vrb_gen" || return 3
    printf 'outcome\tcommitted\tconfigured\tverified\tfalse\temulated\n'
)

vward_routing_pipeline_recover2() (
    umask 077
    [ "$#" -eq 3 ] || return 2
    case $3 in inspect|compensate) ;; *) return 2 ;; esac
    vrb_envelope "$1" "$2" || return 75
    vrj2_ready "$vrb_j" "$vrb_op" || return 75
    vrj2_gate_except "$vrb_j" "$vrb_op" || return 75
    case $(cat "$vrb_j/$vrb_op/state") in planned|pending|unknown) ;; *) return 75 ;; esac
    if [ -e "$vrb_j/$vrb_op/worker" ] || [ -L "$vrb_j/$vrb_op/worker" ]; then
        vrj2_file "$vrb_j/$vrb_op/worker" || return 75
        IFS="$(printf '\t')" read -r vrb_pid vrb_start vrb_extra < "$vrb_j/$vrb_op/worker" || return 75
        case $vrb_pid:$vrb_start in *[!0-9:]*|:*|*:) return 75 ;; esac
        [ -z "$vrb_extra" ] && [ "$(vrj2_pid_start "$vrb_pid")" != "$vrb_start" ] || return 75
    fi
    vrb_t=$vrb_j/$vrb_op/prepared
    vrj_dir "$vrb_t" && cmp -s "$vrb_t/plan" "$vrb_j/$vrb_op/plan" || return 75
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
                vward_journal2_compensating "$vrb_j" "$vrb_op" "$vrb_n" "$vrb_t/current.hash" || return 75
                if [ "$vrb_kind" = group ]; then
                    # Inverse from a proven own prefix, preserving other groups.
                    # Derive set difference to the EXACT saved baseline. No CLI
                    # or policy recomputation and no forward command replay.
                    vrb_inverse_group "$vrb_id" "$vrb_n" || return 3
                else
                    vrb_path=$(vrb_local_path "$vrb_kind" "$vrb_id") || return 2
                    vrb_scope_read "$vrb_kind" "$vrb_id" "$vrb_t/check" || return 3
                    cmp -s "$vrb_t/check" "$vrb_t/current" || return 75
                    if [ "$(cat "$vrb_t/pre.$vrb_n")" = - ]; then rm -f "$vrb_path"
                    else cp "$vrb_t/pre.$vrb_n" "$vrb_path.new" && mv "$vrb_path.new" "$vrb_path" || return 1;fi
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
    ndm 'system configuration save' || return 3
    cmp -s "$vrb_e/running.cfg" "$vrb_e/saved.cfg" || return 3
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

