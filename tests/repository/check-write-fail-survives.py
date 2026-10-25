#!/usr/bin/env python3
"""A failed write does not end the route engine or its init script (fix.34, WP-D).

BusyBox ash (the router's shell) ends the whole script when a redirection of a special built-in
fails: «: > file» and «exec 7>file» on a full /tmp or USB (2>/dev/null and «|| ...» do not help).
The engine and S91 write empty files with «printf '' >» and open descriptors with «command exec».
Checked here: none of the two forms is left, and both replacements survive under the shells at hand.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = ["components/route-engine/scripts/vward-route-engine.sh", "components/runtime/init.d/S91vward-route-engine"]
BAD = re.compile(r"(^|[;&|{(]\s*|\s)(:\s*>|exec\s+[0-9]*[<>](?!&))")


def fail(msg):
    print(f"WRITE_FAIL_SURVIVES=FAIL: {msg}")
    sys.exit(1)


for rel in FILES:
    for n, line in enumerate((ROOT / rel).read_text().splitlines(), 1):
        code = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
        m = BAD.search(code)
        if m and not code[:m.start(2)].rstrip().endswith("command"):
            fail(f"{rel}:{n}: a failed write here ends the script under BusyBox ash: {line.strip()}")

shells = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])
probe = "printf '' > /nonexistent/x 2>/dev/null; command exec 7>/nonexistent/x 2>/dev/null || echo handled; echo survived"
for shell in shells:
    r = subprocess.run([*shell, "-c", probe], capture_output=True, text=True, timeout=10)
    if r.stdout.split() != ["handled", "survived"]:
        fail(f"{shell[0]}: the replacements do not survive a failed write: {r.stdout!r} {r.stderr!r}")

print("WRITE_FAIL_SURVIVES=PASS")
