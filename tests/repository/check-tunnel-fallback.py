#!/usr/bin/env python3
"""Several tunnels: the tunnel guard moves VWARD's routes to the best other tunnel that
answers when the one it routes through dies (nothing goes direct), brings them back when
the first answers three minutes in a row, and goes direct as before when no other tunnel
answers or the fallback is switched off. The quality script keeps the last hour of ping
samples and sums up the last 30 minutes."""

import json
import os
import shutil
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
VWARD_POLICY_GROUP=VwardGroup
vward_valid_ifname() {{ case "$1" in ''|*[!A-Za-z0-9_.:-]*) return 1;; esac; }}
vward_device_map() {{ printf 'I\\tWireguard0\\twireguard\\tnwg0\\nI\\tWireguard1\\twireguard\\tnwg1\\nI\\tWireguard2\\twireguard\\tnwg2\\n'; }}
vward_map_vpns() {{ printf '%s\\n' "$1" | awk -F '\\t' '$1=="I" {{print $2 " " $4}}'; }}
""")
    (tmp / "admission.sh").write_text("vward_component_gate() { :; }\nvward_admission_enter() { :; }\nvward_admission_leave() { :; }\n")
    # The provider answers; every tunnel device fails curl (the guard's own check of the dead one).
    (bin_ / "curl").write_text('#!/bin/sh\ncase "$*" in *"--interface eth3"*) exit 0 ;; esac\nexit 7\n')
    # Keenetic's dns-proxy routes of the lists, from the routes file.
    (tmp / "routes").write_text("")
    (bin_ / "ndmc").write_text(f'#!/bin/sh\necho "$*" >> "{tmp}/ndmc.log"\n'
                               f'[ "$2" = "show running-config" ] && {{ echo dns-proxy; sed "s/^/    /" "{tmp}/routes"; echo "!"; }}\nexit 0\n')
    # The quality summary the guard reads: name dev last_loss last_ms ok_streak samples loss avg jitter up fail_streak
    (bin_ / "quality").write_text(f'#!/bin/sh\ncat "{tmp}/summary"\n')
    # The Panel's helper: «tunnel NAME» moves the routes and changes the profile;
    # «domain-list GROUP TUNNEL» moves one list.
    (bin_ / "helper").write_text(f"""#!/bin/sh
echo "$* by_guard=${{VWARD_TUNNEL_BY_GUARD:-}}" >> "{tmp}/helper.log"
case "$1" in
    tunnel)
        case "$2" in Wireguard0) d=nwg0 ;; Wireguard1) d=nwg1 ;; Wireguard2) d=nwg2 ;; esac
        echo "$2 $d" > "{tmp}/iface" ;;
    domain-list) sed -i "s/^route object-group $2 .*/route object-group $2 $3 auto/" "{tmp}/routes" ;;
    *) exit 64 ;;
