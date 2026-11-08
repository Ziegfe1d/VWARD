#!/usr/bin/env python3
"""One journal lock per request (owner decision 08.11.2026): vrj2_hold/borrow.

The coordinator holds the elected journal lock in its own process. Only a
DESCENDANT of the live holder may borrow it; a foreign process (also one that
forges the holder variables) and an orphan whose holder died are refused; a
dead holder leaves an ordinary stale lock that the existing election reclaims.
Runs under the shell of the fixture (sh, or BusyBox ash with RS6_BUSYBOX).
"""
import os
import signal
import subprocess
import time
from fixture import PipelineFixture, SHELL

with PipelineFixture() as f:
    j = f.j
    lock = j/'.lock'

    # 1. Holder borrows to its child; foreign/forged/orphan refused.
    holder = f.p/'holder.out'
    script = f.script('''
vrj2_hold "$1" || { echo hold-failed; exit 1; }
echo "held $vrj2_hme"
( vrj2_lock "$1" && echo child-borrowed && vrj2_unlock "$1" && echo child-released ) || echo child-refused
# The lock is still the holder's after the child's unlock.
[ "$(cut -f1 "$1/.lock/owner")" = "$vrj2_hme" ] && echo still-held
# Orphan: waits for the holder to die, then tries to borrow.
( while kill -0 "$vrj2_hme" 2>/dev/null; do sleep 0.05; done
  if vrj2_lock "$1"; then echo orphan-borrowed > "$2"; else echo orphan-refused > "$2"; fi ) &
echo ready
while :; do sleep 1; done
''')
    p = subprocess.Popen(SHELL + ['-c', script, 'x', *map(str, f.libs), str(j), str(f.p/'orphan')],
                         env=f.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    out = []
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        line = p.stdout.readline().strip()
        if not line:
            continue
        out.append(line)
        if line == 'ready':
            break
    assert out[0].startswith('held '), out
    hpid = out[0].split()[1]
    assert 'child-borrowed' in out and 'child-released' in out and 'still-held' in out, out

    # Foreign process: no hold variables -> ordinary election sees a live owner.
    r = f.run(f.script('vrj2_lock "$1"; echo "rc=$?"'), *f.libs, j, env=f.env, timeout=30)
    assert r.stdout.strip().endswith('rc=75'), ('foreign process took a held journal lock', r.stdout, r.stderr)
    # Forged holder variables in a non-descendant process.
    forged = f.script('vrj2_held=$1;vrj2_hme=$2;vrj2_hstart=$(vrj2_pid_start "$2");IFS= read -r vrj2_hboot < /proc/sys/kernel/random/boot_id;'
                      'vrj2_lock "$1"; echo "rc=$?"')
    r = f.run(forged, *f.libs, j, hpid, env=f.env, timeout=30)
    assert r.stdout.strip().endswith('rc=75'), ('forged holder variables borrowed the lock', r.stdout, r.stderr)

    # 2. Holder dies: the orphan is refused, the stale lock is reclaimed.
    os.kill(int(hpid), signal.SIGKILL)
    if int(hpid) == p.pid:
        p.wait()  # reap: a zombie holder would still answer kill -0
    deadline = time.monotonic() + 20
    while not (f.p/'orphan').exists() and time.monotonic() < deadline:
        time.sleep(.05)
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    p.poll()
    assert (f.p/'orphan').read_text().strip() == 'orphan-refused', (f.p/'orphan').read_text()
    assert lock.exists(), 'holder death removed the lock'
    r = f.run(f.script('vrj2_lock "$1" && echo taken && vrj2_unlock "$1" && echo released'), *f.libs, j, env=f.env, timeout=30)
    assert 'taken' in r.stdout and 'released' in r.stdout, ('stale held lock not reclaimable', r.stdout, r.stderr)

    # 3. Release by the holder frees the lock for the next coordinator.
    r = f.run(f.script('vrj2_hold "$1" && vrj2_release && echo released;[ ! -e "$1/.lock" ] && echo gone'), *f.libs, j, env=f.env, timeout=30)
    assert 'released' in r.stdout and 'gone' in r.stdout, (r.stdout, r.stderr)
print('JOURNAL_HOLD=PASS child borrows live holder lock; foreign/forged/orphan refused; dead holder lock reclaimed by election; release frees it')
