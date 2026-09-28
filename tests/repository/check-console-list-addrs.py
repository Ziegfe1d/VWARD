#!/usr/bin/env python3
"""Panel page «IP-адреса»: the addresses Keenetic learned for one list, by domain.

api.cgi action=list-addrs reads Keenetic's RCI answer (as a real KN-1913 gives
it: every list at once, one element as an object, several as an array) and
returns only the asked list.
"""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(msg):
    raise SystemExit(f"CONSOLE_LIST_ADDRS=FAIL: {msg}")


RCI = {"group": [
    {"group-name": "AdaptiveAuto", "ipv4-addresses-count": 1, "entry": {"fqdn": "a.example", "ipv4": {"address": "192.0.2.1", "ttl": 9}}},
    {"group-name": "domain-list0", "enabled": True, "ipv4-addresses-count": 3, "ipv6-addresses-count": 1, "fqdn-count": 3, "entry": [
        {"fqdn": "tg.dev", "type": "config", "ipv4": [{"address": "149.154.167.99", "ttl": 43, "last-updated": 54324}], "ipv6": []},
        {"fqdn": "usercontent.dev", "type": "config", "ipv4": [], "ipv6": []},
        {"fqdn": "graph.org", "type": "config", "ipv4": {"address": "149.154.164.13"}, "ipv6": [{"address": "2001:db8::13"}]}]}]}

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / "rci.json").write_text(json.dumps(RCI))
    curl = tmp / "curl"
    curl.write_text(f'#!/bin/sh\nfor u do :; done\necho "$u" >> "{tmp}/urls"\ncase "$u" in */show/object-group/fqdn) cat "{tmp}/rci.json" ;; *) exit 22 ;; esac\n')
    curl.chmod(0o755)
    env = os.environ | {"REQUEST_METHOD": "GET", "JQ": shutil.which("jq"), "CURL": str(curl), "VWARD_NDMC": "/bin/false",
                        "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_RCI_BASE": "http://127.0.0.1:79/rci"}

    def get(name):
        r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=env | {"QUERY_STRING": "action=list-addrs&name=" + name},
                           text=True, capture_output=True)
        return json.loads(r.stdout.split("\n\n", 1)[1])

    got = get("domain-list0")
    want = {"ok": True, "name": "domain-list0", "v4": 3, "v6": 1, "entries": [
        {"fqdn": "tg.dev", "v4": ["149.154.167.99"], "v6": []},
        {"fqdn": "usercontent.dev", "v4": [], "v6": []},
        {"fqdn": "graph.org", "v4": ["149.154.164.13"], "v6": ["2001:db8::13"]}]}
    if got != want:
        fail(f"domain-list0: {got}")
    got = get("AdaptiveAuto")
    if got.get("entries") != [{"fqdn": "a.example", "v4": ["192.0.2.1"], "v6": []}]:
        fail(f"one entry and one address come as objects: {got}")
    if get("domain-list9").get("error") != "list_not_found":
        fail("an unknown list")
    for bad in ("x;reboot", "../x", ""):
        if get(bad).get("error") != "invalid_group":
            fail(f"{bad!r} must be refused")
    # A list made in Keenetic's command line may have any plain name: a missing one is not found.
    if get("ISP").get("error") != "list_not_found":
        fail("a plain name that is not a list")

js = (ROOT / "web/assets/vward-console.js").read_text()
for need in ("apiGet('list-addrs'", "'ip-' + l.name", "function addrPage("):
    if need not in js:
        fail(f"the Panel page is missing: {need}")
print("CONSOLE_LIST_ADDRS=PASS")
