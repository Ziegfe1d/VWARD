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
want = ["[VPN] 2026-10-04 11:30:00|OK", "[Интернет] 2026-10-04 11:40:00+0300 class=HEALTHY",
        "[Обновления] 2026-10-04T08:45:00Z [INFO] check", "    no time line", "[VPN] 2026-10-04 11:50:00|FAILOPEN_DOWN",
        "[Интернет] 2026-10-04 12:00:00+0300 class=DOWN", "      details"]
if got != want:
    fail(f"timeline: {got}")
for need in ("const LOG_VIEW = [{ id: 'all', label: 'Все' }].concat(LOG_TABS);", "logTab = 'all'",
             "LOG_VIEW.map(t => '<button type=\"button\" data-log=\"'", "S.logs.all = mergeLogs(parts, logNewest, LOGINFO)",
             "copyText(S.logs[logTab] || '')", "LOG_TABS.filter(tb => tb.id !== 'cron')", "download('vward-' + tab + '-' + today() + '.txt'"):
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
print("CONSOLE_LOGS_ALL=PASS")
