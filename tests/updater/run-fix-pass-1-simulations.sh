#!/bin/sh

set -eu

REPO=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
UPDATER=$REPO/components/update-engine
WORK=$(mktemp -d "${TMPDIR:-/tmp}/vward-fix-pass-1.XXXXXX")
trap 'rm -rf "$WORK"' EXIT HUP INT TERM
passed=0
failed=0
number=0

ok() { number=$((number + 1)); passed=$((passed + 1)); printf 'ok %s - %s\n' "$number" "$1"; }
bad() { number=$((number + 1)); failed=$((failed + 1)); printf 'not ok %s - %s\n' "$number" "$1"; }
assert() { name=$1; shift; if "$@"; then ok "$name"; else bad "$name"; fi; }

openssl genpkey -algorithm ED25519 -out "$WORK/private.pem" >/dev/null 2>&1
openssl pkey -in "$WORK/private.pem" -pubout -out "$WORK/public.pem" >/dev/null 2>&1

new_root() {
    label=$1
    ROOT=$WORK/root-$label
    mkdir -p "$ROOT/opt/etc/vward" "$ROOT/opt/etc/vward/console" "$ROOT/opt/share/vward" \
        "$ROOT/opt/bin" "$ROOT/opt/share/vward/console/www/cgi-bin" "$ROOT/opt/var/lib/vward/updater"
    cp "$WORK/public.pem" "$ROOT/opt/etc/vward/update-public.pem"
    printf '%s\n' '0.1.0-dev' > "$ROOT/opt/share/vward/VERSION"
    printf '%s\n' old > "$ROOT/opt/bin/vward-route.sh"
    printf '%s\n' wan > "$ROOT/opt/bin/vward-wan-guard.sh"
    printf '%s\n' html > "$ROOT/opt/share/vward/console/www/index.html"
    CONFIG=$ROOT/opt/etc/vward/update.conf
    {
        printf '%s\n' 'update_enabled=1' 'auto_apply=1' 'auto_critical=1' 'auto_important=1' 'auto_routine=1' 'channel=dev'
        printf '%s\n' 'manifest_url=https://example.invalid/update-manifest.json'
        printf 'public_key_file=%s\n' "$ROOT/opt/etc/vward/update-public.pem"
        printf 'current_version_file=%s\n' "$ROOT/opt/share/vward/VERSION"
        printf '%s\n' 'minimum_free_kb=1' 'max_package_size=1048576' 'staging_multiplier=2' 'barrier_integration_ready=1'
        printf '%s\n' 'safe_window_start=03:00' 'safe_window_end=05:00' 'important_max_delay_seconds=7200' 'routine_max_delay_seconds=86400'
    } > "$CONFIG"
    STATE=$ROOT/opt/var/lib/vward/updater
    printf 'installed_version=0.1.0-dev\ninstalled_update_id=bootstrap\nlast_sequence=0\nmanifest_hash=bootstrap\nlast_health_check=bootstrap\n' > "$STATE/committed.state"
}

make_package() {
    label=$1
    PKGDIR=$WORK/package-$label
    mkdir -p "$PKGDIR/files"
    printf '%s\n' "new-$label" > "$PKGDIR/files/vward-route.sh"
    printf '%s\n' "wan-$label" > "$PKGDIR/files/vward-wan-guard.sh"
    one=$(sha256sum "$PKGDIR/files/vward-route.sh" | awk '{print $1}')
    two=$(sha256sum "$PKGDIR/files/vward-wan-guard.sh" | awk '{print $1}')
    jq -n --arg one "$one" --arg two "$two" '{schema:1,files:[{source:"files/vward-route.sh",target:"/opt/bin/vward-route.sh",sha256:$one,mode:"0755",component:"route-tools",restart_policy:"none",config_policy:"program-only"},{source:"files/vward-wan-guard.sh",target:"/opt/bin/vward-wan-guard.sh",sha256:$two,mode:"0755",component:"wan-guard",restart_policy:"none",config_policy:"program-only"}]}' > "$PKGDIR/package-manifest.json"
    PACKAGE=$WORK/package-$label.tar.gz
    tar -czf "$PACKAGE" -C "$PKGDIR" .
}

