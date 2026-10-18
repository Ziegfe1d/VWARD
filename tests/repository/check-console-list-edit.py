#!/usr/bin/env python3
"""Clearing and deleting a whole domain list (fix.30): a copy of the settings first; a delete
takes the list, its route and exclusions out of Keenetic; a refused step puts everything back;
AdaptiveAuto and catalog services' lists are refused, VWARD's own list is only cleared; the
API asks for a confirmation."""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"

RUNNING = "\n".join([
    "interface Wireguard0", "!",
    "dns-proxy",
    "    route object-group domain-list4 Wireguard0 auto",
    "    route object-group domain-list0 Wireguard0 auto",
    "!",
    "object-group fqdn domain-list4", "    description \"Video\"",
    "    include video.example", "    include cdn.example", "    exclude music.video.example", "!",
    "object-group fqdn domain-list0", "    include my.example", "!",
    "object-group fqdn domain-list7", "    include svc.example", "!",
    "object-group fqdn AdaptiveAuto", "    include auto.example", "!",
]) + "\n"

# A Keenetic CLI over a text file: object groups and dns-proxy routes; .fail holds a command
# prefix the router refuses.
FAKE_NDMC = r'''#!/usr/bin/env python3
import sys, re
from pathlib import Path
cfg = Path("@CFG@")
cmd = sys.argv[2]
if cmd == "show running-config":
    print(cfg.read_text(), end=""); sys.exit(0)
if cmd == "system configuration save":
    print("saved"); sys.exit(0)
fail = Path(str(cfg) + ".fail")
if fail.exists() and cmd.startswith(fail.read_text().strip()):
    print("Command::Base: error[7]: refused"); sys.exit(0)
blocks, cur = [], None
for l in cfg.read_text().splitlines():
    if l == "!":
        blocks.append(cur); cur = None
    elif not l.startswith(" "):
        cur = [l]
    else:
        cur.append(l.strip())
def write():
    cfg.write_text("".join(b[0] + "\n" + "".join("    " + x + "\n" for x in b[1:]) + "!\n" for b in blocks))
def grp(g):
    return next((b for b in blocks if b[0] == "object-group fqdn " + g), None)
m = re.match(r"^dns-proxy (no )?route object-group (\S+) (.+)$", cmd)
if m:
    dp = next(b for b in blocks if b[0] == "dns-proxy")
    line = "route object-group " + m.group(2) + " " + m.group(3)
    if m.group(1):
        dp[:] = [x for x in dp if not x.startswith("route object-group " + m.group(2) + " " + m.group(3).split()[0])]
    else:
        dp.append(line)
    write(); sys.exit(0)
m = re.match(r"^(no )?object-group fqdn (\S+)( (include|exclude|description) (.+))?$", cmd)
if not m:
    print("Command::Base: error[7]: syntax error"); sys.exit(0)
neg, g, rest = m.group(1), m.group(2), m.group(3)
b = grp(g)
if rest is None:
    if neg:
        if b: blocks.remove(b)
    elif not b:
        blocks.append(["object-group fqdn " + g])
    write(); sys.exit(0)
if not b:
    print("Command::Base: error[7]: not found"); sys.exit(0)
item = rest.strip()
if neg:
    b[:] = [x for x in b if x != item]
elif item not in b:
    b.append(item)
write()
'''

DEVICE_CONF = """VWARD_LAN_ADDRESS=10.77.0.1
VWARD_LAN_SUBNET=10.77.0.0/24
VWARD_LAN_DEVICE=br0
VWARD_LAN_INTERFACE=Bridge0
VWARD_WAN_DEVICE=eth3
VWARD_WAN_INTERFACE=GigabitEthernet1
VWARD_TUNNEL_INTERFACE=Wireguard0
VWARD_TUNNEL_DEVICE=nwg0
VWARD_POLICY_GROUP=domain-list0
"""


