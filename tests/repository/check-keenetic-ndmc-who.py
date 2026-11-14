#!/usr/bin/env python3
"""Who asks Keenetic through ndmc (fix.39 item 30, owner's diagnostics 13.11.2026).

Every ndmc command leaves two lines in Keenetic's journal («Core::Session started/disconnected»):
2 566 of about 4 000 lines were VWARD's, the journal held only 15 hours. Before the calls are cut,
they are counted by the program that makes them:

1. the library counts every ndmc session by the hour of uptime with the program's name (25 files in
   RAM, shell built-ins only), the read of the configuration through ndmc included; with the
   timing switched off nothing is counted;
2. vward_keenetic_ndmc_json answers the programs of the last 24 hours of uptime with the counts of
   the day, of this hour and of the last full hour; names that are not a program's are dropped;
3. the router answers it in «stability» and «Диагностика» shows it.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/runtime/lib/vward-device-profile.sh"


def fail(m):
    raise SystemExit(f"KEENETIC_NDMC_WHO=FAIL: {m}")


with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    (tmp / "bin").mkdir()
    (tmp / "bin/ndmc").write_text("#!/bin/sh\necho \"answer $*\"\n")
    (tmp / "bin/ndmc").chmod(0o755)
    (tmp / "uptime").write_text("7300.50 100.00\n")  # hour 2 of uptime
    env = {"PATH": f"{tmp}/bin:/usr/bin:/bin", "VWARD_KEENETIC_SLOW_LOG": str(tmp / "slow.log"),
           "VWARD_KEENETIC_CALLS": str(tmp / "calls"), "VWARD_KEENETIC_SLOWN": str(tmp / "slown"),
           "VWARD_KEENETIC_LAST": str(tmp / "last"), "VWARD_KEENETIC_NDMC": str(tmp / "who"),
           "VWARD_RCI_CALLS": str(tmp / "rci-calls"), "VWARD_RCI_FAIL_LOG": str(tmp / "rci-fail"),
           "VWARD_RCI_BASE": "http://127.0.0.1:9/rci", "VWARD_KCACHE": str(tmp / "kc"), "VWARD_UPTIME_FILE": str(tmp / "uptime")}

    def prog(name, body, extra=None):
        p = tmp / name
        p.write_text(f'#!/bin/sh\n. "{LIB}"\n{body}\n')
        p.chmod(0o755)
        r = subprocess.run([str(p)], env=env | (extra or {}), text=True, capture_output=True, timeout=60)
        if r.returncode:
            fail(f"{name}: rc={r.returncode} {r.stderr[-300:]}")
        return r.stdout

    prog("vward-tunnel-guard.sh", 'ndmc -c "show interface" >/dev/null; ndmc -c "system configuration save" >/dev/null')
    prog("vward-route-reconciler.sh", 'ndmc -c "show ip route" >/dev/null')
    # The read of the configuration when RCI does not answer is an ndmc session too.
    prog("api.cgi", "vward_running_config >/dev/null")
    prog("vward-quiet.sh", 'ndmc -c "show version" >/dev/null', {"VWARD_KEENETIC_TIMING": "0"})
    f = tmp / "who/2"
    if not f.exists():
        fail("no file of this hour of uptime (VWARD_KEENETIC_NDMC/<hour % 25>)")
    lines = f.read_text().splitlines()
    if lines[0] != "2" or sorted(lines[1:]) != ["api.cgi", "vward-route-reconciler.sh", "vward-tunnel-guard.sh", "vward-tunnel-guard.sh"]:
        fail(f"every ndmc session with its program, the hour first: {lines}")
    # The last full hour, an hour 30 hours ago (its file is reused: dropped) and a line that is no name.
    (tmp / "uptime").write_text(f"{28 * 3600 + 5}.00 1.00\n")  # hour 28: file 3 holds hour 3 (25 hours ago)
    (tmp / "who/2").write_text("27\n" + "\n".join(lines[1:]) + "\n")
    (tmp / "who/1").write_text("26\nvward-tunnel-guard.sh\nvward-wan-guard.sh\nnot a name\n\"quote\n")
    (tmp / "who/4").write_text("3\nold.sh\n")
    (tmp / "who/5").write_text("28\nvward-wan-guard.sh\n")
    out = prog("reader.sh", "vward_keenetic_ndmc_json")
    try:
        got = {x["name"]: (x["day"], x["hour"], x["prev"]) for x in json.loads(out)}
    except (ValueError, KeyError, TypeError) as e:
        fail(f"vward_keenetic_ndmc_json must print a JSON list: {out!r} ({e})")
    want = {"vward-tunnel-guard.sh": (3, 0, 2), "vward-route-reconciler.sh": (1, 0, 1), "api.cgi": (1, 0, 1), "vward-wan-guard.sh": (2, 1, 0)}
    if got != want:
        fail(f"counts of the day, this hour and the last full hour: {got}, want {want}")
    env["VWARD_KEENETIC_NDMC"] = str(tmp / "none")
    if json.loads(prog("reader2.sh", "vward_keenetic_ndmc_json")) != []:
        fail("nothing counted yet: an empty list")

API = (ROOT / "web/cgi-bin/api.cgi").read_text(encoding="utf-8")
JS = (ROOT / "web/assets/vward-console.js").read_text(encoding="utf-8")
if "vward_keenetic_ndmc_json" not in API or "ndmc_by: $ndmc" not in API:
    fail("the router must answer the ndmc sessions by program in «stability»")
diag = JS[JS.index("  'd-diag'() {"):JS.index("  'd-stability'() {")]
if "keeneticCallsPanel()" not in diag or "function keeneticCallsPanel()" not in JS or "ndmc_by" not in JS:
    fail("«Диагностика» must show the ndmc sessions by program")
print("KEENETIC_NDMC_WHO=PASS")