make_manifest() {
    label=$1 priority=$2 sequence=${3:-1} version=${4:-0.1.1-dev}
    sha=$(sha256sum "$PACKAGE" | awk '{print $1}')
    size=$(wc -c < "$PACKAGE" | tr -d ' ')
    MANIFEST=$WORK/manifest-$label.json
    signed=$WORK/signed-$label.json
    jq -n --arg id "$label" --arg version "$version" --arg priority "$priority" --arg sha "$sha" --argjson size "$size" --argjson sequence "$sequence" '{schema:1,update_id:$id,sequence:$sequence,version:$version,channel:"dev",priority:$priority,published_at:"2026-09-07T00:00:00Z",min_updater_version:"1.0.0",package:{url:"https://example.invalid/package.tar.gz",sha256:$sha,size:$size},compatibility:{min_vward:"0.1.0-dev",max_vward:"0.1.0-dev"},affected_components:["route-tools","wan-guard"],affected_services:[],health_profile:"default",requires_reboot:false,rollback_policy:"automatic",signature:{algorithm:"Ed25519",key_id:"test-key"}}' > "$signed"
    jq -cS . "$signed" > "$signed.canonical"
    openssl pkeyutl -sign -inkey "$WORK/private.pem" -rawin -in "$signed.canonical" -out "$signed.sig"
    signature=$(openssl base64 -A -in "$signed.sig")
    jq -n --slurpfile signed "$signed" --arg signature "$signature" '{signed:$signed[0],signature:$signature}' > "$MANIFEST"
}

run_update() {
    env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" VWARD_TEST_MANIFEST="$MANIFEST" VWARD_TEST_PACKAGE="$PACKAGE" "$@" "$UPDATER/vward-update.sh" "${COMMAND:---apply}"
}

# SemVer 2.0 precedence used by development builds.
new_root semver
semver_check() {
    VWARD_ROOT_PREFIX=$ROOT VWARD_UPDATE_CONFIG=$CONFIG sh -c '. "$1"; [ "$(vu_version_cmp 0.1.0-dev 0.1.0)" = -1 ] && [ "$(vu_version_cmp 0.1.1-dev1 0.1.1-dev2)" = -1 ] && [ "$(vu_version_cmp 0.1.1-alpha 0.1.1-beta)" = -1 ] && [ "$(vu_version_cmp 0.1.1-2 0.1.1-10)" = -1 ] && [ "$(vu_version_cmp 0.1.1 0.1.1-beta)" = 1 ]' sh "$UPDATER/vward-update-common.sh"
}
assert 'SemVer prerelease precedence' semver_check

# Committed state is authoritative even when the bootstrap VERSION file is absent.
new_root installed-version; rm -f "$ROOT/opt/share/vward/VERSION"; make_package installed-version; make_manifest installed-version CRITICAL
COMMAND=--dry-run
assert 'installed version comes from committed state' run_update
unset COMMAND

# Pre-download staging rejection leaves no cached package.
new_root staging-space; make_package staging-space; make_manifest staging-space CRITICAL
set +e; VWARD_TEST_FREE_STAGING_KB=0 run_update >/dev/null 2>&1; code=$?; set -e
[ "$code" -eq 33 ] && [ ! -e "$STATE/pending/package.tar.gz" ] && ok 'staging space rejected before package copy' || bad 'staging preflight'

new_root backup-space; make_package backup-space; make_manifest backup-space CRITICAL
set +e; VWARD_TEST_FREE_BACKUP_KB=0 run_update >/dev/null 2>&1; code=$?; set -e
[ "$code" -eq 33 ] && [ "$(cat "$ROOT/opt/bin/vward-route.sh")" = old ] && ok 'backup space blocks install' || bad 'backup space preflight'

new_root target-space; make_package target-space; make_manifest target-space CRITICAL
set +e; VWARD_TEST_FREE_TARGET_KB=0 run_update >/dev/null 2>&1; code=$?; set -e
[ "$code" -eq 33 ] && [ "$(cat "$ROOT/opt/bin/vward-route.sh")" = old ] && ok 'target space blocks sibling replacement' || bad 'target space preflight'

# Allow-list matches the verified installation map.
new_root allowlist
allowlist_check() {
    VWARD_ROOT_PREFIX=$ROOT VWARD_UPDATE_CONFIG=$CONFIG sh -c '. "$1"; vu_safe_target /opt/etc/vward/console/lighttpd.conf && ! vu_safe_target /opt/etc/lighttpd/lighttpd.conf' sh "$UPDATER/vward-update-common.sh"
}
assert 'real lighttpd target accepted and old path rejected' allowlist_check

# Dry-run uses isolated runtime paths and leaves updater-owned production paths unchanged.
new_root dryrun; make_package dryrun; make_manifest dryrun CRITICAL
before=$(find "$ROOT/opt/var" -type f -o -type d | sort | sha256sum | awk '{print $1}')
COMMAND=--dry-run; run_update >/dev/null 2>&1; unset COMMAND
after=$(find "$ROOT/opt/var" -type f -o -type d | sort | sha256sum | awk '{print $1}')
[ "$before" = "$after" ] && [ ! -e "$ROOT/opt/var/run/vward/updater.lock" ] && ok 'dry-run makes zero production runtime writes' || bad 'dry-run isolation'

