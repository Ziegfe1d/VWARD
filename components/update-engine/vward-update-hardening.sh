#!/bin/sh

# Focused safety overrides for VWARD Update Engine.
# This file is sourced after vward-update-common-base.sh.

VU_COMPONENT_STATE_FILE=$VU_STATE_DIR/components.json
if [ -r "$SELF_DIR/component-registry.json" ]; then
    VU_COMPONENT_REGISTRY=$SELF_DIR/component-registry.json
else
    VU_COMPONENT_REGISTRY=$SELF_DIR/../../config/components/component-registry.json
fi

vu_component_registry_validate() {
    [ -r "$VU_COMPONENT_REGISTRY" ] || return 1
    jq -e '
      .schema == 1 and
      (.components | type == "array" and length > 0) and
      ([.components[].id] | length == (unique | length)) and
      ([.components[].runtime_targets[]] | length == (unique | length)) and
      all(.components[];
        (.id | type == "string" and length > 0) and
        (.legacy_ids | type == "array") and
        (.update_method | IN("signed-package", "slot-installer")) and
        (.health_profile | type == "string" and length > 0) and
        (.runtime_targets | type == "array" and length > 0) and
        ((.depends_on // []) | type == "array"))
    ' "$VU_COMPONENT_REGISTRY" >/dev/null 2>&1 || return 1
    jq -r '.components[] | (.depends_on // [])[]' "$VU_COMPONENT_REGISTRY" |
    while IFS= read -r dependency; do
        jq -e --arg dependency "$dependency" 'any(.components[]; .id == $dependency)' "$VU_COMPONENT_REGISTRY" >/dev/null 2>&1 || exit 1
    done
}

vu_component_canonical() {
    requested=$1
    jq -r --arg requested "$requested" '
      first(.components[] | select(.id == $requested or (.legacy_ids | index($requested) != null)) | .id) // empty
    ' "$VU_COMPONENT_REGISTRY"
}

vu_component_owner() {
    target=$1
    jq -r --arg target "$target" '
      first(.components[] | select(.runtime_targets | index($target) != null) | .id) // empty
    ' "$VU_COMPONENT_REGISTRY"
}

vu_component_dependencies_ready() {
    manifest=$1 package_manifest=$2
    for component in $(jq -r '.signed.affected_components[]' "$manifest" | while read -r id; do vu_component_canonical "$id"; done | sort -u); do
        for dependency in $(jq -r --arg component "$component" '.components[] | select(.id == $component) | (.depends_on // [])[]' "$VU_COMPONENT_REGISTRY"); do
            jq -r --arg dependency "$dependency" '.components[] | select(.id == $dependency) | .runtime_targets[]' "$VU_COMPONENT_REGISTRY" |
            while IFS= read -r target; do
                [ -e "$VU_ROOT_PREFIX$target" ] || jq -e --arg target "$target" 'any(.files[]; .target == $target)' "$package_manifest" >/dev/null 2>&1 || exit 1
            done || return 1
        done
    done
}

vu_target_mode_allowed() {
    target=$1 mode=$2
    case "$target" in
        /opt/share/vward/VERSION|/opt/etc/vward/console/lighttpd.conf|/opt/share/vward/console/www/index.html)
            [ "$mode" = 0644 ] ;;
        *) [ "$mode" = 0755 ] ;;
    esac
}

# Cross-check signed components, package components and authoritative target owners.
vu_package_validate() {
    package_dir=$1
    manifest=${2:-}
    package_manifest=$package_dir/package-manifest.json
    [ -r "$manifest" ] || return 1
    vu_component_registry_validate || return 1
    jq -e '.schema == 1 and
      ((.files | type) == "array" and (.files | length) > 0) and
      ([.files[].source] | length == (unique | length)) and
      ([.files[].target] | length == (unique | length)) and
      all(.files[];
        (.source | type) == "string" and
        (.target | type) == "string" and
        (.sha256 | type) == "string" and
        (.mode | type) == "string" and
        ((.component | type) == "string" and (.component | length) > 0) and
        (.restart_policy | IN("none", "deferred")) and
        (.config_policy == "program-only"))' "$package_manifest" >/dev/null 2>&1 || return 1

    validation_dir=${package_dir%/*}
    declared_components=$validation_dir/declared-components
    packaged_components=$validation_dir/packaged-components
    jq -r '.signed.affected_components[]' "$manifest" | while IFS= read -r component; do
        canonical=$(vu_component_canonical "$component")
        [ -n "$canonical" ] || exit 1
        printf '%s\n' "$canonical"
    done | sort -u > "$declared_components" || return 1
    [ -s "$declared_components" ] || return 1

    jq -r '.files[].component' "$package_manifest" | while IFS= read -r component; do
        canonical=$(vu_component_canonical "$component")
        [ -n "$canonical" ] || exit 1
        [ "$canonical" != update-engine ] || exit 1
        printf '%s\n' "$canonical"
    done | sort -u > "$packaged_components" || return 1
    cmp -s "$declared_components" "$packaged_components" || return 1
    vu_component_dependencies_ready "$manifest" "$package_manifest" || return 1
    profile=$(jq -r '.signed.health_profile' "$manifest")
    case "$profile" in
        default) : ;;
        updater) grep -qx update-engine "$declared_components" || return 1 ;;
        *)
            profile_matches=$(jq -r --arg profile "$profile" '.components[] | select(.health_profile == $profile) | .id' "$VU_COMPONENT_REGISTRY")
            matched=0
            for id in $profile_matches; do grep -qx "$id" "$declared_components" && matched=1; done
            [ "$matched" = 1 ] || return 1
            ;;
    esac

    jq -r '.files[] | [.source,.target,.sha256,.mode,.component] | @tsv' "$package_manifest" |
    while IFS="$(printf '\t')" read -r source target expected mode component; do
        case "$source" in ''|..|/*|*../*|../*|*/..) return 1 ;; esac
        [ "${#expected}" -eq 64 ] || return 1
        case "$expected" in *[!0-9a-f]*) return 1 ;; esac
        vu_safe_target "$target" || return 1
        vu_local_target "$target" && return 1
        canonical=$(vu_component_canonical "$component")
        owner=$(vu_component_owner "$target")
        [ -n "$canonical" ] && [ "$canonical" = "$owner" ] || return 1
        vu_target_mode_allowed "$target" "$mode" || return 1
        [ -f "$package_dir/$source" ] || return 1
        actual=$(sha256sum "$package_dir/$source" | awk '{print $1}')
        [ "$actual" = "$expected" ] || return 1
    done || return 1

    actual_files=$validation_dir/actual-files
    expected_files=$validation_dir/expected-files
    find "$package_dir" -type f | sed "s#^$package_dir/##" | sort > "$actual_files" || return 1
    { printf '%s\n' package-manifest.json; jq -r '.files[].source' "$package_manifest"; } | sort > "$expected_files"
    cmp -s "$actual_files" "$expected_files"
}

