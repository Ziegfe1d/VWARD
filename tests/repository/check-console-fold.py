#!/usr/bin/env python3
"""Every block of the Panel folds to its title with the arrow on its right (or a tap on the
title), and stays folded in this browser; the page's main block and the address checks do not
fold, and a folded block keeps the state shown beside its title."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text()
CSS = (ROOT / "web/assets/vward-console.css").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_FOLD=FAIL: {message}")


a = JS.index("// Collapsed blocks, per page and title")
script = JS[JS.index("const esc ="):JS.index("\n", JS.index("const esc ="))] + "\n" + JS[a:JS.index("/* Строка:", a)] + r"""
const saved = {}; const store = { get: (k, d) => saved[k] || d, set: (k, v) => { saved[k] = JSON.parse(JSON.stringify(v)); } };
const ico = n => '<i>' + n + '</i>';
let current = 'vpn'; const page = id => ({ vpn: { title: 'VPN' } })[id];
""".replace("const FOLDED = store.get", "var FOLDED = store.get") + r"""
const out = {};
out.open = panel('Туннели', 'BODY', { desc: 'DESC', right: '<span class="head-pill">В сети</span>' });
foldToggle(foldKey('Туннели'));
out.folded = panel('Туннели', 'BODY', { desc: 'DESC', right: '<span class="head-pill">В сети</span>' });
out.saved = saved['vward-folded'];
out.main = panel('VPN', 'BODY');
out.fixed = panel('Проверка адреса', 'BODY', { fixed: true });
current = 'ads'; out.otherPage = panel('Туннели', 'BODY');
console.log(JSON.stringify(out));
"""
# FOLDED is read from store at load: define the store first.
script = script.replace("// Collapsed blocks", "const saved = {}; const store = { get: (k, d) => saved[k] || d, set: (k, v) => { saved[k] = JSON.parse(JSON.stringify(v)); } };\n// Collapsed blocks", 1)
script = script.replace("\nconst saved = {}; const store = { get: (k, d) => saved[k] || d, set: (k, v) => { saved[k] = JSON.parse(JSON.stringify(v)); } };\nconst ico", "\nconst ico", 1)
r = subprocess.run(["node", "-e", script], text=True, capture_output=True)
if r.returncode:
    fail(r.stderr[-600:])
o = json.loads(r.stdout)
if 'data-fold="vpn|Туннели"' not in o["open"] or 'aria-expanded="true"' not in o["open"] or "BODY" not in o["open"] or "DESC" not in o["open"]:
    fail(f"an open block: {o['open']}")
if "BODY" in o["folded"] or "DESC" in o["folded"] or 'class="block folded"' not in o["folded"] or "В сети" not in o["folded"] or 'aria-expanded="false"' not in o["folded"]:
    fail(f"a folded block keeps its title and state only: {o['folded']}")
if o["saved"] != {"vpn|Туннели": 1}:
    fail(f"the fold is kept per page and title: {o['saved']}")
if "block-toggle" in o["main"] or "block-toggle" in o["fixed"]:
    fail("the page's main block and the address checks do not fold")
if "folded" in o["otherPage"] or "BODY" not in o["otherPage"]:
    fail("a fold on one page does not fold a block of the same title on another")
if JS.count("{ fixed: true,") != 2:
    fail("both address checks stay open")
for need in ("const fold = e.target.closest('[data-fold]');", "foldToggle(fold.dataset.fold); render(); return;"):
    if need not in JS:
        fail(f"the click lacks {need}")
if ".block.folded .block-toggle .icon{transform:rotate(90deg)}" not in CSS or "@media (hover:hover){.block-toggle:hover" not in CSS:
    fail("the arrow turns, and no sticky hover on phones")
print("CONSOLE_FOLD=PASS")
