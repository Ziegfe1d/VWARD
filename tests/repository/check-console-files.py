#!/usr/bin/env python3
"""Files page: VWARD's own folders, read only, secrets closed.

The API lists and reads only the four VWARD folders.  Tunnel configurations,
keys, logins and every file only root may read are listed as closed and are
never returned or downloaded; paths leaving a folder and links are refused.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "web/cgi-bin/api.cgi"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    etc = tmp / "opt/etc/vward"
    (etc / "tunnels/Wireguard1").mkdir(parents=True)
    (etc / "tunnels/Wireguard1/tunnel.conf").write_text("PrivateKey = SECRET-TUNNEL\n")
    (etc / "ads-privacy-guard").mkdir()
    auth = etc / "ads-privacy-guard/agh-api.auth"; auth.write_text("admin:SECRET-AGH\n"); auth.chmod(0o644)
    closed = etc / "device.conf"; closed.write_text("VWARD_LAN_ADDRESS=1\n"); closed.chmod(0o600)
    (etc / "update.conf").write_text("channel=dev\n"); (etc / "update.conf").chmod(0o644)
    (etc / "link.conf").symlink_to(closed)
    logs = tmp / "opt/var/log/vward"; logs.mkdir(parents=True)
    (logs / "big.log").write_text("".join(f"line {i}\n" for i in range(20000)))
    (logs / "old.log.gz").write_bytes(b"\x1f\x8b\x08\x00" + b"\x00" * 64)
    for p in [logs / "big.log", logs / "old.log.gz"]:
        p.chmod(0o644)

    env = os.environ | {"REQUEST_METHOD": "GET", "JQ": shutil.which("jq"), "VWARD_ROOT_PREFIX": str(tmp),
                        "VWARD_PROFILE_LIB": "/nonexistent", "CURL": "/bin/false"}

    def call(query, raw=False):
        r = subprocess.run(["sh", str(API)], env=env | {"QUERY_STRING": "action=files&" + query}, capture_output=True)
        head, _, body = r.stdout.partition(b"\n\n")
        return (head.decode(), body) if raw else json.loads(body)

    x = call("op=list&root=etc")
    names = {e["name"]: e for e in x.get("entries", [])}
    if not x.get("ok") or set(names) != {"tunnels", "ads-privacy-guard", "device.conf", "update.conf"}:
        fail(f"etc listing (links are left out): {x}")
    if not names["device.conf"]["closed"] or names["update.conf"]["closed"] or names["tunnels"]["kind"] != "dir":
        fail(f"closed marks: {names}")
    if [e["name"] for e in x["entries"]][:2] != ["ads-privacy-guard", "tunnels"]:
        fail("folders come first")
    if not call("op=list&root=etc&path=ads-privacy-guard")["entries"][0]["closed"]:
        fail("a login file must be closed")

    for q in ["op=list&root=etc&path=tunnels", "op=read&root=etc&path=tunnels%2FWireguard1%2Ftunnel.conf",
              "op=read&root=etc&path=ads-privacy-guard%2Fagh-api.auth", "op=read&root=etc&path=device.conf",
              "op=download&root=etc&path=device.conf"]:
        if call(q).get("error") != "file_closed":
            fail(f"{q} must be closed")
    for q in ["op=read&root=etc&path=..%2F..%2Fetc%2Fpasswd", "op=read&root=etc&path=%2E%2E/x", "op=read&root=etc&path=a/../update.conf",
              "op=list&root=/opt&path=", "op=read&root=etc&path=link.conf", "op=read&root=etc&path=%2Fetc%2Fpasswd"]:
        r = call(q)
        if r.get("ok") or "SECRET" in json.dumps(r):
            fail(f"{q} must be refused: {r}")

    r = call("op=read&root=etc&path=update.conf")
    if r.get("text") != "channel=dev\n" or r.get("truncated"):
        fail(f"read: {r}")
    r = call("op=read&root=logs&path=big.log")
    if not (r["truncated"] and r["from_end"] and r["text"].endswith("line 19999\n") and len(r["text"]) <= 65536):
        fail("a long log is read from its end")
    if not call("op=read&root=logs&path=old.log.gz").get("binary"):
        fail("a compressed file is not shown as text")
    head, body = call("op=download&root=etc&path=update.conf", raw=True)
    if body != b"channel=dev\n" or 'filename="update.conf"' not in head:
        fail(f"download: {head} {body!r}")

print("CONSOLE_FILES=PASS")