vu_component_state_write() {
    manifest=$1 package_dir=$2 health_time=$3
    state_tmp=$VU_STATE_DIR/components.new.$$
    if [ -r "$VU_COMPONENT_STATE_FILE" ]; then
        cp "$VU_COMPONENT_STATE_FILE" "$state_tmp" || return 1
    else
        printf '%s\n' '{"schema":1,"components":{}}' > "$state_tmp" || return 1
    fi
    version=$(jq -r '.signed.version' "$manifest")
    update_id=$(jq -r '.signed.update_id' "$manifest")
    sequence=$(jq -r '.signed.sequence' "$manifest")
    for component in $(jq -r '.files[].component' "$package_dir/package-manifest.json" | while read -r id; do vu_component_canonical "$id"; done | sort -u); do
        files=$(jq -c --arg component "$component" --slurpfile registry "$VU_COMPONENT_REGISTRY" '
          reduce .files[] as $f ({};
            ($registry[0].components[] | select(.id == $component) | ([.id] + .legacy_ids)) as $ids |
            if ($ids | index($f.component)) != null then . + {($f.target): $f.sha256} else . end)
        ' "$package_dir/package-manifest.json") || return 1
        jq --arg component "$component" --arg version "$version" --arg update_id "$update_id" \
           --argjson sequence "$sequence" --arg installed_at "$health_time" --argjson files "$files" \
          '.schema=1 | .components[$component]={release:$version,update_id:$update_id,sequence:$sequence,installed_at:$installed_at,health:"PASS",files:$files}' \
          "$state_tmp" > "$state_tmp.next" || return 1
        mv -f "$state_tmp.next" "$state_tmp" || return 1
    done
    vu_atomic_write "$VU_COMPONENT_STATE_FILE" "$state_tmp" || return 1
    rm -f "$state_tmp"
}

# Accept the retired staging_multiplier key silently for compatibility with
# older local test/config material while using signed compressed+unpacked sizes.
vu_assign_config() {
    key=$1
    value=$2
    case "$key" in
        update_enabled) update_enabled=$value ;;
        auto_apply) auto_apply=$value ;;
        auto_critical) auto_critical=$value ;;
        auto_important) auto_important=$value ;;
        auto_routine) auto_routine=$value ;;
        manifest_url) manifest_url=$value ;;
        public_key_file) public_key_file=$value ;;
        channel) channel=$value ;;
        safe_window_start) safe_window_start=$value ;;
        safe_window_end) safe_window_end=$value ;;
        minimum_free_kb) minimum_free_kb=$value ;;
        max_manifest_size) max_manifest_size=$value ;;
        max_package_size) max_package_size=$value ;;
        max_unpacked_size) max_unpacked_size=$value ;;
        staging_multiplier) : ;;
        backup_keep) backup_keep=$value ;;
        barrier_integration_ready) barrier_integration_ready=$value ;;
        current_version_file) current_version_file=$value ;;
        health_timeout_seconds) health_timeout_seconds=$value ;;
        check_interval_seconds) check_interval_seconds=$value ;;
        request_timeout_seconds) request_timeout_seconds=$value ;;
        important_max_delay_seconds) important_max_delay_seconds=$value ;;
        routine_max_delay_seconds) routine_max_delay_seconds=$value ;;
        ''|'#'*) ;;
        *) vu_log WARN "Ignoring unknown config key: $key" ;;
    esac
}

