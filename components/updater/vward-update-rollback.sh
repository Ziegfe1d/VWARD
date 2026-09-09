#!/bin/sh

set -u

SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SELF_DIR/vward-update-common.sh"
vu_load_config

rollback_internal=${VWARD_INTERNAL_ROLLBACK:-0}
rollback_failure_class=

if [ "$rollback_internal" = 1 ]; then
    internal_token=${VWARD_INTERNAL_ROLLBACK_TOKEN:-}
    lock_owner=$(sed -n '1p' "$VU_RUN_DIR/updater.lock/owner" 2>/dev/null || :)
    barrier_owner=$(sed -n '1p' "$VU_BARRIER_LOCK/owner" 2>/dev/null || :)
    [ -n "$internal_token" ] && [ "$internal_token" = "$lock_owner" ] && [ "$internal_token" = "$barrier_owner" ] ||
        vu_die "$VU_SAFETY_ERROR" "Internal rollback ownership validation failed"

    # Persist the reason before entering ROLLING_BACK. If power dies after files
    # are restored but before quarantine is written, recovery sees this reason
    # and completes quarantine before declaring ROLLED_BACK.
    phase_before=$(vu_state_get phase "$VU_JOURNAL_FILE" 2>/dev/null || :)
    case "$phase_before" in
        INSTALLING) rollback_failure_class=install ;;
        VERIFYING) rollback_failure_class=health ;;
        ROLLING_BACK|RECOVERY_REQUIRED)
            rollback_failure_class=$(vu_state_get rollback_failure_class "$VU_JOURNAL_FILE" 2>/dev/null || :)
            ;;
    esac
    if [ -n "$rollback_failure_class" ]; then
        vu_journal_set rollback_failure_class "$rollback_failure_class" ||
            vu_die "$VU_ROLLBACK_ERROR" "Cannot persist rollback failure class"
    fi
else
    rollback_failure_class=$(vu_state_get rollback_failure_class "$VU_JOURNAL_FILE" 2>/dev/null || :)
fi

rollback_cleanup() {
    [ "$rollback_internal" = 1 ] || vu_barrier_leave || :
    [ "$rollback_internal" = 1 ] || vu_runtime_resume || vu_log ERROR "Runtime resume failed after rollback"
    [ "$rollback_internal" = 1 ] || vu_lock_release || :
}

rollback_fail() {
    vu_transition RECOVERY_REQUIRED
    vu_die "$VU_ROLLBACK_ERROR" "$*"
}

if [ "$rollback_internal" != 1 ]; then
    vu_lock_acquire || vu_die "$VU_DEFERRED" "Another updater transaction is active"
    trap rollback_cleanup EXIT HUP INT TERM
    vu_barrier_recover_stale || vu_die "$VU_SAFETY_ERROR" "Stale or foreign update barrier cannot be recovered safely"
    vu_staging_cleanup_orphans || vu_die "$VU_SAFETY_ERROR" "Cannot clean stale updater staging"
    [ "$barrier_integration_ready" = 1 ] || vu_die "$VU_SAFETY_ERROR" "Rollback barrier integration is disabled"
    vu_runtime_quiesce || vu_die "$VU_SAFETY_ERROR" "Cannot quiesce runtime for rollback"
    vu_barrier_enter || vu_die "$VU_SAFETY_ERROR" "Cannot enter rollback barrier"
fi

