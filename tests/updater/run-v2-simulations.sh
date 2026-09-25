#!/bin/sh
# Update Engine 2: per-file updates and engine self-update.
#
# A router with the engine in slot A (current -> slots/A) gets signed schema-2
# manifests.  Only files whose content or mode differ are fetched, backed up and
# replaced; a tampered or missing file stops the update; a newer signed engine
# goes into slot B after its self-test and finishes the update itself; a broken
# one never becomes current; --engine-adopt moves an engine 1 router over.

set -u

REPO=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ENGINE_SRC=$REPO/components/update-engine
. "$REPO/tests/updater/seed-runtime.sh"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/vward-updater-v2.XXXXXX")
trap 'rm -rf "$WORK"' EXIT HUP INT TERM

passed=0 failed=0 case_number=0
pass() { passed=$((passed + 1)); case_number=$((case_number + 1)); printf 'ok %s - %s\n' "$case_number" "$1"; }
fail() { failed=$((failed + 1)); case_number=$((case_number + 1)); printf 'not ok %s - %s\n' "$case_number" "$1"; }
check() { name=$1; shift; if "$@"; then pass "$name"; else fail "$name"; sed 's/^/  # /' "$WORK/last.out" 2>/dev/null | tail -n 15; fi; }

openssl genpkey -algorithm ED25519 -out "$WORK/private.pem" >/dev/null 2>&1
openssl pkey -in "$WORK/private.pem" -pubout -out "$WORK/public.pem" >/dev/null 2>&1

ENGINE_FILES="vward-update-bootstrap.sh vward-update-common-base.sh vward-update-common.sh vward-update-delta.sh
vward-update-hardening.sh vward-update-health.sh vward-update-rollback.sh vward-update-watch.sh vward-update.sh"

# engine_dir NAME VERSION: a copy of this engine that reports VERSION.
engine_dir() {
    dir=$WORK/engine-$1
    mkdir -p "$dir"
    for f in $ENGINE_FILES; do cp "$ENGINE_SRC/$f" "$dir/$f"; done
    cp "$REPO/config/components/component-registry.json" "$dir/component-registry.json"
    sed -i "s/^VU_ENGINE_VERSION=.*/VU_ENGINE_VERSION=$2/" "$dir/vward-update-common-base.sh"
    printf '%s\n' "$dir"
}

CUR_ENGINE=$(engine_dir current 2.0.0)

new_root() {
    ROOT=$WORK/root-$1
    mkdir -p "$ROOT/opt/etc/vward" "$ROOT/opt/share/vward/console/www" "$ROOT/opt/bin" "$ROOT/opt/var/lib/vward/updater"
    cp "$WORK/public.pem" "$ROOT/opt/etc/vward/update-public.pem"
    printf '%s\n' '0.2.0-rc.1' > "$ROOT/opt/share/vward/VERSION"
    printf '%s\n' route-old > "$ROOT/opt/bin/vward-route.sh"
    printf '%s\n' wan-same > "$ROOT/opt/bin/vward-wan-guard.sh"
    printf '%s\n' html > "$ROOT/opt/share/vward/console/www/index.html"
    chmod 0755 "$ROOT/opt/bin/vward-route.sh" "$ROOT/opt/bin/vward-wan-guard.sh"
    CONFIG=$ROOT/opt/etc/vward/update.conf
    {
        printf '%s\n' 'update_enabled=1' 'auto_apply=0' 'channel=dev'
        printf 'public_key_file=%s\n' "$ROOT/opt/etc/vward/update-public.pem"
        printf 'current_version_file=%s\n' "$ROOT/opt/share/vward/VERSION"
        printf '%s\n' 'minimum_free_kb=1' 'barrier_integration_ready=1' 'safe_window_start=00:00' 'safe_window_end=23:59'
    } > "$CONFIG"
    seed_runtime "$ROOT" || exit 1
    SLOTS=$ROOT/opt/share/vward/updater
    mkdir -p "$SLOTS/slots"
    cp -R "$(engine_dir "slot-$1" "${2:-2.0.0}")" "$SLOTS/slots/A"
    ln -s "$SLOTS/slots/A" "$SLOTS/current"
    FILES=$WORK/files-$1
    mkdir -p "$FILES"
}

# blob FILE: stored under its sha256 in FILES; prints "sha size".
blob() {
    digest=$(sha256sum "$1" | awk '{print $1}')
    cp "$1" "$FILES/$digest"
    printf '%s %s\n' "$digest" "$(wc -c < "$1" | tr -d ' ')"
}

