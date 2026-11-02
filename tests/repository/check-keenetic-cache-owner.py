#!/usr/bin/env python3
"""A killed shared-config reader must not impose the old 35s wait on restart."""
import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = (ROOT / 'components/runtime/lib/vward-device-profile.sh').read_text()
code = ''.join(re.search(r'^' + n + r'\(\)\n\{\n.*?^\}\n', SRC, re.M | re.S).group(0)
               for n in ('_vward_kc_fresh', 'vward_keenetic_config'))
with tempfile.TemporaryDirectory() as td:
    t = Path(td)
    (t / 'kc/lock').mkdir(parents=True)
    dead = subprocess.Popen(['sleep', '30'])
    dead.kill(); dead.wait()
    (t / f'kc/lock/owner.{dead.pid}').write_text(str(dead.pid) + '\n')
    (t / 'ndmc').write_text('#!/bin/sh\necho read >> "$T/reads"\nsleep "${DELAY:-0}"\necho "dns-proxy"\necho "!"\n')
    (t / 'ndmc').chmod(0o755)
    base = f'''VWARD_KCACHE='{t}/kc'; _VWARD_KCACHE_OWN=1; VWARD_NDMC='{t}/ndmc'
vward_uptime_cs() {{ _VCS=0; }}
vward_keenetic_timed() {{ :; }}
{code}
vward_keenetic_config
'''
    env = dict(os.environ, T=td)
    start = time.monotonic()
    p = subprocess.Popen(['sh', '-c', base], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         env=env, start_new_session=True)
    try:
        out, err = p.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL); p.communicate()
        raise SystemExit('CACHE_OWNER=FAIL: dead reader still blocks the next startup (old wait: 35s)')
    assert p.returncode == 0 and out == b'dns-proxy\n!\n', (out, err)
    assert time.monotonic() - start < 2
    assert not (t / 'kc/lock').exists(), 'owner did not release the lock'
    # Two real concurrent clients still share ONE read; a live owner cannot be stolen.
    (t / 'kc/running-config').unlink()
    (t / 'reads').unlink()
    env['DELAY'] = '2'
    p = subprocess.Popen(['sh', '-c', base], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    deadline = time.monotonic() + 3
    while not (t / 'reads').exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    q = subprocess.Popen(['sh', '-c', base], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    for proc in (p, q):
        out, err = proc.communicate(timeout=6)
        assert proc.returncode == 0 and out == b'dns-proxy\n!\n', (out, err)
    assert (t / 'reads').read_text().splitlines() == ['read'], 'live lock stolen / repeated ndmc'
print('CACHE_OWNER=PASS')
