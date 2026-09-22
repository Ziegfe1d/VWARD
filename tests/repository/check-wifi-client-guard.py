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
for marker in ("ENABLED=0", 'vward-wifi-client-monitor.sh" --once', 'vward-wifi-client-analyze.sh" --once', "vward_admission_enter wifi-client-guard"):
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

for marker in ("HOME_BRIDGE=\n", "AP_2G_PATTERN=\n", "AP_5G_PATTERN=\n"):
    if marker not in cfg:
        raise SystemExit(f"FAIL: Wi-Fi Client Guard must discover device values by default: {marker.strip()}")
if "VWARD_LAN_INTERFACE" not in control or "vward_discover_lan_interface" not in control:
    raise SystemExit("FAIL: control must take the home segment from the device profile")

import os, subprocess, tempfile
with tempfile.TemporaryDirectory() as tmp:
    tmp=Path(tmp)
    tools=tmp/"tools"; tools.mkdir()
    (tmp/"interface.json").write_text(json.dumps({
        "WifiMaster3": {"type": "WifiMaster", "channel": 44},
        "WifiMaster3/AccessPoint1": {"type": "AccessPoint", "interface-name": "HomeFast"},
        "WifiMaster6": {"type": "WifiMaster", "band": "2.4GHz", "channel": 40},
        "WifiMaster6/AccessPoint0": {"type": "AccessPoint", "interface-name": "HomeSlow"},
        "WifiMaster9": {"type": "WifiMaster"},
        "WifiMaster9/AccessPoint0": {"type": "AccessPoint"},
    }))
    (tools/"curl").write_text(f'#!/bin/sh\nfor URL do :; done\ncase "$URL" in */show/interface) cat "{tmp}/interface.json" ;; *) exit 22 ;; esac\n')
    (tools/"ndmc").write_text("""#!/bin/sh
[ "$2" = "show associations" ] || exit 1
cat <<'EOF'
station:
    mac: AA:AA:AA:AA:AA:01
    ap: WifiMaster3/AccessPoint1
    rssi: -61
station:
    mac: AA:AA:AA:AA:AA:02
    ap: HomeSlow
    rssi: -48
station:
    mac: AA:AA:AA:AA:AA:03
    ap: WifiMaster9/AccessPoint0
    rssi: -50
EOF
""")
    for tool in ("curl","ndmc"): (tools/tool).chmod(0o755)
    conf=tmp/"wifi.conf"; conf.write_text("ENABLED=1\n")
    env=os.environ|{"PATH":f"{tools}{os.pathsep}{os.environ['PATH']}","VWARD_CURL_BIN":str(tools/"curl"),
                    "VWARD_WIFI_CLIENT_GUARD_CONF":str(conf),"VWARD_WIFI_CLIENT_GUARD_STATE":str(tmp/"state"),
                    "VWARD_WIFI_CLIENT_GUARD_LOG":str(tmp/"wifi.log")}
    result=subprocess.run(["sh",str(root/"components/wifi-client-guard/scripts/vward-wifi-client-monitor.sh"),"--once"],env=env,text=True,capture_output=True)
    if result.returncode != 0:
        raise SystemExit(f"FAIL: monitor simulation rc={result.returncode}: {result.stderr}")
    bands={line.split("\t")[1]:line.split("\t")[3] for line in (tmp/"state/current.tsv").read_text().splitlines()}
    expected_bands={"aa:aa:aa:aa:aa:01":"5","aa:aa:aa:aa:aa:02":"2.4","aa:aa:aa:aa:aa:03":"unknown"}
    if bands != expected_bands:
        raise SystemExit(f"FAIL: AP band discovery {bands} != {expected_bands}")

if "vward_admission_enter wifi-client-control" not in control:
    raise SystemExit("FAIL: Wi-Fi control must not mutate the router during an update")

with tempfile.TemporaryDirectory() as tmp:
    tmp=Path(tmp)
    (tmp/"root/tmp").mkdir(parents=True)
    bindir=tmp/"bin"; bindir.mkdir()
    for name in ("monitor","analyze"):
        script=bindir/f"vward-wifi-client-{name}.sh"
        script.write_text(f'#!/bin/sh\necho {name} >> "{tmp}/ran"\n'); script.chmod(0o755)
    conf=tmp/"wifi.conf"; conf.write_text("ENABLED=1\n")
    lock=tmp/"wifi.lock"
    env=os.environ|{"VWARD_WIFI_CLIENT_GUARD_CONF":str(conf),"VWARD_WIFI_CLIENT_GUARD_LOCK":str(lock),
                    "VWARD_WIFI_CLIENT_GUARD_BIN":str(bindir),"VWARD_ROOT_PREFIX":str(tmp/"root"),
                    "VWARD_ADMISSION_LIB":str(root/"components/runtime/lib/vward-runtime-admission.sh")}
    scheduler=["sh",str(root/"components/wifi-client-guard/scripts/vward-wifi-client-scheduler.sh")]
    def ran():
        return (tmp/"ran").read_text().split() if (tmp/"ran").exists() else []

    (tmp/"root/tmp/vward-update-requested").write_text("x")
    if subprocess.run(scheduler,env=env).returncode != 75 or ran():
        raise SystemExit("FAIL: Wi-Fi scheduler must yield to a requested update")
    (tmp/"root/tmp/vward-update-requested").unlink()

    holder=subprocess.Popen(["sleep","30"])
    try:
        start=subprocess.run(["sh","-c",f'. "{env["VWARD_ADMISSION_LIB"]}"; vward_admission_pid_start {holder.pid}'],text=True,capture_output=True).stdout.strip()
        lock.mkdir(); (lock/"pid").write_text(f"{holder.pid}\n"); (lock/"pid_start").write_text(start+"\n")
        if subprocess.run(scheduler,env=env).returncode != 0 or ran():
            raise SystemExit("FAIL: Wi-Fi scheduler must not overlap a live run")
    finally:
        holder.kill(); holder.wait()

    if subprocess.run(scheduler,env=env).returncode != 0 or ran() != ["monitor","analyze"]:
        raise SystemExit(f"FAIL: Wi-Fi scheduler must reclaim a stale lock and run: {ran()}")
    if lock.exists():
        raise SystemExit("FAIL: Wi-Fi scheduler must release its lock")

print("WIFI_CLIENT_GUARD=PASS")
