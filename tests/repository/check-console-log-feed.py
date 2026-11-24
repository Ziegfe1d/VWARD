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


if "copyText(S.logs[logTab] || '');" not in JS or "logFeed(text)" not in JS or "chips('Важность', 'data-act=\"log-view\"'" not in JS:
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
 '[Панель VWARD] 2026-11-02T00:10:44+0300 CONSOLE_CONFIG list-domain add x result=changed',
 '[Автоподбор доменов] 2026-11-01 23:59:00|WATCHDOG_RESTART|reason=cores=2'].join('\\n');
console.log(JSON.stringify({imp: logFeed(T), all: (logImportant = false, logFeed(T))}));""")
r = subprocess.run(["node", "-e", h], capture_output=True, text=True, env=os.environ | {"TZ": "Europe/Moscow"})
if r.returncode:
    fail(r.stderr[-400:])
import json
o = json.loads(r.stdout)
imp, al = o["imp"], o["all"]
for need in ("<time>00:12:00</time>", "<time>00:10:44</time>", "Настройки Панели VWARD: изменены", "1,26\u00a0с",
             "Автоподбор: 2 проверки", "Перезапуск после сбоя", 'log-day">02.11.2026', 'log-day">01.11.2026', "log-e warn"):
    if need not in imp:
        fail(f"«Важное» lacks {need!r}")
for gone in ("|", "CONSOLE", "2026-11-02T", "1.256241", "HINT_"):
    if gone in imp.replace("<wbr>", ""):
        fail(f"«Важное» still shows {gone!r}")
if "Автоподбор:" in al or al.count('class="log-e') != 5:
    fail("«Все» shows every entry, nothing folded")

# Boot DNS rules and nightly scan: counts are observed, and only an actual
# outcome may render completion. A control query can fail with all rules loaded.
diagnostics = [
    ("DNS_RULES|result=mismatch|config=16|live=1|reapplied=15", "Активно 1 из 16 правил DNS через VPN. Keenetic принял 15 повторно поданных правил", "warn"),
    ("DNS_RULES|result=ok|config=16|live=16|resolves=yes", "Активно 16 из 16 правил DNS через VPN", "ok"),
    ("DNS_RULES|result=ok|config=16|live=16|resolves=no", "Активно 16 из 16 правил DNS через VPN. Контрольный запрос не вернул IPv4-адрес", "warn"),
    ("DNS_RULES|result=unknown|config=16|live=0", "Не удалось подтвердить активные правила DNS через VPN", "warn"),
    ("DNS_RULES|result=gave_up|config=16|live=15|tries=3", "Активно 15 из 16 правил DNS через VPN. Попытки восстановления исчерпаны", "warn"),
    ("POLICY_SCAN_START", "Проверка IP-категорий запущена", "info"),
    ("POLICY_SCAN_ABORT|audit_rc=1", "Проверка IP-категорий завершилась с ошибкой (код 1)", "warn"),
    ("POLICY_SCAN_ABORT|reason=summary_unconfirmed", "Проверка IP-категорий остановлена. Итог скана не подтверждён", "warn"),
    ("SKIPPED_TUNNEL_DOWN|health=none", "Проверка IP-категорий пропущена. Доступность VPN не подтверждена", "warn"),
    ("duration=1785s|targets=538|checked=538|ok=23", "Проверка IP-категорий завершена. Проверено 538 из 538", "ok"),
    ("duration=14s|targets=538|checked=2", "Проверка IP-категорий выполнена частично. Проверено 2 из 538", "warn"),
]
sample = json.dumps([row[0] for row in diagnostics])
js = h.split("const T = [")[0] + f"""
console.log(JSON.stringify({sample}.map(line => {{
  const e = logEntry('2026-11-25 00:10:04|' + line);
  return [e.text, e.level];
}})));
"""
r = subprocess.run(["node", "-e", js], capture_output=True, text=True)
got = json.loads(r.stdout) if r.returncode == 0 else r.stderr[-400:]
if got != [list(row[1:]) for row in diagnostics]:
    fail(f"DNS rule and scan cards: {got}")

# fix.35.3 (owner 02.11: «vless-server servers OpkgTun4 result=checked» read «изменены»): a Panel action
# says its real result; the technical words go to the details.
h3 = h.split("const T = [")[0] + """
const API_ERRORS = {router_rejected: 'роутер отклонил команду'};
console.log(JSON.stringify(['result=checked', 'result=unchanged', 'result=changed', 'error=router_rejected'].map(r =>
  logEntry('2026-11-02T21:41:47+0300|CONSOLE_CONFIG|vless-server servers OpkgTun4 ' + r)).map(e => [e.text, e.more.join(' '), e.level])));"""
r = subprocess.run(["node", "-e", h3], capture_output=True, text=True, env=os.environ | {"TZ": "Europe/Moscow"})
if r.returncode:
    fail(r.stderr[-400:])
got = json.loads(r.stdout)
want = [["Настройки Панели VWARD: проверены", "vless-server servers OpkgTun4 result=checked"],
        ["Настройки Панели VWARD: без изменений", "vless-server servers OpkgTun4 result=unchanged"],
        ["Настройки Панели VWARD: изменены", "vless-server servers OpkgTun4 result=changed"],
        ["Настройки Панели VWARD: действие не выполнено: роутер отклонил команду", "vless-server servers OpkgTun4 error=router_rejected"]]
if [g[:2] for g in got] != want or got[3][2] != "warn":
    fail(f"RED: CONSOLE_CONFIG must follow its real result: {got}")

# fix.35.2 (owner 02.11): the DNS guard's events in words with their level, a reason in words, the
# same entry repeated in a row folded into one card that says how often and when.
h2 = h.split("const T = [")[0] + """
const D = ['[Реклама] 2026-11-02 10:52:00|DNS_CHAIN_OUT|ns=192.168.1.1:65053|reason=loop_upstream',
 '[Реклама] 2026-11-02 10:51:00|WOULD_TAKE_OUT|silent|ns=192.168.1.1:65053|observation: Keenetic not changed',
 '[Реклама] 2026-11-02 10:50:00|WOULD_TAKE_OUT|silent|ns=192.168.1.1:65053|observation: Keenetic not changed',
 '[Реклама] 2026-11-02 10:49:00|WOULD_TAKE_OUT|silent|ns=192.168.1.1:65053|observation: Keenetic not changed',
 '[Интернет] 2026-11-02 10:48:00|WOULD_TAKE_OUT|silent|ns=192.168.1.1:65053|observation: Keenetic not changed',
 '[Реклама] 2026-11-02 10:47:00|DNS_CHAIN_IN|ns=192.168.1.1:65053|AdGuard Home back in the DNS chain'].join('\\n');
