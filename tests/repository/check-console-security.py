#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONF = (ROOT / "web/lighttpd.conf").read_text()
API = (ROOT / "web/cgi-bin/api.cgi").read_text()
UI = (ROOT / "web/index.html").read_text()

assert 'server.bind = "192.168.1.1"' in CONF
assert 'server.bind = "0.0.0.0"' not in CONF
assert 'server.bind = "::"' not in CONF
assert 'dir-listing.activate = "disable"' in CONF
assert 'url.access-deny' in CONF
for header in ("Content-Security-Policy", "Permissions-Policy", "Referrer-Policy", "X-Content-Type-Options", "X-Frame-Options"):
    assert header in CONF
    assert header in API
assert 'GET|POST) ;;' in API
assert 'OPTIONS)' not in API
assert '${HTTP_X_VWARD_REQUEST:-}' in API
assert 'application/x-www-form-urlencoded' in API
assert "'X-VWARD-Request':'console'" in UI
assert "Access-Control-Allow-Origin" not in API + CONF
print("console security checks: PASS")
