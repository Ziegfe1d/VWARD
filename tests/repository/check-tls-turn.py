#!/usr/bin/env python3
"""P0-1: the shared HTTPS turn (vward_tls_take) never succeeds without ownership.

Real device-profile functions under sh and BusyBox ash: free/contended turn, the
bounded waits (5 s with a fresh .ok, 20 s without, explicit WAIT for downloads),
live / dead / PID-reused / expired / ownerless owners, SIGKILL of an owner, release
only of the caller's own turn, crash codes against network and external codes,
the vward_fetch fallback, and exclusivity of parallel takers. Also the route
reconciler: a direct check that did not run is never ISP_BAD.
"""
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "components/runtime/lib/vward-device-profile.sh"
RECON = (ROOT / "components/route-reconciler/scripts/vward-route-reconciler.sh").read_text()
SHELLS = [["sh"]] + ([["busybox", "ash"]] if shutil.which("busybox") else [])
fails = []


def check(label, cond, detail=""):
    if not cond:
        fails.append(f"{label}: {detail}")


def sh(shell, t, body, timeout=60, env=None):
    script = f'. "{PROFILE}"\nVWARD_TLS_BROKEN_FLAG="{t}/tls.broken"\n{body}\n'
    start = time.monotonic()
    r = subprocess.run(shell + ["-c", script], capture_output=True, text=True, timeout=timeout,
                       env=(os.environ | (env or {})))
    return r, time.monotonic() - start


def proc_id(pid):
    stat = Path(f"/proc/{pid}/stat").read_text()
    return f"{pid} {stat.rsplit(') ', 1)[1].split()[19]}"


def age(path, minutes):
    t = time.time() - minutes * 60
    os.utime(path, (t, t))


