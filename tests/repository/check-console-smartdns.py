#!/usr/bin/env python3
"""Smart DNS guard: lists-data flags tunnel lists that hold Smart DNS domains,
the switch is written by the Console helper, and AdaptiveAuto skips those domains."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "components/route-engine/scripts/vward-route-engine.sh").read_text()

RUNNING = """dns-proxy
    route object-group domain-list4 ISP auto
    route object-group domain-list9 Wireguard0 auto
    route object-group domain-list7 Wireguard0 auto
    route object-group domain-list5 Wireguard0 auto
    https upstream https://x.example/dns-query dnsm on ISP domain gemini.google.com
    https upstream https://x.example/dns-query dnsm on ISP domain anthropic.com
!
object-group fqdn domain-list4
    include claude.ai
    include anthropic.com
!
object-group fqdn domain-list9
    include google.com
!
object-group fqdn domain-list7
    include telegram.org
!
object-group fqdn domain-list5
    include api.anthropic.com
!
"""


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    ndmc = tmp / "ndmc"
    ndmc.write_text(f'#!/bin/sh\n[ "$2" = "show running-config" ] && cat "{tmp}/running"\n'
                    f'[ "$2" = "show object-group fqdn" ] && printf "            group: \\n               group-name: domain-list9\\n                  enabled: yes\\n     ipv4-addresses-count: 7\\n\\n            group: \\n               group-name: domain-list4\\n     ipv4-addresses-count: 0\\n"\nexit 0\n')
    ndmc.chmod(0o755)
    (tmp / "running").write_text(RUNNING)
    lists_conf = tmp / "etc/route-engine/domain-lists.conf"
    lists_conf.parent.mkdir(parents=True)
    env = os.environ | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=lists-data", "JQ": shutil.which("jq"),
                        "VWARD_NDMC": str(ndmc), "VWARD_PROFILE_LIB": "/nonexistent", "VWARD_TUNNEL_INTERFACE": "Wireguard0",
                        "VWARD_DOMAIN_LISTS_CONF": str(lists_conf)}

    def lists():
        r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=env, text=True, capture_output=True)
        return json.loads(r.stdout.split("\n\n", 1)[1])

    data = lists()
    addrs = {l["name"]: l["addresses"] for l in data["lists"]}
    if addrs != {"domain-list4": 0, "domain-list9": 7, "domain-list7": None, "domain-list5": None}:
        fail(f"learned addresses per list: {addrs}")
    got = {l["name"]: l["smartdns_conflict"] for l in data["lists"]}
    # google.com in a tunnel list takes gemini.google.com; api.anthropic.com sits under anthropic.com.
    if got != {"domain-list4": False, "domain-list9": True, "domain-list7": False, "domain-list5": True}:
        fail(f"conflicts: {got}")
    if data["smartdns_domains"] != ["gemini.google.com", "anthropic.com"] or data["smartdns_guard"] is not True:
        fail(f"Smart DNS summary: {data['smartdns_domains']} {data['smartdns_guard']}")
    lists_conf.write_text("smartdns_guard=0\n")
    if lists()["smartdns_guard"] is not False:
        fail("the switch state is not reported")
    lists_conf.write_text("")

    # Smart DNS kept in AdGuard Home only (the Keenetic DoH rows removed): the
    # domains still count, the Keenetic row limit counts Keenetic rows only.
    (tmp / "running").write_text("\n".join(l for l in RUNNING.splitlines() if "https upstream" not in l) + "\n")
    agh = tmp / "AdGuardHome.yaml"
    agh.write_text("""http:
  address: 192.168.1.1:3001
dns:
  upstream_dns:
    - '[/anthropic.com/claude.ai/]https://tr.example:8443/dns-query/x'
    - "[/Gemini.Google.com/]tls://dns.example"
    - '[/lan/]192.168.1.1'
    - https://dns.nextdns.io/abc
filtering:
  upstream_dns:
    - '[/not-dns.example/]https://x'
""")
    env |= {"VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"), "VWARD_ADGUARD_CONFIG": str(agh)}
    data = lists()
    if data["smartdns_domains"] != ["anthropic.com", "claude.ai", "gemini.google.com"] or data["doh_used"] != 0:
        fail(f"Smart DNS from AdGuard Home: {data['smartdns_domains']} used={data['doh_used']}")
    if data["smartdns_sources"] != {"keenetic": [], "adguard": ["anthropic.com", "claude.ai", "gemini.google.com"]}:
        fail(f"sources: {data['smartdns_sources']}")
    got = {l["name"]: l["smartdns_conflict"] for l in data["lists"]}
    if got != {"domain-list4": False, "domain-list9": True, "domain-list7": False, "domain-list5": True}:
        fail(f"conflicts from AdGuard Home domains: {got}")

# The engine keeps a list of Smart DNS domains and checks it before AdaptiveAuto.
host = ENGINE[ENGINE.index("handle_host()\n"):]
if "vward_agh_smartdns_domains\n        } | sort -u > \"$SMARTDNS\"" not in ENGINE:
    fail("the engine must add Smart DNS domains kept in AdGuard Home")
if host.index('parent_list_match "$HOST" "$SMARTDNS"') > host.index('if is_adaptive "$HOST"'):
    fail("Smart DNS domains must be skipped before AdaptiveAuto handles a host")
awk = ENGINE[ENGINE.index("                /^[^ \\t!]/ {ctx"):ENGINE.index("' \"$CFG\"\n            vward_agh_smartdns_domains")]
r = subprocess.run(["awk", "\n".join(awk.splitlines())], input=RUNNING, text=True, capture_output=True)
if sorted(r.stdout.split()) != ["anthropic.com", "gemini.google.com"]:
    fail(f"engine Smart DNS extraction: {r.stdout!r}")

print("CONSOLE_SMARTDNS=PASS")
