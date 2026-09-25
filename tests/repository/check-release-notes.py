#!/usr/bin/env python3
"""«Что нового»: release notes of the installed version and of an update on offer.

A CHANGELOG on the router is read first when present; otherwise the CHANGELOG
next to the update feed (the branch the manifest URL names; it holds every
version) is fetched and kept an hour.  Only a raw.githubusercontent.com feed is used.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


CHANGELOG = """# Changelog

## 0.2.0-rc.1.fix.12: исправление RC1

Консоль
- «Что нового» у версии.
  Вторая строка пункта.

## 0.2.0-rc.1.fix.11: исправление RC1

- Smart DNS в AdGuard Home.

## 0.2.0-rc.1.fix.1

- Первое исправление.
"""

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    root = tmp / "root"
    (root / "opt/share/vward").mkdir(parents=True)
    (root / "opt/etc/vward").mkdir(parents=True)
    local = CHANGELOG.split("## 0.2.0-rc.1.fix.12")[0] + "## 0.2.0-rc.1.fix.11" + CHANGELOG.split("## 0.2.0-rc.1.fix.11", 1)[1]
    (root / "opt/share/vward/CHANGELOG.md").write_text(local)
    (root / "opt/etc/vward/update.conf").write_text("manifest_url=https://raw.githubusercontent.com/Ziegfe1d/VWARD/dev/updates/dev/update-manifest.json\n")
    remote = tmp / "remote.md"; remote.write_text(CHANGELOG)
    log = tmp / "curl.log"
    curl = tmp / "curl"
    curl.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nout=""; while [ $# -gt 0 ]; do case "$1" in -o) out=$2; shift ;; esac; shift; done\ncp "{remote}" "$out"\n')
    curl.chmod(0o755)
    env = os.environ | {"REQUEST_METHOD": "GET", "JQ": shutil.which("jq"), "CURL": str(curl), "VWARD_PROFILE_LIB": "/nonexistent",
                        "VWARD_ROOT_PREFIX": str(root), "VWARD_CONSOLE_CACHE_DIR": str(tmp / "cache")}

    def notes(v):
        r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=env | {"QUERY_STRING": "action=release-notes&version=" + v},
                           text=True, capture_output=True)
        return json.loads(r.stdout.split("\n\n", 1)[1])

    x = notes("0.2.0-rc.1.fix.11")
    if x.get("source") != "installed" or x["text"].strip() != "#title исправление RC1\n\n- Smart DNS в AdGuard Home.":
        fail(f"installed notes: {x}")
    if log.exists():
        fail("the installed version must not go to the network")
    x = notes("0.2.0-rc.1.fix.12")
    if x.get("source") != "feed" or "«Что нового» у версии.\n  Вторая строка пункта." not in x["text"] or "fix.11" in x["text"]:
        fail(f"feed notes: {x}")
    if "https://raw.githubusercontent.com/Ziegfe1d/VWARD/dev/CHANGELOG.md" not in log.read_text():
        fail(f"the CHANGELOG must come from the feed branch: {log.read_text()}")
    x = notes("0.2.0-rc.1.fix.1")
    if "Первое исправление" not in x.get("text", "") or "fix.12" in x["text"]:
        fail(f"a version that prefixes others: {x}")
    for bad in ("1;reboot", "a%20b", ""):
        if notes(bad).get("error") != "invalid_version":
            fail(f"bad version {bad!r} accepted")
    if notes("9.9.9").get("error") != "notes_unavailable":
        fail("an unknown version has no notes")
    (root / "opt/etc/vward/update.conf").write_text("manifest_url=https://evil.example/x/updates/dev/update-manifest.json\n")
    (tmp / "cache/changelog").unlink()
    if notes("0.2.0-rc.1.fix.12").get("error") != "notes_unavailable":
        fail("only a raw.githubusercontent.com feed is fetched")

print("RELEASE_NOTES=PASS")
