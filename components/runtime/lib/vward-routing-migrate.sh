#!/bin/sh
# Versioned local-state rehearsal. Not installed or called by production code.
# Same OFF DATA-root and operation envelope as the pipeline; no native write.
# File rollback and accepted user-state downgrade are separate decisions.
vrb_state_names() {
    printf '%s\n' choices bindings evidence policies saved queue tombstones context resources proofs upstreams version
}
vward_routing_state_gate() (
    [ "$#" -eq 2 ] && vrj_dir "$2" || return 2
    case $1 in 1|2) ;; *) return 75 ;; esac
    [ ! -e "$2/.migration-pending" ] && [ ! -L "$2/.migration-pending" ] || return 75
    vrj2_file "$2/version.tsv" || return 75
    [ "$(cat "$2/version.tsv")" = "$(printf 'routing-state\t%s' "$1")" ] || return 75
    for vrb_m in $(vrb_state_names); do vrj2_file "$2/$vrb_m.tsv" || return 75;done
)
vrb_migration_seal() (
    for vrb_m in $(vrb_state_names); do
        vrj2_file "$1/$vrb_m.tsv" && vrb_single_link "$1/$vrb_m.tsv" || return 2
        # Numeric authority metadata; the filename is not parsed.
        # shellcheck disable=SC2012
        printf '%s\t%s\t%s\n' "$vrb_m" "$(vr2_hash "$1/$vrb_m.tsv")" "$(ls -ldn "$1/$vrb_m.tsv" | awk '{print substr($1,1,10) "\t" $3}')"
    done
)
# Normalized state1 and deployed legacy0 are different formats. Both use the
# same local-state compiler, J2 prefixes, leased publisher and final byte/mode
# CAS. Neither this API nor a version marker grants a native/DNS capability.
vward_routing_state_migrate2() (
    umask 077
    [ "$#" -eq 2 ] || return 2
    vrb_envelope "$1" "$2" || return 75
    : "${vrb_e:?}" "${vrb_j:?}" "${vrb_op:?}"
    vward_journal2_gate "$vrb_j" && vward_routing_state_gate 1 "$vrb_e/decision" || return 75
    [ ! -e "$vrb_j/.migrations" ] || vrj_dir "$vrb_j/.migrations" || return 75
    [ -d "$vrb_j/.migrations" ] || mkdir "$vrb_j/.migrations" || return 1
    vrb_migration=$vrb_j/.migrations/$vrb_op
    [ ! -e "$vrb_migration" ] && [ ! -L "$vrb_migration" ] || return 75
    mkdir "$vrb_migration" "$vrb_migration/before" "$vrb_migration/after" "$vrb_migration/stage" "$vrb_migration/lowered" || return 1
    printf '%s\n' normalized1 > "$vrb_migration/kind"
    # State1 cannot express an accepted DNS/ISP pin or durable fresh evidence.
    awk -F'\t' '$1=="schema"{next}$1!="service"||NF!=7||$4!~/^(auto|vpn)$/{bad=1}END{exit bad?1:0}' \
        "$vrb_e/decision/choices.tsv" || return 75
    cp "$vrb_e/running.cfg" "$vrb_e/running-config" || return 1
    vward_routing_bootstrap_read2 "$vrb_migration/stage" "$vrb_e/decision" > "$vrb_migration/read.status" || return 3
    for vrb_m in $(vrb_state_names); do
        vrb_owned_data_file "$vrb_e/decision/$vrb_m.tsv" && vrb_single_link "$vrb_e/decision/$vrb_m.tsv" || return 75
        cp "$vrb_e/decision/$vrb_m.tsv" "$vrb_migration/before/$vrb_m.tsv" &&
            cp "$vrb_e/decision/$vrb_m.tsv" "$vrb_migration/after/$vrb_m.tsv" || return 1
    done
    awk -F'\t' 'BEGIN{OFS="\t"} $1=="A" {$8="history";$9=0} {print}' \
        "$vrb_migration/before/evidence.tsv" > "$vrb_migration/after/evidence.tsv" || return 1
    printf 'routing-state\t2\n' > "$vrb_migration/after/version.tsv" || return 1
    for vrb_side in before after; do
        vrb_migration_seal "$vrb_migration/$vrb_side" > "$vrb_migration/$vrb_side.seal" &&
            vr2_hash "$vrb_migration/$vrb_side.seal" > "$vrb_migration/$vrb_side.sha" || return 1
    done
    vrb_compile_state_set "$vrb_migration/stage" "$vrb_e/decision" "$vrb_migration/after" "$vrb_migration/lowered" .tsv || return 75
    vrb_execute2 "$vrb_migration/lowered" || return $?
    printf '%s\n' committed > "$vrb_migration/state" && vrj2_flush
)

