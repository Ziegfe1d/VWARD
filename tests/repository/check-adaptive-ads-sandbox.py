#!/usr/bin/env python3
"""«Реклама и счётчики мимо VPN» of Autopodbor, in the sandbox (owner 13.11.2026; CLAUDE.md «сначала
песочница»). This release knows «Выкл · Песочница» only; «Вкл» comes after the owner's router.

1. The Panel's helper: «adaptive-ads shadow|off» keeps one word in a file; «on» and anything else
   is refused; the same choice again changes nothing. A setting, not a routing step.
2. The Go core reads that same file, in that same form, and writes its result where the API reads
   it; the sandbox holds no hand on the writer, the engine or the router.
3. The API gives the Panel the choice (config) and the sandbox's result (route).
4. The Panel: the slider «Выкл · Песочница» on «Автоподбор доменов», no «Вкл»; the sandbox's result
   and its lines in words that start with «Песочница:»; an entry of the sandbox is not a warning."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"
JS = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")
API = (ROOT / "web/cgi-bin/api.cgi").read_text(encoding="utf-8")
CMD = (ROOT / "tools/vward-core/cmd_adaptive.go").read_text(encoding="utf-8")
ADS = (ROOT / "tools/vward-core/internal/adaptive/ads.go").read_text(encoding="utf-8")


def fail(m):
    raise SystemExit(f"ADAPTIVE_ADS_SANDBOX=FAIL: {m}")


# 1. The helper.
with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    etc = tmp / "etc"
    (etc / "route-engine").mkdir(parents=True)
    (tmp / "root/tmp").mkdir(parents=True)
    ndmc = tmp / "ndmc"
    ndmc.write_text(f'#!/bin/sh\necho "$@" >> "{tmp}/ndmc.log"\n')
    ndmc.chmod(0o755)
    env = os.environ | {
        "VWARD_CONSOLE_ETC": str(etc), "VWARD_ROUTE_STATE": str(tmp / "state"), "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"),
        "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"), "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"), "VWARD_NDMC": str(ndmc),
        "VWARD_CONSOLE_EDIT_LOCK": str(tmp / "edit.lock"), "VWARD_CONSOLE_SETTINGS_LOCK": str(tmp / "settings.lock"),
        "VWARD_AGENTS_CONF": str(tmp / "agents.conf"), "VWARD_ROOT_PREFIX": str(tmp / "root"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
        "VWARD_SETTINGS_REGISTRY": str(ROOT / "config/settings/settings-registry.json"), "VWARD_COMPONENT_STATE": str(tmp / "components"),
    }
    mode = etc / "route-engine/adaptive-ads.mode"

    def run(*a):
        r = subprocess.run(["sh", str(HELPER), *a], env=env, text=True, capture_output=True, timeout=60)
        return (r.stdout.strip().splitlines() or [""])[-1]

    if run("adaptive-ads", "off") != "result=unchanged" or mode.exists():
        fail("off when nothing is set changes nothing")
    if run("adaptive-ads", "shadow") != "result=changed" or mode.read_text() != "shadow\n":
        fail(f"shadow: the file holds one word: {mode.read_text() if mode.exists() else None!r}")
    if run("adaptive-ads", "shadow") != "result=unchanged":
        fail("the same choice again changes nothing")
    for bad in ("on", "1", "act", "shadow;reboot", "Вкл"):
        if run("adaptive-ads", bad) != "error=invalid_value" or mode.read_text() != "shadow\n":
            fail(f"{bad!r} must be refused and the choice kept («Вкл» is not in this release)")
    if run("adaptive-ads", "off") != "result=changed" or mode.exists():
        fail("off takes the file away")
    if (tmp / "ndmc.log").exists():
        fail(f"the switch must not touch Keenetic: {(tmp / 'ndmc.log').read_text()!r}")
    # «Сброс настроек»: as after installation - off.
    run("adaptive-ads", "shadow")
    if run("reset", "settings") != "result=changed" or mode.exists():
        fail("«Сброс настроек» must switch the sandbox off")
    for x in list((tmp / "backup").rglob("*")) + [etc / "route-engine/domain-lists.conf"]:
        if x.is_file():
            x.unlink()
    if [x for x in etc.rglob("*") if x.is_file()]:
        fail(f"off leaves no trace: {[str(x) for x in etc.rglob('*') if x.is_file()]}")
    audit = (tmp / "audit.log").read_text()
    if "adaptive-ads mode=shadow result=changed" not in audit or "adaptive-ads mode=off result=changed" not in audit:
        fail("the Panel's journal has the changes")

# 2. The core: the same file, the same word; the result where the API reads it; passive.
for need, where, what in (
        ('"/opt/etc/vward/route-engine/adaptive-ads.mode"', CMD, "the core reads the helper's file"),
        ('"/tmp/vward-core-ads-sandbox.json"', CMD, "the core's result in memory, not on the USB drive"),
        ("${VWARD_CORE_ADS_REPORT:-/tmp/vward-core-ads-sandbox.json}", API, "the API reads the core's result"),
        ('AdsShadow AdsMode = "shadow"', ADS, "the word of the sandbox"),
        ('log.put("WOULD_SKIP_AD", res.Host, "zone="+z)', CMD, "a name on its way into the VPN"),
        ('put("WOULD_REMOVE_AD", a.Host, "zone="+a.Zone)', CMD, "a name already in the VPN"),
        ("adaptive.SaveAdsReport(f.adsReport, nil)", CMD, "the result goes with the core"),
):
    if need not in where:
        fail(f"{what}: {need!r}")
# The sandbox is asked and answers: no hand on what changes the router.
for hand in ("Writer", "*Engine", "rci.", "router.", "ndm.", "journal."):
    if hand in ADS:
        fail(f"the sandbox must not hold {hand!r}")
# The working system first: the name is on its way into the group before the sandbox is asked.
if not CMD.index("pending[res.Host] = true") < CMD.index('ads.WouldSkip(res.Host)') < CMD.index("if len(last) > 4096"):
    fail("the sandbox is asked after the working decision, inside the same step")
if "on" in [w.strip('"') for w in ADS.split() if w.startswith('"') and w.endswith('"')]:
    fail("no «Вкл» in the core yet")

# 3. The API.
for need, what in (
        ('AD_ADS=off; [ "$(cat "$CONFIG_ETC/route-engine/adaptive-ads.mode" 2>/dev/null)" != shadow ] || AD_ADS=shadow', "the choice as the core reads it"),
        ("adaptive_ads:$adaptive_ads", "config gives the choice"),
        ("ads_sandbox:$ads_sandbox", "route gives the sandbox's result"),
        ('adaptive-mode|adaptive-ads|classifier|smartdns-guard|tunnel-fallback|tunnel-return) set -- "$OP" "$VALUE" ;;', "the operation reaches the helper"),
):
    if need not in API:
        fail(f"api.cgi: {what}")
if shutil.which("jq"):
    flt = API[API.index("ADS_SANDBOX=\"$(\"$JQ\" -c '") + len("ADS_SANDBOX=\"$(\"$JQ\" -c '"):]
    flt = flt[:flt.index("' \\\n")]
    for text, want in (
            ('{"mode":"shadow","since":"2026-11-14T09:00:00Z","at":"2026-11-14T11:00:00Z","ads":{"ad.doubleclick.net":"doubleclick.net"}}',
             {"since": "2026-11-14T09:00:00Z", "at": "2026-11-14T11:00:00Z", "ads": {"ad.doubleclick.net": "doubleclick.net"}}),
            ('{"mode":"off","ads":{"x":"y"}}', None), ("not json", None), ('{"mode":"shadow"}', {"since": "", "at": "", "ads": {}}),
            ('{"mode":"shadow","ads":{"a.example":7}}', {"since": "", "at": "", "ads": {}})):
        r = subprocess.run(["jq", "-c", flt], input=text, capture_output=True, text=True)
        got = json.loads(r.stdout) if r.stdout.strip() else None
        if got != want:
            fail(f"the result filter: {text!r} -> {got!r}, want {want!r}")

# 4. The Panel.
page = JS[JS.index("  'd-adaptive'() {"):JS.index("  'd-ipcats'() {")]
if "choiceSlider('ad-ads', [['off', 'Выкл'], ['shadow', 'Песочница']]" not in page:
    fail("the slider «Выкл · Песочница» on the autopick page (no «Вкл» in this release)")
if "ctrlRow('Реклама и счётчики мимо VPN'" not in page or "adsSandboxHtml(" not in page:
    fail("the row and the sandbox's result on the page")
if "if (key === 'ad-ads')" not in JS or "cfgSet({ op: 'adaptive-ads', value: v }" not in JS:
    fail("the slider sets adaptive-ads")
if not shutil.which("node"):
    print("ADAPTIVE_ADS_SANDBOX=PASS (node not found)")
    sys.exit(0)
a = JS.index("const adHm = ")
b = JS.index("// Light: the core's journal tail")
la = JS.index("function logTime")
le = JS.index("\n}\n", la) + 3
lc = JS.index("/* The journals as cards (owner 02.11")
ld = JS.index("\n}\n", JS.index("function logFeed(text) {")) + 3
h = ("const store={get:()=>null}; const esc=s=>String(s).replace(/</g,'&lt;'), dom=s=>String(s), empty=s=>'<empty>'+s+'</empty>', ico=n=>'{'+n+'}';"
     "const plural=(n,a,b,c)=>{n=Math.abs(n)%100;const m=n%10;return n>10&&n<20?c:m>1&&m<5?b:m===1?a:c;};\n"
     "let S = {}, CFG = {}; const cfgRoute = () => CFG;\n" + JS[la:le] + JS[lc:ld] + JS[a:b] + """
