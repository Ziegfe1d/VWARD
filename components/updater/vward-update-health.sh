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
    route-engine)
        required="$VU_ROOT_PREFIX/opt/bin/agh-adaptive-live.sh $VU_ROOT_PREFIX/opt/bin/adaptive-auto-maint.sh"
        ;;
    route-tools)
        required="$VU_ROOT_PREFIX/opt/bin/adaptive-route.sh $VU_ROOT_PREFIX/opt/bin/agh-adaptive-route.sh"
        ;;
    tunnel-guard)
        required="$VU_ROOT_PREFIX/opt/bin/wg-health-watch.sh $VU_ROOT_PREFIX/opt/bin/wg-failopen-guard.sh"
        ;;
    wan-guard)
        required="$VU_ROOT_PREFIX/opt/bin/wan-health-watch.sh $VU_ROOT_PREFIX/opt/bin/wan-recovery-plan.sh $VU_ROOT_PREFIX/opt/bin/wan-guardian.sh $VU_ROOT_PREFIX/opt/bin/wan-recovery-actuator.sh"
        ;;
    policy-sync)
        required="$VU_ROOT_PREFIX/opt/bin/vpn-domain-audit.sh $VU_ROOT_PREFIX/opt/bin/vpn-subnet-sync.sh"
        ;;
    runtime)
        required="$VU_ROOT_PREFIX/opt/bin/crond-supervisor.sh $VU_ROOT_PREFIX/opt/etc/init.d/S91adaptive-live"
        ;;
    console)
        required="$VU_ROOT_PREFIX/opt/share/keenetic-apps/www/index.html $VU_ROOT_PREFIX/opt/share/keenetic-apps/www/cgi-bin/api.cgi"
        ;;
    *) vu_die "$VU_CONFIG_ERROR" "Unknown health profile: $profile" ;;
esac

for path in $required; do
    [ -r "$path" ] || vu_die "$VU_HEALTH_ERROR" "Health check failed: missing $path"
done

if [ -z "$VU_ROOT_PREFIX" ]; then
    command -v ndmc >/dev/null 2>&1 || vu_die "$VU_HEALTH_ERROR" "ndmc is unavailable"
    ndmc -c "show version" >/dev/null 2>&1 || vu_die "$VU_HEALTH_ERROR" "Keenetic control plane is unavailable"

    if [ "$profile" = console ]; then
        console_pid=$(cat /opt/var/run/keenetic-apps-lighttpd.pid 2>/dev/null || true)
        [ -n "$console_pid" ] && kill -0 "$console_pid" 2>/dev/null ||
            vu_die "$VU_HEALTH_ERROR" "VWARD Console service is unavailable"

        console_ping=$(/opt/bin/curl --fail --silent --show-error \
            --connect-timeout 2 --max-time 5 \
            'http://192.168.1.1:8088/cgi-bin/api.cgi?action=ping' 2>/dev/null || true)
        printf '%s\n' "$console_ping" | /opt/bin/jq -e \
            '.ok == true and .service == "vward-console"' >/dev/null 2>&1 ||
            vu_die "$VU_HEALTH_ERROR" "VWARD Console API health check failed"
    fi
fi

vu_log INFO "Health profile $profile passed"
exit "$VU_OK"
