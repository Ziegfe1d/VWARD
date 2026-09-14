#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONF = (ROOT / "web/lighttpd.conf").read_text()
API = (ROOT / "web/cgi-bin/api.cgi").read_text()
UI = (ROOT / "web/index.html").read_text()
JS = (ROOT / "web/assets/vward-console.js").read_text()
CSS = (ROOT / "web/assets/vward-console.css").read_text()

assert 'server.bind = "@VWARD_CONSOLE_BIND@"' in CONF
assert 'server.port = @VWARD_CONSOLE_PORT@' in CONF
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
assert "'X-VWARD-Request':'console'" in JS
assert "Access-Control-Allow-Origin" not in API + CONF
for marker in ('id="security"', 'id="securityRefresh"'):
    assert marker in UI
assert 'action=security-data' in JS
assert 'security-data' in API
assert '<style' not in UI and '<script>' not in UI and 'style="' not in UI + JS
assert "script-src 'self'" in CONF and "style-src 'self'" in CONF
assert '/assets/vward-console.css' in UI and '/assets/vward-console.js' in UI
assert 'wildcard:false' not in API
assert 'CONSOLE_RUNTIME_CONFIG' in API and 'socket_state' in API and 'config_test' in API
assert ':3000/' not in UI + JS

jq = shutil.which("jq")
assert jq

def call_ads(body: str, guard: str = "console") -> dict:
    env = os.environ | {
        "REQUEST_METHOD": "POST",
        "QUERY_STRING": "action=ads-control",
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "CONTENT_LENGTH": str(len(body.encode())),
        "HTTP_X_VWARD_REQUEST": guard,
        "JQ": jq,
        "VWARD_PROFILE_LIB": "/nonexistent",
    }
    result = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], input=body, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.split("\n\n", 1)[1])

assert call_ads("op=allow&domain=bad..example&scope=exact")["error"] == "invalid_domain"
assert call_ads("op=allow&domain=_bad.example&scope=exact")["error"] == "invalid_domain"
assert call_ads("op=source-mode&source=bad%2Fid&mode=active")["error"] == "invalid_source"
assert call_ads("op=source-mode&source=good-source&mode=unsafe")["error"] == "invalid_source_mode"
assert call_ads("op=pause", guard="wrong")["error"] == "request_guard_failed"
print("console security checks: PASS")
