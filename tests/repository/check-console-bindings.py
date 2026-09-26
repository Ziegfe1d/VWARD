#!/usr/bin/env python3
"""Console contract: every control is wired, every link resolves, every API call is allowed."""

import json
import re
import shutil
import subprocess
from pathlib import Path


root = Path(__file__).resolve().parents[2]
html = (root / "web/index.html").read_text(encoding="utf-8")
js = (root / "web/assets/vward-console.js").read_text(encoding="utf-8")
api = (root / "web/cgi-bin/api.cgi").read_text(encoding="utf-8")
registry = json.loads((root / "config/components/component-registry.json").read_text(encoding="utf-8"))


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


# Shell markup: stable anchors only, no inline code or styles (CSP: script-src/style-src 'self').
for marker in ("pageTitle", "content", "tabbar", "layer", "toasts", "backBtn", "searchBtn", "bellBtn", "themeBtn"):
    if f'id="{marker}"' not in html:
        fail(f"нет элемента каркаса Console: {marker}")
html_ids = re.findall(r'\bid="([^"]+)"', html)
if len(html_ids) != len(set(html_ids)):
    fail("повторяющиеся id в index.html")
if re.search(r"\son[a-z]+=", html) or "style=" in html or "<style" in html or re.search(r"<script>(?!</script>)", html):
    fail("index.html содержит встроенные обработчики, стили или скрипты")
if 'style="' in js or "style=\\\"" in js:
    fail("JavaScript строит разметку со встроенными стилями - CSP их заблокирует")

node = shutil.which("node")
if node:
    result = subprocess.run([node, "--check", root / "web/assets/vward-console.js"], capture_output=True, text=True)
    if result.returncode != 0:
        fail("синтаксис JavaScript: " + (result.stderr.strip() or result.stdout.strip()))
if re.search(r"\?\.|\?\?", js):
    fail("optional chaining / nullish coalescing не поддерживаются старыми WebView")

# Actions: every button has a handler and every handler has a button.
produced = set(re.findall(r"data-act=\"([a-z-]+)\"", js)) | set(re.findall(r"btn\('([a-z-]+)'", js))
handled = set(re.findall(r"a === '([a-z-]+)'", js))
if produced - handled:
    fail("кнопки без обработчика: " + ", ".join(sorted(produced - handled)))
if handled - produced:
    fail("обработчики без кнопок: " + ", ".join(sorted(handled - produced)))
confirms = set(re.findall(r"data-confirm=\"([a-z-]+)\"", js))
confirmed = set(re.findall(r"^\s+'([a-z-]+)': (?:\(\)|c) =>", js, re.MULTILINE))
if confirms - confirmed:
    fail("подтверждения без действия: " + ", ".join(sorted(confirms - confirmed)))
forms = set(re.findall(r'data-form="([a-z-]+)"', js))
form_handlers = set(re.findall(r"f === '([a-z-]+)'", js))
if forms - form_handlers:
    fail("формы без обработчика: " + ", ".join(sorted(forms - form_handlers)))

# Every action the Console sends by POST is one the API accepts by POST.
api_src = api
post_ok = set(re.search(r'case "\$ACTION" in\n\s+(settings\|control[^)]*)\) ;;', api_src).group(1).split("|"))
posted = set(re.findall(r"apiPost\('([a-z-]+)'", js)) | set(re.findall(r"runLong\('[a-z-]+', '([a-z-]+)'", js)) | set(re.findall(r"runAction\('[a-z-]+', '([a-z-]+)'", js))
if posted - post_ok:
    fail("POST-действия, которые API отклонит: " + ", ".join(sorted(posted - post_ok)))

# Navigation: every page and detail page has a renderer, every static link resolves.
pages = set(re.findall(r"\{ id: '([a-z]+)', title: '[^']+', icon: '[a-z]+', group:", js))
if len(pages) != 11:
    fail(f"ожидалось 11 разделов, найдено {len(pages)}")
details = set(re.findall(r"^  '?([a-z][a-z-]*)'?: \{ title:", js, re.MULTILINE))
renderers = set(re.findall(r"^  ([a-z]+)\(\) \{", js, re.MULTILINE)) | set(re.findall(r"^  '([du]-[a-z-]+)'\(\) \{", js, re.MULTILINE))
if (pages | details) - renderers:
    fail("разделы без отрисовки: " + ", ".join(sorted((pages | details) - renderers)))
