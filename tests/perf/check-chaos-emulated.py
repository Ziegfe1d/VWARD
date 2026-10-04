#!/usr/bin/env python3
"""Chaos run on the router emulator: VWARD's minute jobs under faults, minute by minute.

The emulated clock moves one minute a round (a stand-in for date in /opt/bin); each round
runs what cron runs every minute (route engine watchdog, tunnel health + guard, runtime
watchdog, WAN guard, ads scheduler with the DNS guard) and every five minutes (route
reconciler, Wi-Fi scheduler). Faults are flags the fake router tools read:

  wan            no internet (pings, sites, Keenetic's internet status)
  tunnel         the VPN server is silent (old handshake, nothing through nwg1)
  wan-flap       the internet comes and goes every minute
  dns            the router's DNS does not answer
  ndmc-refuse    Keenetic refuses every change
  ndmc-slow      every Keenetic command takes 8 s
  agh            AdGuard Home does not answer (agh-down: its port closed too; agh-loop: a new
                 process every minute); agh-blip: silent for two minutes only
  kill           a job killed with SIGKILL in the middle, every round
  twice          every job started twice at the same time

What must hold, under each fault and after it:
  * no job hangs (60 s) or dies of a shell error (syntax, «not found», bad number);
  * no change to Keenetic repeats without end (the same command more than 6 times in a
    scenario is a loop);
  * a lock left by a job that is gone is taken over by the next round (the job runs on);
  * after the fault the guards come back: the tunnel guard is not in fail-open, the route
    engine runs.
Needs root (chroot, mknod, mount).
  check-chaos-emulated.py [--scenario NAME] [--report FILE]
"""
import argparse
import collections
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PATH_ENV = "/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin"

MINUTE_JOBS = [
    ("route-engine watchdog", "/opt/etc/init.d/S91vward-route-engine start"),
    ("tunnel health", "/opt/bin/vward-tunnel-health.sh"),
    ("tunnel guard", "/opt/bin/vward-tunnel-guard.sh"),
    ("runtime watchdog", "/opt/etc/init.d/S92vward-runtime start"),
    ("WAN guard", "/opt/bin/vward-wan-guard.sh"),
    ("ads scheduler", "/opt/bin/vward-ads-privacy-scheduler.sh"),
]
FIVE_JOBS = [
    ("route reconciler", "/opt/bin/vward-route-reconciler.sh"),
    ("Wi-Fi scheduler", "/opt/bin/vward-wifi-client-scheduler.sh"),
]

# (name, minutes with the fault, minutes after it, fault flags)
SCENARIOS = [
    ("healthy", 0, 4, []),
    ("wan", 6, 6, ["wan"]),
    ("tunnel", 8, 8, ["tunnel"]),
    ("wan-flap", 8, 6, ["wan-flap"]),
    ("dns", 4, 4, ["dns"]),
    ("ndmc-refuse", 6, 6, ["ndmc-refuse", "tunnel"]),
    ("ndmc-slow", 3, 4, ["ndmc-slow"]),
    ("kill", 4, 4, ["kill"]),
    ("twice", 3, 3, ["twice"]),
    ("agh-silent", 5, 5, ["agh"]),
    ("agh-blip", 2, 4, ["agh"]),
    ("agh-loop", 6, 8, ["agh-loop"]),
    ("agh-down", 5, 5, ["agh", "agh-down"]),
]

SHELL_ERRORS = re.compile(r"syntax error|unexpected|not found|bad number|integer expression|"
                          r"arithmetic|Segmentation|Illegal|can't open|Permission denied|parameter not set", re.I)
# Fake tools and expected messages that look like errors but are not VWARD's.
SHELL_OK = re.compile(r"curl: \(28\)|no servers could be reached|/emu/|Command::Base error")
JOB_TIMEOUT = 60
LOOP_LIMIT = 6


