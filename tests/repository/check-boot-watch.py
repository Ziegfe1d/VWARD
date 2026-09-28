#!/usr/bin/env python3
"""Boot watch in the cron supervisor: the Panel's web server is started again when it is
not running (at boot the home network may come up after it) and a failed start is logged
once; AdGuard Home is started only between 90 s and 10 minutes after boot and only when
it is not running at all.

watch_services is taken from vward-cron-supervisor.sh as it is and run with stand-ins."""

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
    for f in bin_.iterdir():
        f.chmod(0o755)
    harness = tmp / "h.sh"
    harness.write_text(f"""PATH="{bin_}:$PATH"
VWARD_CONSOLE_INIT="{bin_}/console" VWARD_CONSOLE_PIDFILE="{tmp}/console.pid"
VWARD_AGH_INIT="{bin_}/agh" VWARD_UPTIME_FILE="{tmp}/uptime"
log_event() {{ echo "$*" >> "{tmp}/log"; }}
{FUNC}
for i in $(seq "$1"); do watch_services; done
""")

    def run(uptime, times=1):
        for f in ("calls", "log"):
            (tmp / f).unlink(missing_ok=True)
        (tmp / "uptime").write_text(f"{uptime}.42 100.0\n")
        subprocess.run(["sh", str(harness), str(times)], check=True, timeout=30)
        read = lambda n: (tmp / n).read_text().split("\n")[:-1] if (tmp / n).exists() else []
        return read("calls"), read("log")

    # No home network yet: the Panel cannot start; tried each time, logged once.
    calls, log = run(30, 3)
    if calls != ["console start"] * 3 or log != ["PANEL_START_FAILED"]:
        fail(f"no network: {calls} {log}")
    # The network is up: started once, then left alone while it runs.
    (tmp / "lan").write_text("")
    calls, log = run(40, 2)
    if calls != ["console start"] or log != ["PANEL_STARTED"]:
        fail(f"network up: {calls} {log}")
    # AdGuard Home not running two minutes after boot: started.
    calls, log = run(120)
    if calls != ["agh start"] or log != ["AGH_STARTED|uptime=120"]:
        fail(f"AdGuard Home after boot: {calls} {log}")
    # Too early (its own script is still starting it), too late (owner's choice), running.
    for up in (30, 900):
        if run(up)[0]:
            fail(f"AdGuard Home must be left alone at uptime {up}")
    (tmp / "agh.running").write_text("")
    if run(120)[0]:
        fail("a running AdGuard Home is left alone")
    subprocess.run(["sh", "-c", f'kill $(cat "{tmp}/console.pid") 2>/dev/null'])

if "watch_services" not in SRC.split("while :; do", 1)[1]:
    fail("the supervisor loop does not call watch_services")
print("BOOT_WATCH=PASS")
