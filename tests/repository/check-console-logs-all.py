#!/usr/bin/env python3
"""Технические журналы: «Все» is the first chip and open by default; it shows every
journal in one timeline (times with and without a zone), a line without a time stays
with its entry, and each entry is marked with its journal; copy, share and save take
what is shown."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_LOGS_ALL=FAIL: {message}")


a = JS.index("function logTime")
funcs = JS[a:JS.index("\n}\n", JS.index("function mergeLogs")) + 3]
if "function logRestamp(line, t) {" not in funcs:
    fail("RED: the timeline keeps each journal's own time zone")
script = funcs + """
console.log(JSON.stringify(mergeLogs([
  {label: "Интернет", text: "2026-10-04 11:40:00+0300 class=HEALTHY\\n2026-10-04 12:00:00+0300 class=DOWN\\n  details\\n"},
  {label: "VPN", text: "2026-10-04 11:30:00|OK\\n2026-10-04 11:50:00|FAILOPEN_DOWN"},
  {label: "Обновления", text: "2026-10-04T08:45:00Z [INFO] check\\nno time line"},
  {label: "Wi-Fi", text: "Лог пока пуст или недоступен."}]).split("\\n")));
"""
r = subprocess.run(["node", "-e", script], text=True, capture_output=True, env=os.environ | {"TZ": "Europe/Moscow"})
if r.returncode:
    fail(r.stderr[-400:])
got = json.loads(r.stdout)
# One time zone in the timeline, its offset said (owner 13.11.2026: UTC «+0000», «Z» and local
# time without a zone side by side in one export).
want = ["[VPN] 2026-10-04 11:30:00+0300|OK", "[Интернет] 2026-10-04 11:40:00+0300 class=HEALTHY",
        "[Обновления] 2026-10-04 11:45:00+0300 [INFO] check", "    no time line", "[VPN] 2026-10-04 11:50:00+0300|FAILOPEN_DOWN",
        "[Интернет] 2026-10-04 12:00:00+0300 class=DOWN", "      details"]
if got != want:
    fail(f"timeline: {got}")
for need in ("const LOG_VIEW = [{ id: 'all', label: 'Все' }].concat(LOG_TABS);", "logTab = 'all'",
             "LOG_VIEW.map(t => '<button type=\"button\" data-log=\"'", "const info = [], merged = mergeLogs(parts, logNewest, info, want);",
             "else copyText(text);", "LOG_TABS.filter(tb => tb.id !== 'cron')", "name = 'vward-' + tab + '-' + today() + '.txt'", "logFull(tab).then(text => download(name, text || '')"):
    if need not in JS:
        fail(f"the Panel lacks {need}")
# Owner 2026-11-01: newest first by default (the choice kept in the browser); an entry keeps its
# continuation lines; each source's last event or state (empty / not created / unreadable).
if "let logNewest = store.get('vward-log-order') !== 'oldest';" not in JS:
    fail("«Все» must open newest first")
script2 = funcs + """
const info = [];
const out = mergeLogs([
  {label: "Интернет", text: "2026-10-18 11:40:00+0300 old\\n2026-11-01 12:00:00+0300 new\\n  details\\n"},
  {label: "VPN", text: "Журнал пуст: записей пока нет."},
  {label: "Wi-Fi", text: "Журнал ещё не создан: программа пока ничего не записала."},
  {label: "ИИ", text: "Журнал недоступен: нет прав на чтение."}], true, info).split("\\n");
