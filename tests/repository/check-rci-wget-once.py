#!/usr/bin/env python3
"""A wget that crashes is run once, also when agents ask Keenetic at the same moment.

Chaos CI 08.11 (wget-crash): «BusyBox wget crashed 2 times» - two agents of the same minute, no
curl, both reached vward_rci_get's wget before either noted the crash. The first try of a wget
not known to work belongs to one caller (an atomic mkdir); the others skip it meanwhile. Real
vward_rci_get, a fake wget that crashes after 0.5 s, 6 parallel callers, sh + BusyBox ash; also:
a working wget is noted and used by all, a try left by a killed caller expires after a minute.
"""
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "components/runtime/lib/vward-device-profile.sh"
SHELLS = [["sh"]] + ([["busybox", "ash"]] if shutil.which("busybox") else [])
fails = []


def check(label, cond, detail=""):
    if not cond:
        fails.append(f"{label}: {detail}")


for shell in SHELLS:
    n = shell[-1]
    for mode in ("crash", "works"):
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            w = t / "fakewget"
            body = (f'echo run >> "{t}/runs"; sleep 0.5; kill -SEGV $$' if mode == "crash"
                    else f'echo run >> "{t}/runs"; echo answer')
            w.write_text(f"#!/bin/sh\n{body}\n")
            w.chmod(0o755)
            script = (f'. "{PROFILE}"\nVWARD_CURL_BIN=\nvward_tool() {{ :; }}\n'
                      f'VWARD_RCI_WGET="{w}"\nVWARD_WGET_BROKEN_DIR="{t}/broken"\n'
                      f'VWARD_RCI_CALLS="{t}/calls"\nvward_rci_get show/x 2; echo "rc=$?"')
            ps = [subprocess.Popen(shell + ["-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                  for _ in range(6)]
            outs = [p.communicate(timeout=60)[0] for p in ps]
            runs = (t / "runs").read_text().split() if (t / "runs").exists() else []
            if mode == "crash":
                check(f"{n} parallel callers crash wget once", len(runs) == 1, f"{len(runs)} runs")
                again = subprocess.run(shell + ["-c", script], capture_output=True, text=True, timeout=60).stdout
                runs = (t / "runs").read_text().split()
                check(f"{n} crashed wget not asked again", len(runs) == 1 and "rc=1" in again, again)
            else:
                check(f"{n} working wget answers", sum("answer" in o for o in outs) >= 1, outs)
                again = subprocess.run(shell + ["-c", script], capture_output=True, text=True, timeout=60).stdout
                check(f"{n} known-good wget used", "answer" in again and "rc=0" in again, again)
    # A try left by a killed caller: skipped within the minute, taken over after it.
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        w = t / "fakewget"
        w.write_text(f'#!/bin/sh\necho run >> "{t}/runs"; echo answer\n')
        w.chmod(0o755)
        script = (f'. "{PROFILE}"\nVWARD_CURL_BIN=\nvward_tool() {{ :; }}\n'
                  f'VWARD_RCI_WGET="{w}"\nVWARD_WGET_BROKEN_DIR="{t}/broken"\n'
                  f'VWARD_RCI_CALLS="{t}/calls"\nvward_rci_get show/x 2; echo "rc=$?"')
        key = str(w).replace("/", "_").replace(":", "_")
        (t / "broken" / f"{key}.try").mkdir(parents=True)
        r1 = subprocess.run(shell + ["-c", script], capture_output=True, text=True, timeout=60).stdout
        old = time.time() - 120
        os.utime(t / "broken" / f"{key}.try", (old, old))
        r2 = subprocess.run(shell + ["-c", script], capture_output=True, text=True, timeout=60).stdout
        r3 = subprocess.run(shell + ["-c", script], capture_output=True, text=True, timeout=60).stdout
        check(f"{n} fresh try skipped", "rc=1" in r1, r1)
        check(f"{n} stale try taken over", "rc=0" in r2 or "rc=0" in r3, r2 + r3)

if fails:
    raise SystemExit("RCI_WGET_ONCE=FAIL\n" + "\n".join(fails))
print("RCI_WGET_ONCE=PASS " + "+".join(s[-1] for s in SHELLS) +
      ": parallel callers crash wget once, a crashed wget never again, a working one used by all, a killed try expires")
