#!/bin/sh

set -u

SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SELF_DIR/vward-update-common.sh"

usage() {
    printf '%s\n' 'Usage: vward-update.sh --status|--check|--dry-run|--apply|--rollback|--recover'
}

cleanup() {
    vu_barrier_leave
    vu_lock_release
    if [ -n "${dry_run_staging:-}" ]; then
        case "$dry_run_staging" in */tmp/vward-updater-dryrun.*) rm -rf "$dry_run_staging" ;; esac
    fi
}

fetch_and_verify_manifest() {
    mkdir -p "$VU_STAGING_DIR" || vu_die "$VU_INSTALL_ERROR" "Cannot create staging directory"
    manifest=$VU_STAGING_DIR/update-manifest.json
    if [ -n "${VWARD_LOCAL_MANIFEST:-}" ]; then
        case "$VWARD_LOCAL_MANIFEST" in "$VU_STAGING_DIR"/*) ;; *) vu_die "$VU_VERIFY_ERROR" "Unsafe local manifest path" ;; esac
        cp "$VWARD_LOCAL_MANIFEST" "$manifest" || vu_die "$VU_VERIFY_ERROR" "Cannot copy local manifest"
    elif [ -n "$VU_ROOT_PREFIX" ] && [ -n "${VWARD_TEST_MANIFEST:-}" ]; then
        cp "$VWARD_TEST_MANIFEST" "$manifest" || vu_die "$VU_VERIFY_ERROR" "Cannot copy test manifest"
    else
        [ -n "$manifest_url" ] || vu_die "$VU_CONFIG_ERROR" "manifest_url is not configured"
        vu_fetch "$manifest_url" "$manifest" || vu_die "$VU_VERIFY_ERROR" "Manifest download failed"
    fi
    vu_manifest_validate "$manifest" || vu_die "$VU_VERIFY_ERROR" "Manifest structure is invalid"
    vu_manifest_verify_signature "$manifest" || vu_die "$VU_VERIFY_ERROR" "Manifest signature is invalid"
    vu_manifest_check_policy "$manifest" || vu_die "$VU_COMPAT_ERROR" "Manifest violates version, channel, replay or compatibility policy"
    VU_MANIFEST=$manifest
}

download_and_unpack() {
    manifest=$1
    package=$VU_STAGING_DIR/package.tar.gz
    package_dir=$VU_STAGING_DIR/package.$$
    expected=$(jq -r '.signed.package.sha256' "$manifest")
    expected_size=$(jq -r '.signed.package.size' "$manifest")
    if [ -n "$VU_ROOT_PREFIX" ] && [ -n "${VWARD_TEST_PACKAGE:-}" ]; then
        cp "$VWARD_TEST_PACKAGE" "$package" || vu_die "$VU_VERIFY_ERROR" "Cannot copy test package"
    else
        url=$(jq -r '.signed.package.url' "$manifest")
        vu_fetch "$url" "$package" || vu_die "$VU_VERIFY_ERROR" "Package download failed"
    fi
    actual=$(sha256sum "$package" | awk '{print $1}')
    [ "$actual" = "$expected" ] || vu_die "$VU_VERIFY_ERROR" "Package SHA-256 mismatch"
    actual_size=$(wc -c < "$package" | tr -d ' ')
    [ "$actual_size" = "$expected_size" ] || vu_die "$VU_VERIFY_ERROR" "Package size mismatch"
    mkdir -p "$package_dir" || vu_die "$VU_INSTALL_ERROR" "Cannot create package directory"
    tar -tzf "$package" | while IFS= read -r member; do
        case "$member" in ''|..|/*|*../*|../*|*/..) exit 1 ;; esac
    done || vu_die "$VU_VERIFY_ERROR" "Unsafe package member path"
    tar -tvzf "$package" | awk '{ type=substr($1,1,1); if (type != "-" && type != "d") exit 1 }' || vu_die "$VU_VERIFY_ERROR" "Package links or special files are forbidden"
    tar -xzf "$package" -C "$package_dir" || vu_die "$VU_VERIFY_ERROR" "Package extraction failed"
    vu_package_validate "$package_dir" || vu_die "$VU_VERIFY_ERROR" "Package manifest validation failed"
    VU_PACKAGE_DIR=$package_dir
}

print_plan() {
    manifest=$1
    package_dir=$2
    printf 'Version: %s\n' "$(jq -r '.signed.version' "$manifest")"
    printf 'Priority: %s\n' "$(jq -r '.signed.priority' "$manifest")"
    printf 'Sequence: %s\n' "$(jq -r '.signed.sequence' "$manifest")"
    printf '%s\n' 'Files:'
    jq -r '.files[] | "  \(.target) mode=\(.mode)"' "$package_dir/package-manifest.json"
}

