#!/usr/bin/env python3
"""The DNS capture of the route engine.

- vward-dnscap (VWARD's own static program) first, tcpdump second: Entware's libpcap
  1.10.6 made tcpdump die at every start on MIPS (SIGBUS), and the engine learned nothing;
- on the LAN device first (not «-i any», which died with SIGSEGV in libpcap), «any» after;
- a pause that grows after quick deaths; the next choice after three; a capture that lived
  long starts the count again;
- a capture that keeps dying without vward-dnscap fetches it (vward-sentinel.sh
  install-dnscap, in the background, at most every 10 minutes), and once it is there it is
  the first choice at once;
- with no program at all the engine waits instead of spinning;
- S91's startup check and the Panel count a vward-dnscap capture like a tcpdump one."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "components/route-engine/scripts/vward-route-engine.sh").read_text()
S91 = (ROOT / "components/runtime/init.d/S91vward-route-engine").read_text()
API = (ROOT / "web/cgi-bin/api.cgi").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"ROUTE_ENGINE_CAPTURE=FAIL: {message}")


if 'tcpdump -ni "$CAP_IF" -l -vv' not in ENGINE or "tcpdump -ni any" in ENGINE:
    fail("the capture runs on $CAP_IF, not on «any»")
if '"$DNSCAP" "$CAP_IF" "$VWARD_LAN_SUBNET" "$VWARD_DNS_SERVER" > "$RAW"' not in ENGINE:
    fail("vward-dnscap is started as DEVICE SUBNET DNS into the same pipe")
a = ENGINE.index("CAP_LAN=${VWARD_LAN_DEVICE:-}")
init = ENGINE[a:ENGINE.index("\nmkdir -p", a)]
b = ENGINE.index('    read -r CAP_UP _ < "${VWARD_UPTIME_FILE:-/proc/uptime}"\n    if [ $((')
logic = ENGINE[b:ENGINE.index('    sleep "$CAP_PAUSE"', b)]

script = '''
vward_valid_ifname() { case "$1" in ''|*[!A-Za-z0-9_.-]*) return 1 ;; esac; }
EVENT_LOG=/dev/null
''' + init + '''
step() {  # step LIFETIME: a capture was started, lived LIFETIME seconds and ended
    cap_pick
    CAP_T0=100; echo "$(( 100 + $1 )).00 0" > "$VWARD_UPTIME_FILE"
''' + logic + '''
    wait
    echo "${CAP_TOOL:-none}:$CAP_IF/$CAP_FAILS/$CAP_PAUSE"
}
for t in $STEPS; do step "$t"; done
'''


# Only the utilities the code needs: a tcpdump installed on this machine must not count.
def tools_dir(tmp):
    d = Path(tmp) / "tools"
    if not d.exists():
        d.mkdir()
        for name in ("date", "cat", "chmod", "printf", "rm"):
            (d / name).symlink_to(shutil.which(name))
    return str(d)


def run(tmp, shell, lan, tools, steps, ctl=None):
    bin_dir = Path(tmp) / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("tcpdump",):
        f = bin_dir / name
        if name in tools:
            f.write_text("#!/bin/sh\nexit 0\n"); f.chmod(0o755)
        elif f.exists():
            f.unlink()
    dnscap = Path(tmp) / "share/vward-dnscap"
    dnscap.parent.mkdir(exist_ok=True)
    if "dnscap" in tools:
        dnscap.write_text("#!/bin/sh\n"); dnscap.chmod(0o755)
    elif dnscap.exists():
        dnscap.unlink()
    try_file = Path(tmp) / "try"
    if try_file.exists():
        try_file.unlink()
    env = {"VWARD_UPTIME_FILE": str(Path(tmp) / "uptime"), "VWARD_LAN_DEVICE": lan, "STEPS": " ".join(map(str, steps)),
           "PATH": f"{bin_dir}:{tools_dir(tmp)}", "VWARD_DNSCAP_BIN": str(dnscap), "VWARD_DNSCAP_TRY": str(try_file),
           "VWARD_SENTINEL_CTL": ctl or str(Path(tmp) / "no-ctl")}
    sh_bin = shutil.which(shell[0])
    r = subprocess.run([sh_bin] + shell[1:] + ["-c", script], env=env, text=True, capture_output=True)
    if r.returncode:
        fail(f"{shell[0]}: {r.stderr[-300:]}")
    return r.stdout.split()


with tempfile.TemporaryDirectory() as tmp:
    ctl = Path(tmp) / "ctl"
    calls = Path(tmp) / "ctl.calls"
    ctl.write_text(f"#!/bin/sh\necho \"$*\" >> {calls}\n[ \"$1\" = install-dnscap ] && printf '#!/bin/sh\\n' > \"$VWARD_DNSCAP_BIN\" && chmod 755 \"$VWARD_DNSCAP_BIN\"\nexit 0\n")
    ctl.chmod(0o755)
    for shell in (["sh"], ["busybox", "sh"]):
        got = run(tmp, shell, "br0", ("dnscap", "tcpdump"), [1] * 13 + [40, 2])
        want = ["dnscap:br0/1/4", "dnscap:br0/2/8", "dnscap:br0/0/2", "tcpdump:br0/1/4", "tcpdump:br0/2/8", "tcpdump:br0/0/2",
                "dnscap:any/1/4", "dnscap:any/2/8", "dnscap:any/0/2", "tcpdump:any/1/4", "tcpdump:any/2/8", "tcpdump:any/0/2",
                "dnscap:br0/1/4", "dnscap:br0/0/2", "dnscap:br0/1/4"]
        if got != want:
            fail(f"{shell[0]}: both programs: {got} want {want}")
        got = run(tmp, shell, "br0", ("tcpdump",), [1] * 7)
        want = ["tcpdump:br0/1/4", "tcpdump:br0/2/8", "tcpdump:br0/0/2", "tcpdump:any/1/4", "tcpdump:any/2/8", "tcpdump:any/0/2", "tcpdump:br0/1/4"]
        if got != want:
            fail(f"{shell[0]}: tcpdump only: {got} want {want}")
        got = run(tmp, shell, "", ("dnscap", "tcpdump"), [1, 1, 1, 1, 40, 1])
        if got != ["dnscap:any/1/4", "dnscap:any/2/8", "dnscap:any/0/2", "tcpdump:any/1/4", "tcpdump:any/0/2", "tcpdump:any/1/4"]:
            fail(f"{shell[0]}: without a LAN device only «any»: {got}")
        got = run(tmp, shell, "br0", (), [1, 1, 1, 1, 1, 1])
        if got != ["none:br0/1/4", "none:br0/2/8", "none:br0/0/2", "none:br0/1/4", "none:br0/2/8", "none:br0/0/2"]:
            fail(f"{shell[0]}: no program: {got}")
        # tcpdump dying, vward-dnscap fetched in the background, then first choice.
        if calls.exists():
            calls.unlink()
        got = run(tmp, shell, "br0", ("tcpdump",), [1, 1, 1, 1, 1, 1], ctl=str(ctl))
        if got[:2] != ["tcpdump:br0/1/4", "dnscap:br0/1/4"]:
            fail(f"{shell[0]}: the fetched vward-dnscap is not taken next: {got}")
        if calls.read_text().split() != ["install-dnscap"]:
            fail(f"{shell[0]}: fetch at most every 10 minutes: {calls.read_text()!r}")
        # Arriving while a later choice runs: back to the first at once.
        if calls.exists():
            calls.unlink()
        got = run(tmp, shell, "br0", ("tcpdump",), [1, 1], ctl=str(ctl))
        if got[0] != "tcpdump:br0/1/4":
            fail(f"{shell[0]}: {got}")

# The arrival reset in isolation: CAP_N=1 (tcpdump on «any»), vward-dnscap appears.
probe = '''
vward_valid_ifname() { return 0; }
EVENT_LOG=/dev/null
''' + init + '''
CAP_N=1; cap_pick; echo "$CAP_TOOL:$CAP_IF"
printf '#!/bin/sh\\n' > "$VWARD_DNSCAP_BIN"; chmod 755 "$VWARD_DNSCAP_BIN"
CAP_T0=100; echo "101.00 0" > "$VWARD_UPTIME_FILE"
''' + logic + '''
echo "$CAP_N/$CAP_PAUSE"; cap_pick; echo "$CAP_TOOL:$CAP_IF"
'''
with tempfile.TemporaryDirectory() as tmp:
    b = Path(tmp) / "bin"; b.mkdir(); (b / "tcpdump").write_text("#!/bin/sh\n"); (b / "tcpdump").chmod(0o755)
    r = subprocess.run([shutil.which("sh"), "-c", probe], text=True, capture_output=True,
                       env={"PATH": f"{b}:{tools_dir(tmp)}", "VWARD_LAN_DEVICE": "br0", "VWARD_UPTIME_FILE": str(Path(tmp) / "up"),
                            "VWARD_DNSCAP_BIN": str(Path(tmp) / "dnscap"), "VWARD_DNSCAP_TRY": str(Path(tmp) / "try"),
                            "VWARD_SENTINEL_CTL": "/nonexistent"})
    if r.stdout.split() != ["tcpdump:any", "0/1", "dnscap:br0"]:
        fail(f"vward-dnscap arriving mid-way: {r.stdout.split()} {r.stderr[-200:]}")

# S91 and the Panel count the vward-dnscap capture (ps w: PID USER VSZ STAT CMD ARGS).
a = S91.index("adaptive_tcpdump_pids()\n")
fn = S91[a:S91.index("\n}\n", a) + 3]
ps = """  101 root      1234 S    tcpdump -ni br0 -l -vv src net 10.9.0.0/24 and not src host 10.9.0.1 and dst host 10.9.0.1 and (udp dst port 53 or tcp dst port 53)
  102 root       300 S    /opt/share/vward/dnscap/vward-dnscap br0 10.9.0.0/24 10.9.0.1
  103 root       300 S    {vward-dnscap} /opt/share/vward/dnscap/vward-dnscap any 10.9.0.0/24 10.9.0.1
  104 root       300 S    /opt/share/vward/dnscap/vward-dnscap br0 10.8.0.0/24 10.9.0.1
  105 root       300 S    vi /tmp/vward-dnscap 10.9.0.0/24
