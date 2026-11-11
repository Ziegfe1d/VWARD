#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import tempfile
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
# The scheduler every 5 minutes, its DNS guard every minute (owner 08.11): one line each.
assert cron.count("*/5 * * * * /opt/bin/vward-ads-privacy-scheduler.sh >") == 1
assert cron.count("* * * * * /opt/bin/vward-ads-privacy-scheduler.sh dns >") == 1
assert cron.count("/opt/bin/vward-ads-privacy-scheduler.sh") == 2

scripts = ROOT / "components/ads-privacy-guard/scripts"
scheduler = scripts / "vward-ads-privacy-scheduler.sh"
guard = scripts / "vward-ads-privacy-dns-guard.sh"
shells = [["sh"]]
if shutil.which("busybox"):
    shells.append(["busybox", "sh"])

for shell in shells:
    with tempfile.TemporaryDirectory() as temp:
        tmp = Path(temp)
        (tmp / "configured").touch()
        (tmp / "uptime").write_text("0 0\n")
        common = tmp / "common.sh"
        common.write_text("""
ADS_CONFIG="$T/configured"
ADS_AGH_AUTH_FILE="$T/absent-auth"
ADS_STATE="$T"
ADS_DEVICE_PROFILE_LIB="$T/absent-profile"
ads_mkdirs() { :; }
ads_load_config() { echo load-config >> "$T/calls"; [ "${CONFIG_FAIL:-0}" = 0 ] || exit 1; ENABLED=0; }
ads_source_registry_merge() { echo merge-registry >> "$T/calls"; }
ads_num() { echo ads-num >> "$T/calls"; printf '%s\\n' "${1:-$2}"; }
ads_bool() { return 1; }
""")
        admission = tmp / "admission.sh"
        admission.write_text("""
vward_component_gate() { [ "${COMPONENT_OFF:-0}" = 0 ] || exit 69; }
vward_admission_enter() { echo enter >> "$T/calls"; return "${DENY:-0}"; }
vward_admission_leave() { echo leave >> "$T/calls"; }
""")
        fake_guard = tmp / "guard"
        fake_guard.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "$T/calls"\n')
        fake_guard.chmod(0o755)
        env = os.environ | {
            "T": str(tmp), "VWARD_ADS_LIB": str(common), "VWARD_ADMISSION_LIB": str(admission),
            "VWARD_ADS_DNS_GUARD": str(fake_guard), "VWARD_ADS_SCHEDULER_STATUS": str(tmp / "status"),
            "VWARD_ADS_ORPHAN_MARK": str(tmp / "orphan"), "VWARD_UPTIME_FILE": str(tmp / "uptime"),
            "VWARD_ADS_CLIENTS_SYNC": "/bin/true", "VWARD_ADS_ROUTE_DNS": "/bin/true",
            "VWARD_DNS_GUARD_CONF": str(tmp / "dns.conf"), "VWARD_DNS_GUARD_STATE": str(tmp / "dns-state"),
            "VWARD_DNS_GUARD_PARK": str(tmp / "park"), "VWARD_DNS_CHAIN_STATE": str(tmp / "chain"),
            "VWARD_COMPONENT_STATE": str(tmp / "components"),
        }

        def run(script, *args, **overrides):
            calls = tmp / "calls"
            calls.unlink(missing_ok=True)
            result = subprocess.run(
                [*shell, str(script), *args], env=env | overrides, capture_output=True, text=True, timeout=10
            )
            return result, calls.read_text().splitlines() if calls.exists() else []

        result, calls = run(scheduler, "dns")
        assert (result.returncode, result.stdout.strip()) == (0, "SCHEDULER=DNS_TICK"), result
        assert calls == ["enter", "load-config", "tick", "leave"], (shell, calls)
        result, calls = run(scheduler, "dns", CONFIG_FAIL="1")
        assert result.returncode == 1 and calls == ["enter", "load-config", "leave"], (shell, result, calls)
        result, calls = run(scheduler, "dns", DENY="75")
        assert result.returncode == 75 and calls == ["enter"], (shell, result, calls)
        result, calls = run(scheduler, "dns", COMPONENT_OFF="1")
        assert result.returncode == 69 and calls == [], (shell, result, calls)
        (tmp / "configured").unlink()
        result, calls = run(scheduler, "dns")
        assert (result.returncode, result.stdout.strip()) == (0, "SCHEDULER=NOT_CONFIGURED"), result
        assert calls == ["enter", "leave"], (shell, calls)
        (tmp / "configured").touch()
        result, calls = run(scheduler)
        assert (result.returncode, result.stdout.strip()) == (0, "SCHEDULER=DISABLED"), result
        assert calls.count("merge-registry") == 1 and "load-config" in calls and "tick" not in calls, (shell, calls)
        result, calls = run(guard, "status")
        assert result.returncode == 0 and "chain=" in result.stdout and not calls, (shell, result, calls)

print("ADS_PRIVACY_INTEGRATION=PASS")
