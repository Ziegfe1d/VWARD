#!/usr/bin/env python3
"""Console API: Keenetic "show" answers are cached briefly, and dropped by any change.

A console page refreshes every 15 seconds; without a cache every refresh made
the router serialize its whole configuration (and every domain group with its
addresses).  The answer is kept a few seconds in a root-only RAM directory; any
POST drops it first, so a change is never followed by the old state.
"""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    running = tmp / "running"; running.write_text("object-group fqdn domain-list0\n    include t.me\n!\n")
    calls = tmp / "calls"
    addrs = tmp / "addrs"; addrs.write_text("3")
    ndmc = tmp / "ndmc"
    ndmc.write_text(f'#!/bin/sh\necho "$2" >> "{calls}"\n[ "$2" = "show running-config" ] && cat "{running}"\n'
                    f'[ "$2" = "show object-group fqdn" ] && printf "group-name: domain-list0\\nipv4-addresses-count: %s\\n    address: 1.2.3.4\\n" "$(cat {addrs})"\nexit 0\n')
    ndmc.chmod(0o755)
    cache = tmp / "cache"
    env = os.environ | {"JQ": shutil.which("jq"), "CURL": "/bin/false", "VWARD_PROFILE_LIB": "/nonexistent", "VWARD_NDMC": str(ndmc),
                        "VWARD_CONSOLE_CACHE_DIR": str(cache), "VWARD_CONSOLE_CACHE_TTL": "30",
                        "VWARD_DOMAIN_LISTS_CONF": str(tmp / "lists.conf"), "VWARD_CONSOLE_SESSIONS": str(tmp / "sessions")}

    def get(action):
        r = subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], env=env | {"REQUEST_METHOD": "GET", "QUERY_STRING": "action=" + action},
                           text=True, capture_output=True)
        return json.loads(r.stdout.split("\n\n", 1)[1])

    def count(cmd):
        return calls.read_text().splitlines().count(cmd) if calls.exists() else 0

    a = get("lists-data")
    b = get("lists-data")
    if a != b or a["lists"][0]["addresses"] != 3:
        fail(f"cached answer differs: {a} {b}")
    if count("show running-config") != 1 or count("show object-group fqdn") != 1:
        fail(f"the second refresh asked the router again: {calls.read_text()}")
    if "address" in (cache / "fqdn-counts").read_text():
        fail("only the per-list counts are kept, not every learned address")

    # Counts older than the TTL are shown at once and refreshed in the background.
    addrs.write_text("5")
    kept = (cache / "fqdn-counts").read_text().split("\n", 1)[1]
    (cache / "fqdn-counts").write_text(f"{int(time.time()) - 40}\n{kept}")
    if get("lists-data")["lists"][0]["addresses"] != 3:
        fail("stale counts must be answered without waiting for the router")
    for _ in range(50):
        if not (cache / "fqdn-counts.lock").exists() and "\t5" in (cache / "fqdn-counts").read_text():
            break
        time.sleep(0.1)
    if get("lists-data")["lists"][0]["addresses"] != 5 or count("show object-group fqdn") != 2:
        fail(f"the background refresh must bring the new count: {calls.read_text()}")
    mode = stat.S_IMODE((cache / "running").stat().st_mode)
    if mode & 0o077 or stat.S_IMODE(cache.stat().st_mode) & 0o077:
        fail(f"the cached configuration must be root-only: {oct(mode)}")

    # Any POST drops the cache: the next page shows the router as it is now.
    running.write_text("object-group fqdn domain-list0\n    include t.me\n    include telegram.org\n!\n")
    body = "op=logout"
    subprocess.run(["sh", str(ROOT / "web/cgi-bin/api.cgi")], input=body, text=True, capture_output=True,
                   env=env | {"REQUEST_METHOD": "POST", "QUERY_STRING": "action=auth", "CONTENT_LENGTH": str(len(body)),
                              "CONTENT_TYPE": "application/x-www-form-urlencoded", "HTTP_X_VWARD_REQUEST": "console"})
    if cache.exists():
        fail("a POST must drop the cache")
    if get("lists-data")["lists"][0]["count"] != 2 or count("show running-config") != 2:
        fail("after a change the router must be asked again")

    # With ndmc replaced and no TTL given (other tests), nothing is cached.
    env.pop("VWARD_CONSOLE_CACHE_TTL")
    get("lists-data"); get("lists-data")
    if count("show running-config") != 4:
        fail("the cache must be off by default when ndmc is replaced")

print("CONSOLE_NDM_CACHE=PASS")
