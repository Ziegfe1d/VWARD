#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
registry = json.loads((ROOT / "config/components/component-registry.json").read_text())
components = registry["components"]
ids = [item["id"] for item in components]
assert len(ids) == len(set(ids)), "duplicate component id"
assert ids.count("ads-privacy-guard") == 1

targets = []
for component in components:
    targets.extend(component.get("runtime_targets", []))
assert len(targets) == len(set(targets)), "duplicate runtime target"

ads = next(item for item in components if item["id"] == "ads-privacy-guard")
ads_targets = set(ads["runtime_targets"])
for target in (
    "/opt/bin/vward-ads-privacy-scheduler.sh",
    "/opt/bin/vward-ads-privacy-job.sh",
    "/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh",
    "/opt/share/vward/ads-privacy-guard/source-registry.json",
):
    assert target in ads_targets, target

cron = (ROOT / "config/cron/root.crontab").read_text()
assert cron.count("/opt/bin/vward-ads-privacy-scheduler.sh") == 1
print("ADS_PRIVACY_INTEGRATION=PASS")
