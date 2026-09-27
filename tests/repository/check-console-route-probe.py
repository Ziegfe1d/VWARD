#!/usr/bin/env python3
"""«Проверить адрес»: a domain is found in a Keenetic list with its subdomains,
an exclude takes it out, and the answer names the list and where it goes."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNING = """object-group fqdn domain-list1
    description "YouTube"
    include youtube.com
    exclude music.youtube.com
!
object-group fqdn AdaptiveAuto
    include ggpht.com
!
dns-proxy
    route object-group domain-list1 Wireguard0 auto
    route object-group AdaptiveAuto Wireguard0 auto
!
"""


def fail(msg):
    raise SystemExit(f"CONSOLE_ROUTE_PROBE=FAIL: {msg}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / "running").write_text(RUNNING)
    ndmc = tmp / "ndmc"
    ndmc.write_text(f'#!/bin/sh\n[ "$2" = "show running-config" ] && cat "{tmp}/running"\n')
    ndmc.chmod(0o755)
    env = os.environ | {"REQUEST_METHOD": "GET", "JQ": shutil.which("jq"), "VWARD_NDMC": str(ndmc), "VWARD_ROOT_PREFIX": str(tmp / "root")}

    def probe(value):
        r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=env | {"QUERY_STRING": "action=route-probe&type=domain&value=" + value},
                           text=True, capture_output=True, timeout=60)
        return json.loads(r.stdout.split("\n\n", 1)[1])

    want = {"youtube.com": (["domain-list1"], {"domain-list1": "YouTube"}), "www.youtube.com": (["domain-list1"], {"domain-list1": "YouTube"}),
            "music.youtube.com": ([], {}), "yt3.ggpht.com": (["AdaptiveAuto"], {}), "ya.ru": ([], {}), "notyoutube.com": ([], {})}
    for value, (groups, names) in want.items():
        x = probe(value)
        if not x.get("ok") or x["groups"] != groups or x["names"] != names or [r["group"] for r in x["routes"]] != groups:
            fail(f"{value}: {x}")
    if probe("x;reboot").get("error") != "invalid_domain":
        fail("bad input must be refused")

js = (ROOT / "web/assets/vward-console.js").read_text()
for need in ("function probeText(", "probeText(RPROBE)", "идёт напрямую, через провайдера"):
    if need not in js:
        fail(f"the Panel result is missing: {need}")
print("CONSOLE_ROUTE_PROBE=PASS")
