#!/usr/bin/env python3
"""Boot watch in the cron supervisor: the Panel's web server is started again when it is
not running (at boot the home network may come up after it) and a failed start is logged
once; AdGuard Home is started from 90 s after boot on, only when it is not running at all
(through the shared gate: tests/repository/check-agh-start-gate.py), not while ads protection
is off or a package update holds it; a program that cannot run is told in the bell once and
the official build is asked for (fix.28.2).

watch_services is taken from vward-cron-supervisor.sh as it is and run with stand-ins."""

import os
import shutil
import time
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = (ROOT / "components/runtime/scripts/vward-cron-supervisor.sh").read_text()
FUNC = SRC[SRC.index("CONSOLE_INIT="):SRC.index('log_event "SUPERVISOR_START')]


def fail(message: str) -> None:
    raise SystemExit(f"BOOT_WATCH=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    bin_ = tmp / "bin"; bin_.mkdir()
    (bin_ / "console").write_text(f'#!/bin/sh\necho "console $1" >> "{tmp}/calls"\n[ -e "{tmp}/lan" ] || exit 1\n'
                                  f'sleep 60 & echo $! > "{tmp}/console.pid"\n')
    (bin_ / "agh").write_text(f'#!/bin/sh\necho "agh $1" >> "{tmp}/calls"\n')
    (bin_ / "pidof").write_text(f'#!/bin/sh\n[ "$1" = AdGuardHome ] && [ -e "{tmp}/agh.running" ]\n')
    (bin_ / "helper").write_text(f'#!/bin/sh\necho "helper $*" >> "{tmp}/calls"\n')
    aghbin = tmp / "aghbin"; aghbin.mkdir()
    (aghbin / "AdGuardHome").write_text(f'#!/bin/sh\n[ -e "{tmp}/agh.broken" ] && exit 132\nexit 0\n')
    (aghbin / "AdGuardHome").chmod(0o755)
    for f in bin_.iterdir():
        f.chmod(0o755)
    # The agents act here (the default is observation since fix.28.6).
    (tmp / "agents.conf").write_text("all=act\n")
    harness = tmp / "h.sh"
    harness.write_text(f"""PATH="{bin_}:$PATH"
VWARD_CONSOLE_INIT="{bin_}/console" VWARD_CONSOLE_PIDFILE="{tmp}/console.pid"
VWARD_AGH_INIT="{bin_}/agh" VWARD_UPTIME_FILE="{tmp}/uptime"
VWARD_ADMISSION_LIB="{ROOT}/components/runtime/lib/vward-runtime-admission.sh" VWARD_AGH_STATE="{tmp}/aghstate" VWARD_AGH_PIDFILES="{tmp}/agh.pid"
VWARD_COMPONENT_STATE="{tmp}/components" VWARD_EXT_UPDATE_STATE="{tmp}/ext" VWARD_DNS_CHAIN_STATE="{tmp}/chain" VWARD_CONSOLE_CONFIG_BIN="{bin_}/helper"
VWARD_AGH_BIN_DIRS="{aghbin}" VWARD_AGH_REPAIR_STAMP="{tmp}/ext/agh-repair.last"
VWARD_PROFILE_LIB="{ROOT}/components/runtime/lib/vward-device-profile.sh" VWARD_CONSOLE_NOTES="{tmp}/notes" VWARD_AGENTS_CONF="{tmp}/agents.conf"
export VWARD_COMPONENT_STATE VWARD_AGH_BIN_DIRS VWARD_CONSOLE_NOTES
[ ! -r "$VWARD_ADMISSION_LIB" ] || . "$VWARD_ADMISSION_LIB"
log_event() {{ echo "$*" >> "{tmp}/log"; }}
{FUNC}
for i in $(seq "$1"); do watch_services; done
wait
""")

    def run(uptime, times=1):
        for f in ("calls", "log"):
            (tmp / f).unlink(missing_ok=True)
        shutil.rmtree(tmp / "aghstate", ignore_errors=True)
        (tmp / "uptime").write_text(f"{uptime}.42 100.0\n")
        subprocess.run(["sh", str(harness), str(times)], check=True, timeout=30, stderr=subprocess.DEVNULL)
        read = lambda n: (tmp / n).read_text().split("\n")[:-1] if (tmp / n).exists() else []
        # The agents' lateness (the harness has none running) is another test's.
        return read("calls"), [l for l in read("log") if not l.startswith("AGENT_LATE|")]

    # No home network yet: the Panel cannot start; tried after 1, 2, 4... minutes, logged once.
    calls, log = run(30, 8)
    if calls != ["console start"] * 3 or log != ["PANEL_START_FAILED"]:
        fail(f"no network: tries at minutes 1, 3 and 6 of 8: {calls} {log}")
    # The network is up: started once, then left alone while it runs.
    (tmp / "lan").write_text("")
    calls, log = run(40, 2)
    if calls != ["console start"] or log != ["PANEL_STARTED"]:
        fail(f"network up: {calls} {log}")
    # AdGuard Home not running two minutes after boot: started.
    calls, log = run(120)
    if calls != ["agh start"] or log != ["AGH_STARTED|uptime=120"]:
        fail(f"AdGuard Home after boot: {calls} {log}")
    # A day after boot too (fix.28.2: only the first half hour before, a crash a day later
    # left DNS without AdGuard Home for a day).
    calls, log = run(86400)
    if calls != ["agh start"] or log != ["AGH_STARTED|uptime=86400"]:
        fail(f"AdGuard Home a day after boot: {calls} {log}")
    # Too early (its own script is still starting it): left alone.
    if run(30)[0]:
        fail("AdGuard Home must be left alone at uptime 30")
    # Ads protection off, VWARD off, a package update running: left alone.
    (tmp / "components").mkdir()
    for flag in ("ads-privacy-guard.disabled", "vward.off"):
        (tmp / "components" / flag).write_text("")
        if run(3600)[0]:
            fail(f"AdGuard Home must be left alone with {flag}")
        (tmp / "components" / flag).unlink()
    (tmp / "chain").mkdir()
    (tmp / "chain/planned").write_text(f"{int(time.time()) + 600}\n")
    if run(3600)[0]:
        fail("AdGuard Home must be left alone while an update replaces it")
    (tmp / "chain/planned").write_text(f"{int(time.time()) - 5}\n")
    if run(3600)[0] != ["agh start"]:
        fail("an update's window that ended: AdGuard Home is watched again")
    (tmp / "chain/planned").unlink()
    # A program that cannot run (exit 132, an illegal instruction): not started, told once,
    # the official build asked for once a day.
    (tmp / "agh.broken").write_text("")
    calls, log = run(3600, 3)
    notes = (tmp / "notes/notes.tsv").read_text() if (tmp / "notes/notes.tsv").exists() else ""
    if calls != ["helper ext-agh-official repair"] or log != ["AGH_BINARY_BROKEN|uptime=3600|exit=132", "AGH_REPAIR_STARTED|uptime=3600"]:
        fail(f"broken AdGuard Home: {calls} {log}")
    if notes.count("AdGuard Home не запускается") != 1 or "недопустимая инструкция" not in notes or "d-agh" not in notes:
        fail(f"broken AdGuard Home must be told in the bell once: {notes!r}")
    (tmp / "agh.broken").unlink()
    (tmp / "agh.running").write_text("")
    if run(120)[0]:
        fail("a running AdGuard Home is left alone")
    subprocess.run(["sh", "-c", f'kill $(cat "{tmp}/console.pid") 2>/dev/null'])

# Memory: a program above its limit three minutes in a row is stopped (its starter brings it
# back); one below is left alone; low memory of the router is logged once, and its end.
MEM = SRC[SRC.index("PROC=${VWARD_PROC"):SRC.index("watch_services()")]
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    for pid, rss in ((4242, 20000), (4343, 9000)):
        (tmp / f"proc/{pid}").mkdir(parents=True)
        (tmp / f"proc/{pid}/status").write_text(f"Name:\tsh\nVmRSS:\t   {rss} kB\n")
    (tmp / "run/awg-engine").mkdir(parents=True)
    (tmp / "run/route-engine.pid").write_text("4242\n")
    (tmp / "run/awg-engine/t0.pid").write_text("4343\n")
    meminfo = tmp / "proc/meminfo"
    harness = tmp / "m.sh"
    harness.write_text(f"""VWARD_PROC="{tmp}/proc" VWARD_RUN_DIR="{tmp}/run" CONSOLE_PIDFILE="{tmp}/none"
log_event() {{ echo "$*"; }}
kill() {{ echo "KILL $*"; }}
{MEM}
for i in 1 2 3; do watch_memory; done
sed -i 's/12000/90000/' "{meminfo}"
watch_memory
""")
    meminfo.write_text("MemTotal: 250000 kB\nMemAvailable:   12000 kB\n")
    out = subprocess.run(["sh", str(harness)], text=True, capture_output=True, timeout=30).stdout.split("\n")[:-1]
    if out != ["MEM_LOW|available_kb=12000", "KILL 4242", "MEM_RESTART|routeengine|rss_kb=20000|limit_kb=16384", "MEM_OK|available_kb=90000"]:
        fail(f"memory watch: {out}")
if "watch_memory" not in SRC[SRC.index("watch_services()"):] or "$UNNICE" not in SRC:
    fail("the memory watch runs every minute; what the supervisor starts gets the normal priority")

if "watch_services" not in SRC.split("while :; do", 1)[1]:
    fail("the supervisor loop does not call watch_services")
print("BOOT_WATCH=PASS")
