#!/usr/bin/env python3
"""Moving the lists and subnets off a tunnel without settings (fix.33): a subnet Keenetic
refuses no longer undoes the whole move - the rest move, the refused ones are journaled with
Keenetic's whole answer; the IP categories' routes stay with policy-sync.

fix.33.1, both branches: Keenetic keeps one route per subnet, so the new route replaces the
old one and the old one's removal is refused - such a false refusal is not counted and not
told; a subnet that really stays on the old tunnel is told (its new route taken back). The
answer reaches the journal without terminal codes, also with Keenetic's own BusyBox tools."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"


def fail(message: str) -> None:
    raise SystemExit(f"TUNNEL_MOVE=FAIL: {message}")


RUNNING = """interface Wireguard0
!
interface OpkgTun2
!
dns-proxy
    route object-group Video OpkgTun2 auto
    route object-group Mine Wireguard0 auto
!
ip route 10.20.0.0 255.255.0.0 OpkgTun2 auto
ip route 10.30.0.0 255.255.0.0 OpkgTun2 auto
ip route 10.40.0.0 255.255.0.0 OpkgTun2 auto
ip route 10.50.0.0 255.255.0.0 OpkgTun2 auto
"""

# Keenetic over a text file. A refused command prints its reason on one line and a bare
# «[» on the last one, as the router did.
FAKE_NDMC = r'''#!/usr/bin/env python3
import sys
from pathlib import Path
cfg = Path("@CFG@")
cmd = sys.argv[2]
if cmd == "show running-config":
    print(cfg.read_text(), end=""); sys.exit(0)
if cmd == "system configuration save":
    sys.exit(0)
if cmd == "no ip route 10.30.0.0 255.255.0.0 OpkgTun2":
    print("Network::RoutingTable: error: synthetic refusal\n["); sys.exit(0)
# The false refusal: the new route replaced the old one, removing the old one is refused.
if cmd == "ip route 10.50.0.0 255.255.0.0 Wireguard0 auto":
    t = cfg.read_text().replace("ip route 10.50.0.0 255.255.0.0 OpkgTun2 auto\n", "")
    cfg.write_text(t + "ip route 10.50.0.0 255.255.0.0 Wireguard0 auto\n"); sys.exit(0)
if cmd == "no ip route 10.50.0.0 255.255.0.0 OpkgTun2":
    print("\x1b[KCommand::Base error[7405600]: no such route.\n\x1b[K"); sys.exit(0)
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

def run(tmp: Path, busybox: bool) -> None:
    cfg = tmp / "running.cfg"; cfg.write_text(RUNNING)
    ndmc = tmp / "ndmc"; ndmc.write_text(FAKE_NDMC.replace("@CFG@", str(cfg))); ndmc.chmod(0o755)
    devconf = tmp / "device.conf"
    devconf.write_text("VWARD_LAN_ADDRESS=10.77.0.1\nVWARD_LAN_SUBNET=10.77.0.0/24\nVWARD_LAN_DEVICE=br0\nVWARD_LAN_INTERFACE=Bridge0\n"
                       "VWARD_WAN_DEVICE=eth3\nVWARD_WAN_INTERFACE=GigabitEthernet1\nVWARD_TUNNEL_INTERFACE=Wireguard0\nVWARD_TUNNEL_DEVICE=nwg0\n"
                       "VWARD_POLICY_GROUP=Mine\n"); devconf.chmod(0o600)
    pol = tmp / "policy"; pol.mkdir()
    (pol / "owned.dynamic.routes").write_text("10.40.0.0/16\n")
    (tmp / "root/tmp").mkdir(parents=True)
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
    if busybox:
        # Keenetic's own userland: BusyBox tr, sed, awk, cut (its tr has no [:print:]).
        bb = tmp / "bb"; bb.mkdir()
        for tool in ("tr", "sed", "awk", "cut", "grep", "head", "tail", "sort", "mktemp", "cat", "rm", "mv"):
            (bb / tool).symlink_to(shutil.which("busybox"))
        env["PATH"] = f"{bb}:{env['PATH']}"
    r = subprocess.run((["busybox", "sh"] if busybox else ["sh"]) + [str(HELPER), "tunnel-delete", "OpkgTun2", "vpn", "move"], env=env, text=True, capture_output=True, timeout=60)
    out = r.stdout.strip().splitlines()
    text = cfg.read_text()
    audit = (tmp / "audit.log").read_text()
    if not out or out[-1] != "result=changed":
        fail(f"a refused subnet must not undo the move: {r.stdout} {r.stderr[-300:]}")
    if "route object-group Video Wireguard0 auto" not in text or "Video OpkgTun2" in text:
        fail("the list moves:\n" + text)
    if "ip route 10.20.0.0 255.255.0.0 Wireguard0 auto" not in text or "10.20.0.0 255.255.0.0 OpkgTun2" in text:
        fail("the accepted subnet moves:\n" + text)
    if "ip route 10.30.0.0 255.255.0.0 OpkgTun2 auto" not in text or "10.30.0.0 255.255.0.0 Wireguard0" in text:
        fail("a subnet that really stays on the old tunnel stays, its copy on the default tunnel taken back:\n" + text)
    if "ip route 10.50.0.0 255.255.0.0 Wireguard0 auto" not in text or "10.50.0.0 255.255.0.0 OpkgTun2" in text:
        fail("a route Keenetic replaced itself is on the default tunnel:\n" + text)
    if "ip route 10.40.0.0 255.255.0.0 OpkgTun2 auto" not in text:
        fail("an IP category's route is left to policy-sync:\n" + text)
    if "info.moved=lists:1,subnets:2,failed:1,ip_categories:1" not in r.stdout:
        fail(f"the result counts: {r.stdout}")
    if "tunnel-move OpkgTun2 subnet 10.30.0.0 255.255.0.0 refused: Network::RoutingTable: error: synthetic refusal" not in audit:
        fail("the journal names the refused subnet with Keenetic's whole answer, not its last «[»:\n" + audit)
    if "10.50.0.0" in audit:
        fail("a false refusal (the route was replaced by Keenetic) is not told:\n" + audit)
    if "\x1b" in audit or "[K" in audit:
        fail("no terminal codes in the journal:\n" + audit)
    if "tunnel-delete" in audit:
        fail("a move is journaled as a move, not as a deletion:\n" + audit)
for bb in (False, True):
    if bb and not shutil.which("busybox"):
        continue
    with tempfile.TemporaryDirectory() as tmp:
        run(Path(tmp), bb)
print("TUNNEL_MOVE=PASS")
