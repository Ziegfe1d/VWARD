#!/usr/bin/env python3
import json
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
                   "safe_window_start", "safe_window_end", "check_interval_seconds", "apply_window"}
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

print("SETTINGS_REGISTRY=PASS")
