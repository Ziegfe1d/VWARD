#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
for f in "$ROOT"/components/ads-privacy-guard/lib/*.sh "$ROOT"/components/ads-privacy-guard/scripts/*.sh "$ROOT"/components/ads-privacy-guard/https/*.sh "$ROOT"/components/ads-privacy-guard/https/providers/*.sh; do busybox sh -n "$f"; done
for f in "$ROOT"/components/route-engine/lib/*.sh "$ROOT"/components/route-engine/scripts/*.sh; do busybox sh -n "$f"; done
busybox sh -n "$ROOT/web/cgi-bin/api.cgi"
find "$ROOT" -type f -name '*.json' -print | while IFS= read -r f; do jq -e . "$f" >/dev/null; done
if command -v node >/dev/null 2>&1; then node --check "$ROOT/web/assets/vward-console.js" >/dev/null; fi
python3 "$ROOT/tests/repository/check-ads-privacy-settings-registry.py" >/dev/null
python3 "$ROOT/tests/repository/check-ads-privacy-integration.py" >/dev/null
TERM=xterm "$ROOT/tests/ads-privacy-guard/run-simulations.sh"
TERM=xterm "$ROOT/tests/ads-privacy-guard/run-https-simulations.sh"
TERM=xterm "$ROOT/tests/route-engine/run-domain-classifier-simulations.sh"
if grep -RInE '192\.168\.1\.|65053|3001|br0|nwg1|eth3|domain-list[0-9]+' "$ROOT/components/ads-privacy-guard" "$ROOT/config/ads-privacy-guard" "$ROOT/components/route-engine" "$ROOT/config/route-engine" >/tmp/vward-ads-hardcodes.$$; then cat /tmp/vward-ads-hardcodes.$$; rm -f /tmp/vward-ads-hardcodes.$$; echo 'FAIL: current-device hardcode in production component' >&2; exit 1; fi
rm -f /tmp/vward-ads-hardcodes.$$
if grep -RInEi 'BEGIN (RSA|OPENSSH|EC|PRIVATE) KEY|private[_-]?key[=:]|password[=:][^[:space:]]|token[=:][A-Za-z0-9_-]{12,}|api[_-]?key[=:][A-Za-z0-9_-]{12,}|aeternia' \
  "$ROOT/components/ads-privacy-guard" "$ROOT/config/ads-privacy-guard" \
  "$ROOT/components/route-engine/data" "$ROOT/components/route-engine/lib" \
  "$ROOT/config/route-engine" "$ROOT/web" \
  --exclude=SHA256SUMS --exclude=run-package-validation.sh >/tmp/vward-ads-secrets.$$; then cat /tmp/vward-ads-secrets.$$; rm -f /tmp/vward-ads-secrets.$$; echo 'FAIL: secret-like material found' >&2; exit 1; fi
rm -f /tmp/vward-ads-secrets.$$
if [ -r "$ROOT/SHA256SUMS" ]; then
  (cd "$ROOT" && sha256sum -c SHA256SUMS >/dev/null) || { echo 'FAIL: SHA256SUMS mismatch' >&2; exit 1; }
fi
echo PACKAGE_VALIDATION=PASS
