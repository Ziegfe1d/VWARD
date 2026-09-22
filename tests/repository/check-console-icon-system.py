#!/usr/bin/env python3
"""Console icons: one registry, one grid, one stroke width, no emoji or one-off SVG."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
html = (ROOT / "web/index.html").read_text(encoding="utf-8")
js = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")
css = (ROOT / "web/assets/vward-console.css").read_text(encoding="utf-8")

assert "const ICON_PATHS = {" in js and "function iconSvg(" in js, "canonical icon registry missing"
declared = set(re.findall(r"^  ([A-Za-z][A-Za-z0-9]*): '", js.split("const ICON_PATHS = {", 1)[1].split("};", 1)[0], re.M))
used = set(re.findall(r"ico\('([A-Za-z][A-Za-z0-9]*)'", js)) | set(re.findall(r"icon: '([A-Za-z][A-Za-z0-9]*)'", js))
used |= set(re.findall(r"btn\('[a-z-]+', '([A-Za-z][A-Za-z0-9]*)'", js))
missing = sorted(used - declared)
assert not missing, "icons used but not declared: " + ", ".join(missing)
assert js.count('viewBox="0 0 24 24"') == 1, "icons must be built only by iconSvg"
assert 'viewBox=' not in html, "static one-off SVG bypasses the icon registry"
for glyph in ("↗", "⚙", "🔄", "✓", "✕", "☀", "🌙"):
    assert glyph not in html + js, f"text glyph used instead of an icon: {glyph}"
assert ".icon{width:20px;height:20px;flex:none;fill:none;stroke:currentColor;stroke-width:1.75;stroke-linecap:round;stroke-linejoin:round}" in css, "single icon stroke style missing"
print("CONSOLE_ICON_SYSTEM=PASS")