console.log(logFeed(D));"""
r = subprocess.run(["node", "-e", h2], capture_output=True, text=True, env=os.environ | {"TZ": "Europe/Moscow"})
if r.returncode:
    fail(r.stderr[-400:])
f = r.stdout
if f.count('class="log-e') != 4:
    fail(f"three WOULD_TAKE_OUT in a row from one journal are one card, another journal's one is not: {f.count('class=\"log-e')}")
for need in ("AdGuard Home выведен из цепочки DNS", "причина: AdGuard Home отправляет запросы обратно роутеру",
             "Песочница: VWARD вывел бы AdGuard Home", "AdGuard Home не отвечал", "Повторилось 3 раза подряд, 10:49:00–10:51:00",
             "AdGuard Home снова в цепочке DNS", 'log-e ok', 'log-e warn'):
    if need not in f.replace("<wbr>", ""):
        fail(f"DNS guard events: {need!r} missing")
for gone in ("DNS_CHAIN", "WOULD_TAKE_OUT", "loop_upstream"):
    if gone in f.replace("<wbr>", ""):
        fail(f"internal code {gone!r} shown")

# A VLESS supervisor fork is an attempted recovery, not a proven VPN connection.
# User-facing text is plain Russian; tunnel ids remain only in details.
h4 = h.split("const T = [")[0] + """
const events = [
  '2026-11-09 20:32:29|VLESS_ENGINE|restart_attempted OpkgTun4|by=components-agent',
  '2026-11-09 20:33:10|VLESS_ENGINE|started OpkgTun4 by request|by=owner',
  '2026-11-24 11:44:52|VLESS_ENGINE|restart_attempted OpkgTun0 on its adapter|reason=both_probes_failed|by=components-agent'
].map(logEntry);
console.log(JSON.stringify(events.map(e => [e.text, e.more.join(' '), e.level])));
"""
r = subprocess.run(["node", "-e", h4], capture_output=True, text=True, env=os.environ | {"TZ": "Europe/Moscow"})
if r.returncode:
    fail(r.stderr[-400:])
events = json.loads(r.stdout)
if events[0] != ["Xray: попытка перезапуска", "Туннель OpkgTun4 by: components-agent", "warn"] or \
   events[1] != ["Xray: процесс запущен, соединение не проверено", "Туннель OpkgTun4 by: owner", "info"] or \
   events[2] != ["Xray: попытка перезапуска", "Туннель OpkgTun0 причина: оба контрольных адреса через туннель без ответа by: components-agent", "warn"]:
    fail(f"Xray recovery event truth / Panel rendering: {events}")

# The API cuts «Журналы» to the last 24 hours (hours=24); without hours a section page still sees
# its last events however old; a journal without times is shown as it is; an empty window is said.
import tempfile, datetime as dt
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp); log = tmp / "opt/var/log"; log.mkdir(parents=True)
    now = dt.datetime.now(dt.timezone.utc)
    loc = lambda h: (now - dt.timedelta(hours=h)).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    utc = lambda h: (now - dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (log / "vward-ads-privacy-guard.log").write_text(
        f"{loc(30)}|OLD_EVENT|a\n  old continuation\n{loc(25)}|OLD_TWO|b\n{utc(23)} NEW_UTC x\n{loc(2)}|NEW_LOCAL|c\n  new continuation\n")
    (log / "vward-tunnel-guard.log").write_text(f"{loc(40)}|ONLY_OLD|x\n")
    (log / "vward-wan-guard.log").write_text("raw line one\nraw line two\n")
    def api(name, hours=None):
        q = f"action=log&name={name}" + (f"&hours={hours}" if hours is not None else "")
        e = os.environ | {"REQUEST_METHOD": "GET", "QUERY_STRING": q, "VWARD_ROOT_PREFIX": str(tmp), "JQ": shutil.which("jq"),
                          "VWARD_PROFILE_LIB": str(tmp / "none")}
        out = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=e, capture_output=True, text=True).stdout
        return out.split("\n\n", 1)[1] if "\n\n" in out else out
    a = api("ads", 24)
    if "OLD_" in a or "old continuation" in a or "NEW_UTC" not in a or "NEW_LOCAL" not in a or "new continuation" not in a:
        fail(f"RED: hours=24 keeps exactly the last day, continuations with their entry: {a!r}")
    if "OLD_EVENT" not in api("ads"):
        fail("without hours a section page sees old events as before")
    if not api("tunnel", 24).startswith("За последние 24 ч записей нет"):
        fail(f"an empty window is said, not shown as an empty journal: {api('tunnel', 24)!r}")
    if "raw line two" not in api("wan", 24):
        fail("a journal without times is shown as it is")
    if "NEW_UTC" in api("ads", 1) or "NEW_LOCAL" not in api("ads", 3):
        fail("hours=N is N hours")
if "hours: LOG_HOURS" not in JS or "const LOG_HOURS = 24" not in JS or "quiet: 'за 24 ч записей нет'" not in JS:
    fail("«Журналы» ask the API for the last 24 hours and name a quiet source")
# An ambiguous TLS certificate is not evidence of direct access. The autopick
# feed must show this as uncertainty, not as an ad or a confirmed good VPN.
if shutil.which("node"):
    a = JS.index("const AD_EV = {")
    b = JS.index("function adFeedHtml()", a)
    snippet = JS[a:b]
    script = snippet + """
