#!/usr/bin/env python3
"""VWARD opens only on devices registered in Keenetic, when that is switched on.

The caller's address is looked up in the router's host list (RCI
show/ip/hotspot).  The router itself always passes, a device registered a
moment ago passes on a fresh look, and a host list that cannot be read lets the
request through instead of locking the owner out.  The switch cannot be turned
on from a device it would shut out.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "web/cgi-bin/api.cgi"
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"

FAKE_CURL = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path
st = json.loads(Path("@STATE@").read_text())
url = [a for a in sys.argv[1:] if a.startswith("http")][-1]
if st.get("down") or not url.endswith("/show/ip/hotspot"):
    sys.exit(22)
print(json.dumps({"host": [{"mac": "aa:bb:cc:00:00:%02x" % i, "ip": ip, "registered": reg} for i, (ip, reg) in enumerate(st["hosts"])]}))
'''


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    state = tmp / "rci.json"
    def hosts(h, down=False):
        state.write_text(json.dumps({"hosts": h, "down": down}))
    hosts([["192.168.1.10", True], ["192.168.1.20", False]])
    curl = tmp / "curl"; curl.write_text(FAKE_CURL.replace("@STATE@", str(state))); curl.chmod(0o755)
    etc = tmp / "etc"; (etc / "console").mkdir(parents=True)
    auth_conf = etc / "console/auth.conf"
    cache = tmp / "devices"
    (tmp / "root/tmp").mkdir(parents=True)
    env = os.environ | {"JQ": shutil.which("jq"), "CURL": str(curl), "VWARD_PROFILE_LIB": "/nonexistent",
                        "VWARD_CONSOLE_AUTH_CONF": str(auth_conf), "VWARD_CONSOLE_DEVICES_CACHE": str(cache),
                        "VWARD_CONSOLE_SESSIONS": str(tmp / "sessions"), "VWARD_CONSOLE_CONFIG_BIN": str(HELPER),
                        "VWARD_CONSOLE_ETC": str(etc), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit"),
                        "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "lock"), "VWARD_ROUTE_STATE": str(tmp / "route"),
                        "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh")}

    def call(ip, action="security-data", post=None):
        e = env | {"REMOTE_ADDR": ip, "QUERY_STRING": "action=" + action, "REQUEST_METHOD": "GET"}
        body = ""
        if post is not None:
            body = urllib.parse.urlencode(post)
            e |= {"REQUEST_METHOD": "POST", "HTTP_X_VWARD_REQUEST": "console", "CONTENT_TYPE": "application/x-www-form-urlencoded", "CONTENT_LENGTH": str(len(body))}
        r = subprocess.run(["sh", str(API)], input=body, env=e, text=True, capture_output=True)
        head, _, payload = r.stdout.partition("\n\n")
        return ("403" in head.split("\n", 1)[0]), json.loads(payload)

    def blocked(ip):
        return call(ip)[0]

    # Off: everyone in the home network.
    if blocked("192.168.1.20") or blocked("192.168.1.99"):
        fail("with the switch off every device passes")

    # Turning it on from an unregistered device is refused; from a registered one it works.
    if call("192.168.1.20", "auth", {"op": "devices", "value": "1"})[1].get("error") != "this_device_not_registered":
        fail("an unregistered device must not switch it on")
    if not call("192.168.1.10", "auth", {"op": "devices", "value": "1"})[1].get("ok"):
        fail("a registered device switches it on")
    if "DEVICES_ONLY=1" not in auth_conf.read_text():
        fail(f"setting not stored: {auth_conf.read_text()}")

    if blocked("192.168.1.10") or blocked("127.0.0.1") or blocked("::ffff:192.168.1.10"):
        fail("registered devices and the router itself pass")
    shut, x = call("192.168.1.20")
    if not shut or x.get("error") != "device_not_registered":
        fail(f"an unregistered device is refused: {x}")
    if not blocked("192.168.1.99") or not blocked(""):
        fail("unknown and empty addresses are refused")
    if call("192.168.1.20", "ping")[0]:
        fail("ping stays open")
    a = call("192.168.1.10", "auth")[1]
    if a.get("devices_only") is not True or a.get("device") != {"ip": "192.168.1.10", "state": "registered"}:
        fail(f"auth shows the switch and this device: {a}")

    # Registered a moment ago: the cached list is re-read (it is older than 5 s).
    hosts([["192.168.1.10", True], ["192.168.1.20", True]])
    cache.write_text(str(int(time.time()) - 10) + "\n192.168.1.10\n")
    if blocked("192.168.1.20"):
        fail("a freshly registered device passes after one fresh look")

    # The router's host list cannot be read: nobody is locked out.
    hosts([], down=True)
    cache.write_text("0\n")
    if blocked("192.168.1.77"):
        fail("an unreadable host list must not lock the owner out")
    hosts([["192.168.1.10", True]])
    cache.unlink()

    # Off again, from a registered device.
    if not call("192.168.1.10", "auth", {"op": "devices", "value": "0"})[1].get("ok") or blocked("192.168.1.20"):
        fail("switching it off opens VWARD to the home network again")

print("CONSOLE_DEVICES=PASS")
