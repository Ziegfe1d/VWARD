#!/usr/bin/env python3
"""fix.35.3: the DNS page (ai-data) tells the chosen way from what the router holds.

02.11.2026: the old Smart DNS server's 35 rows lived in AdGuard Home only, the own address was gone:
the page showed «Сервер: не задан» and no button to take the rows out. ChatGPT read «Провайдер»
while a manual list with chatgpt.com went through VPN. Now ai-data lists every server in use (Keenetic
lines and AdGuard Home rows, host only, with counts), says which server the liveness answer is about,
and names, for each service, the other lists that route its main domains. Nothing is switched.
"""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "web/cgi-bin/api.cgi"
OLD = "https://old-smartdns.example:8443/dns-query/expired-secret"


def fail(msg):
    raise SystemExit("CONSOLE_AI_DATA=FAIL: " + msg)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    running = ("object-group fqdn domain-list7\n    description \"ChatGPT OpenAI (ISP)\"\n    include chatgpt.com\n    include openai.com\n!\n"
               "object-group fqdn svc-claude\n    include claude.ai\n!\n"
               "dns-proxy\n    https upstream https://keen.example/dns-query domain copilot.microsoft.com\n"
               "    route object-group domain-list7 Wireguard0 auto\n    route object-group svc-claude Wireguard0 auto\n!\n")
    ndmc = tmp / "ndmc"
    ndmc.write_text("#!/bin/sh\n[ \"$2\" = 'show running-config' ] || exit 1\ncat " + str(tmp / "running.cfg") + "\n")
    ndmc.chmod(0o755)
    (tmp / "running.cfg").write_text(running)
    yaml = tmp / "agh.yaml"
    yaml.write_text("dns:\n  upstream_dns:\n    - 9.9.9.10\n    - 149.112.112.10\n    - '[/claude.ai/]" + OLD + "'\n    - '[/chatgpt.com/oaistatic.com/]" + OLD + "'\n")
    etc = tmp / "etc"; (etc / "services").mkdir(parents=True)
    (etc / "smartdns.conf").write_text("SMARTDNS_STORE=auto\n")
    (etc / "services/enabled.tsv").write_text("claude.ai\tsvc-claude\tauto\n")
    # The two AdGuard Home readers of the production library, nothing else of it.
    lib = (ROOT / "components/runtime/lib/vward-device-profile.sh").read_text()
    start = lib.index("vward_agh_smartdns_domains()")
    end = lib.index("# vward_doh_alive URL")
    (tmp / "profile.sh").write_text("vward_profile_load(){ VWARD_WAN_INTERFACE=GigabitEthernet1; return 0; }\n" + lib[start:end])
    env = os.environ | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=ai-data", "JQ": shutil.which("jq"),
                        "VWARD_PROFILE_LIB": str(tmp / "profile.sh"), "VWARD_ROOT_PREFIX": str(tmp / "root"),
                        "VWARD_NDMC": str(ndmc), "VWARD_CONSOLE_CACHE_TTL": "0", "VWARD_CONSOLE_ETC": str(etc),
                        "VWARD_ADGUARD_CONFIG": str(yaml), "VWARD_DOH_ALIVE": "0",
                        "VWARD_SERVICES_FETCHED": str(tmp / "none.json"),
                        "VWARD_SERVICES_BUNDLED": str(ROOT / "components/console/data/services-catalog.json")}
    r = subprocess.run(["sh", str(API)], env=env, text=True, capture_output=True, timeout=120)
    if r.returncode:
        fail("rc=%d %s" % (r.returncode, r.stderr[-400:]))
    body = r.stdout.split("\n\n", 1)[-1]
    if "expired-secret" in r.stdout:
        fail("a server token reached the Panel")
    d = json.loads(body)
    if not d.get("ok"):
        fail("ai-data: " + body[:300])
    sd = d["smartdns"]
    rows = {x["host"]: x for x in sd.get("server_rows", [])}
    if set(rows) != {"keen.example", "old-smartdns.example"}:
        fail("RED: every server in use must be listed, AdGuard Home's too: " + json.dumps(sd))
    if rows["old-smartdns.example"]["agh"] != 3 or rows["old-smartdns.example"]["keenetic"] != 0 or rows["old-smartdns.example"]["own"]:
        fail("the old server's counts: " + json.dumps(rows))
    if rows["keen.example"]["keenetic"] != 1 or "old-smartdns.example" not in sd["servers"]:
        fail("Keenetic's server and the hosts list: " + json.dumps(sd))
    svc = {s["id"]: s for s in d["services"]}
    gpt = next((s for i, s in svc.items() if "chatgpt.com" in s.get("roots", [])), None)
    if not gpt:
        fail("no catalog service with chatgpt.com: " + ", ".join(svc))
    lists = gpt.get("lists", [])
    if not any(l["group"] == "domain-list7" and l["route"] == "Wireguard0" and l["title"] == "ChatGPT OpenAI (ISP)" for l in lists):
        fail("RED: the list sending ChatGPT's domains through VPN must be named: " + json.dumps(gpt))
    claude = svc.get("claude.ai")
    if not claude or claude["via"] != "vpn" or claude.get("lists"):
        fail("the service's own list is its way, not a conflict: " + json.dumps(claude))
print("CONSOLE_AI_DATA=PASS")