create_backup() {
    package_dir=$1
    backup=$VU_BACKUP_DIR/$(date -u '+%Y%m%dT%H%M%SZ')-$$
    mkdir -p "$backup/files" || vu_die "$VU_INSTALL_ERROR" "Cannot create backup"
    : > "$backup/files.tsv" || vu_die "$VU_INSTALL_ERROR" "Cannot create backup index"
    jq -r '.files[] | [.target,.mode] | @tsv' "$package_dir/package-manifest.json" |
    while IFS="$(printf '\t')" read -r target new_mode; do
        vu_safe_target "$target" || exit 1
        source=$VU_ROOT_PREFIX$target
        if [ -e "$source" ]; then
            mode=$(stat -c '%a' "$source" 2>/dev/null || printf '%s' "$new_mode")
            mkdir -p "$backup/files$(dirname "$target")" || exit 1
            cp -p "$source" "$backup/files$target" || exit 1
            printf '%s\t1\t%s\n' "$target" "$mode" >> "$backup/files.tsv"
        else
            printf '%s\t0\t%s\n' "$target" "$new_mode" >> "$backup/files.tsv"
        fi
    done || vu_die "$VU_INSTALL_ERROR" "Backup failed"
    vu_state_set active_backup "$backup" || vu_die "$VU_INSTALL_ERROR" "Cannot record backup"
    VU_BACKUP=$backup
}

install_package() {
    package_dir=$1
    count=0
    jq -r '.files[] | [.source,.target,.mode,.sha256] | @tsv' "$package_dir/package-manifest.json" |
    while IFS="$(printf '\t')" read -r source target mode expected; do
        count=$((count + 1))
        if [ -n "$VU_ROOT_PREFIX" ] && [ "${VWARD_TEST_FAIL_INSTALL_AT:-0}" = "$count" ]; then
            exit 1
        fi
        destination=$VU_ROOT_PREFIX$target
        mkdir -p "$(dirname "$destination")" || exit 1
        tmp=$destination.vward-new.$$
        cp "$package_dir/$source" "$tmp" || exit 1
        actual=$(sha256sum "$tmp" | awk '{print $1}')
        [ "$actual" = "$expected" ] || { rm -f "$tmp"; exit 1; }
        chmod "$mode" "$tmp" && sync && mv -f "$tmp" "$destination" || exit 1
    done
}

run_health_bounded() {
    profile=$1
    "$SELF_DIR/vward-update-health.sh" "$profile" &
    health_pid=$!
    elapsed=0
    while kill -0 "$health_pid" 2>/dev/null; do
        if [ "$elapsed" -ge "$health_timeout_seconds" ]; then
            kill "$health_pid" 2>/dev/null || :
            wait "$health_pid" 2>/dev/null || :
            return 1
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    wait "$health_pid"
}

apply_update() {
    manifest=$1
    package_dir=$2
    priority=$(jq -r '.signed.priority' "$manifest")
    vu_safety_check "$priority" || vu_die "$VU_SAFETY_ERROR" "Safe-window, barrier, activity or free-space check failed"
    vu_barrier_enter || vu_die "$VU_SAFETY_ERROR" "Could not enter the update barrier"
    manifest_hash=$(sha256sum "$manifest" | awk '{print $1}')
    update_id=$(jq -r '.signed.update_id' "$manifest")
    previous_version=$(sed -n '1p' "$current_version_file")
    vu_state_set pending_update "$update_id" || vu_die "$VU_INSTALL_ERROR" "Cannot persist pending update"
    vu_state_set manifest_hash "$manifest_hash" || vu_die "$VU_INSTALL_ERROR" "Cannot persist manifest hash"
    vu_state_set previous_version "$previous_version" || vu_die "$VU_INSTALL_ERROR" "Cannot persist previous version"
    vu_transition BACKING_UP
    create_backup "$package_dir"
    backup=$VU_BACKUP
    vu_transition INSTALLING
    if ! install_package "$package_dir"; then
        rollback_policy=$(jq -r '.signed.rollback_policy' "$manifest")
        if [ "$rollback_policy" = automatic ]; then
            "$SELF_DIR/vward-update-rollback.sh" "$backup" || vu_die "$VU_ROLLBACK_ERROR" "Install and rollback both failed"
            vu_die "$VU_INSTALL_ERROR" "Install failed; rollback completed"
        fi
        vu_transition RECOVERY_REQUIRED
        vu_die "$VU_INSTALL_ERROR" "Install failed; manual recovery required"
    fi
    sync
    vu_transition VERIFYING
    profile=$(jq -r '.signed.health_profile' "$manifest")
    if ! run_health_bounded "$profile"; then
        rollback_policy=$(jq -r '.signed.rollback_policy' "$manifest")
        if [ "$rollback_policy" = automatic ]; then
            "$SELF_DIR/vward-update-rollback.sh" "$backup" || vu_die "$VU_ROLLBACK_ERROR" "Health check and rollback both failed"
            vu_die "$VU_HEALTH_ERROR" "Health check failed; rollback completed"
        fi
        vu_transition RECOVERY_REQUIRED
        vu_die "$VU_HEALTH_ERROR" "Health check failed; manual recovery required"
    fi
    sequence=$(jq -r '.signed.sequence' "$manifest")
    version=$(jq -r '.signed.version' "$manifest")
    vu_state_set last_sequence "$sequence" || vu_die "$VU_INSTALL_ERROR" "Cannot persist sequence"
    vu_state_set installed_update_id "$update_id" || vu_die "$VU_INSTALL_ERROR" "Cannot persist update id"
    vu_state_set installed_version "$version" || vu_die "$VU_INSTALL_ERROR" "Cannot persist version"
    vu_state_set last_health_check "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" || vu_die "$VU_INSTALL_ERROR" "Cannot persist health result"
    vu_state_set pending_update none || vu_die "$VU_INSTALL_ERROR" "Cannot clear pending update"
    vu_transition COMMITTED
    vu_log INFO "Update $version committed"
}