for shell in SHELLS:
    n = shell[-1]
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        lock = t / "tls.probe"

        # 1. Free turn: owned, owner recorded as THIS shell, given back by done.
        r, _ = sh(shell, t, 'vward_tls_take; echo "rc=$? mine=$_vt_mine"; cat "$_vt_lock/owner"; '
                            'read -r me _ < /proc/self/stat; echo "me=$me"; vward_tls_done 0; [ -d "$_vt_lock" ] && echo LEFT')
        out = r.stdout.split("\n")
        check(f"{n} free", out[0] == "rc=0 mine=1", r.stdout + r.stderr)
        check(f"{n} free owner", len(out) > 2 and out[1].split()[:1] == out[2].split("=")[1:2], r.stdout)
        check(f"{n} free release", "LEFT" not in r.stdout and not lock.exists(), r.stdout)
        check(f"{n} done 0 writes .ok", (t / "tls.ok").exists())

        # 2. A live owner holds the turn: 2 after the bounded wait, never 0; lock untouched.
        holder = subprocess.Popen(["sleep", "120"])
        try:
            shutil.rmtree(lock, ignore_errors=True); lock.mkdir()
            (lock / "owner").write_text(proc_id(holder.pid) + "\n")
            before = (lock / "owner").read_text()
            r, dt = sh(shell, t, 'vward_tls_take; echo "rc=$? mine=$_vt_mine"')
            check(f"{n} contended .ok", r.stdout.strip() == "rc=2 mine=0", r.stdout)
            check(f"{n} contended .ok wait", 4.0 <= dt <= 9.0, f"{dt:.1f}s")
            r, dt = sh(shell, t, 'vward_tls_take 2; echo "rc=$?"')
            check(f"{n} contended WAIT=2", r.stdout.strip() == "rc=2" and 1.5 <= dt <= 5.0, f"{r.stdout} {dt:.1f}s")
            if n == "sh":
                (t / "tls.ok").unlink()
                r, dt = sh(shell, t, 'vward_tls_take; echo "rc=$?"', timeout=90)
                check(f"{n} contended no .ok", r.stdout.strip() == "rc=2" and 19.0 <= dt <= 26.0, f"{r.stdout} {dt:.1f}s")
                (t / "tls.ok").touch()
            check(f"{n} live owner kept", (lock / "owner").read_text() == before)
            # Non-owner done never removes someone else's turn.
            sh(shell, t, 'vward_tls_done 0; _vt_mine=1; _vt_id="1 1"; vward_tls_done 0')
            check(f"{n} foreign done", (lock / "owner").read_text() == before)
            # Broken noted while waiting: 1, not 2 and not 0.
            r, dt = sh(shell, t, f'( sleep 1; : > "{t}/tls.broken" ) & vward_tls_take 10; echo "rc=$?"')
            check(f"{n} broken while waiting", r.stdout.strip() == "rc=1" and dt < 6, f"{r.stdout} {dt:.1f}s")
            (t / "tls.broken").unlink()
            # Expired live owner (past VWARD_TLS_TURN_MAX_MIN) is taken away.
            age(lock, 11)
            r, dt = sh(shell, t, 'vward_tls_take 3; echo "rc=$? mine=$_vt_mine"; vward_tls_done 0')
            check(f"{n} expired live owner", r.stdout.strip() == "rc=0 mine=1" and dt < 2.5, f"{r.stdout} {dt:.1f}s")
        finally:
            holder.kill(); holder.wait()

        # 3. Dead owner (exited process) and a reused PID with another start: taken at once.
        gone = subprocess.Popen(["true"]); gone.wait()
        for case, owner in (("dead", f"{gone.pid} 12345"), ("pid-reused", f"{os.getpid()} 1")):
            shutil.rmtree(lock, ignore_errors=True); lock.mkdir()
            (lock / "owner").write_text(owner + "\n")
            r, dt = sh(shell, t, 'vward_tls_take 3; echo "rc=$? mine=$_vt_mine"; vward_tls_done 0')
            check(f"{n} {case}", r.stdout.strip() == "rc=0 mine=1" and dt < 2.5, f"{r.stdout} {dt:.1f}s")
            check(f"{n} {case} released", not lock.exists())

        # 4. Ownerless turn: fresh is respected (2), older than a minute is taken away.
        shutil.rmtree(lock, ignore_errors=True); lock.mkdir()
        r, _ = sh(shell, t, 'vward_tls_take 1; echo "rc=$?"')
        check(f"{n} ownerless fresh", r.stdout.strip() == "rc=2", r.stdout)
        age(lock, 2)
        r, _ = sh(shell, t, 'vward_tls_take 1; echo "rc=$?"; vward_tls_done 0')
        check(f"{n} ownerless old", r.stdout.strip() == "rc=0", r.stdout)

        # 5. An owner killed by SIGKILL between take and done: the next caller gets the turn at once.
        p = subprocess.Popen(shell + ["-c", f'. "{PROFILE}"\nVWARD_TLS_BROKEN_FLAG="{t}/tls.broken"\n'
                                      f'vward_tls_take && : > "{t}/taken"; exec sleep 120'])
        for _ in range(100):
            if (t / "taken").exists():
                break
            time.sleep(0.05)
        r, _ = sh(shell, t, 'vward_tls_take 1; echo "rc=$?"')
        check(f"{n} live killer-to-be holds", r.stdout.strip() == "rc=2", r.stdout)
        p.kill(); p.wait()
        r, dt = sh(shell, t, 'vward_tls_take 3; echo "rc=$?"; vward_tls_done 0')
        check(f"{n} after SIGKILL", r.stdout.strip() == "rc=0" and dt < 2.5, f"{r.stdout} {dt:.1f}s")

        # 6. Result codes: crash -> broken (no .ok); network/external -> no broken.
        for rc, broken, ok in ((28, 0, 1), (35, 0, 1), (52, 0, 1), (60, 0, 1), (132, 1, 0), (134, 1, 0),
                               (135, 1, 0), (136, 1, 0), (139, 1, 0), (137, 0, 0), (141, 0, 0), (143, 0, 0)):
            for f in ("tls.broken", "tls.ok"):
                (t / f).unlink(missing_ok=True)
            sh(shell, t, f'vward_tls_take; vward_tls_done {rc}')
            check(f"{n} rc {rc}", (t / "tls.broken").exists() == bool(broken) and (t / "tls.ok").exists() == bool(ok),
                  f"broken={(t / 'tls.broken').exists()} ok={(t / 'tls.ok').exists()}")
            check(f"{n} rc {rc} released", not lock.exists())
        (t / "tls.broken").touch()
        r, dt = sh(shell, t, 'vward_tls_take; echo "rc=$?"')
        check(f"{n} broken within the hour", r.stdout.strip() == "rc=1" and dt < 1.5, r.stdout)
        (t / "tls.broken").unlink()

        # 7. vward_fetch: busy turn -> fallback, never curl unowned; free turn -> curl; crash -> fallback.
        tools = t / "tools"; tools.mkdir()
        (tools / "curl").write_text(f'#!/bin/sh\necho curl >> "{t}/fetch.calls"\nexit "$(cat {t}/curl.rc)"\n')
        (tools / "uclient").write_text(f'#!/bin/sh\necho uclient >> "{t}/fetch.calls"\nexit 0\n')
        for f in ("curl", "uclient"):
            (tools / f).chmod(0o755)
        env = {"VWARD_CURL_BIN": str(tools / "curl"), "VWARD_UCLIENT_BIN": str(tools / "uclient")}
        holder = subprocess.Popen(["sleep", "120"])
        try:
            shutil.rmtree(lock, ignore_errors=True); lock.mkdir(); (lock / "owner").write_text(proc_id(holder.pid) + "\n")
            (t / "curl.rc").write_text("0")
            r, dt = sh(shell, t, 'vward_fetch -s -o /dev/null https://example.invalid/; echo "rc=$?"', env=env)
            calls = (t / "fetch.calls").read_text().split() if (t / "fetch.calls").exists() else []
            check(f"{n} fetch busy", calls == ["uclient"] and 18 <= dt <= 26, f"{calls} {dt:.1f}s {r.stdout}")
        finally:
            holder.kill(); holder.wait()
        shutil.rmtree(lock, ignore_errors=True)
        for rc, want in (("0", ["curl"]), ("28", ["curl"]), ("139", ["curl", "uclient"])):
            (t / "fetch.calls").unlink(missing_ok=True); (t / "tls.broken").unlink(missing_ok=True)
            (t / "curl.rc").write_text(rc)
            sh(shell, t, 'vward_fetch -s -o /dev/null https://example.invalid/', env=env)
            calls = (t / "fetch.calls").read_text().split() if (t / "fetch.calls").exists() else []
            check(f"{n} fetch rc {rc}", calls == want, calls)
            check(f"{n} fetch rc {rc} released", not lock.exists())
        (t / "tls.broken").unlink(missing_ok=True)

        # 8. Exclusivity: 6 parallel takers holding the turn ~0.3 s each never overlap.
        log = t / "excl.log"
        procs = [subprocess.Popen(shell + ["-c", f'. "{PROFILE}"\nVWARD_TLS_BROKEN_FLAG="{t}/tls.broken"\n'
                                           f'if vward_tls_take 15; then echo "in $$" >> "{log}"; i=0; '
                                           f'while [ $i -lt 30000 ]; do i=$((i+1)); done; '
                                           f'echo "out $$" >> "{log}"; vward_tls_done 0; else echo "skip $$" >> "{log}"; fi'])
                 for _ in range(6)]
        for p in procs:
            p.wait(timeout=120)
        rows = log.read_text().split("\n")[:-1] if log.exists() else []
        depth = bad = 0
        for row in rows:
            if row.startswith("in"):
                depth += 1
                bad |= depth > 1
            elif row.startswith("out"):
                depth -= 1
        check(f"{n} exclusive", not bad and sum(r.startswith("in") for r in rows) >= 1, rows)

    # 9. Reconciler: a direct check that did not run is UNKNOWN, a real failure stays ISP_BAD.
    m = re.search(r"^isp_check_ran\(\)\n\{\n.*?^\}\n", RECON, re.S | re.M)
    c = re.search(r"^classify_isp_vs_vpn\(\)\n\{\n.*?^\}\n", RECON, re.S | re.M)
    for isp, want in (("2|000|-", "UNKNOWN"), ("143|000|-", "UNKNOWN"), ("137|000|-", "UNKNOWN"),
                      ("139|000|-", "UNKNOWN"), ("28|000|3", "ISP_BAD"), ("7|000|0", "ISP_BAD")):
        script = (m.group(0) if m else "") + (c.group(0) if c else "") + \
            f'probe_result() {{ if [ "$2" = eth3 ]; then echo "{isp}"; else echo "0|200|0.1"; fi; }}\nWAN=eth3 WG=nwg0\nclassify_isp_vs_vpn h 192.0.2.1'
        out = subprocess.run(shell + ["-c", script], capture_output=True, text=True).stdout.split("|")[0].strip()
        check(f"{n} reconciler {isp}", out == want, out)

if fails:
    raise SystemExit("TLS_TURN=FAIL\n" + "\n".join(fails))
print("TLS_TURN=PASS " + "+".join(s[-1] for s in SHELLS) +
      ": owned-only success, bounded 5/20 s waits, dead/reused/expired/ownerless/SIGKILL recovery, own-only release, crash vs network codes, fetch fallback, exclusive; reconciler UNKNOWN")
