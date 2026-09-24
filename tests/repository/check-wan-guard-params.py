#!/usr/bin/env python3
"""Internet guard: limits set in VWARD replace the defaults only when they are in range."""

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = (ROOT / "components/wan-guard/scripts/vward-wan-guard.sh").read_text()
BLOCK = GUARD[GUARD.index("CONFIRM_FAILURES=3\n"):GUARD.index("wg_conf_apply\n", GUARD.index("wg_conf_apply()")) + len("wg_conf_apply\n")]
KEYS = ["CONFIRM_FAILURES", "RENEW_COOLDOWN", "BOUNCE_COOLDOWN", "MAX_RENEW_HOUR", "MAX_BOUNCE_HOUR", "MAX_BOUNCE_DAY"]


def run(conf):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "wan-guard.conf"
        if conf is not None:
            path.write_text(conf)
        script = f'VWARD_WAN_GUARD_CONF="{path}"\n' + BLOCK + 'echo ' + ' '.join('$' + k for k in KEYS) + '\n'
        out = subprocess.run(["sh", "-c", script], capture_output=True, text=True, check=True).stdout.split()
        return dict(zip(KEYS, map(int, out)))


defaults = {"CONFIRM_FAILURES": 3, "RENEW_COOLDOWN": 600, "BOUNCE_COOLDOWN": 1800, "MAX_RENEW_HOUR": 3, "MAX_BOUNCE_HOUR": 2, "MAX_BOUNCE_DAY": 6}
if run(None) != defaults:
    raise SystemExit(f"FAIL: defaults without a file: {run(None)}")
got = run("CONFIRM_FAILURES=5\nRENEW_COOLDOWN=10\nMAX_BOUNCE_DAY=abc\nMAX_BOUNCE_HOUR=4\nBOUNCE_COOLDOWN=900\r\nUNKNOWN=1\n")
if got != defaults | {"CONFIRM_FAILURES": 5, "MAX_BOUNCE_HOUR": 4}:
    raise SystemExit(f"FAIL: out-of-range or malformed values must keep the default: {got}")
print("WAN_GUARD_PARAMS=PASS")
