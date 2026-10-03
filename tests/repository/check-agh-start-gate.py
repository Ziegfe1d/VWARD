#!/usr/bin/env python3
"""One gate for every start of AdGuard Home (vward_agh_ensure): it is started when it is not running; a
second starter inside the 120 s grace only waits (it loads its lists for a minute or more, a start
on top of a start restarts it); after a start that did not bring it up the pauses grow and never end;
a PID file that points to nothing, or to another program, is removed before the start; two starters
at the same moment start it once; running for a whole grace clears the books; a start script that is
missing is reported."""

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/runtime/lib/vward-runtime-admission.sh"


def fail(message: str) -> None:
    raise SystemExit(f"AGH_START_GATE=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    bin_ = tmp / "bin"; bin_.mkdir()
    (bin_ / "S99adguardhome").write_text(f'#!/bin/sh\necho "start $(cat "{tmp}/pidfile-seen" 2>/dev/null)" >> "{tmp}/calls"\n[ -f "{tmp}/agh.pid" ] && echo present > "{tmp}/pidfile-seen" || echo absent > "{tmp}/pidfile-seen"\nsleep 0.3\n')
    (bin_ / "pidof").write_text(f'#!/bin/sh\n[ "$1" = AdGuardHome ] && [ -e "{tmp}/running" ]\n')
    for f in bin_.iterdir():
        f.chmod(0o755)
    (tmp / "proc/4242").mkdir(parents=True)
    (tmp / "proc/4242/comm").write_text("sleep\n")
    (tmp / "proc/4343").mkdir(parents=True)
    (tmp / "proc/4343/comm").write_text("AdGuardHome\n")
    uptime = tmp / "uptime"

    def ensure(up, pidfile=None, parallel=1):
        uptime.write_text(f"{up}.5 1.0\n")
        if pidfile is None:
            (tmp / "agh.pid").unlink(missing_ok=True)
        else:
            (tmp / "agh.pid").write_text(pidfile + "\n")
        (tmp / "pidfile-seen").unlink(missing_ok=True)
        script = f'''PATH="{bin_}:$PATH" VWARD_AGH_STATE="{tmp}/state" VWARD_AGH_PIDFILES="{tmp}/agh.pid" VWARD_PROC="{tmp}/proc" VWARD_UPTIME_FILE="{uptime}"
VWARD_AGH_INIT="{bin_}/S99adguardhome" . "{LIB}"
vward_agh_ensure; echo $?'''
        procs = [subprocess.Popen(["sh", "-c", script], text=True, stdout=subprocess.PIPE) for _ in range(parallel)]
        return sorted(p.communicate(timeout=30)[0].strip() for p in procs)

    def calls():
        f = tmp / "calls"
        return len(f.read_text().splitlines()) if f.exists() else 0

    # Not running: started once; at once again - the grace holds it back (every second starter too).
    if ensure(100) != ["10"] or calls() != 1:
        fail(f"first start: {calls()}")
    for up in (101, 150, 219):
        if ensure(up) != ["11"] or calls() != 1:
            fail(f"inside the grace at {up}: a start on top of a start")
    # Grace over and still not running: the start failed, started again; the next pause is twice as long.
    if ensure(221) != ["10"] or calls() != 2:
        fail("after the grace: start again")
    if ensure(221 + 239) != ["11"] or calls() != 2:
        fail("the second pause is 240 s")
    if ensure(221 + 241) != ["10"] or calls() != 3:
        fail("after 240 s: start again")
    # The pauses stop growing at 600 s and the tries never end.
    t = 221 + 241
    for pause in (481, 601, 601, 601):
        t += pause
        if ensure(t) != ["10"]:
            fail(f"the pause is at most 600 s: {pause}")
    if ensure(t + 599) != ["11"]:
        fail("600 s is the longest pause")
    # Running: nothing. Running for a whole grace since the last start: the books are clean, so the next
    # stop starts it at once; a program that dies a minute after its start keeps its long pause.
    (tmp / "running").write_text("")
    before = calls()
    if ensure(t + 100) != ["0"] or (tmp / "state/last").exists() is False:
        fail("running shortly after a start keeps the books")
    if ensure(t + 800) != ["0"] or (tmp / "state/last").exists():
        fail("running for a whole grace clears the books")
    (tmp / "running").unlink()
    if ensure(t + 801) != ["10"] or calls() != before + 1:
        fail("after a good run the next stop is started at once")
    if (tmp / "state/fails").read_text().strip() != "0":
        fail("the books start again from zero")

    # An orphaned PID file (nothing runs under that number, or another program does) is removed before the start.
    for name, content in (("dead pid", "99999"), ("another program", "4242"), ("not a number", "xyz")):
        (tmp / "state").rename(tmp / "state.old") if (tmp / "state").exists() else None
        import shutil; shutil.rmtree(tmp / "state.old", ignore_errors=True)
        (tmp / "calls").unlink(missing_ok=True)
        # the fake start script reports whether the file was still there when it ran
        (bin_ / "S99adguardhome").write_text(f'#!/bin/sh\n[ -f "{tmp}/agh.pid" ] && echo present > "{tmp}/seen" || echo absent > "{tmp}/seen"\n')
        (tmp / "seen").unlink(missing_ok=True)
        if ensure(500, pidfile=content) != ["10"] or (tmp / "seen").read_text().strip() != "absent":
            fail(f"an orphaned PID file ({name}) must be removed before the start")
    # A PID file of a live AdGuard Home stays.
    shutil.rmtree(tmp / "state", ignore_errors=True)
    if ensure(500, pidfile="4343") != ["10"] or (tmp / "seen").read_text().strip() != "present":
        fail("the PID file of a live AdGuard Home must stay")

    # Two starters at the same moment: one start.
    shutil.rmtree(tmp / "state", ignore_errors=True)
    (tmp / "calls").unlink(missing_ok=True)
    (bin_ / "S99adguardhome").write_text(f'#!/bin/sh\necho start >> "{tmp}/calls"\nsleep 0.3\n')
    res = ensure(700, parallel=4)
    if res.count("10") != 1 or calls() != 1:
        fail(f"four starters at once: {res} {calls()} starts")
    # A reboot restarts the uptime: a «last» from the future is an old one.
    uptime.write_text("90.0 1.0\n")
    if ensure(90) != ["10"]:
        fail("after a reboot the old bookkeeping must not hold the start back")
    # A program that dies on --version is not started again and again: the state «broken» tells the Panel.
    shutil.rmtree(tmp / "state", ignore_errors=True)
    (tmp / "calls").unlink(missing_ok=True)
    (bin_ / "S99adguardhome").write_text(f'#!/bin/sh\necho start >> "{tmp}/calls"\n')
    bad = tmp / "badbin"; bad.mkdir()
    (bad / "AdGuardHome").write_text("#!/bin/sh\necho 'fatal error: missing stackmap' >&2\nexit 2\n"); (bad / "AdGuardHome").chmod(0o755)

    def ensure_bin(up, dirs):
        uptime.write_text(f"{up}.5 1.0\n")
        script = f'''PATH="{bin_}:$PATH" VWARD_AGH_STATE="{tmp}/state" VWARD_AGH_PIDFILES="{tmp}/agh.pid" VWARD_PROC="{tmp}/proc" VWARD_UPTIME_FILE="{uptime}" VWARD_AGH_BIN_DIRS="{dirs}"
VWARD_AGH_INIT="{bin_}/S99adguardhome" . "{LIB}"
vward_agh_ensure; echo $?'''
        return subprocess.run(["sh", "-c", script], text=True, capture_output=True, timeout=30).stdout.strip()

    if ensure_bin(800, str(bad)) != "13" or calls() != 0:
        fail("a program that dies on --version must not be started")
    if (tmp / "state/broken").read_text().strip() != "800|2|" + str(bad / "AdGuardHome"):
        fail(f"the broken state: {(tmp / 'state/broken').read_text()!r}")
    good = tmp / "goodbin"; good.mkdir()
    (good / "AdGuardHome").write_text("#!/bin/sh\necho 'AdGuard Home, version v0.107.73'\n"); (good / "AdGuardHome").chmod(0o755)
    if ensure_bin(801, f"{good} {bad}") != "10" or calls() != 1 or (tmp / "state/broken").exists():
        fail("the first program on the start script's path decides: a good one starts and clears «broken»")
    # No start script.
    if subprocess.run(["sh", "-c", f'VWARD_AGH_STATE="{tmp}/s2" VWARD_UPTIME_FILE="{uptime}" . "{LIB}"; vward_agh_ensure "{tmp}/none"; echo $?'],
                      text=True, capture_output=True, env={"PATH": f"{bin_}:/usr/bin:/bin"}).stdout.strip() != "12":
        fail("a missing start script is reported")

# The Panel says it.
api = (ROOT / "web/cgi-bin/api.cgi").read_text()
js = (ROOT / "web/assets/vward-console.js").read_text()
for need in ('adguard_broken:($agh_broken != "")', '"${VWARD_AGH_STATE:-/tmp/vward-agh-start}/broken"'):
    if need not in api:
        fail(f"the API lacks {need}")
if "sv.adguard === false && sv.adguard_broken" not in js or "'Программа AdGuard Home повреждена'" not in js:
    fail("the Panel must say the AdGuard Home program is broken")
# Both starters go through the gate.
for path, need in (("components/runtime/scripts/vward-cron-supervisor.sh", "vward_agh_ensure"), ("components/runtime/scripts/vward-sentinel-act.sh", "vward_agh_ensure")):
    if need not in (ROOT / path).read_text():
        fail(f"{path} must start AdGuard Home through the gate")
print("AGH_START_GATE=PASS")
