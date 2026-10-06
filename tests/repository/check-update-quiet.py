#!/usr/bin/env python3
"""An update stops VWARD's programs before replacing them; nothing may bring them back meanwhile.
On a router the real-time watcher saw the stopped route engine as fallen, asked the components
agent, which the request itself started again: every automatic update ended in «Could not quiesce».

- The update engine stops the real-time watcher before the programs (the components agent
  starts it again on resume).
- While an update is requested or under way, a request to the components agent is refused and
  does not start it; the watcher's actions are only logged."""

import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> None:
    raise SystemExit(f"UPDATE_QUIET=FAIL: {message}")


base = (ROOT / "components/update-engine/vward-update-common-base.sh").read_text()
q = re.search(r"^vu_runtime_quiesce\(\) \{\n.*?^\}\n", base, re.S | re.M)
if not q:
    fail("no vu_runtime_quiesce")
body = q.group(0)
if "vward-sentinel.sh}\" stop" not in body or body.index("vward-sentinel.sh}\" stop") > body.index("S92vward-runtime stop"):
    fail("the watcher is not stopped before the components agent")

adm = ROOT / "components/runtime/lib/vward-runtime-admission.sh"
act = ROOT / "components/runtime/scripts/vward-sentinel-act.sh"
with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    (t / "tmp").mkdir()
    init = t / "S92"; init.write_text(f"#!/bin/sh\necho started >> {t}/init.log\n"); init.chmod(0o755)
    env = dict(os.environ, VWARD_ROOT_PREFIX=str(t), VWARD_AGENT_REQ=str(t / "req"), VWARD_AGENT_PIDFILE=str(t / "none.pid"),
               VWARD_AGENT_INIT=str(init), VWARD_ADMISSION_LIB=str(adm), VWARD_SENTINEL_LOG=str(t / "sentinel.log"))

    def ask():
        return subprocess.run(["sh", "-c", f'. "{adm}"; vward_agent_ask start:route-engine'], env=env, capture_output=True, text=True, timeout=20).returncode

    if ask() != 0 or not (t / "init.log").exists() or not (t / "req/start:route-engine").exists():
        fail("without an update the request is made and the agent started")
    for marker in ("vward-update-requested", "vward-update.lock"):
        (t / "init.log").unlink(); (t / "req/start:route-engine").unlink()
        m = t / "tmp" / marker
        m.mkdir() if marker.endswith(".lock") else m.write_text("token\n")
        rc = ask()
        if rc != 75 or (t / "init.log").exists() or (t / "req/start:route-engine").exists():
            fail(f"during an update ({marker}) the request is refused and nothing starts: rc={rc}")
        r = subprocess.run(["sh", str(act), "down", "route-engine"], env=env, capture_output=True, text=True, timeout=20)
        if r.returncode != 0 or (t / "init.log").exists() or "down|route-engine|update" not in (t / "sentinel.log").read_text():
            fail(f"during an update ({marker}) the watcher's action only logs: rc={r.returncode}")
        m.rmdir() if m.is_dir() else m.unlink()
        (t / "init.log").write_text(""); (t / "req/start:route-engine").write_text("")
print("UPDATE_QUIET=PASS")