"""
with tempfile.TemporaryDirectory() as tmp:
    b = Path(tmp) / "ps"; b.write_text("#!/bin/sh\ncat <<'X'\n" + ps + "X\n"); b.chmod(0o755)
    r = subprocess.run(["sh", "-c", f"PATH={tmp}:$PATH\nVWARD_LAN_SUBNET=10.9.0.0/24 VWARD_LAN_ADDRESS=10.9.0.1\n" + fn + "adaptive_tcpdump_pids"],
                       text=True, capture_output=True)
    if r.stdout.split() != ["101", "102", "103"]:
        fail(f"S91 counts captures {r.stdout.split()} want 101 102 103")
    a = API.index("set -- $(ps w 2>/dev/null | awk")
    awk_src = API[API.index("'", a) + 1:API.index("')", a)]
    r = subprocess.run(["awk", "-v", "subnet=10.9.0.0/24", "-v", "address=10.9.0.1", awk_src], input=ps, text=True, capture_output=True)
    if r.stdout.split()[-1] != "3":
        fail(f"the Panel counts captures {r.stdout!r} {r.stderr[-200:]}")
if 'install-dnscap' not in S91 or "tcpdump --version" not in S91:
    fail("S91 fetches vward-dnscap before the startup check when tcpdump cannot start")
print("ROUTE_ENGINE_CAPTURE=PASS")
