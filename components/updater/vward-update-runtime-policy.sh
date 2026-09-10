#!/bin/sh

# Runtime target and quiescing policy overrides for VWARD Update Engine.
# Sourced after common-base and hardening so policy changes stay small and auditable.

vu_safe_target() {
    target=$1

    case "$target" in
        *../*|*/..|*/./*|*//* ) return 1 ;;
    esac

    case "$target" in
        /opt/bin/adaptive-2ip-test.sh|/opt/bin/adaptive-auto-maint.sh|/opt/bin/adaptive-hints-update.sh|/opt/bin/adaptive-housekeeping.sh|/opt/bin/adaptive-resolve4.sh|/opt/bin/adaptive-route.sh|/opt/bin/agh-adaptive-live.sh|/opt/bin/agh-adaptive-route.sh|/opt/bin/crond-supervisor.sh|/opt/bin/vpn-domain-audit-chain.sh|/opt/bin/vpn-domain-audit.sh|/opt/bin/vpn-night-reconcile.sh|/opt/bin/vpn-subnet-sync.sh|/opt/bin/wan-guardian.sh|/opt/bin/wan-health-watch.sh|/opt/bin/wan-recovery-plan.sh|/opt/bin/wan-recovery-actuator.sh|/opt/bin/wg-failopen-guard.sh|/opt/bin/wg-health-watch.sh|/opt/etc/init.d/S90crond|/opt/etc/init.d/S91adaptive-live|/opt/etc/init.d/S92crond-supervisor|/opt/etc/init.d/S93keenetic-apps|/opt/etc/keenetic-apps/lighttpd.conf|/opt/share/keenetic-apps/www/index.html|/opt/share/keenetic-apps/www/cgi-bin/api.cgi|/opt/share/vward/VERSION)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

vu_activity_clear() {
    [ ! -e "$VU_RUN_DIR/runtime-active" ] || return 1

    for conflict in \
        "$VU_ROOT_PREFIX/tmp/adaptive-auto-maint.lock" \
        "$VU_ROOT_PREFIX/tmp/agh-adaptive-live.lock" \
        "$VU_ROOT_PREFIX/tmp/vpn-domain-audit.lock" \
        "$VU_ROOT_PREFIX/tmp/vpn-night-reconcile.lock" \
        "$VU_ROOT_PREFIX/tmp/wg-failopen.lock" \
        "$VU_ROOT_PREFIX/tmp/wan-health-watch.lock" \
        "$VU_ROOT_PREFIX/tmp/wan-guardian.lock" \
        "$VU_ROOT_PREFIX/tmp/wan-guardian.lock.d"
    do
        [ ! -e "$conflict" ] || return 1
    done

    return 0
}
