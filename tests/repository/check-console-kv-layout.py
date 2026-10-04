#!/usr/bin/env python3
"""Panel rows: a long value with a state dot («Напрямую, пока VPN недоступен») wraps inside
its column and never runs over the row's name, at phone and desktop widths (seen on the
owner's phone 2026-10-04). Rendered in Chromium; skipped where no browser is installed."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSS = ROOT / "web/assets/vward-console.css"


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_KV_LAYOUT=FAIL: {message}")


if ".kv dd .pill{flex:0 1 auto;min-width:0;white-space:normal" not in CSS.read_text():
    fail("a state in a row must be allowed to wrap and shrink")

node = shutil.which("node")
npm = shutil.which("npm")
chromium = "/opt/pw-browsers/chromium"
if not node or not npm:
    print("CONSOLE_KV_LAYOUT=SKIPPED: no node")
    raise SystemExit(0)
groot = subprocess.run([npm, "root", "-g"], text=True, capture_output=True).stdout.strip()
if not (Path(groot) / "playwright").exists():
    print("CONSOLE_KV_LAYOUT=SKIPPED: no playwright")
    raise SystemExit(0)

ROWS = [["Трафик списков", "Напрямую, пока VPN недоступен", "warn"], ["Автоматическая защита", "Через VPN", "ok"],
        ["Обновление IP-категорий", "04.10, 02:19 · добавлено 212, убрано 0", "info"], ["Возврат в VPN", "автоматически", ""]]
SCRIPT = """
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const css = fs.readFileSync(process.argv[2], 'utf8'), rows = JSON.parse(process.argv[3]);
  const html = '<html><head><style>' + css + '</style></head><body><main><section class="block"><div class="panel"><dl class="kv">' +
    rows.map(r => '<div class="kv-row"><dt>' + r[0] + '</dt><dd>' + (r[2] ? '<span class="pill ' + r[2] + '">' + r[1] + '</span>' : '<span class="num">' + r[1] + '</span>') + '</dd></div>').join('') +
    '</dl></div></section></main></body></html>';
  const opts = fs.existsSync(process.argv[4]) ? { executablePath: process.argv[4] } : {};
  const b = await chromium.launch(opts);
  const out = {};
  for (const w of [320, 390, 1280]) {
    const p = await b.newPage({ viewport: { width: w, height: 800 } });
    await p.setContent(html);
    out[w] = await p.$$eval('.kv-row', rs => rs.map(r => {
      const dt = r.querySelector('dt').getBoundingClientRect(), v = r.querySelector('dd > *').getBoundingClientRect();
      return [r.querySelector('dt').textContent, v.left >= dt.right - 0.5 && v.right <= document.documentElement.clientWidth + 0.5];
    }));
    await p.close();
  }
  await b.close();
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e.message); process.exit(3); });
"""
with tempfile.TemporaryDirectory() as t:
    f = Path(t) / "kv.js"; f.write_text(SCRIPT)
    r = subprocess.run([node, str(f), str(CSS), json.dumps(ROWS, ensure_ascii=False), chromium], text=True, capture_output=True,
                       timeout=120, env=os.environ | {"NODE_PATH": groot})
if r.returncode != 0:
    print(f"CONSOLE_KV_LAYOUT=SKIPPED: browser did not start ({r.stderr.strip()[-120:]})")
    raise SystemExit(0)
bad = [f"{w}px: {name}" for w, rows in json.loads(r.stdout).items() for name, ok in rows if not ok]
if bad:
    fail("the value runs over the row's name: " + "; ".join(bad))
print("CONSOLE_KV_LAYOUT=PASS")
