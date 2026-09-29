#!/usr/bin/env python3
"""The Ads page loads fast on the router: it asks only what it shows (not AdGuard Home's
filters and services, 8 s, nor its counters), ads-data asks the component's programs side
by side, and AdGuard Home's API address is resolved once and kept ten minutes, not with the
whole device profile before every request."""

import os
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text()
API = (ROOT / "web/cgi-bin/api.cgi").read_text()
LIB = ROOT / "components/ads-privacy-guard/lib/vward-ads-privacy-common.sh"
VIEW = (ROOT / "components/ads-privacy-guard/scripts/vward-ads-privacy-view.sh").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"ADS_PAGE_SPEED=FAIL: {message}")


if "{ id: 'ads', title: 'Реклама и трекеры', icon: 'block', group: 'Сеть', data: ['ads', 'security', 'adspub'] }" not in JS:
    fail("the Ads page must load only ads, security and adspub")
a = JS.index("  ads() {")
page = JS[a:JS.index("  'd-adrecent'() {", a)]
for used in ("S.agh", "S.adsstats"):
    if used in page:
        fail(f"the Ads page now uses {used!r}: add its loader back to the page data")

blk = API[API.index('if [ "$ACTION" = ads-data ]; then'):]
blk = blk[:blk.index("\nfi\n")]
for name in ("SETJSON", "SOURCES", "JOBS", "GUARD", "GHOSTS", "CLIENTS", "ROUTEDNS"):
    if f'> "$PD/{name}" &' not in blk:
        fail(f"ads-data must ask {name} in the background")
if blk.index("  wait") > blk.index('SETJSON="$(cat "$PD/SETJSON")"'):
    fail("ads-data reads the answers after wait")

if 'case "${1:-}" in stats|querylog|agh|check) ads_agh_base_export ;; esac' not in VIEW:
    fail("the views resolve AdGuard Home's address once")

# The address: resolved once, then read from the cache; a stale or odd cache is resolved again.
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    cache = tmp / "base"
    calls = tmp / "calls"
    script = f'''
. "{LIB}"
ads_agh_api_base() {{ echo x >> "{calls}"; echo http://192.0.2.1:3000/control; }}
unset AGH_API_BASE; ads_agh_base_export; echo "1=$AGH_API_BASE"
unset AGH_API_BASE; ads_agh_base_export; echo "2=$AGH_API_BASE"
echo 'http://evil/x' > "{cache}"; unset AGH_API_BASE; ads_agh_base_export; echo "3=$AGH_API_BASE"
touch -d '@{int(time.time()) - 3600}' "{cache}"; unset AGH_API_BASE; ads_agh_base_export; echo "4=$AGH_API_BASE"
AGH_API_BASE=http://set/control; ads_agh_base_export; echo "5=$AGH_API_BASE"
'''
    env = os.environ | {"ADS_AGH_BASE_CACHE": str(cache), "VWARD_ADS_LIB": str(LIB)}
    for shell in (["sh"], ["busybox", "sh"]):
        if shell[0] == "busybox" and subprocess.run(["which", "busybox"], capture_output=True).returncode:
            continue
        cache.unlink(missing_ok=True); calls.unlink(missing_ok=True)
        r = subprocess.run(shell + ["-c", script], env=env, text=True, capture_output=True)
        got = dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)
        want = {"1": "http://192.0.2.1:3000/control", "2": "http://192.0.2.1:3000/control", "3": "http://192.0.2.1:3000/control",
                "4": "http://192.0.2.1:3000/control", "5": "http://set/control"}
        n = len(calls.read_text().splitlines()) if calls.exists() else 0
        if got != want or n != 3:
            fail(f"{shell[0]}: address cache {got}, resolved {n} times (want 3: first, odd cache, stale cache) {r.stderr[-300:]}")
        if oct(cache.stat().st_mode & 0o777) != "0o600":
            fail(f"the cache is private: {oct(cache.stat().st_mode)}")

print("ADS_PAGE_SPEED=PASS")
