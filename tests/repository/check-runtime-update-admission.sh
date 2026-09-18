#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
LIB="$ROOT/components/runtime/lib/vward-runtime-admission.sh"
UPDATER="$ROOT/components/update-engine/vward-update-common-base.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT HUP INT TERM

fail() { echo "FAIL: $*" >&2; exit 1; }

[ -r "$LIB" ] || fail "runtime admission library is missing"

VWARD_ROOT_PREFIX="$TMP/root"
VWARD_ADMISSION_OWNER_UID=$(id -u)
export VWARD_ROOT_PREFIX VWARD_ADMISSION_OWNER_UID
mkdir -p "$VWARD_ROOT_PREFIX/tmp"
. "$LIB"

vward_admission_enter test-worker || fail "ordinary worker was rejected"
SLOT=$VWARD_ADMISSION_SLOT
[ -d "$SLOT" ] || fail "active slot was not created"
vward_admission_leave || fail "owned active slot was not removed"
[ ! -e "$SLOT" ] || fail "active slot remains after leave"

printf 'updater\n' > "$VWARD_ROOT_PREFIX/tmp/vward-update-requested"
if vward_admission_enter blocked-worker; then
    fail "worker entered after update request"
fi
[ ! -d "$VWARD_ROOT_PREFIX/tmp/vward-runtime-active" ] ||
    [ -z "$(find "$VWARD_ROOT_PREFIX/tmp/vward-runtime-active" -mindepth 1 -maxdepth 1 -print -quit)" ] ||
    fail "rejected worker left an active slot"
rm -f "$VWARD_ROOT_PREFIX/tmp/vward-update-requested"

ln -s "$VWARD_ROOT_PREFIX/tmp/symlink-target" "$VWARD_ROOT_PREFIX/tmp/vward-update-requested"
if vward_admission_enter symlink-worker; then
    fail "worker ignored a dangling request symlink"
fi
[ ! -e "$VWARD_ROOT_PREFIX/tmp/symlink-target" ] || fail "worker followed request symlink"
rm -f "$VWARD_ROOT_PREFIX/tmp/vward-update-requested"

VWARD_ADMISSION_TEST_REQUEST_AFTER_REGISTER=1
export VWARD_ADMISSION_TEST_REQUEST_AFTER_REGISTER
if vward_admission_enter raced-worker; then
    fail "worker crossed a request published after registration"
fi
unset VWARD_ADMISSION_TEST_REQUEST_AFTER_REGISTER
[ -f "$VWARD_ROOT_PREFIX/tmp/vward-update-requested" ] || fail "race hook did not publish request"
[ -z "$(find "$VWARD_ROOT_PREFIX/tmp/vward-runtime-active" -mindepth 1 -maxdepth 1 -print -quit)" ] ||
    fail "raced worker left an active slot"
rm -f "$VWARD_ROOT_PREFIX/tmp/vward-update-requested"

VU_ROOT_PREFIX="$VWARD_ROOT_PREFIX"
VU_RUN_DIR="$VWARD_ROOT_PREFIX/opt/var/run/vward"
export VU_ROOT_PREFIX VU_RUN_DIR
. "$UPDATER"

VU_LOCK_TOKEN="$$:$(date +%s):vward-update"
ln -s "$VWARD_ROOT_PREFIX/tmp/updater-symlink-target" "$VWARD_ROOT_PREFIX/tmp/vward-update-requested"
if vu_barrier_request; then
    fail "updater accepted a dangling request symlink"
fi
[ ! -e "$VWARD_ROOT_PREFIX/tmp/updater-symlink-target" ] || fail "updater followed request symlink"
rm -f "$VWARD_ROOT_PREFIX/tmp/vward-update-requested"

vward_admission_enter draining-worker || fail "draining worker could not enter"
if vu_activity_clear; then
    fail "updater ignored a registered active worker"
fi
vward_admission_leave || fail "draining worker slot cleanup failed"
vu_activity_clear || fail "updater did not observe drained workers"

mkdir "$VWARD_ROOT_PREFIX/tmp/vward-runtime-active/dead-worker.999999.1"
printf '999999\n' > "$VWARD_ROOT_PREFIX/tmp/vward-runtime-active/dead-worker.999999.1/pid"
printf '1\n' > "$VWARD_ROOT_PREFIX/tmp/vward-runtime-active/dead-worker.999999.1/pid_start"
printf 'dead-worker\n' > "$VWARD_ROOT_PREFIX/tmp/vward-runtime-active/dead-worker.999999.1/component"
vu_activity_clear || fail "dead active slot was not reclaimed"
[ ! -e "$VWARD_ROOT_PREFIX/tmp/vward-runtime-active/dead-worker.999999.1" ] || fail "dead active slot remains"

