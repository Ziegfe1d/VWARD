#!/usr/bin/env python3
"""fix.35.5: an AI service's move to Smart DNS is one move - checked before its first write, taken
back on any refusal; a domain on another server is not «unchanged»; a removed server leaves no row in
the lists' DNS proofs. Real helper over a stateful Keenetic transport (no AdGuard Home), no network.

A2: the second Smart DNS line refused -> before: the first stayed (router_rejected), now taken back.
A3: an unfinished service operation -> before: lines could be written first; now refused before any.
A8: no Smart DNS server at all -> refused before any write (AdGuard Home installed is not a server).
A4: the domain already on another server -> before: «unchanged» (a new own server promised a change).
Capacity: Keenetic's 8 lines counted for the whole service before the first one.
A5: «Убрать» of a server also takes its rows out of domain-lists.dns proofs (before: the list's next
move found its proof row gone and refused list_dns_reference_only).
"""
import ast
import os
import subprocess
import tempfile
from pathlib import Path
from doh_fixture import responder

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"
tree = ast.parse((Path(__file__).with_name("check-console-ai.py")).read_text())
C = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
     and n.targets[0].id in ("FAKE_NDMC", "CATALOG", "DEVICE_CONF", "TOKEN")}
TOKEN = C["TOKEN"]
OWN = f"https://dns.example.test/dns-query/{TOKEN}"
OLD = "https://old.example.test/dns-query"
# A refusal of one form on demand: the file «refuse» names a text the command must not contain.
FAKE = C["FAKE_NDMC"].replace('w = cmd.split()', 'w = cmd.split()\nrf = cfg.with_name("refuse")\n'
                                'if rf.exists() and rf.read_text().strip() in cmd:\n    print("Command::Base: error[7]: refused"); sys.exit(0)')


def fail(msg):
    raise SystemExit("AI_TRANSITIONS=FAIL: " + msg)


def setup(tmp, lines=(), own=True):
    tools = tmp / "tools"; tools.mkdir()
    cfg = tmp / "running.cfg"
    cfg.write_text("interface Wireguard0\n!\ndns-proxy\n" + "".join("    " + l + "\n" for l in lines) + "!\n")
    ndmc = tools / "ndmc"; ndmc.write_text(FAKE.replace("@CFG@", str(cfg))); ndmc.chmod(0o755)
    dev = tmp / "device.conf"; dev.write_text(C["DEVICE_CONF"]); dev.chmod(0o600)
    cat = tmp / "catalog.json"; cat.write_text(C["CATALOG"])
    etc = tmp / "etc"; etc.mkdir()
    (tmp / "root/tmp").mkdir(parents=True)
    if own:
        (etc / "smartdns.conf").write_text("SMARTDNS_URL=" + OWN + "\nSMARTDNS_STORE=keenetic\n"); (etc / "smartdns.conf").chmod(0o600)
    env = os.environ | {
        "VWARD_NDMC": str(ndmc), "VWARD_DEVICE_CONFIG": str(dev), "VWARD_DEVICE_CONFIG_OWNER_UID": str(os.getuid()),
        "VWARD_DEVICE_MAP_CACHE": str(tmp / "map.tsv"), "VWARD_SYSFS_NET": str(tmp / "sys"),
        "VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"),
        "VWARD_ROUTE_STATE": str(tmp / "route"), "VWARD_CONSOLE_ETC": str(etc),
        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
        "VWARD_ADS_CONTROL_BIN": str(tmp / "no-ads-control"), "VWARD_ADGUARD_CONFIG": str(tmp / "no-adguard.yaml"),
        "VWARD_SERVICES_FETCHED": str(cat), "VWARD_SERVICES_BUNDLED": str(cat), "VWARD_DOH_ALIVE": "0",
    }

    responder(tmp, env)
    def run(*args, stdin=""):
        r = subprocess.run(["sh", str(HELPER), *args], env=env, text=True, capture_output=True, input=stdin, timeout=120)
        if TOKEN in r.stdout or TOKEN in r.stderr:
            fail(f"{args}: the server's token was printed")
        out = r.stdout.strip().splitlines()
        return out[-1] if out else r.stderr.strip()[-300:]

    def doh():
        return sorted(l.strip() for l in cfg.read_text().splitlines() if l.strip().startswith("https upstream"))
    return run, doh, cfg, etc


with tempfile.TemporaryDirectory() as t:
    # A2: the second line refused - the first one goes again, the service stays as it was.
    run, doh, cfg, etc = setup(Path(t), [f"https upstream {OLD} dnsm on ISP domain old.example"])
    before = doh()
    cfg.with_name("refuse").write_text("domain cdn.chatstatic.example")
    r = run("ai", "chat.example", "dns")
    if r == "result=changed" or doh() != before:
        fail(f"RED A2: a refused second line must take the first back: {r} {doh()}")
    cfg.with_name("refuse").unlink()
    if run("ai", "chat.example", "dns") != "result=changed" or len(doh()) != len(before) + 2:
        fail("the same move goes through once Keenetic takes it: " + str(doh()))

