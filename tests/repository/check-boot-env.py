#!/usr/bin/env python3
"""Keenetic can start Entware's scripts with a library path of its own; Entware's curl then
crashes in the loader (seen on a router right after boot). Every VWARD script loads the device
profile, which drops that path."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
lib = ROOT / "components/runtime/lib/vward-device-profile.sh"
r = subprocess.run(["sh", "-c", f'. "{lib}"; printf "%s" "${{LD_LIBRARY_PATH-unset}}"'],
                   env=os.environ | {"LD_LIBRARY_PATH": "/lib:/usr/lib"}, text=True, capture_output=True, timeout=20)
if r.returncode != 0 or r.stdout != "unset":
    raise SystemExit(f"BOOT_ENV=FAIL: the library path stays after the profile: {r.stdout!r} {r.stderr}")
print("BOOT_ENV=PASS")
