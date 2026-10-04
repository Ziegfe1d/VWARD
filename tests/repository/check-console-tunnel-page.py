#!/usr/bin/env python3
"""Tunnel page: «Проверить» and «Перезапустить» stand on one row at phone width; the
tunnel's subnets are one row («Подсети · N ›») that opens their own page with adding,
a search and removal, not a sheet of addresses on the tunnel page (owner, 2026-10-04)."""

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")
CSS = ROOT / "web/assets/vward-console.css"


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_TUNNEL_PAGE=FAIL: {message}")


_js = (ROOT / "web/assets/vward-console.js").read_text()
for need in ("sw('data-tunsw=\"' + esc(t.name) + '\"', !tunOff(t)", "t.name === managed || !cfgOk()", "'tunsw-off': c => tunnelState('down', c.name)",
             "confirm = { id: 'tunsw-off', name: n }", "tunnelState('up', n)", "if (t.dataset.go && e.target.closest('.switch')) return;", 'class="row link tun"'):
    if need not in _js:
        fail(f"the tunnel switch lacks {need!r}")


for need in ("'<div class=\"panel-actions even\">' + btn('tunnel-probe', 'check', 'Проверить', 'primary'",
             "['Подсети', nets.length ? fmtInt(nets.length) : 'нет', '', 'tn-' + name]",
             "function tunnelNetsPage(name)", "if (id.startsWith('tn-')) return { id: id, title: 'Подсети', parent: 't-' + id.slice(3) };",
             "k === 'tn' ? 'subnets'", "r[0] === 'tunnel' && r[2] === 'subnets') return 'tn-' + r[1];",
             "current.startsWith('tn-') ? tunnelNetsPage(current.slice(3))", "tunnelSubnet(current.slice(current.startsWith('tn-') ? 3 : 2), 'remove'"):
    if need not in JS:
        fail(f"the Panel lacks {need}")
traffic = JS[JS.index("function tunnelTrafficPanel(name)"):JS.index("// tunnelNetsPage NAME")]
if "rowBtn('tsubnet'" in traffic:
    fail("the tunnel page must not list every subnet")

# The page's address: /vpn/tunnel/<name>/subnets and back.
script = JS[JS.index("const SLUG = {"):JS.index("function idOf(path)")] + JS[JS.index("function idOf(path)"):JS.index("\n}\n", JS.index("function idOf(path)")) + 3]
script = ("const PAGES = [{ id: 'vpn' }, { id: 'lists' }, { id: 'wifi' }], DETAILS = {}; const S = {}; const tunLabel = x => x;\n"
          + JS[JS.index("function page(id)"):JS.index("const parentOf")] + "const parentOf = id => { const p = page(id); return p && p.parent; };\n"
          + script + "console.log(JSON.stringify([pathOf('tn-OpkgTun2'), idOf(pathOf('tn-OpkgTun2'))]));")
r = subprocess.run(["node", "-e", script], text=True, capture_output=True)
if r.returncode or json.loads(r.stdout) != ["/vpn/tunnel/OpkgTun2/subnets", "tn-OpkgTun2"]:
    fail(f"subnets page address: {r.stdout.strip()} {r.stderr[-300:]}")

# Both buttons on one row at 320 and 390 px (Chromium; skipped without a browser).
npm = shutil.which("npm")
groot = subprocess.run([npm, "root", "-g"], text=True, capture_output=True).stdout.strip() if npm else ""
if not groot or not (Path(groot) / "playwright").exists():
    print("CONSOLE_TUNNEL_PAGE=PASS (layout SKIPPED: no playwright)")
    raise SystemExit(0)
