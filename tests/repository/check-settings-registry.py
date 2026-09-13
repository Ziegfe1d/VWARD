#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
registry_path = ROOT / "config/settings/settings-registry.json"
schema_path = ROOT / "config/settings/settings-registry.schema.json"
registry = json.loads(registry_path.read_text(encoding="utf-8"))
schema = json.loads(schema_path.read_text(encoding="utf-8"))

assert registry["schema"] == 1
assert schema["properties"]["schema"]["const"] == 1
settings = registry["settings"]
assert len(settings) >= 17
assert len({item["id"] for item in settings}) == len(settings)
required = {"id", "component", "section", "label_ru", "description_ru", "source", "key", "type", "editable", "secret", "restart_requirement", "risk"}
for item in settings:
    assert required <= item.keys(), item["id"]
    assert item["secret"] is False, item["id"]
    if item["editable"]:
        assert item["source"] == "update.conf"
        assert item["key"] in {"auto_apply", "auto_critical", "auto_important", "auto_routine"}
    else:
        assert item.get("read_only_reason"), item["id"]

jq = shutil.which("jq")
assert jq, "jq is required"
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    device = tmp / "device.conf"
    device.write_text("""VWARD_LAN_ADDRESS=10.20.30.1
VWARD_LAN_SUBNET=10.20.30.0/24
VWARD_DNS_SERVER=10.20.30.1
VWARD_PROBE_DNS=10.20.30.1
VWARD_ADGUARD_ADDRESS=10.20.30.1
VWARD_ADGUARD_PORT=3000
VWARD_WAN_DEVICE=wan0
VWARD_WAN_INTERFACE=Provider
VWARD_TUNNEL_DEVICE=wg7
VWARD_TUNNEL_INTERFACE=Wireguard7
VWARD_POLICY_GROUP=policy7
VWARD_CONSOLE_PORT=9088
VWARD_RCI_BASE=http://127.0.0.1:79/rci
""", encoding="utf-8")
    device.chmod(0o600)
    update = tmp / "update.conf"
    update.write_text("auto_apply=1\nauto_critical=1\nauto_important=0\nauto_routine=0\n", encoding="utf-8")
    env = os.environ | {
        "REQUEST_METHOD": "GET",
        "QUERY_STRING": "action=settings-data",
        "JQ": jq,
        "VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"),
        "VWARD_DEVICE_CONFIG": str(device),
        "VWARD_SETTINGS_REGISTRY": str(registry_path),
        "VWARD_UPDATE_CONFIG": str(update),
    }
    result = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.split("\n\n", 1)[1])
    assert payload["ok"] is True
    assert payload["profile_ready"] is True
    assert payload["authentication_required_for_device_write"] is True
    by_id = {item["id"]: item for item in payload["settings"]}
    assert by_id["device.lan_address"]["effective"] == "10.20.30.1"
    assert by_id["device.console_port"]["effective"] == 9088
    assert by_id["update.auto_apply"]["effective"] is True
    assert by_id["update.auto_important"]["effective"] is False
    assert by_id["device.lan_address"]["editable"] is False

print("SETTINGS_REGISTRY=PASS")
