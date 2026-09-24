#!/usr/bin/env python3
"""Console: AdGuard Home login is checked against AdGuard Home before it is kept,
stored root-only, never passed in argv, and removed only with a confirmation."""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    auth = tmp / "etc/agh-api.auth"
    # curl stand-in: reads "user = ..." from stdin (-K -), answers 200 only for admin:s3cr"et\x.
    curl = tmp / "curl"
    curl.write_text(f'''#!/bin/sh
echo "$*" >> "{tmp}/curl.argv"
conf=$(cat)
case "$conf" in 'user = "admin:s3cr\\"et\\\\x"') printf 200 ;; *) printf 401 ;; esac
''')
    curl.chmod(0o755)
    env = os.environ | {"JQ": shutil.which("jq"), "CURL": str(curl), "VWARD_PROFILE_LIB": "/nonexistent",
                        "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_ADS_AGH_AUTH_FILE": str(auth),
                        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
                        "VWARD_ADGUARD_ADDRESS": "192.0.2.1", "VWARD_ADGUARD_PORT": "3001",
                        "HTTP_X_VWARD_REQUEST": "console", "CONTENT_TYPE": "application/x-www-form-urlencoded"}
    (tmp / "root/tmp").mkdir(parents=True)

    def post(fields):
        body = urllib.parse.urlencode(fields)
        r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], input=body, text=True, capture_output=True,
                           env=env | {"REQUEST_METHOD": "POST", "QUERY_STRING": "action=agh-auth", "CONTENT_LENGTH": str(len(body))})
        if r.returncode != 0:
            fail(f"rc={r.returncode} {r.stderr}")
        return json.loads(r.stdout.split("\n\n", 1)[1])

    if post({"op": "connect", "login": "admin", "password": "wrong"}) != {"ok": False, "error": "wrong_credentials"} or auth.exists():
        fail("a login AdGuard Home rejects must not be kept")
    if post({"op": "connect", "login": "ad min", "password": "x"}).get("error") != "invalid_login":
        fail("login characters are checked")
    got = post({"op": "connect", "login": "admin", "password": 's3cr"et\\x'})
    if got != {"ok": True, "connected": True}:
        fail(f"a login AdGuard Home accepts is kept: {got}")
    if auth.read_text() != 'admin:s3cr"et\\x\n' or stat.S_IMODE(auth.stat().st_mode) != 0o600:
        fail(f"auth file content or mode: {auth.read_text()!r} {oct(auth.stat().st_mode)}")
    if "s3cr" in (tmp / "curl.argv").read_text():
        fail("the password reached curl's argv")
    if "http://192.0.2.1:3001/control/status" not in (tmp / "curl.argv").read_text():
        fail("AdGuard Home address from the profile is not used")
    if post({"op": "disconnect"}).get("error") != "confirmation_required" or not auth.exists():
        fail("disconnect needs a confirmation")
    if post({"op": "disconnect", "confirm": "AGH_DISCONNECT"}) != {"ok": True, "connected": False} or auth.exists():
        fail("confirmed disconnect removes the login")

print("CONSOLE_AGH_AUTH=PASS")
