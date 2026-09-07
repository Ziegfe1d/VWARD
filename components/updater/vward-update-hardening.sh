#!/bin/sh

# Focused safety overrides for VWARD Smart Updater v1.
# This file is sourced after vward-update-common-base.sh.

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
