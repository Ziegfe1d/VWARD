#!/usr/bin/env python3
"""VWARD gives way to the router.

- vward_background: a job and all it starts get the lowest CPU priority (once per job
  tree); the Panel's requests (VWARD_FOREGROUND) keep theirs; the tunnels' programs take
  the normal priority back.
- vward_busy: busy when the load of the last minute reaches the number of CPU threads or
  less than 24 MiB of memory is available (read from /proc by the shell).
- vward_defer: optional work waits while busy, at most 2 hours in a row, then runs anyway."""

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/runtime/lib/vward-runtime-admission.sh"


def fail(message: str) -> None:
    raise SystemExit(f"RESOURCE_YIELD=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    proc = tmp / "proc"; proc.mkdir()
    (proc / "cpuinfo").write_text("".join(f"processor\t\t: {i}\ncpu model\t\t: MIPS 1004Kc V2.15\n\n" for i in range(4)))
    bin_ = tmp / "bin"; bin_.mkdir()
    (bin_ / "renice").write_text(f'#!/bin/sh\necho "renice $*" >> "{tmp}/calls"\n')
    (bin_ / "renice").chmod(0o755)

    def sh(script, load="0.50 0.40 0.30 1/80 999", mem=60000, uptime=1000, env=None):
        (proc / "loadavg").write_text(load + "\n")
        (proc / "meminfo").write_text(f"MemTotal:  250000 kB\nMemFree:   20000 kB\nMemAvailable:   {mem} kB\n")
        (proc / "uptime").write_text(f"{uptime}.12 800.00\n")
        (tmp / "calls").unlink(missing_ok=True)
        r = subprocess.run(["sh", "-c", f'. "{LIB}"; {script}'], text=True, capture_output=True, timeout=30,
                           env={"PATH": f"{bin_}:/usr/bin:/bin", "VWARD_PROC": str(proc), "VWARD_DEFER_DIR": str(tmp / "defer"),
                                **(env or {})})
        calls = (tmp / "calls").read_text() if (tmp / "calls").exists() else ""
        return r.stdout.strip(), calls

    busy = 'vward_busy && echo busy || echo free'
    if sh(busy)[0] != "free":
        fail("a quiet router is not busy")
    if sh(busy, load="4.10 2.00 1.00 2/80 999")[0] != "busy":
        fail("load 4 on 4 threads is busy")
    if sh(busy, load="3.95 2.00 1.00 2/80 999")[0] != "free":
        fail("load under 4 on 4 threads is not busy")
    if sh(busy, mem=20000)[0] != "busy":
        fail("20 MiB available is busy")

    defer = 'vward_defer scan && echo wait || echo run'
    if sh(defer, mem=20000, uptime=1000)[0] != "wait" or not (tmp / "defer/scan").exists():
        fail("busy: optional work waits and the start of the wait is kept")
    if sh(defer, mem=20000, uptime=1000 + 7199)[0] != "wait":
        fail("busy under 2 hours: still waits")
    if sh(defer, mem=20000, uptime=1000 + 7200)[0] != "run" or (tmp / "defer/scan").exists():
        fail("busy 2 hours: runs anyway")
    sh(defer, mem=20000, uptime=5000)
    if sh(defer, uptime=5060)[0] != "run" or (tmp / "defer/scan").exists():
        fail("free again: runs and the wait is forgotten")

    out, calls = sh('vward_background; vward_background; echo "$VWARD_BACKGROUND"')
    lines = calls.splitlines()
    if out != "1" or len(lines) != 1 or not lines[0].startswith("renice -n 19 -p "):
        fail(f"background: lowest priority once per job: {out!r} {calls!r}")
    out, calls = sh('vward_background; echo "${VWARD_BACKGROUND:-0}"', env={"VWARD_FOREGROUND": "1"})
    if out != "0" or calls:
        fail("the Panel's requests keep their priority")
    if "    vward_background\n" not in LIB.read_text().split("vward_admission_enter() {", 1)[1][:200]:
        fail("every admitted job becomes background work")

    # CPU per component, measured on the router by the shell's own `times`.
    cpu = tmp / "cpu"
    out, _ = sh(f'VWARD_CPU_DIR="{cpu}"; for t in 0m0.020000s 1m2.345678s 0m10.09s 0m0.000s; do vward_cs $t; printf "%s " $VC_CS; done; '
                f'awk "BEGIN{{for(i=0;i<2000000;i++)x+=i}}"; vward_cpu_account tunnel-health; vward_cpu_account tunnel-health; '
                f'vward_cpu_account "../x"')
    if out.split() != ["2", "6234", "1009", "0"]:
        fail(f"times to centiseconds: {out}")
    runs, cs = (cpu / "tunnel-health").read_text().split()
    if runs != "2" or not cs.isdigit() or [p.name for p in cpu.iterdir() if not p.name.startswith(".")] != ["tunnel-health"]:
        fail(f"per component: runs and centiseconds, a bad name ignored: {runs} {cs}")
    if "vward_cpu_account \"${VWARD_ADMISSION_COMPONENT:-}\"" not in LIB.read_text().split("vward_admission_leave() {", 1)[1][:200]:
        fail("every admitted job is accounted when it leaves")

# fix.33.2 (WP-C): Keenetic's last answer of 2 s or more within 90 s is «busy» too (the device
# library writes when and how long; no answer counts as 2 s); a job crond started waits its
# seconds, one started by hand or by the Panel does not.
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    proc = tmp / "proc"; proc.mkdir()
    (proc / "cpuinfo").write_text("processor\t: 0\nprocessor\t: 1\nprocessor\t: 2\nprocessor\t: 3\n")
    (proc / "loadavg").write_text("0.50 0.40 0.30 1/80 999\n")
    (proc / "meminfo").write_text("MemAvailable:   60000 kB\n")
    (proc / "uptime").write_text("1000.12 800.00\n")
    last = tmp / "last"
    env = {"PATH": "/usr/bin:/bin", "VWARD_PROC": str(proc), "VWARD_DEFER_DIR": str(tmp / "defer"), "VWARD_KEENETIC_LAST": str(last)}
    busy = lambda: subprocess.run(["sh", "-c", f'. "{LIB}"; vward_keenetic_busy && echo k; vward_busy && echo b'], env=env, text=True, capture_output=True).stdout.split()
    for text, want in (("", []), ("990 350", ["k", "b"]), ("990 150", []), ("900 350", []), ("x y", [])):
        last.write_text(text + "\n") if text else last.unlink(missing_ok=True)
        if busy() != want:
            fail(f"Keenetic busy by its last answer {text!r}: {busy()} != {want}")
    prof = ROOT / "components/runtime/lib/vward-device-profile.sh"
    for args, want in (("running-config 99500", "1000 512"), ("rci:x 99990 rc=28", "1000 200"), ("rci:x 70000", "1000 30012")):
        subprocess.run(["sh", "-c", f'. "{prof}"; vward_keenetic_timed {args}'], env=env | {"VWARD_UPTIME_FILE": str(proc / "uptime"),
                       "VWARD_KEENETIC_SLOW_LOG": str(tmp / "slow.log"), "VWARD_KEENETIC_CALLS": str(tmp / "c"), "VWARD_KEENETIC_SLOWN": str(tmp / "s")}, check=True)
        if last.read_text().strip() != want:
            fail(f"the last request {args}: {last.read_text().strip()!r} != {want!r}")
    # A parent chain with crond two levels up: the job sleeps (sleep is a stand-in that notes it).
    (tmp / "bin").mkdir()
    (tmp / "bin/sleep").write_text(f'#!/bin/sh\necho "slept $1" >> "{tmp}/slept"\n'); (tmp / "bin/sleep").chmod(0o755)
    def spread(parent_comm):
        (tmp / "slept").unlink(missing_ok=True)
        script = f'. "{LIB}"; p=$PPID; mkdir -p "{proc}/$p" "{proc}/7"; echo "$p (sh) S 7 1" > "{proc}/$p/stat"; echo "7 ({parent_comm}) S 1 1" > "{proc}/7/stat"; vward_spread 35'
        subprocess.run(["sh", "-c", f"sh -c '{script}'; true"], env=env | {"PATH": f"{tmp}/bin:/usr/bin:/bin"}, check=True)
        return (tmp / "slept").read_text().strip() if (tmp / "slept").exists() else ""
    if spread("crond") != "slept 35" or spread("lighttpd") != "":
        fail(f"a cron job waits its seconds, another does not: {spread('crond')!r} {spread('lighttpd')!r}")

api = (ROOT / "web/cgi-bin/api.cgi").read_text()
if "VWARD_FOREGROUND=1\nexport VWARD_FOREGROUND" not in api:
    fail("the API marks its requests as foreground")
for engine in ("vward-awg-engine.sh", "vward-vless-engine.sh"):
    src = (ROOT / "components/tunnel-guard/scripts" / engine).read_text()
    if '[ "${VWARD_BACKGROUND:-0}" != 1 ] || VWARD_TUNNEL_NICE="nice -n -19"' not in src or 'exec $VWARD_TUNNEL_NICE "$BIN"' not in src:
        fail(f"{engine}: the tunnel takes the normal priority back")
for rel, name in (("components/route-tools/scripts/vward-route-hints-update.sh", "route-hints-update"),
                  ("components/policy-sync/scripts/vward-policy-chain.sh", "policy-chain")):
    src = (ROOT / rel).read_text()
    if f"while vward_defer {name}; do sleep 60; done" not in src or src.index("vward_defer " + name) > src.index("vward_admission_enter"):
        fail(f"{rel}: daily work waits for a busy router before its admission slot")
if "! vward_defer tunnel-speed" not in (ROOT / "components/tunnel-guard/scripts/vward-tunnel-quality.sh").read_text():
    fail("the speed test waits for a busy router")
print("RESOURCE_YIELD=PASS")
