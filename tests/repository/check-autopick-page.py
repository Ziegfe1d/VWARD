#!/usr/bin/env python3
"""«Автоподбор доменов» (fix.38, owner 12.11.2026, mock-up v3/v4): the live feed from the core's
journal speaks words, counts the day right (added / back direct / skipped as ads), shows a name
once per step; the page has the switch, «Сейчас» with «Пауза», search, filter and the way slider
«Авто | VPN | Провайдер»; the feed is read only while the page is open."""
import json, shutil, subprocess, sys
from pathlib import Path
JS = (Path(__file__).resolve().parents[2] / "web/assets/vward-console.js").read_text(encoding="utf-8")
def fail(m): raise SystemExit(f"AUTOPICK_PAGE=FAIL: {m}")
page = JS[JS.index("  'd-adaptive'() {"):JS.index("  'd-ipcats'() {")]
for need in ("data-cfg-rt=\"adaptive-mode\"", "panel('Сейчас'", "data-act=\"ad-pause\"", "data-go=\"a-adaptive\"", "data-list-filter placeholder=\"Найти домен\"",
             "choiceSlider('ad-way', [['auto', 'Авто'], ['vpn', 'VPN'], ['direct', 'Провайдер']]", "скоро вернётся напрямую"):
    if need not in page:
        fail(f"page lacks {need!r}")
if "if (current === 'd-adaptive' && !ADV.paused) adFeedLoad();" not in JS:
    fail("the feed refreshes only on its page, not paused")
if "if (key === 'ad-way')" not in JS or "action: v === 'vpn' ? 'pin' : 'remove'" not in JS:
    fail("the slider pins (VPN) or takes back (Провайдер)")
if not shutil.which("node"):
    print("AUTOPICK_PAGE=PASS (node not found)"); sys.exit(0)
a = JS.index("const adHm = "); b = JS.index("// Light: the core's journal tail")
code = a and JS[a:b]
h = """const esc = s => String(s), dom = s => String(s), empty = s => '<empty>' + s + '</empty>';
""" + code + """
const now = Date.now(), t = m => new Date(now - m * 60000).toISOString().replace('Z', '+0000').replace(/\\.\\d+/, '');
ADV.feed = adFeedParse([t(30) + '|DIRECT_OK|dl.google.com|http 302', t(12) + '|PROBE_UNKNOWN|ad.doubleclick.net|dns blocked',
  t(5) + '|AUTO_VPN|chatgpt.com|direct: tls', t(5) + '|ADDED|chatgpt.com|AdaptiveAuto', t(2) + '|MAINT_REMOVE|cdn.discordapp.com|streak=3/3 http 200',
  t(1) + '|MAINT_REMOVE|api.mixpanel.com|streak=0/3 dns blocked', t(1) + '|STATS|-|seen=1'].join('\\n'));
console.log(JSON.stringify({ html: adFeedHtml(), n: ADV.feed.length, hosts: ADV.feed.map(e => e.host) }));
"""
r = subprocess.run(["node", "-e", h], capture_output=True, text=True, timeout=30)
if r.returncode:
    fail(r.stderr[-500:])
o = json.loads(r.stdout)
if "За сутки: 1 добавлено, 1 вернулись напрямую, 2 пропущено как реклама." not in o["html"]:
    fail(f"the day's counts: {o['html'][:300]}")
if o["hosts"].count("chatgpt.com") != 1 or "-" in o["hosts"]:
    fail(f"one step a line, no service lines: {o['hosts']}")
if "возможно, реклама: не добавлен" not in o["html"] or "убран: возможно, реклама" not in o["html"]:
    fail("ads in words")
print("AUTOPICK_PAGE=PASS")
