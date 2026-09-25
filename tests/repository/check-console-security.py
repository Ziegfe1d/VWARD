#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import tempfile
import time
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
assert "'X-VWARD-Request': 'console'" in JS
assert "Access-Control-Allow-Origin" not in API + CONF
assert "apiGet('security-data')" in JS
assert 'security-data' in API
assert '<style' not in UI and '<script>' not in UI and 'style="' not in UI + JS
assert "script-src 'self'" in CONF and "style-src 'self'" in CONF
assert '/assets/vward-console.css' in UI and '/assets/vward-console.js' in UI
assert 'wildcard:false' not in API
assert 'CONSOLE_RUNTIME_CONFIG' in API and 'socket_state' in API and 'config_test' in API
assert ':3000/' not in UI + JS

# Root CGI scratch files must not use predictable PID-derived names.  A local
# user could pre-create those paths as symlinks and make the Console disclose
# or overwrite arbitrary files when it captures the running configuration.
route_probe = API.split('if [ "$ACTION" = "route-probe" ]; then', 1)[1].split(
    'if [ "$ACTION" = "update-data" ]; then', 1
)[0]
assert '/tmp/vward-console-route-probe.$$' not in route_probe
assert '/tmp/vward-console-ip-matches.$$' not in route_probe
assert 'umask 077' in route_probe
assert 'RUNCFG="$(mktemp /tmp/vward-console-route-probe.XXXXXX 2>/dev/null)" || {' in route_probe
assert 'MATCHES_FILE="$(mktemp /tmp/vward-console-ip-matches.XXXXXX 2>/dev/null)" || {' in route_probe
assert route_probe.count('"error":"temporary_file_unavailable"') == 2
assert 'rm -f "$RUNCFG"' in route_probe
assert '[ -z "$MATCHES_FILE" ] || rm -f "$MATCHES_FILE"' in route_probe
assert 'trap route_probe_cleanup EXIT' in route_probe
assert "trap 'exit 1' HUP INT TERM" in route_probe

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
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
    }
    result = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], input=body, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.split("\n\n", 1)[1])

assert call_ads("op=allow&domain=bad..example&scope=exact")["error"] == "invalid_domain"
assert call_ads("op=allow&domain=_bad.example&scope=exact")["error"] == "invalid_domain"
assert call_ads("op=source-mode&source=bad%2Fid&mode=active")["error"] == "invalid_source"
assert call_ads("op=source-mode&source=good-source&mode=unsafe")["error"] == "invalid_source_mode"
assert call_ads("op=pause", guard="wrong")["error"] == "request_guard_failed"

assert "\\\\" not in API, "double-escaped sequences print literal backslashes in BusyBox printf/tr/awk/jq"


def call_api(query: str, body: str = "", method: str = "GET") -> dict:
    env = os.environ | {
        "REQUEST_METHOD": method,
        "QUERY_STRING": query,
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "CONTENT_LENGTH": str(len(body.encode())),
        "HTTP_X_VWARD_REQUEST": "console",
        "JQ": jq,
        "VWARD_PROFILE_LIB": "/nonexistent",
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
    }
    result = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], input=body, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.split("\n\n", 1)[1])

env_rci_down = os.environ | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=status", "JQ": jq,
                             "CURL": "/bin/false", "VWARD_PROFILE_LIB": "/nonexistent"}
status = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=env_rci_down, text=True, capture_output=True)
assert json.loads(status.stdout.split("\n\n", 1)[1]).get("ok") is True, "status must survive an unavailable RCI"

assert "?//" not in API, "jq 1.7 parses '?//' as the destructuring operator; write '(x? // y)'"
assert call_api("action=ads-data").get("ok") is True, "ads-data must render without Ads Guard state"

probe = call_api("action=route-probe&type=ip&value=203.0.113.7")
assert probe.get("ok") is True and probe["value"] == "203.0.113.7", probe
assert call_api("action=route-probe&type=ip&value=203.0.113.300")["error"] == "invalid_ipv4"
# Parsed op reaches the allowlist (the command itself is absent in the test tree).
assert call_api("action=control", "op=route-reconcile&confirm=ROUTE_RECONCILE", "POST")["error"] == "action_unavailable"
assert call_api("action=control", "op=bogus&confirm=X", "POST")["error"] == "unknown_control_action"
for op in ("wan-renew", "wan-bounce"):
    assert call_api("action=control", f"op={op}", "POST")["error"] in ("action_unavailable", "confirmation_required")
