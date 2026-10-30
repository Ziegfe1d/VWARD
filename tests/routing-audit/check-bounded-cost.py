#!/usr/bin/env python3
"""Bounded host regression for repeated subtree evidence; no live router input."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument('--busybox', required=True, help='Existing host BusyBox executable')
args = parser.parse_args()
busybox = str(Path(args.busybox).resolve())
root = Path(__file__).resolve().parents[2]
lib = root / 'components/runtime/lib/vward-routing-audit.sh'

with tempfile.TemporaryDirectory(prefix='vward-audit-cost-') as tmp:
    tmp = Path(tmp)
    (tmp / 'awk').symlink_to(busybox)
    refs = [f's{i:03d}' for i in range(128)]
    children = [f'child.c{i:03d}.x.example' for i in range(63)]
    intents = ''.join(f'S\t{ref}\tx.example\tsubtree\tISP\tdefault\t1\n' for ref in refs)
    intents += ''.join(f'A\ta{i:03d}\t{domain}\texact\tISP\tdefault\t0\n' for i, domain in enumerate(children))
    snapshot = 'snapshot\tg1\tknown\nsource\tM\t0\tknown\nsource\tS\t1\tknown\nsource\tA\t0\tknown\nhealth\tDNS\tavailable\nhealth\tAGH\tavailable\n'
    snapshot += ''.join(f'route\tr{i:03d}\tx.example\tsubtree\tISP\tdefault\tmanual\treference\n' for i in range(128))
    intent_path = tmp / 'intents.tsv'
    snapshot_path = tmp / 'snapshot.tsv'
    intent_path.write_text(intents)
    snapshot_path.write_text(snapshot)
    active = ','.join(f'S:{ref}' for ref in refs)
    configured = ','.join(f'r{i:03d}@subtree@ISP@default' for i in range(128))
    rights = ','.join(f'r{i:03d}@manual@reference' for i in range(128))
    expected = ''
    for i, domain in enumerate(children + ['x.example']):
        sources = f'A:a{i:03d}' if domain != 'x.example' else active
        expected += '\t'.join([domain, sources, active, 'subtree@ISP@default', configured, rights,
                               '127', 'covered', 'reuse-existing-coverage', '-', 'g1', 'unknown']) + '\n'
    expected = expected.encode()
    started = time.monotonic()
    proc = subprocess.Popen([busybox, 'ash', '-c', '. "$1"; vward_routing_audit "$2" "$3"',
                             'audit-cost', str(lib), str(intent_path), str(snapshot_path)],
                            env=dict(os.environ, PATH=str(tmp) + ':' + os.environ['PATH']),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise SystemExit('FAIL: 64 domains / 128 intent+route refs exceeded unchanged 3s bound')
    elapsed = time.monotonic() - started
    assert proc.returncode == 0, (proc.returncode, stderr.decode())
    assert stderr == b'', stderr
    assert stdout == expected, 'Detailed evidence bytes or semantic verdict differ'
    assert len(stdout) == 449454
    assert len(stdout.splitlines()) == 64
    assert intent_path.read_text() == intents and snapshot_path.read_text() == snapshot
    print(f'ROUTING_AUDIT_BOUNDED_COST=PASS domains=64 refs=128 bytes={len(stdout)} elapsed={elapsed:.3f}s limit=3s')
