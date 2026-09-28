#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
# device.conf belongs to root on the router; the test fixtures belong to the runner.
VWARD_DEVICE_CONFIG_OWNER_UID=$(id -u)
export VWARD_DEVICE_CONFIG_OWNER_UID
cd "$ROOT"

fail() { echo "FAIL: $*" >&2; exit 1; }

VERSION=$(sed -n '1p' VERSION)
REGISTRY_VERSION=$(sed -n 's/.*"platform_version": "\([^"]*\)".*/\1/p' config/components/component-registry.json)
[ -n "$VERSION" ] || fail "VERSION is empty"
[ "$VERSION" = "$REGISTRY_VERSION" ] || fail "VERSION and registry differ"
grep -Fq "**$VERSION**" README.md || fail "README version differs"
python3 tests/repository/check-version-synchronization.py || fail "Version synchronization"
python3 tests/repository/check-no-personal-data.py || fail "no data of the owner's router in the repository"

for DOC in docs/INSTALL.md docs/INSTALLATION_MAP.md docs/DEPENDENCIES.md docs/PANEL.md \
    docs/NAMING_MIGRATION.md docs/UPDATER_ARCHITECTURE.md \
    docs/UPDATE_POLICY.md docs/UPDATE_RECOVERY.md docs/UPDATE_SECURITY.md \
    docs/SECURITY_HARDENING.md
do
    [ -r "$DOC" ] || fail "missing documentation: $DOC"
done

grep -E 'Smart Updater|>Update</button>|192\.168\.1\.1' web/index.html web/assets/vward-console.js >/dev/null &&
    fail "Panel contains legacy naming or universal device hardcode"
# Keenetic's BusyBox stat has no -c; the CI host's BusyBox does, so only this catches it.
grep -rnE '(^|[^A-Za-z_])stat +(-c|--format|--printf)' components web scripts >/dev/null &&
    fail "router code uses stat -c, which Keenetic BusyBox lacks"
# Entware jq is built without Oniguruma: test/match/sub and friends fail at run time.
# awk's sub/gsub/match take commas, jq's take semicolons.
grep -rnE --include='*.sh' --include='*.cgi' '(^|[^a-z_])(test|capture|scan|splits)\(|(sub|gsub|match)\("[^"]*";' \
    components web scripts >/dev/null &&
    fail "router jq uses a regex function, which Entware jq lacks"
grep -E '\?\.|\?\?|scrollTo\(\{' web/assets/vward-console.js >/dev/null &&
    fail "Panel contains incompatible mobile JavaScript"

grep -Fq 'function iconSvg' web/assets/vward-console.js || fail "canonical SVG icon system missing"
grep -Fq "{ id: 'settings', title: 'Настройки'" web/assets/vward-console.js || fail "settings section missing"
grep -Fq 'border-radius:28px' web/assets/vward-console.css || fail "floating mobile toolbar missing"
grep -Fq 'env(safe-area-inset-bottom,0px)' web/assets/vward-console.css ||
    fail "mobile toolbar safe-area handling missing"

for ID in platform-core route-engine route-reconciler route-tools tunnel-guard \
    wan-guard wifi-client-guard policy-sync runtime console update-engine ads-privacy-guard
do
    grep -Fq "\"id\": \"$ID\"" config/components/component-registry.json ||
        fail "registry component missing: $ID"
    grep -Fq "{ id: '$ID', name: '" web/assets/vward-console.js || fail "Panel component mapping missing: $ID"
done

for LOG_NAME in wan recovery cron routing updater tunnel policy console wifi ads
do
    grep -Fq "{ id: '$LOG_NAME', label: '" web/assets/vward-console.js ||
        fail "Panel log tab missing: $LOG_NAME"
    grep -Eq "^[[:space:]]*$LOG_NAME\)" web/cgi-bin/api.cgi ||
        fail "Panel log allowlist missing: $LOG_NAME"
done