mkdir "$VWARD_ROOT_PREFIX/tmp/vward-runtime-active/malformed"
printf 'invalid\n' > "$VWARD_ROOT_PREFIX/tmp/vward-runtime-active/malformed/pid"
printf '1\n' > "$VWARD_ROOT_PREFIX/tmp/vward-runtime-active/malformed/pid_start"
if vu_activity_clear; then
    fail "malformed active slot did not fail closed"
fi
rm -rf "$VWARD_ROOT_PREFIX/tmp/vward-runtime-active/malformed"

for required in \
    vward-route-reconciler-maint.lock \
    vward-route-engine.lock \
    vward-policy-sync.lock \
    vward-policy-reconcile.lock \
    vward-tunnel-health-watch.lock \
    vward-tunnel-guard-guard.lock \
    vward-wan-guard.lock.d \
    vward-route.lock \
    vward-route-discovery.lock
do
    grep -Fq "$required" "$UPDATER" || fail "updater conflict inventory misses $required"
done

for legacy_lock in \
    /opt/var/lib/vward/policy-sync/lock \
    /opt/var/lib/vward/route-engine/classifier.lock \
    /opt/var/lib/vward/ads-privacy-guard/scan.lock \
    /opt/var/lib/vward/ads-privacy-guard/sources-update.lock \
    /opt/var/lib/vward/ads-privacy-guard/publish.lock \
    /opt/var/lib/vward/ads-privacy-guard/jobs/worker.lock
do
    grep -Fq "$legacy_lock" "$UPDATER" || fail "updater transition inventory misses $legacy_lock"
done

for participant in \
    components/route-engine/scripts/vward-route-engine.sh \
    components/route-reconciler/scripts/vward-route-reconciler.sh \
    components/route-tools/scripts/vward-route.sh \
    components/route-tools/scripts/vward-route-discovery.sh \
    components/route-tools/scripts/vward-route-hints-update.sh \
    components/tunnel-guard/scripts/vward-tunnel-health.sh \
    components/tunnel-guard/scripts/vward-tunnel-guard.sh \
    components/wan-guard/scripts/vward-wan-guard.sh \
    components/policy-sync/scripts/vward-policy-chain.sh \
    components/policy-sync/scripts/vward-policy-audit.sh \
    components/policy-sync/scripts/vward-policy-reconcile.sh \
    components/policy-sync/scripts/vward-policy-sync.sh \
    components/runtime/scripts/vward-housekeeping.sh \
    components/ads-privacy-guard/scripts/vward-ads-privacy-scheduler.sh
do
    grep -Fq 'vward_admission_enter ' "$ROOT/$participant" || fail "runtime participant misses admission: $participant"
    grep -Fq 'vward_admission_leave ' "$ROOT/$participant" || fail "runtime participant misses release: $participant"
done


for ads_leaf in \
    vward-ads-privacy-control.sh \
    vward-ads-privacy-guard.sh \
    vward-ads-privacy-https.sh \
    vward-ads-privacy-job.sh \
    vward-ads-privacy-publish.sh \
    vward-ads-privacy-rules-rebuild.sh \
    vward-ads-privacy-settings.sh \
    vward-ads-privacy-source-control.sh \
    vward-ads-privacy-sources-update.sh
do
    grep -Fq 'ads_admission_enter ' "$ROOT/components/ads-privacy-guard/scripts/$ads_leaf" ||
        fail "Ads leaf mutator misses admission: $ads_leaf"
done
grep -Fq 'vward_admission_enter domain-classifier' "$ROOT/components/route-engine/scripts/vward-domain-classifier.sh" ||
    fail "domain classifier catalog mutation misses admission"

APPLY_BODY=$(sed -n '/^apply_update()/,/^}/p' "$ROOT/components/update-engine/vward-update.sh")
REQUEST_LINE=$(printf '%s\n' "$APPLY_BODY" | grep -n 'vu_barrier_request' | head -n 1 | cut -d: -f1)
QUIESCE_LINE=$(printf '%s\n' "$APPLY_BODY" | grep -n 'vu_runtime_quiesce' | head -n 1 | cut -d: -f1)
[ -n "$REQUEST_LINE" ] && [ -n "$QUIESCE_LINE" ] && [ "$REQUEST_LINE" -lt "$QUIESCE_LINE" ] ||
    fail "update request is not published before runtime quiesce"

grep -Fq 'updater_mutation_busy(){' "$ROOT/web/cgi-bin/api.cgi" || fail "Console mutation barrier is missing"
grep -Fq 'console_mutation_enter(){' "$ROOT/web/cgi-bin/api.cgi" || fail "Console mutation admission is missing"
for marker in /opt/var/run/vward/updater.lock /tmp/vward-update-requested /tmp/vward-update.lock; do
    grep -Fq "$marker" "$ROOT/web/cgi-bin/api.cgi" || fail "Console mutation barrier misses $marker"
done

echo "Runtime update admission checks passed."
