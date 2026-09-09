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
expect_code(){ name=$1 expected=$2; shift 2; set +e; "$@" >"$WORK/last.out" 2>&1; actual=$?; set -e; if [ "$actual" -eq "$expected" ]; then ok "$name"; else sed 's/^/  # /' "$WORK/last.out"; printf '  # expected=%s actual=%s\n' "$expected" "$actual"; bad "$name"; fi; }

openssl genpkey -algorithm ED25519 -out "$WORK/private.pem" >/dev/null 2>&1
openssl pkey -in "$WORK/private.pem" -pubout -out "$WORK/public.pem" >/dev/null 2>&1

new_root(){
  label=$1
  ROOT=$WORK/root-$label
  mkdir -p "$ROOT/opt/etc/vward" "$ROOT/opt/etc/keenetic-apps" "$ROOT/opt/share/vward" "$ROOT/opt/bin" "$ROOT/opt/share/keenetic-apps/www/cgi-bin" "$ROOT/opt/var/lib/vward/updater" "$ROOT/tmp"
  cp "$WORK/public.pem" "$ROOT/opt/etc/vward/update-public.pem"
  printf '0.1.0-dev\n' > "$ROOT/opt/share/vward/VERSION"
  printf 'old\n' > "$ROOT/opt/bin/adaptive-route.sh"
  printf 'wan\n' > "$ROOT/opt/bin/wan-guardian.sh"
  printf 'html\n' > "$ROOT/opt/share/keenetic-apps/www/index.html"
  CONFIG=$ROOT/opt/etc/vward/update.conf
  {
    printf '%s\n' 'update_enabled=1' 'auto_apply=1' 'auto_critical=1' 'auto_important=1' 'auto_routine=1' 'channel=dev'
    printf '%s\n' 'manifest_url=https://example.invalid/update-manifest.json'
    printf 'public_key_file=%s\n' "$ROOT/opt/etc/vward/update-public.pem"
    printf 'current_version_file=%s\n' "$ROOT/opt/share/vward/VERSION"
    printf '%s\n' 'minimum_free_kb=1' 'max_manifest_size=262144' 'max_package_size=1048576' 'max_unpacked_size=4194304' 'barrier_integration_ready=1'
    printf '%s\n' 'safe_window_start=00:00' 'safe_window_end=23:59' 'important_max_delay_seconds=7200' 'routine_max_delay_seconds=86400' 'check_interval_seconds=1'
  } > "$CONFIG"
  STATE=$ROOT/opt/var/lib/vward/updater
  printf 'installed_version=0.1.0-dev\ninstalled_update_id=bootstrap\nlast_sequence=0\nmanifest_hash=bootstrap\nlast_health_check=bootstrap\n' > "$STATE/committed.state"
}

make_package(){
  label=$1
  PKGDIR=$WORK/pkg-$label
  mkdir -p "$PKGDIR/files"
  printf 'new-%s\n' "$label" > "$PKGDIR/files/adaptive-route.sh"
  printf 'wan-%s\n' "$label" > "$PKGDIR/files/wan-guardian.sh"
  one=$(sha256sum "$PKGDIR/files/adaptive-route.sh"|awk '{print $1}')
  two=$(sha256sum "$PKGDIR/files/wan-guardian.sh"|awk '{print $1}')
  jq -n --arg one "$one" --arg two "$two" '{schema:1,files:[{source:"files/adaptive-route.sh",target:"/opt/bin/adaptive-route.sh",sha256:$one,mode:"0755",component:"route-tools",restart_policy:"none",config_policy:"program-only"},{source:"files/wan-guardian.sh",target:"/opt/bin/wan-guardian.sh",sha256:$two,mode:"0755",component:"wan-guardian",restart_policy:"none",config_policy:"program-only"}]}' > "$PKGDIR/package-manifest.json"
  PACKAGE=$WORK/pkg-$label.tar.gz
  tar -czf "$PACKAGE" -C "$PKGDIR" .
  UNPACKED=$(find "$PKGDIR" -type f -exec wc -c {} \; | awk '{s+=$1} END {print s+0}')
}

