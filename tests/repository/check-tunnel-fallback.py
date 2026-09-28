#!/usr/bin/env python3
"""Several tunnels: the tunnel guard moves VWARD's routes to the best other tunnel that
answers when the one it routes through dies (nothing goes direct), brings them back when
the first answers three minutes in a row, and goes direct as before when no other tunnel
answers or the fallback is switched off. The quality script keeps the last hour of ping
samples and sums up the last 30 minutes."""

import os
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "components/tunnel-guard/scripts/vward-tunnel-guard.sh"
QUALITY = ROOT / "components/tunnel-guard/scripts/vward-tunnel-quality.sh"


def fail(message: str) -> None:
    raise SystemExit(f"TUNNEL_FALLBACK=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    bin_ = tmp / "bin"; bin_.mkdir()
    etc = tmp / "etc"; etc.mkdir()
    gdir = tmp / "guard"; gdir.mkdir()
    health = tmp / "health"
    # The profile: routes through Wireguard0 (nwg0); the provider is eth3.
    (tmp / "iface").write_text("Wireguard0 nwg0")
    (tmp / "profile.sh").write_text(f"""vward_profile_load() {{ read -r VWARD_TUNNEL_INTERFACE VWARD_TUNNEL_DEVICE < "{tmp}/iface"; VWARD_WAN_DEVICE=eth3; }}
vward_valid_ifname() {{ case "$1" in ''|*[!A-Za-z0-9_.:-]*) return 1;; esac; }}
vward_device_map() {{ printf 'I\\tWireguard0\\twireguard\\tnwg0\\nI\\tWireguard1\\twireguard\\tnwg1\\nI\\tWireguard2\\twireguard\\tnwg2\\n'; }}
vward_map_vpns() {{ printf '%s\\n' "$1" | awk -F '\\t' '$1=="I" {{print $2 " " $4}}'; }}
""")
    (tmp / "admission.sh").write_text("vward_component_gate() { :; }\nvward_admission_enter() { :; }\nvward_admission_leave() { :; }\n")
    # The provider answers; every tunnel device fails curl (the guard's own check of the dead one).
    (bin_ / "curl").write_text('#!/bin/sh\ncase "$*" in *"--interface eth3"*) exit 0 ;; esac\nexit 7\n')
    (bin_ / "ndmc").write_text(f'#!/bin/sh\necho "$*" >> "{tmp}/ndmc.log"\n')
    # The quality summary the guard reads: name dev last_loss last_ms ok_streak samples loss avg jitter up
    (bin_ / "quality").write_text(f'#!/bin/sh\ncat "{tmp}/summary"\n')
    # The Panel's helper: «tunnel NAME» moves the routes and changes the profile.
    (bin_ / "helper").write_text(f"""#!/bin/sh
echo "$* by_guard=${{VWARD_TUNNEL_BY_GUARD:-}}" >> "{tmp}/helper.log"
[ "$1" = tunnel ] || exit 64
case "$2" in Wireguard0) d=nwg0 ;; Wireguard1) d=nwg1 ;; Wireguard2) d=nwg2 ;; esac
echo "$2 $d" > "{tmp}/iface"
echo result=changed
""")
    for f in bin_.iterdir():
        f.chmod(0o755)
    env = os.environ | {"PATH": f"{bin_}:{os.environ['PATH']}", "VWARD_PROFILE_LIB": str(tmp / "profile.sh"),
                        "VWARD_ADMISSION_LIB": str(tmp / "admission.sh"), "VWARD_TUNNEL_HEALTH_STATE": str(health),
                        "VWARD_TUNNEL_GUARD_DIR": str(gdir), "VWARD_TUNNEL_GUARD_LOG": str(tmp / "guard.log"),
                        "VWARD_TUNNEL_GUARD_LOCK": str(tmp / "lock"), "VWARD_ETC": str(etc),
                        "VWARD_TUNNEL_QUALITY_BIN": str(bin_ / "quality"), "VWARD_CONSOLE_CONFIG_BIN": str(bin_ / "helper"),
                        "VWARD_CURL_BIN": str(bin_ / "curl"), "VWARD_NDMC": str(bin_ / "ndmc")}

    def run(status, summary):
        health.write_text(f"STATUS={status}\nLAST_CHECK={int(time.time())}\nCONFIG_STATE=up\n")
        (tmp / "summary").write_text(summary)
        r = subprocess.run(["sh", str(GUARD)], env=env, text=True, capture_output=True, timeout=60)
        if r.returncode != 0:
            fail(f"guard rc={r.returncode} {r.stderr[-300:]}")
        return r.stdout.split("\n", 1)[0]

    def fallback():
        f = gdir / "fallback"
        return f.read_text() if f.exists() else ""

    # Wireguard0 dies; Wireguard1 answers with loss, Wireguard2 cleanly: Wireguard2 is taken.
    alive = "Wireguard0\tnwg0\t100\t-\t0\t30\t40\t30\t5\t60\nWireguard1\tnwg1\t0\t90\t5\t30\t10\t90\t20\t100\nWireguard2\tnwg2\t0\t60\t30\t30\t0\t60\t4\t100\n"
    if run("DOWN", alive) != "ACTION=FALLBACK_SWITCH":
        fail(f"a dead tunnel with others alive must fall back: {(tmp / 'guard.log').read_text()}")
    if (tmp / "iface").read_text().split()[0] != "Wireguard2" or "tunnel Wireguard2 by_guard=1" not in (tmp / "helper.log").read_text():
        fail("the routes must go to the best answering tunnel through the helper")
    if not fallback().startswith("FROM=Wireguard0") or (tmp / "ndmc.log").exists():
        fail(f"the first tunnel is remembered and nothing is switched off: {fallback()}")
    if "|to=Wireguard2|from=Wireguard0" not in (tmp / "guard.log").read_text():
        fail("the guard log names where the routes went")
    # Wireguard0 answers two minutes: not yet; three: the routes come back.
    if run("UP", "Wireguard0\tnwg0\t0\t50\t2\t30\t60\t50\t5\t40\n") != "ACTION=KEEP_UP":
        fail("two minutes are not enough to come back")
    if run("UP", "Wireguard0\tnwg0\t0\t50\t3\t30\t60\t50\t5\t40\n") != "ACTION=FALLBACK_RETURN":
        fail("three minutes bring the routes back")
    if (tmp / "iface").read_text().split()[0] != "Wireguard0" or fallback():
        fail("back on the first tunnel, nothing to remember")
    # Return switched off: the routes stay where they are.
    (etc / "tunnel-return.disabled").write_text("x")
    run("DOWN", alive)
    if run("UP", "Wireguard0\tnwg0\t0\t50\t9\t30\t0\t50\t5\t100\n") != "ACTION=KEEP_UP" or (tmp / "iface").read_text().split()[0] != "Wireguard2":
        fail("with the return switched off the routes stay on the fallback")
    (etc / "tunnel-return.disabled").unlink()
    (tmp / "iface").write_text("Wireguard0 nwg0"); (gdir / "fallback").unlink(); (gdir / "state").unlink()
    # Nothing else answers, or the fallback is off: direct, as before (the tunnel is taken down).
    if run("DOWN", "Wireguard1\tnwg1\t100\t-\t0\t30\t100\t-\t-\t0\n") != "ACTION=FAILOPEN_DOWN":
        fail("with no tunnel alive the lists go direct")
    (gdir / "state").unlink(); (tmp / "ndmc.log").unlink()
    (etc / "tunnel-fallback.disabled").write_text("x")
    if run("DOWN", alive) != "ACTION=FAILOPEN_DOWN" or "interface Wireguard0 down" not in (tmp / "ndmc.log").read_text():
        fail("with the fallback off the lists go direct")

    # The quality script: the samples of all tunnels at once, summed for 30 minutes.
    qdir = tmp / "q"
    (bin_ / "ping").write_text('#!/bin/sh\ncase "$*" in *nwg1*) printf "3 packets transmitted, 0 packets received, 100%% packet loss\\n" ;; '
                                '*) printf "3 packets transmitted, 3 packets received, 0%% packet loss\\nround-trip min/avg/max = 40.1/41.6/43.0 ms\\n" ;; esac\n')
    (bin_ / "ping").chmod(0o755)
    sysfs = tmp / "sys"
    for d in ("nwg0", "nwg1"):
        (sysfs / d).mkdir(parents=True)
    qenv = env | {"VWARD_TUNNEL_QUALITY_DIR": str(qdir), "VWARD_PING": str(bin_ / "ping"), "VWARD_SYSFS_NET": str(sysfs)}
    old = int(time.time()) - 7200
    qdir.mkdir(); (qdir / "samples.tsv").write_text(f"{old}\tWireguard0\tnwg0\t0\t10\n")
    for _ in range(2):
        subprocess.run(["sh", str(QUALITY)], env=qenv, check=True, timeout=60)
    lines = (qdir / "samples.tsv").read_text().splitlines()
    if len(lines) != 4 or any(l.startswith(str(old)) for l in lines):
        fail(f"an hour of samples, both tunnels, a missing device skipped: {lines}")
    summ = subprocess.run(["sh", str(QUALITY), "summary"], env=qenv, text=True, capture_output=True, check=True).stdout.splitlines()
    if summ != ["Wireguard0\tnwg0\t0\t42\t2\t2\t0\t42\t0\t100", "Wireguard1\tnwg1\t100\t-\t0\t2\t100\t-\t-\t0"]:
        fail(f"summary: {summ}")
print("TUNNEL_FALLBACK=PASS")
