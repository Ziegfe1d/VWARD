#!/usr/bin/env python3
"""«Журналы» as cards (owner 02.11, display only): HH:MM:SS with the date once a day, one time format
for every journal, a level sign, words instead of internal codes (CONSOLE never shown), numbers
rounded with units, no «|», the autopick checks folded into one counter in «Важное» (warnings
and errors kept); copy/save/share still take the raw journal."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")


def fail(m):
    raise SystemExit(f"CONSOLE_LOG_FEED=FAIL: {m}")


if "copyText(S.logs[logTab] || '')" not in JS or "logFeed(text)" not in JS or 'data-act="log-view"' not in JS:
    fail("the feed, the «Важное/Все» switch and the raw copy")
if not shutil.which("node"):
    print("CONSOLE_LOG_FEED=PASS (node not found)"); sys.exit(0)
a = JS.index("function logTime"); e = JS.index("\n}\n", a) + 3
c = JS.index("/* The journals as cards (owner 02.11"); d = JS.index("\n}\n", JS.index("function logFeed(text) {")) + 3
h = ("const store={get:()=>null}; const esc=s=>String(s).replace(/</g,'&lt;'); const ico=n=>'{'+n+'}';"
     "const plural=(n,a,b,c)=>{n=Math.abs(n)%100;const m=n%10;return n>10&&n<20?c:m>1&&m<5?b:m===1?a:c;};\n" + JS[a:e] + JS[c:d] + """
const T = ['[Интернет] 2026-11-02T00:12:00+0300 class=HEALTHY',
 '[Автоподбор доменов] 2026-11-02 00:11:48|HINT_DIRECT_OK|chatgpt.com|200|1.256241',
 '[Автоподбор доменов] 2026-11-02 00:11:47|HINT_ADAPTIVE_CHECK|a.example',
 '[Панель VWARD] 2026-11-02T00:10:44+0300 CONSOLE_CONFIG list-domain add x',
 '[Автоподбор доменов] 2026-11-01 23:59:00|WATCHDOG_RESTART|reason=cores=2'].join('\\n');
console.log(JSON.stringify({imp: logFeed(T), all: (logImportant = false, logFeed(T))}));""")
r = subprocess.run(["node", "-e", h], capture_output=True, text=True, env=os.environ | {"TZ": "Europe/Moscow"})
if r.returncode:
    fail(r.stderr[-400:])
import json
o = json.loads(r.stdout)
imp, al = o["imp"], o["all"]
for need in ("<time>00:12:00</time>", "<time>00:10:44</time>", "Настройки Панели VWARD изменены", "1,26 с",
             "Автоподбор: 2 проверки", "Перезапуск после сбоя", 'log-day">02.11.2026', 'log-day">01.11.2026', "log-e warn"):
    if need not in imp:
        fail(f"«Важное» lacks {need!r}")
for gone in ("|", "CONSOLE", "2026-11-02T", "1.256241", "HINT_"):
    if gone in imp.replace("<wbr>", ""):
        fail(f"«Важное» still shows {gone!r}")
if "Автоподбор:" in al or al.count('class="log-e') != 5:
    fail("«Все» shows every entry, nothing folded")
print("CONSOLE_LOG_FEED=PASS")
