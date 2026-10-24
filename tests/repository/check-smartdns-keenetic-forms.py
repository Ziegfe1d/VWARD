#!/usr/bin/env python3
"""Smart DNS in Keenetic (fix.33): a form Keenetic refuses is journaled with its whole answer,
the shorter forms are tried in turn; the slots used and where the form came from are written.
fix.33.1: a Keenetic without its DNS-over-HTTPS component («no such command: https») is told so
at once, in one try, not as «the router refused»; Smart DNS kept in AdGuard Home gets the server
chosen in the Panel, not «auto» (a fresh AdGuard Home has no Smart DNS rows to take one from)."""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"


def fail(message: str) -> None:
    raise SystemExit(f"SMARTDNS_KEENETIC_FORMS=FAIL: {message}")


RUNNING = """interface Wireguard0
!
dns-proxy
    route object-group Mine Wireguard0 auto
!
"""

FAKE_NDMC = r'''#!/usr/bin/env python3
import sys
from pathlib import Path
cfg = Path("@CFG@")
cmd = sys.argv[2]
if cmd == "show running-config":
    print(cfg.read_text(), end=""); sys.exit(0)
if cmd == "system configuration save":
    sys.exit(0)
if cfg.with_name("no-doh").exists() and cmd.startswith("dns-proxy https"):
    print("\x1b[KCommand::Base error[7405600]: no such command: https.\n\x1b[K"); sys.exit(0)
if " dnsm on " in cmd:
    print("Core::Configurator: error: synthetic refusal of the form\n["); sys.exit(0)
lines = cfg.read_text().splitlines()
ctx = cmd.startswith("dns-proxy ")
body = cmd[len("dns-proxy "):] if ctx else cmd
neg = body.startswith("no ")
if neg: body = body[3:]
out, inblock = [], False
for l in lines:
    if l == "dns-proxy": inblock = True
    elif l == "!": inblock = False
    if neg and ((ctx and inblock and l.strip().startswith(body)) or (not ctx and not l.startswith(" ") and l.startswith(body))):
        continue
    out.append(l)
if not neg:
    if ctx:
        i = out.index("dns-proxy"); j = out.index("!", i); out.insert(j, "    " + body)
    else:
        out.append(body)
cfg.write_text("\n".join(out) + "\n")
'''

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    cfg = tmp / "running.cfg"; cfg.write_text(RUNNING)
    ndmc = tmp / "ndmc"; ndmc.write_text(FAKE_NDMC.replace("@CFG@", str(cfg))); ndmc.chmod(0o755)
    devconf = tmp / "device.conf"
    devconf.write_text("VWARD_LAN_ADDRESS=10.77.0.1\nVWARD_LAN_SUBNET=10.77.0.0/24\nVWARD_LAN_DEVICE=br0\nVWARD_LAN_INTERFACE=Bridge0\n"
                       "VWARD_WAN_DEVICE=eth3\nVWARD_WAN_INTERFACE=GigabitEthernet1\nVWARD_TUNNEL_INTERFACE=Wireguard0\nVWARD_TUNNEL_DEVICE=nwg0\n"
                       "VWARD_POLICY_GROUP=Mine\n"); devconf.chmod(0o600)
    pol = tmp / "policy"; pol.mkdir()
    (tmp / "root/tmp").mkdir(parents=True)
    (tmp / "etc").mkdir()
    (tmp / "etc/smartdns.conf").write_text("SMARTDNS_URL=https://doh.example/dns-query/synthetic-token\n")
    env = os.environ | {
        "VWARD_NDMC": str(ndmc), "VWARD_DEVICE_CONFIG": str(devconf), "VWARD_DEVICE_CONFIG_OWNER_UID": str(os.getuid()),
        "VWARD_DEVICE_MAP_CACHE": str(tmp / "map.tsv"), "VWARD_SYSFS_NET": str(tmp / "sys"),
        "VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"),
        "VWARD_ROUTE_STATE": str(tmp / "route"), "VWARD_CONSOLE_ETC": str(tmp / "etc"), "VWARD_POLICY_STATE": str(pol),
        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
        "VWARD_SNAPSHOT_DIR": str(tmp / "snaps"), "VWARD_POLICY_SYNC_BIN": str(tmp / "no-sync"),
    }
    r = subprocess.run(["sh", str(HELPER), "smartdns-keenetic", "add", "chat.example"], env=env, text=True, capture_output=True, timeout=60)
    out = r.stdout.strip().splitlines()
    audit = (tmp / "audit.log").read_text()
    if not out or out[-1] != "result=changed":
        fail(f"the shorter form must be tried: {r.stdout} {r.stderr[-300:]}")
    if "    https upstream https://doh.example/dns-query/synthetic-token dnsm domain chat.example" not in cfg.read_text():
        fail("the form Keenetic takes is written:\n" + cfg.read_text())
    if "refused form=https upstream https://doh.example/… dnsm on GigabitEthernet1 domain chat.example used=0/8 source=default: Core::Configurator: error: synthetic refusal of the form" not in audit:
        fail("the refusal is journaled with the form, the slots, the source and Keenetic's whole answer:\n" + audit)
    if "accepted form=https upstream https://doh.example/… dnsm domain chat.example used=1/8" not in audit or "synthetic-token" in audit:
        fail("the accepted form is journaled, the server's token never:\n" + audit)
    # No DNS-over-HTTPS component: one try, the owner told what to install.
    (tmp / "no-doh").write_text("")
    (tmp / "audit.log").write_text("")
    r = subprocess.run(["sh", str(HELPER), "smartdns-keenetic", "add", "other.example"], env=env, text=True, capture_output=True, timeout=60)
    audit = (tmp / "audit.log").read_text()
    if "error=smartdns_doh_component" not in r.stdout:
        fail(f"no component: smartdns_doh_component, not router_rejected: {r.stdout}")
    if audit.count("refused form=") != 1 or "no such command: https." not in audit or "\x1b" in audit or "[K" in audit:
        fail("no component: one try, Keenetic's answer clean in the journal:\n" + audit)
    # AdGuard Home: what it is handed.
    ctl = tmp / "ads-control"
    ctl.write_text('#!/bin/sh\ncat "$3" > "' + str(tmp / "handed") + '"\necho CONTROL=PASS\n'); ctl.chmod(0o755)
    (tmp / "etc/smartdns.conf").write_text("SMARTDNS_URL=https://doh.example/dns-query/synthetic-token\nSMARTDNS_STORE=agh\n")
    r = subprocess.run(["sh", str(HELPER), "smartdns-domain", "add", "third.example"], env=env | {"VWARD_ADS_CONTROL_BIN": str(ctl)},
                       text=True, capture_output=True, timeout=60)
    handed = (tmp / "handed").read_text() if (tmp / "handed").exists() else ""
    if "result=changed" not in r.stdout or handed != "third.example\thttps://doh.example/dns-query/synthetic-token\n":
        fail(f"AdGuard Home gets the Panel's server: {r.stdout} {handed!r}")
print("SMARTDNS_KEENETIC_FORMS=PASS")
