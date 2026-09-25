#!/usr/bin/env python3
"""Route engine watchdog: the engine's own subshells are not duplicate engines.

A probe inside $(...) or a pipeline forks the engine's shell, so "ps" shows its
command line twice for a moment.  Counting those as a second engine restarted it
whenever the watchdog ran during a probe.  Only processes whose parent is not
itself an engine process are counted, and a restart writes its reason to the
engine's event log.
"""

import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
S91 = (ROOT / "components/runtime/init.d/S91vward-route-engine").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


start = S91.index("adaptive_core_count()\n")
fn = S91[start:S91.index("\n}\n", start) + 3]

parent = subprocess.Popen(["sh", "-c", "sh -c 'sleep 30; :' & sleep 30"])
other = subprocess.Popen(["sleep", "30"])
try:
    time.sleep(0.5)
    kids = subprocess.run(["sh", "-c", f"grep -l '^[0-9]* ([a-z]*) [A-Z] {parent.pid} ' /proc/[0-9]*/stat"], capture_output=True, text=True).stdout.split()
    child = [k.split("/")[2] for k in kids if k.split("/")[2] != str(parent.pid)]
    if not child:
        fail("no child process to test with")

    def count(pids):
        script = "adaptive_live_pids() { printf '%s\\n' " + " ".join(pids) + "; }\n" + fn + "adaptive_core_count\n"
        return subprocess.run(["sh", "-c", script], capture_output=True, text=True).stdout.strip()

    if count([str(parent.pid)] + child) != "1":
        fail(f"an engine with its own subshell counts as {count([str(parent.pid)] + child)} engines")
    if count([str(parent.pid)] + child + [str(other.pid)]) != "2":
        fail("a second independent engine must still count")
    if count([str(parent.pid), "999999"]) != "1":
        fail("a process gone meanwhile must not count")
finally:
    parent.kill(); other.kill()

for use in ("LCNT=$(adaptive_core_count)",):
    if S91.count(use) != 3:
        fail("health, startup and status checks must count cores, not command lines")
if "WATCHDOG_RESTART|reason=$UNHEALTHY" not in S91:
    fail("a restart must log its reason")

print("ROUTE_ENGINE_WATCHDOG=PASS")