# make_manifest LABEL VERSION SEQUENCE ENGINE_DIR [ENGINE_VERSION]: route.sh new,
# wan-guard unchanged; the engine section from ENGINE_DIR.
make_manifest() {
    label=$1 version=$2 sequence=$3 edir=$4 ever=${5:-}
    printf '%s\n' "route-$label" > "$WORK/route-$label"
    set -- $(blob "$WORK/route-$label"); route_sha=$1 route_size=$2
    set -- $(blob "$ROOT/opt/bin/vward-wan-guard.sh"); wan_sha=$1 wan_size=$2
    : > "$WORK/engine-$label.tsv"
    for f in $ENGINE_FILES component-registry.json; do
        set -- $(blob "$edir/$f")
        case "$f" in *.sh) m=0755 ;; *) m=0644 ;; esac
        printf '%s\t%s\t%s\t%s\n' "$f" "$1" "$2" "$m" >> "$WORK/engine-$label.tsv"
    done
    [ -n "$ever" ] || ever=$(sed -n 's/^VU_ENGINE_VERSION=//p' "$edir/vward-update-common-base.sh")
    signed=$WORK/signed-$label.json
    jq -n --arg version "$version" --argjson sequence "$sequence" --arg rs "$route_sha" --argjson rz "$route_size" \
        --arg ws "$wan_sha" --argjson wz "$wan_size" --arg ever "$ever" --rawfile e "$WORK/engine-$label.tsv" '
        {schema:2,update_id:("test-v2-"+($sequence|tostring)),sequence:$sequence,version:$version,channel:"dev",priority:"ROUTINE",
         published_at:"2026-09-25T00:00:00Z",min_updater_version:"2.0.0",files_base:"https://example.invalid/files/",
         files:[{target:"/opt/bin/vward-route.sh",sha256:$rs,size:$rz,mode:"0755",component:"route-tools"},
                {target:"/opt/bin/vward-wan-guard.sh",sha256:$ws,size:$wz,mode:"0755",component:"wan-guard"}],
         engine:{version:$ever,files:($e | split("\n") | map(select(length > 0) | split("\t") | {name:.[0],sha256:.[1],size:(.[2]|tonumber),mode:.[3]}))},
         compatibility:{min_vward:"0.1.0-dev",max_vward:$version},affected_components:["route-tools","wan-guard"],affected_services:[],
         health_profile:"default",requires_reboot:false,rollback_policy:"automatic",signature:{algorithm:"Ed25519",key_id:"test-key"}}' > "$signed"
    jq -cS . "$signed" > "$signed.c"
    openssl pkeyutl -sign -inkey "$WORK/private.pem" -rawin -in "$signed.c" -out "$signed.sig"
    MANIFEST=$WORK/manifest-$label.json
    jq -n --slurpfile s "$signed" --arg sig "$(openssl base64 -A -in "$signed.sig")" '{signed:$s[0],signature:$sig}' > "$MANIFEST"
}

run() {
    VWARD_ROOT_PREFIX=$ROOT VWARD_UPDATE_CONFIG=$CONFIG VWARD_TEST_MANIFEST=$MANIFEST VWARD_TEST_FILES_DIR=$FILES \
        VWARD_UPDATER_ROOT=$SLOTS "$SLOTS/current/vward-update.sh" "$@" > "$WORK/last.out" 2>&1
}
slot() { CDPATH= cd -- "$SLOTS/current" && pwd -P; }
inode() { ls -i "$1" | awk '{print $1}'; }

# 1. Only what differs is fetched, backed up and replaced.
new_root delta
make_manifest delta 0.2.0-rc.2 10 "$CUR_ENGINE"
wan_inode=$(inode "$ROOT/opt/bin/vward-wan-guard.sh")
run --apply; rc=$?
backup=$(sed -n 's/^active_backup=//p' "$ROOT/opt/var/lib/vward/updater/journal.state" | tail -n 1)
check 'per-file update applies' [ "$rc" -eq 0 ]
check 'the changed file is replaced' [ "$(cat "$ROOT/opt/bin/vward-route.sh")" = route-delta ]
check 'an unchanged file is not touched' [ "$(inode "$ROOT/opt/bin/vward-wan-guard.sh")" = "$wan_inode" ]
check 'only the changed file is backed up' [ "$(grep -c . "$backup/files.tsv")" = 1 ]
check 'the plan says 1 of 2 files' grep -q 'Changed files: 1 of 2' "$WORK/last.out"
check 'every signed file is recorded as installed' jq -e '.components["wan-guard"].files["/opt/bin/vward-wan-guard.sh"] and .components["route-tools"].files["/opt/bin/vward-route.sh"]' "$ROOT/opt/var/lib/vward/updater/components.json" >/dev/null
check 'the last run is recorded' grep -qx 'changed_files=1' "$ROOT/opt/var/lib/vward/updater/last-apply.state"
check 'the version is committed' grep -qx 'installed_version=0.2.0-rc.2' "$ROOT/opt/var/lib/vward/updater/committed.state"
check 'the engine stays in slot A' [ "$(slot)" = "$SLOTS/slots/A" ]

