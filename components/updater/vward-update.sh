#!/bin/sh

set -u

SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SELF_DIR/vward-update-common.sh"

usage() { printf '%s\n' 'Usage: vward-update.sh --status|--check|--dry-run|--apply|--apply-pending|--rollback|--recover'; }

cleanup() {
    vu_barrier_leave
    vu_lock_release
    if [ -n "${dry_run_staging:-}" ]; then case "$dry_run_staging" in */tmp/vward-updater-dryrun.*) rm -rf "$dry_run_staging" ;; esac; fi
    if [ -n "${transaction_staging:-}" ]; then case "$transaction_staging" in "$VU_STAGING_DIR"/transaction.*) rm -rf "$transaction_staging" ;; esac; fi
    for transient in update-manifest.json signed.json signature.bin; do rm -f "$VU_STAGING_DIR/$transient"; done
}

fetch_and_verify_manifest() {
    mkdir -p "$VU_STAGING_DIR" || return "$VU_INSTALL_ERROR"
    manifest=$VU_STAGING_DIR/update-manifest.json
    if [ "${use_pending_manifest:-0}" = 1 ]; then
        [ -r "$VU_PENDING_DIR/manifest.json" ] || return "$VU_NO_UPDATE"
        cp "$VU_PENDING_DIR/manifest.json" "$manifest" || return "$VU_VERIFY_ERROR"
    elif [ -n "${VWARD_LOCAL_MANIFEST:-}" ]; then
        case "$VWARD_LOCAL_MANIFEST" in "$VU_STAGING_DIR"/*) ;; *) return "$VU_VERIFY_ERROR" ;; esac
        cp "$VWARD_LOCAL_MANIFEST" "$manifest" || return "$VU_VERIFY_ERROR"
    elif [ -n "$VU_ROOT_PREFIX" ] && [ -n "${VWARD_TEST_MANIFEST:-}" ]; then
        cp "$VWARD_TEST_MANIFEST" "$manifest" || return "$VU_VERIFY_ERROR"
    else
        [ -n "$manifest_url" ] || return "$VU_CONFIG_ERROR"
        vu_fetch_limited "$manifest_url" "$manifest" "$max_manifest_size" || return "$VU_NETWORK_ERROR"
    fi
    actual_manifest_size=$(wc -c < "$manifest" | tr -d ' ')
    [ "$actual_manifest_size" -le "$max_manifest_size" ] || return "$VU_VERIFY_ERROR"
    vu_manifest_validate "$manifest" || return "$VU_VERIFY_ERROR"
    vu_manifest_verify_signature "$manifest" || return "$VU_VERIFY_ERROR"
    vu_manifest_check_policy "$manifest" || return "$VU_COMPAT_ERROR"
    trust_persist=1
    [ "${persist_trust:-1}" = 1 ] || trust_persist=0
    vu_trust_check_and_maybe_advance "$manifest" "$trust_persist" || return "$VU_COMPAT_ERROR"
    if [ "$VU_POLICY_DISPOSITION" = no-update ]; then
        VU_MANIFEST=$manifest
        return "$VU_NO_UPDATE"
    fi
    vu_manifest_space_preflight "$manifest" || return "$VU_SAFETY_ERROR"
    if [ "${persist_pending:-1}" = 1 ]; then vu_pending_store "$manifest" || return "$VU_INSTALL_ERROR"; fi
    VU_MANIFEST=$manifest
    return "$VU_OK"
}

download_and_unpack() {
    manifest=$1
    transaction_staging=$VU_STAGING_DIR/transaction.$$
    mkdir -p "$transaction_staging" || vu_die "$VU_INSTALL_ERROR" "Cannot create transaction staging"
    package=$transaction_staging/package.tar.gz
    package_dir=$transaction_staging/package
    expected=$(jq -r '.signed.package.sha256' "$manifest")
    expected_size=$(jq -r '.signed.package.size' "$manifest")
    unpacked_limit=$(vu_manifest_unpacked_size "$manifest") || vu_die "$VU_VERIFY_ERROR" "Signed unpacked size is unavailable"
    if [ -r "$VU_PENDING_DIR/package.tar.gz" ] && [ "$(sha256sum "$VU_PENDING_DIR/package.tar.gz" | awk '{print $1}')" = "$expected" ]; then
        cp "$VU_PENDING_DIR/package.tar.gz" "$package" || vu_die "$VU_VERIFY_ERROR" "Cannot read pending package"
    elif [ -n "$VU_ROOT_PREFIX" ] && [ -n "${VWARD_TEST_PACKAGE:-}" ]; then
        cp "$VWARD_TEST_PACKAGE" "$package" || vu_die "$VU_VERIFY_ERROR" "Cannot copy test package"
    else
        url=$(jq -r '.signed.package.url' "$manifest")
        vu_fetch_limited "$url" "$package" "$expected_size" || vu_die "$VU_NETWORK_ERROR" "Package download failed or exceeded signed size"
    fi
    actual_size=$(wc -c < "$package" | tr -d ' ')
    [ "$actual_size" -eq "$expected_size" ] || vu_die "$VU_VERIFY_ERROR" "Package size mismatch"
    [ "$actual_size" -le "$max_package_size" ] || vu_die "$VU_SAFETY_ERROR" "Package exceeds local maximum"
    actual=$(sha256sum "$package" | awk '{print $1}')
    [ "$actual" = "$expected" ] || vu_die "$VU_VERIFY_ERROR" "Package SHA-256 mismatch"
    if [ "${persist_pending:-1}" = 1 ]; then vu_atomic_write "$VU_PENDING_DIR/package.tar.gz" "$package" || vu_die "$VU_INSTALL_ERROR" "Cannot cache verified package"; fi
    mkdir -p "$package_dir" || vu_die "$VU_INSTALL_ERROR" "Cannot create package directory"
    tar -tzf "$package" | while IFS= read -r member; do case "$member" in ''|..|/*|*../*|../*|*/..) exit 1 ;; esac; done || vu_die "$VU_VERIFY_ERROR" "Unsafe package member path"
    tar -tvzf "$package" | awk '{type=substr($1,1,1); if(type!="-"&&type!="d") exit 1}' || vu_die "$VU_VERIFY_ERROR" "Package links or special files are forbidden"
    tar -xzf "$package" -C "$package_dir" || vu_die "$VU_VERIFY_ERROR" "Package extraction failed"
    actual_unpacked=$(find "$package_dir" -type f -exec wc -c {} \; 2>/dev/null | awk '{sum+=$1} END{print sum+0}')
    [ "$actual_unpacked" -le "$unpacked_limit" ] && [ "$actual_unpacked" -le "$max_unpacked_size" ] || vu_die "$VU_SAFETY_ERROR" "Extracted package exceeds signed/local unpacked size"
    vu_package_validate "$package_dir" || vu_die "$VU_VERIFY_ERROR" "Package manifest validation failed"
    VU_PACKAGE_DIR=$package_dir
}

