#!/usr/bin/env python3
"""AdaptiveAuto restored from USB at the engine's start (fix.34; CI #726, stress «big»).

With thousands of saved names the restore ran a grep for each name and an ndmc for each missing
one: longer than S91's start wait (12 s), S91 killed the engine every minute and each TERM left
/tmp/vward-route-restore-*.<pid> (428 KB each). Now:
  * both differences in one awk: 20 000 saved names (the stress list) restore in a few seconds;
  * removals first, then no more names than Keenetic's 300 leave room for; the rest counted
    (over_limit=N) and not sent;
  * a name the router would refuse is skipped; «too many elements» stops the adds and sets the
    one-hour «full» flag;
  * at most VWARD_RESTORE_SECONDS (8) of Keenetic calls, so S91's start wait is kept; the names
    left are counted (left=N);
  * a TERM in the middle leaves no restore files; files a killed run left are taken away.
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "components/route-engine/scripts/vward-route-engine.sh").read_text()


def fail(msg):
    print(f"ROUTE_ENGINE_RESTORE=FAIL: {msg}")
    sys.exit(1)


restore = ENGINE[ENGINE.index("valid_fqdn()\n"):ENGINE.index("# ADD TO VPN")]
cleanup = ENGINE[ENGINE.index("cleanup()\n"):ENGINE.index("trap cleanup EXIT")]
shells = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])


def leftovers(pid=None):
    return [p.name for p in Path("/tmp").glob("vward-route-restore-*") if pid is None or p.name.endswith(f".{pid}")]


for shell in shells:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "bin").mkdir()
        (t / "bin/ndmc").write_text('#!/bin/sh\necho "$2" >> "$T/ndmc.log"\n[ ! -e "$T/slow" ] || sleep 1\n'
                                    'n=$(grep -c . "$T/ndmc.log")\n[ ! -e "$T/full-at" ] || [ "$n" -lt "$(cat "$T/full-at")" ] || '
                                    'echo \'Network::ObjectGroup: "AdaptiveAuto": too many elements\'\nexit 0\n')
        (t / "bin/ndmc").chmod(0o755)
        script = t / "run.sh"
        script.write_text(f"""PERSIST="{t}/persist"; EVENT_LOG="{t}/events"; GROUP=AdaptiveAuto; REFRESH_TS="{t}/ts"
