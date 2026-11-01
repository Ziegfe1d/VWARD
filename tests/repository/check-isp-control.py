#!/usr/bin/env python3
"""A failed direct check proves nothing when the direct check itself does not work (01.11.2026).

Viva 31.10-1.11: the night audit had ok 4-5 of 482, 281 timeouts through the provider, 76 both
failed (19.10: ok 90); the reconciler marked api.ozon.ru and wb.ru «broken» (ISP=000 VPN=000).
vward_isp_control checks the provider path the way site checks do (curl, WAN device, 2/3 s) on
sites that are always up. When it fails: add_adaptive sends nothing to the VPN, the reconciler
judges no name this run, the audit stops with 75 (no site judged, categories still updated).
"""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/runtime/lib/vward-runtime-admission.sh"
ENGINE = (ROOT / "components/route-engine/scripts/vward-route-engine.sh").read_text()
RECON = (ROOT / "components/route-reconciler/scripts/vward-route-reconciler.sh").read_text()
AUDIT = (ROOT / "components/policy-sync/scripts/vward-policy-audit.sh").read_text()


def fail(msg):
    raise SystemExit(f"ISP_CONTROL=FAIL: {msg}")


lib = LIB.read_text()
m = re.search(r"^vward_isp_control\(\) \{\n.*?^\}\n", lib, re.S | re.M)
if not m:
    fail("missing vward_isp_control")
fn = m.group(0)
shells = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])
for shell in shells:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "bin").mkdir()
        # curl stand-in: «up» answers 200 for the hosts listed, else a timeout (rc 28, 000).
        (t / "bin/curl").write_text('#!/bin/sh\necho "$*" >> "$T/calls"\nfor a; do u=$a; done\n'
                                    'h=${u#*://}; h=${h%%/*}\nif grep -qx "$h" "$T/up" 2>/dev/null; then printf 200; exit 0; fi\n'
                                    'printf 000; exit 28\n')
        (t / "bin/curl").chmod(0o755)

        def run(up, env_extra=None, keep=False):
            (t / "up").write_text("".join(h + "\n" for h in up))
            if not keep:
                (t / "state").unlink(missing_ok=True)
            (t / "calls").unlink(missing_ok=True)
            env = {"PATH": f"{t}/bin:/usr/bin:/bin", "T": str(t), "VWARD_WAN_DEVICE": "eth3",
                   "VWARD_ISP_CONTROL_STATE": str(t / "state")} | (env_extra or {})
            r = subprocess.run([*shell, "-c", fn + "vward_isp_control; echo rc=$?"], env=env, capture_output=True, text=True)
            calls = (t / "calls").read_text().splitlines() if (t / "calls").exists() else []
            return r.stdout.strip(), calls

        out, calls = run(["ya.ru", "vk.com"])
        if out != "rc=0" or len(calls) != 1 or "--interface eth3" not in calls[0] or "--max-time 3" not in calls[0]:
            fail(f"{shell}: the provider path works: {out} {calls}")
        out, calls = run(["vk.com"])
        if out != "rc=0" or len(calls) != 2:
            fail(f"one control site down is not the provider: {out} {calls}")
        out, calls = run([])
        if out != "rc=1" or len(calls) != 2:
            fail(f"both control sites fail through the provider: unreliable: {out}")
        out, calls = run(["ya.ru"], keep=True)
        if out != "rc=1" or calls:
            fail(f"the answer is kept for 120 s, no curl again: {out} {calls}")
        out, calls = run(["ya.ru"], {"VWARD_ISP_CONTROL_TTL": "0"}, keep=True)
        if out != "rc=0" or len(calls) != 1:
            fail(f"an old answer is checked again: {out} {calls}")
        out, calls = run([], {"VWARD_ISP_CONTROL": "0"})
        if out != "rc=0" or calls:
            fail("VWARD_ISP_CONTROL=0 turns it off")
        out, calls = run([], {"VWARD_WAN_DEVICE": ""})
        if out != "rc=2":
            fail("no WAN device: cannot tell (2), never «unreliable»")

# The deciders.
add = ENGINE[ENGINE.index("\nadd_adaptive()\n"):ENGINE.index("\nremove_adaptive()\n")]
i_ctrl, i_vpn, i_add = add.find("vward_isp_control"), add.find('probe "$H" "$WG" "$GIP"'), add.find("object-group fqdn $GROUP include $H")
if not (0 < i_ctrl < i_vpn < i_add) or "ADD_ABORT_ISP_UNRELIABLE" not in add:
    fail("add_adaptive must stop before the VPN probe and the add when the direct check is unreliable")
loop = RECON[RECON.find('while [ "$DONE" -lt "$MAX_PER_RUN" ]'):]
c, v = loop.find("vward_isp_control"), loop.find('probe "$H" "$WG" "$IP"')
if "MAINT_ISP_PROBE_UNRELIABLE" not in loop or not (0 < c < v) or "break" not in loop[c:v]:
    fail("the reconciler must stop judging names once the direct check proves unreliable")
# Lazy: only after a direct check failed (the healthy path costs no process: resource budget).
if loop.find("vward_isp_control") < loop.find('if probe "$H" "$WAN" "$IP"; then'):
    fail("the reconciler must ask the control only after a failed direct check")
a = AUDIT.find("ABORTED_ISP_PROBE_UNRELIABLE")
if a < 0 or "exit 75" not in AUDIT[a:a + 400] or AUDIT.rfind("vward_isp_control", 0, a) < AUDIT.find('ISP_RC=$?'):
    fail("the audit must stop with 75 when a failed direct check proves unreliable")
if re.search(r"vward_isp_control\(\) \{.*?\$\(date", fn, re.S):
    fail("no clock process: the control reads /proc/uptime")
print("ISP_CONTROL=PASS")