console.log(JSON.stringify({out, info: info.map(i => [i.label, i.state, i.last != null])}));
"""
r = subprocess.run(["node", "-e", script2], text=True, capture_output=True, env=os.environ | {"TZ": "Europe/Moscow"})
if r.returncode:
    fail(r.stderr[-400:])
got = json.loads(r.stdout)
if got["out"] != ["[Интернет] 2026-11-01 12:00:00+0300 new", "      details", "[Интернет] 2026-10-18 11:40:00+0300 old"]:
    fail(f"newest first: {got['out']}")
if got["info"] != [["Интернет", "ok", True], ["VPN", "empty", False], ["Wi-Fi", "missing", False], ["ИИ", "error", False]]:
    fail(f"source states: {got['info']}")
API = (ROOT / "web/cgi-bin/api.cgi").read_text(encoding="utf-8")
for need in ("Журнал пуст: записей пока нет.", "Журнал недоступен: нет прав на чтение.", "Журнал ещё не создан: программа пока ничего не записала."):
    if need not in API:
        fail(f"API: {need}")

# owner 12.11.2026: «Все» in one request (each source after «@@VWARD-LOG name»), the newest N of the
# timeline, nothing loaded by itself; «Очистить» empties the live journal(s), archives stay.
split = JS[JS.index("function logSplit(text) {"):JS.index("\n}\n", JS.index("function logSplit(text) {")) + 3]
pick = JS[JS.index("function logPick(text, q) {"):JS.index("\n}\n", JS.index("function logPick(text, q) {")) + 3]
script3 = funcs + split + pick + """
const got = logSplit('@@VWARD-LOG wan\\n2026-11-12 10:00:00+0300 a\\n@@VWARD-LOG tunnel\\nЖурнал пуст: записей пока нет.\\n@@VWARD-LOG ads\\n');
const parts = [{label: 'Интернет', text: got.wan}, {label: 'VPN', text: '2026-11-12 09:00:00|x\\n2026-11-12 11:00:00|y\\n2026-11-12 12:00:00|z'}];
console.log(JSON.stringify({got, newest: mergeLogs(parts, true, null, 2).split('\\n'), oldest: mergeLogs(parts, false, null, 2).split('\\n'),
  pick: logPick('[VPN] 2026-11-12 09:00:00|alpha\\n    more\\n[VPN] 2026-11-12 10:00:00|beta', 'alpha').split('\\n'), none: logPick('[VPN] 2026-11-12 09:00:00|a', 'zzz')}));
