#!/usr/bin/env python3
"""Domain lists: move a list into the tunnel and back through the Console writer.

Moving a list into the tunnel also takes out the Smart DNS (DNS-over-HTTPS
upstream) lines of its domains and puts them back on return.  Keenetic's delete
syntax for such a line is not documented, so the fake router supports several
behaviours: the exact mirror form, only the short form, and an unsafe form that
drops every line of the same server.  The 8-line DoH limit is enforced.
"""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"

AET = "https://de.aeternia.space:8443/dns-query/abc"
UPSTREAMS = [f"https upstream {AET} dnsm on ISP domain {d}" for d in (
    "chatgpt.com", "openai.com", "copilot.com", "copilot.microsoft.com", "claude.ai", "anthropic.com")]

RUNNING = "\n".join([
    "interface Wireguard0", "!",
    "dns-proxy",
    "    route object-group domain-list4 ISP auto",
    "    route object-group domain-list3 ISP auto",
    "    route object-group domain-list0 Wireguard0 auto",
    *("    " + u for u in UPSTREAMS),
    "!",
    "object-group fqdn domain-list4", "    description \"Claude Anthropic (ISP)\"",
    "    include anthropic.com", "    include claude.ai", "    include claude.com", "!",
    "object-group fqdn domain-list3", "    include chatgpt.com", "    include openai.com", "!",
    "object-group fqdn domain-list0", "    include telegram.org", "!",
    "object-group fqdn AdaptiveAuto", "    include example.org", "!",
]) + "\n"

