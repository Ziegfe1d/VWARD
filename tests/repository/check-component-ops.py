#!/usr/bin/env python3
"""«Компоненты» (fix.32): AdGuard Home switched off, on, set up from scratch and removed from the
Panel with everything that depends on it - Keenetic's DNS lines (the DNS guard), Smart DNS domains
moved to Keenetic and back, the components agent told to leave it stopped; one operation at a time
with its mark on the flash; a failed step undone; the owner's password only through a file."""

import json
import os
import socket
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"


def fail(message: str) -> None:
    raise SystemExit(f"COMPONENT_OPS=FAIL: {message}")


RUNNING = """interface Wireguard0
!
dns-proxy
    route object-group domain-list0 Wireguard0 auto
    route object-group Other ISP auto
!
ip name-server 10.77.0.1:65053
"""

# A Keenetic CLI over a text file: «dns-proxy X» lines live in the dns-proxy block, the rest at
# the top; «no X» takes out the lines that start with X.
FAKE_NDMC = r'''#!/usr/bin/env python3
import sys
from pathlib import Path
cfg = Path("@CFG@")
cmd = sys.argv[2]
with open("@CFG@.log", "a") as f: f.write(cmd + "\n")
if cmd == "show running-config":
    print(cfg.read_text(), end=""); sys.exit(0)
if cmd == "system configuration save":
    sys.exit(0)
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

# AdGuard Home's first run: its setup API on the -p port; configure writes the settings.
FAKE_AGH = r'''#!/usr/bin/env python3
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
a = sys.argv
if "--version" in a: print("AdGuard Home, version v0.107.73"); sys.exit(0)
port = int(a[a.index("-p") + 1]); yaml = a[a.index("-c") + 1]
class H(BaseHTTPRequestHandler):
    def log_message(self, *x): pass
    def do_GET(self):
        self.send_response(200 if self.path == "/control/install/get_addresses" else 404); self.end_headers(); self.wfile.write(b"{}")
    def do_POST(self):
        d = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        open(yaml, "w").write("http:\n  address: 0.0.0.0:%d\nusers:\n  - name: %s\ndns:\n  port: %d\nschema_version: 29\n" % (d["web"]["port"], d["username"], d["dns"]["port"]))
        open(yaml + ".pw", "w").write(d["password"])
        self.send_response(200); self.end_headers()
