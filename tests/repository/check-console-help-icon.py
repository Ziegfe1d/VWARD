#!/usr/bin/env python3
"""«?» next to its title (owner 2026-11-01, Keenetic «Диагностика (?)»): a block's «?» follows its
h2; a page's own block puts its «?» into the page title at the top, never alone apart from it;
the explanation opens by click or keyboard and the same «?» keeps the focus."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text()
CSS = (ROOT / "web/assets/vward-console.css").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_HELP_ICON=FAIL: {message}")


panel = JS[JS.index("function panel(title, body, opts) {"):JS.index("\n}\n", JS.index("function panel(title, body, opts) {"))]
if "if (same && longDesc) PAGEQ = { k: dq, title: title };" not in panel:
    fail("a page's own block must hand its «?» to the page title")
if "(longDesc && !folded && !same ? qBtn(dq, title) : '')" not in panel:
    fail("a block's «?» must follow its own title only")
if "const head = same && !extra ? ''" not in panel:
    fail("no title-less head holding a lone «?»")
if "$('pageTitle').innerHTML = '<span class=\"page-title-text\">' + esc(p.title) + '</span>' + (PAGEQ ? qBtn(PAGEQ.k, PAGEQ.title) : '');" not in JS:
    fail("the page title must carry the page's «?»")
if "PAGEQ = null;" not in JS[JS.index("function render() {"):JS.index("function render() {") + 200]:
    fail("PAGEQ must be reset on every render")
if "again.focus()" not in JS:
    fail("the «?» must keep the keyboard focus after it opens or closes")
qb = JS[JS.index("const qBtn = "):JS.index("\n", JS.index("const qBtn = "))]
if '<button class="q-btn" type="button"' not in qb or "aria-expanded" not in qb or "aria-label=\"Пояснение: " not in qb:
    fail("«?» must be a real button with aria-expanded and a label")
for rule in (".block-head h2+.q-btn{margin-left:-4px}", ".topbar-title h1{margin:0;font-size:var(--fs-lg);font-weight:650;line-height:1.2;display:flex;align-items:center;gap:2px;min-width:0}",
             ".topbar-title .page-title-text{overflow:hidden;"):
    if rule not in CSS:
        fail(f"CSS: {rule}")
print("CONSOLE_HELP_ICON=PASS")
