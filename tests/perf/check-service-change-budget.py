#!/usr/bin/env python3
"""Process budget per service-change request type (CI gate, fixtures only).

On Keenetic every fork+exec costs ~10 ms (owner measurement, BusyBox 1.37):
processes, not CPU, set the time of a Panel request. This gate counts the
processes ONE request of each type creates through the actual copied console
closure (NDMC fixture, never a router) and fails when any type exceeds its
budget in service-change-budget.json, so growth cannot return unnoticed.

Count: with strace available, the exact number of fork/vfork/clone calls of the
request's process tree (deterministic); otherwise the kernel PID counter delta
(/proc/loadavg field 5), an upper bound on an idle host. Budgets are the
measured values of this HEAD plus a small margin; the owner's targets are
recorded next to them and are NOT yet met (see docs/AGENT.md).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'routing-readers'))
from live_fixture import LiveFixture, SHELL  # noqa: E402

BUDGET = json.loads((HERE / 'service-change-budget.json').read_text())
STRACE = shutil.which('strace') if os.environ.get('VWARD_BUDGET_NO_STRACE') != '1' else None
FORK = re.compile(r'^\d+\s+(?:clone|clone3|fork|vfork)\(')


def last_pid():
    with open('/proc/loadavg') as f:
        return int(f.read().split()[4])


def request(f, *args):
    env = f.env | {'VWARD_DEVICE_CONFIG_OWNER_UID': str(os.getuid()),
                   'VWARD_CONSOLE_EDIT_LOCK': str(f.prefix/'tmp/vward-console-edit.lock'),
                   'VWARD_ROUTE_CHANGE_LOCK': str(f.prefix/'tmp/vward-route-change.lock'),
                   'VWARD_CONSOLE_AUDIT_LOG': str(f.p/'console-audit')}
    cmd = [*SHELL, str(f.console_path), *args]
    t0 = time.monotonic()
    if STRACE:
        log = f.p / 'budget.strace'
        p = subprocess.run([STRACE, '-f', '-qq', '--seccomp-bpf', '-e', 'trace=clone,clone3,fork,vfork', '-o', str(log), *cmd],
                           env=env, text=True, capture_output=True, timeout=600)
        n = sum(1 for line in log.read_text(errors='replace').splitlines() if FORK.match(line))
        log.unlink()
    else:
        before = last_pid()
        p = subprocess.run(cmd, env=env, text=True, capture_output=True, timeout=600)
        after = last_pid()
        with open('/proc/sys/kernel/pid_max') as fh:
            pid_max = int(fh.read())
        n = (after - before if after >= before else after + pid_max - before) - 1
    last = (p.stdout.strip().splitlines() or [''])[-1]
    return {'rc': p.returncode, 'result': last, 'processes': n, 'wall_s': round(time.monotonic() - t0, 1)}


def main():
    out = {'counter': 'strace' if STRACE else 'pid-delta', 'shell': ' '.join(SHELL)}
    with LiveFixture() as f:
        f.install_console()
        if os.environ.get('RS6_BUSYBOX'):
            (f.p/'poison/mv').symlink_to(os.environ['RS6_BUSYBOX'])
        r = f.console('service', 'off', 'svc')
        assert r.returncode == 0, (r.stdout, r.stderr)
        shutil.rmtree(f.live)
        out['cold'] = request(f, 'service', 'on', 'svc', 'Wireguard1')
        out['change'] = request(f, 'service', 'on', 'svc', 'Wireguard0')
        out['repeat'] = request(f, 'service', 'on', 'svc', 'Wireguard0')
        out['off'] = request(f, 'service', 'off', 'svc')
    want = {'cold': 'result=changed', 'change': 'result=changed', 'repeat': 'result=unchanged', 'off': 'result=changed'}
    bad = []
    for kind, expect in want.items():
        got = out[kind]
        limit = BUDGET['budget'][kind]
        if got['rc'] != 0 or got['result'] != expect:
            bad.append(f"{kind}: rc={got['rc']} result={got['result']!r}, expected {expect}")
        elif got['processes'] > limit:
            bad.append(f"{kind}: {got['processes']} processes > budget {limit} (owner target {BUDGET['target'][kind]})")
    print(json.dumps(out, ensure_ascii=False))
    if bad:
        print('SERVICE_CHANGE_BUDGET=FAIL ' + '; '.join(bad))
        return 1
    print('SERVICE_CHANGE_BUDGET=PASS ' + ', '.join(
        f"{k} {out[k]['processes']}/{BUDGET['budget'][k]}" for k in want))
    return 0


if __name__ == '__main__':
    sys.exit(main())