def sh(root, command, timeout=JOB_TIMEOUT, background=False):
    cmd = ["env", "-i", f"PATH={PATH_ENV}", "HOME=/root", "VWARD_EMU_DNS_INTERVAL=1",
           "chroot", str(root), "/bin/sh", "-c", command]
    if background:
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    t0 = time.time()
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        return r.returncode, r.stdout, time.time() - t0
    except subprocess.TimeoutExpired as e:
        return "timeout", (e.stdout or "") if isinstance(e.stdout, str) else "", time.time() - t0


def build(tmp):
    root = tmp / "root"
    subprocess.run([str(REPO / "tests/perf/emulator/build-rootfs.sh"), str(root)], check=True, stdout=subprocess.DEVNULL)
    # The clock moves a minute a round: date answers with the emulated time.
    (root / "emu/clock-offset").write_text("0\n")
    date = root / "opt/bin/date"
    date.write_text('#!/bin/sh\n'
                    'case " $* " in *" -d "*|*" -r "*|*" -s "*|*" -u -d "*) exec /bin/busybox date "$@" ;; esac\n'
                    'o=$(cat /emu/clock-offset 2>/dev/null); case "$o" in ""|*[!0-9]*) o=0 ;; esac\n'
                    'exec /bin/busybox date -d "@$(( $(/bin/busybox date +%s) + o ))" "$@"\n')
    date.chmod(0o755)
    (root / "opt/var/run/vward").mkdir(parents=True, exist_ok=True)
    # AdGuard Home in the DNS chain: its settings, Keenetic handing it the queries, and
    # stand-ins for what the DNS guard asks (its port open, its answers, its process id).
    agh = root / "opt/etc/AdGuardHome"; agh.mkdir(parents=True, exist_ok=True)
    (agh / "AdGuardHome.yaml").write_text("dns:\n  bind_hosts:\n    - 192.0.2.1\n  port: 65053\n  upstream_dns:\n    - 9.9.9.10\n")
    rc = root / "emu/running-config"
    rc.write_text("ip name-server 192.0.2.1:65053\n" + rc.read_text())
    (root / "emu/agh-pid").write_text("4321\n")
    for name, body in (
        ("netstat", '#!/bin/sh\n[ -e /emu/fault-agh-down ] || echo "udp 0 0 192.0.2.1:65053 0.0.0.0:* 4321/AdGuardHome"\n'
                    'echo "udp 0 0 0.0.0.0:53 0.0.0.0:* 1/ndnproxy"\n'),
        ("pidof", '#!/bin/sh\n[ "$1" = AdGuardHome ] && { [ -s /emu/agh-pid ] && cat /emu/agh-pid && exit 0; exit 1; }\nexec /bin/busybox pidof "$@"\n'),
    ):
        f = root / "opt/bin" / name; f.write_text(body); f.chmod(0o755)
    ns = root / "opt/bin/nslookup"
    ns.write_text(ns.read_text().replace("#!/bin/sh\n", '#!/bin/sh\ncase "$2" in *:65053) [ ! -e /emu/fault-agh ] || { echo ";; connection timed out; no servers could be reached"; exit 1; } ;; esac\n'
                                         '[ ! -e /emu/fault-wan ] || { echo ";; connection timed out; no servers could be reached"; exit 1; }\n', 1))
    nd = root / "bin/ndmc"
    nd.write_text(nd.read_text().replace("    show*) : ;;", "    'show ip name-server') printf '  address: 192.0.2.1\\n     port: 65053\\n  address: 198.51.100.53\\n' ;;\n"
                  "    show*) : ;;\n"
                  "    'no ip name-server '*) printf '%s\\n' \"$cmd\" >> /emu/ndmc-changes.log; grep -vx \"ip name-server ${cmd#no ip name-server }\" /emu/running-config > /emu/rc.n; cat /emu/rc.n > /emu/running-config ;;\n"
                  "    'ip name-server '*) printf '%s\\n' \"$cmd\" >> /emu/ndmc-changes.log; { echo \"$cmd\"; cat /emu/running-config; } > /emu/rc.n; cat /emu/rc.n > /emu/running-config ;;", 1))
    subprocess.run(["mount", "-t", "proc", "proc", str(root / "proc")], check=True)
    subprocess.run(["mount", "--bind", str(root / "opt"), str(root / "opt")], check=True)
    return root


