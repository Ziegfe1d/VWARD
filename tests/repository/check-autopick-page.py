#!/usr/bin/env python3
"""«Автоподбор доменов» (fix.38, owner 12.11.2026, mock-up v3/v4; fix.39: the check through the VPN
too, the marks of the core, «Реклама и счётчики мимо VPN» as «Выкл · Песочница»): the live feed from the core's
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
# fix.39: the check through the VPN too, the sandbox «Реклама и счётчики», the core's marks.
for need in ("choiceSlider('ad-ads', [['off', 'Выкл'], ['sandbox', 'Песочница']]", "adSandboxText(adNames.length, names.length)", "общее имя CDN",
             "реклама или счётчик", "не открывается и через VPN (", "['cdn', 'Общие имена CDN']", "adWhy(n.why)"):
    if need not in page:
        fail(f"page lacks {need!r}")
if "if (key === 'ad-ads') { cfgSet({ op: 'adaptive-ads', value: v }" not in JS:
    fail("the sandbox slider saves adaptive-ads")
h2 = """const esc = s => String(s), dom = s => String(s), empty = s => '<empty>' + s + '</empty>', fmtInt = n => String(n);
""" + code + JS[JS.index("function adSandboxText("):JS.index("// Light: the core's journal tail")] + """
const now = Date.now(), t = m => new Date(now - m * 60000).toISOString().replace('Z', '+0000').replace(/\\.\\d+/, '');
const quiet = adSandboxText(0, 40);
ADV.feed = adFeedParse([t(50) + '|MAINT_NO_PATH|2.datadog.pool.ntp.org|fails=2/3 direct: connect: timeout; vpn: connect: timeout',
  t(20) + '|DROPPED|2.datadog.pool.ntp.org|opens neither directly nor through the VPN: direct: connect: timeout; vpn: connect: timeout',
  t(15) + '|REMOVED|ad.doubleclick.net|dns blocked', t(14) + '|REMOVED|cdn.discordapp.com|opened directly 3 times in a row',
  t(9) + '|AUTO_VPN|www.googleadservices.com|direct: tls: reset; vpn: http 200', t(9) + '|SANDBOX_AD_SKIP|www.googleadservices.com|would not send to the VPN: an advert or a counter (googleadservices.com)',
  t(8) + '|ADDED|www.googleadservices.com|AdaptiveAuto', t(3) + '|MAINT_VPN_DOWN|-|x', t(2) + '|MODE|-|apply', t(1) + '|SANDBOX_AD_GROUP|-|would take out of the VPN 2 of 40: a, b'].join('\\n'));
console.log(JSON.stringify({ html: adFeedHtml(), hosts: ADV.feed.map(e => e.host), quiet, busy: adSandboxText(2, 40),
  why: [adWhy('connect: timeout'), adWhy('tls: reset'), adWhy('http 451'), adWhy('http 302 region'), adWhy('connect: refused'), adWhy(''), adWhy('http 403 refused'), adWhy('http 403 region'), adWhy('http 200 wrong-cert refused')] }));
"""
r = subprocess.run(["node", "-e", h2], capture_output=True, text=True, timeout=30)
if r.returncode:
    fail(r.stderr[-500:])
o = json.loads(r.stdout)
if "За сутки: 1 добавлено, 1 вернулись напрямую, 1 пропущено как реклама, 1 убрано: не открываются и через VPN. Песочница: 1 не отправил бы в VPN." not in o["html"]:
    fail(f"the day's counts with the VPN check and the sandbox: {o['html'][:400]}")
for need in ("проверка: не открывается ни напрямую, ни через VPN (2 из 3)", "убран: не открывается ни напрямую, ни через VPN",
             "Песочница: не отправил бы в VPN - реклама или счётчик", "убран: возможно, реклама"):
    if need not in o["html"]:
        fail(f"the feed lacks {need!r}")
if "-" in o["hosts"]:
    fail(f"service lines (the VPN down, the mode, the sandbox's summary) are not names: {o['hosts']}")
if not o["quiet"].startswith("Песочница: совпало с автоподбором") or "Ничего не меняется" not in o["quiet"]:
    fail(f"sandbox, nothing to do: {o['quiet']}")
if not o["busy"].startswith("Песочница: расхождения с автоподбором - убрал бы из VPN 2 из 40 доменов, за сутки не отправил бы в VPN 1") or "Ничего не меняется" not in o["busy"]:
    fail(f"sandbox, what it would do: {o['busy']}")
if o["why"] != ["нет ответа", "соединение сброшено", "сайт закрыт по требованию (451)", "сайт не работает в этом регионе", "соединение отклонено", "", "сайт отказывает отсюда (403), через VPN отвечает", "сайт не работает в этом регионе", "напрямую чужой сертификат (заглушка провайдера), через VPN настоящий"]:
    fail(f"why it did not open directly, in words: {o['why']}")
print("AUTOPICK_PAGE=PASS")