sh -n web/cgi-bin/api.cgi || fail "Panel API syntax"
python3 tests/repository/check-console-bindings.py || fail "Panel bindings"
python3 tests/repository/check-console-activity.py || fail "sections show their events in plain words"
python3 tests/repository/check-console-responsive.py || fail "Panel responsive layout"
python3 tests/repository/check-console-icon-system.py || fail "Panel icon and typography system"
python3 tests/repository/check-console-security.py || fail "Panel security"
python3 tests/repository/check-console-config.py || fail "Panel configuration writer"
python3 tests/repository/check-console-domain-lists.py || fail "Panel domain lists"
python3 tests/repository/check-console-list-addrs.py || fail "Panel learned addresses of a list"
python3 tests/repository/check-console-addresses.py || fail "Panel page addresses"
python3 tests/repository/check-console-route-probe.py || fail "Panel address check"
python3 tests/repository/check-services-catalog.py || fail "Services catalog"
python3 tests/repository/check-console-services.py || fail "Panel services"
python3 tests/repository/check-awg-engine.py || fail "Tunnel engine (AmneziaWG)"
python3 tests/repository/check-list-watch.py || fail "Route engine list watch"
python3 tests/repository/check-wan-guard-params.py || fail "Internet guard limits"
python3 tests/repository/check-console-tunnel-probe.py || fail "Panel tunnel check"
python3 tests/repository/check-console-site-test.py || fail "site check, tunnel restart and switch-on"
python3 tests/repository/check-tunnel-fallback.py || fail "fallback tunnel and tunnel quality"
python3 tests/repository/check-tunnel-services.py || fail "services checked through every tunnel"
python3 tests/repository/check-route-engine-alt-tunnel.py || fail "route engine tries the other tunnels"
python3 tests/repository/check-console-agh-auth.py || fail "Panel AdGuard Home login"
python3 tests/repository/check-console-smartdns.py || fail "Smart DNS guard"
python3 tests/repository/check-console-tunnels.py || fail "Panel tunnels"
python3 tests/repository/check-ads-agh-settings.py || fail "AdGuard Home ad settings"
python3 tests/repository/check-ads-agh-clients.py || fail "Device names reach AdGuard Home without a restart"
python3 tests/repository/check-ads-dns-guard.py || fail "DNS of every device goes through AdGuard Home"
python3 tests/repository/check-ads-route-dns.py || fail "routed domains go through Keenetic DNS"
python3 tests/repository/check-route-sources.py || fail "routing sources keep their last good copy"
python3 tests/repository/check-ads-agh-smartdns.py || fail "AdGuard Home Smart DNS rows for tunnel lists"
python3 tests/repository/check-ads-default-config.py || fail "Ads default settings"
python3 tests/repository/check-console-backups.py || fail "Settings backups"
python3 tests/repository/check-update-manual-install.py || fail "Manual install from VWARD"
python3 tests/repository/check-wifi-hosts.py || fail "Wi-Fi device names and access"
python3 tests/repository/check-console-files.py || fail "Files page: read only, secrets closed"
python3 tests/repository/check-console-devices.py || fail "Only registered devices open VWARD"
python3 tests/repository/check-route-engine-names.py || fail "Route engine sends only valid names"
python3 tests/repository/check-route-engine-classify.py || fail "Route engine checks a name against all lists in one pass"
python3 tests/repository/check-route-engine-watchdog.py || fail "Watchdog counts engine cores, not subshells"
python3 tests/repository/check-console-diagnostics-dns.py || fail "Diagnostics: DNS chain, files as installed"
python3 tests/repository/check-console-ndm-cache.py || fail "Panel caches Keenetic answers briefly"
python3 tests/repository/check-release-notes.py || fail "What is new in a version"
python3 tests/repository/check-console-request.py || fail "Panel request guards and form parsing"
python3 tests/repository/check-housekeeping.py || fail "Housekeeping rotates logs and keeps copies to their newest few"
python3 tests/repository/check-ext-update.py || fail "Updates of other software"
python3 tests/repository/check-stale-locks.py || fail "Locks whose owner is gone are removed at boot and hourly"
python3 tests/repository/check-console-tunnel.py || fail "Panel tunnel switch"
python3 tests/repository/check-component-graph.py || fail "Component dependency graph"
python3 tests/repository/check-component-resilience.py || fail "Component disable resilience"
python3 tests/repository/check-ads-console.py || fail "Ads Panel functions"
python3 tests/repository/check-console-auth.py || fail "Panel login"
python3 tests/repository/check-device-profile.py || fail "Device profile"
python3 tests/repository/check-settings-registry.py || fail "Settings registry"
python3 tests/repository/check-update-schema-registry.py || fail "Updater schema registry"
python3 tests/repository/check-dev-release-pipeline.py || fail "Dev release pipeline"
python3 tests/repository/check-package-map.py || fail "Signed package map"
python3 tests/repository/check-wifi-client-guard.py || fail "Wi-Fi Client Guard safety"
sh tests/repository/check-update-boot-recovery.sh || fail "Updater boot recovery"
sh tests/repository/check-full-health-profile.sh || fail "Full update health profile"
python3 tests/repository/check-ads-privacy-settings-registry.py || fail "Ads & Privacy Guard settings registry"
python3 tests/repository/check-ads-privacy-integration.py || fail "Ads & Privacy Guard integration"
grep -Fq 'interface $VWARD_WAN_INTERFACE down' components/wan-guard/scripts/vward-wan-guard.sh || fail "WAN down action is not profile-bound"
grep -Fq 'interface $VWARD_WAN_INTERFACE up' components/wan-guard/scripts/vward-wan-guard.sh || fail "WAN up action is not profile-bound"
grep -Fq '"$CAPTURE_FILTER"' components/route-engine/scripts/vward-route-engine.sh || fail "DNS capture filter is not expanded safely"
grep -Fq "'src net \$VWARD_LAN_SUBNET" components/route-engine/scripts/vward-route-engine.sh && fail "DNS capture filter remains single-quoted"
python3 tests/repository/check-policy-sync-safety.py || fail "VPN audit safety"
python3 tests/repository/check-policy-groups.py || fail "IP categories see tunnel lists"
sh tests/repository/check-wan-guard-recovery.sh || fail "WAN recovery cancellation safety"
python3 tests/repository/check-wan-manual-recovery.py || fail "Manual WAN recovery"
sh tests/repository/check-runtime-pid-safety.sh || fail "Runtime PID identity safety"
sh tests/repository/check-terminating-signal-traps.sh || fail "Terminating signal trap safety"
sh tests/repository/check-runtime-update-admission.sh || fail "Runtime update admission safety"
sh tests/repository/check-updater-stale-lock-atomic.sh || fail "Updater stale-lock atomicity"
sh tests/repository/check-external-archive-safety.sh || fail "External archive safety"
python3 tests/repository/check-cutover-cron-parity.py || fail "Cutover cron parity"
for SCRIPT in components/*/scripts/*.sh components/runtime/init.d/* \
    components/update-engine/*.sh tests/updater/*.sh scripts/beta-to-dev-cutover.sh
do
    sh -n "$SCRIPT" || fail "shell syntax: $SCRIPT"
done

echo "CONSISTENCY_CHECKS=PASS"