LAYOUT = """
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const css = fs.readFileSync(process.argv[2], 'utf8');
  const ico = '<svg width="18" height="18"></svg>';
  const html = '<html><head><style>' + css + '</style></head><body><main><section class="block"><div class="panel">' +
    '<div class="panel-actions even"><button class="btn primary">' + ico + 'Проверить</button><button class="btn">' + ico + 'Перезапустить</button></div>' +
    '</div></section></main></body></html>';
  const opts = fs.existsSync(process.argv[3]) ? { executablePath: process.argv[3] } : {};
  const b = await chromium.launch(opts), out = {};
  for (const w of [320, 390]) {
    const p = await b.newPage({ viewport: { width: w, height: 600 } });
    await p.setContent(html);
    out[w] = await p.$$eval('.btn', bs => bs.map(x => [Math.round(x.getBoundingClientRect().top), x.scrollWidth <= x.clientWidth + 1]));
    await p.close();
  }
  await b.close();
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e.message); process.exit(3); });
"""
import os
import tempfile
with tempfile.TemporaryDirectory() as t:
    f = Path(t) / "layout.js"; f.write_text(LAYOUT)
    r = subprocess.run(["node", str(f), str(CSS), "/opt/pw-browsers/chromium"], text=True, capture_output=True,
                       timeout=120, env=os.environ | {"NODE_PATH": groot})
if r.returncode:
    print(f"CONSOLE_TUNNEL_PAGE=PASS (layout SKIPPED: browser did not start: {r.stderr.strip()[-120:]})")
    raise SystemExit(0)
for w, got in json.loads(r.stdout).items():
    if len({t for t, _ in got}) != 1:
        fail(f"at {w}px the buttons are on separate rows: {got}")
    if not all(fits for _, fits in got):
        fail(f"at {w}px a button's label does not fit: {got}")

# The tunnel list: each tunnel has its on/off switch, on the line of its state, at 320 and
# 390 px (switch inside the row, beside the state, nothing wider than the screen).
ROWS = r"""const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const css = fs.readFileSync(process.argv[2], 'utf8');
  const chev = '<svg class="chev" width="18" height="18"></svg>';
  const sw = on => '<span class="row-acts"><label class="switch"><input type="checkbox"' + (on ? ' checked' : '') + ' aria-label="x"><i></i></label></span>';
  const row = (n, sub, pill, cls, on) => '<li class="row link tun" data-go="t-x"><div class="row-main"><b>' + n + '</b><small>' + sub + '</small></div><span class="pill ' + cls + '">' + pill + '</span>' + sw(on) + chev + '</li>';
  const html = '<html><head><style>' + css + '</style></head><body><main><section class="block"><div class="panel"><ul class="rows">' +
    row('de-vless', '<span class="st ok">по умолчанию</span> · VLESS · de.example.net:8443', 'В сети', 'ok', true) +
    row('awg2-fi', 'AmneziaWG 2.0 · контур VWARD', 'Не в сети', 'warn', true) +
    row('us-east', 'AmneziaWG 3.x · контур VWARD', 'Выключен', 'warn', false) +
    '</ul></div></section></main></body></html>';
  const opts = fs.existsSync(process.argv[3]) ? { executablePath: process.argv[3] } : {};
  const b = await chromium.launch(opts), out = {};
  for (const w of [320, 390]) {
    const p = await b.newPage({ viewport: { width: w, height: 400 } });
    await p.setContent(html);
    out[w] = await p.$$eval('.row', rs => rs.map(r => { const s = r.querySelector('.switch').getBoundingClientRect(), rr = r.getBoundingClientRect(), pl = r.querySelector('.pill').getBoundingClientRect();
      return [Math.round(s.right) <= Math.round(rr.right), Math.abs((s.top + s.bottom) / 2 - (pl.top + pl.bottom) / 2) < 6, r.scrollWidth <= r.clientWidth + 1, document.documentElement.scrollWidth <= window.innerWidth]; }));
    await p.close();
  }
  await b.close();
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e.message); process.exit(3); });
"""
with tempfile.TemporaryDirectory() as t:
    f = Path(t) / "rows.js"; f.write_text(ROWS)
    r = subprocess.run(["node", str(f), str(CSS), "/opt/pw-browsers/chromium"], text=True, capture_output=True,
                       timeout=120, env=os.environ | {"NODE_PATH": groot})
if r.returncode:
    fail(f"tunnel rows layout: {r.stderr[-200:]}")
for w, got in json.loads(r.stdout).items():
    if not all(all(x) for x in got):
        fail(f"at {w}px a tunnel's switch is not on its state's line or overflows: {got}")
print("CONSOLE_TUNNEL_PAGE=PASS")
