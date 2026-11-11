#!/usr/bin/env python3
"""Route engine watchdog: the engine's own subshells are not duplicate engines.

A probe inside $(...) or a pipeline forks the engine's shell, so "ps" shows its
command line twice for a moment.  Counting those as a second engine restarted it
whenever the watchdog ran during a probe.  Only processes whose parent is not
itself an engine process are counted, and a restart writes its reason to the
engine's event log.
"""

import os
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
    # 01.11: a restart names the processes it counted (pid:ppid), so a second core in the journal is a
    # process with its parent and the one command that asked, not a bare number.
    cd_start = S91.index("core_detail()\n")
    cd_fn = S91[cd_start:S91.index("\n}\n", cd_start) + 3]
    script = "adaptive_live_pids() { printf '%s\\n' " + " ".join([str(parent.pid)] + child) + "; }\n" + cd_fn + "core_detail\n"
    det = subprocess.run(["sh", "-c", script], capture_output=True, text=True).stdout.strip()
    if det != f"{parent.pid}:{os.getppid()},{child[0]}:{parent.pid}," and not det.startswith(f"{parent.pid}:"):
        fail(f"core_detail must list pid:ppid of each counted process: {det!r}")
    if f"{child[0]}:{parent.pid}" not in det:
        fail(f"core_detail must show the subshell with its parent: {det!r}")
finally:
    parent.kill(); other.kill()

# 01.11 hypothesis «WATCHDOG_RESTART cores=2 = the helper awk list-watch counted as a second engine»:
# the match is on the exact script field of "ps w", never on a substring of the command line.
fn_live = S91[S91.index("adaptive_live_pids()\n"):]
fn_live = fn_live[:fn_live.index("\n}\n") + 3]
PS = """  101 root      3200 S    /bin/sh /opt/bin/vward-route-engine.sh
  205 root      1100 S    awk -v g=list-watch -f /opt/bin/vward-route-engine.sh.awk /opt/var/run/vward/list-watch.map
  206 root      1100 S    grep vward-route-engine.sh /opt/var/run/vward/list-watch.map
  207 root      1100 S    {awk} /bin/sh /opt/bin/vward-route-engine.sh-helper list-watch
  300 root      3200 S    {/opt/bin/vward-route-engine.sh} /bin/sh /opt/bin/vward-route-engine.sh"""
r = subprocess.run(["sh", "-c", "ps() { cat <<'EOF'\n" + PS + "\nEOF\n}\n" + fn_live + "adaptive_live_pids"], capture_output=True, text=True)
if r.stdout.split() != ["101", "300"]:
    fail(f"only the engine itself is a core, helpers (awk, grep, *-helper) are not: {r.stdout.split()}")

for use in ("LCNT=$(adaptive_core_count)",):
    if S91.count(use) != 3:
        fail("health, startup and status checks must count cores, not command lines")
if "WATCHDOG_RESTART|reason=$UNHEALTHY" not in S91:
    fail("a restart must log its reason")
if "|procs=$(core_detail)" not in S91 or S91.count("|procs=$(core_detail)") != 2 or "START_FAILED|wait=${N}s|last_stop=$(last_stop)|alive=" not in S91:
    fail("WATCHDOG_RESTART and START_FAILED must name the processes and the lock they saw")


# The components supervisor checks every 10 s, while S91 cron is intentionally off.
# A *reused* PID must not masquerade as the Route Engine or prevent its restart.
# This test runs the actual keep_route_engine function with synthetic pid files,
# no Keenetic commands and no changes outside a temporary directory.
import re as _re
import shlex as _shlex
import signal as _signal
import tempfile as _tempfile

supervisor = (ROOT / "components/runtime/scripts/vward-cron-supervisor.sh").read_text()
fm = _re.search(r"^keep_route_engine\(\)\n\{\n.*?^\}\n", supervisor, _re.M | _re.S)
if not fm:
    fail("the components supervisor has no keep_route_engine")

with _tempfile.TemporaryDirectory() as td:
    t = Path(td)
    bin_dir = t / "bin"
    run_dir = t / "run"
    bin_dir.mkdir()
    run_dir.mkdir()
    fake = bin_dir / "vward-route-engine.sh"
    fake.write_text("#!/bin/sh\nsleep 30\n")
    fake.chmod(0o755)
    # keep_route_engine acts only when the S91 start script is there (as on the router).
    s91 = t / "S91vward-route-engine"
    s91.write_text("#!/bin/sh\nexit 0\n")
    s91.chmod(0o755)
    starts = t / "starts"
    events = t / "events"
    pidfile = run_dir / "route-engine.pid"
    p = subprocess.Popen([str(fake)], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.1)
        script = (f"BIN_DIR={_shlex.quote(str(bin_dir))}; RUN_DIR={_shlex.quote(str(run_dir))}; "
                  f"INITD={_shlex.quote(str(t))}; START_LOG={_shlex.quote(str(starts))}; "
                  f"EVENT_LOG={_shlex.quote(str(events))}\n"
                  'vward_component_enabled(){ return 0; }\n'
                  'vward_update_pending(){ return 1; }\n'
                  'restart_allowed(){ return 0; }\n'
                  'start_of(){ echo called >> "$START_LOG"; }\n'
                  'log_event(){ echo "$1" >> "$EVENT_LOG"; }\n'
                  + fm.group(0) + "\nkeep_route_engine\n")
        def check(pid):
            pidfile.write_text(str(pid) + "\n")
            run = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=5)
            if run.returncode:
                fail(f"supervisor identity check exited unexpectedly: {run.stderr}")
        check(p.pid)
        if starts.exists():
            fail("the supervisor tried to restart an actual Route Engine")
        check(os.getpid())  # a *live* Python process, not the Route Engine
        if not starts.exists() or starts.read_text().count("called") != 1 or \
           not events.exists() or "ROUTE_ENGINE_PID_STALE|" not in events.read_text():
            fail("reused PID stopped the Route Engine recovery or was not logged")
        check(99999999)  # dead PID
        if starts.read_text().count("called") != 2:
            fail("dead Route Engine PID did not trigger recovery")
    finally:
        try:
            os.killpg(p.pid, _signal.SIGTERM)
        except ProcessLookupError:
            pass
        p.wait(timeout=5)


