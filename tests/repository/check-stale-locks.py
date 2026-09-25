#!/usr/bin/env python3
"""Locks whose owner is gone are removed; locks of a running job stay.

The updater starts nothing while any VWARD lock exists, and locks on the USB
drive outlive a power cut.  vward_locks_sweep (run by the boot hook S89 and by
hourly housekeeping) removes a lock whose process is dead, whose process id now
belongs to another process, or that has had no owner id for an hour.
vward_lock_take takes such a lock over and refuses a live one.
"""

import os
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/runtime/lib/vward-runtime-admission.sh"
S89 = ROOT / "components/runtime/init.d/S89vward-update-recovery"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def pid_start(pid: int) -> str:
    stat = Path(f"/proc/{pid}/stat").read_text()
    return stat[stat.rindex(")") + 2:].split()[19]


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    root = tmp / "root"
    dead = subprocess.Popen(["true"]); dead.wait()
    me = os.getpid()

    def lock(path, pid=None, start=None, age_min=0):
        d = root / path.lstrip("/")
        d.mkdir(parents=True)
        if pid is not None:
            (d / "pid").write_text(f"{pid}\n")
        if start is not None:
            (d / "pid_start").write_text(f"{start}\n")
        if age_min:
            t = time.time() - age_min * 60
            os.utime(d, (t, t))
        return d

    def setup():
        subprocess.run(["rm", "-rf", str(root)], check=True)
        (root / "tmp").mkdir(parents=True)
        return {
            "dead_flash": lock("/opt/var/lib/vward/policy-sync/lock", pid=dead.pid),
            "live": lock("/tmp/vward-route-reconciler-maint.lock", pid=me, start=pid_start(me)),
            "live_no_start": lock("/tmp/vward-tunnel-guard-guard.lock", pid=me),
            "reused_pid": lock("/opt/var/lib/vward/ads-privacy-guard/scan.lock", pid=me, start="1"),
            "ownerless_old": lock("/opt/var/lib/vward/route-engine/classifier.lock", age_min=120),
            "ownerless_new": lock("/tmp/vward-wan-guard.lock.d"),
        }

    def sh(script, extra=None):
        env = os.environ | {"VWARD_ROOT_PREFIX": str(root)} | (extra or {})
        return subprocess.run(["sh", "-c", f'. "{LIB}"; {script}'], env=env, capture_output=True, text=True)

    def check(locks, how):
        for name in ("dead_flash", "reused_pid", "ownerless_old"):
            if locks[name].exists():
                fail(f"{how}: the {name} lock must be removed")
        for name in ("live", "live_no_start", "ownerless_new"):
            if not locks[name].exists():
                fail(f"{how}: the {name} lock must stay")
        if list(root.rglob("*.stale.*")):
            fail(f"{how}: nothing of a removed lock may stay")

    locks = setup()
    out = sh("vward_locks_sweep").stdout
    check(locks, "sweep")
    if out.count("STALE_LOCK_REMOVED|") != 3:
        fail(f"each removed lock is reported: {out}")

    # The boot hook sweeps before anything of VWARD starts.
    locks = setup()
    state = tmp / "state"; state.mkdir(exist_ok=True)
    (state / "journal.state").write_text("phase=IDLE\n")
    boot = tmp / "boot-id"; boot.write_text("boot\n")
    r = subprocess.run(["sh", str(S89), "start"], capture_output=True, text=True,
                       env=os.environ | {"VWARD_ROOT_PREFIX": str(root), "VWARD_ADMISSION_LIB": str(LIB),
                                         "VWARD_UPDATER": "/nonexistent", "VWARD_UPDATE_STATE_DIR": str(state),
                                         "VWARD_UPDATE_JOURNAL": str(state / "journal.state"),
                                         "VWARD_UPDATE_RECOVERY_FAILED": str(state / "failed"),
                                         "VWARD_UPDATE_RECOVERY_LOG": str(tmp / "recovery.log"),
                                         "VWARD_UPDATE_RUN_DIR": str(tmp / "run"), "VWARD_UPDATE_BOOT_ID_FILE": str(boot)})
    if r.returncode != 0:
        fail(f"boot hook: {r.stdout} {r.stderr}")
    check(locks, "boot")

    # Taking a lock: a stale one is taken over (owner id and start recorded), a live one refused.
    locks = setup()
    flash = locks["dead_flash"]
    r = sh(f'vward_lock_take "{flash}" && cat "{flash}/pid" "{flash}/pid_start"')
    lines = r.stdout.split()
    if r.returncode != 0 or len(lines) != 2 or not lines[1].isdigit():
        fail(f"a stale lock is taken over with the new owner recorded: {r.stdout} {r.stderr}")
    if sh(f'vward_lock_take "{locks["live"]}"').returncode == 0:
        fail("a lock held by a running process must be refused")
    fresh = root / "tmp/new.lock"
    if sh(f'vward_lock_take "{fresh}"').returncode != 0 or not (fresh / "pid").exists():
        fail("a free lock is taken")

print("STALE_LOCKS=PASS")