print_plan() {
    manifest=$1; package_dir=$2
    printf 'Version: %s\nPriority: %s\nSequence: %s\n' "$(jq -r '.signed.version' "$manifest")" "$(jq -r '.signed.priority' "$manifest")" "$(jq -r '.signed.sequence' "$manifest")"
    printf '%s\n' 'Files:'
    jq -r '.files[] | "  \(.target) mode=\(.mode)"' "$package_dir/package-manifest.json"
}

create_backup() {
    package_dir=$1
    backup=$VU_BACKUP_DIR/$(date -u '+%Y%m%dT%H%M%SZ')-$$
    mkdir -p "$backup/files" || vu_die "$VU_INSTALL_ERROR" "Cannot create backup"
    : > "$backup/files.tsv" || vu_die "$VU_INSTALL_ERROR" "Cannot create backup index"
    if [ -r "$VU_COMMITTED_FILE" ]; then cp "$VU_COMMITTED_FILE" "$backup/committed.state" || vu_die "$VU_INSTALL_ERROR" "Cannot back up committed metadata"; printf '%s\n' 1 > "$backup/committed.existed"; else printf '%s\n' 0 > "$backup/committed.existed"; fi
    jq -r '.files[]|[.target,.mode]|@tsv' "$package_dir/package-manifest.json" |
    while IFS="$(printf '\t')" read -r target new_mode; do
        vu_safe_target "$target" || exit 1
        source=$VU_ROOT_PREFIX$target
        if [ -e "$source" ]; then
            mode=$(stat -c '%a' "$source" 2>/dev/null || printf '%s' "$new_mode")
            mkdir -p "$backup/files$(dirname "$target")" || exit 1
            cp -p "$source" "$backup/files$target" || exit 1
            original_sha=$(sha256sum "$source" | awk '{print $1}'); backup_sha=$(sha256sum "$backup/files$target" | awk '{print $1}')
            [ "$original_sha" = "$backup_sha" ] || exit 1
            printf '%s\t1\t%s\t%s\t%s\n' "$target" "$mode" "$original_sha" "$backup_sha" >> "$backup/files.tsv"
        else
            printf '%s\t0\t%s\t-\t-\n' "$target" "$new_mode" >> "$backup/files.tsv"
        fi
    done || vu_die "$VU_INSTALL_ERROR" "Backup failed"
    index_sha=$(sha256sum "$backup/files.tsv" | awk '{print $1}')
    if [ -r "$backup/committed.state" ]; then committed_sha=$(sha256sum "$backup/committed.state" | awk '{print $1}'); else committed_sha=-; fi
    printf 'index_sha=%s\ncommitted_sha=%s\n' "$index_sha" "$committed_sha" > "$backup/backup.meta" || vu_die "$VU_INSTALL_ERROR" "Cannot write backup metadata"
    vu_journal_set active_backup "$backup" || vu_die "$VU_INSTALL_ERROR" "Cannot record backup"
    VU_BACKUP=$backup
}