# Per-priority switches are independent under the master switch.
new_root auto-flags
auto_check() {
    VWARD_ROOT_PREFIX=$ROOT VWARD_UPDATE_CONFIG=$CONFIG sh -c '. "$1"; vu_load_config; auto_important=0; vu_auto_allowed CRITICAL && ! vu_auto_allowed IMPORTANT && vu_auto_allowed ROUTINE; auto_apply=0; ! vu_auto_allowed CRITICAL' sh "$UPDATER/vward-update-common.sh"
}
assert 'per-priority automatic policy' auto_check

# IMPORTANT escalates after two hours; ROUTINE remains lazy until its own threshold.
new_root schedule
schedule_check() {
    VWARD_TEST_NOW_HM=12:00 VWARD_TEST_NOW_EPOCH=10000 VWARD_ROOT_PREFIX=$ROOT VWARD_UPDATE_CONFIG=$CONFIG sh -c '. "$1"; vu_load_config; ! vu_schedule_ready IMPORTANT 3000 && ! vu_schedule_ready ROUTINE 0; important_max_delay_seconds=7000; vu_schedule_ready IMPORTANT 3000; routine_max_delay_seconds=10000; vu_schedule_ready ROUTINE 0' sh "$UPDATER/vward-update-common.sh"
}
assert 'IMPORTANT deadline and ROUTINE lazy escalation' schedule_check

# Pending survives an unchanged (304) watcher cycle and applies in the later window.
new_root pending304; make_package pending304; make_manifest pending304 ROUTINE
set +e
env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" VWARD_TEST_HTTP_STATUS=200 VWARD_TEST_WATCH_MANIFEST="$MANIFEST" VWARD_TEST_PACKAGE="$PACKAGE" VWARD_TEST_NOW_HM=12:00 VWARD_TEST_NOW_EPOCH=1000 "$UPDATER/vward-update-watch.sh" --once >"$WORK/pending-first.out" 2>&1
first_code=$?
set -e
pending_before=$(sed -n 's/^update_id=//p' "$STATE/pending/pending.state" 2>/dev/null || :)
env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" VWARD_TEST_HTTP_STATUS=304 VWARD_TEST_PACKAGE="$PACKAGE" VWARD_TEST_NOW_HM=03:30 VWARD_TEST_NOW_EPOCH=2000 "$UPDATER/vward-update-watch.sh" --once >"$WORK/pending-second.out" 2>&1
installed=$(sed -n 's/^installed_update_id=//p' "$STATE/committed.state")
if [ "$first_code" -eq 20 ] && [ "$pending_before" = pending304 ] && [ "$installed" = pending304 ] && [ "$(cat "$ROOT/opt/bin/vward-route.sh")" = new-pending304 ]; then
    ok 'deferred pending survives 304 and later applies'
else
    sed 's/^/  # first: /' "$WORK/pending-first.out"; sed 's/^/  # second: /' "$WORK/pending-second.out"
    printf '  # first_code=%s pending=%s installed=%s content=%s\n' "$first_code" "$pending_before" "$installed" "$(cat "$ROOT/opt/bin/vward-route.sh")"
    bad 'pending 304 retry'
fi

# Active, stale and malformed lock behavior.
new_root locks
LOCK=$ROOT/opt/var/run/vward/updater.lock; mkdir -p "$LOCK"
printf '#!/bin/sh\nsleep 60\n' > "$WORK/vward-update-holder.sh"; chmod 755 "$WORK/vward-update-holder.sh"
"$WORK/vward-update-holder.sh" & holder_pid=$!
printf '%s:%s:vward-update\n' "$holder_pid" "$(date +%s)" > "$LOCK/owner"
make_package locks; make_manifest locks CRITICAL; COMMAND=--check
set +e; run_update >/dev/null 2>&1; active_code=$?; set -e
[ "$active_code" -eq 20 ] && ok 'active updater lock blocks second transaction' || bad 'active lock rejection'
kill "$holder_pid" 2>/dev/null || :; wait "$holder_pid" 2>/dev/null || :
printf '999999:%s:vward-update\n' "$(date +%s)" > "$LOCK/owner"
assert 'dead PID stale lock is recovered' run_update
rm -rf "$LOCK"; mkdir -p "$LOCK"; printf '%s\n' malformed > "$LOCK/owner"
set +e; run_update >/dev/null 2>&1; malformed_code=$?; set -e
[ "$malformed_code" -eq 20 ] && [ -d "$LOCK" ] && ok 'malformed lock fails conservatively' || bad 'malformed lock policy'
unset COMMAND

