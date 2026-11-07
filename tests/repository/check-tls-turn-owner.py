#!/usr/bin/env python3
"""Addressed audit: who owns the shared HTTPS turn (vward_tls_take).

The owner is the PROCESS that ran vward_tls_take (PID + start from /proc/self).
A subshell that takes the turn and exits leaves a dead owner: the next caller
reaps it at once, while a curl started by the parent would still be running,
and the parent's vward_tls_done cannot give back (it never set _vt_mine). So
the contract is: take, curl and done in ONE process; curl may run in its
descendant ($(...) of the owner), never in its parent.

1. Dynamic (real functions, sh + BusyBox ash): take in a subshell, curl in the
   parent -> the turn is lost immediately (documents the hazard); take in the
   parent with curl in a $(...) child -> another taker is refused the whole
   time the child runs; the parent's done after a subshell take never removes
   a turn owned by somebody else.
2. Static: every production call of vward_tls_take sits in a function that
   also runs the curl and vward_tls_done, at statement level (not inside
   $(...), backticks, a ( ) group or a pipeline) and not in a subshell-bodied
   function whose curl would then run in the caller.
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
SHELLS = [["sh"]] + ([["busybox", "ash"]] if shutil.which("busybox") else [])
fails = []


def check(label, cond, detail=""):
    if not cond:
        fails.append(f"{label}: {detail}")


def run(shell, t, body, timeout=60):
    script = f'. "{PROFILE}"\nVWARD_TLS_BROKEN_FLAG="{t}/tls.broken"\n{body}\n'
    return subprocess.run(shell + ["-c", script], capture_output=True, text=True, timeout=timeout)


def taker(shell, t, wait):
    """Another agent asking for the turn now: its rc (0 owned, 2 not given)."""
    r = run(shell, t, f'vward_tls_take {wait}; rc=$?; [ "$rc" = 0 ] && vward_tls_done 0; echo "rc=$rc"')
    return r.stdout.strip()


for shell in SHELLS:
    n = shell[-1]
    # 1a. Take in a subshell, "curl" in the parent: the subshell is gone, so the
    # turn is reaped by the next caller while the parent's curl would run.
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        r = run(shell, t, f'( vward_tls_take 0; echo "sub=$?" ); echo "parent_mine=${{_vt_mine:-0}}"; '
                          f'"{shutil.which("sh")}" -c "sleep 3" & cpid=$!; sleep 0.5; '
                          f'echo "{"MARK"}"; wait "$cpid"; vward_tls_done 0; '
                          f'[ -d "$_vt_lock" ] && echo "left=$(cat "$_vt_lock/owner")"')
        check(f"{n} subshell take", "sub=0" in r.stdout and "parent_mine=0" in r.stdout, r.stdout + r.stderr)
        # The subshell owner is dead: another caller gets the turn at once.
        check(f"{n} dead subshell owner is reaped", taker(shell, t, 0) == "rc=0",
              "a subshell-held turn must not block (and so cannot protect a parent's curl)")

    # 1b. Take in the parent, curl in a $(...) child: exclusive while it runs.
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        p = subprocess.Popen(shell + ["-c", f'. "{PROFILE}"\nVWARD_TLS_BROKEN_FLAG="{t}/tls.broken"\n'
                                             'vward_tls_take 0 || exit 9\n'
                                             f'out=$( : > "{t}/child-running"; sleep 3; echo done )\n'
                                             'vward_tls_done 0\necho "$out"\n'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(100):
            if (t / "child-running").exists():
                break
            time.sleep(0.05)
        check(f"{n} child curl started", (t / "child-running").exists())
        check(f"{n} turn held during child curl", taker(shell, t, 1) == "rc=2",
              "a live owner's turn must not be given while its $(...) curl runs")
        out, err = p.communicate(timeout=30)
        check(f"{n} owner finished", p.returncode == 0 and out.strip() == "done", out + err)
        check(f"{n} turn given back by owner", not (t / "tls.probe").exists())
        check(f"{n} free after owner", taker(shell, t, 0) == "rc=0")

    # 1c. Parent done after a subshell take never removes somebody else's turn.
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        holder = subprocess.Popen(shell + ["-c", f'. "{PROFILE}"\nVWARD_TLS_BROKEN_FLAG="{t}/tls.broken"\n'
                                                  f'( vward_tls_take 0 ) ; : > "{t}/sub-done"\n'
                                                  f'while [ ! -e "{t}/go" ]; do sleep 0.05; done\n'
                                                  'vward_tls_done 0\n'],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(100):
            if (t / "sub-done").exists():
                break
            time.sleep(0.05)
        other = subprocess.Popen(shell + ["-c", f'. "{PROFILE}"\nVWARD_TLS_BROKEN_FLAG="{t}/tls.broken"\n'
                                                 f'vward_tls_take 0 || exit 9\n: > "{t}/other-owns"\n'
                                                 f'while [ ! -e "{t}/release" ]; do sleep 0.05; done\nvward_tls_done 0\n'],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(100):
            if (t / "other-owns").exists():
                break
            time.sleep(0.05)
        check(f"{n} other took reaped turn", (t / "other-owns").exists())
        (t / "go").touch()
        holder.communicate(timeout=30)
        check(f"{n} parent done keeps other's turn", (t / "tls.probe/owner").exists() and
              (t / "tls.probe/owner").read_text().split()[0] == str(other.pid),
              "vward_tls_done in a process that does not own the turn must not release it")
        (t / "release").touch()
        other.communicate(timeout=30)
        check(f"{n} other gave back", not (t / "tls.probe").exists())

# 2. Static: every production take is in the same process as its curl and done.
FUNC = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*(\{|\()?\s*$')


def functions(text):
    """(name, body-opener, start, end) of top-level and nested shell functions."""
    lines = text.split("\n")
    out = []
    for i, line in enumerate(lines):
        m = FUNC.match(line)
        if not m:
            continue
        opener = m.group(2) or (lines[i + 1].strip()[:1] if i + 1 < len(lines) else "")
        indent = len(line) - len(line.lstrip())
        closer = "}" if opener == "{" else ")"
        end = i + 1
        while end < len(lines):
            s = lines[end]
            if s.strip() == closer and len(s) - len(s.lstrip()) == indent:
                break
            end += 1
        out.append((m.group(1), opener, i, end))
    return lines, out


sites = 0
for path in list(ROOT.glob("components/**/*.sh")) + list(ROOT.glob("components/**/*.cgi")):
    text = path.read_text(errors="replace")
    if "vward_tls_take" not in text:
        continue
    lines, funcs = functions(text)
    for i, line in enumerate(lines):
        code = line.split("#", 1)[0]
        if "vward_tls_take" not in code or re.match(r'^\s*vward_tls_take\s*\(\)', code):
            continue
        if "command -v vward_tls_take" in code and code.count("vward_tls_take") == 1:
            continue
        sites += 1
        rel = path.relative_to(ROOT)
        # Statement level: no $(, backtick, ( group or pipe before the call.
        before = code[:code.index("vward_tls_take", code.index("command -v vward_tls_take") + 1
                                  if "command -v vward_tls_take" in code else 0)]
        check(f"{rel}:{i+1} statement level", "$(" not in before and "`" not in before and
              not re.search(r'(^|[;&|]\s*)\(\s', before) and not re.search(r'[^|]\|[^|]', before),
              code.strip())
        enclosing = [f for f in funcs if f[2] < i < f[3]]
        check(f"{rel}:{i+1} inside a function", bool(enclosing), code.strip())
        if not enclosing:
            continue
        name, opener, s, e = max(enclosing, key=lambda f: f[2])
        body = "\n".join(l.split("#", 1)[0] for l in lines[i:e])
        check(f"{rel}:{i+1} curl in the owner ({name})", re.search(r'(^|[\s(]|")(curl|"\$_vf_curl")\s', body) is not None,
              "the curl guarded by this turn must run in the same function")
        check(f"{rel}:{i+1} done in the owner ({name})", "vward_tls_done" in body,
              "the turn must be given back by the process that took it")
        if opener == "(":
            # A subshell-bodied function: its curl must not be left to the caller.
            check(f"{rel}:{i+1} subshell function keeps curl", "curl" in body, name)

check("static sites found", sites >= 6, f"only {sites} vward_tls_take call sites")

if fails:
    raise SystemExit("TLS_TURN_OWNER=FAIL\n" + "\n".join(fails))
print(f"TLS_TURN_OWNER=PASS {len(SHELLS)} shells; {sites} production call sites take, run curl and give back "
      "in one process; a subshell take is reaped at once and is never used")
