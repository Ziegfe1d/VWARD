#!/usr/bin/env python3
"""The Ads job queue: the scheduler runs the worker when the queue folder holds jobs (it
looked at the old single file only, so jobs queued from the Panel waited for ever); status
lists the queue itself; a queued job can be cancelled; «Выполнить очередь» drains it; the API
and the Panel show the list with its controls."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "components/ads-privacy-guard/scripts"
JOB = SCRIPTS / "vward-ads-privacy-job.sh"
SCHED = (SCRIPTS / "vward-ads-privacy-scheduler.sh").read_text()
API = (ROOT / "web/cgi-bin/api.cgi").read_text()
JS = (ROOT / "web/assets/vward-console.js").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"ADS_JOBS=FAIL: {message}")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / "root/tmp").mkdir(parents=True)
    ran = tmp / "ran"
    scanner = tmp / "scan.sh"; scanner.write_text(f"#!/bin/sh\necho scan >> {ran}\n"); scanner.chmod(0o755)
    rebuild = tmp / "rebuild.sh"; rebuild.write_text(f"#!/bin/sh\necho rebuild >> {ran}\n"); rebuild.chmod(0o755)
    env = os.environ | {"VWARD_ADS_LIB": str(ROOT / "components/ads-privacy-guard/lib/vward-ads-privacy-common.sh"),
                        "VWARD_ADS_ETC": str(tmp / "etc"), "VWARD_ADS_STATE": str(tmp / "state"), "VWARD_ADS_LOG_DIR": str(tmp / "log"),
                        "VWARD_ROOT_PREFIX": str(tmp / "root"), "TMPDIR": str(tmp),
                        "VWARD_ADMISSION_LIB": str(ROOT / "components/runtime/lib/vward-runtime-admission.sh"),
                        "VWARD_ADS_SCANNER": str(scanner), "VWARD_ADS_RULES_REBUILD": str(rebuild)}

    def job(*args):
        r = subprocess.run(["sh", str(JOB), *args], env=env, text=True, capture_output=True, timeout=60)
        return r.stdout + r.stderr

    ids = []
    for t in ("scan", "rules-rebuild", "scan"):
        out = job("enqueue", t)
        ids.append(next(l.split("=", 1)[1] for l in out.splitlines() if l.startswith("JOB_ID=")))
    st = job("status")
    queued = [l for l in st.splitlines() if l.startswith("QUEUED_")]
    if "JOB_QUEUE=3" not in st or len(queued) != 3 or not queued[0].startswith(f"QUEUED_01={ids[0]}|scan|"):
        fail(f"status lists the queue: {st}")

    # The scheduler's check sees the folder (the old file is empty).
    a = SCHED.index("jobs_waiting()"); fn = SCHED[a:SCHED.index("\n}\n", a) + 3]
    r = subprocess.run(["sh", "-c", fn + 'jobs_waiting && echo yes || echo no'], env=env | {"ADS_STATE": str(tmp / "state")}, text=True, capture_output=True)
    if r.stdout.strip() != "yes":
        fail("the scheduler must see jobs in the queue folder")
    if 'if [ -x "$JOB" ] && jobs_waiting; then' not in SCHED:
        fail("the scheduler runs the worker on jobs_waiting")

    if "JOB=CANCELLED" not in job("cancel", ids[1]) or "JOB=NOT_QUEUED" not in job("cancel", ids[1]) or "invalid job id" not in job("cancel", "../x"):
        fail("cancel: a queued job goes, twice changes nothing, odd ids refused")
    out = job("drain")
    if "JOB_DRAINED=2" not in out or ran.read_text() != "scan\nscan\n":
        fail(f"drain runs the queue: {out} {ran.read_text() if ran.exists() else ''}")
    st = job("status")
    if "JOB_QUEUE=0" not in st or "LAST_state=DONE" not in st:
        fail(f"after drain: {st}")

for need in ("job-run|job-cancel|agh", 'drain </dev/null >/dev/null 2>&1 & )', 'cancel "$JID"',
             'queue:[$jobsraw | to_entries[] | select(.key | startswith("QUEUED_"))'):
    if need not in API:
        fail(f"the API lacks {need}")
for need in ("panel('Очередь'", "data-act=\"ads-job-cancel\"", "btn('ads-job-run', 'refresh', 'Выполнить очередь сейчас'", "a === 'ads-job-run'",
             "a === 'ads-job-cancel'", "ctrlRow('Обработка заданий', sw('data-ads-pause'"):
    if need not in JS:
        fail(f"the Panel lacks {need}")
print("ADS_JOBS=PASS")
