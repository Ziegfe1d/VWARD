#!/usr/bin/env python3
"""A confirmed «Установить» from VWARD installs now; the scheduled window only
holds automatic installs."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "components/update-engine/vward-update-common-base.sh"
API = (ROOT / "web/cgi-bin/api.cgi").read_text()


def ready(manual):
    script = (f'. "{BASE}" >/dev/null 2>&1; safe_window_start=03:00; safe_window_end=04:00; apply_window=window; '
              f'routine_max_delay_seconds=86400; VWARD_TEST_NOW_HM=12:00; VWARD_TEST_NOW_EPOCH=1000; VU_PENDING_DIR=/nonexistent; '
              f'VWARD_UPDATE_MANUAL={manual}; vu_schedule_ready ROUTINE 1000')
    return subprocess.run(["sh", "-c", script]).returncode == 0


if ready(0):
    raise SystemExit("FAIL: an automatic ROUTINE update outside the window must wait")
if not ready(1):
    raise SystemExit("FAIL: a manual install from VWARD must not wait for the window")
if "case \"$LABEL\" in update-apply|update-retry) VWARD_UPDATE_MANUAL=1" not in API:
    raise SystemExit("FAIL: the Console must mark its installs as manual")
print("UPDATE_MANUAL_INSTALL=PASS")
