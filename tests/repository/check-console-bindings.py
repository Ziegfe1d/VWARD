#!/usr/bin/env python3

import re
import shutil
import subprocess
import tempfile
from pathlib import Path


root = Path(__file__).resolve().parents[2]
html = (root / "web/index.html").read_text(encoding="utf-8")
js = (root / "web/assets/vward-console.js").read_text(encoding="utf-8")
api = (root / "web/cgi-bin/api.cgi").read_text(encoding="utf-8")
ui = html + "\n" + js


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


html_ids = re.findall(r'\bid="([^"]+)"', html)
duplicate_ids = sorted({item for item in html_ids if html_ids.count(item) > 1})
if duplicate_ids:
    fail("повторяющиеся id: " + ", ".join(duplicate_ids))


section_ids = set(re.findall(r'<section class="section(?: active)?" id="([^"]+)"', html))
section_links = set(re.findall(r'data-section="([^"]+)"', html))
go_links = {
    value for value in re.findall(r'data-go="([^"]+)"', html) if "+" not in value
}
map_ids = set(re.findall(r"([a-z]+):\['", js))

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

if "navigator.clipboard.writeText" not in js or "fallbackCopy" not in js:
    fail("копирование журнала не имеет Clipboard/fallback binding")
if "navigator.share" not in js:
    fail("поделиться журналом не связано с Web Share API")
if "return await fetch(url" not in js or "return await apiFetch(url" in js:
    fail("Console request timeout wrapper is recursive or disconnected")

if 'action=route-data' not in js or 'route-data' not in api:
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
if 'action=update-data' not in js or 'update-data' not in api:
    fail("Update Engine action availability endpoint is not bound")
if 'action=settings-data' not in js or 'settings-data' not in api:
    fail("unified settings registry endpoint is not bound")
for marker in ("settingsCatalog", "settingsCatalogPill"):
    if f'id="{marker}"' not in html:
        fail(f"нет элемента единого каталога настроек: {marker}")
if 'state_action_not_allowed' not in api or 'rollback_unavailable' not in api or 'recovery_not_required' not in api:
    fail("Update Engine server-side state preconditions are incomplete")
if "count='+encodeURIComponent(prefs.logCount)" not in js:
    fail("bounded log tail preference is not bound")

for marker in ("adsPrivacyPanel", "adsEnabled", "adsSettingsSave", "adsRunNow", "adsPublishNow", "adsHttpsPanel", "adsSourcesPanel", "adsProbeBtn", "adsRuleAllow"):
    if f'id="{marker}"' not in html:
        fail(f"нет Ads & Privacy Guard элемента: {marker}")
for action in ("ads-data", "ads-https-data", "ads-settings", "ads-control", "ads-https-control"):
    if action not in api:
        fail(f"нет Ads & Privacy Guard API action: {action}")
if "bindAdsPrivacyGuard()" not in js or "action=ads-data" not in js:
    fail("Ads & Privacy Guard UI не связан с active Console JavaScript")
for marker in ("adsUpdateDirty", "adsSnapshot", "adsDirty"):
    if marker not in js:
        fail(f"нет Ads dirty-state marker: {marker}")
if "button.textContent=label" in js or "button.id==='adsSettingsSave'" not in js:
    fail("Ads busy-state ломает иконку или состояние кнопки сохранения")
if "Будущие возможности" in html or "ROADMAP" in html:
    fail("в active Console остался недействующий roadmap-блок")
if 'class="vward-group-icon" data-icon="shield"' not in html:
    fail("группы Ads не используют единые SVG-иконки")


for marker in ("logAll", "logReset", "tunnelSelect", "tunnelSelectedStats", "routeListSearch", "routeListSort"):
    if f'id="{marker}"' not in html:
        fail(f"нет финального элемента prompt-gap closure: {marker}")
for marker in ('data-dashboard-view="grid"', 'data-dashboard-view="list"', "syncDashboardView", "view:dashboardView"):
    if marker not in ui:
        fail(f"нет настройки вида карточек: {marker}")
if '<option value="group">FQDN-группа</option>' not in html or 'group_not_found' not in api:
    fail("FQDN group probe is incomplete")
if 'Runtime сейчас не хранит отдельную достоверную state-machine очереди' not in html:
    fail("Route Engine lifecycle limitation is not disclosed")

tcpdump_counter = re.search(r'^TCPDUMP_COUNT=.*$', api, re.MULTILINE)
if not tcpdump_counter:
    fail("Console API tcpdump counter is missing")
tcpdump_counter_source = tcpdump_counter.group(0)
if 'udp dst port 53' in tcpdump_counter_source:
    fail("Console API tcpdump counter depends on the truncated ps command tail")
for marker in ('-v subnet="$VWARD_LAN_SUBNET"', '-v address="$VWARD_LAN_ADDRESS"', 'src net " subnet', 'dst host " address'):
    if marker not in tcpdump_counter_source:
        fail(f"Console API tcpdump counter is missing stable marker: {marker}")

node = shutil.which("node")
if node:
    result = subprocess.run([node, "--check", root / "web/assets/vward-console.js"], capture_output=True, text=True)
    if result.returncode != 0:
        fail("Console JavaScript syntax: " + (result.stderr.strip() or result.stdout.strip()))

for name in ("overview", "settings", "logs"):
    desktop = len(re.findall(rf'<button[^>]+data-section="{name}"', html))
    if desktop < 1:
        fail(f"раздел {name} недоступен из навигации")

if not re.search(r'<nav class="mobile"[^>]*>.*data-section="settings"', html):
    fail("настройки недоступны из мобильной навигации")

print("CONSOLE_BINDINGS=PASS")
