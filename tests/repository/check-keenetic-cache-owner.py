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
    # Deterministic ABA: a delayed reaper observes the old lease, removes the
    # next reader's empty directory, and publishes its own before that reader
    # resumes. Both clients must still share one completed configuration read.
    (t / 'kc/running-config').unlink(); (t / 'reads').unlink()
    (t / 'kc/lock').mkdir()
    (t / f'kc/lock/owner.{dead.pid}').write_text('old\n')
    (t / 'ndmc').write_text('#!/bin/sh\necho read >> "$T/reads"\ntouch "$T/read-started"\nsleep 0.5\necho dns-proxy\necho "!"\n')
    barriers = f'''
mkdir() {{
 command mkdir "$@"; mb_rc=$?
 if [ "$mb_rc" = 0 ] && [ "$1" = "$VWARD_KCACHE/lock" ] && [ "$CLIENT" = A ]; then
   touch "$T/A-empty"
   while [ ! -e "$T/read-started" ]; do sleep 0.01; done
 fi
 return "$mb_rc"
}}
rm() {{
 if [ "$CLIENT" = B ] && [ "${{2:-}}" = "$VWARD_KCACHE/lock/owner.{dead.pid}" ]; then
   touch "$T/B-observed"
   while [ ! -e "$T/A-empty" ]; do sleep 0.01; done
 fi
 command rm "$@"
}}
'''
    env.pop('DELAY', None)
    b = subprocess.Popen(['sh', '-c', barriers + base], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         env=env | {'CLIENT': 'B'})
    deadline = time.monotonic() + 3
    while not (t / 'B-observed').exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert (t / 'B-observed').exists(), 'reaper barrier not reached'
    a = subprocess.Popen(['sh', '-c', barriers + base], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         env=env | {'CLIENT': 'A'})
    for proc in (a, b):
        out, err = proc.communicate(timeout=6)
        assert proc.returncode == 0 and out == b'dns-proxy\n!\n', (out, err)
    assert (t / 'reads').read_text().splitlines() == ['read'], 'CACHE_OWNER=FAIL: ABA published two simultaneous readers'
print('CACHE_OWNER=PASS')