ADAPTIVE_FULL="{t}/adaptive.full"; ENGINE_LOG="{t}/engine.log"; LOCK="{t}/lock"; STOP_WHY=exit; RAW=; HOSTS=
change_lock() {{ :; }}; change_unlock() {{ :; }}; vward_running_config() {{ cat "{t}/rc"; }}
classifier_stop() {{ :; }}; vward_admission_leave() {{ :; }}
{cleanup}
trap cleanup EXIT
trap 'STOP_WHY=TERM; exit 143' TERM
{restore}
echo "pid=$$" > "{t}/pid"
restore_adaptive_from_persist
""")
        env = {"PATH": f"{t}/bin:/usr/bin:/bin", "T": str(t)}

        def setup(cur, want):
            (t / "rc").write_text("object-group fqdn AdaptiveAuto\n" + "".join(f"    include {h}\n" for h in cur) + "!\n")
            (t / "persist").write_text("".join(f"{h}\n" for h in want))
            for f in ("ndmc.log", "events", "adaptive.full", "slow", "full-at"):
                (t / f).unlink(missing_ok=True)

        def run(**extra):
            t0 = time.time()
            r = subprocess.run([*shell, str(script)], env=env | extra, capture_output=True, text=True, timeout=120)
            return r, time.time() - t0

        def asked():
            return (t / "ndmc.log").read_text().splitlines() if (t / "ndmc.log").exists() else []

        def event():
            return [l for l in (t / "events").read_text().splitlines() if "PERSIST_RESTORE_" in l]

        # The stress list: 20 000 saved names, 3 of them in Keenetic, 2 in Keenetic not saved.
        Path("/tmp/vward-route-restore-want.99999999").write_text("left by a killed run\n")
        names = [f"auto{n}.example.com" for n in range(20000)]
        setup(["auto1.example.com", "auto2.example.com", "auto3.example.com", "gone1.example", "gone2.example"], names)
        r, took = run(VWARD_RESTORE_SECONDS="100")  # the time of the differences, not of the calls
        if took > 20:
            fail(f"{shell[0]}: 20 000 saved names took {took:.1f} s")
        a = asked()
        dels = [x for x in a if x.startswith("no ")]
        adds = [x for x in a if not x.startswith("no ")]
        if sorted(dels) != ["no object-group fqdn AdaptiveAuto include gone1.example", "no object-group fqdn AdaptiveAuto include gone2.example"] \
           or a.index(dels[-1]) > a.index(adds[0]):
            fail(f"{shell[0]}: the names Keenetic has and USB does not: removed first, once: {dels}")
        if len(adds) != 297 or len(set(adds)) != 297 or any(x.endswith((" auto1.example.com", " auto2.example.com", " auto3.example.com")) for x in adds):
            fail(f"{shell[0]}: no more than Keenetic's 300 and none it has: {len(adds)} sent")
        if not event() or not event()[-1].split("|", 1)[1].startswith("PERSIST_RESTORE_OK|added=297|removed=2|skipped=0|over_limit=19700|left=0"):
            fail(f"{shell[0]}: the restore line: {event()}")
        if leftovers():
            fail(f"{shell[0]}: restore files left: {leftovers()}")

        # A name the router would refuse is not sent; a small restore as before.
        setup(["keep.example", "old.example"], ["keep.example", "New.Example", "bad_name!.example", ""])
        run()
        if asked() != ["no object-group fqdn AdaptiveAuto include old.example", "object-group fqdn AdaptiveAuto include new.example"]:
            fail(f"{shell[0]}: a small restore: {asked()}")
        if "|added=1|removed=1|skipped=1|over_limit=0" not in event()[-1]:
            fail(f"{shell[0]}: a small restore line: {event()}")

        # Keenetic says the group is full (names added by hand meanwhile): the adds stop there.
        setup([], [f"x{n}.example" for n in range(50)])
        (t / "full-at").write_text("3\n")
        run()
        if len(asked()) != 3 or not (t / "adaptive.full").exists() or "PERSIST_RESTORE_PARTIAL|added=2|" not in event()[-1]:
            fail(f"{shell[0]}: «too many elements» does not stop the restore: {len(asked())} {event()}")

        # A slow Keenetic: the restore stops after its seconds, the names left are counted.
        setup([], [f"z{n}.example" for n in range(30)])
        (t / "slow").write_text("")
        r, took = subprocess.run([*shell, str(script)], env=env | {"VWARD_RESTORE_SECONDS": "2"}, capture_output=True, text=True, timeout=60), 0
        if not 1 <= len(asked()) <= 4 or "PERSIST_RESTORE_PARTIAL|" not in event()[-1] or f"left={30 - len(asked())}" not in event()[-1]:
            fail(f"{shell[0]}: a restore past its seconds: {len(asked())} sent, {event()}")

        # TERM in the middle (S91's start wait): no restore file is left.
        setup([], [f"y{n}.example" for n in range(50)])
        (t / "slow").write_text("")
        p = subprocess.Popen([*shell, str(script)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)
        pid = (t / "pid").read_text().strip().split("=")[1]
        if not leftovers(pid):
            fail(f"{shell[0]}: the restore did not start")
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=20)
        if leftovers(pid):
            fail(f"{shell[0]}: a TERM left restore files: {leftovers(pid)}")
        if "|STOP|reason=TERM|rc=143|" not in (t / "events").read_text():
            fail(f"{shell[0]}: a TERM not logged as such")

print("ROUTE_ENGINE_RESTORE=PASS")
