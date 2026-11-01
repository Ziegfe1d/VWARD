#!/usr/bin/env python3
"""ads-ui (owner 2026-11-01): «Реклама и трекеры» - «Проверка VWARD», «Списки и правила», «Проверка
блокировки», AdGuard Home last; waiting is not green; 191 of 38 232 is «≈ 0,5 %», not «0%»."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_ADS_UI=FAIL: {message}")


page = JS[JS.index("  ads() {"):]
page = page[:page.index("\n  },\n")]
ret = page[page.index("return loadError(['ads'])"):]
order = [ret.index(x) for x in ("panel('Проверка VWARD'", "panel('Списки и правила'", "adsCheckPanel()", "aghTopPanel()")]
if order != sorted(order):
    fail(f"blocks out of order: {order}")
if "Math.round(100 * st1.blocked / st1.queries)" in JS:
    fail("the blocked share is rounded to whole percent")
if not shutil.which("node"):
    print("CONSOLE_ADS_UI=PASS (node not found: texts not run)")
    sys.exit(0)


def grab(start, end="\n}\n"):
    i = JS.index(start)
    return JS[i:JS.index(end, i) + len(end)]


code = grab("function blockedShare(") + grab("function adsNow(")
harness = """
const S = { ads: {}, cached: {} }; const num = v => v == null ? null : Number(v); const fmtInt = n => String(n);
const plural = (n, a, b, c) => n === 1 ? a : n < 5 ? b : c; const jobText = j => 'Проверка';
""" + code + """
const now = new Date(Date.now() - 3600e3).toISOString().slice(0, 19).replace('T', ' ');
const old = new Date(Date.now() - 3 * 86400e3).toISOString().slice(0, 19).replace('T', ' ');
const A = { agh_connected: true }, st = (a, j, sc, off, mode) => adsNow(Object.assign({}, A, a), {}, j || {}, sc || {}, !!off, mode || 'scheduled').slice(0, 2).join('|');
const out = {
  share: [blockedShare(191, 38232), blockedShare(0, 100), blockedShare(5, 0), blockedShare(1, 5000), blockedShare(1, 2000), blockedShare(3000, 10000), blockedShare(12, 100)],
  waitNoRun: st({}, {}, {}), waitOld: st({}, {}, { last_run: old }), fresh: st({}, {}, { last_run: now }),
  paused: st({ paused: true }), off: st({}, {}, {}, true), noAgh: st({ agh_connected: false }),
  failed: st({}, { last: { type: 'scan', state: 'FAILED' } }, { last_run: now }),
  busy: st({}, { current: { state: 'RUNNING', type: 'scan' } })
};
S.cached = { ads: Date.now() }; out.cached = st({}, {}, { last_run: now });
S.cached = {}; S.ads = null; out.none = st({}, {}, { last_run: now });
console.log(JSON.stringify(out));
"""
r = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30)
if r.returncode:
    fail(r.stderr.strip()[-500:])
got = json.loads(r.stdout)
nb = " "
want = {
    "share": [f" · ≈ 0,5{nb}%", f" · 0{nb}%", "", f" · < 0,1{nb}%", f" · < 0,1{nb}%", f" · ≈ 30{nb}%", f" · ≈ 12{nb}%"],
    "waitNoRun": "|ожидает следующей проверки · проверок ещё не было", "waitOld": "|ожидает следующей проверки",
    "fresh": "ok|работает · ожидает следующей проверки", "paused": "warn|На паузе", "off": "warn|Компонент выключен",
    "noAgh": "warn|Нет подключения к AdGuard Home", "failed": "crit|последняя проверка с ошибкой", "busy": "info|выполняется: проверка",
    "cached": "|Нет данных", "none": "|Нет данных",
}
for k, v in want.items():
    if got.get(k) != v:
        fail(f"{k}: {got.get(k)!r} != {v!r}")
print("CONSOLE_ADS_UI=PASS")
