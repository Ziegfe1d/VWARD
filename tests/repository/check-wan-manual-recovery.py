#!/usr/bin/env python3
"""Manual WAN recovery tool: renew, reconnect, shared lock, ownership marker, signals."""

import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "components/wan-guard/scripts/vward-wan-recovery.sh"
GUARD = ROOT / "components/wan-guard/scripts/vward-wan-guard.sh"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


source = TOOL.read_text()
if '"ISP"' in source or "IFACE=" in source or "EXECUTED=NO" in source:
    fail("the manual tool must use the profile interface and really execute")

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / "root/tmp").mkdir(parents=True)
    profile = tmp / "profile.sh"
    profile.write_text("vward_profile_load(){ VWARD_WAN_INTERFACE=Uplink7; }\n")
    ndmc = tmp / "ndmc"
    ndmc.write_text(f"""#!/bin/sh
echo "$2" >> "{tmp}/calls"
case "$2" in
  *" down") [ -e "{tmp}/fail-down" ] && exit 1 ;;
  *" up") [ -e "{tmp}/fail-up" ] && exit 1 ;;
esac
exit 0
""")
    ndmc.chmod(0o755)
    rec = tmp / "rec"; marker = rec / "owned-down"; lock = tmp / "lock.d"
    env = os.environ | {
        "VWARD_PROFILE_LIB": str(profile), "NDMC": str(ndmc), "VWARD_ROOT_PREFIX": str(tmp / "root"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
        "VWARD_WAN_GUARD_LOCK": str(lock), "VWARD_WAN_RECOVERY_DIR": str(rec),
        "VWARD_WAN_RECOVERY_LOG": str(tmp / "recovery.log"), "VWARD_WAN_MANUAL_COOLDOWN": "0",
        "VWARD_WAN_BOUNCE_WAIT": "0",
    }

    def calls():
        f = tmp / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def run(request, expect, rc, **extra):
        (tmp / "calls").unlink(missing_ok=True)
        r = subprocess.run(["sh", str(TOOL), request], env=env | extra, text=True, capture_output=True)
        if expect not in r.stdout.splitlines() or r.returncode != rc:
            fail(f"{request}: rc={r.returncode} out={r.stdout!r} err={r.stderr!r}, expected {expect} rc={rc}")
        if lock.exists():
            fail(f"{request}: lock left behind")
        return calls()

    run("reboot", "ERROR=INVALID_REQUEST", 64)
    if calls():
        fail("an invalid request must not reach the router")

    if run("dhcp-renew", "RESULT=DONE", 0) != ["interface Uplink7 ip dhcp client renew"]:
        fail("renew must use the profile interface")
    if run("wan-bounce", "RESULT=DONE", 0) != ["interface Uplink7 down", "interface Uplink7 up"] or marker.exists():
        fail("bounce must take the interface down and up and clear its marker")

    (tmp / "fail-down").touch()
    if run("wan-bounce", "ERROR=DOWN_FAILED", 1) != ["interface Uplink7 down"] or marker.exists():
        fail("a rejected down must not be followed by up or leave a marker")
    (tmp / "fail-down").unlink()

    (tmp / "fail-up").touch()
    run("wan-bounce", "ERROR=UP_FAILED", 1)
    if marker.read_text().strip() != "Uplink7":
        fail("a bounce that did not come back must keep the marker for WAN Guard")
    run("dhcp-renew", "ERROR=INCOMPLETE_BOUNCE", 1)
    (tmp / "fail-up").unlink()
    if run("dhcp-renew", "RESULT=DONE", 0) != ["interface Uplink7 up", "interface Uplink7 ip dhcp client renew"] or marker.exists():
        fail("an unfinished bounce must be completed before anything else")

    # Cooldown between manual actions.
    run("dhcp-renew", "ERROR=COOLDOWN", 75, VWARD_WAN_MANUAL_COOLDOWN="60")

    # The lock is shared with WAN Guard: a live guard run blocks, a dead one is reclaimed.
    holder = subprocess.Popen(["sh", "-c", "sleep 30", "vward-wan-guard.sh"])
    try:
        lock.mkdir(); (lock / "pid").write_text(f"{holder.pid}\n")
        r = subprocess.run(["sh", str(TOOL), "dhcp-renew"], env=env, text=True, capture_output=True)
        if "ERROR=BUSY" not in r.stdout or r.returncode != 75 or not lock.exists():
            fail("a running WAN Guard must block manual actions and keep its lock")
    finally:
        holder.kill(); holder.wait()
    run("dhcp-renew", "RESULT=DONE", 0)

    # WAN Guard recognises the manual tool as a live lock owner.
    fn = subprocess.run(["sed", "-n", "/^lock_is_live()/,/^}/p", str(GUARD)], text=True, capture_output=True).stdout
    holder = subprocess.Popen(["sh", "-c", "sleep 30", "vward-wan-recovery.sh"])
    try:
        lock.mkdir(); (lock / "pid").write_text(f"{holder.pid}\n")
        r = subprocess.run(["sh", "-c", fn + f'\nLOCKDIR="{lock}"; lock_is_live'])
        if r.returncode != 0:
            fail("WAN Guard must not steal the lock from the manual tool")
    finally:
        holder.kill(); holder.wait()
        (lock / "pid").unlink(); lock.rmdir()

    # TERM while the interface is down: it is brought back up.
    (tmp / "calls").unlink(missing_ok=True)
    p = subprocess.Popen(["sh", str(TOOL), "wan-bounce"], env=env | {"VWARD_WAN_BOUNCE_WAIT": "2"}, text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.05)
    p.send_signal(signal.SIGTERM)
    out, _ = p.communicate(timeout=20)
    if "ERROR=INTERRUPTED" not in out or calls()[-1] != "interface Uplink7 up" or marker.exists():
        fail(f"TERM during a bounce must restore the interface: {out!r} {calls()}")

    # An update in progress blocks manual actions.
    (tmp / "root/tmp/vward-update-requested").write_text("x")
    run("dhcp-renew", "ERROR=UPDATER_BUSY", 75)
    (tmp / "root/tmp/vward-update-requested").unlink()

    log = (tmp / "recovery.log").read_text()
    for action in ("MANUAL_DHCP_RENEW", "MANUAL_WAN_BOUNCE", "MANUAL_BOUNCE_RECOVERY", "MANUAL_WAN_BOUNCE_INTERRUPTED"):
        if f"action={action} interface=Uplink7" not in log:
            fail(f"recovery log misses {action}")

print("WAN_MANUAL_RECOVERY=PASS")