assert 'wan-bounce) COMP=wan-guard; CMD=/opt/bin/vward-wan-recovery.sh; ARG=wan-bounce; REQUIRED=WAN_BOUNCE' in API
assert 'wan-renew) COMP=wan-guard; CMD=/opt/bin/vward-wan-recovery.sh; ARG=dhcp-renew; REQUIRED=WAN_RENEW' in API
assert call_api("action=update-control", "op=check", "POST")["error"] == "action_unavailable"
# Update operations run detached: an install outlasts the browser's request, so
# update-control returns at once and update-data reports the phase and result.
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    fake = td / "vward-update.sh"
    fake.write_text('#!/bin/sh\necho "State transition: CHECKING $1"\nsleep 3\necho done\nexit 20\n')
    fake.chmod(0o755)
    os.environ["VWARD_UPDATER_BIN"] = str(fake)
    os.environ["VWARD_CONSOLE_UPDATE_RUN"] = str(td / "run")
    try:
        began = time.monotonic()
        got = call_api("action=update-control", "op=check", "POST")
        assert got.get("ok") is True and got.get("started") is True, got
        assert time.monotonic() - began < 2, "update-control must not wait for the updater"
        assert call_api("action=update-control", "op=check", "POST")["error"] == "updater_busy"
        data = call_api("action=update-data")
        assert data["busy"] is True and data["run"]["running"] is True and data["run"]["label"] == "update-check", data
        # No engine 2 installed here: version 1, no per-file apply yet.
        assert data["engine"] == {"version": "1"} and data["last_apply"] is None, data
        for _ in range(60):
            run = call_api("action=update-data")["run"]
            if run["finished"]:
                break
            time.sleep(0.25)
        assert run["finished"] is True and run["running"] is False and run["rc"] == 20, run
        assert "CHECKING --check" in run["output"] and "done" in run["output"], run
    finally:
        del os.environ["VWARD_UPDATER_BIN"], os.environ["VWARD_CONSOLE_UPDATE_RUN"]
with tempfile.TemporaryDirectory() as td:
    os.environ["VWARD_CONSOLE_CONTROL_RUN"] = td
    try:
        idle = call_api("action=control-data")
        assert idle.get("ok") is True and idle["run"]["running"] is False and idle["run"]["rc"] is None, idle
    finally:
        del os.environ["VWARD_CONSOLE_CONTROL_RUN"]
assert 'refresh-hints|route-reconcile|policy-refresh|policy-reconcile|housekeeping) run_detached "$CONTROL_RUN_DIR" control_busy' in API
# Ads views and source management: strict input before anything runs.
assert call_api("action=ads-view&view=querylog&search=a%26b")["error"] == "invalid_value"
assert call_api("action=ads-view&view=shell")["error"] in ("invalid_view", "action_unavailable")
assert call_ads("op=source-add&url=http%3A%2F%2Fx.example%2Fl.txt&format=hosts")["error"] == "invalid_url"
assert call_ads("op=source-add&url=https%3A%2F%2Fuser%40x.example%2Fl.txt&format=hosts")["error"] == "invalid_url"
assert call_ads("op=source-add&url=https%3A%2F%2Fx.example%2F%0Al.txt&format=hosts")["error"] == "invalid_url"
assert call_ads("op=source-add&url=https%3A%2F%2Fx.example%2Fl.txt&format=json")["error"] == "invalid_format"
assert call_ads("op=source-delete&source=hagezi-pro")["error"] == "invalid_source"
assert call_ads("op=source-category&category=ads%3Breboot&state=off")["error"] == "invalid_category"
# A valid address decodes and reaches the (absent) source tool.
assert call_ads("op=source-add&url=https%3A%2F%2Flists.example.org%2Fa.txt%3Fv%3D1&format=adblock").get("error") is None
print("console security checks: PASS")
