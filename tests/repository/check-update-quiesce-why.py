#!/usr/bin/env python3
"""fix.35.3.1: «Could not quiesce VWARD runtime» says what was still at work.

03.11.2026 02:02:59: the updater stopped with «Could not quiesce VWARD runtime» and nothing more; the
runtime came back at 02:03:13 and the next try installed fix.35.3. The reason (a component still
active, one of the known locks, a stop that failed, crond still running) was not recorded. The
check itself is unchanged; only its answer is named. No router.
"""
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "components/update-engine/vward-update-common-base.sh"


def fail(msg):
    raise SystemExit("UPDATE_QUIESCE_WHY=FAIL: " + msg)


def clear(root):
    r = subprocess.run(["sh", "-c", '. "$1" >/dev/null 2>&1; VU_ROOT_PREFIX=$2; VU_RUN_DIR=$2/run; vu_activity_clear; echo "rc=$? why=$VU_ACTIVITY_WHY"',
                        "sh", str(BASE), str(root)], capture_output=True, text=True, timeout=30)
    return r.stdout.strip().splitlines()[-1]


with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    (d / "tmp").mkdir(); (d / "run").mkdir()
    if clear(d) != "rc=0 why=":
        fail("nothing at work must be clear: " + clear(d))
    (d / "tmp/vward-policy-sync.lock").touch()
    if clear(d) != "rc=1 why=lock:vward-policy-sync.lock":
        fail("RED: a known lock must be named: " + clear(d))
    (d / "tmp/vward-policy-sync.lock").unlink()
    (d / "run/runtime-active").touch()
    if clear(d) != "rc=1 why=runtime-active":
        fail("the runtime marker must be named: " + clear(d))
update = (ROOT / "components/update-engine/vward-update.sh").read_text()
if '"Could not quiesce VWARD runtime${VU_QUIESCE_WHY:+: $VU_QUIESCE_WHY}"' not in update:
    fail("the updater's message must carry the reason")
base = BASE.read_text()
for need in ("VU_QUIESCE_WHY=supervisor-stop", "VU_QUIESCE_WHY=crond-stop", "VU_QUIESCE_WHY=route-engine-stop",
             'VU_QUIESCE_WHY="busy ${VU_ACTIVITY_WHY:-unknown} after ${waited}s"', "VU_QUIESCE_WHY=crond-running"):
    if need not in base:
        fail("quiesce lacks " + need)
print("UPDATE_QUIESCE_WHY=PASS")
