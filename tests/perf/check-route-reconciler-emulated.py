#!/usr/bin/env python3
"""AdaptiveAuto upkeep on the router emulator: Keenetic's configuration is saved once an hour.

The upkeep takes back to direct the names that answer again without the VPN.  On a Viva it
saved Keenetic's configuration after every such name - 20-27 flash writes an hour (13.10).
The route engine restores AdaptiveAuto from the USB list at every start, so that list is the
record; Keenetic's own saved configuration follows once for the hour:
  * five names direct again in one run: five removals, the USB list without them, one save;
  * two more in the next run within the hour: removed, no save (left for the hour);
  * an hour later: one save for them.
Needs root (chroot, mount).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PATH_ENV = "/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
SAVE = "system configuration save"


def fail(message):
    raise SystemExit(f"ROUTE_RECONCILER_EMULATED=FAIL: {message}")


def sh(root, command):
    return subprocess.run(["env", "-i", f"PATH={PATH_ENV}", "HOME=/root", "chroot", str(root), "/bin/sh", "-c", command],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300)


def changes(root):
    f = root / "emu/ndmc-changes.log"
    return f.read_text().splitlines() if f.exists() else []


if os.geteuid() != 0:
    sys.exit("check-route-reconciler-emulated: needs root")

tmp = Path(tempfile.mkdtemp(prefix="vward-reconciler."))
root = tmp / "root"
subprocess.run([str(REPO / "tests/perf/emulator/build-rootfs.sh"), str(root)], check=True, stdout=subprocess.DEVNULL)
names = [f"back-{c}.example" for c in "abcdefg"]
cfg = (root / "emu/running-config").read_text()
cfg = cfg.replace("    include adaptive-one.example\n", "".join(f"    include {n}\n" for n in names[:5]))
(root / "emu/running-config").write_text(cfg)
state = root / "opt/var/lib/vward/route-engine"
hyst = root / "opt/var/lib/vward/route-reconciler"
state.mkdir(parents=True, exist_ok=True)
hyst.mkdir(parents=True, exist_ok=True)
(state / "adaptive-persist.txt").write_text("".join(n + "\n" for n in names))


def confirmed(batch):
    # Two direct answers already seen long ago: this run's answer is the third, the last needed.
    for n in batch:
        (hyst / f"{n}.state").write_text(f"HOST={n}\nDIRECT_OK_STREAK=2\nLAST_SUCCESS={int(time.time()) - 3600}\n")


subprocess.run(["mount", "-t", "proc", "proc", str(root / "proc")], check=True)
subprocess.run(["mount", "--bind", str(root / "opt"), str(root / "opt")], check=True)
try:
    confirmed(names[:5])
    reads = root / "emu/config-reads.log"
    reads.unlink(missing_ok=True)
    out = sh(root, "/opt/bin/vward-route-reconciler.sh").stdout
    first = changes(root)
    # fix.33.2 (WP-C): one look at Keenetic's configuration for the run, five removals included.
    if len(reads.read_text().splitlines()) != 1:
        fail(f"one look at the configuration a run: {reads.read_text().splitlines()}")
    removed = [c for c in first if c.startswith("no object-group fqdn AdaptiveAuto include ")]
    if len(removed) != 5:
        fail(f"five names direct again, five removals: {first} / {out[-400:]}")
    if first.count(SAVE) != 1:
        fail(f"one save for the run, not one a name: {first.count(SAVE)} saves")
    persist = (state / "adaptive-persist.txt").read_text().split()
    if any(n in persist for n in names[:5]) or persist != names[5:]:
        fail(f"the USB list keeps what was removed: {persist}")

    # Two more within the hour: removed, the save waits for the hour.
    cfg = (root / "emu/running-config").read_text()
    for n in names[:5]:
        cfg = cfg.replace(f"    include {n}\n", "")
    cfg = cfg.replace("object-group fqdn AdaptiveAuto\n", "object-group fqdn AdaptiveAuto\n" + "".join(f"    include {n}\n" for n in names[5:]))
    (root / "emu/running-config").write_text(cfg)
    (state / "maint-cursor").write_text("1\n")
    confirmed(names[5:])
    sh(root, "/opt/bin/vward-route-reconciler.sh")
    second = changes(root)[len(first):]
    if len([c for c in second if c.startswith("no object-group fqdn AdaptiveAuto include ")]) != 2:
        fail(f"two more removals expected: {second}")
    if SAVE in second:
        fail("a second save within the hour")
    if not (state / "keenetic-config.dirty").exists():
        fail("the unsaved removals are not remembered")

    # An hour later (nothing new to remove): one save for them.
    old = time.time() - 3700
    os.utime(state / "keenetic-config.saved", (old, old))
    sh(root, "/opt/bin/vward-route-reconciler.sh")
    third = changes(root)[len(first) + len(second):]
    if third.count(SAVE) != 1 or (state / "keenetic-config.dirty").exists():
        fail(f"the hour's removals are saved once: {third}")
finally:
    subprocess.run(["umount", str(root / "opt")])
    subprocess.run(["umount", str(root / "proc")])
    shutil.rmtree(tmp, ignore_errors=True)

print("ROUTE_RECONCILER_EMULATED=PASS")
