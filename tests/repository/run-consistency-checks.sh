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
    docs/DISCOVERY.md
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
grep -Fq "if(id==='logs')loadLog(logName);window.scrollTo(0,0)" web/index.html ||
    fail "Logs must load before compatibility-safe scroll"

for ID in platform-core route-engine route-reconciler route-tools tunnel-guard \
    wan-guard policy-sync runtime console update-engine
do
    grep -Fq "\"id\": \"$ID\"" config/components/component-registry.json ||
        fail "registry component missing: $ID"
    grep -Fq "'$ID':" web/index.html || fail "Console component mapping missing: $ID"
done

grep -Fq '"/opt/bin/vward-discovery.sh"' config/components/component-registry.json ||
    fail "VWARD Discovery runtime target missing"

grep -Fq 'DISCOVERY="${VWARD_DISCOVERY:-/opt/bin/vward-discovery.sh}"' web/cgi-bin/api.cgi ||
    fail "Console API does not declare the shared Discovery provider"
grep -Fq '"$DISCOVERY" snapshot' web/cgi-bin/api.cgi ||
    fail "Console API does not consume the unified Discovery snapshot"
grep -Fq 'name:(.rci_id // "")' web/cgi-bin/api.cgi ||
    fail "Console API compatibility alias must come from discovered rci_id"
grep -Fq 'wg_discovery_state' web/cgi-bin/api.cgi ||
    fail "Console API does not expose WireGuard Discovery state"
grep -Fq 'wan_discovery_state' web/cgi-bin/api.cgi ||
    fail "Console API does not expose WAN Discovery state"
grep -Fq 'observer_source:"legacy-wan-guardian"' web/cgi-bin/api.cgi ||
    fail "Console API must label transitional legacy WAN observer data"
grep -Fq "'http://127.0.0.1:79/rci/show/interface'" web/cgi-bin/api.cgi >/dev/null &&
    fail "Console API must not maintain a second full interface inventory"
grep -Fq 'show/interface?name=ISP' web/cgi-bin/api.cgi >/dev/null &&
    fail "Console API must not hardcode the WAN role as ISP"
grep -Eq 'Wireguard[0-9]|nwg[0-9]' web/cgi-bin/api.cgi >/dev/null &&
    fail "Console API contains installation-specific WireGuard hardcode"

SNAPSHOT_CALLS=$(grep -Fc '"$DISCOVERY" snapshot' web/cgi-bin/api.cgi || true)
[ "$SNAPSHOT_CALLS" -eq 1 ] ||
    fail "Console API must perform exactly one Discovery snapshot per status request"

grep -Fq 'discovery_snapshot()' components/runtime-supervision/scripts/vward-discovery.sh ||
    fail "Discovery snapshot implementation missing"
grep -Fq 'select(((.value.role // []) | index("misc")) == null)' \
    components/runtime-supervision/scripts/vward-discovery.sh ||
    fail "WAN discovery must exclude VPN misc role"

for LOG_NAME in wan recovery cron routing updater tunnel policy console
do
    grep -Fq "data-log=\"$LOG_NAME\"" web/index.html ||
        fail "Console log tab missing: $LOG_NAME"
    grep -Eq "^[[:space:]]*$LOG_NAME\)" web/cgi-bin/api.cgi ||
        fail "Console log allowlist missing: $LOG_NAME"
done

sh -n web/cgi-bin/api.cgi || fail "Console API syntax"
python3 tests/repository/check-console-bindings.py || fail "Console bindings"
for SCRIPT in components/*/scripts/*.sh components/runtime-supervision/init.d/* \
    components/updater/*.sh tests/updater/*.sh tests/repository/*.sh
do
    sh -n "$SCRIPT" || fail "shell syntax: $SCRIPT"
done

for TEST in tests/repository/test-*.sh
do
    "$TEST" || fail "repository test: $TEST"
done

echo "CONSISTENCY_CHECKS=PASS"