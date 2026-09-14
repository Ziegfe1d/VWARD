#!/usr/bin/env python3
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
html = (ROOT / "web/index.html").read_text(encoding="utf-8")
js = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")
css = (ROOT / "web/assets/vward-console.css").read_text(encoding="utf-8")

assert "const ICON_PATHS=" in js
assert "function iconSvg(" in js and "function hydrateIcons(" in js
for obsolete in ("symbolIcons", "function svgIcon(", "function actionIcon("):
    assert obsolete not in js, obsolete
for glyph in ("⌂", "↻", "⌁", "◇", "⇄", "◷", "▣", "▱", "≡", "◐", "⚙"):
    assert glyph not in html + js, glyph

declared = set(re.findall(r"([A-Za-z][A-Za-z0-9]*):'", js.split("function iconSvg", 1)[0]))
declared.update(re.findall(r"ICON_PATHS\.([A-Za-z][A-Za-z0-9]*)=", js))
used = set(re.findall(r'data-icon="([A-Za-z][A-Za-z0-9]*)"', html))
used.update(re.findall(r"'([A-Za-z][A-Za-z0-9]*)'", js.split("const CONTROL_ICONS=", 1)[1].split(";", 1)[0]))
assert used <= declared, f"icons used without canonical path: {sorted(used - declared)}"

for marker in (
    "/* Canonical icon and typography system - dev.8 */",
    "--font-ui:",
    "--icon-sm:",
    ".icon-only",
    ".mobile button.has-icon",
    ".catalog-group>summary:before{content:\"\"",
):
    assert marker in css, marker

assert html.count('viewBox="0 0 24 24"') == 0, "static one-off SVG bypasses canonical registry"
print("CONSOLE_ICON_SYSTEM=PASS")
