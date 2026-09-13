#!/usr/bin/env python3
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
runtime = "\n".join(
    p.read_text(errors="ignore")
    for base in (ROOT / "components", ROOT / "web")
    for p in base.rglob("*")
    if p.is_file() and (p.suffix in (".sh", ".cgi", ".html", ".conf") or "init.d" in p.parts)
)
for value in ("192.168.1.1", "192.168.1.0/24", '"eth3"', '"nwg1"', '"domain-list22"'):
    assert value not in runtime, f"device-specific runtime value remains: {value}"

profile = (ROOT / "components/runtime/lib/vward-device-profile.sh").read_text()
for name in ("VWARD_LAN_ADDRESS", "VWARD_LAN_SUBNET", "VWARD_WAN_DEVICE", "VWARD_TUNNEL_DEVICE", "VWARD_CONSOLE_PORT", "VWARD_ADGUARD_ADDRESS", "VWARD_ADGUARD_PORT"):
    assert name in profile
assert "WAN device is missing or ambiguous" in profile
assert "tunnel device is missing or ambiguous" in profile

with tempfile.NamedTemporaryFile("w", delete=False) as f:
    f.write("""VWARD_LAN_ADDRESS=10.20.30.1
VWARD_LAN_SUBNET=10.20.30.0/24
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
    config = f.name
env = os.environ | {"VWARD_DEVICE_CONFIG": config}
cmd = f'. "{ROOT / "components/runtime/lib/vward-device-profile.sh"}"; vward_profile_load; printf "%s|%s|%s|%s|%s" "$VWARD_LAN_ADDRESS" "$VWARD_TUNNEL_DEVICE" "$VWARD_CONSOLE_PORT" "$VWARD_ADGUARD_ADDRESS" "$VWARD_ADGUARD_PORT"'
result = subprocess.run(["sh", "-c", cmd], env=env, text=True, capture_output=True)
os.unlink(config)
assert result.returncode == 0, result.stderr
assert result.stdout == "10.20.30.1|wg7|9088|10.20.30.2|3080"

with tempfile.TemporaryDirectory() as tools:
    fake_ip = Path(tools) / "ip"
    fake_ip.write_text("#!/bin/sh\nprintf '%s\\n' 'default via 1.1.1.1 dev wan0' 'default via 2.2.2.2 dev wan1'\n")
    fake_ip.chmod(0o755)
    env = os.environ | {"PATH": tools + os.pathsep + os.environ["PATH"]}
    cmd = f'. "{ROOT / "components/runtime/lib/vward-device-profile.sh"}"; vward_discover_wan_device'
    result = subprocess.run(["sh", "-c", cmd], env=env, text=True, capture_output=True)
    assert result.returncode == 0
    assert result.stdout == "", "ambiguous WAN discovery must fail closed"
print("DEVICE_PROFILE=PASS")