"""
r = subprocess.run(["node", "-e", script3], text=True, capture_output=True, env=os.environ | {"TZ": "Europe/Moscow"})
if r.returncode:
    fail(r.stderr[-400:])
o = json.loads(r.stdout)
if o["got"] != {"wan": "2026-11-12 10:00:00+0300 a", "tunnel": "Журнал пуст: записей пока нет.", "ads": ""}:
    fail(f"the «Все» answer split by source: {o['got']}")
if o["newest"] != ["[VPN] 2026-11-12 12:00:00+0300|z", "[VPN] 2026-11-12 11:00:00+0300|y"] or o["oldest"] != ["[VPN] 2026-11-12 11:00:00+0300|y", "[VPN] 2026-11-12 12:00:00+0300|z"]:
    fail(f"the newest N of the timeline in either order: {o}")
if o["pick"] != ["[VPN] 2026-11-12 09:00:00|alpha", "    more"] or o["none"] != "Ничего не найдено":
    fail(f"«Найти в журнале» keeps whole entries: {o}")
import re, shutil, tempfile
API = (ROOT / "web/cgi-bin/api.cgi").read_text(encoding="utf-8")
HELPER = (ROOT / "components/console/scripts/vward-console-config.sh").read_text(encoding="utf-8")
def cases(text, start):
    body = text[text.index(start):]; body = body[:body.index("    esac")]
    return dict(re.findall(r"^\s+([a-z]+)\)\s*(?:#[^\n]*\n\s*)*(?:\n\s*)?echo (\S+)", body, re.M))
api_map, helper_map = cases(API, "log_file() {"), cases(HELPER, "journal_file() {")
tabs = re.findall(r"\{ id: '([a-z]+)', label: '", JS[JS.index("const LOG_TABS = ["):JS.index("];", JS.index("const LOG_TABS = ["))])
all_api = re.search(r'LOG_ALL_NAMES="([^"]+)"', API).group(1).split()
all_helper = re.search(r'all\) jc_names="([^"]+)"', HELPER).group(1).split()
if api_map != helper_map or len(api_map) < 19:
    fail(f"«Очистить» must clear the files «Журналы» read: {set(api_map.items()) ^ set(helper_map.items())}")
if all_api != [t for t in tabs if t != "cron"] or all_helper != all_api:
    fail(f"«Все» is every source but «Расписание», in the Panel's order: {all_api} / {all_helper} / {tabs}")
for need in ("loadLog(logTab, true, true)", "else if (current === 'logs') loadLog"):
    if need in JS:
        fail(f"RED: «Журналы» still load by themselves: {need}")
if "if (id === 'logs') { busyEnd(b); load('journal')" not in JS or "'log-clear': c => cfgSet({ op: 'journal', target: 'clear', value: c.what, confirm: 'LOG_CLEAR' }" not in JS:
    fail("«Журналы» open without a request; «Очистить» goes through the confirmed journal op")
if '[ "$OP:$TARGET" != journal:clear ] || REQUIRED=LOG_CLEAR' not in API:
    fail("the API asks the confirmation for «Очистить»")
jq = shutil.which("jq")
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp); log = tmp / "opt/var/log"; (log / "vward/archive").mkdir(parents=True); (tmp / "tmp").mkdir()
    (log / "vward-wan-guard.log").write_text("2026-11-12 10:00:00+0300 class=HEALTHY\n")
    (log / "vward-tunnel-guard.log").write_text("".join(f"2026-11-12 10:{i:02d}:00|OK\n" for i in range(40)))
    (log / "vward/archive/vward-tunnel-guard.log.20261111-000000.gz").write_text("old")
    e = os.environ | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=log&name=all&count=20", "VWARD_ROOT_PREFIX": str(tmp), "JQ": jq or "jq",
                      "VWARD_PROFILE_LIB": str(tmp / "none")}
    out = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=e, capture_output=True, text=True).stdout.split("\n\n", 1)[-1]
    heads = re.findall(r"^@@VWARD-LOG ([a-z]+)$", out, re.M)
    if heads != all_api or "class=HEALTHY" not in out or out.count("|OK") != 20 or "10:39:00|OK" not in out:
        fail(f"RED: name=all must answer every source once, each cut to count: {heads} {out[:400]!r}")
    # «Скачать» (owner 13.11.2026): the whole live journal, not the entries shown.
    e["QUERY_STRING"] = "action=log&name=all&count=20&full=1"
    out = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=e, capture_output=True, text=True).stdout.split("\n\n", 1)[-1]
    if out.count("|OK") != 40 or "10:00:00|OK" not in out:
        fail(f"RED: full=1 must answer the whole live journal: {out.count('|OK')} entries")
    if jq:
        def clear(value, confirm="LOG_CLEAR"):
            body = f"op=journal&target=clear&value={value}" + (f"&confirm={confirm}" if confirm else "")
            e2 = os.environ | {"REQUEST_METHOD": "POST", "QUERY_STRING": "action=config", "HTTP_X_VWARD_REQUEST": "console",
                               "CONTENT_TYPE": "application/x-www-form-urlencoded", "CONTENT_LENGTH": str(len(body)), "VWARD_ROOT_PREFIX": str(tmp),
                               "JQ": jq, "VWARD_PROFILE_LIB": str(tmp / "none"), "VWARD_CONSOLE_CONFIG_BIN": str(ROOT / "components/console/scripts/vward-console-config.sh"),
                               "VWARD_CONSOLE_AUDIT_LOG": str(log / "vward/console-audit.log"), "VWARD_CONSOLE_CACHE_DIR": str(tmp / "cache"),
                               "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"), "TMPDIR": str(tmp)}
            r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=e2, input=body, capture_output=True, text=True)
            return r.stdout.split("\n\n", 1)[-1].strip()
        if '"confirmation_required"' not in clear("tunnel", None) or (log / "vward-tunnel-guard.log").stat().st_size == 0:
            fail(f"«Очистить» without the confirmation must not clear: {clear('tunnel', None)}")
        got = clear("tunnel")
        if '"ok":true' not in got and "action_unavailable" not in got:
            fail(f"«Очистить» VPN: {got}")
        if "action_unavailable" not in got:
            if (log / "vward-tunnel-guard.log").stat().st_size or not (log / "vward/archive/vward-tunnel-guard.log.20261111-000000.gz").exists() or \
               (log / "vward-wan-guard.log").stat().st_size == 0:
                fail("RED: «Очистить» empties the chosen live journal only, the archive stays")
            if '"invalid_value"' not in clear("passwd") and '"invalid_operation"' not in clear("passwd"):
                fail("an unknown journal is refused")
print("CONSOLE_LOGS_ALL=PASS")

# «Скачать»: no reload, no redraw (owner 12.11.2026), the whole live journal (owner 13.11.2026).
_a = JS.index("else if (a === 'log-save')"); _b = JS.index("else if", _a + 10)
if "render()" in JS[_a:_b] or "loadLog(" in JS[_a:_b]:
    raise SystemExit("CONSOLE_LOGS_ALL=FAIL: «Скачать» reloads or redraws the journal")
if "logFull(tab)" not in JS[_a:_b] or "apiText('log', { name: 'all', full: 1 })" not in JS:
    raise SystemExit("CONSOLE_LOGS_ALL=FAIL: RED: «Скачать» must save the whole live journal")
