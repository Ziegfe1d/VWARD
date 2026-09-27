#!/usr/bin/env python3
"""Each section shows its component's events in plain words.

The journal readers of the Panel run in node over sample lines written the way
the components write them: every known event becomes a sentence with no
technical text (no EVENT_NAMES, key=value or pipes), routine checks are left out.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")


def fail(msg):
    raise SystemExit(f"CONSOLE_ACTIVITY=FAIL: {msg}")


node = shutil.which("node")
if not node:
    print("CONSOLE_ACTIVITY=SKIPPED (node not found)")
    sys.exit(0)

start = JS.index("/* ---------- Что происходило")
end = JS.index("Object.keys(ACTIVITY).forEach")
block = JS[start:end]

LOGS = {
    "adaptive": "\n".join([
        "2026-09-27 12:00:01|AUTO_VPN|chatgpt.com|domain-list3|reason=DIRECT_UNAVAILABLE_VPN_OK|ip=1.2.3.4|dns=IPV4_OK",
        "2026-09-27 12:00:02|DIRECT_OK|ya.ru|200|0.1",
        "2026-09-27 12:00:03|RECHECK_ADAPTIVE|ya.ru",
        "2026-09-27 12:01:00|MAINT_DIRECT_CONFIRM|old.example|streak=3/3",
        "2026-09-27 12:02:00|AUTO_DIRECT_MAINT|old.example",
        "2026-09-27 12:03:00|night.example|AUTO_DIRECT|memberships=2",
        "2026-09-27 12:04:00|ADD_ERROR|bad.example|rc=1|some error",
        "2026-09-27 12:05:00|UNKNOWN_THING|x",
    ]),
    "routing": "AUTO_DIRECT: old.example\nChecked=40 Total=512 Next=41\n",
    "policysync": "2026-09-27 00:33:23 start\n2026-09-27 00:33:23 SYNC active=8 wanted=200 added=3 removed=0 existing=109 managed=91 errors=0 save=YES\n",
    "policy": "2026-09-27 00:40:00|duration=12s|targets=120|checked=118|ok=110|fail=8|unknown=0|nodns=0|skipped=2|candidates=0\n",
    "tunnel": "\n".join([
        "2026-09-27 11:00:00|WAIT_DOWN_CONFIRM|health=DOWN|config=OK|age=30|down_streak=1|active=0",
        "2026-09-27 11:01:00|FAILOPEN_DOWN|health=DOWN|config=OK|age=30|down_streak=2|active=1",
        "2026-09-27 11:10:00|FAILOPEN_RESTORED|health=UP|config=OK|age=5|down_streak=0|active=0",
    ]),
    "wan": "2026-09-27 10:00:00+0300 class=PHY_DOWN previous=HEALTHY carrier=0\n2026-09-27 10:02:00+0300 class=HEALTHY previous=PHY_DOWN ok\n",
    "recovery": "2026-09-27 10:01:00+0300 action=DHCP_RENEW interface=ISP rc=0\n2026-09-27 10:01:30+0300 action=MANUAL_WAN_BOUNCE interface=ISP down_rc=0 up_rc=1\n",
    "wifi": "2026-09-27T09:00:00+0300 INFO snapshot clients=5\n2026-09-27T09:01:00+0300 INFO band switch mac=aa:bb:cc:dd:ee:01 from=2.4 to=5 ap=ap1 rssi=-50\n",
    "updater": "\n".join([
        "2026-09-27T01:00:00Z [INFO] Manifest unchanged; no pending update",
        "2026-09-27T02:00:00Z [INFO] Manifest unchanged; no pending update",
        "2026-09-27T03:00:00Z [INFO] State transition: CHECKING",
        "2026-09-27T04:00:00Z [INFO] Update 0.2.0-rc.1.fix.16 committed",
    ]),
    "ads": "2026-09-27 08:00:00|SOURCES_UPDATE_OK|healthy=5\n2026-09-27 08:05:00|ROUTE_DNS|rows_set|domains=42|skipped=1\n2026-09-27 08:06:00|JOB_DONE|id=7\n",
}

EXPECT = {
    "adaptive": ["bad.example: не удалось добавить в VPN", "night.example снова открывается напрямую - убран из VPN",
                 "old.example снова открывается напрямую - убран из VPN", "chatgpt.com напрямую не открывается - теперь через VPN"],
    "routing": ["night.example убран из VPN - открывается напрямую", "old.example убран из VPN - открывается напрямую",
                "old.example стабильно открывается напрямую"],
    "policy": ["Проверено адресов: 118, напрямую не открываются: 8", "IP-категории обновлены: добавлено 3, убрано 0"],
    "tunnel": ["VPN снова работает - трафик списков вернулся в VPN", "VPN не работает - трафик списков пущен напрямую",
               "VPN не отвечает - проверяем ещё раз"],
    "wan": ["Интернет снова работает", "Вы переподключили интернет - не получилось", "Запросили у провайдера новый адрес",
            "Нет сигнала в кабеле провайдера"],
    "wifi": ["Ноутбук: перешло с 2.4 ГГц на 5 ГГц"],
    "updater": ["Установлено обновление 0.2.0-rc.1.fix.16", "Проверка: обновлений нет"],
    "ads": ["Домены маршрутов идут через DNS Keenetic: 42", "Источники списков обновлены"],
}

harness = """
const num = v => (v == null || v === '' || isNaN(Number(v))) ? null : Number(v);
const fmtInt = v => num(v) == null ? '—' : String(Number(v));
function plural(n, one, few, many) { const a = n % 10, b = n % 100; return a === 1 && b !== 11 ? one : a >= 2 && a <= 4 && (b < 12 || b > 14) ? few : many; }
const wifiName = mac => mac === 'aa:bb:cc:dd:ee:01' ? 'Ноутбук' : mac;
const S = { logs: @LOGS@, loadedAt: {} };
@BLOCK@
const out = {};
Object.keys(ACTIVITY).forEach(k => { out[k] = activityEvents(k).map(e => e.text + (e.n > 1 ? ' x' + e.n : '')); });
out._links = {}; Object.keys(ACTIVITY).forEach(k => { out._links[k] = activityEvents(k).map(e => [e.host || '', e.go || '']); });
console.log(JSON.stringify(out));
""".replace("@LOGS@", json.dumps(LOGS)).replace("@BLOCK@", block)

r = subprocess.run([node, "-e", harness], capture_output=True, text=True, timeout=30)
if r.returncode != 0:
    fail(r.stderr[-800:])
got = json.loads(r.stdout)

for key, want in EXPECT.items():
    texts = got.get(key, [])
    if [t.split(" x")[0] for t in texts] != want:
        fail(f"{key}: {texts}")
if got["updater"][1] != "Проверка: обновлений нет x2":
    fail(f"the same event in a row must be shown once with a count: {got['updater']}")
links = got.pop("_links")
# A domain event carries its domain (its controls), other events open their place.
if links["adaptive"] != [["bad.example", ""], ["night.example", ""], ["old.example", ""], ["chatgpt.com", ""]] or any(h for h, _ in links["policy"]):
    fail(f"domain events must carry the domain: {links['adaptive']}")
if links["wifi"] != [["", "w-aa:bb:cc:dd:ee:01"]]:
    fail(f"a Wi-Fi event opens its device: {links['wifi']}")
if links["ads"] != [["", "d-agh"], ["", "d-sources"]]:
    fail(f"an Ads event opens where it is managed: {links['ads']}")
for key, texts in got.items():
    for t in texts:
        if "=" in t or "|" in t or any(w.isupper() and "_" in w for w in t.split()):
            fail(f"technical text reached the page: {key}: {t}")

print("CONSOLE_ACTIVITY=PASS")
