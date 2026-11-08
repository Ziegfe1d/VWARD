#!/usr/bin/env python3
"""The owner's switch «Smart DNS» (owner 08.11, off by default). Off: no Smart DNS row is written
(«smartdns_off»), the DoH client is not kept running, the server is not asked. On: only with a server
set that answers. Going off: VWARD's own rows of its server go (by its address), other servers' rows
stay, the address stays for a later «on»."""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"
LIB = ROOT / "components/runtime/lib/vward-device-profile.sh"
ADM = ROOT / "components/runtime/lib/vward-runtime-admission.sh"
URL = "https://doh.example/dns-query/synthetic-token"
OTHER = "https://other.example/dns-query"


def fail(message: str) -> None:
    raise SystemExit(f"SMARTDNS_FEATURE=FAIL: {message}")


RUNNING = f"""interface Wireguard0
!
dns-proxy
    route object-group Mine Wireguard0 auto
    https upstream {URL} dnsm domain mine.example
    https upstream {OTHER} dnsm domain theirs.example
!
"""
GOOD = "0000818000010001" + "00000000" + "076578616d706c6503636f6d0000010001" + "c00c000100010000012c00045db8d822"

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
if " dnsm on " in cmd and False:
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
    curl = tmp / "curl"
    curl.write_text("#!/bin/sh\nout=\nwhile [ $# -gt 0 ]; do [ \"$1\" != -o ] || out=$2; shift; done\ncat >/dev/null\n"
                    "python3 -c 'import sys; sys.stdout.buffer.write(bytes.fromhex(open(sys.argv[1]).read().strip()))' " + str(tmp / "body.hex") + " > \"$out\"\nprintf '%s' \"$(cat " + str(tmp / "code") + ")\"\n")
    curl.chmod(0o755)
    (tmp / "body.hex").write_text(GOOD); (tmp / "code").write_text("200")
    devconf = tmp / "device.conf"
    devconf.write_text("VWARD_LAN_ADDRESS=10.77.0.1\nVWARD_LAN_SUBNET=10.77.0.0/24\nVWARD_LAN_DEVICE=br0\nVWARD_LAN_INTERFACE=Bridge0\n"
                       "VWARD_WAN_DEVICE=eth3\nVWARD_WAN_INTERFACE=GigabitEthernet1\nVWARD_TUNNEL_INTERFACE=Wireguard0\nVWARD_TUNNEL_DEVICE=nwg0\n"
                       "VWARD_POLICY_GROUP=Mine\n"); devconf.chmod(0o600)
    pol = tmp / "policy"; pol.mkdir(); (tmp / "root/tmp").mkdir(parents=True); (tmp / "etc").mkdir()
    switch = tmp / "etc/smartdns.switch"
    env = os.environ | {
        "VWARD_NDMC": str(ndmc), "VWARD_DEVICE_CONFIG": str(devconf), "VWARD_DEVICE_CONFIG_OWNER_UID": str(os.getuid()),
        "VWARD_DEVICE_MAP_CACHE": str(tmp / "map.tsv"), "VWARD_SYSFS_NET": str(tmp / "sys"),
        "VWARD_PROFILE_LIB": str(LIB), "VWARD_ADMISSION_LIB": str(ADM),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"),
        "VWARD_ROUTE_STATE": str(tmp / "route"), "VWARD_CONSOLE_ETC": str(tmp / "etc"), "VWARD_POLICY_STATE": str(pol),
        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
        "VWARD_SNAPSHOT_DIR": str(tmp / "snaps"), "VWARD_POLICY_SYNC_BIN": str(tmp / "no-sync"),
        "VWARD_CURL_BIN": str(curl), "VWARD_DOH_ALIVE_DIR": str(tmp / "alive"), "VWARD_DOH_ALIVE_FRESH": "1",
        "VWARD_TLS_BROKEN_FLAG": str(tmp / "none"), "VWARD_SMARTDNS_SWITCH": str(switch),
    }

    def run(*args, stdin=None):
        r = subprocess.run(["sh", str(HELPER), *args], env=env, text=True, capture_output=True, timeout=120, input=stdin)
        return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()[-200:]

    rows = lambda: sorted(l.strip() for l in cfg.read_text().splitlines() if l.strip().startswith("https upstream"))
    before = rows()
    # Off by default: no row is written, the server is not asked, the DoH client is not kept.
    if run("smartdns-keenetic", "add", "new.example") != "error=smartdns_off" or rows() != before:
        fail("off: no Smart DNS row may be written")
    r = subprocess.run(["sh", "-c", '. "$1"; vward_doh_alive "$2"; echo "rc=$?"', "sh", str(LIB), URL], env=env, text=True, capture_output=True)
    if r.stdout.strip() != "rc=2":
        fail(f"off: the server is not asked: {r.stdout}")
    r = subprocess.run(["sh", "-c", '. "$1"; vward_doh_keep; echo "rc=$?"', "sh", str(ADM)], env=env | {"VWARD_ADGUARD_CONFIG": "/nonexistent-but-checked-after"}, text=True, capture_output=True)
    if r.stdout.strip() != "rc=0":
        fail(f"off: the DoH client is not kept: {r.stdout}")
    # On: a server set that answers; none set or silent: refused with the reason.
    if run("smartdns-feature", "1") != "error=smartdns_not_configured" or switch.exists():
        fail("on without a server: refused")
    (tmp / "etc/smartdns.conf").write_text("SMARTDNS_URL=" + URL + "\n")
    (tmp / "code").write_text("503")
    if run("smartdns-feature", "1") != "error=smartdns_dead" or switch.exists():
        fail("on with a silent server: refused")
    (tmp / "code").write_text("200")
    if run("smartdns-feature", "1") != "result=changed" or switch.read_text().strip() != "1":
        fail("on with a server that answers")
    if run("smartdns-keenetic", "add", "new.example") != "result=changed" or f"https upstream {URL} dnsm domain new.example" not in rows():
        fail(f"on: rows are written: {rows()}")
    # Off: VWARD's own rows of its server go; the other server's row, the address stay.
    r = run("smartdns-feature", "0")
    if r != "result=changed" or switch.read_text().strip() != "0":
        fail(f"off: {r}")
    if rows() != [f"https upstream {OTHER} dnsm domain theirs.example"]:
        fail(f"off: only VWARD's rows of its own server go: {rows()}")
    if "SMARTDNS_URL=" + URL not in (tmp / "etc/smartdns.conf").read_text():
        fail("off: the server address stays for a later on")
    if run("smartdns-feature", "0") != "result=unchanged":
        fail("off again: nothing to do")
print("SMARTDNS_FEATURE=PASS")