# 11.11 (Route Engine down from 03:50 to past 06:14, nothing in the journals): a down engine that is
# not started says why, and a stale S91 control lock (dead/foreign owner, or no pid) does not keep
# every start at «control busy» for ever.
with _tempfile.TemporaryDirectory() as td:
    t = Path(td)
    (t / "S91vward-route-engine").write_text("#!/bin/sh\nexit 0\n")
    (t / "S91vward-route-engine").chmod(0o755)
    held = supervisor[supervisor.index("RE_HELD= RE_HELD_AT=0\n"):] if "RE_HELD= RE_HELD_AT=0\n" in supervisor else ""
    held = held[:held.index("\n}\n") + 3] if held else ""
    ev = t / "events"
    def run_keep(pending, start_rc, rounds=1):
        if ev.exists():
            ev.unlink()
        script = (f"BIN_DIR=/nonexistent; RUN_DIR={_shlex.quote(str(t))}; INITD={_shlex.quote(str(t))}; "
                  f"UPTIME_FILE=/proc/uptime; EVENT_LOG={_shlex.quote(str(ev))}\n"
                  'vward_component_enabled(){ return 0; }\n'
                  f'vward_update_pending(){{ return {0 if pending else 1}; }}\n'
                  'restart_allowed(){ return 0; }\n'
                  f'start_of(){{ return {start_rc}; }}\n'
                  'log_event(){ echo "$1" >> "$EVENT_LOG"; }\n'
                  + held + fm.group(0) + "\n" + "keep_route_engine\n" * rounds)
        subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=10)
        return ev.read_text() if ev.exists() else ""
    if "ROUTE_ENGINE_NOT_STARTED|reason=update_pending" not in run_keep(True, 0):
        fail("a down Route Engine held by an update marker must be logged")
    out = run_keep(False, 1, rounds=3)
    if out.count("ROUTE_ENGINE_NOT_STARTED|reason=start_failed rc=1") != 1:
        fail(f"a failed S91 start must be logged once per hour, not every round: {out!r}")
    if "STARTED|route-engine" not in run_keep(False, 0):
        fail("a successful start must still be logged")

def s91_fn(name):
    i = S91.index(name + "()\n")
    return S91[i:S91.index("\n}\n", i) + 3]
lock_fns = s91_fn("control_owner_alive") if "control_owner_alive()\n" in S91 else ""
lock_fns += s91_fn("control_lock")
with _tempfile.TemporaryDirectory() as td:
    lock = Path(td) / "control.lock"
    ev = Path(td) / "events"
    def try_lock(owner):
        if lock.exists():
            subprocess.run(["rm", "-rf", str(lock)])
        lock.mkdir()
        if owner is not None:
            (lock / "pid").write_text(f"{owner}\n")
        script = (f"CONTROL_LOCK={_shlex.quote(str(lock))}; EVENT_LOG={_shlex.quote(str(ev))}; CONTROL_WAIT=2\n"
                  + lock_fns + "control_lock && echo GOT || echo BUSY\n")
        return subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=20).stdout.strip()
    if try_lock(os.getpid()) != "GOT":
        fail("a control lock held by a reused pid (not S91) must be taken over")
    if try_lock(None) != "GOT":
        fail("a control lock without an owner pid must be taken over after the wait")
    if try_lock(99999999) != "GOT":
        fail("a control lock of a dead owner must be taken over")
    real = subprocess.Popen(["sh", "-c", "sleep 30", "S91vward-route-engine"])
    try:
        time.sleep(0.2)
        if try_lock(real.pid) != "BUSY":
            fail("a control lock held by a live S91 must be respected")
    finally:
        real.kill(); real.wait()
    if "CONTROL_LOCK_STALE|owner=" not in (ev.read_text() if ev.exists() else ""):
        fail("taking over a stale control lock must be logged")
if "|CONTROL_BUSY|cmd=$1|" not in S91:
    fail("«control busy» must be logged in the engine's event log")

print("ROUTE_ENGINE_WATCHDOG=PASS")