# 2. A file that differs from its signed sha256 stops everything.
new_root tampered
make_manifest tampered 0.2.0-rc.2 10 "$CUR_ENGINE"
for f in "$FILES"/*; do [ "$(cat "$f")" = route-tampered ] && printf 'evil\n' > "$f"; done
run --apply; rc=$?
check 'a tampered file is refused' [ "$rc" -eq 31 ]
check 'nothing changes after a refused file' [ "$(cat "$ROOT/opt/bin/vward-route.sh")" = route-old ]

# 3. A missing file stops everything too.
new_root missing
make_manifest missing 0.2.0-rc.2 10 "$CUR_ENGINE"
route_sha=$(jq -r '.signed.files[0].sha256' "$MANIFEST"); rm -f "$FILES/$route_sha"
run --apply; rc=$?
check 'a missing file is refused' [ "$rc" -eq 31 ]

# 4. A mode that differs counts as a change.
new_root mode
chmod 0644 "$ROOT/opt/bin/vward-wan-guard.sh"
make_manifest mode 0.2.0-rc.2 10 "$CUR_ENGINE"
run --apply; rc=$?
check 'a file with the wrong mode is replaced' sh -c '[ "$1" -eq 0 ] && grep -q "Changed files: 2 of 2" "$2" && [ -x "$3" ]' sh "$rc" "$WORK/last.out" "$ROOT/opt/bin/vward-wan-guard.sh"

# 5. Nothing differs: the version is committed without touching any file.
new_root same
make_manifest same 0.2.0-rc.2 10 "$CUR_ENGINE"
cp "$WORK/route-same" "$ROOT/opt/bin/vward-route.sh"; chmod 0755 "$ROOT/opt/bin/vward-route.sh"
run --apply; rc=$?
check 'an update without changed files commits' sh -c '[ "$1" -eq 0 ] && grep -q "Changed files: 0 of 2" "$2" && grep -qx installed_version=0.2.0-rc.2 "$3"' sh "$rc" "$WORK/last.out" "$ROOT/opt/var/lib/vward/updater/committed.state"

# 6. A dry run changes nothing, the engine included.
new_root dry
make_manifest dry 0.2.0-rc.2 10 "$(engine_dir dry-new 2.0.1)"
run --dry-run; rc=$?
check 'a dry run plans without changing anything' sh -c '[ "$1" -eq 0 ] && grep -q "Changed files: 1 of 2" "$2" && [ "$(cat "$3")" = route-old ]' sh "$rc" "$WORK/last.out" "$ROOT/opt/bin/vward-route.sh"
check 'a dry run leaves the engine alone' [ "$(slot)" = "$SLOTS/slots/A" ]

# 7. A newer signed engine goes to slot B and finishes the update itself.
new_root engine
make_manifest engine 0.2.0-rc.2 10 "$(engine_dir new 2.0.1)"
run --apply; rc=$?
check 'the update with a new engine applies' [ "$rc" -eq 0 ]
check 'the new engine is current in slot B' [ "$(slot)" = "$SLOTS/slots/B" ]
check 'slot B holds the new engine' grep -qx 'VU_ENGINE_VERSION=2.0.1' "$SLOTS/slots/B/vward-update-common-base.sh"
check 'the switch is logged' grep -q 'Update engine 2.0.0 -> 2.0.1' "$WORK/last.out"
check 'the new engine finished the files' sh -c '[ "$(cat "$1")" = route-engine ] && grep -qx engine_version=2.0.1 "$2"' sh "$ROOT/opt/bin/vward-route.sh" "$ROOT/opt/var/lib/vward/updater/last-apply.state"
check 'slot A is kept for a revert' grep -qx 'VU_ENGINE_VERSION=2.0.0' "$SLOTS/slots/A/vward-update-common-base.sh"
run --engine-revert; rc=$?
check 'the engine can go back to the previous slot' sh -c '[ "$1" -eq 0 ] && [ "$2" = "$3" ]' sh "$rc" "$(slot)" "$SLOTS/slots/A"

# 8. An engine that fails its self-test never becomes current; the update still applies.
new_root broken
broken=$(engine_dir broken 2.0.1)
make_manifest broken 0.2.0-rc.2 10 "$broken" 2.0.2
run --apply; rc=$?
check 'a broken engine is not switched to' [ "$(slot)" = "$SLOTS/slots/A" ]
check 'the old engine finishes the update' sh -c '[ "$1" -eq 0 ] && [ "$(cat "$2")" = route-broken ]' sh "$rc" "$ROOT/opt/bin/vward-route.sh"

# 9. An older engine in a manifest is never installed.
new_root older
make_manifest older 0.2.0-rc.2 10 "$(engine_dir older 1.9.0)"
run --apply; rc=$?
check 'an older engine is ignored' sh -c '[ "$1" -eq 0 ] && [ "$2" = "$3" ]' sh "$rc" "$(slot)" "$SLOTS/slots/A"

# 10. The move from engine 1: the new engine, unpacked by the old installation, adopts itself.
new_root adopt 1.2.0
sed -i '/^VU_ENGINE_VERSION=/d; s/^minimum_updater_version=.*/minimum_updater_version=1.2.0/' "$SLOTS/slots/A/vward-update-common-base.sh"
make_manifest adopt 0.2.0-rc.2 10 "$CUR_ENGINE"
stage=$WORK/adopt-stage; mkdir -p "$stage"
jq -r '.signed.engine.files[] | [.name, .sha256] | @tsv' "$MANIFEST" | while IFS="$(printf '\t')" read -r n s; do cp "$FILES/$s" "$stage/$n"; done
adopt() {
    VWARD_ROOT_PREFIX=$ROOT VWARD_UPDATE_CONFIG=$CONFIG VWARD_UPDATER_ROOT=$SLOTS sh "$stage/vward-update.sh" --engine-adopt "$stage" "$1" > "$WORK/last.out" 2>&1
}
printf 'tampered\n' >> "$stage/vward-update-watch.sh"
adopt "$MANIFEST"; rc=$?
check 'adopt refuses engine files that differ from the signed list' sh -c '[ "$1" -ne 0 ] && [ "$2" = "$3" ]' sh "$rc" "$(slot)" "$SLOTS/slots/A"
cp "$ENGINE_SRC/vward-update-watch.sh" "$stage/vward-update-watch.sh"
printf 'highest_seen_sequence=11\n' > "$ROOT/opt/var/lib/vward/updater/trust.state"
adopt "$MANIFEST"; rc=$?
check 'adopt refuses a manifest older than the trusted one' sh -c '[ "$1" -ne 0 ] && [ "$2" = "$3" ]' sh "$rc" "$(slot)" "$SLOTS/slots/A"
rm -f "$ROOT/opt/var/lib/vward/updater/trust.state"
adopt "$MANIFEST"; rc=$?
check 'engine 2 adopts itself into slot B' sh -c '[ "$1" -eq 0 ] && [ "$2" = "$3" ] && grep -q "^VU_ENGINE_VERSION=" "$3/vward-update-common-base.sh"' sh "$rc" "$(slot)" "$SLOTS/slots/B"
run --apply; rc=$?
check 'after the move the engine applies per-file updates' sh -c '[ "$1" -eq 0 ] && [ "$(cat "$2")" = route-adopt ]' sh "$rc" "$ROOT/opt/bin/vward-route.sh"

