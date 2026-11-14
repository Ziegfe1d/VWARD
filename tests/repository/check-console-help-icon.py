#!/usr/bin/env python3
"""«?» next to its title (owner 2026-11-01, Keenetic «Диагностика (?)»): a block's «?» follows its
h2; the explanation opens by click or keyboard and the same «?» keeps the focus.
Owner 2026-11-02: no «?» in the top bar on ANY page (back, title, search, bell, theme only); the
page's own block shows its explanation in place instead (the texts are kept).
Owner 13.11.2026: the «?» right after the last word, wrapping with it (rows and blocks alike), never
apart at the edge when the title wraps or the block folds."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text()
CSS = (ROOT / "web/assets/vward-console.css").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_HELP_ICON=FAIL: {message}")


panel = JS[JS.index("function panel(title, body, opts) {"):JS.index("\n}\n", JS.index("function panel(title, body, opts) {"))]
if "(opts.desc && (!longDesc || same || qOpen(dq))" not in panel:
    fail("a page's own block must show its explanation in place (its «?» left the top bar)")
if "'<span>' + qGlue(title, longDesc && !folded ? qBtn(dq, title) : '') + '</span></h2>'" not in panel:
    fail("RED: a block's «?» must sit in its title, right after the last word")
dt = JS[JS.index("function dtHtml(key, hint) {"):JS.index("\n}\n", JS.index("function dtHtml(key, hint) {"))]
if "qGlue(key, qBtn('r:' + key, key))" not in dt:
    fail("RED: a row's «?» must follow its last word")
glue = JS[JS.index("function qGlue(text, q) {"):JS.index("\n}\n", JS.index("function qGlue(text, q) {"))]
if "'<span class=\"q-glue\">' + esc(t.slice(i + 1)) + q + '</span>'" not in glue:
    fail("the last word and its «?» wrap together")
if "const head = same && !extra ? ''" not in panel:
    fail("no title-less head holding a lone «?»")
if "$('pageTitle').innerHTML = '<span class=\"page-title-text\">' + esc(p.title) + '</span>';" not in JS or "qBtn(PAGEQ" in JS:
    fail("RED: no «?» in the top bar on any page (owner 02.11)")
if "PAGEQ = null;" not in JS[JS.index("function render() {"):JS.index("function render() {") + 200]:
    fail("PAGEQ must be reset on every render")
if "again.focus()" not in JS:
    fail("the «?» must keep the keyboard focus after it opens or closes")
qb = JS[JS.index("const qBtn = "):JS.index("\n", JS.index("const qBtn = "))]
if '<button class="q-btn" type="button"' not in qb or "aria-expanded" not in qb or "aria-label=\"Пояснение: " not in qb:
    fail("«?» must be a real button with aria-expanded and a label")
for rule in (".block-head h2 .q-btn{margin-left:2px}", ".dt-t{display:inline}", ".q-glue{white-space:nowrap}", ".topbar-title h1{margin:0;font-size:var(--fs-lg);font-weight:650;line-height:1.2;display:flex;align-items:center;gap:2px;min-width:0}",
             ".topbar-title .page-title-text{overflow:hidden;"):
    if rule not in CSS:
        fail(f"CSS: {rule}")
print("CONSOLE_HELP_ICON=PASS")
