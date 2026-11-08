#!/usr/bin/env python3
"""Observation by default (owner 08.11, ROADMAP 7): writers that changed the owner's settings on
their own only report what they would do unless the owner turns them on again.
  * policy-reconcile: DRY_RUN=1 unless policy_reconcile=act (or DRY_RUN given)."""

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
print("OBSERVATION_DEFAULTS=PASS")
