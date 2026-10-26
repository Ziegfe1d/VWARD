#!/usr/bin/env python3
"""fix.34.1 (r5): 25.10 14:58:01 «domain-list10 error=doh_remove_failed», the same change went
through 55 s later: Keenetic was still taking another «https upstream» out. doh_remove tries
again inside the operation (3 tries); a line gone meanwhile counts as removed; «other lines
affected» (2) is final, never tried again."""

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = (ROOT / "components/console/scripts/vward-console-config.sh").read_text()
SH = ["busybox", "sh"] if shutil.which("busybox") else ["sh"]


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_DOH_RETRY=FAIL: {message}")


m = re.search(r"^doh_remove\(\) \{\n.*?^\}\n", SRC, re.S | re.M)
if not m or "\ndoh_remove_once() {" not in SRC:
    fail("doh_remove has no retry around doh_remove_once")


def run(results: str, present: str) -> tuple[int, str]:
    # results: what each doh_remove_once returns in turn; present: doh_present answers in turn.
    script = f"""VWARD_DOH_RETRY_DELAY=0
R="{results}"; P="{present}"; CALLS=
doh_remove_once() {{ CALLS="$CALLS once"; r=${{R%% *}}; R=${{R#* }}; return "$r"; }}
doh_present() {{ CALLS="$CALLS present"; p=${{P%% *}}; P=${{P#* }}; return "$p"; }}
snapshot() {{ :; }}
audit() {{ echo "AUDIT $*"; }}
{m.group(0)}doh_remove "https upstream https://doh.example/x dot domain example.com"; echo "rc=$? calls=$CALLS"
"""
    r = subprocess.run(SH + ["-c", script], text=True, capture_output=True, timeout=30)
    if r.stderr:
        fail(r.stderr)
    return r.stdout


out = run("0 ", "0 ")
if "rc=0 calls= once\n" not in out or "AUDIT" in out:
    fail(f"removed at once: one try, nothing logged: {out!r}")
out = run("1 0 ", "0 ")
if "rc=0 calls= once present once" not in out or "AUDIT doh_remove tries=2 rc=0" not in out:
    fail(f"refused once, then removed: {out!r}")
out = run("1 ", "1 ")
if "rc=0 calls= once present\n" not in out:
    fail(f"the line gone meanwhile counts as removed: {out!r}")
out = run("1 1 1 ", "0 0 ")
if "rc=1 calls= once present once present once" not in out or "tries=3 rc=1" not in out:
    fail(f"3 tries at most, then doh_remove_failed: {out!r}")
out = run("2 ", "0 ")
if "rc=2 calls= once\n" not in out:
    fail(f"«other lines affected» is final: {out!r}")
print("CONSOLE_DOH_RETRY=PASS")
