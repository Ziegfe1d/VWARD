#!/bin/sh

set -u

SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SELF_DIR/vward-update-common.sh"
vu_load_config

backup=${1:-$(vu_state_get active_backup 2>/dev/null || :)}
[ -n "$backup" ] || vu_die "$VU_ROLLBACK_ERROR" "No active backup recorded"
case "$backup" in "$VU_BACKUP_DIR"/*) ;; *) vu_die "$VU_ROLLBACK_ERROR" "Unsafe backup path" ;; esac
[ -r "$backup/files.tsv" ] || vu_die "$VU_ROLLBACK_ERROR" "Backup index is missing"

vu_transition ROLLING_BACK
count=0
while IFS="$(printf '\t')" read -r target existed mode; do
    count=$((count + 1))
    if [ -n "$VU_ROOT_PREFIX" ] && [ "${VWARD_TEST_FAIL_ROLLBACK_AT:-0}" = "$count" ]; then
        vu_die "$VU_ROLLBACK_ERROR" "Injected rollback interruption"
    fi
    destination=$VU_ROOT_PREFIX$target
    if [ "$existed" = 1 ]; then
        source=$backup/files$target
        [ -f "$source" ] || vu_die "$VU_ROLLBACK_ERROR" "Backup payload missing for $target"
        mkdir -p "$(dirname "$destination")" || vu_die "$VU_ROLLBACK_ERROR" "Cannot create rollback directory"
        tmp=$destination.rollback.$$
        cp "$source" "$tmp" && chmod "$mode" "$tmp" && mv -f "$tmp" "$destination" || vu_die "$VU_ROLLBACK_ERROR" "Cannot restore $target"
    else
        vu_safe_target "$target" || vu_die "$VU_ROLLBACK_ERROR" "Unsafe rollback target"
        rm -f "$destination" || vu_die "$VU_ROLLBACK_ERROR" "Cannot remove newly installed $target"
    fi
done < "$backup/files.tsv"

sync
vu_transition ROLLED_BACK
vu_log INFO "Rollback completed from $backup"
exit "$VU_OK"
