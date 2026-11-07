#!/usr/bin/env python3
"""Measure ONE service change through the common routing chain (fixtures only).

Reports, per scenario, wall time and the number of processes the request
created. The count is the kernel PID counter delta (/proc/loadavg field 5)
around the request, so it needs no strace and also counts short-lived tools;
it is an upper bound (other host activity adds to it; run on an idle host).

Scenarios: cold (first request, ROOT absent: import + write), change (ROOT
ready, target changes), repeat (same request again: unchanged).

This is a measurement, not a budget: no timeout below 300 s is applied and no
production limit is read or changed. Never touches a real router: the actual
copied console closure runs against the NDMC fixture.

Estimate for a device: time ~= processes x per-process cost on that device.
A per-process cost can be measured READ-ONLY on the device with
    time sh -c 'i=0; while [ $i -lt 500 ]; do /bin/true; i=$((i+1)); done'
(divide by 500); fork+exec of real tools (awk/sha256sum) costs more than true.
"""
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'routing-readers'))
from live_fixture import LiveFixture, SHELL, LIBDIR  # noqa: E402


def last_pid():
    with open('/proc/loadavg') as f:
        return int(f.read().split()[4])


def pid_max():
    with open('/proc/sys/kernel/pid_max') as f:
        return int(f.read())


def measure(f, *args):
    device = f.etc/'device.conf'
    env = f.env | {'VWARD_PROFILE_LIB': f.env['VWARD_PROFILE_LIB'],
                   'VWARD_ADMISSION_LIB': f.env['VWARD_ADMISSION_LIB'],
                   'VWARD_DEVICE_CONFIG_OWNER_UID': str(os.getuid()),
                   'VWARD_CONSOLE_EDIT_LOCK': str(f.prefix/'tmp/vward-console-edit.lock'),
                   'VWARD_ROUTE_CHANGE_LOCK': str(f.prefix/'tmp/vward-route-change.lock'),
                   'VWARD_CONSOLE_AUDIT_LOG': str(f.p/'console-audit')}
    assert device.exists()
    before = last_pid(); t0 = time.monotonic()
    p = subprocess.run([*SHELL, str(f.console_path), *args], env=env, text=True,
                       capture_output=True, timeout=300)
    wall = time.monotonic() - t0; after = last_pid()
    delta = after - before if after >= before else after + pid_max() - before
    return {'rc': p.returncode, 'result': p.stdout.strip().splitlines()[-1:] or [''],
            'wall_s': round(wall, 1), 'processes': delta - 1}


def main():
    out = {'shell': ' '.join(SHELL), 'cpus': os.cpu_count()}
    with LiveFixture() as f:
        f.install_console()
        if os.environ.get('RS6_BUSYBOX'):
            (f.p/'poison/mv').symlink_to(os.environ['RS6_BUSYBOX'])
        r = f.console('service', 'off', 'svc')  # valid device profile, no route
        assert r.returncode == 0, (r.stdout, r.stderr)
        shutil.rmtree(f.live)
        out['cold'] = measure(f, 'service', 'on', 'svc', 'Wireguard1')
        out['change'] = measure(f, 'service', 'on', 'svc', 'Wireguard0')
        out['repeat'] = measure(f, 'service', 'on', 'svc', 'Wireguard0')
    print(json.dumps(out, ensure_ascii=False))
    ok = all(out[k]['rc'] == 0 for k in ('cold', 'change', 'repeat'))
    print('MEASURE_SERVICE_CHANGE=' + ('DONE' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
