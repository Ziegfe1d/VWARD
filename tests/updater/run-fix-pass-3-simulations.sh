#!/bin/sh
set -eu

REPO=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
UPDATER=$REPO/components/updater
WORK=$(mktemp -d "${TMPDIR:-/tmp}/vward-fix-pass-3.XXXXXX")
trap 'rm -rf "$WORK"' EXIT HUP INT TERM

passed=0
failed=0
number=0
ok(){ number=$((number+1)); passed=$((passed+1)); printf 'ok %s - %s\n' "$number" "$1"; }
bad(){ number=$((number+1)); failed=$((failed+1)); printf 'not ok %s - %s\n' "$number" "$1"; }

openssl genpkey -algorithm ED25519 -out "$WORK/private.pem" >/dev/null 2>&1
openssl pkey -in "$WORK/private.pem" -pubout -out "$WORK/public.pem" >/dev/null 2>&1

new_root() {
    label=$1
    ROOT=$WORK/root-$label
    mkdir -p "$ROOT/opt/etc/vward" "$ROOT/opt/share/vward" "$ROOT/opt/bin" \
        "$ROOT/opt/share/keenetic-apps/www" "$ROOT/opt/var/lib/vward/updater" "$ROOT/tmp"
    cp "$WORK/public.pem" "$ROOT/opt/etc/vward/update-public.pem"
    printf '0.1.0-dev\n' > "$ROOT/opt/share/vward/VERSION"
    awk 'BEGIN{for(i=0;i<1900;i++)printf "O";printf "\n"}' > "$ROOT/opt/bin/adaptive-route.sh"
    awk 'BEGIN{for(i=0;i<1900;i++)printf "W";printf "\n"}' > "$ROOT/opt/bin/wan-guardian.sh"
    printf 'html\n' > "$ROOT/opt/share/keenetic-apps/www/index.html"
    CONFIG=$ROOT/opt/etc/vward/update.conf
    {
        printf '%s\n' 'update_enabled=1' 'auto_apply=1' 'auto_critical=1' 'auto_important=1' 'auto_routine=1' 'channel=dev'
        printf '%s\n' 'manifest_url=https://example.invalid/update-manifest.json'
        printf 'public_key_file=%s\n' "$ROOT/opt/etc/vward/update-public.pem"
        printf 'current_version_file=%s\n' "$ROOT/opt/share/vward/VERSION"
        printf '%s\n' 'minimum_free_kb=0' 'max_manifest_size=262144' 'max_package_size=1048576' 'max_unpacked_size=4194304' 'barrier_integration_ready=1'
        printf '%s\n' 'safe_window_start=00:00' 'safe_window_end=23:59'
    } > "$CONFIG"
    STATE=$ROOT/opt/var/lib/vward/updater
    printf 'installed_version=0.1.0-dev\ninstalled_update_id=bootstrap\nlast_sequence=0\nmanifest_hash=bootstrap\nlast_health_check=bootstrap\n' > "$STATE/committed.state"
}

make_package() {
    label=$1
    PKGDIR=$WORK/pkg-$label
    mkdir -p "$PKGDIR/files"
    awk 'BEGIN{for(i=0;i<1900;i++)printf "N";printf "\n"}' > "$PKGDIR/files/adaptive-route.sh"
    awk 'BEGIN{for(i=0;i<1900;i++)printf "V";printf "\n"}' > "$PKGDIR/files/wan-guardian.sh"
    one=$(sha256sum "$PKGDIR/files/adaptive-route.sh" | awk '{print $1}')
    two=$(sha256sum "$PKGDIR/files/wan-guardian.sh" | awk '{print $1}')
    jq -n --arg one "$one" --arg two "$two" \
      '{schema:1,files:[
        {source:"files/adaptive-route.sh",target:"/opt/bin/adaptive-route.sh",sha256:$one,mode:"0755",component:"adaptive-routing",restart_policy:"none",config_policy:"program-only"},
        {source:"files/wan-guardian.sh",target:"/opt/bin/wan-guardian.sh",sha256:$two,mode:"0755",component:"wan-guardian",restart_policy:"none",config_policy:"program-only"}
      ]}' > "$PKGDIR/package-manifest.json"
    PACKAGE=$WORK/pkg-$label.tar.gz
    tar -czf "$PACKAGE" -C "$PKGDIR" .
    UNPACKED=$(find "$PKGDIR" -type f -exec wc -c {} \; | awk '{s+=$1} END{print s+0}')
}

