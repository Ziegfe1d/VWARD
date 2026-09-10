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
grep -E '\?\.[A-Za-z_$]|\?\.\[|\?\.\(|\?\?|scrollTo\(\{' web/index.html >/dev/null &&
    fail "Console contains incompatible mobile JavaScript"

grep -Fq 'function svgIcon' web/index.html || fail "local SVG icon system missing"
grep -Fq 'componentNames=' web/index.html || fail "component display mapping missing"
grep -Fq 'id="settings"' web/index.html || fail "safe settings overview missing"
grep -Fq 'border-radius:28px' web/index.html || fail "floating mobile toolbar missing"
grep -Fq 'bottom:max(10px,env(safe-area-inset-bottom))' web/index.html ||
    fail "mobile toolbar safe-area handling missing"
grep -Fq "if(id==='logs')loadLog(logName);window.scrollTo(0,0)" web/index.html ||
    fail "Logs must load before compatibility-safe scroll"
grep -Fq "wanUp=w.status==='UP'" web/index.html ||
    fail "Console WAN visual state must use observer status"
grep -Fq 'wan:[w.internet===true' web/index.html >/dev/null &&
    fail "Console WAN card must not use global Internet status as health"
grep -Fq "badge('wanPill',w.internet===true" web/index.html >/dev/null &&
    fail "Console WAN pill must not use global Internet status as health"
grep -Fq 'wan:w.internet===true?1:0' web/index.html >/dev/null &&
    fail "Console WAN history must not use global Internet status as health"

for ID in platform-core route-engine route-reconciler route-tools tunnel-guard \
    wan-guard policy-sync runtime console update-engine
do
    grep -Fq "\"id\": \"$ID\"" config/components/component-registry.json ||
        fail "registry component missing: $ID"
    grep -Fq "'$ID':" web/index.html || fail "Console component mapping missing: $ID"
done

grep -Fq '"/opt/bin/vward-discovery.sh"' config/components/component-registry.json ||
    fail "VWARD Discovery runtime target missing"
grep -Fq '"/opt/bin/wan-health-watch.sh"' config/components/component-registry.json ||
    fail "WAN observer runtime target missing"

grep -Fq '/opt/bin/wan-health-watch.sh > /tmp/wan-health-watch.cron.out' config/cron/root.crontab ||
    fail "separate WAN observer cron missing"
grep -Fq '/opt/bin/wan-guardian.sh > /tmp/wan-guardian.cron.out' config/cron/root.crontab ||
    fail "legacy WAN recovery cron missing"
WAN_HEALTH_CRON_COUNT=$(grep -Fc '/opt/bin/wan-health-watch.sh > /tmp/wan-health-watch.cron.out' config/cron/root.crontab || true)
WAN_GUARDIAN_CRON_COUNT=$(grep -Fc '/opt/bin/wan-guardian.sh > /tmp/wan-guardian.cron.out' config/cron/root.crontab || true)
[ "$WAN_HEALTH_CRON_COUNT" -eq 1 ] || fail "WAN observer cron must exist exactly once"
[ "$WAN_GUARDIAN_CRON_COUNT" -eq 1 ] || fail "legacy WAN recovery cron must exist exactly once"
grep -F '/opt/bin/wan-health-watch.sh' config/cron/root.crontab | grep -Fq '/opt/bin/wan-guardian.sh' &&
    fail "WAN observer and recovery must not be chained in one cron entry"

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
grep -Fq 'WAN_HEALTH_STATE=/opt/var/lib/wan-health/state' web/cgi-bin/api.cgi ||
    fail "Console API does not consume WAN observer state"
grep -Fq 'observer_source:"wan-health-watch"' web/cgi-bin/api.cgi ||
    fail "Console API must identify the Discovery-driven WAN observer"
grep -Fq 'recovery_source:"legacy-wan-guardian"' web/cgi-bin/api.cgi ||
    fail "Console API must keep legacy WAN recovery source explicit"
grep -Fq 'WAN_CLASS="OBSERVER_STALE"' web/cgi-bin/api.cgi ||
    fail "Console API must fail safe on stale WAN observer state"
grep -Fq 'WAN_CLASS="OBSERVER_ROLE_MISMATCH"' web/cgi-bin/api.cgi ||
    fail "Console API must reject WAN observer state from another RCI role"
grep -Fq 'WAN_CLASS="OBSERVER_MAPPING_MISMATCH"' web/cgi-bin/api.cgi ||
    fail "Console API must reject WAN observer state from another Linux mapping"
grep -Fq 'WAN_CLASS="DISCOVERY_${WAN_DISCOVERY_STATE}"' web/cgi-bin/api.cgi ||
    fail "Console API must prefer current WAN Discovery failure over stale health"
grep -Fq 'FILE=/opt/var/log/wan-health.log' web/cgi-bin/api.cgi ||
    fail "Console WAN log must use WAN observer log"
grep -Fq 'GOUT=/tmp/wan-guardian.cron.out' web/cgi-bin/api.cgi ||
    fail "Console API must keep recovery telemetry separate from observer state"
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

WAN_OBSERVER=components/wan-guardian/scripts/wan-health-watch.sh
[ -x "$WAN_OBSERVER" ] || fail "WAN observer must be executable"
grep -Fq '"$DISCOVERY" wan-guard' "$WAN_OBSERVER" ||
    fail "WAN observer must consume wan-guard role"
grep -Fq 'VWARD_WAN_HEALTH_DIR' "$WAN_OBSERVER" ||
    fail "WAN observer state contract missing"
grep -Fq '[ "$INTERNET" = "true" ] && [ "$NETWORK_OK" -eq 1 ]' "$WAN_OBSERVER" ||
    fail "WAN HEALTHY classification must require a bound selected-path probe"
if grep -Eq 'ip dhcp client renew|interface [^" ]+ (down|up)|[Nn][Dd][Mm][Cc]' "$WAN_OBSERVER"; then
    fail "read-only WAN observer contains mutation command"
fi
if grep -Eq 'Wireguard[0-9]|nwg[0-9]|eth3|192\.168\.|show/interface\?name=ISP' "$WAN_OBSERVER"; then
    fail "WAN observer contains installation-specific network hardcode"
fi

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