const now = Date.now(), t = m => new Date(now - m * 60000).toISOString().replace('Z', '+0000').replace(/\\.\\d+/, '');
ADV.feed = adFeedParse([t(40) + '|ADS_MODE|shadow|', t(30) + '|WOULD_REMOVE_AD|stats.g.doubleclick.net|zone=doubleclick.net',
  t(5) + '|AUTO_VPN|ad.doubleclick.net|direct: tls', t(5) + '|WOULD_SKIP_AD|ad.doubleclick.net|zone=doubleclick.net',
  t(5) + '|ADDED|ad.doubleclick.net|AdaptiveAuto', t(1) + '|STATS|-|seen=1 ads=shadow ads_would_skip=1 ads_would_remove=1'].join('\\n'));
const iso = m => new Date(now - m * 60000).toISOString();
const res = c => { CFG = { adaptive_ads: c.mode }; S = { route: { adaptive: { names: [{ d: 'chatgpt.com' }, { d: 'ad.doubleclick.net' }, { d: 'stats.g.doubleclick.net' }], ads_sandbox: c.rep } } }; return adsSandboxHtml(); };
const two = { since: iso(600), at: iso(2), ads: { 'ad.doubleclick.net': 'doubleclick.net', 'stats.g.doubleclick.net': 'doubleclick.net' } };
console.log(JSON.stringify({ feed: adFeedHtml(),
  off: res({ mode: 'off', rep: two }), wait: res({ mode: 'shadow', rep: null }), stale: res({ mode: 'shadow', rep: Object.assign({}, two, { at: iso(60) }) }),
  same: res({ mode: 'shadow', rep: { since: iso(600), at: iso(2), ads: {} } }), two: res({ mode: 'shadow', rep: two }),
  mark: [adsMark('ad.doubleclick.net'), adsMark('chatgpt.com')],
  log: ['2026-11-14 10:00:00|WOULD_SKIP_AD|ad.doubleclick.net|zone=doubleclick.net', '2026-11-14 10:00:00|WOULD_REMOVE_AD|api.mixpanel.com|zone=api.mixpanel.com',
    '2026-11-14 10:00:00|ADS_MODE|shadow|', '2026-11-14 10:00:00|ADS_MODE|off|'].map(l => { const e = logEntry(l); return [e.text, e.level]; }) }));
