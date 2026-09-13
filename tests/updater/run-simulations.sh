#!/bin/sh

set -eu

REPO=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
UPDATER=$REPO/components/update-engine
WORK=$(mktemp -d "${TMPDIR:-/tmp}/vward-updater-test.XXXXXX")
trap 'rm -rf "$WORK"' EXIT HUP INT TERM

passed=0
failed=0

case_number=0
pass() { passed=$((passed + 1)); case_number=$((case_number + 1)); printf 'ok %s - %s\n' "$case_number" "$1"; }
fail() { failed=$((failed + 1)); case_number=$((case_number + 1)); printf 'not ok %s - %s\n' "$case_number" "$1"; }
expect_code() {
    name=$1 expected=$2
    shift 2
    set +e
    "$@" >"$WORK/last.out" 2>&1
    actual=$?
    set -e
    if [ "$actual" -eq "$expected" ]; then
        pass "$name"
    else
        sed 's/^/  # /' "$WORK/last.out"
        fail "$name (expected $expected, got $actual)"
    fi
}

openssl genpkey -algorithm ED25519 -out "$WORK/private.pem" >/dev/null 2>&1
openssl pkey -in "$WORK/private.pem" -pubout -out "$WORK/public.pem" >/dev/null 2>&1

new_root() {
    ROOT=$WORK/root-$1
    mkdir -p "$ROOT/opt/etc/vward" "$ROOT/opt/share/vward" "$ROOT/opt/bin" \
        "$ROOT/opt/share/vward/console/www" "$ROOT/opt/var/lib/vward/updater"
    cp "$WORK/public.pem" "$ROOT/opt/etc/vward/update-public.pem"
    printf '%s\n' '0.1.0-dev' > "$ROOT/opt/share/vward/VERSION"
    printf '%s\n' old > "$ROOT/opt/bin/vward-route.sh"
    printf '%s\n' wan > "$ROOT/opt/bin/vward-wan-guard.sh"
    printf '%s\n' html > "$ROOT/opt/share/vward/console/www/index.html"
    CONFIG=$ROOT/opt/etc/vward/update.conf
    {
        printf '%s\n' 'update_enabled=1' 'auto_apply=0' 'channel=dev'
        printf 'public_key_file=%s\n' "$ROOT/opt/etc/vward/update-public.pem"
        printf 'current_version_file=%s\n' "$ROOT/opt/share/vward/VERSION"
        printf '%s\n' 'minimum_free_kb=1' 'barrier_integration_ready=1' 'safe_window_start=00:00' 'safe_window_end=23:59'
    } > "$CONFIG"
}

make_package() {
    label=$1
    PKGDIR=$WORK/package-$label
    mkdir -p "$PKGDIR/files"
    printf '%s\n' "new-$label" > "$PKGDIR/files/vward-route.sh"
    printf '%s\n' "wan-$label" > "$PKGDIR/files/vward-wan-guard.sh"
    digest=$(sha256sum "$PKGDIR/files/vward-route.sh" | awk '{print $1}')
    wan_digest=$(sha256sum "$PKGDIR/files/vward-wan-guard.sh" | awk '{print $1}')
    jq -n --arg digest "$digest" --arg wan_digest "$wan_digest" '{schema:1,files:[{source:"files/vward-route.sh",target:"/opt/bin/vward-route.sh",sha256:$digest,mode:"0755",component:"route-tools",restart_policy:"none",config_policy:"program-only"},{source:"files/vward-wan-guard.sh",target:"/opt/bin/vward-wan-guard.sh",sha256:$wan_digest,mode:"0755",component:"wan-guard",restart_policy:"none",config_policy:"program-only"}]}' > "$PKGDIR/package-manifest.json"
    PACKAGE=$WORK/package-$label.tar.gz
    tar -czf "$PACKAGE" -C "$PKGDIR" .
}