HTTPServer(("127.0.0.1", port), H).serve_forever()
'''

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    tools = tmp / "tools"; tools.mkdir()
    sbin = tmp / "sbin"; sbin.mkdir()
    cfg = tmp / "running.cfg"; cfg.write_text(RUNNING)
    (tools / "ndmc").write_text(FAKE_NDMC.replace("@CFG@", str(cfg)))
    running = tmp / "agh.running"
    (tools / "pidof").write_text(f'#!/bin/sh\n[ -e "{running}" ]\n')
    (tools / "killall").write_text(f'#!/bin/sh\nrm -f "{running}"\n')
    (tools / "guard").write_text(f'#!/bin/sh\necho "$*" >> "{tmp}/guard.log"\n')
    init = tmp / "init.d/S99adguardhome"; init.parent.mkdir()
    init.write_text(f'#!/bin/sh\ncase "$1" in start) touch "{running}" ;; stop) rm -f "{running}" ;; esac\n')
    (sbin / "AdGuardHome").write_text(FAKE_AGH)
    for f in list(tools.iterdir()) + [init, sbin / "AdGuardHome"]:
        f.chmod(0o755)
    devconf = tmp / "device.conf"
    devconf.write_text("VWARD_LAN_ADDRESS=10.77.0.1\nVWARD_LAN_SUBNET=10.77.0.0/24\nVWARD_LAN_DEVICE=br0\nVWARD_LAN_INTERFACE=Bridge0\n"
                       "VWARD_WAN_DEVICE=eth3\nVWARD_WAN_INTERFACE=GigabitEthernet1\nVWARD_TUNNEL_INTERFACE=Wireguard0\nVWARD_TUNNEL_DEVICE=nwg0\n"
                       "VWARD_POLICY_GROUP=domain-list0\n"); devconf.chmod(0o600)
    etc = tmp / "etc"; (etc / "components").mkdir(parents=True)
    (etc / "smartdns.conf").write_text("SMARTDNS_URL=https://doh.example/dns-query\n")
    agh = tmp / "AdGuardHome"; agh.mkdir()
    yaml = agh / "AdGuardHome.yaml"
    YAML = "http:\n  address: 0.0.0.0:3000\ndns:\n  port: 65053\n  upstream_dns:\n    - '[/chat.example/]https://doh.example/dns-query'\n    - 10.77.0.1\n"
    yaml.write_text(YAML)
    auth = tmp / "agh-api.auth"
    netd = tmp / "net"; netd.mkdir()
    for n in ("tcp", "tcp6", "udp", "udp6"):
        (netd / n).write_text("  sl  local_address rem_address   st\n")
    # Something already listens on 3000: the web interface takes the next port.
    (netd / "tcp").write_text("  sl  local_address rem_address   st\n   0: 00000000:0BB8 00000000:0000 0A\n")
    (tmp / "root/tmp").mkdir(parents=True)
    env = os.environ | {
        "VWARD_NDMC": str(tools / "ndmc"), "VWARD_DEVICE_CONFIG": str(devconf), "VWARD_DEVICE_CONFIG_OWNER_UID": str(os.getuid()),
        "VWARD_DEVICE_MAP_CACHE": str(tmp / "map.tsv"), "VWARD_SYSFS_NET": str(tmp / "sys"),
        "VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"),
        "VWARD_ROUTE_STATE": str(tmp / "route"), "VWARD_CONSOLE_ETC": str(etc), "VWARD_COMPONENT_STATE": str(etc / "components"),
        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
        "VWARD_SNAPSHOT_DIR": str(tmp / "snaps"), "VWARD_CONSOLE_NOTES": str(tmp / "notes"),
        "VWARD_ADS_DNS_GUARD_BIN": str(tools / "guard"), "VWARD_PIDOF_BIN": str(tools / "pidof"), "VWARD_KILLALL_BIN": str(tools / "killall"),
        "VWARD_AGH_INIT": str(init), "VWARD_AGH_DIR": str(agh), "VWARD_ADGUARD_CONFIG": str(yaml), "VWARD_AGH_BIN_DIRS": str(sbin),
        "VWARD_ADS_AGH_AUTH_FILE": str(auth), "VWARD_AGH_BACKUPS": str(tmp / "agh-backups"), "VWARD_PROC_NET": str(netd),
        "VWARD_COMPONENT_OP_LOCK": str(tmp / "comp.lock"), "VWARD_AGH_ARCH": "mipsle_softfloat", "VWARD_AGH_START_WAIT": "10",
        "VWARD_EXT_UPDATE_STATE": str(tmp / "ext"), "VWARD_COMPONENT_REGISTRY": str(ROOT / "config/components/component-registry.json"),
    }

    def run(*args, extra=None):
        r = subprocess.run(["sh", str(HELPER), *args], env=env | (extra or {}), text=True, capture_output=True, timeout=120)
        out = r.stdout.strip().splitlines()
        return out[-1] if out else r.stderr.strip()[-300:]

    pending = etc / "component-ops/pending"
    running.touch()
    # Off: DNS lines released first, the program stopped and not started at boot, Smart DNS to Keenetic.
    if run("agh-component", "disable") != "result=changed":
        fail("disable: " + run("agh-component", "disable"))
    if "release" not in (tmp / "guard.log").read_text() or running.exists() or os.access(init, os.X_OK):
        fail("off: DNS released, program stopped, start script not executable")
    if not (etc / "components/adguardhome.disabled").exists() or pending.exists():
        fail("off: the flag for the components agent, no mark left")
    if "https upstream https://doh.example/dns-query dnsm on" not in cfg.read_text() or "domain chat.example" not in cfg.read_text():
        fail("off: Smart DNS domains go to Keenetic:\n" + cfg.read_text())
    # On: everything back.
    if run("agh-component", "enable") != "result=changed" or not running.exists() or not os.access(init, os.X_OK):
        fail("enable: " + run("agh-component", "enable"))
    if "chat.example" in cfg.read_text() or (etc / "components/adguardhome.disabled").exists():
        fail("on: Keenetic's Smart DNS lines go back to AdGuard Home:\n" + cfg.read_text())
    # One operation at a time.
    (tmp / "comp.lock").mkdir(); (tmp / "comp.lock/pid").write_text(str(os.getpid()))
    if run("agh-component", "disable") != "error=component_busy":
        fail("a second operation must wait for the first")
    import shutil; shutil.rmtree(tmp / "comp.lock")
    # Reset without a login: refused before anything changes.
    if run("agh-component", "reset", "backup") != "error=agh_credentials_required" or yaml.read_text() != YAML:
        fail("a new setup needs the owner's login, nothing touched before")
    # Reset with the owner's login from the Panel (a file, never argv): copy, setup, login kept.
    cred = tmp / "vward-agh-cred.test"; cred.write_text("owner:synthetic-pass-123\n"); cred.chmod(0o600)
    out = subprocess.run(["sh", str(HELPER), "agh-component", "reset", "backup"], env=env | {"VWARD_AGH_CRED_FILE": str(cred)}, text=True, capture_output=True, timeout=120)
    if out.stdout.strip().splitlines()[-1:] != ["result=changed"]:
        fail("reset: " + out.stdout + out.stderr[-400:])
    y = yaml.read_text()
    if "0.0.0.0:3001" not in y or "port: 65053" not in y or "name: owner" not in y or Path(str(yaml) + ".pw").read_text() != "synthetic-pass-123":
        fail("the setup takes the next free web port, DNS 65053 and the owner's login:\n" + y)
    if auth.read_text() != "owner:synthetic-pass-123\n" or oct(auth.stat().st_mode & 0o777) != "0o600":
        fail("the login is kept for VWARD, root-only")
    if "synthetic-pass-123" in (tmp / "audit.log").read_text() or "synthetic-pass-123" in out.stdout + out.stderr:
        fail("the password never reaches a journal or the output")
    if not list((tmp / "agh-backups").glob("*/AdGuardHome.yaml")) or not running.exists():
        fail("a copy of the old settings, the program running")
    # A failed setup is undone: the old settings back, no mark left.
    yaml.write_text(YAML); running.touch()
    (sbin / "AdGuardHome").write_text("#!/bin/sh\nexit 0\n")
    if run("agh-component", "reset", "nobackup") != "error=agh_start_failed" or yaml.read_text() != YAML or pending.exists():
        fail("a failed reset puts the settings back: " + run("agh-component", "reset", "nobackup"))
    (sbin / "AdGuardHome").write_text(FAKE_AGH)
    # Remove: DNS out, program, start script and settings gone, ad blocking off with a note.
    running.touch()
    if run("agh-component", "remove", "backup") != "result=changed":
        fail("remove: " + run("agh-component", "remove", "backup"))
    if (sbin / "AdGuardHome").exists() or init.exists() or agh.exists():
        fail("remove: the program, its start script and settings go")
    if "(with adguardhome)" not in (etc / "components/ads-privacy-guard.disabled").read_text():
        fail("remove: ad blocking goes off with it, marked so it comes back with the program")
    if "AdGuard Home удалён" not in (tmp / "notes/notes.tsv").read_text():
        fail("remove: the owner is told")
    # A mark left by a power cut: the components agent does the same operation again.
    pending.parent.mkdir(exist_ok=True); pending.write_text("op=agh-remove\nat=1\n")
    rec = run("component-recover", "now")
    if rec not in ("error=agh_not_installed", "result=changed") or pending.exists():
        fail(f"recover: the operation is repeated and the mark goes: {rec} {pending.exists()}")

API = (ROOT / "web/cgi-bin/api.cgi").read_text()
JS = (ROOT / "web/assets/vward-console.js").read_text()
SUP = (ROOT / "components/runtime/scripts/vward-cron-supervisor.sh").read_text()
for need, where in (('ARGS="agh-component $CACT $CBK"', API), ('[ "$(form_value confirm)" = COMPONENT_OP ]', API),
                    ('run_detached "$CONTROL_RUN_DIR" control_busy ${VWARD_AGH_CRED_FILE:-}', API),
                    ("function compPanel(id)", JS), ("compPanel('agh')", JS), ("compPanel('awg')", JS), ("compPanel('vless')", JS),
                    ('[ ! -e "$AGH_OFF_FILE" ] || return 1', SUP), ('"$CONFIG_BIN" component-recover now', SUP)):
    if need not in where:
        fail(f"missing: {need}")
# A program that keeps dying: five starts an hour, then left stopped and the owner told once.
import re
fn = re.search(r"^restart_allowed\(\)\n\{\n.*?^\}\n", SUP, re.S | re.M).group(0)
with tempfile.TemporaryDirectory() as t:
    sh = (f'RESTART_DIR={t}/r; RESTART_MAX=5; log_event() {{ echo "$*" >> {t}/log; }}\n'
          f'vward_note() {{ echo "$1|$2" >> {t}/notes; }}\n' + fn +
          'n=0; for i in 1 2 3 4 5 6 7; do restart_allowed panel && n=$((n + 1)); done; echo $n')
    r = subprocess.run(["sh", "-c", sh], text=True, capture_output=True)
    if r.stdout.strip() != "5" or Path(t, "notes").read_text().count("Компонент panel остановлен") != 1 or "RESTART_LIMIT|panel" not in Path(t, "log").read_text():
        fail(f"restart limit: {r.stdout} {r.stderr}")
print("COMPONENT_OPS=PASS")
