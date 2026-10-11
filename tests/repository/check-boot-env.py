#!/usr/bin/env python3
"""VWARD starts after a reboot even when Entware's own environment is broken.

- Keenetic can start Entware's scripts with a library path of its own; every VWARD script
  loads the device profile, which drops it.
- Entware's curl may not start at all (an OpenSSL library that crashes: «Bus error», seen on a
  router after a reboot). The router's interfaces and configuration come over plain HTTP from
  Keenetic itself, so BusyBox wget answers instead and the profile (LAN address, tunnels)
  still loads: without it neither the Panel nor AdGuard Home start."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/runtime/lib/vward-device-profile.sh"


def fail(message: str) -> None:
    raise SystemExit(f"BOOT_ENV=FAIL: {message}")


r = subprocess.run(["sh", "-c", f'. "{LIB}"; printf "%s" "${{LD_LIBRARY_PATH-unset}}"'],
                   env=os.environ | {"LD_LIBRARY_PATH": "/lib:/usr/lib"}, text=True, capture_output=True, timeout=20)
if r.returncode != 0 or r.stdout != "unset":
    fail(f"the library path stays after the profile: {r.stdout!r} {r.stderr}")

IFACES = {"Bridge0": {"type": "Bridge", "security-level": "private"},
          "GigabitEthernet1": {"type": "GigabitEthernet", "security-level": "public"},
          "Wireguard0": {"type": "Wireguard", "security-level": "public"}}
SYSNAMES = {"Bridge0": "br0", "GigabitEthernet1": "eth3", "Wireguard0": "nwg0"}

with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    (t / "curl").write_text("#!/bin/sh\nkill -BUS $$\n"); (t / "curl").chmod(0o755)
    answers = t / "rci"; answers.mkdir()
    (answers / "show_interface").write_text(json.dumps(IFACES))
    for k, v in SYSNAMES.items():
        (answers / f"sysname_{k}").write_text(json.dumps(v))
    (answers / "running").write_text(json.dumps({"message": ["dns-proxy", "    route object-group vpn Wireguard0 auto", "!"]}))
    (t / "busybox").write_text(f"""#!/bin/sh
[ "$1" = wget ] || exit 127
url=$(eval echo \\${{$#}})
case "$url" in
  */show/interface) cat {answers}/show_interface ;;
  */show/interface/system-name?name=*) cat {answers}/sysname_${{url##*=}} ;;
  */show/running-config) cat {answers}/running ;;
  *) exit 1 ;;
esac
""")
    (t / "busybox").chmod(0o755)
    env = {"PATH": os.environ["PATH"], "VWARD_CURL_BIN": str(t / "curl"), "VWARD_RCI_WGET": f"{t}/missing:wget {t}/busybox:wget",
           "VWARD_DEVICE_MAP_CACHE": str(t / "map.tsv"), "VWARD_RCI_BASE": "http://127.0.0.1:79/rci"}
    script = f'. "{LIB}"; vward_device_map; echo ---; vward_running_config'
    r = subprocess.run(["sh", "-c", script], env=env, text=True, capture_output=True, timeout=30)
    if r.returncode != 0:
        fail(f"no device map without curl: {r.returncode} {r.stderr}")
    out = r.stdout
    for need in ("I\tBridge0\tBridge\tbr0\tprivate", "I\tWireguard0\tWireguard\tnwg0\tpublic", "R\tvpn\tWireguard0",
                 "---\ndns-proxy\n    route object-group vpn Wireguard0 auto"):
        if need not in out:
            fail(f"without curl, through wget: {need!r} missing in\n{out}")


api = (ROOT / "web/cgi-bin/api.cgi").read_text()
if '"$CURL" --version' not in api or "STARTUP DISABLED" not in api or 'id:"boot"' not in api:
    fail("the diagnostics do not show a curl that cannot start or Entware startup switched off")
# curl --version runs even with a broken OpenSSL; only a real HTTPS request shows the crash.
if "https://1.1.1.1/cdn-cgi/trace" not in api or "126|127|13[0-9])" not in api or "status:$curl,detail:$curl_detail" not in api:
    fail("the diagnostics trust curl --version and miss curl crashing on HTTPS")
# A curl that runs and hears an error from Keenetic is not replaced: wget is not even asked.
with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    (t / "curl").write_text("#!/bin/sh\nexit 22\n"); (t / "curl").chmod(0o755)
    (t / "busybox").write_text(f"#!/bin/sh\necho asked >> {t}/wget.log\nexit 1\n"); (t / "busybox").chmod(0o755)
    env = {"PATH": os.environ["PATH"], "VWARD_CURL_BIN": str(t / "curl"), "VWARD_RCI_WGET": f"{t}/busybox:wget"}
    r = subprocess.run(["sh", "-c", f'. "{LIB}"; vward_rci_get show/interface/system-name?name=Bridge0 3'], env=env, text=True, capture_output=True, timeout=20)
    if r.returncode == 0 or (t / "wget.log").exists():
        fail("an error answer from a working curl went on to wget")
# A wget that crashes (BusyBox 1.37 of Entware, the same place every time) is asked once, not
# on every request until the router restarts.
with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    (t / "busybox").write_text(f"#!/bin/sh\necho asked >> {t}/wget.log\nkill -SEGV $$\n"); (t / "busybox").chmod(0o755)
    env = {"PATH": os.environ["PATH"], "VWARD_CURL_BIN": str(t / "no-curl"), "VWARD_RCI_WGET": f"{t}/busybox:wget",
           "VWARD_WGET_BROKEN_DIR": str(t / "broken")}
    for _ in range(3):
        subprocess.run(["sh", "-c", f'. "{LIB}"; vward_rci_get show/version 3'], env=env, capture_output=True, timeout=20)
    if (t / "wget.log").read_text().count("asked") != 1:
        fail("a crashing wget is asked again and again")
print("BOOT_ENV=PASS")
