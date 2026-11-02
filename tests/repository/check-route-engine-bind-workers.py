#!/usr/bin/env python3
"""Real shell process regression: DNS binding workers stay children of Live.

The old double fork yields ppid=1 with the engine argv, briefly or beyond
S91's two-second recheck. Neither is another engine. A real second engine
must still count. No router commands are executed.
"""
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = (ROOT / 'components/route-engine/scripts/vward-route-engine.sh').read_text()
S91 = (ROOT / 'components/runtime/init.d/S91vward-route-engine').read_text()


def fn(src, name):
    m = re.search(r'^' + name + r'\(\)\n\{\n.*?^\}\n', src, re.M | re.S)
    return m.group(0) if m else ''


def pids(path):
    result = {}
    for entry in Path('/proc').glob('[0-9]*'):
        try:
            if str(path).encode() in (entry / 'cmdline').read_bytes().split(b'\0'):
                fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
                result[int(entry.name)] = (fields[0], int(fields[1]))
        except (OSError, IndexError):
            pass
    return result


def count(rows):
    live = 'adaptive_live_pids() { printf "%s\\n" ' + ' '.join(map(str, rows)) + '; }\n'
    return subprocess.check_output(['sh', '-c', live + fn(S91, 'adaptive_core_count') + 'adaptive_core_count'], text=True).strip()


shells = [['sh']] + ([[shutil.which('busybox'), 'ash']] if shutil.which('busybox') else [])
errors = []
for shell in shells:
    for delay in (0.5, 3.5):
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            script = t / 'engine.sh'
            body = f'''HOST_TAGS=M
VWARD_DNS_SERVER=192.0.2.1
valid_fqdn() {{ return 0; }}
refresh_sets() {{ :; }}
classifier_check() {{ :; }}
classify_host() {{ echo M; }}
list_watch_check() {{ :; }}
agh_bind() {{ AB_REPLY=$(sleep {delay}; echo ok); }}
nslookup() {{ :; }}
{fn(ENGINE, 'agh_bind_start')}
{fn(ENGINE, 'agh_bind_stop')}
{fn(ENGINE, 'handle_host')}
handle_host example.org
touch '{t}/ready'
while [ ! -f '{t}/stop' ]; do sleep 0.1; done
{('agh_bind_stop' if fn(ENGINE, 'agh_bind_stop') else ':')}
'''
            script.write_text(body)
            with (t / 'out').open('w') as out:
                main = subprocess.Popen(shell + [str(script)], stdout=out, stderr=out, start_new_session=True)
                other = None
                try:
                    deadline = time.monotonic() + 4
                    while not (t / 'ready').exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    assert (t / 'ready').exists(), (t / 'out').read_text()
                    initial = pids(script)
                    workers = {p: v for p, v in initial.items() if p != main.pid}
                    assert workers, 'fixture did not start the real binding worker'
                    c1 = count(initial)
                    time.sleep(2.05)
                    c2 = count(pids(script))
                    if c1 != '1' or c2 != '1' or any(v[1] not in initial for v in workers.values()):
                        errors.append(f'{shell} bind={delay}s cores={c1}->{c2} processes={initial}; DNS worker orphaned')
                    # Real independent shell with the same engine argv remains a duplicate.
                    other = subprocess.Popen(shell + [str(script)], stdout=out, stderr=out, start_new_session=True)
                    time.sleep(0.1)
                    assert int(count(pids(script))) >= 2, 'real independent engine was hidden'
                    os.killpg(other.pid, signal.SIGKILL)
                    other.wait()
                    other = None
                    (t / 'stop').touch()
                    main.wait(timeout=5)
                    left = {p: v for p, v in pids(script).items() if v[0] != 'Z'}
                    if left:
                        errors.append(f'worker left after engine cleanup: {left}')
                finally:
                    for proc in (main, other):
                        if proc:
                            try:
                                os.killpg(proc.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            proc.wait()
if errors:
    raise SystemExit('BIND_WORKERS=FAIL: ' + '\n'.join(errors))
print('BIND_WORKERS=PASS')
