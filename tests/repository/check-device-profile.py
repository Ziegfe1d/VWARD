#!/usr/bin/env python3
from pathlib import Path
import json
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "components/runtime/lib/vward-device-profile.sh"
runtime_files = [
    p
    for base in (ROOT / "components", ROOT / "web", ROOT / "config")
    for p in base.rglob("*")
    if p.is_file() and (p.suffix in (".sh", ".cgi", ".html", ".js", ".conf", ".example") or "init.d" in p.parts)
]
runtime = "\n".join(p.read_text(errors="ignore") for p in runtime_files)
for value in ("192.168.1.1", "192.168.1.0/24", '"eth3"', '"nwg1"', '"domain-list22"'):
    assert value not in runtime, f"device-specific runtime value remains: {value}"
for pattern in (r"KN-?1913", r"Wireguard\[?[0-9]", r"WifiMaster[0-9]", r"Bridge[0-9]", r"/sys/class/net/(nwg|wg)\*"):
    hits = [str(p.relative_to(ROOT)) for p in runtime_files if re.search(pattern, p.read_text(errors="ignore"))]
    assert not hits, f"model or interface-name hardcode {pattern!r} in {hits}"

profile = PROFILE.read_text()
for name in ("VWARD_LAN_ADDRESS", "VWARD_LAN_SUBNET", "VWARD_WAN_DEVICE", "VWARD_TUNNEL_DEVICE", "VWARD_CONSOLE_PORT", "VWARD_ADGUARD_ADDRESS", "VWARD_ADGUARD_PORT", "VWARD_LAN_INTERFACE"):
    assert name in profile
assert "WAN device is missing or ambiguous" in profile
assert "tunnel device is missing or ambiguous" in profile


def run(cmd, env):
    return subprocess.run(["sh", "-c", f'. "{PROFILE}"; {cmd}'], env=env, text=True, capture_output=True)