make_manifest() {
    label=$1
    sha=$(sha256sum "$PACKAGE" | awk '{print $1}')
    size=$(wc -c < "$PACKAGE" | tr -d ' ')
    MANIFEST=$WORK/manifest-$label.json
    signed=$WORK/signed-$label.json
    jq -n --arg id "$label" --arg sha "$sha" --argjson size "$size" --argjson unpacked "$UNPACKED" \
      '{schema:1,update_id:$id,sequence:1,version:"0.1.1-dev",channel:"dev",priority:"CRITICAL",
        published_at:"2026-09-07T00:00:00Z",min_updater_version:"1.0.0",
        package:{url:"https://example.invalid/package.tar.gz",sha256:$sha,size:$size,unpacked_size:$unpacked},
        compatibility:{min_vward:"0.1.0-dev",max_vward:"0.1.0-dev"},
        affected_components:["adaptive-routing","wan-guardian"],affected_services:[],
        health_profile:"default",requires_reboot:false,rollback_policy:"automatic",
        signature:{algorithm:"Ed25519",key_id:"test-key"}}' > "$signed"
    jq -cS . "$signed" > "$signed.canon"
    openssl pkeyutl -sign -inkey "$WORK/private.pem" -rawin -in "$signed.canon" -out "$signed.sig"
    sig=$(openssl base64 -A -in "$signed.sig")
    jq -n --slurpfile signed "$signed" --arg signature "$sig" '{signed:$signed[0],signature:$signature}' > "$MANIFEST"
}

run_update() {
    env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" \
        VWARD_TEST_MANIFEST="$MANIFEST" VWARD_TEST_PACKAGE="$PACKAGE" "$@" \
        "$UPDATER/vward-update.sh" --apply
}

new_root combined-space
make_package combined-space
make_manifest combined-space
set +e
VWARD_TEST_FREE_BACKUP_KB=5 VWARD_TEST_FREE_TARGET_KB=5 VWARD_TEST_FREE_COMBINED_KB=5 \
    run_update >/dev/null 2>&1
rc=$?
set -e
if [ "$rc" -eq 33 ]; then
    ok 'shared filesystem sums backup and target future allocations'
else
    printf '  # rc=%s\n' "$rc"
    bad 'shared filesystem combined accounting'
fi

new_root quarantine-crash
make_package quarantine-crash
make_manifest quarantine-crash
set +e
VWARD_TEST_FAIL_INSTALL_AT=2 VWARD_TEST_CRASH_BEFORE_QUARANTINE=1 \
    run_update >/dev/null 2>&1
crash_rc=$?
set -e

phase=$(sed -n 's/^phase=//p' "$STATE/journal.state" 2>/dev/null || :)
reason=$(sed -n 's/^rollback_failure_class=//p' "$STATE/journal.state" 2>/dev/null || :)

set +e
env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" \
    "$UPDATER/vward-update.sh" --recover >/dev/null 2>&1
recover_rc=$?
set -e

final_phase=$(sed -n 's/^phase=//p' "$STATE/journal.state" 2>/dev/null || :)
qseq=$(sed -n 's/^sequence=//p' "$STATE/quarantine.state" 2>/dev/null || :)
qreason=$(sed -n 's/^failure_class=//p' "$STATE/quarantine.state" 2>/dev/null || :)

if [ "$crash_rc" -ne 0 ] && [ "$phase" = ROLLING_BACK ] && [ "$reason" = install ] && \
   [ "$recover_rc" -eq 0 ] && [ "$final_phase" = ROLLED_BACK ] && \
   [ "$qseq" = 1 ] && [ "$qreason" = install ]; then
    ok 'rollback recovery completes quarantine before ROLLED_BACK'
else
    printf '  # crash_rc=%s phase=%s reason=%s recover_rc=%s final=%s qseq=%s qreason=%s\n' \
        "$crash_rc" "$phase" "$reason" "$recover_rc" "$final_phase" "$qseq" "$qreason"
    bad 'rollback quarantine crash recovery'
fi

printf '1..%s\n' "$number"
printf '# passed=%s failed=%s\n' "$passed" "$failed"
[ "$failed" -eq 0 ]
