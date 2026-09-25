#!/usr/bin/env python3
"""The API's request guards and form parsing.

Only the names the router answers to reach the API (DNS rebinding); a refused
request changes nothing, the saved router answers included.  A control lock
whose owner is gone is taken over.  The shared form helpers read, check and
decode values the way every handler relies on.
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


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    auth = tmp / "auth.conf"
    cache = tmp / "cache"
    env = os.environ | {"JQ": shutil.which("jq"), "CURL": "/bin/false", "VWARD_PROFILE_LIB": "/nonexistent",
                        "VWARD_CONSOLE_AUTH_CONF": str(auth), "VWARD_CONSOLE_CACHE_DIR": str(cache),
                        "VWARD_CONSOLE_SESSIONS": str(tmp / "sessions"), "VWARD_CONSOLE_CONTROL_LOCK": str(tmp / "control.lock"),
                        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
                        "VWARD_ROOT_PREFIX": str(tmp / "root")}
    (tmp / "root/tmp").mkdir(parents=True)

    def call(host, action="ping", post=None):
        e = env | {"QUERY_STRING": "action=" + action, "REQUEST_METHOD": "GET"}
        if host is not None:
            e["HTTP_HOST"] = host
        body = ""
        if post is not None:
            body = urllib.parse.urlencode(post)
            e |= {"REQUEST_METHOD": "POST", "HTTP_X_VWARD_REQUEST": "console",
                  "CONTENT_TYPE": "application/x-www-form-urlencoded", "CONTENT_LENGTH": str(len(body))}
        r = subprocess.run(["sh", str(API)], input=body, env=e, text=True, capture_output=True)
        head, _, payload = r.stdout.partition("\n\n")
        return head.split("\n", 1)[0], json.loads(payload)

    def allowed(host):
        status, x = call(host)
        if x.get("error") == "host_not_allowed" and "403" not in status:
            fail("a refused host answers 403")
        return x.get("ok") is True

    for h in (None, "", "192.168.1.1", "192.168.1.1:8088", "[fe80::1]:8088", "[::1]", "localhost:8088", "keenetic",
              "Keenetic-4521", "router.lan", "vward.local", "nas.home.arpa", "my.keenetic.net", "abc.keenetic.pro:443",
              "ROUTER.LAN", "router.lan."):
        if not allowed(h):
            fail(f"{h!r} must reach the API")
    for h in ("evil.example.com", "Evil.Example.COM:8088", "1.2.3.4.nip.io", "192.168.1.1.attacker.net",
              "localhost.attacker.net", "a b", "x\"y"):
        if allowed(h):
            fail(f"{h!r} must be refused")

    # Names the owner adds, with or without quotes; the check can be turned off.
    auth.write_text('ALLOWED_HOSTS="vward.example.org router.example.net"\n')
    if not allowed("vward.example.org:8088") or not allowed("router.example.net") or allowed("other.example.org"):
        fail("ALLOWED_HOSTS lists extra names")
    auth.write_text("ALLOWED_HOSTS=vward.example.org\n")
    if not allowed("vward.example.org"):
        fail("ALLOWED_HOSTS without quotes")
    auth.write_text("HOST_CHECK=0\n")
    if not allowed("evil.example.com"):
        fail("HOST_CHECK=0 turns the check off")
    auth.write_text("")

    # A refused request changes nothing: the saved router answers stay.
    cache.mkdir(); (cache / "running").write_text("0\nx\n")
    call("evil.example.com", "settings", {"auto_apply": "1"})
    r = subprocess.run(["sh", str(API)], input="op=x", text=True, capture_output=True,
                       env=env | {"QUERY_STRING": "action=control", "REQUEST_METHOD": "POST", "HTTP_HOST": "192.168.1.1",
                                  "CONTENT_TYPE": "application/x-www-form-urlencoded", "CONTENT_LENGTH": "4"})
    if "request_guard_failed" not in r.stdout or not (cache / "running").exists():
        fail("requests refused by a guard must not touch the cache")
    call("192.168.1.1", "control", {"op": "no-such-action"})
    if cache.exists():
        fail("an accepted change drops the saved router answers")

    # Control lock: a live owner blocks, a gone one is taken over.
    lock = tmp / "control.lock"
    def control():
        return call("192.168.1.1", "control", {"op": "housekeeping"})[1].get("error")
    lock.mkdir(); (lock / "pid").write_text(str(os.getpid()))
    if control() != "control_busy":
        fail("a running control action blocks another")
    dead = subprocess.Popen(["true"]); dead.wait()
    (lock / "pid").write_text(str(dead.pid))
    if control() == "control_busy" or lock.exists():
        fail("a lock whose owner is gone must be taken over and released")
    lock.mkdir()
    if control() != "control_busy":
        fail("a fresh lock without its owner yet still blocks")
    old = time.time() - 300
    os.utime(lock, (old, old))
    if control() == "control_busy":
        fail("an old lock without an owner is taken over")

    # Form helpers, straight from api.cgi.
    src = API.read_text()
    helpers = src[src.index("# ---------- Request body"):src.index("# secret_path PATH")]
    def sh(body, script):
        r = subprocess.run(["sh", "-c", helpers + "\nBODY=$1\n" + script, "sh", body], capture_output=True)
        return r.returncode, r.stdout
    cases = [
        ("op=a&name=b", 'form_value name', b"b\n"),
        ("op=a&xop=b", 'form_value op', b"a\n"),
        ("xop=b&op=a", 'form_value op', b"a\n"),
        ("op=a", 'form_value missing', b""),
        ("op=a=b&c=d", 'form_value op', b"a=b\n"),
        ("op=1&op=2", 'form_value op', b"1\n"),
        ("conf=%5BPeer%5D%0AKey+%3D+x%09y%0D%0A", 'form_decode conf text', b"[Peer]\nKey = x\ty\r\n"),
        ("name=%D0%9A%D1%83%D1%85%D0%BD%D1%8F+TV", 'form_decode name name', "Кухня TV".encode()),
        ("u=https%3A%2F%2Fa.example%2Fl%2Bx.txt", 'form_decode u url', b"https://a.example/l+x.txt"),
        ("p=a%20b%21", 'form_decode p ascii', b"a b!"),
        ("p=%FF%01x", "form_decode p raw", b"\xff\x01x"),
    ]
    for body, script, want in cases:
        rc, out = sh(body, script)
        if rc != 0 or out != want:
            fail(f"{script} on {body!r}: rc={rc} {out!r} != {want!r}")
    for body, script in (("n=a%22b", "form_decode n name"), ("n=a%5Cb", "form_decode n name"), ("n=a%0Ab", "form_decode n name"),
                         ("c=a%00b", "form_decode c text"), ("c=%80", "form_decode c text"), ("u=a%20b", "form_decode u url"),
                         ("p=%7F", "form_decode p ascii")):
        if sh(body, script)[0] == 0:
            fail(f"{script} must refuse {body!r}")
    for body, keys, ok in (("op=a&confirm=b", "op confirm", True), ("op=a&extra=1", "op confirm", False),
                           ("op=a&&confirm=b", "op confirm", True), ("", "op", True), ("=x", "op", True)):
        if (sh(body, "form_only " + keys)[0] == 0) != ok:
            fail(f"form_only {keys} on {body!r} must be {ok}")

print("CONSOLE_REQUEST=PASS")