# 11. A failed health check rolls back exactly the replaced files.
new_root health
make_manifest health 0.2.0-rc.2 10 "$CUR_ENGINE"
VWARD_TEST_FORCE_HEALTH_FAIL=1 run --apply; rc=$?
check 'a failed health check rolls the changed file back' sh -c '[ "$1" -eq 41 ] && [ "$(cat "$2")" = route-old ] && [ "$(cat "$3")" = wan-same ]' sh "$rc" "$ROOT/opt/bin/vward-route.sh" "$ROOT/opt/bin/vward-wan-guard.sh"

# 12. The v1 feed still works with engine 2 (full package).
new_root v1
REPO_ROOT=$REPO
mkdir -p "$WORK/pkg-v1/files"
printf 'route-v1\n' > "$WORK/pkg-v1/files/vward-route.sh"
d=$(sha256sum "$WORK/pkg-v1/files/vward-route.sh" | awk '{print $1}')
jq -n --arg d "$d" '{schema:1,files:[{source:"files/vward-route.sh",target:"/opt/bin/vward-route.sh",sha256:$d,mode:"0755",component:"route-tools",restart_policy:"none",config_policy:"program-only"}]}' > "$WORK/pkg-v1/package-manifest.json"
tar -czf "$WORK/pkg-v1.tar.gz" -C "$WORK/pkg-v1" .
ps=$(sha256sum "$WORK/pkg-v1.tar.gz" | awk '{print $1}'); pz=$(wc -c < "$WORK/pkg-v1.tar.gz" | tr -d ' ')
signed=$WORK/signed-v1.json
jq -n --arg s "$ps" --argjson z "$pz" '{schema:1,update_id:"test-v1",sequence:10,version:"0.2.0-rc.2",channel:"dev",priority:"ROUTINE",published_at:"2026-09-25T00:00:00Z",min_updater_version:"1.0.0",package:{url:"https://example.invalid/p.tar.gz",sha256:$s,size:$z},compatibility:{min_vward:"0.1.0-dev",max_vward:"0.2.0-rc.2"},affected_components:["route-tools"],affected_services:[],health_profile:"default",requires_reboot:false,rollback_policy:"automatic",signature:{algorithm:"Ed25519",key_id:"test-key"}}' > "$signed"
jq -cS . "$signed" > "$signed.c"; openssl pkeyutl -sign -inkey "$WORK/private.pem" -rawin -in "$signed.c" -out "$signed.sig"
MANIFEST=$WORK/manifest-v1.json
jq -n --slurpfile s "$signed" --arg sig "$(openssl base64 -A -in "$signed.sig")" '{signed:$s[0],signature:$sig}' > "$MANIFEST"
VWARD_TEST_PACKAGE=$WORK/pkg-v1.tar.gz run --apply; rc=$?
check 'engine 2 still installs a full v1 package' sh -c '[ "$1" -eq 0 ] && [ "$(cat "$2")" = route-v1 ]' sh "$rc" "$ROOT/opt/bin/vward-route.sh"

