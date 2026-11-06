#!/bin/sh
# Fixed installed dependency closure. No executor path is an API argument;
# sourcing this loader only defines functions and never changes native state.
vward_routing_modules_load() {
    case ${1:-} in /*) ;; *) return 75 ;; esac
    [ -d "$1" ] && [ ! -L "$1" ] || return 75
    vrload_names='vward-runtime-admission.sh vward-routing-read.sh vward-routing-observe.sh
vward-routing-snapshot.sh vward-routing-audit.sh vward-routing-project.sh
vward-routing-plan.sh vward-routing-journal.sh
vward-routing-workers.sh vward-routing-migrate.sh vward-routing-dns.sh
vward-routing-lifecycle.sh vward-routing-legacy.sh vward-routing-state.sh
vward-routing-outcome.sh vward-routing-dispatch.sh vward-routing-pipeline.sh
vward-routing-admission.sh'
    for vrload_file in $vrload_names; do
        [ -f "$1/$vrload_file" ] && [ ! -L "$1/$vrload_file" ] &&
            [ -O "$1/$vrload_file" ] && [ -r "$1/$vrload_file" ] || return 75
    done
    for vrload_file in $vrload_names; do
        # shellcheck source=/dev/null
        . "$1/$vrload_file" || return 75
    done
}

# A legacy permission check is not a capability for the common coordinator.
# It observes fresh native data and retains the OLD path only outside B scopes.
vward_routing_native_admit() { [ "$#" -eq 1 ] && vward_routing_scope_admit command "$1"; }

vward_routing_scope_admit() (
    umask 077
    [ "$#" -eq 2 ] || return 75
    vrna_root=${VWARD_ROOT_PREFIX:-}/opt/var/lib/vward/routing
    [ -e "$vrna_root" ] || [ -L "$vrna_root" ] || return 0
    case $1 in
        command)
            vrna_scopes=$(vward_routing_legacy_command_scopes "$2") || return 75
            [ "$vrna_scopes" != "$(printf 'readonly\t-')" ] || return 0 ;;
        group|domain|auto|policy) ;;
        all) return 75 ;; # Compound managed metadata actions require the coordinator.
        *) return 75 ;;
    esac
    vrj_dir "$vrna_root" && vrj_dir "$vrna_root/decision" && vrj_dir "$vrna_root/journal" || return 75
    vrj2_file "$vrna_root/decision/version.tsv" &&
        [ "$(cat "$vrna_root/decision/version.tsv")" = "$(printf 'routing-state\t2')" ] || return 75
    vward_routing_state_gate 2 "$vrna_root/decision" &&
        vward_routing_update_eligibility2 "$vrna_root/journal" || return 75
    vward_routing_legacy_recovery_gate || return 75
    vrna_tmp=$(mktemp -d "${VWARD_ROOT_PREFIX:-}/tmp/vward-routing-gate.XXXXXX") || return 75
    trap 'rm -rf "$vrna_tmp"' EXIT
    trap 'exit 75' HUP INT TERM
    mkdir "$vrna_tmp/native" "$vrna_tmp/stage" || return 75
    # A private cache forces a fresh read; no saved history or caller cache is
    # accepted as current native membership. The existing profile transport is
    # used for this READ only, including its ordinary instrumented fixture path.
    VWARD_KCACHE=$vrna_tmp/native;_VWARD_KCACHE_OWN=1
    VWARD_ROUTING_INPUTS=1
    export VWARD_KCACHE VWARD_ROUTING_INPUTS
    vward_keenetic_config 0 > "$vrna_tmp/native/response" || return 75
    [ -s "$vrna_tmp/native/response" ] && awk '
        /^[[:space:]]*(Command::|[Ee][Rr][Rr][Oo][Rr][: ]|[Ff]ailed[: ])/ {bad=1}
        /^(object-group fqdn |dns-proxy$|interface |ip |system$)/ {seen=1}
        END {exit bad || !seen}' "$vrna_tmp/native/response" || return 75
    mv "$vrna_tmp/native/response" "$vrna_tmp/native/running-config" || return 75
    vward_routing_consistent_read2 "$vrna_tmp/stage" "$vrna_root/decision" >/dev/null || return 75
    vward_routing_legacy_recovery_gate || return 75
    if [ "$1" = command ]; then
        vward_routing_legacy_command_gate "$vrna_tmp/stage" "$vrna_root/journal" "$2" >/dev/null
    else
        vward_routing_legacy_eligibility2 "$vrna_tmp/stage" "$vrna_root/journal" "$1" "$2" >/dev/null
    fi
)