# Data downgrade refuses EVERY later byte/authority change BEFORE a first
# write. Partial migration is resolved explicitly through J2 compensation,
# never by bypassing its pending/unknown barrier with a fresh operation.
vward_routing_state_restore1() (
    umask 077
    [ "$#" -eq 2 ] && vrj2_id "$2" || return 2
    vrb_restore_source=$2
    vrb_restore_id=$(printf '%s' "$2" | sha256sum);vrb_restore_id=${vrb_restore_id%% *}
    vrb_restore_id=r-${vrb_restore_id%????????????????????????????????????????}
    vrb_envelope "$1" "$vrb_restore_id" || return 75
    : "${vrb_e:?}" "${vrb_j:?}" "${vrb_op:?}"
    vward_journal2_gate "$vrb_j" && vward_routing_state_gate 2 "$vrb_e/decision" || return 75
    vrb_migration=$vrb_j/.migrations/$vrb_restore_source
    vrj_dir "$vrb_j/.migrations" && vrj_dir "$vrb_migration" && \
        [ "$(cat "$vrb_migration/kind")" = normalized1 ] || return 75
    vrj2_ready "$vrb_j" "$vrb_restore_source" && [ "$(cat "$vrb_j/$vrb_restore_source/state")" = committed ] || return 75
    vrb_state_step_valid "$vrb_j/$vrb_restore_source/prepared" "$vrb_j/$vrb_restore_source" 1 || return 75
    for vrb_side in before after; do
        vrj2_file "$vrb_migration/$vrb_side.seal" && vrj2_file "$vrb_migration/$vrb_side.sha" || return 75
        [ "$(vr2_hash "$vrb_migration/$vrb_side.seal")" = "$(cat "$vrb_migration/$vrb_side.sha")" ] || return 75
        [ "$(vrb_migration_seal "$vrb_migration/$vrb_side")" = "$(cat "$vrb_migration/$vrb_side.seal")" ] || return 75
    done
    vrb_revocations_gate "$vrb_j" "$vrb_migration/before" || return 75
    vrb_restore_work=$(mktemp -d "$vrb_j/.downgrade.XXXXXX") || return 1
    mkdir "$vrb_restore_work/stage" "$vrb_restore_work/lowered" || return 1
    vrb_state_image "$vrb_e/decision" "$vrb_restore_work/current" &&
        cmp -s "$vrb_restore_work/current" "$vrb_j/$vrb_restore_source/prepared/state/post" || return 75
    cp "$vrb_e/running.cfg" "$vrb_e/running-config" || return 1
    vward_routing_bootstrap_read2 "$vrb_restore_work/stage" "$vrb_e/decision" > "$vrb_restore_work/read.status" || return 3
    vrb_compile_state_set "$vrb_restore_work/stage" "$vrb_e/decision" "$vrb_migration/before" "$vrb_restore_work/lowered" .tsv || return 75
    vrb_execute2 "$vrb_restore_work/lowered" || return $?
    printf '%s\n' restored > "$vrb_migration/state" && vrj2_flush
)
