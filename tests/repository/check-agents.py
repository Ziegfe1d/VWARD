#!/usr/bin/env python3
"""Four agents, one zone each; the components agent (the cron supervisor) also watches the other
three: an agent whose last run is too old is «late», a run that hangs is stopped («hung»), two
runs of one agent at a time are reported (its own subshells are not a second run). The state goes
to RAM for the Panel; nothing is watched while VWARD is switched off. Run on the supervisor's own
functions, with a scratch /proc."""

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUP = (ROOT / "components/runtime/scripts/vward-cron-supervisor.sh").read_text()


def fail(message: str) -> None:
    raise SystemExit(f"AGENTS=FAIL: {message}")


def func(name: str) -> str:
    m = re.search(rf"^{name}\(\)\n\{{\n.*?^\}}\n", SUP, re.S | re.M) or re.search(rf"^{name}\(\) \{{.*?\}}\n", SUP, re.M)
    if not m:
        fail(f"the supervisor lacks {name}")
    return m.group(0)


jobs = re.search(r'^AGENT_JOBS="\n(.*?)^"\n', SUP, re.S | re.M)
if not jobs:
    fail("no list of the agents' jobs")
for need in ("vward-tunnel-guard.sh|network", "vward-wan-guard.sh|network", "vward-housekeeping.sh|maintenance", "vward-update-watch.sh|updates|"):
    if need not in jobs.group(1):
        fail(f"the components agent does not watch {need}")
if "    watch_agents\n" not in SUP.split("watch_services()", 1)[1].split("\n}\n", 1)[0]:
    fail("the components agent does not watch the others every minute")

with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    proc = t / "proc"; proc.mkdir()
    (proc / "uptime").write_text("5000.00 1.00\n")
    hung = subprocess.Popen(["sleep", "300"])
    young = subprocess.Popen(["sleep", "300"])

    def stat(pid, ppid, started_s):
        (proc / str(pid)).mkdir(exist_ok=True)
        (proc / str(pid) / "stat").write_text(f"{pid} (sh) S {ppid} " + " ".join(["0"] * 17) + f" {started_s * 100} 0 0\n")

    stat(hung.pid, 1, 5000 - 900)        # tunnel-guard, 15 minutes: hung (limit 300 s)
    stat(young.pid, 1, 5000 - 20)        # wan-guard, 20 s
    stat(70001, young.pid, 5000 - 19)    # its own subshell: not a second run
    stat(70002, 1, 5000 - 10)            # a second wan-guard run at the same time
    (t / "ps").write_text("#!/bin/sh\ncat <<'X'\n"
                          f"{hung.pid} root 1000 S sh /opt/bin/vward-tunnel-guard.sh\n"
                          f"{young.pid} root 1000 S sh /opt/bin/vward-wan-guard.sh\n"
                          "70001 root 1000 S sh /opt/bin/vward-wan-guard.sh\n"
                          "70002 root 1000 S sh /opt/bin/vward-wan-guard.sh\nX\n")
    (t / "ps").chmod(0o755)
    now = int(time.time())
    files = {"/tmp/vward-tunnel-health-chain.cron.last": now - 30, "/tmp/vward-wan-guard.cron.last": now - 30,
             "/tmp/vward-route-reconciler-maint.cron.last": now - 60, "/tmp/vward-housekeeping.cron.last": now - 4 * 3600,
             "/opt/var/log/vward/updater-watch.log": now - 600}
    job_text = jobs.group(1)
    for real, at in files.items():
        local = t / real.strip("/").replace("/", "_")
        local.write_text("x\n"); os.utime(local, (at, at))
        job_text = job_text.replace(real, str(local))
    script = (f'PROC={proc}; UPTIME_FILE={proc}/uptime; AGENTS_STATE={t}/agents.state; AGENT_NOTED=" "\n'
              f'log_event() {{ echo "$*" >> {t}/log; }}\n'
              f'AGENT_JOBS="\n{job_text}"\n' + func("age_of") + func("ppid_of") + func("watch_agents") + "watch_agents\nwatch_agents\n")
    r = subprocess.run(["sh", "-c", script], env=os.environ | {"PATH": f"{t}:{os.environ['PATH']}"}, text=True, capture_output=True, timeout=60)
    hung.wait(timeout=10)
    log = (t / "log").read_text() if (t / "log").exists() else ""
    state = dict(l.split("=", 1) for l in (t / "agents.state").read_text().split())
    if r.returncode != 0 or r.stderr:
        fail(f"watch_agents: {r.returncode} {r.stderr}")
    if hung.returncode is None or f"AGENT_HUNG|network|vward-tunnel-guard.sh|pid={hung.pid}" not in log or state.get("network") != "hung":
        fail(f"a hung run is stopped and said: {log} {state}")
    if young.poll() is not None:
        fail("a young run is left alone")
    if "AGENT_TWICE|network|vward-wan-guard.sh|runs=2" not in log:
        fail(f"two runs of one agent at a time are reported (its subshell is not one): {log}")
    if state.get("maintenance") != "late" or log.count("AGENT_LATE|maintenance") != 1:
        fail(f"an agent that has not run for 4 hours is late, said once: {log} {state}")
    if state.get("updates") != "ok" or state.get("components") != "ok":
        fail(f"the others are ok: {state}")
    young.kill()

if 'printf \'at=%s\\nstate=off\\n\'' not in SUP:
    fail("while VWARD is off the agents are not watched (state=off)")
api = (ROOT / "web/cgi-bin/api.cgi").read_text()
js = (ROOT / "web/assets/vward-console.js").read_text()
if "agents:($agents |" not in api or "AGENT_STATE = { late:" not in js or "pill(ag.network," not in js:
    fail("the Panel does not show what the components agent sees")
print("AGENTS=PASS")
