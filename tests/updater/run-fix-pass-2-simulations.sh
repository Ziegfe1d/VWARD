#!/bin/sh
set -eu

REPO=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
UPDATER=$REPO/components/updater
WORK=$(mktemp -d "${TMPDIR:-/tmp}/vward-fix-pass-2.XXXXXX")
trap 'rm -rf "$WORK"' EXIT HUP INT TERM
passed=0
failed=0
number=0
ok(){ number=$((number+1)); passed=$((passed+1)); printf 'ok %s - %s\n' "$number" "$1"; }
bad(){ number=$((number+1)); failed=$((failed+1)); printf 'not ok %s - %s\n' "$number" "$1"; }

openssl genpkey -algorithm ED25519 -out "$WORK/private.pem" >/dev/null 2>&1
openssl pkey -in "$WORK/private.pem" -pubout -out "$WORK/public.pem" >/dev/null 2>&1

new_root(){
  label=$1
  ROOT=$WORK/root-$label
  mkdir -p "$ROOT/tmp" "$ROOT/opt/etc/vward" "$ROOT/opt/etc/keenetic-apps" "$ROOT/opt/share/vward" "$ROOT/opt/bin" "$ROOT/opt/share/keenetic-apps/www/cgi-bin" "$ROOT/opt/var/lib/vward/updater"
  cp "$WORK/public.pem" "$ROOT/opt/etc/vward/update-public.pem"
  printf '0.1.0-dev\n' > "$ROOT/opt/share/vward/VERSION"
  printf 'old\n' > "$ROOT/opt/bin/adaptive-route.sh"
  printf 'wan\n' > "$ROOT/opt/bin/wan-guardian.sh"
  printf 'html\n' > "$ROOT/opt/share/keenetic-apps/www/index.html"
  CONFIG=$ROOT/opt/etc/vward/update.conf
  cat > "$CONFIG" <<CFG
update_enabled=1
auto_apply=1
auto_critical=1
auto_important=1
auto_routine=1
channel=dev
manifest_url=https://example.invalid/update-manifest.json
public_key_file=$ROOT/opt/etc/vward/update-public.pem
current_version_file=$ROOT/opt/share/vward/VERSION
minimum_free_kb=1
max_manifest_size=262144
max_package_size=1048576
max_unpacked_size=4194304
staging_multiplier=3
barrier_integration_ready=1
safe_window_start=00:00
safe_window_end=23:59
important_max_delay_seconds=7200
routine_max_delay_seconds=86400
request_timeout_seconds=1
check_interval_seconds=1
CFG
  STATE=$ROOT/opt/var/lib/vward/updater
  printf 'installed_version=0.1.0-dev\ninstalled_update_id=bootstrap\nlast_sequence=0\nmanifest_hash=bootstrap\nlast_health_check=bootstrap\n' > "$STATE/committed.state"
}

make_package(){
  label=$1
  payload_size=${2:-16}
  PKGDIR=$WORK/pkg-$label
  rm -rf "$PKGDIR"; mkdir -p "$PKGDIR/files"
  awk -v n="$payload_size" 'BEGIN{for(i=0;i<n;i++)printf "A";printf "\n"}' > "$PKGDIR/files/adaptive-route.sh"
  awk -v n="$payload_size" 'BEGIN{for(i=0;i<n;i++)printf "W";printf "\n"}' > "$PKGDIR/files/wan-guardian.sh"
  one=$(sha256sum "$PKGDIR/files/adaptive-route.sh"|awk '{print $1}')
  two=$(sha256sum "$PKGDIR/files/wan-guardian.sh"|awk '{print $1}')
  jq -n --arg one "$one" --arg two "$two" '{schema:1,files:[{source:"files/adaptive-route.sh",target:"/opt/bin/adaptive-route.sh",sha256:$one,mode:"0755",component:"adaptive-routing",restart_policy:"none",config_policy:"program-only"},{source:"files/wan-guardian.sh",target:"/opt/bin/wan-guardian.sh",sha256:$two,mode:"0755",component:"wan-guardian",restart_policy:"none",config_policy:"program-only"}]}' > "$PKGDIR/package-manifest.json"
  PACKAGE=$WORK/package-$label.tar.gz
  tar -czf "$PACKAGE" -C "$PKGDIR" .
  UNPACKED=$(find "$PKGDIR" -type f -exec wc -c {} \; | awk '{s+=$1} END{print s+0}')
}

