#!/usr/bin/env python3
"""Services: a service switched on becomes a Keenetic domain list routed to the
tunnel; off removes it and gives the router back exactly as it was; a refused
command leaves nothing behind; the daily catalog keeps the lists in step."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"

RUNNING = "\n".join([
    "interface Wireguard0", "!",
    "dns-proxy",
    "    route object-group domain-list0 Wireguard0 auto",
    "!",
    "object-group fqdn domain-list0", "    description \"Telegram\"", "    include telegram.org", "!",
    "object-group fqdn AdaptiveAuto", "    include example.org", "!",
]) + "\n"

CATALOG = {
    "schema": 1, "source": "iplist", "limit": 300,
    "categories": [{"id": "ai", "title": "Нейросети"}, {"id": "video", "title": "Видео"}],
    "services": [
        {"id": "claude.ai", "category": "ai", "title": "Claude", "domains": ["anthropic.com", "claude.ai", "claude.com"]},
        {"id": "big.tv", "category": "video", "title": "Big", "domains": ["d%d.big.tv" % i for i in range(301)], "too_big": True},
        {"id": "bad.tv", "category": "video", "title": "Bad", "domains": ["ok.tv", "x;reboot.tv"]},
    ],
}

# Fake Keenetic CLI over a running-config text.  .mode-limit caps includes per list.
FAKE_NDMC = r'''#!/usr/bin/env python3
import re, sys
from pathlib import Path
cfg = Path("@CFG@")
cmd = sys.argv[2]
with open(str(cfg) + ".log", "a") as log:
    log.write(cmd + "\n")
text = cfg.read_text()
if cmd == "show running-config":
    print(text, end=""); sys.exit(0)
if cmd == "system configuration save":
    print("saved"); sys.exit(0)
lines = text.splitlines()
def blocks():
    out, cur = {}, None
    for i, l in enumerate(lines):
        if l.startswith("object-group fqdn "): cur = l.split()[2]; out[cur] = [i, None]
        elif l == "!" and cur: out[cur][1] = i; cur = None
    return out
neg = cmd.startswith("no ")
w = (cmd[3:] if neg else cmd).split(" ")
def save(): cfg.write_text("\n".join(lines) + "\n"); print("ok"); sys.exit(0)
if w[:2] == ["object-group", "fqdn"]:
    g = w[2]; b = blocks()
    if len(w) == 3:
        if neg:
            if g not in b: print("error: no such entry"); sys.exit(0)
            s, e = b[g]; del lines[s:e + 1]; save()
        if g not in b: lines += ["object-group fqdn " + g, "!"]
        save()
    if g not in b: print("error: no such entry"); sys.exit(0)
    s, e = b[g]
    if w[3] == "description":
        lines.insert(s + 1, "    description " + " ".join(w[4:])); save()
    if w[3] == "include":
        inc = "    include " + w[4]
        if neg:
            if inc in lines[s:e]: lines.remove(inc)
            save()
        lim = Path(str(cfg) + ".mode-limit")
        if lim.exists() and sum(1 for l in lines[s:e] if l.startswith("    include ")) >= int(lim.read_text()):
            print("error: limit of the list reached"); sys.exit(0)
        if inc not in lines[s:e]: lines.insert(e, inc)
        save()
if w[:1] == ["dns-proxy"]:
    start = lines.index("dns-proxy"); end = lines.index("!", start)
    r = w[1:]
    if r[:1] == ["no"]:
        g, t = r[3], r[4]
        lines[start + 1:end] = [l for l in lines[start + 1:end] if l.split()[:4] != ["route", "object-group", g, t]]
        save()
    if r[:2] == ["route", "object-group"]:
        lines.insert(start + 1, "    " + " ".join(r)); save()
print("Command::Base: error[7]: syntax error")
'''

DEVICE_CONF = """VWARD_LAN_ADDRESS=10.77.0.1
VWARD_LAN_SUBNET=10.77.0.0/24
VWARD_LAN_DEVICE=br0
VWARD_LAN_INTERFACE=Bridge0
VWARD_WAN_DEVICE=eth3
VWARD_WAN_INTERFACE=GigabitEthernet1
VWARD_TUNNEL_INTERFACE=Wireguard0
VWARD_TUNNEL_DEVICE=nwg0
"""


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    tools = tmp / "tools"; tools.mkdir()
    cfg = tmp / "running.cfg"; cfg.write_text(RUNNING)
    ndmc = tools / "ndmc"; ndmc.write_text(FAKE_NDMC.replace("@CFG@", str(cfg))); ndmc.chmod(0o755)
    served = tmp / "served.json"
    curl = tools / "curl"
    curl.write_text("#!/bin/sh\nout=\nwhile [ $# -gt 0 ]; do [ \"$1\" = -o ] && out=$2; shift; done\n"
                    f"[ -f {served} ] || exit 22\ncp {served} \"$out\"\n")
    curl.chmod(0o755)
    devconf = tmp / "device.conf"; devconf.write_text(DEVICE_CONF); devconf.chmod(0o600)
    bundled = tmp / "bundled.json"; bundled.write_text(json.dumps(CATALOG))
    etc = tmp / "etc"
    (tmp / "root/tmp").mkdir(parents=True)
    env = os.environ | {
        "VWARD_NDMC": str(ndmc), "VWARD_CURL_BIN": str(curl), "VWARD_DEVICE_CONFIG": str(devconf),
        "VWARD_DEVICE_CONFIG_OWNER_UID": str(os.getuid()),
        "VWARD_DEVICE_MAP_CACHE": str(tmp / "map.tsv"), "VWARD_SYSFS_NET": str(tmp / "sys"),
        "VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"),
        "VWARD_ROUTE_STATE": str(tmp / "route"), "VWARD_CONSOLE_ETC": str(etc),
        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
        "VWARD_ADGUARD_CONFIG": str(tmp / "no-adguard.yaml"), "VWARD_ADS_CONTROL_BIN": str(tmp / "no-ads-control"),
        "VWARD_SERVICES_BUNDLED": str(bundled), "VWARD_SERVICES_FETCHED": str(tmp / "fetched/catalog.json"),
        "VWARD_SERVICES_URL": "https://example.invalid/services-catalog.json",
    }
    state = etc / "services/enabled.tsv"

    def run(*args, expect, rc=None):
        r = subprocess.run(["sh", str(HELPER), *args], env=env, text=True, capture_output=True)
        out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        if out != expect:
            fail(f"{args}: {out!r} != {expect!r} (rc={r.returncode}) {r.stderr.strip()[-300:]}")
        if rc is not None and r.returncode != rc:
            fail(f"{args}: rc {r.returncode} != {rc}")
        if (tmp / "change.lock").exists():
            fail(f"{args}: change lock left behind")

    def group(name):
        lines = cfg.read_text().splitlines()
        if "object-group fqdn " + name not in lines:
            return None
        s = lines.index("object-group fqdn " + name)
        e = lines.index("!", s)
        return lines[s + 1:e]

    # Input and preconditions never touch the router.
    run("service", "on", "a;b", "auto", expect="error=invalid_service", rc=64)
    run("service", "on", "claude.ai", "x;y", expect="error=invalid_value", rc=64)
    run("service", "on", "claude.ai", "Wireguard9", expect="error=unknown_tunnel", rc=64)
    run("service", "on", "nope.com", "auto", expect="error=unknown_service", rc=64)
    run("service", "on", "big.tv", "auto", expect="error=service_too_big", rc=64)
    run("service", "on", "bad.tv", "auto", expect="error=unknown_service", rc=64)
    run("service", "tunnel", "claude.ai", "auto", expect="error=service_not_enabled", rc=64)
    run("service", "off", "claude.ai", expect="result=unchanged", rc=0)
    run("service", "dance", "claude.ai", "auto", expect="error=invalid_operation", rc=64)
    if cfg.read_text() != RUNNING:
        fail("a refused request changed the router")

    # On: a new Keenetic list with the service's name, its domains, routed to the tunnel.
    run("service", "on", "claude.ai", "auto", expect="result=changed", rc=0)
    g = group("domain-list1")
    if g != ['    description "Claude"', "    include anthropic.com", "    include claude.ai", "    include claude.com"]:
        fail(f"service list: {g}")
    if "    route object-group domain-list1 Wireguard0 auto" not in cfg.read_text():
        fail("service list is not routed to the tunnel")
    if state.read_text() != "claude.ai\tdomain-list1\tauto\n":
        fail(f"state: {state.read_text()!r}")
    run("service", "on", "claude.ai", "Wireguard0", expect="result=changed", rc=0)
    run("service", "tunnel", "claude.ai", "auto", expect="result=changed", rc=0)
    if cfg.read_text().count("route object-group domain-list1 ") != 1:
        fail("the tunnel change doubled the route")

    # Off: the router is exactly as before.
    run("service", "off", "claude.ai", expect="result=changed", rc=0)
    if cfg.read_text() != RUNNING:
        fail("off did not restore the router:\n" + cfg.read_text())
    if state.read_text() != "":
        fail(f"state after off: {state.read_text()!r}")

    # Keenetic refuses an include (list limit): nothing stays behind.
    Path(str(cfg) + ".mode-limit").write_text("2")
    run("service", "on", "claude.ai", "auto", expect="error=list_limit", rc=1)
    if cfg.read_text() != RUNNING or state.read_text() != "":
        fail("a refused include left the router or the state changed")
    Path(str(cfg) + ".mode-limit").unlink()

    # The list the owner deleted in Keenetic: off just forgets it.
    run("service", "on", "claude.ai", "auto", expect="result=changed", rc=0)
    cfg.write_text(RUNNING)
    run("service", "off", "claude.ai", expect="result=changed", rc=0)

    # Daily catalog: a broken one is refused, a good one is kept and the lists follow it.
    run("service", "on", "claude.ai", "auto", expect="result=changed", rc=0)
    run("services-refresh", "run", expect="error=download_failed", rc=1)
    served.write_text("{not json")
    run("services-refresh", "run", expect="error=catalog_invalid", rc=1)
    quoted = json.loads(json.dumps(CATALOG)); quoted["services"][0]["title"] = 'Cla"ude'
    served.write_text(json.dumps(quoted))
    run("services-refresh", "run", expect="error=catalog_invalid", rc=1)
    badid = json.loads(json.dumps(CATALOG)); badid["services"][0]["id"] = "a b"
    served.write_text(json.dumps(badid))
    run("services-refresh", "run", expect="error=catalog_invalid", rc=1)
    newer = json.loads(json.dumps(CATALOG))
    newer["services"][0]["domains"] = ["anthropic.com", "claude.ai", "claudeusercontent.com"]
    served.write_text(json.dumps(newer))
    run("services-refresh", "run", expect="result=changed", rc=0)
    g = group("domain-list1")
    if g != ['    description "Claude"', "    include anthropic.com", "    include claude.ai", "    include claudeusercontent.com"]:
        fail(f"the list did not follow the catalog: {g}")
    run("services-refresh", "run", expect="result=unchanged", rc=0)
    run("service", "off", "claude.ai", expect="result=changed", rc=0)
    if cfg.read_text() != RUNNING:
        fail("off after refresh did not restore the router")

    # A category pinned to a tunnel: its services on «Автоматически» go there.
    cats = etc / "services/categories.tsv"
    run("service", "on", "claude.ai", "auto", expect="result=changed", rc=0)
    run("service-category", "a;b", "Wireguard0", expect="error=invalid_category", rc=64)
    run("service-category", "games", "Wireguard0", expect="error=invalid_category", rc=64)
    run("service-category", "ai", "Wireguard9", expect="error=unknown_tunnel", rc=64)
    run("service-category", "ai", "x;y", expect="error=invalid_value", rc=64)
    run("service-category", "ai", "auto", expect="result=unchanged", rc=0)
    run("service-category", "ai", "Wireguard0", expect="result=changed", rc=0)
    if cats.read_text() != "ai\tWireguard0\n" or "moved=1" not in (tmp / "audit.log").read_text():
        fail(f"category pin: {cats.read_text()!r}")
    run("service-category", "ai", "Wireguard0", expect="result=unchanged", rc=0)
    if cfg.read_text().count("route object-group domain-list1 Wireguard0") != 1:
        fail("the pinned category's service must stay routed once")
    run("service-category", "ai", "auto", expect="result=changed", rc=0)
    if cats.read_text() != "":
        fail(f"back to auto: {cats.read_text()!r}")
    run("service", "off", "claude.ai", expect="result=changed", rc=0)

print("CONSOLE_SERVICES=PASS")
