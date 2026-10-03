#!/usr/bin/env python3
"""The DNS capture of the route engine: on the LAN device (not «-i any», which died with
SIGSEGV in libpcap on the router), a pause that grows after quick deaths, and the other
interface tried after three; a capture that lived long starts the count again."""

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "components/route-engine/scripts/vward-route-engine.sh").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"ROUTE_ENGINE_CAPTURE=FAIL: {message}")


if 'tcpdump -ni "$CAP_IF" -l -vv' not in ENGINE or "tcpdump -ni any" in ENGINE:
    fail("the capture runs on $CAP_IF, not on «any»")
a = ENGINE.index("CAP_LAN=${VWARD_LAN_DEVICE:-}")
init = ENGINE[a:ENGINE.index("\nmkdir -p", a)]
b = ENGINE.index('    read -r CAP_UP _ < "${VWARD_UPTIME_FILE:-/proc/uptime}"\n    if [ $((')
logic = ENGINE[b:ENGINE.index('    sleep "$CAP_PAUSE"', b)]

script = '''
vward_valid_ifname() { case "$1" in ''|*[!A-Za-z0-9_.-]*) return 1 ;; esac; }
''' + init + '''
step() {  # step LIFETIME: a capture that lived LIFETIME seconds ended
    CAP_T0=100; echo "$(( 100 + $1 )).00 0" > "$VWARD_UPTIME_FILE"
''' + logic + '''
    echo "$CAP_IF/$CAP_FAILS/$CAP_PAUSE"
}
echo "start=$CAP_IF"
step 1; step 1; step 1; step 1; step 1; step 1; step 1; step 1; step 1
step 40; step 2
'''
with tempfile.TemporaryDirectory() as tmp:
    up = str(Path(tmp) / "uptime")
    for shell in (["sh"], ["busybox", "sh"]):
        for lan, want_start in (("br0", "br0"), ("", "any"), ("bad name", "any")):
            r = subprocess.run(shell + ["-c", script], env={"VWARD_UPTIME_FILE": up, "VWARD_LAN_DEVICE": lan, "PATH": "/usr/bin:/bin"}, text=True, capture_output=True)
            if r.returncode:
                fail(f"{shell[0]}: {r.stderr[-300:]}")
            lines = r.stdout.split()
            if lines[0] != f"start={want_start}":
                fail(f"{shell[0]} lan={lan!r}: starts on {lines[0]}")
            if lan == "br0":
                want = ["br0/1/4", "br0/2/8", "any/0/2", "any/1/4", "any/2/8", "br0/0/2", "br0/1/4", "br0/2/8", "any/0/2", "any/0/2", "any/1/4"]
                if lines[1:] != want:
                    fail(f"{shell[0]}: pauses and interface switch {lines[1:]} want {want}")
            else:
                if any(not l.startswith("any/") for l in lines[1:]):
                    fail(f"{shell[0]} lan={lan!r}: without a LAN device it stays on any: {lines[1:]}")
                if lines[-2:] != ["any/0/2", "any/1/4"]:
                    fail(f"{shell[0]}: a long capture resets the count: {lines}")
print("ROUTE_ENGINE_CAPTURE=PASS")