# 13. Without any command: hourly housekeeping moves an engine 1 router over.
new_root move 1.2.0
sed -i '/^VU_ENGINE_VERSION=/d; s/^minimum_updater_version=.*/minimum_updater_version=1.2.0/' "$SLOTS/slots/A/vward-update-common-base.sh"
printf '%s\n' 'manifest_url=https://example.invalid/updates/dev/update-manifest.json' >> "$CONFIG"
mkdir -p "$ROOT/tmp" "$ROOT/opt/var/log"
make_manifest move 0.2.0-rc.2 10 "$CUR_ENGINE"
source_dir=$WORK/move-source; mkdir -p "$source_dir"; cp "$MANIFEST" "$source_dir/manifest.json"; cp -R "$FILES" "$source_dir/files"
housekeeping() {
    VWARD_ROOT_PREFIX=$ROOT VWARD_UPDATE_CONFIG=$CONFIG VWARD_ENGINE_MOVE_SOURCE=$source_dir \
        VWARD_ADMISSION_LIB=$REPO/components/runtime/lib/vward-runtime-admission.sh VWARD_CONSOLE_CONFIG_BIN=/nonexistent \
        VWARD_BACKUP_DAY_FILE=$WORK/backup-day sh "$REPO/components/runtime/scripts/vward-housekeeping.sh" > "$WORK/last.out" 2>&1
}
jq '.signature = "AAAA"' "$MANIFEST" > "$source_dir/manifest.json"
housekeeping
check 'the move refuses an unsigned manifest' sh -c '[ "$1" = "$2" ] && grep -q "engine_move=failed" "$3"' sh "$(slot)" "$SLOTS/slots/A" "$ROOT/opt/var/log/vward-housekeeping.log"
cp "$MANIFEST" "$source_dir/manifest.json"
housekeeping
check 'housekeeping moves engine 1 to engine 2' sh -c 'grep -q ENGINE_MOVED "$1" && [ "$2" = "$3" ] && grep -q "^VU_ENGINE_VERSION=2" "$3/vward-update-common-base.sh"' sh "$WORK/last.out" "$(slot)" "$SLOTS/slots/B"
housekeeping
check 'the move happens once' sh -c '! grep -q ENGINE_MOVED "$1" && [ "$2" = "$3" ]' sh "$WORK/last.out" "$(slot)" "$SLOTS/slots/B"

printf 'v2 simulations: %s passed, %s failed\n' "$passed" "$failed"
[ "$failed" -eq 0 ]
