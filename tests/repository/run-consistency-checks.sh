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

for DOC in docs/INSTALL.md docs/INSTALLATION_MAP.md docs/DEPENDENCIES.md docs/CONSOLE.md \
    docs/NAMING_MIGRATION.md docs/UPDATER_ARCHITECTURE.md \
    docs/UPDATE_POLICY.md docs/UPDATE_RECOVERY.md docs/UPDATE_SECURITY.md \
    docs/SECURITY_HARDENING.md
do
    [ -r "$DOC" ] || fail "missing documentation: $DOC"
done

grep -E 'Smart Updater|>Update</button>|192\.168\.1\.1' web/index.html >/dev/null &&
    fail "Console contains legacy naming or universal device hardcode"
grep -E '\?\.|\?\?|scrollTo\(\{' web/index.html >/dev/null &&
    fail "Console contains incompatible mobile JavaScript"

grep -Fq 'function svgIcon' web/index.html || fail "local SVG icon system missing"
grep -Fq 'componentNames=' web/index.html || fail "component display mapping missing"
grep -Fq 'id="settings"' web/index.html || fail "safe settings overview missing"
grep -Fq 'border-radius:28px' web/index.html || fail "floating mobile toolbar missing"
grep -Fq 'bottom:max(10px,env(safe-area-inset-bottom))' web/index.html ||
    fail "mobile toolbar safe-area handling missing"
grep -Fq "if(id==='logs')loadLogs(false);if(id==='route')loadRouteData(false);if(id==='updater')loadUpdateData(false);renderHelp();setHelp(false);window.scrollTo(0,0)" web/index.html ||
    fail "Logs/route-data/help must update before compatibility-safe scroll"

for ID in platform-core route-engine route-reconciler route-tools tunnel-guard \
    wan-guard policy-sync runtime console update-engine
do
    grep -Fq "\"id\": \"$ID\"" config/components/component-registry.json ||
        fail "registry component missing: $ID"
    grep -Fq "'$ID':" web/index.html || fail "Console component mapping missing: $ID"
done

for LOG_NAME in wan recovery cron routing updater tunnel policy console
do
    grep -Fq "data-log=\"$LOG_NAME\"" web/index.html ||
        fail "Console log tab missing: $LOG_NAME"
    grep -Eq "^[[:space:]]*$LOG_NAME\)" web/cgi-bin/api.cgi ||
        fail "Console log allowlist missing: $LOG_NAME"
done

sh -n web/cgi-bin/api.cgi || fail "Console API syntax"
python3 tests/repository/check-console-bindings.py || fail "Console bindings"
python3 tests/repository/check-console-security.py || fail "Console security"
python3 tests/repository/check-policy-sync-safety.py || fail "VPN audit safety"
for SCRIPT in components/*/scripts/*.sh components/runtime/init.d/* \
    components/update-engine/*.sh tests/updater/*.sh
do
    sh -n "$SCRIPT" || fail "shell syntax: $SCRIPT"
done

echo "CONSISTENCY_CHECKS=PASS"