const feed = [
 '2026-11-21 15:10:00|PROBE_UNKNOWN|wrong.example|direct: http 200 wrong-cert; vpn: http 200 wrong-cert',
 '2026-11-21 15:11:00|MAINT_DIRECT_UNKNOWN|remain.example|streak=0/3 direct: http 200 wrong-cert; vpn: http 200 wrong-cert',
 '2026-11-21 15:12:00|PROBE_UNKNOWN|advert.example|direct: dns blocked'
].join('\\n');
console.log(JSON.stringify({entries: adFeedParse(feed).map(x => ({host:x.host, code:x.code, tone:x.tone, text:x.text})),
 why: adWhy('direct: http 200 wrong-cert; vpn: http 200 wrong-cert')}));
"""
    p = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    if p.returncode:
        fail("adaptive certificate feed JS: " + p.stderr[-400:])
    data = json.loads(p.stdout)
    got = {x["host"]: x for x in data["entries"]}
    if set(got) != {"wrong.example", "remain.example", "advert.example"}:
        fail("ambiguous direct checks hidden from adaptive feed: " + repr(got))
    if got["wrong.example"]["code"] != "PROBE_UNKNOWN" or got["wrong.example"]["tone"] != "warn":
        fail("wrong certificate shown as successful or advertising: " + repr(got))
    if got["remain.example"]["tone"] != "warn" or "маршрут сохранён" not in got["remain.example"]["text"]:
        fail("maintenance ambiguity must keep the route: " + repr(got))
    if got["advert.example"]["code"] != "ad":
        fail("dns blocked advert classification regressed: " + repr(got))
    if "через VPN настоящий" in data["why"] or "доступ напрямую не подтверждён" not in data["why"]:
        fail("certificate tooltip claims an unverified VPN recovery: " + repr(data["why"]))

print("CONSOLE_LOG_FEED=PASS")
