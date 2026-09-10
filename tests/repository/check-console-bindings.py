#!/usr/bin/env python3

import re
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

for name in ("overview", "settings", "logs"):
    desktop = len(re.findall(rf'<button[^>]+data-section="{name}"', html))
    if desktop < 1:
        fail(f"раздел {name} недоступен из навигации")

if not re.search(r'<nav class="mobile"[^>]*>.*data-section="settings"', html):
    fail("настройки недоступны из мобильной навигации")

print("CONSOLE_BINDINGS=PASS")