make_manifest(){
  label=$1 priority=$2 sequence=${3:-1} version=${4:-0.1.1-dev} unpacked_override=${5:-}
  sha=$(sha256sum "$PACKAGE"|awk '{print $1}')
  size=$(wc -c < "$PACKAGE"|tr -d ' ')
  unpacked=${unpacked_override:-$UNPACKED}
  MANIFEST=$WORK/manifest-$label.json
  signed=$WORK/signed-$label.json
  jq -n --arg id "$label" --arg ver "$version" --arg pri "$priority" --arg sha "$sha" --argjson size "$size" --argjson unpacked "$unpacked" --argjson seq "$sequence" '{schema:1,update_id:$id,sequence:$seq,version:$ver,channel:"dev",priority:$pri,published_at:"2026-09-07T00:00:00Z",min_updater_version:"1.0.0",package:{url:"https://example.invalid/package.tar.gz",sha256:$sha,size:$size,unpacked_size:$unpacked},compatibility:{min_vward:"0.1.0-dev",max_vward:"0.1.0-dev"},affected_components:["route-tools","wan-guard"],affected_services:[],health_profile:"default",requires_reboot:false,rollback_policy:"automatic",signature:{algorithm:"Ed25519",key_id:"test-key"}}' > "$signed"
  jq -cS . "$signed" > "$signed.canon"
  openssl pkeyutl -sign -inkey "$WORK/private.pem" -rawin -in "$signed.canon" -out "$signed.sig"
  sig=$(openssl base64 -A -in "$signed.sig")
  jq -n --slurpfile signed "$signed" --arg signature "$sig" '{signed:$signed[0],signature:$signature}' > "$MANIFEST"
}

