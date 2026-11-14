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
# fix.39: a name that opens neither directly nor through the VPN leaves the list (a rule of autopick
# itself: no switch and no sandbox, owner 14.11.2026); the row says so while it is counted; shared
# CDN names are marked.
for need in ("не открывается и через VPN (' + Math.min(n.vpn_fail, AD_NEITHER) + ' из ' + AD_NEITHER", "общее имя CDN", "не открывается и через VPN - убирается из списка"):
    if need not in page:
        fail(f"page lacks {need!r}")
if "vpncheck" in JS.lower() or "Песочница: убрал бы" in JS:
    fail("the VPN check is a rule of autopick: no switch, no sandbox")
API = (Path(__file__).resolve().parents[2] / "web/cgi-bin/api.cgi").read_text(encoding="utf-8")
if "vpn_fail: (.value.vpn_fail // 0)" not in API:
    fail("the router must answer each name's count of checks that opened neither way")
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
  t(1) + '|MAINT_REMOVE|api.mixpanel.com|streak=0/3 dns blocked', t(1) + '|STATS|-|seen=1',
  t(0.9) + '|MAINT_VPN_FAIL|ftp.lug.ro|streak=2/3 direct: connect: timeout; vpn: connect: timeout',
  t(0.7) + '|REMOVED|old.example.com|does not open through the VPN either (direct: tls: reset; vpn: tls: reset)',
  t(0.6) + '|REMOVED|back.example.com|opened directly 3 times in a row'].join('\\n'));
console.log(JSON.stringify({ html: adFeedHtml(), n: ADV.feed.length, hosts: ADV.feed.map(e => e.host),
  cdn: [sharedCdn('e123.dscb.akamaiedge.net'), sharedCdn('a.sni.global.fastly.net'), sharedCdn('d1a2b3.cloudfront.net'), sharedCdn('chatgpt.com'), sharedCdn('akamai.net.evil.example')] }));
"""
r = subprocess.run(["node", "-e", h], capture_output=True, text=True, timeout=30)
if r.returncode:
    fail(r.stderr[-500:])
o = json.loads(r.stdout)
if "не открывается и через VPN (2 из 3)" not in o["html"]:
    fail(f"the count in words: {o['html'][:900]}")
if "убран из VPN: не открывается и через VPN" not in o["html"] or o["html"].count("вернулся напрямую") != 2:
    fail("a name removed because the VPN does not open it either must not read «вернулся напрямую»")
if o["cdn"] != [True, True, True, False, False]:
    fail(f"shared CDN names: {o['cdn']}")
if "За сутки: 1 добавлено, 2 вернулись напрямую, 2 пропущено как реклама." not in o["html"]:
    fail(f"the day's counts: {o['html'][:300]}")
if o["hosts"].count("chatgpt.com") != 1 or "-" in o["hosts"]:
    fail(f"one step a line, no service lines: {o['hosts']}")
if "возможно, реклама: не добавлен" not in o["html"] or "убран: возможно, реклама" not in o["html"]:
    fail("ads in words")
print("AUTOPICK_PAGE=PASS")