def fail(message: str) -> None:
    raise SystemExit(f"CONSOLE_LIST_EDIT=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    tools = tmp / "tools"; tools.mkdir()
    cfg = tmp / "running.cfg"; cfg.write_text(RUNNING)
    ndmc = tools / "ndmc"; ndmc.write_text(FAKE_NDMC.replace("@CFG@", str(cfg))); ndmc.chmod(0o755)
    devconf = tmp / "device.conf"; devconf.write_text(DEVICE_CONF); devconf.chmod(0o600)
    etc = tmp / "etc"; (etc / "route-engine/domain-lists").mkdir(parents=True); (etc / "services").mkdir()
    (etc / "services/enabled.tsv").write_text("svc\tdomain-list7\tvpn\n")
    (etc / "route-engine/domain-lists.conf").write_text("watch.domain-list4=1\nwatch.domain-list0=1\n")
    (etc / "route-engine/domain-lists/domain-list4").write_text("saved\n")
    (tmp / "root/tmp").mkdir(parents=True)
    env = os.environ | {
        "VWARD_NDMC": str(ndmc), "VWARD_DEVICE_CONFIG": str(devconf), "VWARD_DEVICE_CONFIG_OWNER_UID": str(os.getuid()),
        "VWARD_DEVICE_MAP_CACHE": str(tmp / "map.tsv"), "VWARD_SYSFS_NET": str(tmp / "sys"),
        "VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"),
        "VWARD_ROUTE_STATE": str(tmp / "route"), "VWARD_CONSOLE_ETC": str(etc), "VWARD_SERVICES_ETC": str(etc / "services"),
        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
        "VWARD_SNAPSHOT_DIR": str(tmp / "snaps"),
    }

    def run(*args):
        r = subprocess.run(["sh", str(HELPER), "list", *args], env=env, text=True, capture_output=True)
        out = r.stdout.strip().splitlines()
        return out[-1] if out else r.stderr.strip()[-300:]

    for args, want in ((("delete", "AdaptiveAuto"), "error=invalid_group"), (("clear", "AdaptiveAuto"), "error=invalid_group"),
                       (("delete", "domain-list0"), "error=invalid_group"), (("delete", "domain-list7"), "error=service_list"),
                       (("delete", "domain-list9"), "error=list_not_found"), (("drop", "domain-list4"), "error=invalid_operation"),
                       (("delete", "../x"), "error=invalid_group")):
        if run(*args) != want:
            fail(f"{args}: {run(*args)} != {want}")
    same = lambda: sorted(cfg.read_text().splitlines()) == sorted(RUNNING.splitlines())

    # A refused step: everything back as it was.
    Path(str(cfg) + ".fail").write_text("no object-group fqdn domain-list4\n")
    if run("delete", "domain-list4") != "error=router_rejected" or not same():
        fail("a refused delete must put the route back:\n" + cfg.read_text())
    Path(str(cfg) + ".fail").write_text("no object-group fqdn domain-list4 include cdn.example\n")
    if run("clear", "domain-list4") != "error=router_rejected" or not same():
        fail("a refused clear must put the domains back:\n" + cfg.read_text())
    Path(str(cfg) + ".fail").unlink()

    if run("clear", "domain-list0") != "result=changed" or "include my.example" in cfg.read_text() or "object-group fqdn domain-list0" not in cfg.read_text():
        fail("VWARD's own list is cleared and stays")
    if run("clear", "domain-list0") != "result=unchanged":
        fail("an empty list has nothing to clear")
    if run("delete", "domain-list4") != "result=changed":
        fail("delete")
    text = cfg.read_text()
    if "domain-list4" in text or "route object-group domain-list0" not in text:
        fail("the list and only its route go:\n" + text)
    if (etc / "route-engine/domain-lists/domain-list4").exists() or "domain-list4" in (etc / "route-engine/domain-lists.conf").read_text():
        fail("VWARD's notes about a deleted list go with it")
    if len([p for p in (tmp / "snaps").iterdir() if p.name.endswith("-prelist.tar.gz")]) < 2:
        fail("a copy of the settings before every change")
    API = (ROOT / "web/cgi-bin/api.cgi").read_text()
    if 'list) set -- "$OP" "$ACT" "$TARGET"; case "$ACT" in clear) REQUIRED=LIST_CLEAR ;; *) REQUIRED=LIST_DELETE ;; esac ;;' not in API:
        fail("the API asks for a confirmation")

print("CONSOLE_LIST_EDIT=PASS")
