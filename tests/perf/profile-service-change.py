#!/usr/bin/env python3
"""Attribute the processes of ONE service-change request to shell functions.

Diagnostic only (fixtures, never a router, never a CI gate). Runs the actual
copied console closure under bash with xtrace (PS4 carries the time, $BASHPID
and the function stack) and strace (clone/execve with timestamps). Each new
process is charged to the function stack of its own first trace line (a
subshell or pipeline element) or, for a child that only exec'd, to the parent's
latest trace line before the clone. bash is used ONLY to obtain function names;
the shipped interpreters remain dash and BusyBox ash, whose counts come from
check-service-change-budget.py.

Usage: profile-service-change.py [scenario ...]   (cold change repeat off)
Prints per scenario: processes, show running-config reads, top functions
(inclusive and self), top exec'd tools.
"""
import bisect
import collections
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'routing-readers'))
from live_fixture import LiveFixture  # noqa: E402

TRACE_LINE = re.compile(r'^\++(\d+\.\d+)\|(\d+)\|([^|]*)\| ?(.*)$')
STRACE_LINE = re.compile(r'^(\d+)\s+(\d+\.\d+)\s+(clone3?|fork|vfork|execve)\((.*)$')
INJECT = ("if [ -n \"${VPROF_TRACE:-}\" ] && [ -n \"${BASH_VERSION:-}\" ]; then\n"
          "PS4='+${EPOCHREALTIME}|${BASHPID}|${FUNCNAME[*]}| '\n"
          "eval 'exec 19>>\"$VPROF_TRACE\"'; BASH_XTRACEFD=19; set -x\nfi\n")


def request(f, kind, *args):
    trace = f.p / f'{kind}.xtrace'
    slog = f.p / f'{kind}.strace'
    for p in (trace, slog):
        if p.exists():
            p.unlink()
    env = f.env | {'VWARD_DEVICE_CONFIG_OWNER_UID': str(os.getuid()),
                   'VWARD_CONSOLE_EDIT_LOCK': str(f.prefix/'tmp/vward-console-edit.lock'),
                   'VWARD_ROUTE_CHANGE_LOCK': str(f.prefix/'tmp/vward-route-change.lock'),
                   'VWARD_CONSOLE_AUDIT_LOG': str(f.p/'console-audit'),
                   'VPROF_TRACE': str(trace)}
    calls_before = f.calls.read_text().count('\tshow running-config\n') if f.calls.exists() else 0
    ndm_before = len(f.calls.read_text().splitlines()) if f.calls.exists() else 0
    p = subprocess.run(['strace', '-f', '-qq', '-ttt', '-e', 'trace=clone,clone3,fork,vfork,execve',
                        '-o', str(slog), 'bash', str(f.console_path), *args],
                       env=env, text=True, capture_output=True, timeout=900)
    calls = f.calls.read_text() if f.calls.exists() else ''
    reads = calls.count('\tshow running-config\n') - calls_before
    ndm = len(calls.splitlines()) - ndm_before
    return p, analyse(trace, slog), reads, ndm


def analyse(trace, slog):
    lines_by_pid = collections.defaultdict(list)   # pid -> [(t, stack, cmd)]
    for raw in trace.read_text(errors='replace').splitlines():
        m = TRACE_LINE.match(raw)
        if m:
            lines_by_pid[int(m[2])].append((float(m[1]), m[3], m[4]))
    clones = []            # (t, parent, child)
    execs = {}             # pid -> basename of first execve
    for raw in slog.read_text(errors='replace').splitlines():
        m = STRACE_LINE.match(raw)
        if not m:
            continue
        pid, t, call, rest = int(m[1]), float(m[2]), m[3], m[4]
        if call == 'execve':
            if pid not in execs and not rest.endswith('= -1 ENOENT (No such file or directory)') and ' = -1 ' not in rest:
                path = rest.split('"', 2)[1] if '"' in rest else '?'
                execs[pid] = os.path.basename(path)
        else:
            rm = re.search(r'= (\d+)$', rest)
            if rm:
                clones.append((t, pid, int(rm[1])))
    times = {pid: [x[0] for x in v] for pid, v in lines_by_pid.items()}
    stack_of = {}
    unattributed = 0
    for t, parent, child in clones:
        if child in lines_by_pid:
            stack = lines_by_pid[child][0][1]
        else:
            stack = None
            q = parent
            while q is not None and stack is None:
                if q in times:
                    i = bisect.bisect_right(times[q], t) - 1
                    if i >= 0:
                        stack = lines_by_pid[q][i][1]
                q = None
            if stack is None:
                unattributed += 1
                stack = '?'
        stack_of[child] = stack
    inclusive = collections.Counter()
    self_c = collections.Counter()
    tools = collections.Counter()
    for t, parent, child in clones:
        stack = stack_of[child].split()
        self_c[stack[0] if stack else 'main'] += 1
        for fn in set(stack) or {'main'}:
            inclusive[fn] += 1
        tools[execs.get(child, '(subshell)')] += 1
    return {'processes': len(clones), 'unattributed': unattributed,
            'inclusive': inclusive.most_common(40), 'self': self_c.most_common(40),
            'tools': tools.most_common(25)}


def main():
    want = sys.argv[1:] or ['cold', 'change', 'repeat', 'off']
    out = {}
    with LiveFixture() as f:
        f.install_console()
        src = f.console_path.read_text()
        first, rest = src.split('\n', 1)
        f.console_path.write_text(first + '\n' + INJECT + rest)
        r = f.console('service', 'off', 'svc')
        assert r.returncode == 0, (r.stdout, r.stderr)
        shutil.rmtree(f.live)
        plan = [('cold', ('service', 'on', 'svc', 'Wireguard1')),
                ('change', ('service', 'on', 'svc', 'Wireguard0')),
                ('repeat', ('service', 'on', 'svc', 'Wireguard0')),
                ('off', ('service', 'off', 'svc'))]
        for kind, args in plan:
            p, prof, reads, ndm = request(f, kind, *args)
            last = (p.stdout.strip().splitlines() or [''])[-1]
            if kind in want:
                out[kind] = {'rc': p.returncode, 'result': last, 'show_running_config': reads,
                             'ndmc_calls': ndm, **prof}
            if p.returncode != 0:
                out[kind + '_stderr'] = p.stderr[-2000:]
                break
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()


if __name__ == '__main__':
    main()
