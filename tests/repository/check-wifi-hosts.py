#!/usr/bin/env python3
"""Wi-Fi clients: names come from the router's host list; a device can be
renamed (known host, UTF-8 through a file) and its internet access switched."""

import json
import os
import shutil
import subprocess
import tempfile
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "components/console/scripts/vward-console-config.sh"
MAC = "60:3d:61:d0:12:88"

FAKE_NDMC = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path
st = Path("@STATE@"); s = json.loads(st.read_text()); cmd = sys.argv[2]
if cmd == "show running-config":
    lines = ['known host "%s" %s' % (n, m) for m, n in s["names"].items()] + ["ip hotspot"] + ["    host %s %s" % (m, a) for m, a in s["access"].items()] + ["!"]
    print("\n".join(lines)); sys.exit(0)
if cmd == "system configuration save": print("ok"); sys.exit(0)
if cmd.startswith("known host "):
    rest = cmd[len("known host "):]; name, mac = rest.rsplit(" ", 1); s["names"][mac] = name.strip('"')
elif cmd.startswith("ip hotspot host "):
    _, _, _, mac, a = cmd.split(); s["access"][mac] = a
else:
    print("Command::Base error: syntax"); sys.exit(0)
st.write_text(json.dumps(s)); print("ok")
'''


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    state = tmp / "state.json"; state.write_text(json.dumps({"names": {}, "access": {}}))
    ndmc = tmp / "ndmc"; ndmc.write_text(FAKE_NDMC.replace("@STATE@", str(state))); ndmc.chmod(0o755)
    (tmp / "root/tmp").mkdir(parents=True)
    env = os.environ | {"VWARD_NDMC": str(ndmc), "VWARD_ROUTE_CHANGE_LOCK": str(tmp / "lock"), "VWARD_ROUTE_STATE": str(tmp / "route"),
                        "VWARD_CONSOLE_ETC": str(tmp / "etc"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit"), "VWARD_ROOT_PREFIX": str(tmp / "root"),
                        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
                        "JQ": shutil.which("jq"), "VWARD_CONSOLE_CONFIG_BIN": str(HELPER), "VWARD_PROFILE_LIB": "/nonexistent",
                        "HTTP_X_VWARD_REQUEST": "console", "CONTENT_TYPE": "application/x-www-form-urlencoded"}

    def api(fields):
        body = urllib.parse.urlencode(fields)
        r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], input=body, text=True, capture_output=True,
                           env=env | {"REQUEST_METHOD": "POST", "QUERY_STRING": "action=wifi-host", "CONTENT_LENGTH": str(len(body.encode()))})
        return json.loads(r.stdout.split("\n\n", 1)[1])

    if api({"op": "name", "mac": MAC, "name": "Телефон Лены"}) != {"ok": True, "result": "changed"}:
        fail("rename")
    if json.loads(state.read_text())["names"].get(MAC) != "Телефон Лены":
        fail(f"name not written: {state.read_text()}")
    if api({"op": "name", "mac": MAC, "name": "Телефон Лены"}).get("result") != "unchanged":
        fail("the same name twice must be unchanged")
    for bad in ('a"b', "x\\y", ""):
        if api({"op": "name", "mac": MAC, "name": bad}).get("ok"):
            fail(f"name {bad!r} must be refused")
    if api({"op": "name", "mac": "zz:zz", "name": "x"}).get("error") != "invalid_mac":
        fail("a bad MAC must be refused")
    if api({"op": "access", "mac": MAC, "value": "deny"}).get("error") != "confirmation_required":
        fail("denying internet needs a confirmation")
    if api({"op": "access", "mac": MAC, "value": "deny", "confirm": "WIFI_ACCESS_DENY"}) != {"ok": True, "result": "changed"}:
        fail("deny")
    if api({"op": "access", "mac": MAC, "value": "permit"}) != {"ok": True, "result": "changed"} or json.loads(state.read_text())["access"][MAC] != "permit":
        fail("permit")
print("WIFI_HOSTS=PASS")
