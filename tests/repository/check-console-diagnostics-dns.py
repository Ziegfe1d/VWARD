#!/usr/bin/env python3
"""Diagnostics: the DNS chain, VWARD's files as installed, Smart DNS from AdGuard Home.

- Keenetic forwarding to AdGuard Home passes; AdGuard Home forwarding back to
  the router is a loop (FAIL); AdGuard Home answering on port 53 itself is a
  warning (Keenetic does not see the answers its domain routes learn from).
- Every file the updater recorded is compared with its sha256: a changed file
  is a warning (an update replaces hand edits), a missing one a failure.
- Smart DNS kept only in AdGuard Home is still checked, not "not used".
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    tools = tmp / "tools"; tools.mkdir()
    running = tmp / "running"
    ndmc = tools / "ndmc"; ndmc.write_text(f'#!/bin/sh\n[ "$2" = "show running-config" ] && cat "{running}"\n'); ndmc.chmod(0o755)
    (tools / "nslookup").write_text("#!/bin/sh\nexit 1\n"); (tools / "nslookup").chmod(0o755)
    yaml = tmp / "AdGuardHome.yaml"
    root = tmp / "root"
    files = {"/opt/bin/vward-a.sh": b"a\n", "/opt/bin/vward-b.sh": b"b\n"}
    for f, body in files.items():
        (root / f.lstrip("/")).parent.mkdir(parents=True, exist_ok=True)
        (root / f.lstrip("/")).write_bytes(body)
    comp = root / "opt/var/lib/vward/updater/components.json"
    comp.parent.mkdir(parents=True)
    comp.write_text(json.dumps({"components": {"x": {"files": {f: hashlib.sha256(b).hexdigest() for f, b in files.items()}}}}))
    env = os.environ | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=diagnostics", "JQ": shutil.which("jq"), "CURL": "/bin/false",
                        "PATH": f"{tools}:{os.environ['PATH']}", "VWARD_NDMC": str(ndmc),
                        "VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"),
                        "VWARD_ADGUARD_CONFIG": str(yaml), "VWARD_ROOT_PREFIX": str(root), "VWARD_LAN_ADDRESS": "192.168.1.1"}

    def diag(conf, up, port):
        running.write_text(conf)
        yaml.write_text(f"http:\n  address: 192.168.1.1:3001\ndns:\n  bind_hosts:\n    - 192.168.1.1\n  port: {port}\n  upstream_dns:\n"
                        + "".join(f"    - '{u}'\n" for u in up))
        r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=env, text=True, capture_output=True)
        return {c["id"]: c for c in json.loads(r.stdout.split("\n\n", 1)[1])["checks"]}

    AET = "[/claude.ai/]https://tr.example:8443/dns-query/x"
    d = diag("ip name-server 192.168.1.1:65053\n!\n", ["9.9.9.10", AET], 65053)
    if d["dns-chain"]["status"] != "PASS" or "Keenetic → AdGuard Home (192.168.1.1:65053) → 9.9.9.10" not in d["dns-chain"]["detail"]:
        fail(f"chain Keenetic → AdGuard Home: {d['dns-chain']}")
    if "не используется" in d["smartdns"]["detail"]:
        fail(f"Smart DNS kept in AdGuard Home must be checked: {d['smartdns']}")
    if d["files"]["status"] != "PASS" or "Все 2 файлов" not in d["files"]["detail"]:
        fail(f"files as installed: {d['files']}")

    d = diag("ip name-server 192.168.1.1:65053\n!\n", ["192.168.1.1", AET], 65053)
    if d["dns-chain"]["status"] != "FAIL" or "петля" not in d["dns-chain"]["detail"]:
        fail(f"a loop back to the router: {d['dns-chain']}")
    d = diag("!\n", ["udp://127.0.0.1:53"], 65053)
    if d["dns-chain"]["status"] != "FAIL":
        fail(f"127.0.0.1:53 is the router too: {d['dns-chain']}")
    d = diag("!\n", ["9.9.9.10"], 53)
    if d["dns-chain"]["status"] != "WARN" or "порту 53" not in d["dns-chain"]["detail"]:
        fail(f"AdGuard Home on port 53: {d['dns-chain']}")

    # AdGuard Home out of the chain: what the DNS guard knows (taken out, why, when; back on its own).
    chain = tmp / "chain"; chain.mkdir()
    env["VWARD_DNS_CHAIN_STATE"] = str(chain)
    env["VWARD_DNS_GUARD_CONF"] = str(tmp / "dns-guard.conf")
    d = diag("ip name-server 89.207.216.1\n!\n", ["9.9.9.10", AET], 65053)
    if d["dns-chain"]["status"] != "WARN" or "вернёт его" not in d["dns-chain"]["detail"]:
        fail(f"out of the chain, not yet back: {d['dns-chain']}")
    if d["smartdns"]["status"] != "WARN" or "не в цепочке" not in d["smartdns"]["detail"]:
        fail(f"Smart DNS in AdGuard Home does nothing out of the chain: {d['smartdns']}")
    (chain / "reason").write_text("loop\n"); (chain / "since").write_text("1759600000\n")
    d = diag("!\n", ["9.9.9.10"], 65053)
    if "перезапускался по кругу" not in d["dns-chain"]["detail"] or "вернётся сам" not in d["dns-chain"]["detail"]:
        fail(f"taken out for a restart loop: {d['dns-chain']}")
    (tmp / "dns-guard.conf").write_text("CHAIN=0\n")
    if "выключен в настройках" not in diag("!\n", ["9.9.9.10"], 65053)["dns-chain"]["detail"]:
        fail("CHAIN=0: the owner's choice is named")
    (tmp / "dns-guard.conf").unlink(); shutil.rmtree(chain)

    (root / "opt/bin/vward-b.sh").write_text("patched\n")
    d = diag("ip name-server 192.168.1.1:65053\n!\n", ["9.9.9.10"], 65053)
    if d["files"]["status"] != "WARN" or "1 из 2" not in d["files"]["detail"] or "vward-b.sh" not in d["files"]["detail"]:
        fail(f"a hand-edited file: {d['files']}")
    (root / "opt/bin/vward-a.sh").unlink()
    if diag("!\n", ["9.9.9.10"], 65053)["files"]["status"] != "FAIL":
        fail("a missing file is a failure")

    # VPN tunnels: each on its own; one switched on but silent is named (a count alone said «Норма»).
    ifs = tmp / "ifs.json"
    curl = tools / "curl"
    curl.write_text(f'#!/bin/sh\nfor a; do case "$a" in */show/interface) cat "{ifs}"; exit 0 ;; esac; done\nexit 7\n'); curl.chmod(0o755)
    env["CURL"] = str(curl)
    ifs.write_text(json.dumps({"OpkgTun2": {"type": "OpkgTun", "description": "de-vless", "state": "up", "connected": "yes"},
                               "OpkgTun3": {"type": "OpkgTun", "description": "awg2-fi", "state": "up", "connected": "no"},
                               "Wireguard1": {"type": "Wireguard", "description": "old", "state": "down", "connected": "no"}}))
    w = diag("!\n", ["9.9.9.10"], 65053)["wg"]
    if w["status"] != "WARN" or w["detail"] != "туннелей: 3; не на связи: awg2-fi; выключено: 1":
        fail(f"a silent tunnel is named: {w}")
    ifs.write_text(json.dumps({"OpkgTun2": {"type": "OpkgTun", "description": "de-vless", "state": "up", "connected": "yes"}}))
    w = diag("!\n", ["9.9.9.10"], 65053)["wg"]
    if w["status"] != "PASS" or "все включённые на связи" not in w["detail"] or "код" in w["detail"]:
        fail(f"all connected: {w}")

print("CONSOLE_DIAGNOSTICS_DNS=PASS")