make_manifest() {
    label=$1 priority=$2 sequence=$3 version=$4
    sha=$(sha256sum "$PACKAGE" | awk '{print $1}')
    size=$(wc -c < "$PACKAGE" | tr -d ' ')
    MANIFEST=$WORK/manifest-$label.json
    signed=$WORK/signed-$label.json
    jq -n --arg version "$version" --arg priority "$priority" --arg sha "$sha" --argjson size "$size" --argjson sequence "$sequence" \
      '{schema:1,update_id:("test-"+($sequence|tostring)+"-"+$priority),sequence:$sequence,version:$version,channel:"dev",priority:$priority,published_at:"2026-09-07T00:00:00Z",min_updater_version:"1.0.0",package:{url:"https://example.invalid/package.tar.gz",sha256:$sha,size:$size},compatibility:{min_vward:"0.1.0-dev",max_vward:"0.1.0-dev"},affected_components:["route-tools","wan-guard"],affected_services:[],health_profile:"default",requires_reboot:false,rollback_policy:"automatic",signature:{algorithm:"Ed25519",key_id:"test-key"}}' > "$signed"
    jq -cS . "$signed" > "$signed.canonical"
    openssl pkeyutl -sign -inkey "$WORK/private.pem" -rawin -in "$signed.canonical" -out "$signed.sig"
    signature=$(openssl base64 -A -in "$signed.sig")
    jq -n --slurpfile signed "$signed" --arg signature "$signature" '{signed:$signed[0],signature:$signature}' > "$MANIFEST"
}

run_update() {
    VWARD_ROOT_PREFIX=$ROOT VWARD_UPDATE_CONFIG=$CONFIG VWARD_TEST_MANIFEST=$MANIFEST VWARD_TEST_PACKAGE=$PACKAGE \
        "$UPDATER/vward-update.sh" "$@"
}

for item in ROUTINE IMPORTANT CRITICAL; do
    new_root "priority-$item"
    make_package "priority-$item"
    make_manifest "priority-$item" "$item" 1 0.1.1-dev
    expect_code "priority $item validates" 0 run_update --dry-run
done

new_root malformed; make_package malformed; make_manifest malformed ROUTINE 1 0.1.1-dev
jq 'del(.signed.package.sha256)' "$MANIFEST" > "$MANIFEST.bad" && MANIFEST=$MANIFEST.bad
expect_code 'malformed manifest rejected' 31 run_update --dry-run

new_root package-sha; make_package package-sha; make_manifest package-sha ROUTINE 1 0.1.1-dev
printf x >> "$PACKAGE"
expect_code 'package digest mismatch rejected' 31 run_update --dry-run

new_root signature; make_package signature; make_manifest signature ROUTINE 1 0.1.1-dev
jq '.signature="AAAA"' "$MANIFEST" > "$MANIFEST.bad" && MANIFEST=$MANIFEST.bad
expect_code 'invalid signature rejected' 31 run_update --dry-run

new_root replay; make_package replay; make_manifest replay ROUTINE 1 0.1.1-dev
    printf 'installed_version=0.1.0-dev\ninstalled_update_id=old\nlast_sequence=1\nmanifest_hash=old\nlast_health_check=old\n' > "$ROOT/opt/var/lib/vward/updater/committed.state"
set +e
run_update --dry-run >/dev/null 2>&1; replay_code=$?
new_root downgrade; make_package downgrade; make_manifest downgrade ROUTINE 1 0.0.9
run_update --dry-run >/dev/null 2>&1; downgrade_code=$?
set -e
[ "$replay_code" -eq 32 ] && [ "$downgrade_code" -eq 32 ] && pass 'downgrade and replay rejected' || fail 'downgrade/replay rejection'

new_root compatibility; make_package compatibility; make_manifest compatibility ROUTINE 1 0.1.1-dev
jq '.compatibility.min_vward="0.2.0"' "$WORK/signed-compatibility.json" > "$WORK/signed-compatibility.changed"
mv "$WORK/signed-compatibility.changed" "$WORK/signed-compatibility.json"
jq -cS . "$WORK/signed-compatibility.json" > "$WORK/re-sign"
openssl pkeyutl -sign -inkey "$WORK/private.pem" -rawin -in "$WORK/re-sign" -out "$WORK/re-sign.sig"
sig=$(openssl base64 -A -in "$WORK/re-sign.sig")
jq -n --slurpfile signed "$WORK/signed-compatibility.json" --arg signature "$sig" '{signed:$signed[0],signature:$signature}' > "$MANIFEST"
expect_code 'incompatible current version rejected' 32 run_update --dry-run

