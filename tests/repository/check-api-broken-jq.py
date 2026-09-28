#!/usr/bin/env python3
"""A broken jq (Segmentation fault on any input, seen on a router) must not give the
Panel empty answers: the API says jq_broken, and the Panel names jq instead of «нет
связи»; an empty or cut answer is named too, not shown as a JSON.parse error."""

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> None:
    raise SystemExit(f"API_BROKEN_JQ=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    jq = Path(tmp) / "jq"
    jq.write_text("#!/bin/sh\nkill -SEGV $$\n")
    jq.chmod(0o755)
    for action in ("status", "route-data", "awg-data"):
        r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], text=True, capture_output=True, timeout=30,
                           env={"PATH": "/usr/bin:/bin", "REQUEST_METHOD": "GET", "QUERY_STRING": f"action={action}",
                                "JQ": str(jq), "VWARD_PROFILE_LIB": "/nonexistent"})
        head, _, body = r.stdout.partition("\n\n")
        if "Content-Type: application/json" not in head or json.loads(body) != {"ok": False, "error": "jq_broken"}:
            fail(f"{action}: {r.stdout!r}")

js = (ROOT / "web/assets/vward-console.js").read_text()
for need in ("jq_broken: '", "роутер вернул пустой ответ", "return apiJson(", "'Роутер отвечает с ошибкой'"):
    if need not in js:
        fail(f"the Panel lacks {need!r}")
if "r.json()" in js:
    fail("an answer is parsed without apiJson")
print("API_BROKEN_JQ=PASS")
