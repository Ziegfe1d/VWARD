#!/usr/bin/env python3
"""Route engine on the router emulator, end to end.

A captured DNS stream goes through the real engine started by its init script:
  * a reachable site ends DIRECT_OK with its state in RAM, not on USB;
  * a site blocked by the ISP but reachable through the tunnel is added to
    AdaptiveAuto on the router and its state is kept on USB;
  * a name repeated within the dedup window is handled and logged once;
  * a name of a manual Keenetic group is left alone;
  * stopping the engine leaves no capture processes behind.
Needs root (chroot, mknod, mount).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PATH_ENV = "/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
DAEMONS = re.compile(r"^\s*(\d+) (/bin/sh /opt/bin/vward-route-engine\.sh|tcpdump -ni |awk -v window=)")


def fail(message):
    raise SystemExit(f"FAIL: {message}")


def sh(root, command):
    return subprocess.run(["env", "-i", f"PATH={PATH_ENV}", "HOME=/root", "VWARD_EMU_DNS_INTERVAL=1",
                           "chroot", str(root), "/bin/sh", "-c", command],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)


def daemons():
    out = subprocess.run(["ps", "-eo", "pid,args"], stdout=subprocess.PIPE, text=True).stdout
    return [int(m.group(1)) for m in (DAEMONS.match(l) for l in out.splitlines()) if m]


def state(path):
    return dict(l.split("=", 1) for l in path.read_text().splitlines() if "=" in l) if path.exists() else {}


if os.geteuid() != 0:
    sys.exit("check-route-engine-emulated: needs root")

tmp = Path(tempfile.mkdtemp(prefix="vward-engine."))
root = tmp / "root"
subprocess.run([str(REPO / "tests/perf/emulator/build-rootfs.sh"), str(root)], check=True, stdout=subprocess.DEVNULL)
(root / "emu/dns-queries").write_text("direct-one.example\nblocked-site.example\ndirect-one.example\nyoutube.com\ndirect-one.example\n")
(root / "emu/blocked-direct").write_text("blocked-site.example\n")
(root / "opt/var/run/vward").mkdir(parents=True, exist_ok=True)
subprocess.run(["mount", "-t", "proc", "proc", str(root / "proc")], check=True)
subprocess.run(["mount", "--bind", str(root / "opt"), str(root / "opt")], check=True)
try:
    out = sh(root, "/opt/etc/init.d/S91vward-route-engine start").stdout
    if "started" not in out:
        fail(f"engine did not start: {out.strip()}")
    # The five names repeat every five seconds; the dedup window is 30 seconds.
    deadline = time.time() + 25
    opt_state = root / "opt/var/lib/vward/route-engine"
    ram_state = root / "tmp/vward-route-engine-state"
    while time.time() < deadline:
        if state(opt_state / "blocked-site.example.state").get("STATUS") == "AUTO_VPN" and \
           state(ram_state / "direct-one.example.state").get("STATUS") == "DIRECT_OK":
            break
        time.sleep(1)
    time.sleep(6)  # a few more rounds of repeats inside the window

    direct = state(ram_state / "direct-one.example.state")
    if direct.get("STATUS") != "DIRECT_OK":
        fail(f"direct site state in RAM: {direct}")
    if (opt_state / "direct-one.example.state").exists():
        fail("direct site state written to USB")
    blocked = state(opt_state / "blocked-site.example.state")
    if blocked.get("STATUS") != "AUTO_VPN":
        fail(f"blocked site state on USB: {blocked}")
    if (ram_state / "blocked-site.example.state").exists():
        fail("adaptive decision left a RAM copy")
    changes = (root / "emu/ndmc-changes.log").read_text() if (root / "emu/ndmc-changes.log").exists() else ""
    if "object-group fqdn AdaptiveAuto include blocked-site.example" not in changes:
        fail(f"blocked site not added to AdaptiveAuto: {changes!r}")
    if "direct-one.example" in changes or "youtube.com" in changes:
        fail(f"unexpected router change: {changes!r}")
    events = (root / "opt/var/log/vward-route-engine-events.log").read_text()
    if events.count("|direct-one.example|") != 1:
        fail(f"direct site should be checked and logged once:\n{events}")
    if (ram_state / "youtube.com.state").exists() or (opt_state / "youtube.com.state").exists():
        fail("manual group name was checked")

    sh(root, "/opt/etc/init.d/S91vward-route-engine stop")
    time.sleep(1)
    left = daemons()
    if left:
        fail(f"processes left after stop: {left}")
finally:
    for pid in daemons():
        try:
            os.kill(pid, 9)
        except OSError:
            pass
    time.sleep(0.5)
    subprocess.run(["umount", str(root / "opt")])
    subprocess.run(["umount", str(root / "proc")])
    shutil.rmtree(tmp, ignore_errors=True)

print("ROUTE_ENGINE_EMULATED=PASS")