def set_faults(root, flags, minute):
    emu = root / "emu"
    for f in ("wan", "tunnel", "dns", "ndmc-refuse", "ndmc-slow", "agh", "agh-down"):
        (emu / f"fault-{f}").unlink(missing_ok=True)
    on = set(flags)
    if "wan-flap" in on and minute % 2 == 0:
        on.add("wan")
    for f in on & {"wan", "tunnel", "dns", "ndmc-refuse", "agh", "agh-down"}:
        (emu / f"fault-{f}").write_text("1\n")
    # AdGuard Home restarting in a loop: a new process every minute.
    if "agh-loop" in on:
        (emu / "agh-pid").write_text(f"{5000 + minute}\n")
    if "ndmc-slow" in on:
        (emu / "fault-ndmc-slow").write_text("8\n")
    internet = "wan" not in on
    (emu / "rci-internet.json").write_text(json.dumps({"gateway": {"address": "203.0.113.1"}, "gateway-accessible": internet,
                                                       "dns-accessible": internet, "internet": internet, "reliable": internet}))


def advance(root, seconds=60):
    f = root / "emu/clock-offset"
    f.write_text(f"{int(f.read_text().strip() or 0) + seconds}\n")


def stale_locks(root):
    """Lock folders whose pid file names a process that is gone."""
    out = []
    for base in (root / "tmp", root / "opt/var/run/vward"):
        if not base.exists():
            continue
        for d in base.glob("*.lock"):
            pid_f = d / "pid"
            if d.is_dir() and pid_f.exists():
                pid = pid_f.read_text().strip()
                if pid.isdigit() and not Path(f"/proc/{pid}").exists():
                    out.append(f"{d.relative_to(root)} pid {pid}")
    return out


def ndmc_changes(root):
    f = root / "emu/ndmc-changes.log"
    return f.read_text().splitlines() if f.exists() else []


def run_round(root, minute, flags, findings, scenario):
    jobs = list(MINUTE_JOBS) + (list(FIVE_JOBS) if minute % 5 == 0 else [])
    for name, cmd in jobs:
        if "kill" in flags and name in ("tunnel guard", "WAN guard", "ads scheduler", "tunnel health", "route-engine watchdog"):
            p = sh(root, cmd, background=True)
            time.sleep(0.05 + (minute % 4) * 0.07)
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()
            continue
        if "twice" in flags:
            a, b = sh(root, cmd, background=True), sh(root, cmd, background=True)
            for p in (a, b):
                try:
                    out, _ = p.communicate(timeout=JOB_TIMEOUT)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL); p.communicate()
                    findings.append((scenario, minute, name, "hang (twice)", ""))
                    continue
                check_output(out, scenario, minute, name, findings)
            continue
        rc, out, took = sh(root, cmd)
        if rc == "timeout":
            findings.append((scenario, minute, name, f"hang over {JOB_TIMEOUT} s", ""))
        check_output(out, scenario, minute, name, findings)


def check_output(out, scenario, minute, name, findings):
    for line in (out or "").splitlines():
        if SHELL_ERRORS.search(line) and not SHELL_OK.search(line):
            findings.append((scenario, minute, name, "shell error", line.strip()[:200]))


def guard_state(root):
    f = root / "opt/var/lib/vward/tunnel-guard/state"
    if not f.exists():
        for alt in root.glob("opt/**/tunnel-guard*/state"):
            f = alt
            break
    return dict(l.split("=", 1) for l in f.read_text().splitlines() if "=" in l) if f.exists() else {}


