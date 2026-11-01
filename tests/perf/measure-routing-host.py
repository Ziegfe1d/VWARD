#!/usr/bin/env python3
"""Bounded routing hot-path measurements; synthetic transport, no router access.

Extract production functions exactly, relocate the membership temporary path, and
run them with BusyBox applets. Separate instrumented accounting from uninstrumented
wait4 CPU/RSS measurements. This is an opt-in diagnostic, not a resource-budget gate.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    'sync': 'components/policy-sync/scripts/vward-policy-sync.sh',
    'policy': 'components/policy-sync/scripts/vward-policy-reconcile.sh',
    'adaptive': 'components/route-reconciler/scripts/vward-route-reconciler.sh',
    'profile': 'components/runtime/lib/vward-device-profile.sh',
}
CASES = ('policy-sync-noop', 'policy-membership', 'adaptive-fresh', 'adaptive-cached')


def extract_function(source, name):
    matches = list(re.finditer(r'^' + re.escape(name) + r'\(\)\s*\n?\{\n.*?^\}\n',
                               source, re.M | re.S))
    if len(matches) != 1:
        raise ValueError(f'expected one production function {name}, got {len(matches)}')
    return matches[0].group()


def validate_bounds(sizes, repeats, timeout):
    if not 1 <= len(sizes) <= 4 or any(not 1 <= n <= 2000 for n in sizes):
        raise ValueError('one to four sizes, each between 1 and 2000 required')
    if not 1 <= repeats <= 5 or not 1 <= timeout <= 60:
        raise ValueError('repeats must be 1..5 and timeout 1..60 seconds')


def fixture(size):
    names = [f'n{i:04d}.example' for i in range(size)]
    routes = [f'198.{18 + i // 256}.{i % 256}.0/24' for i in range(size)]
    config = 'interface Wireguard0\n!\ndns-proxy\n    route object-group domain-list0 Wireguard0 auto\n!\n'
    for group in ('domain-list0', 'AdaptiveAuto'):
        config += f'object-group fqdn {group}\n' + ''.join(f'    include {n}\n' for n in names) + '!\n'
    config += ''.join(f'ip route {r[:-3]} 255.255.255.0 Wireguard0 auto\n' for r in routes)
    return config, names, routes


def trace_counts(paths, payload):
    launches, creations, written, executables = 0, 0, 0, Counter()
    prefix = str(payload) + '/'
    for path in paths:
        if path.stat().st_size > 32 * 1024 * 1024:
            raise RuntimeError('trace exceeded 32 MiB per process; reduce input')
        for line in path.read_text().splitlines():
            call = re.match(r'(\w+)\(', line)
            result = re.search(r' = (\d+)(?:\s|$)', line)
            if not call or not result:
                continue
            name, amount = call[1], int(result[1])
            if name in ('execve', 'execveat') and amount == 0:
                match = re.search(r'"([^"\n]+)"', line)
                if match:
                    launches += 1
                    executables[Path(match[1]).name] += 1
            if name in ('clone', 'clone3', 'fork', 'vfork') and amount > 0:
                creations += 1
            if name in ('write', 'writev', 'pwrite64', 'pwritev', 'sendfile', 'copy_file_range', 'splice'):
                # The first fd is the destination except for copy_file_range/splice.
                descriptors = re.findall(r'\d+<([^>]+)>', line)
                index = 1 if name in ('copy_file_range', 'splice') else 0
                if len(descriptors) > index and descriptors[index].startswith(prefix):
                    written += amount
    return {'executable_launches': launches, 'process_creations': creations,
            'workspace_write_bytes': written, 'executables': dict(sorted(executables.items()))}


def shell_functions(key, *names):
    source = (ROOT / SOURCES[key]).read_text()
    return '\n'.join(extract_function(source, name) for name in names)


def prepare(directory, case, size, applets):
    payload = directory / 'payload'
    payload.mkdir()
    work = payload / 'work'
    work.mkdir()
    catalog = payload / 'catalog'
    catalog.mkdir()
    config, names, routes = fixture(size)
    (directory / 'config').write_text(config)
    (directory / 'names').write_text('\n'.join(names) + '\n')
    (catalog / 'sample.cidr').write_text('\n'.join(routes) + '\n')
    (payload / 'owned').write_text('\n'.join(routes) + '\n')
    (payload / 'owned-device').write_text('Wireguard0\n')
    (directory / 'cats').write_text('sample\n')
    q = shlex.quote
    # The only transport is an executable file local to this temporary directory.
    ndmc = directory / 'ndmc'
    ndmc.write_text(f'#!{applets}/ash\n'
                    f'printf "%s\\n" "$*" >> {q(str(directory / "operations"))}\n'
                    'case "$*" in\n'
                    f'    "-c show running-config") cat {q(str(directory / "config"))} ;;\n'
                    '    *) exit 99 ;;\nesac\n')
    ndmc.chmod(0o755)
    script = f'''#!/bin/sh
set -eu
export PATH={q(str(applets))}
MEASURE_TMP={q(str(payload))}
VWARD_NDMC={q(str(ndmc))}
ndmc() {{ "$VWARD_NDMC" "$@"; }}
vward_running_config() {{ ndmc -c 'show running-config'; }}
vward_uptime_cs() {{ _VCS=0; }}
vward_keenetic_timed() {{ :; }}
log() {{ :; }}
ndm() {{ printf 'UNEXPECTED_MUTATION=%s\\n' "$*" >&2; return 99; }}
'''
    if case == 'policy-sync-noop':
        script += shell_functions('sync', 'prefix_mask', 'route_line', 'reconcile_routes')
        for key, value in {'WORK': work, 'CATALOG': catalog, 'OWNED': payload / 'owned',
                           'OWNED_DEVICE': payload / 'owned-device', 'ACTIVE': payload / 'active',
                           'SHRINK_PENDING': payload / 'shrink.pending', 'LAST_GOOD': payload / 'last-good',
                           'LISTS_CONF': payload / 'lists.conf'}.items():
            script += f'{key}={q(str(value))}\n'
        script += f'''RT=Wireguard0
WG=Wireguard0
vward_running_config > "$WORK/running"
reconcile_routes "$WORK/running" {q(str(directory / 'cats'))}
'''
        # reconcile_routes sorts the owned list lexicographically.
        (payload / 'owned').write_text('\n'.join(sorted(routes)) + '\n')
        (catalog / 'sample.cidr').write_text('\n'.join(sorted(routes)) + '\n')
    elif case == 'policy-membership':
        script += shell_functions('policy', 'group_members', 'membership_state').replace(
            '/tmp/vpn-reconcile-verify.$$', '$MEASURE_TMP/vpn-reconcile-verify.$$')
        script += f'''while IFS= read -r name; do
    membership_state domain-list0 "$name" || exit 91
done < {q(str(directory / 'names'))}
printf 'VERIFIED=%s\\n' {size}
'''
    else:
        script += shell_functions('profile', '_vward_kc_fresh', 'vward_keenetic_config')
        script += shell_functions('adaptive', 'adaptive_names')
        script += f'''VWARD_KCACHE="$MEASURE_TMP/cache"
_VWARD_KCACHE_OWN=1
VWARD_KEENETIC_AGE=60
VWARD_RECONCILER_ONE_LOOK={int(case == 'adaptive-cached')}
i=0
while [ "$i" -lt {1 + min(8, size)} ]; do
    adaptive_names
    i=$((i + 1))
done
'''
    (directory / 'run.sh').write_text(script)
    return len(config.encode())


def execute(command, directory, timeout):
    # wait4 reports this command and waited descendants, excluding Python and
    # earlier samples. ru_maxrss is the maximum single-process RSS, not a sum.
    with (directory / 'stdout').open('wb') as out, (directory / 'stderr').open('wb') as err:
        started = time.monotonic()
        child = subprocess.Popen(command, stdout=out, stderr=err, start_new_session=True)
        while True:
            pid, status, usage = os.wait4(child.pid, os.WNOHANG)
            if pid:
                child.returncode = os.waitstatus_to_exitcode(status)
                break
            if time.monotonic() - started > timeout:
                os.killpg(child.pid, signal.SIGKILL)
                os.wait4(child.pid, 0)
                child.returncode = -signal.SIGKILL
                raise RuntimeError(f'sample exceeded {timeout}s')
            time.sleep(0.005)
    if child.returncode:
        raise RuntimeError(f'{command[0]} rc={child.returncode}: ' + (directory / 'stderr').read_text()[-2000:])
    return {'wall_seconds': round(time.monotonic() - started, 6),
            'child_user_seconds': round(usage.ru_utime, 6),
            'child_system_seconds': round(usage.ru_stime, 6),
            'child_maxrss_kib': usage.ru_maxrss}


def workspace_bytes(payload):
    return sum(path.stat().st_size for path in payload.rglob('*') if path.is_file())


def parse_time_rss(value):
    if not value.strip().isdigit() or int(value.strip()) <= 0:
        raise ValueError('BusyBox time did not return a positive RSS value')
    return int(value.strip())


def install_applets(directory, busybox, observations=None):
    directory.mkdir()
    available = subprocess.run([str(busybox), '--list'], capture_output=True, text=True, check=True).stdout.splitlines()
    for name in available:
        path = directory / name
        if observations is None or name == 'ash':
            path.symlink_to(busybox)
        else:
            path.write_text(f'#!{busybox} ash\n'
                            f'printf "%s\\n" {shlex.quote(name)} >> {shlex.quote(str(observations))}\n'
                            f'exec {shlex.quote(str(busybox))} {shlex.quote(name)} "$@"\n')
            path.chmod(0o755)


def sample(base, applets, busybox, strace, accounting, case, size, repeat, timeout):
    data = {'case': case, 'size': size, 'repeat': repeat}
    for mode in ('accounting', 'cost'):
        directory = base / f'{case}-{size}-{repeat}-{mode}'
        directory.mkdir()
        sample_applets = applets
        if mode == 'accounting' and accounting == 'wrappers':
            sample_applets = directory / 'bin'
            install_applets(sample_applets, busybox, directory / 'tools')
        data['config_bytes'] = prepare(directory, case, size, sample_applets)
        before = workspace_bytes(directory / 'payload')
        command = [str(sample_applets / 'ash'), str(directory / 'run.sh')]
        if mode == 'accounting' and accounting == 'strace':
            command = [strace, '-qq', '-ff', '-yy', '-s', '128', '-o', str(directory / 'trace'),
                       '-e', 'trace=process,write,writev,pwrite64,copy_file_range,sendfile,splice', *command]
        if mode == 'cost':
            # A native intermediate launcher prevents the Python fork's inherited
            # RSS high-water mark from dominating the actual workload measurement.
            command = [str(busybox), 'time', '-f', '%M', '-o', str(directory / 'rss'), *command]
        cost = execute(command, directory, timeout)
        stdout = (directory / 'stdout').read_text()
        if case.startswith('adaptive-'):
            expected_names = (directory / 'names').read_text() * (1 + min(8, size))
            if stdout != expected_names:
                raise RuntimeError('adaptive output changed between repeated snapshots')
        if case == 'policy-sync-noop':
            if (directory / 'payload/owned').read_bytes() != (directory / 'payload/catalog/sample.cidr').read_bytes():
                raise RuntimeError('no-op policy reconcile changed ownership')
            if not all(value in stdout.splitlines() for value in ('ADDED=0', 'REMOVED=0', 'ERRORS=0', 'CONFIG_SAVE=NOT_NEEDED')):
                raise RuntimeError('policy reconcile was not a verified no-op')
        operations = (directory / 'operations').read_text().splitlines()
        expected = (size if case == 'policy-membership' else
                    1 + min(8, size) if case == 'adaptive-fresh' else 1)
        if operations != ['-c show running-config'] * expected:
            raise RuntimeError(f'wrong snapshot count or unexpected external operation: {operations[:10]}')
        if mode == 'cost':
            cost['child_maxrss_kib'] = parse_time_rss((directory / 'rss').read_text())
            data.update(cost)
            data['initial_workspace_file_bytes'] = before
            data['final_workspace_file_bytes'] = workspace_bytes(directory / 'payload')
        else:
            if accounting == 'strace':
                data.update(trace_counts(sorted(directory.glob('trace.*')), directory / 'payload'))
            else:
                tools = Counter((directory / 'tools').read_text().splitlines())
                if not tools.get('awk'):
                    raise RuntimeError('BusyBox shell bypassed external applet wrappers')
                data.update({'external_tool_invocations': sum(tools.values()),
                             'tools': dict(sorted(tools.items())),
                             'executable_launches': None, 'process_creations': None,
                             'workspace_write_bytes': None})
            data['snapshot_reads'] = len(operations)
            data['snapshot_response_bytes'] = len(operations) * data['config_bytes']
            data['external_operations'] = {'ndmc': len(operations), 'rci': 0,
                                           'dns_queries': 0, 'probes': 0,
                                           'mutations': 0, 'config_saves': 0}
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--busybox', required=True, type=Path)
    parser.add_argument('--strace', default='/usr/bin/strace')
    parser.add_argument('--accounting', choices=('wrappers', 'strace'), default='wrappers',
                        help='wrappers count tool dispatches; strace also counts exec/process/write syscalls')
    parser.add_argument('--sizes', nargs='+', type=int, default=[8, 300])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--timeout', type=int, default=30, help='per sample, maximum 60 seconds')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    validate_bounds(args.sizes, args.repeats, args.timeout)
    busybox = args.busybox.resolve(strict=True)
    version = subprocess.run([str(busybox)], capture_output=True, text=True, check=False)
    git = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    results = {'schema': 1, 'baseline_commit': git, 'host': {'system': os.uname().sysname,
               'release': os.uname().release, 'machine': os.uname().machine,
               'busybox': (version.stdout + version.stderr).splitlines()[0],
               'busybox_sha256': hashlib.sha256(busybox.read_bytes()).hexdigest()},
               'accounting': args.accounting,
               'source_sha256': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                                 for path in SOURCES.values()},
               'bounds': {'sizes': args.sizes, 'repeats': args.repeats, 'timeout_seconds': args.timeout,
                          'max_samples': len(args.sizes) * args.repeats * len(CASES) * 2},
               'samples': []}
    with tempfile.TemporaryDirectory(prefix='vward-routing-measure.') as td:
        base = Path(td)
        applets = base / 'bin'
        install_applets(applets, busybox)
        for repeat in range(1, args.repeats + 1):
            # Alternate order; no warm-up or repeated growing workload.
            sizes = args.sizes if repeat % 2 else list(reversed(args.sizes))
            cases = CASES if repeat % 2 else tuple(reversed(CASES))
            for size in sizes:
                for case in cases:
                    results['samples'].append(sample(base, applets, busybox, args.strace, args.accounting,
                                                     case, size, repeat, args.timeout))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, sort_keys=True) + '\n')
    print(f'ROUTING_HOST_MEASUREMENTS=PASS samples={len(results["samples"])} output={args.output}')


if __name__ == '__main__':
    main()
