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
  {label: "Обновления", text: "2026-10-04T08:45:00Z [INFO] check\\nno time line"}]).split("\\n")));
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
             "LOG_VIEW.map(t => '<button type=\"button\" data-log=\"'", "S.logs.all = mergeLogs(parts)",
             "copyText(S.logs[logTab] || '')", "download('vward-' + tab + '-' + today() + '.txt'"):
    if need not in JS:
        fail(f"the Panel lacks {need}")
print("CONSOLE_LOGS_ALL=PASS")
