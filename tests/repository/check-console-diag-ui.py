#!/usr/bin/env python3
"""Panel, 01.11: «Запустить проверку» shows progress and the result on the page (a failed run is
not «выполнена»), and «Управление» names the switched-off components, not a bare count."""
import re
from pathlib import Path

js = (Path(__file__).resolve().parents[2] / "web/assets/vward-console.js").read_text()


def fail(m):
    raise SystemExit(f"CONSOLE_DIAG_UI=FAIL: {m}")


if "a === 'diag-run') diagRun()" not in js:
    fail("diag-run must call diagRun()")
if "load('diag', true).then(() => { render(); toast('Диагностика выполнена'); })" in js:
    fail("the old toast-only handler is back")
m = re.search(r"function diagRun\(\) \{.*?\n\}\n", js, re.S)
if not m or "S.errors.diag" not in m.group(0) or "busy: true" not in m.group(0) or "if (DIAG_RUN && DIAG_RUN.busy) return" not in m.group(0):
    fail("diagRun must show busy, ignore a second click and report S.errors.diag")
if "Проверка выполняется" not in js or "diagRunNote() +" not in js:
    fail("the page must say the check is running and show the result")
if "'выключено: ' + n :" in js or "off.join(', ')" not in js:
    fail("«Управление» must name the switched-off components")
print("CONSOLE_DIAG_UI=PASS")