install_package() {
    package_dir=$1; count=0
    jq -r '.files[]|[.source,.target,.mode,.sha256]|@tsv' "$package_dir/package-manifest.json" |
    while IFS="$(printf '\t')" read -r source target mode expected; do
        count=$((count+1)); [ -z "$VU_ROOT_PREFIX" ] || [ "${VWARD_TEST_FAIL_INSTALL_AT:-0}" != "$count" ] || exit 1
        destination=$VU_ROOT_PREFIX$target; mkdir -p "$(dirname "$destination")" || exit 1
        tmp=$destination.vward-new.$$
        cp "$package_dir/$source" "$tmp" || exit 1
        actual=$(sha256sum "$tmp" | awk '{print $1}'); [ "$actual" = "$expected" ] || { rm -f "$tmp"; exit 1; }
        chmod "$mode" "$tmp" && sync && mv -f "$tmp" "$destination" || exit 1
    done
}

run_health_bounded() {
    profile=$1
    "$SELF_DIR/vward-update-health.sh" "$profile" & health_pid=$!; elapsed=0
    while kill -0 "$health_pid" 2>/dev/null; do
        if [ "$elapsed" -ge "$health_timeout_seconds" ]; then kill "$health_pid" 2>/dev/null || :; wait "$health_pid" 2>/dev/null || :; return 1; fi
        sleep 1; elapsed=$((elapsed+1))
    done
    wait "$health_pid"
}

