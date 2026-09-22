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
assert len(settings) >= 46
assert len({item["id"] for item in settings}) == len(settings)
required = {"id", "component", "section", "label_ru", "description_ru", "source", "key", "type", "editable", "secret", "restart_requirement", "risk"}
editable_update = {"auto_apply", "auto_critical", "auto_important", "auto_routine",
                   "safe_window_start", "safe_window_end", "check_interval_seconds"}
editable_ads = {
    "ENABLED", "RUN_MODE", "SCHEDULE_INTERVAL_MIN", "DYNAMIC_MIN_INTERVAL_SEC",
    "DYNAMIC_MAX_LOAD_PER_CPU_X100", "DYNAMIC_MIN_MEM_AVAILABLE_KB",
    "DYNAMIC_MIN_OPT_FREE_KB", "DYNAMIC_MAX_CANDIDATES_PER_RUN",
    "AUTO_SOURCE_UPDATE", "SOURCE_UPDATE_INTERVAL_HOURS", "QUERY_SOURCE",
    "AUTO_RULE_SCOPE", "PUBLISH_MODE", "AUTO_PUBLISH",
}
for item in settings:
    assert required <= item.keys(), item["id"]
    assert item["secret"] is False, item["id"]
    if item["editable"]:
        if item["source"] == "update.conf":
            assert item["key"] in editable_update
        else:
            assert item["source"] == "ads-privacy-guard.conf"
            assert item["key"] in editable_ads
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
    update.write_text("""update_enabled=1
auto_apply=1
auto_critical=1
auto_important=0
auto_routine=0
channel=dev
safe_window_start=03:00
safe_window_end=05:00
important_max_delay_seconds=7200
routine_max_delay_seconds=86400
minimum_free_kb=8192
max_manifest_size=262144
max_package_size=16777216
max_unpacked_size=67108864
backup_keep=3
health_timeout_seconds=30
check_interval_seconds=900
request_timeout_seconds=120
barrier_integration_ready=1
""", encoding="utf-8")
    ads = tmp / "ads-privacy-guard.conf"
    ads.write_text("""ENABLED=0
RUN_MODE=manual
SCHEDULE_INTERVAL_MIN=30
DYNAMIC_MIN_INTERVAL_SEC=300
DYNAMIC_MAX_LOAD_PER_CPU_X100=120
DYNAMIC_MIN_MEM_AVAILABLE_KB=32768
DYNAMIC_MIN_OPT_FREE_KB=65536
DYNAMIC_MAX_CANDIDATES_PER_RUN=50
AUTO_SOURCE_UPDATE=1
SOURCE_UPDATE_INTERVAL_HOURS=24
QUERY_SOURCE=auto
AUTO_RULE_SCOPE=exact
PUBLISH_MODE=staged
AUTO_PUBLISH=0
""", encoding="utf-8")
    ads.chmod(0o600)
    env = os.environ | {
        "REQUEST_METHOD": "GET",
        "QUERY_STRING": "action=settings-data",
        "JQ": jq,
        "VWARD_PROFILE_LIB": str(ROOT / "components/runtime/lib/vward-device-profile.sh"),
        "VWARD_DEVICE_CONFIG": str(device),
        "VWARD_SETTINGS_REGISTRY": str(registry_path),
        "VWARD_UPDATE_CONFIG": str(update),
        "VWARD_ADS_CONFIG": str(ads),
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
    assert by_id["update.enabled"]["effective"] is True
    assert by_id["update.channel"]["effective"] == "dev"
    assert by_id["update.check_interval"]["effective"] == 900
    assert by_id["update.safe_window_start"]["effective"] == "03:00"
    assert by_id["update.max_package_size"]["effective"] == 16777216
    assert by_id["update.barrier_ready"]["effective"] is True
    assert by_id["ads.enabled"]["effective"] is False
    assert by_id["ads.run_mode"]["effective"] == "manual"
    assert by_id["ads.dynamic_interval"]["effective"] == 300
    assert by_id["ads.publish_mode"]["effective"] == "staged"
    assert by_id["ads.auto_publish"]["effective"] is False
    assert by_id["device.lan_address"]["editable"] is False
    assert "manifest_url" not in {item["key"] for item in payload["settings"]}
    assert "public_key_file" not in {item["key"] for item in payload["settings"]}

print("SETTINGS_REGISTRY=PASS")
