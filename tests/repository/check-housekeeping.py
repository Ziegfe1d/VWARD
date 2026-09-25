#!/usr/bin/env python3
"""Housekeeping on the router's own tools: logs rotate, old copies go.

Runs vward-housekeeping.sh with BusyBox applets first in PATH (no GNU find, so
no -printf) on a scratch tree: every log in the policy rotates at its limit,
logs under it stay, size caps keep the newest entry, and copies made on every
settings save, ad rule and publish are kept to their newest few.  Tunnel .conf
uploads an older version left on the USB drive are removed.
"""

import gzip
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "components/runtime/scripts/vward-housekeeping.sh"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


busybox = shutil.which("busybox")
if not busybox:
    fail("busybox is needed to run housekeeping as on the router")

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    bb = tmp / "bb"; bb.mkdir()
    for applet in ("awk", "ls", "du", "tail", "head", "grep", "gzip", "cp", "mv", "rm", "rmdir", "date", "wc", "cat", "mkdir", "sed", "tr", "id", "find"):
        (bb / applet).symlink_to(busybox)
    r = tmp / "root"
    log = r / "opt/var/log"; (log / "vward").mkdir(parents=True)
    b = r / "opt/var/backups/vward"; b.mkdir(parents=True)
    (r / "tmp").mkdir()

    def aged(path: Path, minutes: float) -> Path:
        t = time.time() - minutes * 60
        os.utime(path, (t, t))
        return path

    # Logs: two over their limit (one of them newly in the policy), one under.
    (log / "vward-wan-guard.log").write_text("w" * 300000)
    (log / "vward/console-audit.log").write_text("c" * 300000)
    (log / "vward-route.log").write_text("small\n")
    (log / "vward-unknown.log").write_text("u" * 900000)

    # Copies kept to their newest few.
    for i in range(15):
        f = b / f"update.conf.console-202609{i:02d}-000000"; f.write_text("x"); aged(f, 100 - i)
    ads = b / "ads-privacy-guard"
    for i in range(14):
        d = ads / f"publish-202609{i:02d}-000000"; d.mkdir(parents=True); (d / "rules.txt").write_text("r")
        aged(d, 100 - i)
    for i in range(25):
        d = ads / "manual" / f"202609{i:02d}-000000"; d.mkdir(parents=True)
        aged(d, 100 - i)
    (b / "unrelated.txt").write_text("kept")

    # Size caps: 3 x 1000 KB diagnostics over a 2 MB cap: the oldest goes.
    diag = log / "vward/diagnostics"; diag.mkdir()
    for i in range(3):
        f = diag / f"report-{i}.txt"; f.write_bytes(b"d" * 1000 * 1024); aged(f, 30 - i)

    # A tunnel .conf an older version left on the USB drive.
    up = r / "opt/var/run/vward/console-tunnel"; up.mkdir(parents=True)
    (up / "upload.AbC123").write_text("PrivateKey = SECRET\n")

    # A lock a power cut left on the USB drive (its process is gone).
    dead = subprocess.Popen(["true"]); dead.wait()
    stale = r / "opt/var/lib/vward/policy-sync/lock"; stale.mkdir(parents=True)
    (stale / "pid").write_text(f"{dead.pid}\n")

    helper = tmp / "helper"; helper.write_text("#!/bin/sh\necho result=unchanged\n"); helper.chmod(0o755)
    env = os.environ | {"PATH": f"{bb}:{os.environ['PATH']}", "VWARD_ROOT_PREFIX": str(r),
                        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
                        "VWARD_CONSOLE_CONFIG_BIN": str(helper), "VWARD_BACKUP_DAY_FILE": str(tmp / "backup-day")}
    res = subprocess.run([busybox, "sh", str(SCRIPT)], env=env, capture_output=True, text=True)
    if res.returncode != 0:
        fail(f"housekeeping failed: {res.stdout[-600:]} {res.stderr[-600:]}")

    for f in (log / "vward-wan-guard.log", log / "vward/console-audit.log"):
        if f.stat().st_size != 0 or not Path(str(f) + ".1.gz").exists():
            fail(f"{f.name} over its limit must rotate: {res.stdout}")
        if gzip.decompress(Path(str(f) + ".1.gz").read_bytes())[:1] not in (b"w", b"c"):
            fail(f"{f.name}.1.gz must hold the old log")
    if (log / "vward-route.log").read_text() != "small\n" or Path(str(log / "vward-route.log") + ".1.gz").exists():
        fail("a log under its limit stays as it is")
    if (log / "vward-unknown.log").stat().st_size != 900000:
        fail("files outside the policy are not touched")

    kept = sorted(p.name for p in b.glob("update.conf.console-*"))
    if len(kept) != 10 or kept[0] != "update.conf.console-20260905-000000":
        fail(f"the newest ten update.conf copies stay: {kept}")
    if not (b / "unrelated.txt").exists():
        fail("other files in the backup folder stay")
    pubs = sorted(p.name for p in ads.glob("publish-*"))
    if len(pubs) != 10 or pubs[0] != "publish-20260904-000000":
        fail(f"the newest ten publish copies stay: {pubs}")
    if len(list((ads / "manual").iterdir())) != 20:
        fail("the newest twenty manual rule copies stay")

    left = sorted(p.name for p in diag.iterdir())
    if left != ["report-1.txt", "report-2.txt"]:
        fail(f"the oldest diagnostics go until the cap holds: {left}")

    if up.exists():
        fail("a tunnel .conf left on the USB drive must go")
    if stale.exists() or "STALE_LOCK_REMOVED|" not in res.stdout:
        fail("a lock whose owner is gone must go")
    if "rotated=2|errors=0" not in (log / "vward-housekeeping.log").read_text():
        fail("the run is logged")

    # A second run changes nothing more.
    res = subprocess.run([busybox, "sh", str(SCRIPT)], env=env, capture_output=True, text=True)
    if res.returncode != 0 or "RETENTION_DELETE" in res.stdout or "ROTATED" in res.stdout:
        fail(f"a second run has nothing to do: {res.stdout}")

print("HOUSEKEEPING=PASS")