""")
r = subprocess.run(["node", "-e", h], capture_output=True, text=True, timeout=30, env=os.environ | {"TZ": "Europe/Moscow"})
if r.returncode:
    fail(r.stderr[-700:])
o = json.loads(r.stdout)
for need in ("<b>ad.doubleclick.net</b> - Песочница: не отправил бы в VPN (реклама или счётчик)",
             "<b>stats.g.doubleclick.net</b> - Песочница: убрал бы из VPN (реклама или счётчик)"):
    if need not in o["feed"]:
        fail(f"the feed lacks {need!r}: {o['feed'][:600]}")
if "пропущено как реклама" not in o["feed"] or "0 пропущено как реклама" not in o["feed"]:
    fail("a line of the sandbox is not «пропущено как реклама»: the working system did add the name")
if o["off"] != "":
    fail(f"off: no result shown: {o['off']!r}")
if "Песочница: данных пока нет" not in o["wait"] or "Песочница: данных пока нет" not in o["stale"]:
    fail(f"no fresh result from the core: said so: {o['wait']!r} / {o['stale']!r}")
if "Песочница: совпало" not in o["same"] or "расхожд" in o["same"]:
    fail(f"nothing to do differently: «совпало»: {o['same']!r}")
if "Песочница: расхождения - 2 из 3 доменов автоподбора не отправил бы в VPN" not in o["two"]:
    fail(f"two ad names of three: {o['two']!r}")
if o["mark"] != ["Песочница: не отправил бы в VPN", ""]:
    fail(f"the mark of an ad name in the list (short: it must fit a phone's line): {o['mark']!r}")
want = [["Песочница: автоподбор не отправил бы в VPN: ad.doubleclick.net · реклама или счётчик: doubleclick.net", "info"],
        ["Песочница: автоподбор убрал бы из VPN: api.mixpanel.com · реклама или счётчик: api.mixpanel.com", "info"],
        ["Реклама и счётчики мимо VPN: песочница", "info"], ["Реклама и счётчики мимо VPN: выкл", "info"]]
if o["log"] != want:
    fail(f"the journal in words:\n got {o['log']}\nwant {want}")
print("ADAPTIVE_ADS_SANDBOX=PASS")