def write_exec(path, body):
    path.write_text(body)
    path.chmod(0o755)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    config = tmp / "device.conf"
    config.write_text("""VWARD_LAN_ADDRESS=10.20.30.1
VWARD_LAN_SUBNET=10.20.30.0/24
VWARD_LAN_INTERFACE=Home
VWARD_DNS_SERVER=10.20.30.1
VWARD_WAN_DEVICE=wan0
VWARD_WAN_INTERFACE=Provider
VWARD_TUNNEL_DEVICE=wg7
VWARD_TUNNEL_INTERFACE=Wireguard7
VWARD_POLICY_GROUP=policy7
VWARD_CONSOLE_PORT=9088
VWARD_ADGUARD_ADDRESS=10.20.30.2
VWARD_ADGUARD_PORT=3080
""")
    config.chmod(0o600)
    env = os.environ | {"VWARD_DEVICE_CONFIG": str(config), "VWARD_DEVICE_MAP_CACHE": str(tmp / "unused.tsv"),
                        "VWARD_CURL_BIN": "/nonexistent/curl"}
    result = run('vward_profile_load; printf "%s|%s|%s|%s|%s" "$VWARD_LAN_ADDRESS" "$VWARD_TUNNEL_DEVICE" "$VWARD_CONSOLE_PORT" "$VWARD_ADGUARD_ADDRESS" "$VWARD_ADGUARD_PORT"', env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "10.20.30.1|wg7|9088|10.20.30.2|3080"

# Simulated Keenetic with deliberately unusual names: nothing may depend on
# Wireguard0/1, Bridge0, WifiMaster0/1 or a particular router model.
INTERFACES = {
    "GigabitEthernet0/Vlan4": {"type": "Vlan", "security-level": "public"},
    "Bridge2": {"type": "Bridge", "security-level": "private"},
    "Bridge5": {"type": "Bridge", "security-level": "protected"},
    "Wireguard3": {"type": "Wireguard", "security-level": "public"},
    "Wireguard8": {"type": "Wireguard", "security-level": "public"},
    "WifiMaster0/AccessPoint2": {"type": "AccessPoint"},
}
SYSTEM_NAMES = {"GigabitEthernet0/Vlan4": "eth2.4", "Bridge2": "br2", "Bridge5": "br5",
                "Wireguard3": "nwg3", "Wireguard8": "nwg8", "WifiMaster0/AccessPoint2": "ra2"}


def keenetic(tmp, running_config, wan_routes=("default via 100.64.0.1 dev eth2.4",)):
    tools = tmp / "tools"
    tools.mkdir()
    (tmp / "interface.json").write_text(json.dumps(INTERFACES))
    names = "\n".join(f'    *"name={k}") printf \'"%s"\' "{v}" ;;' for k, v in SYSTEM_NAMES.items())
    write_exec(tools / "curl", f"""#!/bin/sh
for URL do :; done
case "$URL" in
    */show/interface) cat "{tmp}/interface.json" ;;
    */show/interface/system-name*)
        case "$URL" in
{names}
            *) exit 22 ;;
        esac ;;
    *) exit 22 ;;
esac
""")
    (tmp / "running-config").write_text(running_config)
    write_exec(tools / "ndmc", f'#!/bin/sh\n[ "$2" = "show running-config" ] && cat "{tmp}/running-config"\n')
    (tmp / "routes").write_text("\n".join(wan_routes) + "\n")
    write_exec(tools / "ip", f"""#!/bin/sh
case "$*" in
    "-4 route show default") cat "{tmp}/routes" ;;
    "-o -4 addr show scope global"|"-o -4 addr show")
        printf '%s\\n' \\
            '3: eth2.4    inet 100.64.0.10/24 brd 100.64.0.255 scope global eth2.4' \\
            '5: br2    inet 10.77.0.1/24 brd 10.77.0.255 scope global br2' \\
            '6: br5    inet 10.88.0.1/24 brd 10.88.0.255 scope global br5' \\
            '9: nwg3    inet 172.16.3.2/32 scope global nwg3' \\
            '10: nwg8    inet 172.16.8.2/32 scope global nwg8' ;;
    "-4 route show dev br2 scope link") echo '10.77.0.0/24 proto kernel scope link src 10.77.0.1' ;;
    *) exit 0 ;;
esac
""")
    sysfs = tmp / "sys"
    for dev in ("eth2.4", "br2", "br5", "nwg3", "nwg8"):
        (sysfs / dev).mkdir(parents=True)
        (sysfs / dev / "uevent").write_text("DEVTYPE=wireguard\n" if dev.startswith("nwg") else "")
    return os.environ | {
        "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
        "VWARD_DEVICE_CONFIG": str(tmp / "absent.conf"),
        "VWARD_DEVICE_MAP_CACHE": str(tmp / "device-map.tsv"),
        "VWARD_SYSFS_NET": str(sysfs),
        "VWARD_CURL_BIN": str(tools / "curl"),
    }


SHOW = 'vward_profile_load && printf "%s|" "$VWARD_WAN_DEVICE" "$VWARD_WAN_INTERFACE" "$VWARD_LAN_DEVICE" "$VWARD_LAN_INTERFACE" "$VWARD_LAN_ADDRESS" "$VWARD_LAN_SUBNET" "$VWARD_TUNNEL_INTERFACE" "$VWARD_TUNNEL_DEVICE" "$VWARD_POLICY_GROUP"'

with tempfile.TemporaryDirectory() as tmp:
    env = keenetic(Path(tmp), """dns-proxy
    route object-group AdaptiveAuto Wireguard8 auto
    route object-group streaming Wireguard8 auto
!
ip route 203.0.113.0 255.255.255.0 nwg8 auto
""")
    result = run(SHOW, env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "eth2.4|GigabitEthernet0/Vlan4|br2|Bridge2|10.77.0.1|10.77.0.0/24|Wireguard8|nwg8|streaming|", result.stdout
    assert (Path(tmp) / "device-map.tsv").is_file(), "discovery map must be cached"
    (Path(tmp) / "interface.json").write_text("{}")
    result = run(SHOW, env)
    assert result.returncode == 0 and "Wireguard8|nwg8" in result.stdout, "fresh cache must be reused"

with tempfile.TemporaryDirectory() as tmp:
    env = keenetic(Path(tmp), "!\n")
    result = run(SHOW, env)
    assert result.returncode != 0, "several unreferenced tunnels must fail closed"
    assert "Wireguard3(nwg3)" in result.stderr and "Wireguard8(nwg8)" in result.stderr, result.stderr

with tempfile.TemporaryDirectory() as tmp:
    env = keenetic(Path(tmp), "!\n")
    (Path(tmp) / "absent.conf").write_text("VWARD_TUNNEL_INTERFACE=Wireguard3\n")
    (Path(tmp) / "absent.conf").chmod(0o600)
    result = run(SHOW, env)
    assert result.returncode == 0, result.stderr
    assert "|Wireguard3|nwg3|" in result.stdout, result.stdout

with tempfile.TemporaryDirectory() as tmp:
    env = keenetic(Path(tmp), "!\n", wan_routes=("default via 1.1.1.1 dev wan0", "default via 2.2.2.2 dev wan1"))
    result = run("vward_discover_wan_device", env)
    assert result.returncode == 0 and result.stdout == "", "ambiguous WAN discovery must fail closed"
    result = run(SHOW, env)
    assert result.returncode != 0, "profile errors must fail the whole load"

with tempfile.TemporaryDirectory() as tmp:
    env = keenetic(Path(tmp), "!\n")
    result = run("vward_discover_lan_interface", env)
    assert result.returncode == 0 and result.stdout.strip() == "Bridge2", result.stdout + result.stderr

print("DEVICE_PROFILE=PASS")
