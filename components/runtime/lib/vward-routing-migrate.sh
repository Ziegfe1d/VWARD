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
        vrj2_file "$1/$vrb_m.tsv" || return 2
        printf '%s\t%s\n' "$vrb_m" "$(vr2_hash "$1/$vrb_m.tsv")"
    done
)
vward_routing_state_migrate2() (
    umask 077
    [ "$#" -eq 2 ] || return 2
    vrb_envelope "$1" "$2" || return 75
    vrb_e=$1/.emu
    vward_journal2_gate "$1" && vward_routing_state_gate 1 "$vrb_e/decision" || return 75
    [ ! -e "$1/.migrations" ] || vrj_dir "$1/.migrations" || return 75
    [ -d "$1/.migrations" ] || mkdir "$1/.migrations" || return 1
    vrb_migration=$1/.migrations/$2
    [ ! -e "$vrb_migration" ] && [ ! -L "$vrb_migration" ] || return 75
    mkdir "$vrb_migration" "$vrb_migration/before" "$vrb_migration/after" || return 1
    # v1 has no accepted DNS/ISP pin or durable epoch evidence. Never silently
    # reinterpret a v2 ledger as a supported older state.
    awk -F'\t' '$1=="schema"{next}$1!="service"||NF!=7||$4!~/^(auto|vpn)$/{bad=1}END{exit bad?1:0}' \
        "$vrb_e/decision/choices.tsv" || return 75
    for vrb_m in $(vrb_state_names); do
        cp "$vrb_e/decision/$vrb_m.tsv" "$vrb_migration/before/$vrb_m.tsv" &&
            cp "$vrb_e/decision/$vrb_m.tsv" "$vrb_migration/after/$vrb_m.tsv" || return 1
    done
    # Legacy persisted activity is retained as history, never a fresh probe.
    awk -F'\t' 'BEGIN{OFS="\t"} $1=="A" {$8="history";$9=0} {print}' \
        "$vrb_migration/before/evidence.tsv" > "$vrb_migration/after/evidence.tsv" || return 1
    printf 'routing-state\t2\n' > "$vrb_migration/after/version.tsv" || return 1
    vrb_migration_seal "$vrb_migration/before" > "$vrb_migration/before.seal" &&
        vrb_migration_seal "$vrb_migration/after" > "$vrb_migration/after.seal" || return 1
    vr2_hash "$vrb_migration/before.seal" > "$vrb_migration/before.sha" &&
        vr2_hash "$vrb_migration/after.seal" > "$vrb_migration/after.sha" || return 1
    printf '%s\n' "$2" > "$vrb_e/decision/.migration-pending" || return 1
    vrj2_flush || return 1
    # The version marker is last. A power loss leaves an explicit fence, never
    # a partially migrated state declared compatible by either code version.
    for vrb_m in $(vrb_state_names); do
        [ "$(vr2_hash "$vrb_e/decision/$vrb_m.tsv")" = "$(vr2_hash "$vrb_migration/before/$vrb_m.tsv")" ] || return 75
        cp "$vrb_migration/after/$vrb_m.tsv" "$vrb_e/decision/$vrb_m.new" &&
            mv "$vrb_e/decision/$vrb_m.new" "$vrb_e/decision/$vrb_m.tsv" || return 1
    done
    vrj2_flush && printf '%s\n' committed > "$vrb_migration/state" && vrj2_flush || return 1
    rm -f "$vrb_e/decision/.migration-pending" || return 1
    vward_routing_state_gate 2 "$vrb_e/decision"
)

# Downgrade only when ALL current bytes are this migration's old/new images.
# A choice accepted after migration or an unknown foreign edit refuses BEFORE
# restoring a single file. No data loss disguised as an updater file rollback.
vward_routing_state_restore1() (
    umask 077
    [ "$#" -eq 2 ] || return 2
    vrb_envelope "$1" "$2" || return 75
    vrb_e=$1/.emu
    vward_journal2_gate "$1" || return 75
    vrb_migration=$1/.migrations/$2
    vrj_dir "$1/.migrations" && vrj_dir "$vrb_migration" &&
        vrj_dir "$vrb_migration/before" && vrj_dir "$vrb_migration/after" || return 75
    for vrb_side in before after; do
        vrj2_file "$vrb_migration/$vrb_side.seal" && vrj2_file "$vrb_migration/$vrb_side.sha" || return 75
        [ "$(vr2_hash "$vrb_migration/$vrb_side.seal")" = "$(cat "$vrb_migration/$vrb_side.sha")" ] || return 75
        [ "$(vrb_migration_seal "$vrb_migration/$vrb_side")" = "$(cat "$vrb_migration/$vrb_side.seal")" ] || return 75
    done
    if [ -e "$vrb_e/decision/.migration-pending" ] || [ -L "$vrb_e/decision/.migration-pending" ]; then
        vrj2_file "$vrb_e/decision/.migration-pending" && [ "$(cat "$vrb_e/decision/.migration-pending")" = "$2" ] || return 75
    fi
    for vrb_m in $(vrb_state_names); do
        vrb_current=$(vr2_hash "$vrb_e/decision/$vrb_m.tsv") || return 75
        [ "$vrb_current" = "$(vr2_hash "$vrb_migration/before/$vrb_m.tsv")" ] ||
            [ "$vrb_current" = "$(vr2_hash "$vrb_migration/after/$vrb_m.tsv")" ] || return 75
    done
    vrb_revocations_gate "$1" "$vrb_migration/before" || return 75
    printf '%s\n' "$2" > "$vrb_e/decision/.migration-pending" && vrj2_flush || return 1
    for vrb_m in $(vrb_state_names); do
        vrb_current=$(vr2_hash "$vrb_e/decision/$vrb_m.tsv") || return 75
        [ "$vrb_current" = "$(vr2_hash "$vrb_migration/before/$vrb_m.tsv")" ] ||
            [ "$vrb_current" = "$(vr2_hash "$vrb_migration/after/$vrb_m.tsv")" ] || return 75
        cp "$vrb_migration/before/$vrb_m.tsv" "$vrb_e/decision/$vrb_m.new" &&
            mv "$vrb_e/decision/$vrb_m.new" "$vrb_e/decision/$vrb_m.tsv" || return 1
    done
    vrj2_flush && printf '%s\n' restored > "$vrb_migration/state" && vrj2_flush || return 1
    rm -f "$vrb_e/decision/.migration-pending" || return 1
    vward_routing_state_gate 1 "$vrb_e/decision"
)
