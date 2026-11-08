#!/usr/bin/env python3
"""Observation by default (owner 08.11, ROADMAP 7): writers that changed the owner's settings on
their own only report what they would do unless the owner turns them on again.
  * policy-reconcile: DRY_RUN=1 unless policy_reconcile=act (or DRY_RUN given);
  * housekeeping moves installed routers to the new schedules (ads scheduler every 5 minutes, no
    per-minute S91 cron watchdog) and back when the owner's file says so."""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHELLS = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])


def fail(message: str) -> None:
    raise SystemExit(f"OBSERVATION_DEFAULTS=FAIL: {message}")


src = (ROOT / "components/policy-sync/scripts/vward-policy-reconcile.sh").read_text()
m = re.search(r'^DRY_RUN="\$\{DRY_RUN:-\}"\n.*?^fi\n', src, re.S | re.M)
if not m:
    fail("policy-reconcile: no default DRY_RUN block")
block = m.group(0)
with tempfile.TemporaryDirectory() as tmp:
    conf = Path(tmp) / "lists.conf"
    for sh in SHELLS:
        for content, env, want in ((None, "", "1"), ("watch.x=1\n", "", "1"), ("policy_reconcile=act\n", "", "0"),
                                   ("policy_reconcile=1\n", "", "0"), ("policy_reconcile=observe\n", "", "1"),
                                   ("policy_reconcile=act\n", "DRY_RUN=1", "1"), (None, "DRY_RUN=0", "0")):
            if content is None:
                conf.unlink(missing_ok=True)
            else:
                conf.write_text(content)
            r = subprocess.run(sh + ["-c", f'{env + "; " if env else ""}VWARD_DOMAIN_LISTS_CONF="{conf}"\n{block}printf %s "$DRY_RUN"'],
                               text=True, capture_output=True)
            if r.stdout != want:
                fail(f"{sh} policy-reconcile conf={content!r} env={env!r}: DRY_RUN={r.stdout!r}, want {want}")

# Schedules on installed routers (housekeeping's cron_set_schedule).
hk = (ROOT / "components/runtime/scripts/vward-housekeeping.sh").read_text()
m = re.search(r"^cron_set_schedule\(\)\n\{\n.*?^\}\n", hk, re.S | re.M)
if not m or "\ncron_set_schedule\n" not in hk:
    fail("housekeeping does not set the schedules")
fn = m.group(0)
old_cron = (ROOT / "config/cron/root.crontab").read_text()
old_cron = old_cron.replace("*/5 * * * * /opt/bin/vward-ads-privacy-scheduler.sh", "* * * * * /opt/bin/vward-ads-privacy-scheduler.sh")
old_cron = old_cron.replace("# off: the components agent keeps it running # ", "")
DNS_LINE = [l for l in old_cron.splitlines() if "/opt/bin/vward-ads-privacy-scheduler.sh dns " in l][0]
old_cron = old_cron.replace(DNS_LINE + "\n", "")
old_cron += "# owner's own line\n3 3 * * * /opt/bin/owner-job.sh\n"
with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    (t / "cron").mkdir(); (t / "tmp").mkdir(); (t / "opt/etc/vward").mkdir(parents=True); (t / "opt/var/log").mkdir(parents=True)
    root = t / "cron/root"
    root.write_text(old_cron)
    (t / "crontab").write_text(f'#!/bin/sh\n[ "$1" = -c ] && shift 2\necho x >> "{t}/writes"\ncat "$1" > "{t}/cron/root"\n')
    (t / "crontab").chmod(0o755)
    def hk_run():
        r = subprocess.run(["sh", "-c", f'R="{t}"; CRON_DIR="{t}/cron"; CRON_ROOT="{t}/cron/root"; CRON_OLD="{t}/old"; '
                            f'HOUSE_LOG="{t}/house.log"; VWARD_CRONTAB="{t}/crontab"\n{fn}cron_set_schedule'], text=True, capture_output=True)
        if r.returncode:
            fail(f"cron_set_schedule: {r.stderr}")
        return root.read_text()
    def writes():
        w = t / "writes"
        return len(w.read_text().splitlines()) if w.exists() else 0
    new = hk_run()
    lines = new.splitlines()
    if not any(l.startswith("*/5 * * * * /opt/bin/vward-ads-privacy-scheduler.sh ") for l in lines):
        fail("the ads scheduler must run every 5 minutes")
    if any(l.startswith("* * * * * /opt/etc/init.d/S91vward-route-engine start") for l in lines):
        fail("the per-minute S91 watchdog must be off")
    if "# off: the components agent keeps it running # * * * * * /opt/etc/init.d/S91vward-route-engine start" not in new:
        fail("the S91 line is kept, commented")
    if "3 3 * * * /opt/bin/owner-job.sh" not in new or len(lines) != len(old_cron.splitlines()) + 1 or lines.count(DNS_LINE) != 1:
        fail("the owner's lines stay, the DNS guard's minute line is added once, nothing lost")
    if writes() != 1 or not list((t / "old").iterdir()):
        fail("one write, the crontab before kept in the backups")
    if hk_run() != new or writes() != 1:
        fail("the next run changes nothing")
    (t / "opt/etc/vward/ads-scheduler.every-minute").touch()
    (t / "opt/etc/vward/route-engine.cron-watchdog").touch()
    if hk_run() != old_cron + DNS_LINE + "\n":
        fail("the owner's files turn both back, byte for byte (the DNS guard's line stays)")
    # A fresh install gets the template, the same result.
    root.write_text((ROOT / "config/cron/root.crontab").read_text())
    (t / "opt/etc/vward/ads-scheduler.every-minute").unlink(); (t / "opt/etc/vward/route-engine.cron-watchdog").unlink()
    before = writes()
    if hk_run() != (ROOT / "config/cron/root.crontab").read_text() or writes() != before:
        fail("the template is already the default: no write")
print("OBSERVATION_DEFAULTS=PASS")
