#!/usr/bin/env python3
"""Housekeeping repairs an Entware program that crashes on a plain local task (a damaged copy,
Viva 2026-10-11): it reinstalls the package, at most once in 6 hours, and logs it. A program that
only fails (no crash) or does not exist is left alone. curl that crashed on HTTPS (libnghttp2,
Viva 2026-10-12) gets its HTTP/2 library reinstalled too."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "components/runtime/scripts/vward-housekeeping.sh"


def fail(message: str) -> None:
    raise SystemExit(f"PROGRAM_REPAIR=FAIL: {message}")


busybox = shutil.which("busybox")
if not busybox:
    fail("busybox is needed")
with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    r = t / "root"
    for d in ("opt/var/log/vward", "opt/var/backups/vward", "tmp", "opt/var/spool/cron/crontabs"):
        (r / d).mkdir(parents=True)
    # curl crashes until opkg reinstalls it; jq fails without crashing; no openssl at all.
    (t / "curl").write_text(f'#!/bin/sh\necho run >> "{t}/curl.runs"\n[ -e "{t}/fixed" ] && exit 0\nkill -SEGV $$\n')
    (t / "jq").write_text("#!/bin/sh\nexit 5\n")
    (t / "opkg").write_text(f'#!/bin/sh\necho "$*" >> "{t}/opkg.log"\n: > "{t}/fixed"\n')
    for f in ("curl", "jq", "opkg"):
        (t / f).chmod(0o755)
    stub = t / "admission.sh"
    stub.write_text("vward_admission_enter() { :; }\nvward_admission_leave() { :; }\nvward_defer() { return 1; }\nvward_off() { return 0; }\n")
    env = os.environ | {"VWARD_ROOT_PREFIX": str(r), "VWARD_ADMISSION_LIB": str(stub), "VWARD_CONSOLE_CONFIG_BIN": str(t / "none"),
                        "VWARD_CRONTAB": str(t / "none"), "VWARD_OPKG_BIN": str(t / "opkg"), "VWARD_REPAIR_CURL": str(t / "curl"),
                        "VWARD_REPAIR_JQ": str(t / "jq"), "VWARD_REPAIR_OPENSSL": str(t / "no-openssl"), "VWARD_SENTINEL_CTL": str(t / "none"),
                        "VWARD_TLS_BROKEN_FLAG": str(t / "tls.broken"), "VWARD_REPAIR_HTTPS_URL": "https://example.invalid/"}

    def run() -> str:
        res = subprocess.run([busybox, "sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            fail(f"housekeeping failed: {res.stderr[-300:]}")
        log = r / "opt/var/log/vward-housekeeping.log"
        return log.read_text() if log.exists() else ""

    log = run()
    opkg = (t / "opkg.log").read_text().splitlines() if (t / "opkg.log").exists() else []
    if opkg != ["install --force-reinstall curl"]:
        fail(f"only the crashing curl is reinstalled: {opkg}")
    if "repair=curl|crash=139|reinstalled=curl|opkg=0|after=0" not in log:
        fail(f"the repair and its outcome are logged: {log}")
    # Crashes again within 6 hours: logged, not reinstalled again.
    (t / "fixed").unlink()
    log = run()
    if len((t / "opkg.log").read_text().splitlines()) != 1 or "repair=curl|crash=139|next_try_later" not in log:
        fail("a second reinstall within 6 hours")
    # A curl that works is not touched (two tries each run at most).
    (t / "fixed").write_text("")
    (r / "opt/var/lib/vward/repair/curl").write_text("0\n")
    runs = len((t / "curl.runs").read_text().splitlines())
    run()
    if len((t / "opkg.log").read_text().splitlines()) != 1 or len((t / "curl.runs").read_text().splitlines()) != runs + 1:
        fail("a working curl is run once and left alone")

    # curl crashes only on HTTPS (libnghttp2, Viva 2026-10-12): the local check passes, vward_fetch
    # noted the crash; the HTTP/2 library and curl are reinstalled and the note goes when it works.
    (t / "curl").write_text(f'#!/bin/sh\ncase "$*" in *https://*) [ -e "{t}/h2fixed" ] || kill -SEGV $$ ;; esac\nexit 0\n')
    (t / "opkg").write_text(f'#!/bin/sh\necho "$*" >> "{t}/opkg.log"\n: > "{t}/h2fixed"\n')
    (t / "tls.broken").write_text("")
    log = run()
    if (t / "opkg.log").read_text().splitlines()[-1] != "install --force-reinstall libnghttp2 libcurl curl":
        fail(f"curl crashing on HTTPS: its HTTP/2 library is not reinstalled: {(t / 'opkg.log').read_text()}")
    if "repair=curl-https|crash=139|reinstalled=libnghttp2,libcurl,curl|opkg=0|after=0" not in log or (t / "tls.broken").exists():
        fail(f"the HTTPS repair is not logged, or curl is not trusted again: {log[-300:]}")
    # No note of an HTTPS crash: nothing is reinstalled for HTTPS.
    n = len((t / "opkg.log").read_text().splitlines())
    run()
    if len((t / "opkg.log").read_text().splitlines()) != n:
        fail("HTTPS repair without a crash noted")

print("PROGRAM_REPAIR=PASS")
