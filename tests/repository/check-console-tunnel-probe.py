#!/usr/bin/env python3
"""Console: the on-demand tunnel check reads the peer from the router config,
binds curl and ping to the tunnel device and never accepts a foreign name."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

RUNNING = """interface Wireguard0
    description AWG2_DE
    ip address 10.8.0.2 255.255.255.255
    wireguard listen-port 51820
    wireguard asc 4 40 70 0 0 1 2 3 4
    wireguard peer AAAA= !server
        endpoint de37g.example.site:44486
        keepalive-interval 25
        allow-ips 0.0.0.0 0.0.0.0
    !
    up
!
interface Wireguard1
    wireguard peer BBBB=
        endpoint 203.0.113.5:51820
    !
!
"""
PING_OK = """PING 1.1.1.1 (1.1.1.1): 56 data bytes
64 bytes from 1.1.1.1: seq=0 ttl=57 time=41.2 ms

--- 1.1.1.1 ping statistics ---
4 packets transmitted, 3 packets received, 25% packet loss
round-trip min/avg/max = 40.1/41.5/43.0 ms
"""


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    tools = tmp / "tools"; tools.mkdir()
    (tmp / "sys/nwg0").mkdir(parents=True); (tmp / "sys/nwg1").mkdir()
    (tmp / "running").write_text(RUNNING)
    (tmp / "ping.out").write_text(PING_OK)
    (tools / "ndmc").write_text(f'#!/bin/sh\n[ "$2" = "show running-config" ] && cat "{tmp}/running"\n')
    (tools / "ping").write_text(f'#!/bin/sh\necho "$*" >> "{tmp}/ping.args"\ncat "{tmp}/ping.out"\n')
    (tools / "curl").write_text(f'#!/bin/sh\necho "$*" >> "{tmp}/curl.args"\ncat "{tmp}/curl.out" 2>/dev/null\n')
    for f in ("ndmc", "ping", "curl"):
        (tools / f).chmod(0o755)
    # The device map as vward-device-profile.sh returns it: logical name -> kernel device.
    (tmp / "profile.sh").write_text(
        "vward_profile_load(){ return 0; }\nvward_valid_ifname(){ case \"$1\" in ''|*[!A-Za-z0-9_.:-]*) return 1;; esac; }\n"
        "vward_device_map(){ printf 'I\\tWireguard0\\twireguard\\tnwg0\\nI\\tWireguard1\\twireguard\\tnwg1\\nI\\tWireguard2\\twireguard\\tnwg2\\nI\\tISP\\tethernet\\teth3\\n'; }\n"
        "vward_map_tunnels(){ printf '%s\\n' \"$1\" | awk -F '\\t' '$1==\"I\" && tolower($3)==\"wireguard\" {print $2 \" \" $4}'; }\n")
    (tmp / "curl.out").write_text('{"ip":"198.51.100.7","city":"Frankfurt am Main","region":"Hesse","country":"DE","org":"AS3320 Example"}')

    env = os.environ | {"REQUEST_METHOD": "GET", "JQ": shutil.which("jq"), "CURL": str(tools / "curl"),
                        "VWARD_NDMC": str(tools / "ndmc"), "VWARD_PING": str(tools / "ping"), "VWARD_SYSFS_NET": str(tmp / "sys"),
                        "VWARD_PROFILE_LIB": str(tmp / "profile.sh"), "VWARD_ROOT_PREFIX": str(tmp / "root")}

    def probe(name):
        r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=env | {"QUERY_STRING": "action=tunnel-probe&name=" + name},
                           text=True, capture_output=True)
        if r.returncode != 0:
            fail(f"{name}: rc={r.returncode} {r.stderr}")
        return json.loads(r.stdout.split("\n\n", 1)[1])

    got = probe("Wireguard0")
    want = {"ok": True, "name": "Wireguard0", "device": "nwg0",
            "server": {"host": "de37g.example.site", "port": 44486, "keepalive": 25, "awg": True},
            "exit": {"ip": "198.51.100.7", "city": "Frankfurt am Main", "region": "Hesse", "country": "DE", "org": "AS3320 Example"},
            "ping": {"target": "1.1.1.1", "loss": 25, "avg_ms": 41.5}}
    if got != want:
        fail(f"probe result: {got}")
    if "--interface nwg0" not in (tmp / "curl.args").read_text() or "-I nwg0" not in (tmp / "ping.args").read_text():
        fail("curl and ping must be bound to the tunnel device")

    # A second tunnel: plain WireGuard, no keepalive; the exit service is down; ping lost.
    (tmp / "curl.out").unlink(); (tmp / "ping.out").write_text("4 packets transmitted, 0 packets received, 100% packet loss\n")
    got = probe("Wireguard1")
    if got["server"] != {"host": "203.0.113.5", "port": 51820, "keepalive": None, "awg": False} or got["exit"] is not None or got["ping"]["loss"] != 100 or got["ping"]["avg_ms"] is not None:
        fail(f"plain tunnel result: {got}")

    # Wireguard2 is in the map but has no device; ISP is not a tunnel.
    for bad in ("ISP", "Wireguard0;reboot", "Wireguard", "../x", "Wireguard2", ""):
        got = probe(bad)
        if got.get("ok") or got.get("error") not in ("invalid_tunnel", "tunnel_device_missing"):
            fail(f"{bad!r} must be refused: {got}")

print("CONSOLE_TUNNEL_PROBE=PASS")