make_manifest(){
  label=$1; priority=$2; sequence=$3; version=$4; unpacked=${5:-$UNPACKED}
  sha=$(sha256sum "$PACKAGE"|awk '{print $1}'); size=$(wc -c < "$PACKAGE"|tr -d ' ')
  MANIFEST=$WORK/manifest-$label.json
  signed=$WORK/signed-$label.json
  jq -n --arg id "$label" --arg version "$version" --arg priority "$priority" --arg sha "$sha" --argjson size "$size" --argjson unpacked "$unpacked" --argjson sequence "$sequence" '{schema:1,update_id:$id,sequence:$sequence,version:$version,channel:"dev",priority:$priority,published_at:"2026-09-07T00:00:00Z",min_updater_version:"1.0.0",package:{url:"https://example.invalid/package.tar.gz",sha256:$sha,size:$size,unpacked_size:$unpacked},compatibility:{min_vward:"0.1.0-dev",max_vward:"0.1.0-dev"},affected_components:["adaptive-routing","wan-guardian"],affected_services:[],health_profile:"default",requires_reboot:false,rollback_policy:"automatic",signature:{algorithm:"Ed25519",key_id:"test-key"}}' > "$signed"
  jq -cS . "$signed" > "$signed.canonical"
  openssl pkeyutl -sign -inkey "$WORK/private.pem" -rawin -in "$signed.canonical" -out "$signed.sig"
  sig=$(openssl base64 -A -in "$signed.sig")
  jq -n --slurpfile signed "$signed" --arg sig "$sig" '{signed:$signed[0],signature:$sig}' > "$MANIFEST"
}