apply_update() {
    manifest=$1; package_dir=$2
    vu_hard_safety_check "$package_dir" || vu_die "$VU_SAFETY_ERROR" "Pre-barrier safety check failed"
    vu_barrier_enter || vu_die "$VU_SAFETY_ERROR" "Could not complete update barrier handshake"
    vu_activity_clear || vu_die "$VU_SAFETY_ERROR" "Conflict appeared after barrier acquisition"
    manifest_hash=$(vu_signed_hash "$manifest")
    update_id=$(jq -r '.signed.update_id' "$manifest")
    previous_version=$(vu_installed_version) || vu_die "$VU_COMPAT_ERROR" "Installed version is unknown"
    vu_journal_set pending_update "$update_id" || vu_die "$VU_INSTALL_ERROR" "Cannot persist pending update"
    vu_journal_set manifest_hash "$manifest_hash" || vu_die "$VU_INSTALL_ERROR" "Cannot persist manifest hash"
    vu_journal_set previous_version "$previous_version" || vu_die "$VU_INSTALL_ERROR" "Cannot persist previous version"
    vu_transition BACKING_UP
    create_backup "$package_dir"; backup=$VU_BACKUP
    vu_transition INSTALLING
    if ! install_package "$package_dir"; then
        rollback_policy=$(jq -r '.signed.rollback_policy' "$manifest")
        if [ "$rollback_policy" = automatic ]; then
            if VWARD_INTERNAL_ROLLBACK=1 VWARD_INTERNAL_ROLLBACK_TOKEN="$VU_LOCK_TOKEN" "$SELF_DIR/vward-update-rollback.sh" "$backup"; then
                vu_quarantine_set "$manifest" install || vu_die "$VU_ROLLBACK_ERROR" "Rollback succeeded but quarantine persistence failed"
                vu_die "$VU_INSTALL_ERROR" "Install failed; rollback completed; update quarantined"
            fi
            vu_die "$VU_ROLLBACK_ERROR" "Install and rollback both failed"
        fi
        vu_transition RECOVERY_REQUIRED; vu_die "$VU_INSTALL_ERROR" "Install failed; manual recovery required"
    fi
    sync; vu_transition VERIFYING
    profile=$(jq -r '.signed.health_profile' "$manifest")
    if ! run_health_bounded "$profile"; then
        rollback_policy=$(jq -r '.signed.rollback_policy' "$manifest")
        if [ "$rollback_policy" = automatic ]; then
            if VWARD_INTERNAL_ROLLBACK=1 VWARD_INTERNAL_ROLLBACK_TOKEN="$VU_LOCK_TOKEN" "$SELF_DIR/vward-update-rollback.sh" "$backup"; then
                vu_quarantine_set "$manifest" health || vu_die "$VU_ROLLBACK_ERROR" "Rollback succeeded but quarantine persistence failed"
                vu_die "$VU_HEALTH_ERROR" "Health check failed; rollback completed; update quarantined"
            fi
            vu_die "$VU_ROLLBACK_ERROR" "Health check and rollback both failed"
        fi
        vu_transition RECOVERY_REQUIRED; vu_die "$VU_HEALTH_ERROR" "Health check failed; manual recovery required"
    fi
    sequence=$(jq -r '.signed.sequence' "$manifest"); version=$(jq -r '.signed.version' "$manifest"); health_time=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    vu_journal_set candidate_version "$version" || vu_die "$VU_INSTALL_ERROR" "Cannot journal candidate version"
    vu_journal_set candidate_update_id "$update_id" || vu_die "$VU_INSTALL_ERROR" "Cannot journal candidate update id"
    vu_journal_set candidate_sequence "$sequence" || vu_die "$VU_INSTALL_ERROR" "Cannot journal candidate sequence"
    vu_transition COMMIT_PREPARED
    [ -z "$VU_ROOT_PREFIX" ] || case "${VWARD_TEST_CRASH_COMMIT:-}" in after_installed_version|after_sequence|before_snapshot) exit 99 ;; esac
    vu_committed_write "$version" "$update_id" "$sequence" "$manifest_hash" "$health_time" || vu_die "$VU_INSTALL_ERROR" "Cannot atomically commit updater metadata"
    [ -z "$VU_ROOT_PREFIX" ] || [ "${VWARD_TEST_CRASH_COMMIT:-}" != after_snapshot ] || exit 99
    vu_pending_clear
    vu_transition COMMITTED
    vu_log INFO "Update $version committed"
}

command=${1:-}; dry_run_staging=
if [ "$command" = --dry-run ]; then
    VWARD_NO_PERSIST_LOG=1; export VWARD_NO_PERSIST_LOG
    dry_run_staging=${VWARD_DRY_RUN_DIR:-${VU_ROOT_PREFIX}/tmp/vward-updater-dryrun.$$}
    VU_STAGING_DIR=$dry_run_staging/staging; VU_BACKUP_DIR=$dry_run_staging/backup; VU_RUN_DIR=$dry_run_staging/run; VU_LOG_DIR=$dry_run_staging/log
    persist_pending=0; persist_trust=0
else
    persist_pending=1; persist_trust=1
fi
use_pending_manifest=0; [ "$command" = --apply-pending ] && use_pending_manifest=1

vu_load_config
vu_require_commands awk cmp cp curl date df find grep jq kill mkdir mv openssl sed sha256sum sleep stat tar tr wc

