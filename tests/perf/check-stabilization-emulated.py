#!/usr/bin/env python3
"""fix.33.2 on the router emulator: the cases of the owner's router (2026-10-24), fake ndmc, curl
and ping, nothing on a real router. Needs root (chroot, mount).

1. Keenetic's RCI silent while the internet works (99 «UTILITY_DEGRADED» in 17 hours): the WAN
   guard keeps its state and journals the episode once; the slow answers are in «who waited»
   with the agent; the route upkeep waits while Keenetic is busy. RCI silent and no internet:
   UTILITY_DEGRADED as before. RCI back: the episode's misses in one line.
2. The peaks: the route upkeep (every 5 minutes) together with the network agent and the route
   engine's watchdog (S91), Keenetic answering the configuration in 4 s: one read of the whole
   configuration for all of them.
3. The route engine ends: TERM (its lock goes with it: the watchdog's «lock_mismatch», the
   real case), kill -9 (no word: last_stop=none), a stop asked (who asked).
The AdGuard Home restart (no DNS_ORPHAN_OUT) and «Последняя проверка» are checked by
tests/repository/check-ads-dns-guard.py and check-stability-page.py.
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
EVENTS = "opt/var/log/vward-route-engine-events.log"


def fail(message):
    raise SystemExit(f"STABILIZATION_EMULATED=FAIL: {message}")


def sh(root, command, timeout=120, background=False):
    cmd = ["env", "-i", f"PATH={PATH_ENV}", "HOME=/root", "chroot", str(root), "/bin/sh", "-c", command]
    if background:
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout).stdout


def read(path):
    return path.read_text() if path.exists() else ""


if os.geteuid() != 0:
    sys.exit("check-stabilization-emulated: needs root")

tmp = Path(tempfile.mkdtemp(prefix="vward-stab."))
root = tmp / "root"
subprocess.run([str(REPO / "tests/perf/emulator/build-rootfs.sh"), str(root)], check=True, stdout=subprocess.DEVNULL)
(root / "opt/var/run/vward").mkdir(parents=True, exist_ok=True)
emu = root / "emu"
subprocess.run(["mount", "-t", "proc", "proc", str(root / "proc")], check=True)
subprocess.run(["mount", "--bind", str(root / "opt"), str(root / "opt")], check=True)
try:
    up = float(Path("/proc/uptime").read_text().split()[0])
    if up < 200:
        time.sleep(200 - up)  # the WAN guard's boot grace (180 s) is read from the host's uptime

    # 1. RCI silent, the internet up.
    wan_log = root / "opt/var/log/vward-wan-guard.log"
    out = sh(root, "/opt/bin/vward-wan-guard.sh")
    if "CLASS=HEALTHY" not in out:
        fail(f"a healthy start: {out[-300:]}")
    (emu / "fault-rci-slow").write_text("1\n")
    out = sh(root, "/opt/bin/vward-wan-guard.sh; /opt/bin/vward-wan-guard.sh")
    if out.count("CLASS=HEALTHY") != 2 or "UTILITY_DEGRADED" in out or "UTILITY_DEGRADED" in read(wan_log):
        fail(f"RCI silent with the internet up must keep the state: {out[-400:]} / {read(wan_log)[-300:]}")
    if read(wan_log).count("rci_unavailable reason=isp_rci_unavailable probes=ok") != 1:
        fail(f"one journal line an episode: {read(wan_log)[-400:]}")
    slow = read(root / "opt/var/log/vward/keenetic-slow.log")
    if "|network-agent|vward-wan-guard.sh|rci:show/interface" not in slow:
        fail(f"the silent RCI in «who waited» with the agent: {slow[-300:]}")
    out = sh(root, "/opt/bin/vward-route-reconciler.sh")
    if "Deferred" not in out:
        fail(f"the route upkeep waits while Keenetic is busy: {out[-300:]}")
    (emu / "fault-wan").write_text("1\n")
    out = sh(root, "/opt/bin/vward-wan-guard.sh")
    if "CLASS=UTILITY_DEGRADED" not in out or "probes=fail" not in read(wan_log):
        fail(f"RCI silent and no internet: UTILITY_DEGRADED as before: {out[-300:]}")
    (emu / "fault-wan").unlink(); (emu / "fault-rci-slow").unlink()
    sh(root, "/opt/bin/vward-wan-guard.sh")
    if "rci_back misses=2" not in read(wan_log):
        fail(f"RCI back: the misses of the episode: {read(wan_log)[-300:]}")

    # 2. The peaks: the upkeep, the network agent and S91 at once, the configuration in 4 s.
    # The engine runs already (its start reads the configuration fresh: it restores AdaptiveAuto).
    sh(root, "/opt/etc/init.d/S91vward-route-engine start")
    reads = emu / "config-reads.log"
    sh(root, "rm -f /tmp/vward-keenetic/running-config /tmp/vward-keenetic-last /tmp/vward-defer/route-reconciler")
    reads.unlink(missing_ok=True)
    (emu / "fault-ndmc-slow").write_text("4\n")
    jobs = ["/opt/bin/vward-route-reconciler.sh", "/opt/bin/vward-tunnel-health.sh && /opt/bin/vward-tunnel-guard.sh",
            "/opt/bin/vward-wan-guard.sh", "/opt/etc/init.d/S91vward-route-engine start"]
    procs = [sh(root, j, background=True) for j in jobs]
    for p in procs:
        p.communicate(timeout=180)
    (emu / "fault-ndmc-slow").unlink()
    got = read(reads).splitlines()
    if len(got) > 1:
        fail(f"one read of the configuration for the peak, not one an agent: {got}")
    slow = read(root / "opt/var/log/vward/keenetic-slow.log")
    if "|running-config|4." not in slow and "|running-config|5." not in slow:
        fail(f"the slow read in «who waited»: {slow[-400:]}")

    # 3. The route engine ends.
    events = root / EVENTS

    def engine_pid():
        return read(root / "opt/var/run/vward/route-engine.pid").strip()

    sh(root, "/opt/etc/init.d/S91vward-route-engine start")
    pid = engine_pid()
    if not pid:
        fail("the route engine did not start")
    os.kill(int(pid), 15)
    for _ in range(50):
        if "|STOP|reason=TERM|rc=143|" in read(events):
            break
        time.sleep(0.2)
    else:
        fail(f"TERM: the STOP line with the reason: {read(events)[-400:]}")
    sh(root, "/opt/etc/init.d/S91vward-route-engine start")
    if "|WATCHDOG_RESTART|reason=lock_mismatch|last_stop=TERM/rc=143" not in read(events):
        fail(f"the watchdog names how the engine ended: {read(events)[-400:]}")
    pid = engine_pid()
    os.kill(int(pid), 9)
    time.sleep(0.5)
    sh(root, "/opt/etc/init.d/S91vward-route-engine start")
    # core_dead, or cores=0 while the killed process waits to be reaped: either way no STOP line.
    if not re.search(r"\|WATCHDOG_RESTART\|reason=(core_dead|cores=0)\|last_stop=none", read(events)):
        fail(f"kill -9: no STOP line, «none»: {[l for l in read(events).splitlines() if 'WATCHDOG' in l or 'STOP' in l or 'START' in l][-6:]}")
    sh(root, "/opt/etc/init.d/S91vward-route-engine stop")
    if "|STOP_REQUEST|cmd=stop|by=" not in read(events):
        fail(f"a stop asked: who asked: {read(events)[-300:]}")
finally:
    sh(root, "/opt/etc/init.d/S91vward-route-engine stop")
    subprocess.run(["umount", str(root / "opt")])
    subprocess.run(["umount", str(root / "proc")])
    shutil.rmtree(tmp, ignore_errors=True)

print("STABILIZATION_EMULATED=PASS")