command=${1:-}
dry_run_staging=
if [ "$command" = --dry-run ]; then
    VWARD_NO_PERSIST_LOG=1
    export VWARD_NO_PERSIST_LOG
    dry_run_staging=${VWARD_DRY_RUN_DIR:-${VU_ROOT_PREFIX}/tmp/vward-updater-dryrun.$$}
    VU_STAGING_DIR=$dry_run_staging
    VU_BACKUP_DIR=$dry_run_staging/backup-probe
fi

vu_load_config
vu_require_commands awk cp curl date df grep jq kill mkdir mv openssl sed sha256sum sleep stat tar tr wc

case "$command" in
    --status)
        printf 'enabled=%s\nauto_apply=%s\nbarrier_integration_ready=%s\nphase=%s\nlast_sequence=%s\n' \
            "$update_enabled" "$auto_apply" "$barrier_integration_ready" \
            "$(vu_state_get phase 2>/dev/null || printf IDLE)" \
            "$(vu_state_get last_sequence 2>/dev/null || printf 0)"
        exit "$VU_OK"
        ;;
    --rollback)
        exec "$SELF_DIR/vward-update-rollback.sh"
        ;;
    --recover)
        phase=$(vu_state_get phase 2>/dev/null || printf IDLE)
        case "$phase" in
            INSTALLING|VERIFYING|ROLLING_BACK|RECOVERY_REQUIRED) exec "$SELF_DIR/vward-update-rollback.sh" ;;
            CHECKING|VERIFIED|BACKING_UP) vu_transition IDLE; exit "$VU_OK" ;;
            *) vu_log INFO "No interrupted transaction requires recovery"; exit "$VU_OK" ;;
        esac
        ;;
    --check|--dry-run|--apply) ;;
    *) usage >&2; exit "$VU_CONFIG_ERROR" ;;
esac

[ "$update_enabled" = 1 ] || vu_die "$VU_DEFERRED" "Updater is disabled"
vu_lock_acquire || vu_die "$VU_DEFERRED" "Another updater process is active"
trap cleanup EXIT HUP INT TERM
[ "$command" = --dry-run ] || vu_transition CHECKING
fetch_and_verify_manifest
manifest=$VU_MANIFEST
[ "$command" = --dry-run ] || vu_transition VERIFIED
if [ "$command" = --check ]; then
    printf 'Version: %s\nPriority: %s\nSequence: %s\n' "$(jq -r '.signed.version' "$manifest")" "$(jq -r '.signed.priority' "$manifest")" "$(jq -r '.signed.sequence' "$manifest")"
    vu_transition IDLE
    exit "$VU_OK"
fi
download_and_unpack "$manifest"
package_dir=$VU_PACKAGE_DIR
print_plan "$manifest" "$package_dir"

case "$command" in
    --dry-run)
        priority=$(jq -r '.signed.priority' "$manifest")
        if vu_safety_check "$priority"; then printf '%s\n' 'Safety: ready'; else printf '%s\n' 'Safety: blocked'; fi
        exit "$VU_OK"
        ;;
    --apply) apply_update "$manifest" "$package_dir" ;;
esac