def engine_running(root):
    rc, out, _ = sh(root, "/opt/etc/init.d/S91vward-route-engine status", timeout=30)
    return "RUNNING" in out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", action="append")
    ap.add_argument("--report")
    args = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit("check-chaos-emulated: needs root")
    tmp = Path(tempfile.mkdtemp(prefix="vward-chaos."))
    root = build(tmp)
    findings, summary = [], []
    try:
        sh(root, "/opt/etc/init.d/S91vward-route-engine start")
        minute = 0
        for name, bad, after, flags in SCENARIOS:
            if args.scenario and name not in args.scenario:
                continue
            # Each scenario starts with AdGuard Home in the chain and a fresh chain state.
            rc = root / "emu/running-config"
            if "ip name-server 192.0.2.1:65053" not in rc.read_text().splitlines():
                rc.write_text("ip name-server 192.0.2.1:65053\n" + rc.read_text())
            shutil.rmtree(root / "tmp/vward-dns-chain", ignore_errors=True)
            before = len(ndmc_changes(root))
            refused_f = root / "emu/ndmc-refused.log"
            refused_before = len(refused_f.read_text().splitlines()) if refused_f.exists() else 0
            t0 = time.time()
            prev_stale = []
            for i in range(bad + after):
                minute += 1
                advance(root)
                active = flags if i < bad else []
                set_faults(root, active, minute)
                run_round(root, minute, active, findings, name)
                # A job killed with SIGKILL leaves its lock (no trap runs); the next round must
                # take it over: a lock of a gone process still there a round later is a finding.
                now_stale = stale_locks(root)
                for lock in now_stale:
                    if lock in prev_stale:
                        findings.append((name, minute, "-", "stale lock", lock))
                prev_stale = now_stale
            changes = ndmc_changes(root)[before:]
            refused = (refused_f.read_text().splitlines() if refused_f.exists() else [])[refused_before:]
            counts = collections.Counter(c for c in changes + refused if c != "system configuration save")
            for cmd, n in counts.items():
                if n > LOOP_LIMIT:
                    findings.append((name, minute, "-", f"loop: {n} times", cmd[:160]))
            chain_in = "ip name-server 192.0.2.1:65053" in (root / "emu/running-config").read_text().splitlines()
            if not chain_in:
                findings.append((name, minute, "-", "not recovered", "AdGuard Home not back in the DNS chain"))
            if name in ("agh-blip", "wan", "wan-flap") and any(c.startswith("no ip name-server") for c in changes):
                findings.append((name, minute, "-", "too eager", "AdGuard Home taken out though it was not its fault (a short pause or the whole internet down)"))
            if name in ("agh-silent", "agh-loop", "agh-down") and not any(c.startswith("no ip name-server") for c in changes):
                findings.append((name, minute, "-", "no fail-open", "AdGuard Home dead but still in the DNS chain"))
            gs = guard_state(root)
            if gs.get("FAILOPEN_ACTIVE") == "1":
                findings.append((name, minute, "-", "not recovered", "tunnel guard still in fail-open after the fault"))
            if not engine_running(root):
                findings.append((name, minute, "-", "not recovered", "route engine not running after the fault"))
            summary.append({"scenario": name, "minutes": bad + after, "seconds": round(time.time() - t0, 1),
                            "changes": len(changes), "refused": len(refused), "top": counts.most_common(3),
                            "guard": gs.get("LAST_ACTION", "")})
    finally:
        sh(root, "/opt/etc/init.d/S91vward-route-engine stop", timeout=30)
        sh(root, "/opt/etc/init.d/S92vward-runtime stop", timeout=30)
        subprocess.run(["umount", "-l", str(root / "opt")], check=False)
        subprocess.run(["umount", "-l", str(root / "proc")], check=False)
    report = {"summary": summary, "findings": [dict(zip(("scenario", "minute", "job", "what", "detail"), f)) for f in findings]}
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=1))
    for s in summary:
        print(f"{s['scenario']:12} {s['minutes']:3} min {s['seconds']:6} s  changes {s['changes']:3}  refused {s['refused']:3}  guard {s['guard']}  top {s['top']}")
    seen = set()
    for f in findings:
        key = (f[0], f[2], f[3], f[4])
        if key in seen:
            continue
        seen.add(key)
        print("FINDING", f)
    shutil.rmtree(tmp, ignore_errors=True)
    print("CHAOS_EMULATED=" + ("FAIL" if findings else "PASS"))
    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()
