#!/usr/bin/env python3
"""Route engine: only names Keenetic accepts reach "object-group fqdn ... include".

A name Keenetic refuses answers "argument parse error"; at boot the AdaptiveAuto
restore sent every saved name in a row, so one bad kind of name made a burst of
router errors.  valid_fqdn guards both the live path and the restore, and the
restore logs the router's own words for the first failures.
"""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / "components/route-engine/scripts/vward-route-engine.sh").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


fn = ENGINE[ENGINE.index("valid_fqdn()\n"):ENGINE.index("\n}\n", ENGINE.index("valid_fqdn()\n")) + 3]
GOOD = ["claude.ai", "api.anthropic.com", "xn--80ak6aa92e.xn--p1ai", "a-b.c-d.example", "1.2.example", "x" * 60 + ".com"]
BAD = ["", "_dmarc.example.com", "-a.example", "a-.example", "a.-b.example", "a..example", ".example", "example.",
       "Claude.ai", "a b.example", "*.example.com", "a;reboot.example", "x" * 250 + ".com", "a/b.example", "a:1.example"]
shells = ["sh"] + (["busybox"] if shutil.which("busybox") else [])
for sh in shells:
    for name in GOOD + BAD:
        cmd = ([sh, "sh"] if sh == "busybox" else [sh]) + ["-c", fn + '\nvalid_fqdn "$1"', "x", name]
        ok = subprocess.run(cmd).returncode == 0
        if ok != (name in GOOD):
            fail(f"{sh}: valid_fqdn({name!r}) = {ok}")

host = ENGINE[ENGINE.index("handle_host()\n"):]
if host.index('valid_fqdn "$HOST" || return') > host.index("refresh_sets"):
    fail("the live path must drop invalid names before anything else")
restore = ENGINE[ENGINE.index("restore_adaptive_from_persist()\n"):ENGINE.index("# ADD TO VPN")]
if restore.index('valid_fqdn "$H"') > restore.index('OUT=$(ndmc -c "object-group fqdn $GROUP include $H"'):
    fail("the restore must check a name before sending it")
if "PERSIST_RESTORE_FAIL|$H|" not in restore or "skipped=$SKIPPED" not in restore:
    fail("the restore must log skipped names and the router's answer to failures")

print("ROUTE_ENGINE_NAMES=PASS")
