#!/bin/sh

set -u

SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SELF_DIR/vward-update-common.sh"

profile=${1:-default}

[ -z "$VU_ROOT_PREFIX" ] || [ "${VWARD_TEST_FORCE_HEALTH_FAIL:-0}" != 1 ] || exit "$VU_HEALTH_ERROR"

case "$profile" in
    default)
        required="$VU_ROOT_PREFIX/opt/bin/adaptive-route.sh $VU_ROOT_PREFIX/opt/bin/wan-guardian.sh $VU_ROOT_PREFIX/opt/share/keenetic-apps/www/index.html"
        ;;
    updater)
        required="$VU_ROOT_PREFIX/opt/share/vward/updater/current/vward-update.sh"
        ;;
    *) vu_die "$VU_CONFIG_ERROR" "Unknown health profile: $profile" ;;
esac

for path in $required; do
    [ -r "$path" ] || vu_die "$VU_HEALTH_ERROR" "Health check failed: missing $path"
done

if [ -z "$VU_ROOT_PREFIX" ]; then
    command -v ndmc >/dev/null 2>&1 || vu_die "$VU_HEALTH_ERROR" "ndmc is unavailable"
    ndmc show version >/dev/null 2>&1 || vu_die "$VU_HEALTH_ERROR" "Keenetic control plane is unavailable"
fi

vu_log INFO "Health profile $profile passed"
exit "$VU_OK"
