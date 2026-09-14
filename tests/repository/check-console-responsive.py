#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
css = (ROOT / "web/assets/vward-console.css").read_text(encoding="utf-8")
js = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")
html = (ROOT / "web/index.html").read_text(encoding="utf-8")

required_css = (
    "/* Dashboard and settings hierarchy — dev.7 */",
    "--mobile-nav-h:86px",
    "env(safe-area-inset-bottom)",
    ".wide.chart-empty",
    "grid-template-columns:repeat(7,minmax(0,1fr))",
    "min-height:35dvh",
    "@media(max-width:359px)",
    "/* Final visual polish - dev.8 */",
    "bottom:calc(var(--mobile-nav-h) + env(safe-area-inset-bottom) + 18px)",
    ".btn.has-icon .icon",
    ".vward-group-icon svg",
)
for marker in required_css:
    assert marker in css, marker

assert "classList.toggle('chart-empty',a.length<2)" in js
assert "График появится после второго замера" in js
assert "wanActionText" in js
assert "vward-dashboard" in js
assert "dashboardOrder" in js and "dashboardHidden" in js
assert "dashboardView='grid'" in js and "view:dashboardView" in js
assert "[data-dashboard-view]" in js
assert "draggable=" in js and "ondrop=" in js
assert "storage-bar" in js and "storageBar" in js
assert "data-chart=\"'+d[0]" not in js
assert "<details class=\"catalog-group\">" in js
for marker in ("dashboardEdit", "dashboardEditor", "dashboardList", "dashboardReset"):
    assert f'id="{marker}"' in html
assert 'data-dashboard-view="grid"' in html
assert 'data-dashboard-view="list"' in html
assert 'data-section="updater" data-icon="refresh">Обновления</button>' in html
assert 'data-section="settings" data-icon="settings">Настройки</button>' in html
assert "style=" not in html
assert "onclick=" not in html
assert "overflow-x:hidden" in css
assert "grid-template-columns:repeat(2,minmax(0,1fr))" in css
assert ".cards[data-view=list]" in css
assert "@media(max-width:359px){.card{min-height:174px}" in css

print("CONSOLE_RESPONSIVE=PASS")
