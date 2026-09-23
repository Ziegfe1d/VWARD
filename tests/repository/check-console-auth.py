#!/usr/bin/env python3
"""Console login with the Keenetic account: challenge-response, sessions, lockout."""

import hashlib
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
LOGIN, PASSWORD = "admin", "p@ss wörd&=%+1"
REALM, CHALLENGE = "Keenetic Test", "QZ8ABC123"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


expected = hashlib.sha256((CHALLENGE + hashlib.md5(f"{LOGIN}:{REALM}:{PASSWORD}".encode()).hexdigest()).encode()).hexdigest()

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / "root/tmp").mkdir(parents=True)
    etc = tmp / "etc"; (etc / "console").mkdir(parents=True)
    curl = tmp / "curl"
    # Fake router /auth: GET -> 401 with realm/challenge and a session cookie;
    # POST with the same cookie and the right hash -> 200.
    curl.write_text(f"""#!/bin/sh
echo "$*" >> "{tmp}/curl-args"
hdr=""; jar_in=""; jar_out=""; data=""
while [ "$#" -gt 0 ]; do case "$1" in
  -D) hdr="$2"; shift 2 ;; -b) jar_in="$2"; shift 2 ;; -c) jar_out="$2"; shift 2 ;;
  --data-binary) data="${{2#@}}"; shift 2 ;; -o|-H|-w|--connect-timeout|--max-time) shift 2 ;; *) shift ;; esac; done
if [ -z "$data" ]; then
  printf 'HTTP/1.1 401 Unauthorized\\r\\nX-NDM-Realm: {REALM}\\r\\nX-NDM-Challenge: {CHALLENGE}\\r\\n\\r\\n' > "$hdr"
  echo "session=s1" > "$jar_out"; printf 401; exit 0
fi
grep -q "session=s1" "$jar_in" 2>/dev/null || {{ printf 401; exit 0; }}
cat "$data" >> "{tmp}/posted"
if grep -q '"login":"{LOGIN}","password":"{expected}"' "$data"; then printf 200; else printf 401; fi
""")
    curl.chmod(0o755)
    env0 = os.environ | {
        "JQ": shutil.which("jq"), "CURL": str(curl), "VWARD_PROFILE_LIB": "/nonexistent",
        "VWARD_CONSOLE_AUTH_CONF": str(etc / "console/auth.conf"), "VWARD_CONSOLE_SESSIONS": str(tmp / "sessions"),
        "VWARD_KEENETIC_AUTH_URL": "http://router.test/auth", "VWARD_CONSOLE_ETC": str(etc),
        "VWARD_CONSOLE_CONFIG_BIN": str(ROOT / "components/console/scripts/vward-console-config.sh"),
        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
        "VWARD_ROOT_PREFIX": str(tmp / "root"), "VWARD_CONSOLE_AUDIT_LOG": str(tmp / "audit.log"),
        "VWARD_CONSOLE_BACKUP_DIR": str(tmp / "backup"),
    }

    def call(query, body=None, cookie=""):
        env = env0 | {"REQUEST_METHOD": "POST" if body is not None else "GET", "QUERY_STRING": query,
                      "CONTENT_TYPE": "application/x-www-form-urlencoded", "CONTENT_LENGTH": str(len((body or "").encode())),
                      "HTTP_X_VWARD_REQUEST": "console", "HTTP_COOKIE": cookie}
        r = subprocess.run(["sh", str(API)], input=body or "", env=env, capture_output=True, text=True)
        head, _, payload = r.stdout.partition("\n\n")
        return head, json.loads(payload)

    def form(**kw):
        return urllib.parse.urlencode(kw)

    def cookie_of(head):
        line = next((l for l in head.splitlines() if l.startswith("Set-Cookie: vward_session=")), "")
        return line.split(": ", 1)[1].split(";", 1)[0] if line else ""

    # Off by default: everything open, nothing stored.
    if call("action=auth")[1] != {"ok": True, "enabled": False, "logged_in": False, "login": "", "session_hours": 12}:
        fail("login must be off by default")
    if call("action=status")[1].get("ok") is not True:
        fail("API must stay open while login is off")

    # Enabling needs working router credentials, so a typo cannot lock anyone out.
    if call("action=auth", form(op="enable", login=LOGIN, password="wrong"))[1].get("error") != "wrong_credentials":
        fail("wrong password must be refused")
    if (etc / "console/auth.conf").exists():
        fail("a refused enable must not change the configuration")
    head, res = call("action=auth", form(op="enable", login=LOGIN, password=PASSWORD))
    cookie = cookie_of(head)
    if not res.get("ok") or not cookie or "HttpOnly" not in head or "SameSite=Strict" not in head:
        fail(f"enable with the right password: {res} {head!r}")
    if "AUTH_ENABLED=1" not in (etc / "console/auth.conf").read_text():
        fail("enable must switch the setting on")

    # Closed without a session; ping stays open for the updater health check.
    head, res = call("action=status")
    if res.get("error") != "auth_required" or "401" not in head:
        fail("API must require a session once login is on")
    if call("action=ping")[1].get("ok") is not True:
        fail("ping must stay open")
    if call("action=status", cookie=cookie)[1].get("ok") is not True:
        fail("a valid session must open the API")
    if call("action=auth", cookie=cookie)[1] != {"ok": True, "enabled": True, "logged_in": True, "login": LOGIN, "session_hours": 12}:
        fail("auth state with a session")
    for bad in ("vward_session=" + "0" * 64, "vward_session=../../etc", "vward_session=" + cookie.split("=")[1].upper()):
        if call("action=status", cookie=bad)[1].get("error") != "auth_required":
            fail(f"forged session accepted: {bad}")

    # Nothing secret on disk or in process arguments.
    stored = "".join(p.read_text(errors="ignore") for p in (tmp / "sessions").glob("*") if p.is_file())
    token = cookie.split("=", 1)[1]
    for secret in (PASSWORD, token, "wörd"):
        if secret in stored or secret in (tmp / "curl-args").read_text() or secret in (tmp / "posted").read_text():
            fail(f"secret leaked: {secret!r}")

    # Expired sessions are refused.
    sid = next(p for p in (tmp / "sessions").glob("*") if p.is_file() and not p.name.startswith("."))
    sid.write_text(f"login={LOGIN}\nexpires={int(time.time()) - 1}\n")
    if call("action=status", cookie=cookie)[1].get("error") != "auth_required":
        fail("expired session accepted")

    # Brute force: five failures lock the form for five minutes.
    for _ in range(5):
        call("action=auth", form(op="login", login=LOGIN, password="bad"))
    if call("action=auth", form(op="login", login=LOGIN, password=PASSWORD))[1].get("error") != "too_many_attempts":
        fail("login attempts are not rate limited")
    (tmp / "sessions/.failures").write_text("")
    head, res = call("action=auth", form(op="login", login=LOGIN, password=PASSWORD))
    cookie = cookie_of(head)
    if not res.get("ok"):
        fail("login after the lock expired")
    if call("action=auth", form(op="login", login="a b", password="x"))[1].get("error") != "invalid_login":
        fail("login name must be validated")

    # Disabling needs the session and a confirmation; logout ends the session.
    if call("action=auth", form(op="disable"))[1].get("error") != "auth_required":
        fail("disable without a session")
    if call("action=auth", form(op="disable"), cookie=cookie)[1].get("error") != "confirmation_required":
        fail("disable without confirmation")
    call("action=auth", form(op="logout"), cookie=cookie)
    if call("action=status", cookie=cookie)[1].get("error") != "auth_required":
        fail("logout must end the session")
    head, res = call("action=auth", form(op="login", login=LOGIN, password=PASSWORD))
    cookie = cookie_of(head)
    if call("action=auth", form(op="disable", confirm="CONSOLE_AUTH_DISABLE"), cookie=cookie)[1].get("ok") is not True:
        fail("confirmed disable")
    if call("action=status")[1].get("ok") is not True:
        fail("API must open again after login is switched off")

    # Router /auth unreachable: clear error, no lockout counted.
    env0["CURL"] = "/bin/false"
    if call("action=auth", form(op="login", login=LOGIN, password=PASSWORD))[1].get("error") != "router_auth_unavailable":
        fail("unreachable router auth must be reported")
    if "login_failed" in (tmp / "audit.log").read_text() and (tmp / "sessions/.failures").read_text().strip():
        fail("an unreachable router must not count as a failed login")

print("CONSOLE_AUTH=PASS")
