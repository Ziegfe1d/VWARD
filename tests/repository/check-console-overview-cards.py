#!/usr/bin/env python3
"""Overview cards (owner 2026-10-12): three lines on any screen - title, value, one short line
(longer text ends in «…», the whole of it on hover); Ads shows what AdGuard Home blocked today;
Internet the port speed; Storage what is used; Wi-Fi which client and why; no «Среда выполнения»
card (a stopped scheduler is in the bell); «Маршруты» named as in the bottom bar."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text()
CSS = (ROOT / "web/assets/vward-console.css").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_OVERVIEW_CARDS=FAIL: {message}")


for rule in (".card-value{grid-area:value;", ".card-sub{grid-area:sub;", ".card-title{grid-area:title;"):
    css = CSS[CSS.index(rule):CSS.index("}", CSS.index(rule))]
    if "white-space:nowrap" not in css or "text-overflow:ellipsis" not in css:
        fail(f"{rule} must stay on one line: {css}")
if "const CARD_IDS = ['system', 'updates', 'wan', 'vpn', 'lists', 'routes', 'wifi', 'ads', 'storage'];" not in JS or "'Среда выполнения', to:" in JS:
    fail("no «Среда выполнения» card")
if "{ id: 'routes', title: 'Маршруты'" not in JS or "routes: 'Маршруты'" not in JS:
    fail("the routing section is «Маршруты» on the card, the page and the bottom bar")
if "data: ['status', 'route', 'wifi', 'ads', 'adsstats', 'lists', 'awg', 'tq']" not in JS:
    fail("the Overview loads AdGuard Home's statistics")
API = (ROOT / "web/cgi-bin/api.cgi").read_text()
if '(if $inet | has("internet") then $inet.internet else null end)' not in API:
    fail("an unanswered internet status must be unknown (null), not «no internet»")
if "title: 'Роутер отвечает медленно'" not in JS or "['warn', 'Последний запуск с ошибкой']" not in JS:
    fail("a slow Keenetic and a run that ended with an error are not «Нет связи» and «Не работает»")
if not shutil.which("node"):
    print("CONSOLE_OVERVIEW_CARDS=PASS (node not found: texts not run)")
    sys.exit(0)


def grab(start, end="\n}\n"):
    i = JS.index(start)
    return JS[i:JS.index(end, i) + len(end)]


def line(start):
    i = JS.index(start)
    return JS[i:JS.index("\n", i) + 1]


code = "".join([line("const isTrue = "), grab("const tunPill = ", "];\n"), line("const tunGuardOff = "), line("const tunOff = "), line("const viaIs = "),
                line("const vpnDirect = "), line("const lowDisk = "), grab("function wifiWarnText("), grab("function cardData(id) {")])
harness = """
let STATUS = {}; const S = { lists: null, route: null, wifi: null, ads: null, adsstats: null };
const st = () => STATUS; const prof = () => ({ tunnel_interface: 'OpkgTun2' }); const plat = () => ({});
const TUNBUSY = {}, TUNUP = {}, TUN_BUSY = {};
const tunLabel = n => n; const fmtTime = t => 'T' + t; const num = v => v == null ? null : Number(v); const fmtKB = v => (v / 1048576).toFixed(1) + ' ГБ';
const fmtInt = v => String(v); const phaseText = v => v; const durText = v => v; const fmtSpeed = v => (v / 1000) + ' Гбит/с';
const plural = (n, a, b, c) => { n = Math.abs(n) % 100; const m = n % 10; return n > 10 && n < 20 ? c : m > 1 && m < 5 ? b : m === 1 ? a : c; };
const wifiName = mac => mac === 'aa' ? 'iPhone' : mac;
""" + code + """
const T = (name, connected, state) => ({ name, connected: connected ? 'yes' : 'no', state });
STATUS = { wan: { internet: true, address: '100.86.0.1', speed: 1000 }, storage: { total_kb: 60606054, free_kb: 60186624 },
  wg: { interfaces: [T('OpkgTun0', false, 'down'), T('OpkgTun2', true, 'up')] } };
S.lists = { lists: [{ via: 'vpn' }, { via: 'vpn' }, { via: 'bypass' }] }; S.route = { ip: { managed_routes: 431, active_count: 8 } };
S.wifi = { enabled: true, count: 6, clients: [{ mac: 'aa', health: 'WARNING', recommendation: 'bind_2g' }, { mac: 'bb', health: 'OK' }] };
S.ads = { counts: { blocked: 1 } }; S.adsstats = { ok: true, blocked: 12430 };
const out = {};
for (const id of ['wan', 'vpn', 'lists', 'routes', 'wifi', 'ads', 'storage']) { const c = cardData(id); out[id] = [c.title, c.value, c.sub]; }
// Keenetic did not answer about the internet in time (internet null): not «no internet».
STATUS.wan = { internet: null, address: '100.86.0.1' }; { const c = cardData('wan'); out.slow = [c.value, c.pill[1]]; }
STATUS.wan = { internet: false, address: '100.86.0.1' }; { const c = cardData('wan'); out.down = [c.value, c.pill[1]]; }
// «Мало места»: a tenth of a big drive is plenty (252 GB with 23.8 GB free is not a warning).
out.low = [lowDisk(264241152, 24956108), lowDisk(8388608, 200000), lowDisk(8388608, 700000), lowDisk(33554432, 2097152)];
console.log(JSON.stringify(out));
"""
r = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30)
if r.returncode:
    fail(r.stderr[-1000:])
o = json.loads(r.stdout)
if o.pop("slow") != ["Роутер отвечает медленно", "Нет ответа"] or o.pop("down") != ["Нет связи", "Не работает"]:
    fail("Keenetic's late answer about the internet reads as «no internet» (Viva 2026-10-13)")
if o.pop("low") != [False, True, True, False]:
    fail("«Мало места» by a share alone: a big drive with gigabytes free warns")
want = {
    "wan": ["Интернет", "В сети", "порт 1 Гбит/с"],
    "vpn": ["VPN", "1 из 1", "выключены: 1"],
    "lists": ["Доменные списки", "2 через VPN", "1 в обход"],
    "routes": ["Маршруты", "431 подсеть", "8 IP‑категорий"],
    "wifi": ["Wi-Fi клиенты", "6 клиентов", "iPhone: лучше 2,4 ГГц"],
    "ads": ["Реклама", "12430", "заблокировано за сутки"],
    "storage": ["Хранилище", "0.4 ГБ", "занято из 57.8 ГБ"],
}
for k, v in want.items():
    if o[k] != v:
        fail(f"{k}: {o[k]} want {v}")
# Short enough for one line on a narrow phone (about 22 characters under the value).
for k, v in o.items():
    if len(v[2]) > 24:
        fail(f"{k}: the line under the value is too long for one line: {v[2]!r}")
print("CONSOLE_OVERVIEW_CARDS=PASS")
