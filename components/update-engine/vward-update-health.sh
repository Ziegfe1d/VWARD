#!/bin/sh

set -u

SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SELF_DIR/vward-update-common.sh"

profile=${1:-default}

[ -z "$VU_ROOT_PREFIX" ] || [ "${VWARD_TEST_FORCE_HEALTH_FAIL:-0}" != 1 ] || exit "$VU_HEALTH_ERROR"

check_path()
{
    path=$1
    mode=${2:-}
    [ -r "$path" ] || vu_die "$VU_HEALTH_ERROR" "Health check failed: missing $path"
    if [ "$mode" = 0755 ]; then
        [ -x "$path" ] || vu_die "$VU_HEALTH_ERROR" "Health check failed: not executable $path"
    fi
    case "$path" in
        *.sh|*/init.d/S*|*/cgi-bin/*.cgi)
            sh -n "$path" >/dev/null 2>&1 ||
                vu_die "$VU_HEALTH_ERROR" "Health check failed: shell syntax $path"
            ;;
        *.json)
            jq -e . "$path" >/dev/null 2>&1 ||
                vu_die "$VU_HEALTH_ERROR" "Health check failed: invalid JSON $path"
            ;;
    esac
}

case "$profile" in
    default)
        required="$VU_ROOT_PREFIX/opt/bin/vward-route.sh $VU_ROOT_PREFIX/opt/bin/vward-wan-guard.sh $VU_ROOT_PREFIX/opt/share/vward/console/www/index.html"
        ;;
    updater)
        required="$VU_ROOT_PREFIX/opt/share/vward/updater/current/vward-update.sh"
        ;;
    full)
        required="$VU_ROOT_PREFIX/opt/share/vward/VERSION $VU_ROOT_PREFIX/opt/share/vward/package-map.tsv"
        ;;
    route-engine)
        required="$VU_ROOT_PREFIX/opt/bin/vward-route-engine.sh $VU_ROOT_PREFIX/opt/bin/vward-route-reconciler.sh"
        ;;
    route-tools)
        required="$VU_ROOT_PREFIX/opt/bin/vward-route.sh $VU_ROOT_PREFIX/opt/bin/vward-route-discovery.sh"
        ;;
    tunnel-guard)
        required="$VU_ROOT_PREFIX/opt/bin/vward-tunnel-health.sh $VU_ROOT_PREFIX/opt/bin/vward-tunnel-guard.sh"
        ;;
    wan-guard)
        required="$VU_ROOT_PREFIX/opt/bin/vward-wan-guard.sh $VU_ROOT_PREFIX/opt/bin/vward-wan-recovery.sh"
        ;;
    policy-sync)
        required="$VU_ROOT_PREFIX/opt/bin/vward-policy-audit.sh $VU_ROOT_PREFIX/opt/bin/vward-policy-sync.sh"
        ;;
    wifi-client-guard)
        required="$VU_ROOT_PREFIX/opt/bin/vward-wifi-client-monitor.sh $VU_ROOT_PREFIX/opt/bin/vward-wifi-client-analyze.sh $VU_ROOT_PREFIX/opt/bin/vward-wifi-client-control.sh $VU_ROOT_PREFIX/opt/bin/vward-wifi-client-scheduler.sh"
        ;;
    runtime)
        required="$VU_ROOT_PREFIX/opt/bin/vward-cron-supervisor.sh $VU_ROOT_PREFIX/opt/etc/init.d/S91vward-route-engine"
        ;;
    console)
        required="$VU_ROOT_PREFIX/opt/share/vward/settings-registry.json $VU_ROOT_PREFIX/opt/share/vward/console/www/index.html $VU_ROOT_PREFIX/opt/share/vward/console/www/assets/vward-console.css $VU_ROOT_PREFIX/opt/share/vward/console/www/assets/vward-console.js $VU_ROOT_PREFIX/opt/share/vward/console/www/cgi-bin/api.cgi"
        ;;
    ads-privacy-guard)
        required="$VU_ROOT_PREFIX/opt/bin/vward-ads-privacy-health.sh $VU_ROOT_PREFIX/opt/bin/vward-ads-privacy-scheduler.sh $VU_ROOT_PREFIX/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh $VU_ROOT_PREFIX/opt/share/vward/ads-privacy-guard/source-registry.json"
        ;;
    *) vu_die "$VU_CONFIG_ERROR" "Unknown health profile: $profile" ;;
esac

for path in $required; do
    check_path "$path"
done

if [ "$profile" = full ]; then
    package_map="$VU_ROOT_PREFIX/opt/share/vward/package-map.tsv"
    checked=0
    while IFS="$(printf '\t')" read -r component source target mode extra; do
        case "$component" in ''|'#'*) continue ;; esac
        [ -z "${extra:-}" ] || vu_die "$VU_HEALTH_ERROR" "Health check failed: malformed package map"
        case "$target:$mode" in /opt/*:0644|/opt/*:0755) ;; *)
            vu_die "$VU_HEALTH_ERROR" "Health check failed: unsafe package map entry"
            ;;
        esac
        check_path "$VU_ROOT_PREFIX$target" "$mode"
        checked=$((checked + 1))
    done < "$package_map"
    [ "$checked" -gt 0 ] || vu_die "$VU_HEALTH_ERROR" "Health check failed: empty package map"
fi

if [ -z "$VU_ROOT_PREFIX" ]; then
    command -v ndmc >/dev/null 2>&1 || vu_die "$VU_HEALTH_ERROR" "ndmc is unavailable"
    ndmc -c "show version" >/dev/null 2>&1 || vu_die "$VU_HEALTH_ERROR" "Keenetic control plane is unavailable"

    if [ "$profile" = updater ] || [ "$profile" = full ]; then
        updater_status=$("$VU_ROOT_PREFIX/opt/share/vward/updater/current/vward-update.sh" --status 2>/dev/null || true)
        printf '%s\n' "$updater_status" | grep -Eq '^phase=(IDLE|AVAILABLE|VERIFYING|COMMITTED|ROLLED_BACK)$' ||
            vu_die "$VU_HEALTH_ERROR" "VWARD Update Engine status check failed"
    fi

    if [ "$profile" = ads-privacy-guard ] ||
       { [ "$profile" = full ] && [ -r /opt/etc/vward/ads-privacy-guard/ads-privacy-guard.conf ]; }; then
        /opt/bin/vward-ads-privacy-health.sh >/dev/null 2>&1 ||
            vu_die "$VU_HEALTH_ERROR" "Ads & Privacy Guard functional health check failed"
    fi

    if [ "$profile" = console ] || [ "$profile" = full ]; then
        VWARD_PROFILE_LIB=${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}
        [ -r "$VWARD_PROFILE_LIB" ] || vu_die "$VU_HEALTH_ERROR" "device profile library is unavailable"
        . "$VWARD_PROFILE_LIB"
        vward_profile_load || vu_die "$VU_HEALTH_ERROR" "device profile is incomplete"
        console_pid=$(cat /opt/var/run/vward-console-lighttpd.pid 2>/dev/null || true)
        [ -n "$console_pid" ] && kill -0 "$console_pid" 2>/dev/null ||
            vu_die "$VU_HEALTH_ERROR" "VWARD Console service is unavailable"

        console_ping=$(/opt/bin/curl --fail --silent --show-error \
            --connect-timeout 2 --max-time 5 \
            "http://$VWARD_LAN_ADDRESS:$VWARD_CONSOLE_PORT/cgi-bin/api.cgi?action=ping" 2>/dev/null || true)
        printf '%s\n' "$console_ping" | /opt/bin/jq -e \
            '.ok == true and .service == "vward-console"' >/dev/null 2>&1 ||
            vu_die "$VU_HEALTH_ERROR" "VWARD Console API health check failed"
    fi
fi

vu_log INFO "Health profile $profile passed"
exit "$VU_OK"
