#!/usr/bin/env python3
"""«Мои домены» without a group (owner 12.11.2026: after the switch to a new tunnel there was
none, and «VPN» for claude.ai did nothing): adding a domain makes VWARD's own Keenetic list
«VWARD» routed through the default tunnel, writes it to device.conf and puts the domain there;
the second domain goes to the same list; a list «VWARD» the owner already has is taken as it is."""
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"

def fail(m):
    raise SystemExit(f"OWN_GROUP=FAIL: {m}")

RUNNING = """interface Wireguard0
!
object-group fqdn YouTube
    include youtube.com
!
dns-proxy
    route object-group YouTube Wireguard0 auto
!
"""
FAKE_NDMC = r'''#!/usr/bin/env python3
import sys
from pathlib import Path
cfg = Path("@CFG@")
cmd = sys.argv[2]
with open(str(cfg) + ".log", "a") as f: f.write(cmd + "\n")
if cmd == "show running-config":
    print(cfg.read_text(), end=""); sys.exit(0)
if cmd == "system configuration save":
    sys.exit(0)
lines = cfg.read_text().splitlines()
w = cmd.split()
def block(name):
    h = "object-group fqdn " + name
    if h not in lines:
        lines.extend([h, "!"])
    i = lines.index(h); j = lines.index("!", i); return i, j
if w[:2] == ["object-group", "fqdn"] and len(w) == 3:
    block(w[2])
elif w[:2] == ["object-group", "fqdn"] and len(w) == 5 and w[3] == "include":
    i, j = block(w[2])
    if "    include " + w[4] not in lines[i:j]: lines.insert(j, "    include " + w[4])
elif w[:3] == ["no", "object-group", "fqdn"] and len(w) == 6 and w[4] == "include":
    lines = [l for l in lines if not (l == "    include " + w[5])]
elif w[:2] == ["dns-proxy", "route"]:
    i = lines.index("dns-proxy"); j = lines.index("!", i); lines.insert(j, "    " + " ".join(w[1:]))
elif w[:3] == ["dns-proxy", "no", "route"]:
    lines = [l for l in lines if not l.strip().startswith(" ".join(w[2:]))]
else:
    print("Command::Base: no such command: " + cmd); sys.exit(0)
cfg.write_text("\n".join(lines) + "\n")
'''

def env_for(tmp: Path):
    cfg = tmp / "running.cfg"; cfg.write_text(RUNNING)
    ndmc = tmp / "ndmc"; ndmc.write_text(FAKE_NDMC.replace("@CFG@", str(cfg))); ndmc.chmod(0o755)
    devconf = tmp / "device.conf"
    devconf.write_text("VWARD_LAN_ADDRESS=10.77.0.1\nVWARD_LAN_SUBNET=10.77.0.0/24\nVWARD_LAN_DEVICE=br0\nVWARD_LAN_INTERFACE=Bridge0\n"
                       "VWARD_WAN_DEVICE=eth3\nVWARD_WAN_INTERFACE=GigabitEthernet1\nVWARD_TUNNEL_INTERFACE=Wireguard0\nVWARD_TUNNEL_DEVICE=nwg0\n")
    devconf.chmod(0o600)
    (tmp / "root/tmp").mkdir(parents=True)
    env = os.environ | {
        "VWARD_NDMC": str(ndmc), "VWARD_DEVICE_CONFIG": str(devconf), "VWARD_DEVICE_CONFIG_OWNER_UID": str(os.getuid()),
        "VWARD_DEVICE_MAP_CACHE": str(tmp / "map.tsv"), "VWARD_SYSFS_NET": str(tmp / "sys"),
        "VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "change.lock"),
        "VWARD_ROUTE_STATE": str(tmp / "route"), "VWARD_CONSOLE_ETC": str(tmp / "etc"),
        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
        "VWARD_SNAPSHOT_DIR": str(tmp / "snaps"), "VWARD_CORE_BIN": str(tmp / "no-core"),
    }
    return env, cfg, devconf

def run(env, *a):
    r = subprocess.run(["sh", str(HELPER), *a], env=env, text=True, capture_output=True, timeout=60)
    return r.returncode, r.stdout.strip().splitlines()[-1:] , r

with tempfile.TemporaryDirectory() as t:
    tmp = Path(t); env, cfg, devconf = env_for(tmp)
    rc, out, r = run(env, "route-domain", "add", "claude.ai")
    text = cfg.read_text()
    if rc != 0 or out != ["result=changed"]:
        fail(f"no group: {rc} {out} {r.stderr[-400:]}\n{text}")
    if "object-group fqdn VWARD\n    include claude.ai\n!" not in text or "    route object-group VWARD Wireguard0 auto" not in text:
        fail("VWARD's own list through the default tunnel with the domain:\n" + text)
    if "VWARD_POLICY_GROUP=VWARD" not in devconf.read_text():
        fail("the list is written to device.conf")
    rc, out, r = run(env, "route-domain", "add", "anthropic.com")
    text = cfg.read_text()
    if rc != 0 or "    include anthropic.com" not in text or text.count("object-group fqdn VWARD") != 1 or text.count("route object-group VWARD") != 1:
        fail(f"the second domain goes to the same list: {out}\n{text}")
with tempfile.TemporaryDirectory() as t:
    tmp = Path(t); env, cfg, devconf = env_for(tmp)
    cfg.write_text(RUNNING.replace("!\ndns-proxy", "!\nobject-group fqdn VWARD\n    include mine.example\n!\ndns-proxy"))
    rc, out, r = run(env, "route-domain", "add", "claude.ai")
    text = cfg.read_text()
    if rc != 0 or "    include mine.example" not in text or "    include claude.ai" not in text or text.count("object-group fqdn VWARD") != 1:
        fail(f"an existing list «VWARD» is taken as it is: {out}\n{text}")
print("OWN_GROUP=PASS")