# Fake Keenetic CLI.  Mode files next to the config: .mode-short (only
# "no https upstream URL domain D" deletes), .mode-unsafe (the mirror form
# deletes every line of the server), .mode-reject-route (route commands fail).
FAKE_NDMC = r'''#!/usr/bin/env python3
import sys
from pathlib import Path
cfg = Path("@CFG@")
cmd = sys.argv[2]
with open(str(cfg) + ".log", "a") as log:
    log.write(cmd + "\n")
lines = cfg.read_text().splitlines()
if cmd == "show running-config":
    print(cfg.read_text(), end=""); sys.exit(0)
if cmd == "system configuration save":
    print("saved"); sys.exit(0)
words = cmd.split()
if words[:1] != ["dns-proxy"]:
    print("Command::Base: error[7]: syntax error"); sys.exit(0)
words = words[1:]
neg = words[:1] == ["no"]
if neg:
    words = words[1:]
start = lines.index("dns-proxy")
end = lines.index("!", start)
block = [l.strip() for l in lines[start + 1:end]]
def mode(name):
    return Path(str(cfg) + ".mode-" + name).exists()
if words[:2] == ["route", "object-group"]:
    if mode("reject-route"):
        print("Dns::Proxy: error[5]: rejected"); sys.exit(0)
    g, t = words[2], words[3]
    if neg:
        block = [l for l in block if l.split()[:4] != ["route", "object-group", g, t]]
    else:
        block.insert(0, " ".join(words))
elif words[:2] == ["https", "upstream"]:
    doh = [l for l in block if l.startswith("https upstream ")]
    if neg:
        line = " ".join(words)
        url, dom = words[2], words[-1]
        if mode("unsafe") and line in doh:
            block = [l for l in block if not (l.startswith("https upstream ") and l.split()[2] == url)]
        elif mode("short"):
            if words[3:] == ["domain", dom]:
                block = [l for l in block if not (l.startswith("https upstream " + url + " ") and l.split()[-1] == dom)]
        elif line in block:
            block.remove(line)
    else:
        if len(doh) >= 8:
            print("Dns::Secure::ManagerDoh error[22610020]: DNS-over-HTTPS server list limit exceeded, the maximum is 8 entries."); sys.exit(0)
        block.append(" ".join(words))
else:
    print("Command::Base: error[7]: syntax error"); sys.exit(0)
lines[start + 1:end] = ["    " + l for l in block]
cfg.write_text("\n".join(lines) + "\n")
print("ok")
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


# Stand-in for the Ads component's AdGuard Home Smart DNS operations: keeps the
# upstream rows in a JSON state and mirrors them into AdGuardHome.yaml.
FAKE_ADS = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path
st = Path("@ST@"); s = json.loads(st.read_text()); args = sys.argv[1:]
with open(str(st) + ".log", "a") as f: f.write(args[1] + "\n")
if s.get("fail"): print("CONTROL=FAIL"); print("ERROR=" + s["fail"]); sys.exit(1)
if args[1] == "smartdns-take":
    inc = [l.strip() for l in open(args[2]) if l.strip()]; took = []; new = []
    for u in s["up"]:
        if u.startswith("[/"):
            e = u.index("/]"); ds = u[2:e].split("/"); url = u[e + 2:]
            t = [d for d in ds if any(d == i or d.endswith("." + i) for i in inc)]
            took += [(d, url) for d in t]; rest = [d for d in ds if d not in t]
            if rest: new.append("[/%s/]%s" % ("/".join(rest), url))
        else: new.append(u)
    s["up"] = new; Path(args[3]).write_text("".join("%s\t%s\n" % p for p in took)); print("TAKEN=%d" % len(took))
elif args[1] == "smartdns-put":
    for l in open(args[2]):
        d, url = l.rstrip("\n").split("\t"); s["up"].append("[/%s/]%s" % (d, url))
st.write_text(json.dumps(s))
Path("@YAML@").write_text("dns:\n  upstream_dns:\n" + "".join("    - '%s'\n" % u for u in s["up"]))
print("CONTROL=PASS")
'''


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def dns_block(cfg: Path) -> list:
    lines = cfg.read_text().splitlines()
    start = lines.index("dns-proxy")
    return sorted(l.strip() for l in lines[start + 1:lines.index("!", start)])


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    tools = tmp / "tools"; tools.mkdir()
    cfg = tmp / "running.cfg"; cfg.write_text(RUNNING)
    ndmc = tools / "ndmc"; ndmc.write_text(FAKE_NDMC.replace("@CFG@", str(cfg))); ndmc.chmod(0o755)
    curl = tools / "curl"; curl.write_text("#!/bin/sh\nexit 22\n"); curl.chmod(0o755)
    devconf = tmp / "device.conf"; devconf.write_text(DEVICE_CONF); devconf.chmod(0o600)
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
    }
    state = etc / "route-engine/domain-lists/domain-list4"
    original = dns_block(cfg)

    def run(op, group, value, expect, rc=None):
        r = subprocess.run(["sh", str(HELPER), op, group, value], env=env, text=True, capture_output=True)
        out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        if out != expect:
            fail(f"{op} {group} {value}: {out!r} != {expect!r} (rc={r.returncode}) {r.stderr.strip()[-300:]}")
        if rc is not None and r.returncode != rc:
            fail(f"{op} {group} {value}: rc {r.returncode} != {rc}")
        if (tmp / "change.lock").exists():
            fail(f"{op} {group} {value}: change lock left behind")

    def claude_in_tunnel():
        block = dns_block(cfg)
        want = "route object-group domain-list4 Wireguard0 auto"
        if want not in block or "route object-group domain-list4 ISP auto" in block:
            fail(f"domain-list4 is not in the tunnel: {block}")
        if any(l.endswith("domain claude.ai") or l.endswith("domain anthropic.com") for l in block):
            fail(f"Smart DNS lines of the list stayed: {block}")
        others = [u for u in UPSTREAMS if "claude.ai" not in u and "anthropic.com" not in u]
        if not all(u in block for u in others):
            fail(f"Smart DNS lines of other lists were touched: {block}")

    # Input and preconditions never touch the router.
    run("domain-list", "a;reboot", "vpn", "error=invalid_group", 64)
    run("domain-list", "AdaptiveAuto", "vpn", "error=invalid_group", 64)
    run("domain-list", "domain-list4", "tunnel", "error=unknown_tunnel", 64)
    run("domain-list", "domain-list4", "a;b", "error=invalid_value", 64)
    run("domain-list", "domain-list9", "vpn", "error=unknown_group", 64)
    run("domain-list", "domain-list0", "vpn", "result=unchanged", 0)
    run("domain-list", "domain-list4", "bypass", "result=unchanged", 0)
    if dns_block(cfg) != original:
        fail("a refused request changed the router")

    # 1. Mirror form: into the tunnel and back restores the router exactly.
    run("domain-list", "domain-list4", "vpn", "result=changed", 0)
    claude_in_tunnel()
    saved = state.read_text().splitlines()
    if saved[0] != "route=ISP\tauto" or sorted(saved[1:]) != sorted("doh=" + u for u in UPSTREAMS if "claude.ai" in u or "anthropic.com" in u):
        fail(f"return state is wrong: {saved}")
    if oct(state.stat().st_mode & 0o777) != "0o600":
        fail("return state holds Smart DNS URLs and must be 0600")
    run("domain-list", "domain-list4", "vpn", "result=unchanged", 0)
    run("domain-list", "domain-list4", "bypass", "result=changed", 0)
    if dns_block(cfg) != original:
        fail(f"bypass did not restore the router: {dns_block(cfg)}")
    if state.exists():
        fail("return state left after bypass")
    if "system configuration save" not in (tmp / "running.cfg.log").read_text():
        fail("the router configuration was not saved")

    # 2. Only the short delete form works: the next form is tried and verified.
    Path(str(cfg) + ".mode-short").touch()
    run("domain-list", "domain-list4", "vpn", "result=changed", 0)
    claude_in_tunnel()
    run("domain-list", "domain-list4", "bypass", "result=changed", 0)
    if dns_block(cfg) != original:
        fail(f"short form: bypass did not restore the router: {dns_block(cfg)}")
    Path(str(cfg) + ".mode-short").unlink()

    # 3. A delete form that drops every line of the server: all put back, aborted.
    Path(str(cfg) + ".mode-unsafe").touch()
    run("domain-list", "domain-list4", "vpn", "error=doh_remove_unsafe")
    if dns_block(cfg) != original:
        fail(f"unsafe form: the router was not restored: {dns_block(cfg)}")
    if state.exists():
        fail("unsafe form: return state written")
    Path(str(cfg) + ".mode-unsafe").unlink()

    # 4. The DoH limit is full on return: refused and nothing half-applied.
    run("domain-list", "domain-list4", "vpn", "result=changed", 0)
    for extra in ("gemini.google.com", "googleapis.com", "x.example", "y.example"):
        subprocess.run([str(ndmc), "-c", f"dns-proxy https upstream {AET} dnsm on ISP domain {extra}"], check=True, capture_output=True)
    before = dns_block(cfg)
    run("domain-list", "domain-list4", "bypass", "error=doh_limit")
    if dns_block(cfg) != before:
        fail(f"limit: bypass left a half-applied router: {dns_block(cfg)}")
    if not state.exists():
        fail("limit: the return state was lost")

    # 5. The router rejects route changes: untouched.
    cfg.write_text(RUNNING); state.unlink()
    Path(str(cfg) + ".mode-reject-route").touch()
    run("domain-list", "domain-list4", "vpn", "error=router_rejected")
    if dns_block(cfg) != original:
        fail("rejected route: router changed")
    Path(str(cfg) + ".mode-reject-route").unlink()

    # 7. Smart DNS kept only in AdGuard Home: its rows of the list go out and come back.
    cfg.write_text("\n".join(l for l in RUNNING.splitlines() if "https upstream" not in l) + "\n")
    if state.exists(): state.unlink()
    agh_state = tmp / "agh.json"; yaml = tmp / "AdGuardHome.yaml"
    UP = [f"[/anthropic.com/chatgpt.com/]{AET}", f"[/claude.ai/]{AET}", "https://dns.nextdns.io/abc"]
    agh_state.write_text(__import__("json").dumps({"up": UP}))
    yaml.write_text("dns:\n  upstream_dns:\n" + "".join(f"    - '{u}'\n" for u in UP))
    ads = tmp / "ads-control"; ads.write_text(FAKE_ADS.replace("@ST@", str(agh_state)).replace("@YAML@", str(yaml))); ads.chmod(0o755)
    env |= {"VWARD_ADGUARD_CONFIG": str(yaml), "VWARD_ADS_CONTROL_BIN": str(ads)}
    agh = lambda: __import__("json").loads(agh_state.read_text())["up"]
    keenetic_before = dns_block(cfg)

    run("domain-list", "domain-list4", "vpn", "result=changed", 0)
    if agh() != [f"[/chatgpt.com/]{AET}", "https://dns.nextdns.io/abc"]:
        fail(f"AdGuard Home rows of the list stayed or others went: {agh()}")
    saved = state.read_text().splitlines()
    if sorted(saved[1:]) != sorted([f"agh=anthropic.com\t{AET}", f"agh=claude.ai\t{AET}"]):
        fail(f"AdGuard Home pairs not remembered: {saved}")
    run("domain-list", "domain-list4", "bypass", "result=changed", 0)
    if sorted(agh()) != sorted([f"[/chatgpt.com/]{AET}", "https://dns.nextdns.io/abc", f"[/anthropic.com/]{AET}", f"[/claude.ai/]{AET}"]):
        fail(f"AdGuard Home rows not back: {agh()}")
    if dns_block(cfg) != keenetic_before or state.exists():
        fail("bypass after AdGuard Home did not restore the router")

    # A list without Smart DNS domains does not touch AdGuard Home.
    calls = (tmp / "agh.json.log").read_text()
    run("domain-list", "domain-list0", "bypass", "result=changed", 0)
    run("domain-list", "domain-list0", "vpn", "result=changed", 0)
    if (tmp / "agh.json.log").read_text() != calls:
        fail("a list without Smart DNS domains asked AdGuard Home")

    # AdGuard Home refuses (no login): the list stays where it was.
    st = __import__("json").loads(agh_state.read_text()); st["fail"] = "adguard_auth_required"; agh_state.write_text(__import__("json").dumps(st))
    before = dns_block(cfg)
    run("domain-list", "domain-list4", "vpn", "error=adguard_auth_required")
    if dns_block(cfg) != before or state.exists():
        fail(f"AdGuard Home refusal left the router changed: {dns_block(cfg)}")
    cfg.write_text(RUNNING)

    # 6. Watch switch.
    run("domain-list-watch", "domain-list4", "1", "result=changed", 0)
    run("domain-list-watch", "domain-list4", "1", "result=unchanged", 0)
    if "watch.domain-list4=1" not in (etc / "route-engine/domain-lists.conf").read_text().splitlines():
        fail("watch flag not written")
    run("domain-list-watch", "domain-list4", "2", "error=invalid_value", 64)
    run("domain-list-watch", "AdaptiveAuto", "1", "error=invalid_group", 64)

print("CONSOLE_DOMAIN_LISTS=PASS")