run_update(){ env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" VWARD_TEST_MANIFEST="$MANIFEST" VWARD_TEST_PACKAGE="$PACKAGE" "$@" "$UPDATER/vward-update.sh" "${COMMAND:---apply}"; }
run_watch(){ env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" VWARD_TEST_HTTP_STATUS="$1" VWARD_TEST_WATCH_MANIFEST="${MANIFEST:-}" VWARD_TEST_PACKAGE="${PACKAGE:-}" VWARD_TEST_ETAG="${VWARD_TEST_ETAG:-}" VWARD_TEST_WATCH_ATTEMPT_FILE="${ATTEMPT_FILE:-}" "$UPDATER/vward-update-watch.sh" --once; }

new_root steady; make_package steady; make_manifest steady CRITICAL 1 0.1.1-dev
VWARD_TEST_ETAG=E1 run_watch 200 >/dev/null 2>&1
etag_before=$(sed -n 's/^manifest_etag=//p' "$STATE/watcher.state")
set +e; run_watch 304 >/dev/null 2>&1; rc=$?; set -e
etag_after=$(sed -n 's/^manifest_etag=//p' "$STATE/watcher.state")
[ "$rc" -eq 0 ] && [ "$etag_before" = E1 ] && [ "$etag_after" = E1 ] && [ ! -e "$STATE/pending/pending.state" ] && ok '304 after successful update is clean idle' || bad '304 steady state'
set +e; run_watch 200 >/dev/null 2>&1; rc=$?; set -e
[ "$rc" -eq 0 ] && ok 'HTTP 200 exact installed manifest is no-update' || bad 'exact installed 200'

new_root quarantine; make_package qbad; make_manifest qbad CRITICAL 1 0.1.1-dev
set +e; VWARD_TEST_FAIL_INSTALL_AT=2 run_update >/dev/null 2>&1; rc=$?; set -e
qseq=$(sed -n 's/^sequence=//p' "$STATE/quarantine.state" 2>/dev/null || :)
[ "$rc" -eq 40 ] && [ "$qseq" = 1 ] && [ "$(cat "$ROOT/opt/bin/adaptive-route.sh")" = old ] && ok 'failed install is quarantined after rollback' || bad 'install quarantine'
ATTEMPT_FILE=$WORK/q-attempts; printf '0\n' > "$ATTEMPT_FILE"
set +e; run_watch 304 >/dev/null 2>&1; rc=$?; set -e
attempts=$(cat "$ATTEMPT_FILE")
[ "$rc" -eq 11 ] && [ "$attempts" -eq 1 ] && [ "$(cat "$ROOT/opt/bin/adaptive-route.sh")" = old ] && ok 'quarantined update is not auto-retried' || bad 'quarantine retry block'
make_package qgood; make_manifest qgood CRITICAL 2 0.1.2-dev
set +e; run_watch 200 >/dev/null 2>&1; rc=$?; set -e
[ "$rc" -eq 0 ] && [ "$(sed -n 's/^last_sequence=//p' "$STATE/committed.state")" = 2 ] && ok 'higher sequence proceeds after old quarantine' || bad 'quarantine higher sequence'

new_root healthq; make_package healthq; make_manifest healthq CRITICAL 1 0.1.1-dev
set +e; VWARD_TEST_FORCE_HEALTH_FAIL=1 run_update >/dev/null 2>&1; rc=$?; set -e
reason=$(sed -n 's/^failure_class=//p' "$STATE/quarantine.state" 2>/dev/null || :)
[ "$rc" -eq 41 ] && [ "$reason" = health ] && [ "$(cat "$ROOT/opt/bin/adaptive-route.sh")" = old ] && ok 'health failure is quarantined after rollback' || bad 'health quarantine'

new_root trust; make_package t10; make_manifest t10 CRITICAL 10 0.1.10-dev
COMMAND=--check; run_update >/dev/null 2>&1; unset COMMAND
[ "$(sed -n 's/^highest_seen_sequence=//p' "$STATE/trust.state")" = 10 ] && ok 'highest seen sequence advances on trusted manifest' || bad 'trust advance'
make_package t9; make_manifest t9 CRITICAL 9 0.1.9-dev
COMMAND=--check; set +e; run_update >/dev/null 2>&1; rc=$?; set -e; unset COMMAND
[ "$rc" -eq 32 ] && ok 'older signed sequence rejected after newer seen' || bad 'trust replay block'
PACKAGE=$WORK/pkg-t10.tar.gz; MANIFEST=$WORK/manifest-t10.json; COMMAND=--check; set +e; run_update >/dev/null 2>&1; rc=$?; set -e; unset COMMAND
[ "$rc" -eq 0 ] && ok 'same sequence and identical manifest reused' || bad 'same trust reuse'
make_package t10different; make_manifest t10different CRITICAL 10 0.1.11-dev
COMMAND=--check; set +e; run_update >/dev/null 2>&1; rc=$?; set -e; unset COMMAND
[ "$rc" -eq 32 ] && ok 'same sequence with changed manifest rejected' || bad 'same sequence mutation'

new_root stale-request; make_package sr; make_manifest sr CRITICAL 1 0.1.1-dev
printf '999999:%s:vward-update\n' "$(date +%s)" > "$ROOT/tmp/vward-update-requested"
COMMAND=--check; set +e; run_update >/dev/null 2>&1; rc=$?; set -e; unset COMMAND
[ "$rc" -eq 0 ] && [ ! -e "$ROOT/tmp/vward-update-requested" ] && ok 'stale request marker recovered' || bad 'stale request recovery'
new_root stale-barrier; make_package sb; make_manifest sb CRITICAL 1 0.1.1-dev
mkdir -p "$ROOT/tmp/vward-update.lock"; printf '999999:%s:vward-update\n' "$(date +%s)" > "$ROOT/tmp/vward-update.lock/owner"
COMMAND=--check; set +e; run_update >/dev/null 2>&1; rc=$?; set -e; unset COMMAND
[ "$rc" -eq 0 ] && [ ! -d "$ROOT/tmp/vward-update.lock" ] && ok 'stale barrier directory recovered' || bad 'stale barrier recovery'
new_root malformed-barrier; make_package mb; make_manifest mb CRITICAL 1 0.1.1-dev
mkdir -p "$ROOT/tmp/vward-update.lock"; printf 'garbage\n' > "$ROOT/tmp/vward-update.lock/owner"
COMMAND=--check; set +e; run_update >/dev/null 2>&1; rc=$?; set -e; unset COMMAND
[ "$rc" -eq 33 ] && [ -d "$ROOT/tmp/vward-update.lock" ] && ok 'malformed barrier fails conservatively' || bad 'malformed barrier safety'

new_root live-barrier; make_package lb; make_manifest lb CRITICAL 1 0.1.1-dev
printf '#!/bin/sh\nsleep 30\n' > "$WORK/vward-update-holder.sh"; chmod 755 "$WORK/vward-update-holder.sh"; "$WORK/vward-update-holder.sh" & hp=$!
mkdir -p "$ROOT/tmp/vward-update.lock"; printf '%s:%s:vward-update\n' "$hp" "$(date +%s)" > "$ROOT/tmp/vward-update.lock/owner"
COMMAND=--check; set +e; run_update >/dev/null 2>&1; rc=$?; set -e; unset COMMAND
kill "$hp" 2>/dev/null || :; wait "$hp" 2>/dev/null || :
[ "$rc" -eq 33 ] && [ -d "$ROOT/tmp/vward-update.lock" ] && ok 'live barrier owner is preserved' || bad 'live barrier ownership'

new_root retry; make_package retry; make_manifest retry ROUTINE 1 0.1.1-dev
ATTEMPT_FILE=$WORK/retry-attempts; printf '0\n' > "$ATTEMPT_FILE"
set +e; VWARD_TEST_NOW_HM=23:59 run_watch 200 >/dev/null 2>&1; rc=$?; set -e
[ "$rc" -eq 20 ] && [ "$(cat "$ATTEMPT_FILE")" -eq 1 ] && ok 'deferred result has no fast retry' || bad 'deferred retry classification'
ATTEMPT_FILE=$WORK/network-attempts; printf '0\n' > "$ATTEMPT_FILE"
set +e; run_watch 500 >/dev/null 2>&1; rc=$?; set -e
[ "$rc" -eq 34 ] && [ "$(cat "$ATTEMPT_FILE")" -eq 4 ] && ok 'transient network result uses bounded fast retries' || bad 'network retry classification'

new_root allow
if VWARD_ROOT_PREFIX=$ROOT VWARD_UPDATE_CONFIG=$CONFIG sh -c '. "$1"; vu_safe_target /opt/bin/adaptive-route.sh && vu_safe_target /opt/etc/init.d/S90crond && ! vu_safe_target /opt/bin/other.sh && ! vu_safe_target /opt/etc/init.d/S99foreign' sh "$UPDATER/vward-update-common.sh"; then ok 'exact VWARD target ownership enforced'; else bad 'strict ownership'; fi

new_root component-owner; make_package component-owner
jq '(.files[0].component)="route-engine"' "$PKGDIR/package-manifest.json" > "$PKGDIR/package-manifest.next" && mv "$PKGDIR/package-manifest.next" "$PKGDIR/package-manifest.json"
tar -czf "$PACKAGE" -C "$PKGDIR" .; UNPACKED=$(find "$PKGDIR" -type f -exec wc -c {} \; | awk '{s+=$1} END {print s+0}'); make_manifest component-owner CRITICAL 1 0.1.1-dev
COMMAND=--dry-run; set +e; run_update >/dev/null 2>&1; rc=$?; set -e; unset COMMAND
[ "$rc" -eq 31 ] && ok 'component and target owner mismatch rejected' || bad 'component owner validation'

new_root package-extra; make_package package-extra
printf 'undeclared\n' > "$PKGDIR/files/undeclared.txt"
tar -czf "$PACKAGE" -C "$PKGDIR" .; UNPACKED=$(find "$PKGDIR" -type f -exec wc -c {} \; | awk '{s+=$1} END {print s+0}'); make_manifest package-extra CRITICAL 1 0.1.1-dev
COMMAND=--dry-run; set +e; run_update >/dev/null 2>&1; rc=$?; set -e; unset COMMAND
[ "$rc" -eq 31 ] && ok 'undeclared package payload rejected' || bad 'undeclared payload validation'

new_root component-state; make_package component-state; make_manifest component-state CRITICAL 1 0.1.1-dev
set +e; run_update >/dev/null 2>&1; apply_rc=$?; set -e
component_count=$(jq '.components | length' "$STATE/components.json" 2>/dev/null || printf 0)
set +e; env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" "$UPDATER/vward-update-rollback.sh" >/dev/null 2>&1; rollback_rc=$?; set -e
[ "$apply_rc" -eq 0 ] && [ "$component_count" -eq 2 ] && [ "$rollback_rc" -eq 0 ] && [ ! -e "$STATE/components.json" ] && ok 'component state commits and rolls back atomically' || bad 'component state transaction'

new_root cumulative; make_package cumulative
printf 'minimum_free_kb=0\n' >> "$CONFIG"
awk 'BEGIN{for(i=0;i<1300;i++)printf "A"; printf "\n"}' > "$PKGDIR/files/adaptive-route.sh"
awk 'BEGIN{for(i=0;i<1300;i++)printf "B"; printf "\n"}' > "$PKGDIR/files/wan-guardian.sh"
one=$(sha256sum "$PKGDIR/files/adaptive-route.sh"|awk '{print $1}'); two=$(sha256sum "$PKGDIR/files/wan-guardian.sh"|awk '{print $1}')
jq -n --arg one "$one" --arg two "$two" '{schema:1,files:[{source:"files/adaptive-route.sh",target:"/opt/bin/adaptive-route.sh",sha256:$one,mode:"0755",component:"route-tools",restart_policy:"none",config_policy:"program-only"},{source:"files/wan-guardian.sh",target:"/opt/bin/wan-guardian.sh",sha256:$two,mode:"0755",component:"wan-guardian",restart_policy:"none",config_policy:"program-only"}]}' > "$PKGDIR/package-manifest.json"
tar -czf "$PACKAGE" -C "$PKGDIR" .
UNPACKED=$(find "$PKGDIR" -type f -exec wc -c {} \; | awk '{s+=$1} END {print s+0}')
make_manifest cumulative CRITICAL 1 0.1.1-dev
set +e; VWARD_TEST_FREE_TARGET_KB=2 run_update >/dev/null 2>&1; rc=$?; set -e
[ "$rc" -eq 33 ] && [ "$(cat "$ROOT/opt/bin/adaptive-route.sh")" = old ] && ok 'cumulative target space rejects transaction before install' || bad 'cumulative target space'

new_root unpacked; make_package unpacked; bad_unpacked=$((UNPACKED-1)); make_manifest unpacked CRITICAL 1 0.1.1-dev "$bad_unpacked"
COMMAND=--dry-run; set +e; run_update >/dev/null 2>&1; rc=$?; set -e; unset COMMAND
[ "$rc" -eq 31 ] && ok 'signed unpacked-size mismatch rejected' || bad 'unpacked size protection'

new_root orphan; make_package orphan; make_manifest orphan CRITICAL 1 0.1.1-dev
mkdir -p "$ROOT/opt/var/cache/vward/updater/transaction.999" "$STATE/pending"; printf keep > "$STATE/pending/keep.me"
COMMAND=--check; set +e; run_update >/dev/null 2>&1; rc=$?; set -e; unset COMMAND
[ "$rc" -eq 0 ] && [ ! -d "$ROOT/opt/var/cache/vward/updater/transaction.999" ] && [ -f "$STATE/pending/keep.me" ] && ok 'orphan staging cleaned without deleting pending cache' || bad 'orphan staging cleanup'

new_root race; make_package race; make_manifest race CRITICAL 1 0.1.1-dev
set +e; VWARD_TEST_CONFLICT_AFTER_BARRIER=1 run_update >/dev/null 2>&1; rc=$?; set -e
[ "$rc" -eq 33 ] && [ "$(cat "$ROOT/opt/bin/adaptive-route.sh")" = old ] && ok 'post-barrier race is rejected before install' || bad 'two-phase barrier recheck'

new_root verify-retry; make_package verify-retry; make_manifest verify-retry CRITICAL 1 0.1.1-dev
jq '.signature="AAAA"' "$MANIFEST" > "$MANIFEST.bad"; MANIFEST=$MANIFEST.bad
ATTEMPT_FILE=$WORK/verify-attempts; printf '0\n' > "$ATTEMPT_FILE"
set +e; run_watch 200 >/dev/null 2>&1; rc=$?; set -e
[ "$rc" -eq 31 ] && [ "$(cat "$ATTEMPT_FILE")" -eq 1 ] && ok 'signature failure is not fast-retried' || bad 'verification retry classification'

new_root oversized; make_package oversized; make_manifest oversized CRITICAL 1 0.1.1-dev
printf 'EXTRA-DATA-THAT-EXCEEDS-SIGNED-SIZE' >> "$PACKAGE"
COMMAND=--dry-run; set +e; run_update >/dev/null 2>&1; rc=$?; set -e; unset COMMAND
[ "$rc" -eq 31 ] && [ ! -e "$STATE/pending/package.tar.gz" ] && ok 'oversized package body is rejected' || bad 'bounded package body'

printf '1..%s\n' "$number"
printf '# passed=%s failed=%s\n' "$passed" "$failed"
[ "$failed" -eq 0 ]