esac
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
    if not fallback().startswith("FROM=Wireguard0") or " down" in ((tmp / "ndmc.log").read_text() if (tmp / "ndmc.log").exists() else ""):
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

    # Keenetic's lists with their own tunnel: Games on Wireguard1 moves when Wireguard1 fails
    # two samples in a row; VWARD's group and AdaptiveAuto follow VWARD's tunnel, not this.
    (etc / "tunnel-fallback.disabled").unlink(); (gdir / "state").unlink()
    (tmp / "iface").write_text("Wireguard0 nwg0"); (tmp / "helper.log").write_text("")
    (tmp / "routes").write_text("route object-group Games Wireguard1 auto\nroute object-group Video Wireguard2 auto\n"
                                "route object-group AdaptiveAuto Wireguard1 auto\nroute object-group VwardGroup Wireguard1 auto\n"
                                "route object-group Local ISP auto\n")
    lists = gdir / "lists-fallback"

    def q(w0, w1, w2):
        # ok_streak, fail_streak per tunnel; Wireguard2 is faster than Wireguard0.
        row = lambda n, ms, s: f"Wireguard{n}\tnwg{n}\t{0 if s[0] else 100}\t{ms if s[0] else '-'}\t{s[0]}\t30\t0\t{ms}\t2\t100\t{s[1]}\n"
        return row(0, 60, w0) + row(1, 50, w1) + row(2, 40, w2)

    def route(g):
        return next(l.split()[3] for l in (tmp / "routes").read_text().splitlines() if l.split()[2] == g)

    if run("UP", q((30, 0), (0, 1), (30, 0))) != "ACTION=KEEP_UP" or route("Games") != "Wireguard1" or lists.exists():
        fail("one failed sample is not enough to move a list")
    run("UP", q((30, 0), (0, 2), (30, 0)))
    if route("Games") != "Wireguard2" or route("Video") != "Wireguard2" or not lists.read_text().startswith("Games\tWireguard1\tWireguard2\t"):
        fail(f"the list goes to the best answering tunnel and is remembered: {(tmp / 'routes').read_text()}")
    helper_log = (tmp / "helper.log").read_text()
    if "domain-list Games Wireguard2 by_guard=1" not in helper_log or "AdaptiveAuto" in helper_log or "VwardGroup" in helper_log:
        fail(f"only the list is moved, through the helper: {helper_log}")
    if "|LIST_FALLBACK|list=Games|to=Wireguard2|from=Wireguard1" not in (tmp / "guard.log").read_text():
        fail("the guard log names the list moved")
    before = lists.stat().st_mtime_ns
    run("UP", q((30, 0), (0, 3), (30, 0)))
    if helper_log != (tmp / "helper.log").read_text() or lists.stat().st_mtime_ns != before:
        fail("a list already moved is not moved or written again")
    # Its new tunnel dies too: on to Wireguard0, the first tunnel is still Wireguard1.
    run("UP", q((30, 0), (0, 4), (0, 2)))
    if route("Games") != "Wireguard0" or route("Video") != "Wireguard0" or not lists.read_text().startswith("Games\tWireguard1\tWireguard0\t"):
        fail(f"a list moved on keeps its first tunnel: {lists.read_text() if lists.exists() else ''}")
    # Both answer two minutes: not yet; three: each list comes back to its own first tunnel.
    run("UP", q((30, 0), (2, 0), (2, 0)))
    if route("Games") != "Wireguard0" or route("Video") != "Wireguard0":
        fail("two minutes are not enough to bring a list back")
    run("UP", q((30, 0), (3, 0), (3, 0)))
    if route("Games") != "Wireguard1" or route("Video") != "Wireguard2" or lists.exists() or \
            "|LIST_RETURN|list=Games|to=Wireguard1|from=Wireguard0" not in (tmp / "guard.log").read_text():
        fail("three minutes bring the lists back and nothing is remembered")
    # Someone routes the moved list elsewhere: the guard forgets it and leaves it there.
    run("UP", q((30, 0), (0, 2), (30, 0)))
    (tmp / "routes").write_text((tmp / "routes").read_text().replace("Games Wireguard2", "Games ISP"))
    run("UP", q((30, 0), (5, 0), (30, 0)))
    if route("Games") != "ISP" or lists.exists():
        fail("a list routed elsewhere by hand is forgotten, not brought back")
    # Nothing answers, or the fallback is off: the list stays on its tunnel.
    (tmp / "routes").write_text("route object-group Games Wireguard1 auto\n")
    run("UP", q((30, 0), (0, 2), (0, 2)).replace("Wireguard0\tnwg0\t0\t60\t30", "Wireguard0\tnwg0\t100\t-\t0"))
    if route("Games") != "Wireguard1" or lists.exists():
        fail("with no tunnel answering the list stays")
    (etc / "tunnel-fallback.disabled").write_text("x")
    run("UP", q((30, 0), (0, 2), (30, 0)))
    if route("Games") != "Wireguard1" or lists.exists():
        fail("with the fallback off the list stays")

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
    if summ != ["Wireguard0\tnwg0\t0\t42\t2\t2\t0\t42\t0\t100\t0", "Wireguard1\tnwg1\t100\t-\t0\t2\t100\t-\t-\t0\t2"]:
        fail(f"summary: {summ}")

    # The Panel's tunnel-quality: the tunnels, where VWARD's routes went and the lists moved.
    (tmp / "summary").write_text("Wireguard0\tnwg0\t0\t42\t2\t2\t0\t42\t0\t100\t0\nWireguard1\tnwg1\t100\t-\t0\t2\t100\t-\t-\t0\t2\n")
    (gdir / "fallback").write_text("FROM=Wireguard1\nAT=1759000000\n")
    lists.write_text("Games\tWireguard1\tWireguard0\t1759000100\nbad;x\tWireguard1\tWireguard0\t1\nshort\tWireguard1\n")
    r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], text=True, capture_output=True, timeout=60,
                       env=env | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=tunnel-quality", "JQ": shutil.which("jq"),
                                  "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_TUNNEL_FALLBACK_STATE": str(gdir / "fallback"),
                                  "VWARD_TUNNEL_LISTS_FALLBACK_STATE": str(lists)})
    got = json.loads(r.stdout.split("\n\n", 1)[1])
    if got.get("fallback_from") != "Wireguard1" or got.get("lists_moved") != [{"name": "Games", "from": "Wireguard1", "to": "Wireguard0", "at": 1759000100}]:
        fail(f"tunnel-quality: {got}")
    if [t["fail_streak"] for t in got.get("tunnels", [])] != [0, 2]:
        fail(f"tunnel-quality fail_streak: {got}")
print("TUNNEL_FALLBACK=PASS")