new_root space; make_package space; make_manifest space CRITICAL 1 0.1.1-dev
printf '%s\n' 'minimum_free_kb=999999999999' >> "$CONFIG"
expect_code 'insufficient free space blocks apply' 33 run_update --apply

new_root download; make_package download; make_manifest download ROUTINE 1 0.1.1-dev
printf broken > "$PACKAGE"
expect_code 'interrupted package rejected' 31 run_update --dry-run

new_root install; make_package install; make_manifest install CRITICAL 1 0.1.1-dev
set +e
VWARD_TEST_FAIL_INSTALL_AT=2 run_update --apply >/dev/null 2>&1
code=$?
set -e
[ "$code" -eq 40 ] && [ "$(cat "$ROOT/opt/bin/vward-route.sh")" = old ] && pass 'install failure rolls back' || fail 'install failure rollback'

new_root health; make_package health; make_manifest health CRITICAL 1 0.1.1-dev
set +e
VWARD_TEST_FORCE_HEALTH_FAIL=1 run_update --apply >"$WORK/health.out" 2>&1
code=$?
set -e
if [ "$code" -eq 41 ] && [ "$(cat "$ROOT/opt/bin/vward-route.sh")" = old ]; then
    pass 'health failure rolls back'
else
    sed 's/^/  # /' "$WORK/health.out"
    printf '  # code=%s content=%s phase=%s\n' "$code" "$(cat "$ROOT/opt/bin/vward-route.sh")" "$(sed -n 's/^phase=//p' "$ROOT/opt/var/lib/vward/updater/journal.state" 2>/dev/null || :)"
    fail 'health failure rollback'
fi

new_root rollback; make_package rollback; make_manifest rollback CRITICAL 1 0.1.1-dev
run_update --apply >/dev/null 2>&1
expect_code 'explicit rollback succeeds' 0 env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" "$UPDATER/vward-update-rollback.sh"

new_root interrupted-rollback; make_package interrupted-rollback; make_manifest interrupted-rollback CRITICAL 1 0.1.1-dev
run_update --apply >/dev/null 2>&1
expect_code 'interrupted rollback is reported' 42 env VWARD_TEST_FAIL_ROLLBACK_AT=1 VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" "$UPDATER/vward-update-rollback.sh"

new_root recovery; make_package recovery; make_manifest recovery CRITICAL 1 0.1.1-dev
mkdir -p "$ROOT/opt/var/backups/vward/recovery/files/opt/bin"
cp "$ROOT/opt/bin/vward-route.sh" "$ROOT/opt/var/backups/vward/recovery/files/opt/bin/vward-route.sh"
recovery_sha=$(sha256sum "$ROOT/opt/bin/vward-route.sh" | awk '{print $1}')
printf '/opt/bin/vward-route.sh\t1\t644\t%s\t%s\n' "$recovery_sha" "$recovery_sha" > "$ROOT/opt/var/backups/vward/recovery/files.tsv"
printf '0\n' > "$ROOT/opt/var/backups/vward/recovery/committed.existed"
recovery_index_sha=$(sha256sum "$ROOT/opt/var/backups/vward/recovery/files.tsv" | awk '{print $1}')
printf 'index_sha=%s\ncommitted_sha=-\n' "$recovery_index_sha" > "$ROOT/opt/var/backups/vward/recovery/backup.meta"
printf 'phase=INSTALLING\nactive_backup=%s\n' "$ROOT/opt/var/backups/vward/recovery" > "$ROOT/opt/var/lib/vward/updater/journal.state"
expect_code 'interrupted transaction recovers' 0 env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" "$UPDATER/vward-update.sh" --recover

new_root bootstrap
mkdir -p "$ROOT/opt/share/vward/updater/slot-a"
printf '#!/bin/sh\nexit 0\n' > "$ROOT/opt/share/vward/updater/slot-a/vward-update.sh"
chmod 755 "$ROOT/opt/share/vward/updater/slot-a/vward-update.sh"
ln -s slot-a "$ROOT/opt/share/vward/updater/current"
expect_code 'stable bootstrap hands off to current slot' 0 env VWARD_ROOT_PREFIX="$ROOT" "$UPDATER/vward-update-bootstrap.sh" --status

printf '1..%s\n' "$((passed + failed))"
[ "$failed" -eq 0 ]
