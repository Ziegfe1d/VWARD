#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
UPDATER="$ROOT/components/updater"
HEALTH="$UPDATER/vward-update-health.sh"
REGISTRY="$ROOT/config/components/component-registry.json"

TMP="${TMPDIR:-/tmp}/vward-updater-wan-policy-test.$$"
ROOTFS="$TMP/root"
mkdir -p "$ROOTFS/tmp" "$ROOTFS/opt/bin"
trap 'rm -rf "$TMP"' EXIT INT TERM

fail()
{
    echo "FAIL: $*" >&2
    exit 1
}

VWARD_ROOT_PREFIX="$ROOTFS"
export VWARD_ROOT_PREFIX
SELF_DIR="$UPDATER"
export SELF_DIR

. "$UPDATER/vward-update-common.sh"

for target in \
    /opt/bin/wan-health-watch.sh \
    /opt/bin/wan-capability.sh \
    /opt/bin/wan-recovery-plan.sh \
    /opt/bin/wan-recovery-actuator.sh
do
    vu_safe_target "$target" || fail "WAN target is not allowed by updater: $target"
done

if vu_safe_target /opt/bin/not-a-vward-target.sh; then
    fail "unknown updater target must remain denied"
fi

vu_activity_clear || fail "clean runtime should pass activity gate"
mkdir -p "$ROOTFS/tmp/wan-health-watch.lock"
if vu_activity_clear; then
    fail "WAN observer lock must block updater quiescing"
fi
rmdir "$ROOTFS/tmp/wan-health-watch.lock"
vu_activity_clear || fail "activity gate did not recover after observer lock removal"

for target in \
    wan-health-watch.sh \
    wan-capability.sh \
    wan-recovery-plan.sh \
    wan-guardian.sh \
    wan-recovery-actuator.sh
do
    printf '#!/bin/sh\nexit 0\n' > "$ROOTFS/opt/bin/$target"
    chmod 0755 "$ROOTFS/opt/bin/$target"
done

VWARD_ROOT_PREFIX="$ROOTFS" sh "$HEALTH" wan-guard >/dev/null 2>&1 ||
    fail "wan-guard health profile rejected complete runtime set"

rm -f "$ROOTFS/opt/bin/wan-capability.sh"
if VWARD_ROOT_PREFIX="$ROOTFS" sh "$HEALTH" wan-guard >/dev/null 2>&1; then
    fail "wan-guard health must fail when capability provider is missing"
fi
printf '#!/bin/sh\nexit 0\n' > "$ROOTFS/opt/bin/wan-capability.sh"
chmod 0755 "$ROOTFS/opt/bin/wan-capability.sh"

rm -f "$ROOTFS/opt/bin/wan-recovery-plan.sh"
if VWARD_ROOT_PREFIX="$ROOTFS" sh "$HEALTH" wan-guard >/dev/null 2>&1; then
    fail "wan-guard health must fail when Recovery Planner is missing"
fi

for target in \
    /opt/bin/wan-health-watch.sh \
    /opt/bin/wan-capability.sh \
    /opt/bin/wan-recovery-plan.sh \
    /opt/bin/wan-recovery-actuator.sh
do
    jq -e --arg target "$target" '
        any(.components[];
            .id == "wan-guard" and
            (.runtime_targets | index($target) != null))
    ' "$REGISTRY" >/dev/null 2>&1 ||
        fail "WAN runtime target missing from component registry: $target"
done

sh -n "$UPDATER/vward-update-runtime-policy.sh" || fail "runtime policy shell syntax"
sh -n "$HEALTH" || fail "updater health shell syntax"

echo "UPDATER_WAN_RUNTIME_POLICY_TESTS=PASS"
