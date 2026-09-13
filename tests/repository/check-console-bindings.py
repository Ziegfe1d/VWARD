#!/usr/bin/env python3

import re
import shutil
import subprocess
import tempfile
from pathlib import Path


root = Path(__file__).resolve().parents[2]
html = (root / "web/index.html").read_text(encoding="utf-8")
api = (root / "web/cgi-bin/api.cgi").read_text(encoding="utf-8")


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


section_ids = set(re.findall(r'<section class="section(?: active)?" id="([^"]+)"', html))
section_links = set(re.findall(r'data-section="([^"]+)"', html))
go_links = {
    value for value in re.findall(r'data-go="([^"]+)"', html) if "+" not in value
}
map_ids = set(re.findall(r"([a-z]+):\['", html))

missing_sections = (section_links | go_links) - section_ids
if missing_sections:
    fail("нет разделов для переходов: " + ", ".join(sorted(missing_sections)))

missing_map = section_ids - map_ids
if missing_map:
    fail("нет заголовков разделов: " + ", ".join(sorted(missing_map)))

log_tabs = set(re.findall(r'data-log="([^"]+)"', html))
api_logs = set(re.findall(r'^\s{8}([a-z]+)\)\s*$', api, re.MULTILINE))
missing_logs = log_tabs - api_logs
if missing_logs:
    fail("нет allowlist для журналов: " + ", ".join(sorted(missing_logs)))

if len(log_tabs) != 8:
    fail(f"ожидалось 8 вкладок журналов, найдено {len(log_tabs)}")

for marker in ("helpBtn", "helpPanel", "logSearch", "logRefresh", "logAuto", "logCopy", "logSave", "logShare"):
    if f'id="{marker}"' not in html:
        fail(f"нет элемента Console: {marker}")

if "navigator.clipboard.writeText" not in html or "fallbackCopy" not in html:
    fail("копирование журнала не имеет Clipboard/fallback binding")
if "navigator.share" not in html:
    fail("поделиться журналом не связано с Web Share API")

if 'action=route-data' not in html or 'route-data' not in api:
    fail("Route Engine read-only data endpoint is not bound")
if 'id="routeDataRefresh"' not in html:
    fail("Route Engine data refresh control is missing")


for marker in ("runDiagnostics", "routeProbeBtn", "routeProbeValue", "tunnelHealthBtn", "updateActionResult", "routeActionResult"):
    if f'id="{marker}"' not in html:
        fail(f"нет control-plane элемента: {marker}")
for action in ("diagnostics", "route-probe", "control", "update-control"):
    if action not in api:
        fail(f"нет API action: {action}")
if "action=exec" in api or "action=file" in api or "action=ndmc" in api:
    fail("обнаружен запрещённый generic control API")
for token in ("ROUTE_RECONCILE", "POLICY_REFRESH", "POLICY_RECONCILE", "APPLY_UPDATE", "ROLLBACK_UPDATE", "RECOVER_UPDATE"):
    if token not in api:
        fail(f"нет server-side confirmation token: {token}")


for marker in ("settingsSearch", "prefTheme", "prefRefresh", "prefLogInterval", "prefLogCount", "prefLogWrap", "updateActionState"):
    if f'id="{marker}"' not in html:
        fail(f"нет settings/update-state элемента: {marker}")
if 'action=update-data' not in html or 'update-data' not in api:
    fail("Update Engine action availability endpoint is not bound")
if 'state_action_not_allowed' not in api or 'rollback_unavailable' not in api or 'recovery_not_required' not in api:
    fail("Update Engine server-side state preconditions are incomplete")
if "count='+encodeURIComponent(prefs.logCount)" not in html:
    fail("bounded log tail preference is not bound")


for marker in ("logAll", "logReset", "tunnelSelect", "tunnelSelectedStats", "routeListSearch", "routeListSort"):
    if f'id="{marker}"' not in html:
        fail(f"нет финального элемента prompt-gap closure: {marker}")
if '<option value="group">FQDN-группа</option>' not in html or 'group_not_found' not in api:
    fail("FQDN group probe is incomplete")
if 'Runtime сейчас не хранит отдельную достоверную state-machine очереди' not in html:
    fail("Route Engine lifecycle limitation is not disclosed")

node = shutil.which("node")
if node:
    start = html.find("<script>")
    end = html.find("</script>", start + 8)
    if start < 0 or end < 0:
        fail("inline Console JavaScript block is missing")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as f:
        f.write(html[start + len("<script>"):end])
        js_path = f.name
    result = subprocess.run([node, "--check", js_path], capture_output=True, text=True)
    if result.returncode != 0:
        fail("Console JavaScript syntax: " + (result.stderr.strip() or result.stdout.strip()))

for name in ("overview", "settings", "logs"):
    desktop = len(re.findall(rf'<button[^>]+data-section="{name}"', html))
    if desktop < 1:
        fail(f"раздел {name} недоступен из навигации")

if not re.search(r'<nav class="mobile"[^>]*>.*data-section="settings"', html):
    fail("настройки недоступны из мобильной навигации")

print("CONSOLE_BINDINGS=PASS")