rm -rf "$LOCK"; mkdir -p "$LOCK"; "$WORK/vward-update-holder.sh" & holder_pid=$!; printf '%s:%s:vward-update\n' "$holder_pid" "$(date +%s)" > "$LOCK/owner"
set +e
env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" "$UPDATER/vward-update-rollback.sh" >/dev/null 2>&1; rollback_race=$?
env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" "$UPDATER/vward-update.sh" --recover >/dev/null 2>&1; recover_race=$?
set -e
if [ "$rollback_race" -eq 20 ] && [ "$recover_race" -eq 20 ]; then ok 'rollback and recovery cannot race active updater'; else printf '  # rollback=%s recover=%s\n' "$rollback_race" "$recover_race"; bad 'rollback/recovery mutual exclusion'; fi
kill "$holder_pid" 2>/dev/null || :; wait "$holder_pid" 2>/dev/null || :
rm -rf "$LOCK"

set +e; env VWARD_INTERNAL_ROLLBACK=1 VWARD_INTERNAL_ROLLBACK_TOKEN=forged VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" "$UPDATER/vward-update-rollback.sh" >/dev/null 2>&1; forged_code=$?; set -e
[ "$forged_code" -eq 33 ] && ok 'forged internal rollback ownership is rejected' || bad 'internal rollback ownership validation'

# Crash boundaries before the atomic committed snapshot recover to old files and metadata.
for point in after_installed_version after_sequence before_snapshot; do
    new_root "crash-$point"; make_package "crash-$point"; make_manifest "crash-$point" CRITICAL
    set +e; VWARD_TEST_CRASH_COMMIT=$point run_update >/dev/null 2>&1; crash_code=$?; set -e
    env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" "$UPDATER/vward-update.sh" --recover >/dev/null 2>&1
    committed=$(sed -n 's/^installed_update_id=//p' "$STATE/committed.state")
    [ "$crash_code" -eq 99 ] && [ "$committed" = bootstrap ] && [ "$(cat "$ROOT/opt/bin/vward-route.sh")" = old ] && ok "commit crash $point restores old transaction" || bad "commit crash $point"
done

# Crash after atomic snapshot finalizes the new transaction on recovery.
new_root crash-after; make_package crash-after; make_manifest crash-after CRITICAL
set +e; VWARD_TEST_CRASH_COMMIT=after_snapshot run_update >/dev/null 2>&1; crash_code=$?; set -e
env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" "$UPDATER/vward-update.sh" --recover >/dev/null 2>&1
committed=$(sed -n 's/^installed_update_id=//p' "$STATE/committed.state")
[ "$crash_code" -eq 99 ] && [ "$committed" = crash-after ] && [ "$(cat "$ROOT/opt/bin/vward-route.sh")" = new-crash-after ] && ok 'post-snapshot recovery finalizes new transaction' || bad 'post-snapshot recovery'

# Explicit rollback restores program files and previous committed metadata.
new_root metadata-rollback; make_package metadata-rollback; make_manifest metadata-rollback CRITICAL
run_update >/dev/null 2>&1
env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" "$UPDATER/vward-update-rollback.sh" >/dev/null 2>&1
committed=$(sed -n 's/^installed_update_id=//p' "$STATE/committed.state")
[ "$committed" = bootstrap ] && [ "$(cat "$ROOT/opt/bin/vward-route.sh")" = old ] && ok 'rollback restores committed metadata and files' || bad 'rollback metadata restore'

# Corrupted backup is rejected before restore and leaves a stable recovery state.
new_root corrupt-backup; make_package corrupt-backup; make_manifest corrupt-backup CRITICAL
run_update >/dev/null 2>&1
backup=$(sed -n 's/^active_backup=//p' "$STATE/journal.state")
printf corrupt >> "$backup/files/opt/bin/vward-route.sh"
set +e; env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" "$UPDATER/vward-update-rollback.sh" >/dev/null 2>&1; corrupt_code=$?; set -e
phase=$(sed -n 's/^phase=//p' "$STATE/journal.state")
[ "$corrupt_code" -eq 42 ] && [ "$phase" = RECOVERY_REQUIRED ] && [ "$(cat "$ROOT/opt/bin/vward-route.sh")" = new-corrupt-backup ] && ok 'corrupted backup fails closed' || bad 'backup corruption rejection'

# Successful apply cleans transaction staging and pending artifacts.
new_root cleanup; make_package cleanup; make_manifest cleanup CRITICAL
run_update >/dev/null 2>&1
leftovers=$(find "$ROOT/opt/var/cache/vward/updater" -type f 2>/dev/null | wc -l | tr -d ' ')
pending_files=$(find "$STATE/pending" -type f 2>/dev/null | wc -l | tr -d ' ')
[ "$leftovers" -eq 0 ] && [ "$pending_files" -eq 0 ] && ok 'successful apply cleans transient staging' || bad 'staging cleanup'

printf '1..%s\n' "$number"
printf '# passed=%s failed=%s\n' "$passed" "$failed"
[ "$failed" -eq 0 ]
