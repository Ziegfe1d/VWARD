#!/usr/bin/env python3
"""Ads: once AdGuard Home is connected, the scheduler creates the settings file
with the documented defaults (root-only) instead of staying "not configured"."""

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "components/ads-privacy-guard/lib/vward-ads-privacy-common.sh"
EXAMPLE = ROOT / "config/ads-privacy-guard/ads-privacy-guard.conf.example"


def keys(text):
    return {l.split("=", 1)[0]: l.split("=", 1)[1] for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#") and "=" in l}


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    env = os.environ | {"VWARD_ADS_ETC": str(tmp / "etc"), "VWARD_ADS_STATE": str(tmp / "state"), "VWARD_ADS_LOG_DIR": str(tmp / "log")}
    r = subprocess.run(["sh", "-c", f'. "{LIB}"; ads_write_default_config && ads_write_default_config'], env=env, capture_output=True, text=True)
    conf = tmp / "etc/ads-privacy-guard.conf"
    if r.returncode != 0 or not conf.exists():
        raise SystemExit(f"FAIL: default config not written: {r.stderr}")
    if oct(conf.stat().st_mode & 0o777) != "0o600":
        raise SystemExit("FAIL: the Ads config must be root-only")
    if keys(conf.read_text()) != keys(EXAMPLE.read_text()):
        raise SystemExit("FAIL: built-in defaults differ from ads-privacy-guard.conf.example")
    if subprocess.run(["sh", "-n", str(conf)]).returncode != 0:
        raise SystemExit("FAIL: default config is not valid shell")
sched = (ROOT / "components/ads-privacy-guard/scripts/vward-ads-privacy-scheduler.sh").read_text()
if '[ -s "$ADS_AGH_AUTH_FILE" ] && ads_write_default_config' not in sched:
    raise SystemExit("FAIL: the scheduler must start Ads only once AdGuard Home is connected")
print("ADS_DEFAULT_CONFIG=PASS")