with tempfile.TemporaryDirectory() as t:
    # A3: an unfinished service operation refuses the move before any line is written.
    run, doh, cfg, etc = setup(Path(t))
    txn = Path(t) / "backup/service-transactions/txn.Ab12Cd"; txn.mkdir(parents=True)
    (txn / "pending").write_text(""); (txn / "groups").write_text("")
    r = run("ai", "chat.example", "dns")
    if r != "error=service_recovery_required" or doh():
        fail(f"RED A3: a pending service operation must refuse before the first write: {r} {doh()}")

with tempfile.TemporaryDirectory() as t:
    # A8: no server anywhere - refused before any write.
    run, doh, cfg, etc = setup(Path(t), own=False)
    (etc / "smartdns.conf").write_text("SMARTDNS_STORE=keenetic\n")
    r = run("ai", "chat.example", "dns")
    if r != "error=smartdns_not_configured" or doh():
        fail(f"A8: no Smart DNS server: {r} {doh()}")

with tempfile.TemporaryDirectory() as t:
    # A4: the domain on the old server, a new own server chosen: not «unchanged», not rewritten.
    run, doh, cfg, etc = setup(Path(t), [f"https upstream {OLD} dnsm on ISP domain old.example"])
    before = doh()
    r = run("smartdns-domain", "add", "old.example")
    if r != "error=smartdns_domain_other_server" or doh() != before:
        fail(f"RED A4: a domain on another server must be said so: {r}")
    # The same server: unchanged.
    if run("smartdns-domain", "add", "new.example") != "result=changed" or run("smartdns-domain", "add", "new.example") != "result=unchanged":
        fail("the same server again is unchanged")

with tempfile.TemporaryDirectory() as t:
    # Capacity: 7 of 8 taken, the service needs 2 - refused before the first line.
    lines = [f"https upstream {OLD} dnsm on ISP domain f{i}.example" for i in range(7)]
    run, doh, cfg, etc = setup(Path(t), lines)
    calls = Path(t) / "calls"
    ndmc = Path(t) / "tools/ndmc"
    ndmc.write_text(ndmc.read_text().replace("cmd = sys.argv[2]", "cmd = sys.argv[2]\nopen(" + repr(str(calls)) + ", 'a').write(cmd + '\\n')"))
    r = run("ai", "chat.example", "dns")
    added = [c for c in calls.read_text().splitlines() if c.startswith("dns-proxy https upstream")]
    if r != "error=smartdns_keenetic_full" or added or len(doh()) != 7:
        fail(f"the 8 lines are counted for the whole service first: {r} added={added}")

with tempfile.TemporaryDirectory() as t:
    # A5: a server removed - its rows leave the lists' DNS proofs too, another server's stay.
    lines = [f"https upstream {OWN} dnsm on ISP domain chat.example", f"https upstream {OLD} dnsm on ISP domain old.example"]
    run, doh, cfg, etc = setup(Path(t), lines)
    proofs = etc / "route-engine/domain-lists.dns"; proofs.mkdir(parents=True)
    proof = proofs / "domain-list3"
    proof.write_text("G include chat.example\nG route=ISP\tauto\nD " + lines[0] + "\nD " + lines[1] + "\n"); proof.chmod(0o600)
    r = run("smartdns-server", "clear")
    p = proof.read_text()
    if r != "result=changed" or OWN in p or ("D " + lines[1]) not in p or not p.startswith("G include chat.example\n"):
        fail(f"RED A5: the removed server's proof rows must go, the rest stays: {r} {p!r}")
with tempfile.TemporaryDirectory() as t:
    # A9: the list already on the tunnel but a Smart DNS row of its domain still active (a move cut
    # short): «VPN» again takes the row out and keeps where the list came from (before: unchanged).
    line = f"https upstream {OWN} dnsm on ISP domain chat.example"
    run, doh, cfg, etc = setup(Path(t), [line, "route object-group domain-list5 Wireguard0 auto"])
    cfg.write_text(cfg.read_text() + "object-group fqdn domain-list5\n    include chat.example\n!\n")
    saved = etc / "route-engine/domain-lists/domain-list5"; saved.parent.mkdir(parents=True)
    saved.write_text("route=GigabitEthernet1\tauto\n"); saved.chmod(0o600)
    r = run("domain-list", "domain-list5", "vpn")
    sv = saved.read_text()
    if not r.startswith("result=changed") or line in doh() or not sv.startswith("route=GigabitEthernet1\tauto\n") or ("doh=" + line) not in sv:
        fail(f"RED A9: a row left active must go, the saved route stays: {r} {doh()} {sv!r}")
    if run("domain-list", "domain-list5", "vpn") != "result=unchanged":
        fail("then the same move is unchanged")
print("AI_TRANSITIONS=PASS")
