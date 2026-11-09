#!/usr/bin/env python3
"""Panel pages open at once (owner 08.11): Keenetic's configuration older than its TTL but younger
than CONFIG_STALE is answered from the shared copy at once, and one background refresh renews it;
a POST, a missing copy or a too old one read fresh (and wait). Runs api.cgi's ndm_cached with
stand-ins for the shared-cache functions of the device profile."""

import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = (ROOT / "web/cgi-bin/api.cgi").read_text()
m = re.search(r"^ndm_cached\(\)\n\{\n.*?^\}\n", API, re.S | re.M)
SHELLS = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])


def fail(message: str) -> None:
    raise SystemExit(f"PANEL_STALE_CONFIG=FAIL: {message}")


if not m:
    fail("ndm_cached not found")
FN = m.group(0)

for sh in SHELLS:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        kc = t / "kc"; kc.mkdir()
        stub = f'''VWARD_KCACHE="{kc}"; NDM_CACHE_DIR="{t}/nc"
_vward_kc_fresh() {{ [ -s "$VWARD_KCACHE/running-config" ] || return 1; a=$(( $(date +%s) - $(date -r "$VWARD_KCACHE/running-config" +%s) )); [ "$a" -lt "$1" ]; }}
vward_keenetic_config() {{ echo "read $1" >> "{t}/reads"; sleep "${{SLOW:-0}}"; printf 'fresh\\n' > "$VWARD_KCACHE/running-config"; cat "$VWARD_KCACHE/running-config"; }}
'''
        def run(method="GET", age=None, slow=0):
            cfg = kc / "running-config"
            if age is None:
                cfg.unlink(missing_ok=True)
            else:
                cfg.write_text("old\n")
                past = time.time() - age
                import os
                os.utime(cfg, (past, past))
            (t / "reads").unlink(missing_ok=True)
            t0 = time.time()
            r = subprocess.run(sh + ["-c", stub + FN + 'ndm_cached running 60 "show running-config"'],
                               env={"PATH": "/usr/bin:/bin", "REQUEST_METHOD": method, "SLOW": str(slow)}, text=True, capture_output=True, timeout=30)
            took = time.time() - t0
            time.sleep(0.6)  # the background refresh
            reads = (t / "reads").read_text().splitlines() if (t / "reads").exists() else []
            return r.stdout, reads, took

        out, reads, took = run(age=7200, slow=2)
        if out != "old\n" or took > 1.5:
            fail(f"{sh} a 2-hour-old copy (Panel opened after a pause) must be answered at once: {out!r} in {took:.1f} s")
        time.sleep(2)
        reads = (t / "reads").read_text().splitlines() if (t / "reads").exists() else []
        if reads != ["read 60"] or (kc / "running-config").read_text() != "fresh\n":
            fail(f"{sh} one background refresh renews it: {reads}")
        if (t / "nc/running-refresh.lock").exists():
            fail("the refresh lock goes with the refresh")
        for label, kw in (("POST", {"method": "POST", "age": 120}), ("no copy", {}), ("25 hours old", {"age": 90000})):
            out, reads, _ = run(**kw)
            if out != "fresh\n" or reads != ["read 60"]:
                fail(f"{sh} {label}: a fresh read, waited for: {out!r} {reads}")
        out, reads, _ = run(age=10)
        if out != "fresh\n":  # the stand-in always reads; the real one answers a young copy itself
            fail(f"{sh} a young copy goes to the shared cache: {out!r}")
print("PANEL_STALE_CONFIG=PASS")
