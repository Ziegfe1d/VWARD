#!/usr/bin/env python3
"""One read of Keenetic's configuration serves the whole minute (01.11.2026, item 3).

Viva 1.11: ndm 38 % CPU on average (73 % peak), ~1730 Keenetic sessions 04:13-17:40 (about two a
minute), «show running-config» 7.7-14.5 s. The shared copy lived 20 s while the minute's agents start
seconds apart: each read again. Now 55 s; a write still drops the copy (vward_keenetic_dirty), and
an explicit age (the Panel's 60 s, a caller's own) is kept.
"""
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = (ROOT / "components/runtime/lib/vward-device-profile.sh").read_text()


def fail(msg):
    raise SystemExit(f"KEENETIC_SHARED_AGE=FAIL: {msg}")


def func(name):
    m = re.search(rf"^{name}\(\)\n\{{\n.*?^\}}\n", LIB, re.S | re.M)
    if not m:
        fail(f"missing {name}")
    return m.group(0)


dirty = re.search(r"^vward_keenetic_dirty\(\) \{.*\}$", LIB, re.M).group(0)
code = func("_vward_kc_fresh") + func("vward_keenetic_config") + dirty + "\n"
if "VWARD_ROUTING_CACHE_AGE:-${VWARD_KEENETIC_AGE:-55}" not in (ROOT / "components/runtime/lib/vward-routing-snapshot.sh").read_text():
    fail("the routing snapshot must use the same default age")
for shell in [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else []):
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "ndmc").write_text('#!/bin/sh\necho x >> "$T/reads"\necho "interface Wireguard0"\n')
        (t / "ndmc").chmod(0o755)
        base = f'T="{t}"; VWARD_KCACHE="$T/kc"; _VWARD_KCACHE_OWN=1; VWARD_NDMC="$T/ndmc"\n' \
               'vward_uptime_cs() { _VCS=0; }; vward_keenetic_timed() { :; }\n' + code

        def sh(body):
            r = subprocess.run([*shell, "-c", base + body], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "T": str(t)})
            if r.returncode != 0:
                fail(f"{shell}: {r.stderr}")
            return r.stdout

        def reads():
            return (t / "reads").read_text().count("x") if (t / "reads").exists() else 0

        sh("vward_keenetic_config >/dev/null")
        cache = t / "kc/running-config"
        old = time.time() - 40
        os.utime(cache, (old, old))
        sh("vward_keenetic_config >/dev/null")
        if reads() != 1:
            fail(f"RED: a copy 40 s old was read again ({reads()} reads): the minute's agents must share one")
        os.utime(cache, (time.time() - 70, time.time() - 70))
        sh("vward_keenetic_config >/dev/null")
        if reads() != 2:
            fail("a copy older than 55 s must be read again")
        sh("vward_keenetic_dirty; vward_keenetic_config >/dev/null")
        if reads() != 3:
            fail("a write must drop the copy at once")
        os.utime(cache, (time.time() - 30, time.time() - 30))
        sh("vward_keenetic_config 20 >/dev/null")
        if reads() != 4:
            fail("a caller's own shorter age must be kept")
print("KEENETIC_SHARED_AGE=PASS")