run_update(){ env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" VWARD_TEST_MANIFEST="$MANIFEST" VWARD_TEST_PACKAGE="$PACKAGE" "$@" "$UPDATER/vward-update.sh" "${COMMAND:---apply}"; }

new_root idle304; make_package idle304; make_manifest idle304 CRITICAL 1 0.1.1-dev
run_update >/dev/null 2>&1
mkdir -p "$STATE"; printf 'manifest_etag=etag1\n' > "$STATE/watcher.state"
set +e
env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" VWARD_TEST_HTTP_STATUS=304 "$UPDATER/vward-update-watch.sh" --once >/dev/null 2>&1; c=$?
set -e
[ "$c" -eq 0 ] && grep -q '^manifest_etag=etag1$' "$STATE/watcher.state" && ok '304 after successful update is clean idle' || bad '304 steady state'

set +e
env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" VWARD_TEST_HTTP_STATUS=200 VWARD_TEST_ETAG=etag2 VWARD_TEST_WATCH_MANIFEST="$MANIFEST" "$UPDATER/vward-update-watch.sh" --once >/dev/null 2>&1; c=$?
set -e
[ "$c" -eq 0 ] && grep -q '^manifest_etag=etag2$' "$STATE/watcher.state" && ok 'exact installed 200 is clean no-update' || bad 'exact installed feed'

new_root quarantine-install; make_package quarantine-install; make_manifest quarantine-install CRITICAL 1 0.1.1-dev
set +e
env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" VWARD_TEST_HTTP_STATUS=200 VWARD_TEST_WATCH_MANIFEST="$MANIFEST" VWARD_TEST_PACKAGE="$PACKAGE" VWARD_TEST_FAIL_INSTALL_AT=2 "$UPDATER/vward-update-watch.sh" --once >/dev/null 2>&1; first=$?
set -e
backup_count1=$(find "$ROOT/opt/var/backups/vward" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
set +e
env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" VWARD_TEST_HTTP_STATUS=304 VWARD_TEST_PACKAGE="$PACKAGE" "$UPDATER/vward-update-watch.sh" --once >/dev/null 2>&1; second=$?
set -e
backup_count2=$(find "$ROOT/opt/var/backups/vward" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
[ "$first" -eq 40 ] && [ "$second" -eq 35 ] && [ "$backup_count1" = "$backup_count2" ] && [ "$(sed -n 's/^failure_class=//p' "$STATE/quarantine.state")" = install ] && ok 'failed install is quarantined without auto-retry' || bad 'install quarantine'

new_root quarantine-health; make_package quarantine-health; make_manifest quarantine-health CRITICAL 1 0.1.1-dev
set +e
VWARD_TEST_FORCE_HEALTH_FAIL=1 run_update >/dev/null 2>&1; c=$?
set -e
[ "$c" -eq 41 ] && [ "$(sed -n 's/^failure_class=//p' "$STATE/quarantine.state")" = health ] && ok 'health failure is quarantined' || bad 'health quarantine'

make_package quarantine-higher; make_manifest quarantine-higher CRITICAL 2 0.1.2-dev
set +e
run_update >/dev/null 2>&1; c=$?
set -e
[ "$c" -eq 0 ] && [ "$(sed -n 's/^installed_update_id=//p' "$STATE/committed.state")" = quarantine-higher ] && ok 'higher sequence escapes old quarantine' || bad 'higher sequence after quarantine'

new_root trust; make_package trust10; make_manifest trust10 CRITICAL 10 0.1.10-dev
MANIFEST10=$MANIFEST; PACKAGE10=$PACKAGE
COMMAND=--check; run_update >/dev/null 2>&1
make_package trust9; make_manifest trust9 CRITICAL 9 0.1.9-dev
set +e
run_update >/dev/null 2>&1; c=$?
set -e
[ "$c" -eq 32 ] && [ "$(sed -n 's/^highest_seen_sequence=//p' "$STATE/trust.state")" = 10 ] && ok 'highest seen sequence blocks older signed manifest' || bad 'monotonic trust'

MANIFEST=$MANIFEST10; PACKAGE=$PACKAGE10
set +e
run_update >/dev/null 2>&1; c=$?
set -e
[ "$c" -eq 0 ] && ok 'same sequence same manifest is reusable' || bad 'same trust reuse'

make_package trust10b; make_manifest trust10b CRITICAL 10 0.1.10-dev
set +e
run_update >/dev/null 2>&1; c=$?
set -e
[ "$c" -eq 32 ] && ok 'same sequence different manifest is rejected' || bad 'same sequence collision'
unset COMMAND

new_root stale-request; make_package stale-request; make_manifest stale-request CRITICAL 1 0.1.1-dev
printf '999999:1:vward-update\n' > "$ROOT/tmp/vward-update-requested"
set +e
run_update >/dev/null 2>&1; c=$?
set -e
[ "$c" -eq 0 ] && [ ! -e "$ROOT/tmp/vward-update-requested" ] && ok 'stale request marker recovered' || bad 'stale request recovery'

new_root stale-barrier; make_package stale-barrier; make_manifest stale-barrier CRITICAL 1 0.1.1-dev
mkdir -p "$ROOT/tmp/vward-update.lock"; printf '999999:1:vward-update\n' > "$ROOT/tmp/vward-update.lock/owner"
set +e
run_update >/dev/null 2>&1; c=$?
set -e
[ "$c" -eq 0 ] && [ ! -e "$ROOT/tmp/vward-update.lock" ] && ok 'stale barrier recovered' || bad 'stale barrier recovery'

new_root malformed-barrier; make_package malformed-barrier; make_manifest malformed-barrier CRITICAL 1 0.1.1-dev
mkdir -p "$ROOT/tmp/vward-update.lock"; printf 'garbage\n' > "$ROOT/tmp/vward-update.lock/owner"
set +e
run_update >/dev/null 2>&1; c=$?
set -e
[ "$c" -eq 33 ] && [ -d "$ROOT/tmp/vward-update.lock" ] && ok 'malformed barrier fails conservatively' || bad 'malformed barrier'

new_root allow
set +e
VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" sh -c '. "$1"; vu_safe_target /opt/bin/adaptive-route.sh && ! vu_safe_target /opt/bin/unrelated.sh && ! vu_safe_target /opt/etc/init.d/S99unrelated' sh "$UPDATER/vward-update-common.sh"; c=$?
set -e
[ "$c" -eq 0 ] && ok 'strict VWARD path ownership' || bad 'strict allow-list'

new_root cumulative; make_package cumulative 1600; make_manifest cumulative CRITICAL 1 0.1.1-dev
set +e
VWARD_TEST_FREE_TARGET_KB=3 run_update >/dev/null 2>&1; c=$?
set -e
[ "$c" -eq 33 ] && [ "$(cat "$ROOT/opt/bin/adaptive-route.sh")" = old ] && ok 'cumulative target space is enforced' || bad 'cumulative space'

new_root bounded
awk 'BEGIN{for(i=0;i<2000;i++)printf "x"}' > "$WORK/oversize.bin"
set +e
VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" VWARD_TEST_FETCH_SOURCE="$WORK/oversize.bin" sh -c '. "$1"; vu_fetch_limited https://example.invalid/x "$2" 1000' sh "$UPDATER/vward-update-common.sh" "$WORK/out.bin"; c=$?
set -e
[ "$c" -ne 0 ] && ok 'bounded download rejects oversized response' || bad 'bounded transport'

new_root unpacked; make_package unpacked 800; make_manifest unpacked CRITICAL 1 0.1.1-dev 100
set +e
run_update >/dev/null 2>&1; c=$?
set -e
[ "$c" -eq 33 ] && [ "$(cat "$ROOT/opt/bin/adaptive-route.sh")" = old ] && ok 'signed unpacked-size limit enforced' || bad 'unpacked-size limit'

new_root orphan; make_package orphan; make_manifest orphan CRITICAL 1 0.1.1-dev
mkdir -p "$ROOT/opt/var/cache/vward/updater/transaction.123" "$STATE/pending"; printf keep > "$STATE/pending/keep"
COMMAND=--check; run_update >/dev/null 2>&1
[ ! -d "$ROOT/opt/var/cache/vward/updater/transaction.123" ] && [ -f "$STATE/pending/keep" ] && ok 'orphan staging cleaned without touching pending cache' || bad 'orphan staging cleanup'
unset COMMAND

new_root barrier-race; make_package barrier-race; make_manifest barrier-race CRITICAL 1 0.1.1-dev
set +e
VWARD_TEST_POST_BARRIER_CONFLICT=1 run_update >/dev/null 2>&1; c=$?
set -e
[ "$c" -eq 33 ] && [ "$(cat "$ROOT/opt/bin/adaptive-route.sh")" = old ] && ok 'post-barrier conflict blocks install' || bad 'two-phase barrier'

new_root retry-network; printf 0 > "$WORK/counter"
set +e
env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" VWARD_TEST_HTTP_STATUS=503 VWARD_TEST_WATCH_COUNTER="$WORK/counter" "$UPDATER/vward-update-watch.sh" --once >/dev/null 2>&1; c=$?
set -e
[ "$c" -eq 34 ] && [ "$(cat "$WORK/counter")" -eq 4 ] && ok 'transient network error gets bounded fast retry' || bad 'network retry classification'

new_root retry-deferred; make_package retry-deferred; make_manifest retry-deferred ROUTINE 1 0.1.1-dev
printf 'safe_window_start=03:00\nsafe_window_end=04:00\n' >> "$CONFIG"; printf 0 > "$WORK/counter2"
set +e
env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" VWARD_TEST_HTTP_STATUS=200 VWARD_TEST_WATCH_MANIFEST="$MANIFEST" VWARD_TEST_PACKAGE="$PACKAGE" VWARD_TEST_WATCH_COUNTER="$WORK/counter2" VWARD_TEST_NOW_HM=12:00 VWARD_TEST_NOW_EPOCH=100 "$UPDATER/vward-update-watch.sh" --once >/dev/null 2>&1; c=$?
set -e
[ "$c" -eq 20 ] && [ "$(cat "$WORK/counter2")" -eq 1 ] && ok 'deferred update is not fast-retried' || bad 'deferred retry classification'

new_root trust-rollback; make_package trust-rollback; make_manifest trust-rollback CRITICAL 10 0.1.10-dev
run_update >/dev/null 2>&1
env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" "$UPDATER/vward-update-rollback.sh" >/dev/null 2>&1
[ "$(sed -n 's/^highest_seen_sequence=//p' "$STATE/trust.state")" = 10 ] && ok 'rollback preserves monotonic trust state' || bad 'trust after rollback'

printf '1..%s\n# passed=%s failed=%s\n' "$number" "$passed" "$failed"
[ "$failed" -eq 0 ]