# Return free KB for a filesystem-wide future-allocation check.
# Tests can override this without changing the existing backup/target overrides.
vu_combined_free_kb() {
    probe=$1
    if [ -n "$VU_ROOT_PREFIX" ] && [ -n "${VWARD_TEST_FREE_COMBINED_KB:-}" ]; then
        printf '%s\n' "$VWARD_TEST_FREE_COMBINED_KB"
        return 0
    fi
    df -Pk "$probe" 2>/dev/null | awk 'NR==2 {print $4}'
}

# Stronger free-space gate:
# 1) retain independent backup and target checks used by existing tests;
# 2) additionally aggregate ALL future backup bytes + target sibling bytes
#    by actual filesystem, so shared /opt storage cannot be double-counted.
vu_hard_safety_check() {
    package_dir=$1
    [ "$barrier_integration_ready" = 1 ] || return 1
    vu_activity_clear || return 1
    mkdir -p "$VU_STAGING_DIR" "$VU_BACKUP_DIR" || return 1
    [ -w "$VU_STAGING_DIR" ] && [ -w "$VU_BACKUP_DIR" ] || return 1

    backup_sizes=$package_dir/backup-sizes
    : > "$backup_sizes" || return 1
    jq -r '.files[].target' "$package_dir/package-manifest.json" |
    while IFS= read -r target; do
        source=$VU_ROOT_PREFIX$target
        [ ! -f "$source" ] || wc -c < "$source"
    done > "$backup_sizes" || return 1

    backup_bytes=$(awk '{sum += $1} END {print sum+0}' "$backup_sizes")
    backup_required=$(((backup_bytes + 1023) / 1024 + minimum_free_kb))
    backup_free=$(vu_free_kb backup "$VU_BACKUP_DIR")
    [ -n "$backup_free" ] && [ "$backup_free" -ge "$backup_required" ] || return 1

    target_plan=$package_dir/target-space.tsv
    : > "$target_plan" || return 1
    jq -r '.files[] | [.target,.source] | @tsv' "$package_dir/package-manifest.json" |
    while IFS="$(printf '\t')" read -r target source; do
        destination=$VU_ROOT_PREFIX$target
        probe=$(dirname "$destination")
        while [ ! -d "$probe" ] && [ "$probe" != / ]; do
            probe=$(dirname "$probe")
        done
        fskey=$(df -Pk "$probe" 2>/dev/null | awk 'NR==2 {print $1}')
        [ -n "$fskey" ] || exit 1
        payload_bytes=$(wc -c < "$package_dir/$source")
        printf '%s\t%s\t%s\n' "$fskey" "$probe" "$payload_bytes"
    done > "$target_plan" || return 1

    target_aggregate=$package_dir/target-space-aggregate.tsv
    awk -F '\t' '
      { sum[$1]+=$3; if (!path[$1]) path[$1]=$2 }
      END { for (k in sum) printf "%s\t%s\t%.0f\n", k, path[k], sum[k] }
    ' "$target_plan" > "$target_aggregate" || return 1

    while IFS="$(printf '\t')" read -r fskey probe total_bytes; do
        target_free=$(vu_free_kb target "$probe")
        target_required=$(((total_bytes + 1023) / 1024 + minimum_free_kb))
        [ -n "$target_free" ] && [ "$target_free" -ge "$target_required" ] || return 1
    done < "$target_aggregate"

    # Unified future-allocation plan. This is the critical shared-filesystem fix:
    # if backup and targets live on the same /opt filesystem, their bytes are summed.
    combined_plan=$package_dir/combined-space.tsv
    : > "$combined_plan" || return 1

    backup_probe=$VU_BACKUP_DIR
    backup_fskey=$(df -Pk "$backup_probe" 2>/dev/null | awk 'NR==2 {print $1}')
    [ -n "$backup_fskey" ] || return 1
    printf '%s\t%s\t%s\n' "$backup_fskey" "$backup_probe" "$backup_bytes" >> "$combined_plan" || return 1
    cat "$target_plan" >> "$combined_plan" || return 1

    combined_aggregate=$package_dir/combined-space-aggregate.tsv
    awk -F '\t' '
      { sum[$1]+=$3; if (!path[$1]) path[$1]=$2 }
      END { for (k in sum) printf "%s\t%s\t%.0f\n", k, path[k], sum[k] }
    ' "$combined_plan" > "$combined_aggregate" || return 1

    while IFS="$(printf '\t')" read -r fskey probe total_bytes; do
        combined_free=$(vu_combined_free_kb "$probe")
        combined_required=$(((total_bytes + 1023) / 1024 + minimum_free_kb))
        [ -n "$combined_free" ] && [ "$combined_free" -ge "$combined_required" ] || return 1
    done < "$combined_aggregate"

    return 0
}