backup=${1:-$(vu_state_get active_backup "$VU_JOURNAL_FILE" 2>/dev/null || :)}
[ -n "$backup" ] || vu_die "$VU_ROLLBACK_ERROR" "No active backup recorded"
case "$backup" in "$VU_BACKUP_DIR"/*) ;; *) vu_die "$VU_ROLLBACK_ERROR" "Unsafe backup path" ;; esac
[ -r "$backup/files.tsv" ] || vu_die "$VU_ROLLBACK_ERROR" "Backup index is missing"
[ -r "$backup/backup.meta" ] || vu_die "$VU_ROLLBACK_ERROR" "Backup metadata is missing"

expected_index_sha=$(vu_state_get index_sha "$backup/backup.meta" 2>/dev/null || :)
actual_index_sha=$(sha256sum "$backup/files.tsv" | awk '{print $1}')
[ -n "$expected_index_sha" ] && [ "$expected_index_sha" = "$actual_index_sha" ] ||
    rollback_fail "Backup index hash mismatch"

expected_committed_sha=$(vu_state_get committed_sha "$backup/backup.meta" 2>/dev/null || :)
if [ "$(sed -n '1p' "$backup/committed.existed" 2>/dev/null || :)" = 1 ]; then
    actual_committed_sha=$(sha256sum "$backup/committed.state" 2>/dev/null | awk '{print $1}')
    [ -n "$expected_committed_sha" ] && [ "$expected_committed_sha" = "$actual_committed_sha" ] ||
        rollback_fail "Committed metadata backup hash mismatch"
fi

vu_transition ROLLING_BACK

while IFS="$(printf '\t')" read -r target existed mode original_sha backup_sha; do
    vu_safe_target "$target" || rollback_fail "Unsafe rollback target"
    vu_local_target "$target" && rollback_fail "Protected rollback target"
    printf '%s\n' "$mode" | grep -Eq '^[0-7]{3,4}$' || rollback_fail "Invalid backup mode"
    case "$existed" in 0|1) ;; *) rollback_fail "Invalid backup existence flag" ;; esac
    if [ "$existed" = 1 ]; then
        source=$backup/files$target
        [ -f "$source" ] || rollback_fail "Backup payload missing for $target"
        actual_backup_sha=$(sha256sum "$source" | awk '{print $1}')
        [ "$actual_backup_sha" = "$backup_sha" ] && [ "$original_sha" = "$backup_sha" ] ||
            rollback_fail "Backup payload hash mismatch for $target"
    fi
done < "$backup/files.tsv"

count=0
while IFS="$(printf '\t')" read -r target existed mode original_sha backup_sha; do
    count=$((count + 1))
    if [ -n "$VU_ROOT_PREFIX" ] && [ "${VWARD_TEST_FAIL_ROLLBACK_AT:-0}" = "$count" ]; then
        rollback_fail "Injected rollback interruption"
    fi
    destination=$VU_ROOT_PREFIX$target
    if [ "$existed" = 1 ]; then
        source=$backup/files$target
        mkdir -p "$(dirname "$destination")" || rollback_fail "Cannot create rollback directory"
        tmp=$destination.rollback.$$
        cp "$source" "$tmp" && chmod "$mode" "$tmp" && sync && mv -f "$tmp" "$destination" ||
            rollback_fail "Cannot restore $target"
        restored_sha=$(sha256sum "$destination" | awk '{print $1}')
        restored_mode=$(vu_file_mode "$destination")
        [ "$restored_sha" = "$original_sha" ] && [ "$restored_mode" = "${mode#0}" ] ||
            rollback_fail "Restored file verification failed for $target"
    else
        rm -f "$destination" || rollback_fail "Cannot remove newly installed $target"
    fi
done < "$backup/files.tsv"

committed_existed=$(sed -n '1p' "$backup/committed.existed" 2>/dev/null || :)
case "$committed_existed" in
    1)
        [ -r "$backup/committed.state" ] || rollback_fail "Committed metadata backup is missing"
        vu_atomic_write "$VU_COMMITTED_FILE" "$backup/committed.state" ||
            rollback_fail "Cannot restore committed metadata"
        ;;
    0)
        rm -f "$VU_COMMITTED_FILE" || rollback_fail "Cannot remove newly committed metadata"
        ;;
    *)
        rollback_fail "Committed metadata backup flag is invalid"
        ;;
esac

sync

if [ -n "$VU_ROOT_PREFIX" ] && [ "${VWARD_TEST_CRASH_BEFORE_QUARANTINE:-0}" = 1 ]; then
    exit 99
fi

# Complete quarantine as part of the rollback transaction, BEFORE ROLLED_BACK.
# Recovery of a ROLLING_BACK journal therefore cannot reopen an auto-retry loop.
rollback_failure_class=$(vu_state_get rollback_failure_class "$VU_JOURNAL_FILE" 2>/dev/null || :)
if [ -n "$rollback_failure_class" ] && [ -r "$VU_PENDING_DIR/manifest.json" ]; then
    vu_manifest_validate "$VU_PENDING_DIR/manifest.json" ||
        rollback_fail "Pending manifest is invalid while completing quarantine"
    vu_manifest_verify_signature "$VU_PENDING_DIR/manifest.json" ||
        rollback_fail "Pending manifest signature failed while completing quarantine"
    vu_quarantine_store "$VU_PENDING_DIR/manifest.json" "$rollback_failure_class" ||
        rollback_fail "Cannot persist failed-update quarantine"
fi

vu_transition ROLLED_BACK
vu_log INFO "Rollback completed from $backup"
exit "$VU_OK"
