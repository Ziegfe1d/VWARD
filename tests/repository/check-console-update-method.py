#!/usr/bin/env python3
"""«Обновления» → «Способ обновления»: whole package or changed files, saved in update.conf.

The Panel offers both, the API gives the choice and how the last update came (method.state),
and the «Модуль обновлений» row says it: «целиком» or «изменённые файлы, заменено N …»."""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web/assets/vward-console.js").read_text()
API = (ROOT / "web/cgi-bin/api.cgi").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_UPDATE_METHOD=FAIL: {message}")


for need in ("sel('data-cfg-upd=\"update_method\"'", "['full', 'Целиком'], ['files', 'Только изменённые файлы']",
             "lastApplyNote(u.last_apply, u.last_method)"):
    if need not in JS:
        fail(f"the Panel lacks {need!r}")
for need in ("update_method=U_METHOD", 'update_method:(if $u_method == "files" then "files" else "full" end)',
             'kv_file "$STATE/method.state" last_method=LM_METHOD last_at=LM_AT', "last_method:(if $lm_method"):
    if need not in API:
        fail(f"the API lacks {need!r}")

src = re.search(r"const lastApplyNote = \(la, lm\) => \{.*?\n\};", JS, re.S)
if not src:
    fail("lastApplyNote not found")
prog = ("const plural = (n, a, b, c) => n % 10 == 1 && n % 100 != 11 ? a : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? b : c;"
        "const fmtKB = kb => kb + ' КБ';" + src.group(0) +
        "const la = {changed_files: 3, fetched_bytes: 4096};"
        "console.log(JSON.stringify([lastApplyNote(null, null), lastApplyNote(la, null), lastApplyNote(la, {method: 'full'}),"
        " lastApplyNote(null, {method: 'full'}), lastApplyNote(la, {method: 'files'})]));")
out = json.loads(subprocess.run(["node", "-e", prog], capture_output=True, text=True, check=True).stdout)
want = ["", "последнее обновление: заменено 3 файла, скачано 4 КБ", "последнее обновление: целиком",
        "последнее обновление: целиком", "последнее обновление: изменённые файлы, заменено 3 файла, скачано 4 КБ"]
if out != want:
    fail(f"the engine row note: {out}")
print("CONSOLE_UPDATE_METHOD=PASS")