targets = set(re.findall(r"data-go=\"([a-z][a-z-]*)\"", js)) | set(re.findall(r"'(d-[a-z-]+|u-[a-z-]+|c-[a-z-]+)'\]", js))
targets |= {m for m in re.findall(r"\['[^']+', [^\]]*?'([a-z][a-z-]+)'(?:, '[^']*')?\]", js) if m in pages or m in details}
components = set(re.findall(r"\{ id: '([a-z-]+)', name: '", js))
unknown = {t for t in targets if t not in pages and t not in details and not (t.startswith("c-") and t[2:] in components)}
if unknown:
    fail("переходы на несуществующие страницы: " + ", ".join(sorted(unknown)))

# Components: the Console lists exactly the registry.
registry_ids = {c["id"] for c in registry["components"]}
if components != registry_ids:
    fail("компоненты Console не совпадают с реестром: " + ", ".join(sorted(components ^ registry_ids)))

# Search index points at rows that exist.
row_keys = set(re.findall(r"\[\s*'([^']+)',", js)) | set(re.findall(r"ctrlRow\('([^']+)'", js)) | set(re.findall(r'data-key="([^"]+)"', js))
for page_id, key in re.findall(r"\['([a-z][a-z-]*)', '([^']+)'\]", js.split("const SEARCH_INDEX = [", 1)[1].split("];", 1)[0]):
    if (page_id not in pages and page_id not in details) or key not in row_keys:
        fail(f"запись поиска без строки: {page_id}:{key}")

# API: every call is an allowed action; POST only for mutation actions; confirmation tokens exist server-side.
api_actions = set(re.search(r'case "\$ACTION" in\s*\n\s*([^)]+)\)', api).group(1).split("|"))
post_actions = set(re.search(r'case "\$ACTION" in\s*\n\s*(settings\|control[^)]+)\)', api).group(1).split("|"))
gets = set(re.findall(r"apiGet\('([a-z-]+)'", js)) | set(re.findall(r"apiText\('([a-z-]+)'", js))
posts = set(re.findall(r"(?:apiPost|runAction)\((?:'[a-z-]+', )?'([a-z-]+)'", js))
if gets - api_actions:
    fail("GET-действия вне allowlist API: " + ", ".join(sorted(gets - api_actions)))
if posts - post_actions:
    fail("POST-действия вне allowlist API: " + ", ".join(sorted(posts - post_actions)))
for token in set(re.findall(r"confirm: '([A-Z_0-9]+)'", js)) | set(re.findall(r"'(WIFI_[A-Z0-9_]+)'", js)):
    if token not in api:
        fail(f"токен подтверждения неизвестен API: {token}")
if "'X-VWARD-Request': 'console'" not in js or "application/x-www-form-urlencoded" not in js:
    fail("POST-запросы без заголовка защиты от подделки")

# Journals: every tab is in the server-side allowlist.
log_tabs = set(re.findall(r"\{ id: '([a-z]+)', label: '", js))
api_logs = set(re.findall(r"^\s{8}([a-z]+)\)\s*$", api, re.MULTILINE))
if log_tabs - api_logs:
    fail("вкладки журналов вне allowlist API: " + ", ".join(sorted(log_tabs - api_logs)))

# Server-side guarantees that the Console relies on.
if "action=exec" in api or "action=file" in api or "action=ndmc" in api:
    fail("обнаружен запрещённый generic control API")
for token in ("ROUTE_RECONCILE", "POLICY_REFRESH", "POLICY_RECONCILE", "APPLY_UPDATE", "ROLLBACK_UPDATE", "RECOVER_UPDATE", "ADS_PUBLISH", "HTTPS_START"):
    if token not in api:
        fail(f"нет server-side confirmation token: {token}")
if "state_action_not_allowed" not in api or "rollback_unavailable" not in api or "recovery_not_required" not in api:
    fail("Update Engine server-side state preconditions are incomplete")
tcpdump_counter = re.search(r"^TCPDUMP_COUNT=.*$", api, re.MULTILINE)
if not tcpdump_counter or "udp dst port 53" in tcpdump_counter.group(0):
    fail("Console API tcpdump counter is missing or depends on the truncated ps command tail")

# Texts that describe a component's timing must match the component.
guard = (root / "components/tunnel-guard/scripts/vward-tunnel-guard.sh").read_text(encoding="utf-8")
if "RECOVERY_INTERVAL=300" not in guard or "['Попытка восстановления', 'каждые 5 минут'" not in js:
    fail("VPN recovery interval shown in the Console differs from vward-tunnel-guard.sh")

print("CONSOLE_BINDINGS=PASS")
