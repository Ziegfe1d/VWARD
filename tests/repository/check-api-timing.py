#!/usr/bin/env python3
"""The Panel's slow answers measured step by step on the router itself (fix.39 item 3).

The owner's Viva, 12.11.2026: lists-data 3.7 s, status 1.9 s, config-data 1.7 s; the emulator
explains half of it. «Диагностика» → «Замер скорости Панели» asks the router to answer each of them
once more and says how long every step took:

1. api.cgi marks its steps (tstep) only when VWARD_API_TIMING names a file - an HTTP request cannot
   set it, an ordinary answer writes nothing;
2. action=api-timing&of=NAME runs that answer once with the marks and returns the steps in ms;
   only the three measured answers may be asked;
3. the page has the button, the table and «Копировать».
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "web/cgi-bin/api.cgi"
TEXT = API.read_text(encoding="utf-8")
JS = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")


def fail(m):
    raise SystemExit(f"API_TIMING=FAIL: {m}")


if not re.search(r"\|api-timing(\|[a-z-]+)*\) ;;", TEXT):
    fail("the API must accept action=api-timing")
for act, least in (("status", 8), ("lists-data", 4), ("config-data", 3)):
    start = TEXT.index(f'if [ "$ACTION" = {act} ]; then') if act != "status" else TEXT.index("# The four router queries run side by side")
    end = TEXT.find('\nif [ "$ACTION" = ', start + 10)
    body = TEXT[start:end if end > 0 else len(TEXT)]
    if len(re.findall(r"^\s*tstep [a-z0-9-]+$", body, re.M)) < least:
        fail(f"{act}: fewer than {least} steps marked")

with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    env = {"PATH": os.environ["PATH"], "REQUEST_METHOD": "GET", "JQ": shutil.which("jq"), "VWARD_PROFILE_LIB": "/nonexistent",
           "VWARD_CONSOLE_AUTH_CONF": str(tmp / "auth.conf"), "VWARD_CONSOLE_CACHE_DIR": str(tmp / "cache"), "TMPDIR": str(tmp)}

    def api(query, extra=None):
        r = subprocess.run(["sh", str(API)], env=env | {"QUERY_STRING": query} | (extra or {}), text=True, capture_output=True, timeout=120, cwd=API.parent)
        return r.stdout.split("\n\n", 1)[1] if "\n\n" in r.stdout else r.stdout

    # 1. Marks only on request.
    marks = tmp / "marks"
    api("action=config-data", {"VWARD_API_TIMING": str(marks)})
    got = [l.split("\t") for l in marks.read_text().splitlines()] if marks.exists() else []
    if len(got) < 3 or any(len(x) != 2 or not re.fullmatch(r"[0-9]+(\.[0-9]+)?", x[1]) for x in got):
        fail(f"VWARD_API_TIMING must collect «step<TAB>uptime» lines: {got[:5]}")
    before = set(p.name for p in tmp.iterdir())
    api("action=config-data")
    if set(p.name for p in tmp.iterdir()) - before - {"cache"}:
        fail("an ordinary answer must write no timing file")
    # 2. The measured answer.
    d = json.loads(api("action=api-timing&of=config-data"))
    if d.get("ok") is not True or d.get("of") != "config-data" or not isinstance(d.get("total_ms"), int) or len(d.get("steps") or []) < 3:
        fail(f"api-timing: {d}")
    if any(set(s) != {"step", "ms"} or not isinstance(s["ms"], int) or s["ms"] < 0 for s in d["steps"]) or d["steps"][0]["step"] != "start":
        fail(f"api-timing steps: {d['steps'][:4]}")
    if abs(sum(s["ms"] for s in d["steps"]) - d["total_ms"]) > 20:
        fail(f"the steps must add up to the total: {d}")
    for bad in ("log", "config", "api-timing", "", "status;id"):
        if json.loads(api(f"action=api-timing&of={bad}")).get("error") != "invalid_value":
            fail(f"api-timing must refuse of={bad!r}")
    if list(tmp.glob("vward-api-timing.*")):
        fail("the timing file must be removed")

diag = JS[JS.index("  'd-diag'() {"):JS.index("  'd-stability'() {")]
if "apiTimingPanel()" not in diag or "function apiTimingPanel()" not in JS or "apiGet('api-timing', { of:" not in JS or "data-act=\"api-timing-copy\"" not in JS:
    fail("«Диагностика» must have «Замер скорости Панели» with the button and «Копировать»")
print("API_TIMING=PASS")