case "$command" in
    --status)
        printf 'enabled=%s\nauto_apply=%s\nbarrier_integration_ready=%s\nphase=%s\nlast_sequence=%s\nhighest_seen_sequence=%s\n' "$update_enabled" "$auto_apply" "$barrier_integration_ready" "$(vu_state_get phase "$VU_JOURNAL_FILE" 2>/dev/null || printf IDLE)" "$(vu_committed_get last_sequence 2>/dev/null || printf 0)" "$(vu_trust_get highest_seen_sequence 2>/dev/null || vu_committed_get last_sequence 2>/dev/null || printf 0)"
        exit "$VU_OK" ;;
    --rollback) exec "$SELF_DIR/vward-update-rollback.sh" ;;
    --recover)
        vu_lock_acquire || vu_die "$VU_DEFERRED" "Another updater transaction is active"
        trap cleanup EXIT HUP INT TERM
        [ "$barrier_integration_ready" = 1 ] || vu_die "$VU_SAFETY_ERROR" "Recovery barrier integration is disabled"
        vu_cleanup_orphan_staging || vu_die "$VU_SAFETY_ERROR" "Cannot clean orphan staging"
        vu_barrier_enter || vu_die "$VU_SAFETY_ERROR" "Cannot enter recovery barrier"
        phase=$(vu_state_get phase "$VU_JOURNAL_FILE" 2>/dev/null || printf IDLE)
        case "$phase" in
            INSTALLING|VERIFYING|ROLLING_BACK|RECOVERY_REQUIRED) VWARD_INTERNAL_ROLLBACK=1 VWARD_INTERNAL_ROLLBACK_TOKEN="$VU_LOCK_TOKEN" "$SELF_DIR/vward-update-rollback.sh"; exit $? ;;
            COMMIT_PREPARED)
                candidate=$(vu_state_get candidate_update_id "$VU_JOURNAL_FILE" 2>/dev/null || :); committed=$(vu_committed_get installed_update_id 2>/dev/null || :)
                if [ -n "$candidate" ] && [ "$candidate" = "$committed" ]; then vu_pending_clear; vu_transition COMMITTED; exit "$VU_OK"; fi
                VWARD_INTERNAL_ROLLBACK=1 VWARD_INTERNAL_ROLLBACK_TOKEN="$VU_LOCK_TOKEN" "$SELF_DIR/vward-update-rollback.sh"; exit $? ;;
            CHECKING|VERIFIED|BACKING_UP) vu_transition IDLE; exit "$VU_OK" ;;
            *) vu_log INFO "No interrupted transaction requires recovery"; exit "$VU_OK" ;;
        esac ;;
    --check|--dry-run|--apply|--apply-pending) ;;
    *) usage >&2; exit "$VU_CONFIG_ERROR" ;;
esac

[ "$update_enabled" = 1 ] || vu_die "$VU_DEFERRED" "Updater is disabled"
vu_lock_acquire || vu_die "$VU_DEFERRED" "Another updater process is active"
trap cleanup EXIT HUP INT TERM
[ "$command" = --dry-run ] || vu_cleanup_orphan_staging || vu_die "$VU_SAFETY_ERROR" "Cannot clean orphan staging"
[ "$command" = --dry-run ] || vu_transition CHECKING
fetch_and_verify_manifest
fetch_code=$?
case "$fetch_code" in
    "$VU_OK") ;;
    "$VU_NO_UPDATE") [ "$command" = --dry-run ] || vu_transition IDLE; exit "$VU_NO_UPDATE" ;;
    "$VU_NETWORK_ERROR") vu_die "$VU_NETWORK_ERROR" "Update transport failed" ;;
    "$VU_VERIFY_ERROR") vu_die "$VU_VERIFY_ERROR" "Manifest verification failed" ;;
    "$VU_COMPAT_ERROR") vu_die "$VU_COMPAT_ERROR" "Manifest violates trust/version/compatibility policy" ;;
    "$VU_SAFETY_ERROR") vu_die "$VU_SAFETY_ERROR" "Manifest/package staging preflight failed" ;;
    *) vu_die "$fetch_code" "Manifest processing failed" ;;
esac
manifest=$VU_MANIFEST
[ "$command" = --dry-run ] || vu_transition VERIFIED
if [ "$command" = --check ]; then
    printf 'Version: %s\nPriority: %s\nSequence: %s\n' "$(jq -r '.signed.version' "$manifest")" "$(jq -r '.signed.priority' "$manifest")" "$(jq -r '.signed.sequence' "$manifest")"
    vu_transition AVAILABLE; exit "$VU_OK"
fi
if [ "$command" = --apply-pending ] && vu_quarantine_matches "$manifest"; then vu_die "$VU_QUARANTINED" "Pending update is quarantined after a previous failed apply"; fi
priority=$(jq -r '.signed.priority' "$manifest"); first_seen=$(vu_pending_get first_seen_at 2>/dev/null || vu_now_epoch)
if [ "$command" != --dry-run ] && ! vu_schedule_ready "$priority" "$first_seen"; then vu_transition WAITING_WINDOW; vu_die "$VU_DEFERRED" "Pending update is waiting for its scheduling policy"; fi
download_and_unpack "$manifest"; package_dir=$VU_PACKAGE_DIR; print_plan "$manifest" "$package_dir"
case "$command" in
    --dry-run) if vu_hard_safety_check "$package_dir"; then printf '%s\n' 'Safety: ready'; else printf '%s\n' 'Safety: blocked'; fi; exit "$VU_OK" ;;
    --apply|--apply-pending) apply_update "$manifest" "$package_dir" ;;
esac
