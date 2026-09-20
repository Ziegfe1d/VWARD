#!/usr/bin/env python3
from pathlib import Path
import json

root=Path(__file__).resolve().parents[2]
registry=json.loads((root/"config/components/component-registry.json").read_text(encoding="utf-8"))
component=next((c for c in registry["components"] if c["id"]=="wifi-client-guard"),None)
if component is None:
    raise SystemExit("FAIL: wifi-client-guard missing from registry")
expected={
    "/opt/bin/vward-wifi-client-monitor.sh",
    "/opt/bin/vward-wifi-client-analyze.sh",
    "/opt/bin/vward-wifi-client-control.sh",
    "/opt/bin/vward-wifi-client-scheduler.sh",
}
if set(component["runtime_targets"]) != expected:
    raise SystemExit("FAIL: unexpected Wi-Fi Client Guard runtime targets")

cfg=(root/"config/wifi-client-guard/wifi-client-guard.conf.example").read_text(encoding="utf-8")
for marker in ("ENABLED=0","CONTROL_ENABLED=0","AUTO_APPLY=0"):
    if marker not in cfg:
        raise SystemExit(f"FAIL: unsafe Wi-Fi Client Guard default: {marker}")

control=(root/"components/wifi-client-guard/scripts/vward-wifi-client-control.sh").read_text(encoding="utf-8")
for marker in ("bind-2g) BAND=0","bind-5g) BAND=1","auto) BAND=auto",
               "WIFI_BIND_2G","WIFI_BIND_5G","WIFI_BAND_AUTO",
               "system configuration save","backup write failed","acceptance failed; rollback attempted"):
    if marker not in control:
        raise SystemExit(f"FAIL: control safety marker missing: {marker}")
for forbidden in ("eval ","sh -c","ndmc -c \"$"):
    if forbidden in control:
        raise SystemExit(f"FAIL: unsafe dynamic execution in control: {forbidden}")

monitor=(root/"components/wifi-client-guard/scripts/vward-wifi-client-monitor.sh").read_text(encoding="utf-8")
if "ndmc -c 'show associations'" not in monitor:
    raise SystemExit("FAIL: read-only association source missing")
if "mac band" in monitor or "system configuration save" in monitor:
    raise SystemExit("FAIL: monitor must remain read-only")

doc=(root/"docs/WIFI_CLIENT_GUARD.md").read_text(encoding="utf-8")
for marker in ("AUTO_APPLY=0","read-only API/экран Console","планировщик"):
    if marker not in doc:
        raise SystemExit(f"FAIL: staged rollout contract missing: {marker}")

scheduler=(root/"components/wifi-client-guard/scripts/vward-wifi-client-scheduler.sh").read_text(encoding="utf-8")
for marker in ("ENABLED=0", "vward-wifi-client-monitor.sh --once", "vward-wifi-client-analyze.sh --once"):
    if marker not in scheduler:
        raise SystemExit(f"FAIL: scheduler marker missing: {marker}")

cron=(root/"config/cron/root.crontab").read_text(encoding="utf-8")
if "/opt/bin/vward-wifi-client-scheduler.sh" not in cron:
    raise SystemExit("FAIL: Wi-Fi Client Guard scheduler is not registered in cron")

api=(root/"web/cgi-bin/api.cgi").read_text(encoding="utf-8")
for marker in ("wifi-data", 'component:\"wifi-client-guard\"', "wifi-control", "WIFI_BIND_2G"):
    if marker not in api:
        raise SystemExit(f"FAIL: Console Wi-Fi API marker missing: {marker}")

ui=(root/"web/assets/vward-console.js").read_text(encoding="utf-8")
for marker in ("loadWifiData", "renderWifiData", "wifi-client-guard"):
    if marker not in ui:
        raise SystemExit(f"FAIL: Console Wi-Fi UI marker missing: {marker}")

print("WIFI_CLIENT_GUARD=PASS")
