#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
cd "$ROOT"

fail() { echo "FAIL: $*" >&2; exit 1; }

VERSION=$(sed -n '1p' VERSION)
REGISTRY_VERSION=$(sed -n 's/.*"platform_version": "\([^"]*\)".*/\1/p' config/components/component-registry.json)
[ -n "$VERSION" ] || fail "VERSION is empty"
[ "$VERSION" = "$REGISTRY_VERSION" ] || fail "VERSION and registry differ"
grep -Fq "**$VERSION**" README.md || fail "README version differs"
python3 tests/repository/check-version-synchronization.py || fail "Version synchronization"

for DOC in docs/INSTALL.md docs/INSTALLATION_MAP.md docs/DEPENDENCIES.md docs/CONSOLE.md \
    docs/NAMING_MIGRATION.md docs/UPDATER_ARCHITECTURE.md \
    docs/UPDATE_POLICY.md docs/UPDATE_RECOVERY.md docs/UPDATE_SECURITY.md \
    docs/SECURITY_HARDENING.md
do
    [ -r "$DOC" ] || fail "missing documentation: $DOC"
done

grep -E 'Smart Updater|>Update</button>|192\.168\.1\.1' web/index.html web/assets/vward-console.js >/dev/null &&
    fail "Console contains legacy naming or universal device hardcode"
grep -E '\?\.|\?\?|scrollTo\(\{' web/assets/vward-console.js >/dev/null &&
    fail "Console contains incompatible mobile JavaScript"

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
    grep -Fq "{ id: '$ID', name: '" web/assets/vward-console.js || fail "Console component mapping missing: $ID"
done

for LOG_NAME in wan recovery cron routing updater tunnel policy console wifi ads
do
    grep -Fq "{ id: '$LOG_NAME', label: '" web/assets/vward-console.js ||
        fail "Console log tab missing: $LOG_NAME"
    grep -Eq "^[[:space:]]*$LOG_NAME\)" web/cgi-bin/api.cgi ||
        fail "Console log allowlist missing: $LOG_NAME"
done

sh -n web/cgi-bin/api.cgi || fail "Console API syntax"
python3 tests/repository/check-console-bindings.py || fail "Console bindings"
python3 tests/repository/check-console-responsive.py || fail "Console responsive layout"
python3 tests/repository/check-console-icon-system.py || fail "Console icon and typography system"
python3 tests/repository/check-console-security.py || fail "Console security"
python3 tests/repository/check-console-config.py || fail "Console configuration writer"
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
sh tests/repository/check-wan-guard-recovery.sh || fail "WAN recovery cancellation safety"
sh tests/repository/check-runtime-pid-safety.sh || fail "Runtime PID identity safety"
sh tests/repository/check-terminating-signal-traps.sh || fail "Terminating signal trap safety"
sh tests/repository/check-runtime-update-admission.sh || fail "Runtime update admission safety"
sh tests/repository/check-updater-stale-lock-atomic.sh || fail "Updater stale-lock atomicity"
sh tests/repository/check-external-archive-safety.sh || fail "External archive safety"
for SCRIPT in components/*/scripts/*.sh components/runtime/init.d/* \
    components/update-engine/*.sh tests/updater/*.sh
do
    sh -n "$SCRIPT" || fail "shell syntax: $SCRIPT"
done

echo "CONSISTENCY_CHECKS=PASS"
