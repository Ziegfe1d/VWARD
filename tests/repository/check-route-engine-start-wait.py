#!/usr/bin/env python3
"""S91 start: a slow but healthy engine start is waited for; a second core seen once is checked again.

Viva 1.11 (16:58, 17:12): WATCHDOG_RESTART cores=2 -> STOP TERM -> START_FAILED wait=12s and
PERSIST_RESTORE_LOCK_FAIL. The engine's start (route-change lock up to 10 s, the configuration 5-14 s
on a loaded Viva, up to 8 s of writes) can take longer than START_WAIT, and S91 killed it (TERM).
Now (start_service from S91 with its helpers stubbed, short waits):
A. alive, own lock, the only core, capture after START_WAIT: waited for, START_SLOW logged;
B. the engine dies: START_FAILED at once, as before;
C. alive but the lock is another's: START_FAILED at START_WAIT, as before (no long wait);
D. cores=2 seen once and gone 2 s later: no restart, WATCHDOG_CORES_TRANSIENT logged.
"""
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
S91 = (ROOT / "components/runtime/init.d/S91vward-route-engine").read_text()


def fail(msg):
    raise SystemExit(f"ROUTE_ENGINE_START_WAIT=FAIL: {msg}")


m = re.search(r"^start_service\(\)\n\{\n.*?^\}\n", S91, re.S | re.M)
if not m:
    fail("missing start_service")
start = m.group(0)
shells = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])

for shell in shells:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)

        def run(engine, healthy_seq="1"):
            for f in ("events", "tcp", "started", "seq"):
                (t / f).unlink(missing_ok=True)
            shutil.rmtree(t / "lock", ignore_errors=True)
            (t / "seq").write_text(healthy_seq)
            (t / "engine.sh").write_text("#!/bin/sh\n" + engine)
            (t / "engine.sh").chmod(0o755)
            script = f"""T="{t}"; PIDFILE="$T/pid"; SCRIPT="$T/engine.sh"; LOG="$T/log"; EVENT_LOG="$T/events"
LIVE_LOCK="$T/lock"; CHILD_STATE="$T/child"; DNSCAP=/bin/true; SENTINEL_CTL=/nonexistent
START_WAIT=2; START_WAIT_SLOW=6; UNHEALTHY=""
# service_healthy: answers from $T/seq (1 = unhealthy cores=2, 0 = healthy), one per call.
service_healthy() {{ s=$(cut -c1 "$T/seq"); rest=$(cut -c2- "$T/seq"); [ -n "$rest" ] && echo "$rest" > "$T/seq"
  if [ "$s" = 0 ]; then UNHEALTHY=""; PID=$(cat "$PIDFILE" 2>/dev/null); return 0; fi; UNHEALTHY=cores=2; return 1; }}
adaptive_core_count() {{ echo 1; }}
adaptive_tcpdump_pids() {{ [ ! -e "$T/tcp" ] || echo 1; }}
core_detail() {{ echo "1:1,"; }}
clean_service() {{ :; }}
last_stop() {{ echo none; }}
tcpdump_starts() {{ return 0; }}
{start}
start_service; echo "rc=$?"
"""
            t0 = time.time()
            r = subprocess.run([*shell, "-c", script], capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin", "T": str(t)})
            ev = (t / "events").read_text() if (t / "events").exists() else ""
            subprocess.run(["pkill", "-f", str(t / "engine.sh")], capture_output=True)
            return r.stdout, ev, time.time() - t0

        own = 'mkdir "$T/lock"; echo $$ > "$T/lock/pid"; touch "$T/started"\n'
        out, ev, dt = run(own + "sleep 4; touch \"$T/tcp\"; sleep 30\n")
        if "rc=0" not in out or "|START_SLOW|wait=" not in ev or "START_FAILED" in ev:
            fail(f"{shell}: RED a slow healthy start was killed: {out!r} {ev!r}")
        out, ev, dt = run(own + "sleep 1; exit 1\n")
        if "rc=1" not in out or "|START_FAILED|wait=1s" not in ev and "|START_FAILED|wait=2s" not in ev:
            fail(f"{shell}: an engine that died must fail at once: {out!r} {ev!r}")
        out, ev, dt = run('mkdir "$T/lock"; echo 1 > "$T/lock/pid"; sleep 30\n')
        if "rc=1" not in out or "|START_FAILED|wait=2s" not in ev or dt > 5:
            fail(f"{shell}: another's lock must fail at START_WAIT, not wait longer: {ev!r} {dt:.1f}s")
        out, ev, dt = run(own + "sleep 30\n", healthy_seq="10")
        if "rc=0" not in out or "|WATCHDOG_CORES_TRANSIENT|seen=cores=2" not in ev or "WATCHDOG_RESTART" in ev or (t / "started").exists():
            fail(f"{shell}: a second core seen once must not restart the engine: {out!r} {ev!r}")
        out, ev, dt = run(own + "touch \"$T/tcp\"; sleep 30\n", healthy_seq="11")
        if "|WATCHDOG_RESTART|reason=cores=2" not in ev:
            fail(f"{shell}: a second core still there 2 s later must restart: {ev!r}")
print("ROUTE_ENGINE_START_WAIT=PASS")
