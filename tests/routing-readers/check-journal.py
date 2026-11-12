#!/usr/bin/env python3
"""RS-7 stage 2: write-ahead journal on TEST DATA only (no writer is connected).

PLAN -> PENDING (before any mutation) -> DONE / FAILED / UNKNOWN, evidence-based recovery
after TERM, SIGKILL, reboot, disk/write faults and a lost API reply; no replay; an
unresolved operation closes the gate for every new one.
"""
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture import *

GEN = 'g-0123456789abcdef'
ROW = f'new.example\tadd\tVPN:Wireguard0\tdefault\tyes\tdenied:writers-disabled\trecheck-generation,owner-proof,change-lock,journal-before-write\tnew-coverage-needed\t{GEN}\n'

def mk(base, name):
    d = base/name; d.mkdir(mode=0o700); return d

with Fixture() as f:
    shim = f.p/'shim'; shim.mkdir(); trace = f.p/'trace'
    for name in ('ndmc', 'curl', 'ip', 'wg', 'vward-console-config.sh', 'vward-ads-privacy-control.sh'):
        (shim/name).write_text(f'#!/bin/sh\necho {name} >> {trace}\nexit 99\n'); (shim/name).chmod(0o755)
    env = dict(f.env, PATH=str(shim) + ':' + os.environ['PATH'], VWARD_JOURNAL_SYNC='1')
    J = lambda *a, env_=env: f.run('. "$1"; shift; "$@"', JOURNAL, *a, env=env_)
    planf = f.p/'plan.tsv'; planf.write_text(ROW)
    pre = f.p/'pre.img'; pre.write_text('object-group fqdn Mine\n    include a.example\n!\n')
    post = f.p/'post.img'; post.write_text('object-group fqdn Mine\n    include a.example\n    include new.example\n!\n')
    other = f.p/'other.img'; other.write_text('object-group fqdn Mine\n    include user-edit.example\n!\n')

    def status(j):
        r = J('vward_journal_status', j); assert r.returncode == 0, r.stderr
        return {l.split('\t')[0]: l.split('\t')[1:] for l in r.stdout.splitlines()}

    def planned(j, op='op-1', owner='vward', ident='verified', row=None):
        if row is not None: planf.write_text(row)
        r = J('vward_journal_plan', j, op, planf, 'new.example', 'S', owner, ident)
        planf.write_text(ROW)
        return r

    # ---- happy path: plan -> pending -> done (by evidence) -----------------------------------
    j = mk(f.p, 'j1')
    assert planned(j).returncode == 0
    assert status(j) == {'op-1': ['plan', 'new-coverage-needed']}
    assert J('vward_journal_gate', j).returncode == 0                       # a plan alone does not block
    rec = (j/'op-1/plan').read_text()
    for k in ('opid=op-1', f'generation={GEN}', 'source=S', 'owner=vward', 'identity=verified', 'action=add',
              'domain=new.example', 'target=VPN:Wireguard0', 'dns=default', 'eligible=yes', 'reason=new-coverage-needed'):
        assert k in rec, k
    assert oct((j/'op-1').stat().st_mode & 0o777) == '0o700' and oct((j/'op-1/plan').stat().st_mode & 0o777) == '0o600'
    r = J('vward_journal_begin', j, 'op-1', GEN, pre, post, 'owner-proof,generation'); assert r.returncode == 0, r.stderr
    assert status(j)['op-1'][0] == 'pending' and (j/'op-1/pre').read_text() == pre.read_text()
    assert J('vward_journal_gate', j).returncode == 75                      # PENDING blocks everything new
    assert J('vward_journal_finish', j, 'op-1', post).returncode == 0
    assert status(j)['op-1'] == ['done', 'verified'] and J('vward_journal_gate', j).returncode == 0
    # ---- no replay: a used id never begins again, in any state --------------------------------
    assert J('vward_journal_begin', j, 'op-1', GEN, pre, post, 'x').returncode == 75
    assert planned(j).returncode == 75
    assert J('vward_journal_finish', j, 'op-1', post).returncode == 75

    # ---- begin refuses unsound / foreign / stale plans -------------------------------------------
    j = mk(f.p, 'j2')
    for op, kw, why in (('o-ref', dict(ident='reference-only'), 'name only'), ('o-unk', dict(ident='unknown'), 'unknown identity'),
                        ('o-man', dict(owner='manual'), 'manual rule'), ('o-uo', dict(owner='unknown'), 'unknown owner'),
                        ('o-no', dict(row=ROW.replace('\tyes\t', '\tno\t').replace('new-coverage-needed', 'service-target-defaulted')), 'vpn substitution'),
                        ('o-wild', dict(row=ROW.replace('\tadd\t', '\tnone\t').replace('\tyes\t', '\tno\t').replace('new-coverage-needed', 'domain-not-in-snapshot')), 'wildcard')):
        assert planned(j, op, **kw).returncode == 0, op
        assert J('vward_journal_begin', j, op, GEN, pre, post, 'c').returncode == 75, why
        assert not (j/op/'pending').exists()
    assert planned(j, 'o-gen').returncode == 0
    assert J('vward_journal_begin', j, 'o-gen', 'g-ffffffffffffffff', pre, post, 'c').returncode == 75   # snapshot changed
    assert J('vward_journal_begin', j, 'o-gen', GEN, pre, pre, 'c').returncode == 75                     # nothing to change
    assert J('vward_journal_begin', j, 'missing', GEN, pre, post, 'c').returncode == 75                  # no plan
    assert J('vward_journal_gate', j).returncode == 0

    # ---- lost API reply: unknown, gate closed, evidence resolves (never a retry) ----------------------
    j = mk(f.p, 'j3')
    assert planned(j).returncode == 0 and J('vward_journal_begin', j, 'op-1', GEN, pre, post, 'c').returncode == 0
    assert J('vward_journal_unknown', j, 'op-1', 'lost-reply').returncode == 0
    assert status(j)['op-1'] == ['unknown', 'lost-reply'] and J('vward_journal_gate', j).returncode == 75
    assert planned(j, 'op-2').returncode == 0
    assert J('vward_journal_begin', j, 'op-2', GEN, pre, post, 'c').returncode == 75, 'new op while unknown'
    cur = f.p/'cur'; cur.mkdir()
    (cur/'op-1').write_text(other.read_text())                               # someone else changed it meanwhile
    assert J('vward_journal_recover', j, cur).returncode == 0
    assert status(j)['op-1'] == ['unknown', 'lost-reply'] and J('vward_journal_gate', j).returncode == 75  # stays blocked
    (cur/'op-1').write_text(post.read_text())                                # the POST had been applied
    assert J('vward_journal_recover', j, cur).returncode == 0
    assert status(j)['op-1'] == ['done', 'confirmed-after-restart'] and J('vward_journal_gate', j).returncode == 0
    assert J('vward_journal_begin', j, 'op-2', GEN, pre, post, 'c').returncode == 0                       # gate open again

    # ---- finish by evidence: not applied -> failed; foreign change -> unknown (no blind restore) -------
    j = mk(f.p, 'j4')
    assert planned(j).returncode == 0 and J('vward_journal_begin', j, 'op-1', GEN, pre, post, 'c').returncode == 0
    assert J('vward_journal_finish', j, 'op-1', pre).returncode == 0 and status(j)['op-1'] == ['failed', 'not-applied']
    j = mk(f.p, 'j5')
    assert planned(j).returncode == 0 and J('vward_journal_begin', j, 'op-1', GEN, pre, post, 'c').returncode == 0
    assert J('vward_journal_finish', j, 'op-1', other).returncode == 0 and status(j)['op-1'] == ['unknown', 'state-differs']
    assert (j/'op-1/pre').read_text() == pre.read_text()                     # private evidence kept for the owner
    assert J('vward_journal_finish', j, 'op-1', f.p/'nothing').returncode == 75

    # ---- SIGKILL / TERM / reboot: a writer killed after PENDING -> recovered from evidence ------------
    for sig, current, want in ((signal.SIGKILL, pre, ['failed', 'not-applied']), (signal.SIGTERM, post, ['done', 'confirmed-after-restart']),
                               (signal.SIGKILL, other, ['unknown', 'state-differs']), (signal.SIGKILL, None, ['unknown', 'current-unavailable'])):
        j = mk(f.p, f'jk{sig}{want[0]}{current is None}')
        assert planned(j).returncode == 0
        writer = f'''. "{JOURNAL}"
        vward_journal_begin "$1" op-1 {GEN} "$2" "$3" c || exit 9
        echo started > "$1/started"; sleep 30'''
        p = subprocess.Popen([*SHELL, '-c', writer, 'w', str(j), str(pre), str(post)], env=env)
        for _ in range(100):
            if (j/'started').exists(): break
            time.sleep(0.05)
        assert (j/'started').exists(); os.kill(p.pid, sig); p.wait()
        assert status(j)['op-1'][0] == 'pending' and J('vward_journal_gate', j).returncode == 75
        cur = f.p/f'cur{sig}{want[0]}{current is None}'; cur.mkdir()
        if current is not None: (cur/'op-1').write_text(current.read_text())
        assert J('vward_journal_recover', j, cur).returncode == 0                # "after reboot": a new process
        assert status(j)['op-1'] == want, (sig, status(j))
        assert J('vward_journal_gate', j).returncode == (75 if want[0] == 'unknown' else 0)

    # ---- killed in the middle of writing a record: previous state stays, tmp ignored/cleaned -----------
    j = mk(f.p, 'j6')
    assert planned(j).returncode == 0
    (j/'op-1/pending.tmp.12345').write_text('record=pend')                   # a torn write never renamed
    assert status(j)['op-1'][0] == 'plan' and J('vward_journal_gate', j).returncode == 0
    assert J('vward_journal_recover', j, f.p).returncode == 0 and not (j/'op-1/pending.tmp.12345').exists()

    # ---- disk / write fault: no PENDING -> the caller must not mutate ---------------------------------
    j = mk(f.p, 'j7')
    assert planned(j).returncode == 0
    # The tmp name is pending.tmp.<pid>: make every rename target fail by turning "pending" into a directory.
    (j/'op-1/pending').mkdir()
    mutated = f.p/'mutated'
    r = f.run(f'. "{JOURNAL}"; if vward_journal_begin "$1" op-1 {GEN} "$2" "$3" c; then echo yes > "$4"; fi; exit 0', j, pre, post, mutated, env=env)
    assert not mutated.exists(), 'mutation ran although the journal write failed'
    (j/'op-1/pending').rmdir()
    assert status(j)['op-1'][0] == 'plan' and not (j/'op-1/pre').exists()
    # A failure to finish leaves PENDING (never a false DONE), recover settles it later.
    assert J('vward_journal_begin', j, 'op-1', GEN, pre, post, 'c').returncode == 0
    (j/'op-1/done').mkdir()                                                   # DONE cannot be written
    r = J('vward_journal_finish', j, 'op-1', post)
    assert r.returncode in (1, 75) and status(j)['op-1'][0] in ('pending', 'unknown'), (r.returncode, status(j))
    assert J('vward_journal_gate', j).returncode == 75                        # never a false DONE
    (j/'op-1/done').rmdir()
    assert J('vward_journal_finish', j, 'op-1', post).returncode == 0 and status(j)['op-1'][0] == 'done'

    # ---- corrupt / forged records: unknown, gate closed --------------------------------------------------
    j = mk(f.p, 'j8')
    assert planned(j).returncode == 0 and J('vward_journal_begin', j, 'op-1', GEN, pre, post, 'c').returncode == 0
    (j/'op-1/done').write_text('record=done\nopid=op-1\nreason=$(reboot)\n')     # not a token
    assert status(j)['op-1'][0] == 'unknown' and J('vward_journal_gate', j).returncode == 75
    j = mk(f.p, 'j9')
    assert planned(j).returncode == 0
    (j/'op-1/plan').write_text((j/'op-1/plan').read_text().replace('opid=op-1', 'opid=op-2'))  # moved record
    assert status(j)['op-1'][0] == 'unknown' and J('vward_journal_gate', j).returncode == 75
    j = mk(f.p, 'j10')
    assert planned(j).returncode == 0
    (j/'op-1/done').write_text('record=done\nopid=op-1\nreason=verified\n')       # DONE without PENDING = forged
    assert status(j)['op-1'] == ['unknown', 'terminal-without-pending']
    (j/'bad name').mkdir(mode=0o700)
    assert any(v[0] == 'unknown' for v in status(j).values())

    # ---- races: two writers -> exactly one begins; a dead lock owner does not block forever -----------------
    j = mk(f.p, 'j11')
    assert planned(j, 'op-a').returncode == 0 and planned(j, 'op-b').returncode == 0
    script = f'. "{JOURNAL}"; vward_journal_begin "$1" "$2" {GEN} "$3" "$4" c; echo "rc=$?" > "$1/$2.rc"'
    ps = [subprocess.Popen([*SHELL, '-c', script, 'w', str(j), op, str(pre), str(post)], env=env) for op in ('op-a', 'op-b')]
    for p in ps: p.wait()
    rcs = sorted((j/f'{op}.rc').read_text().strip() for op in ('op-a', 'op-b'))
    assert rcs == ['rc=0', 'rc=75'], rcs                                       # one PENDING, the other refused
    # CI 12.11.2026 (the race above ended rc=1 now and then): an owner seen alive that exits before
    # its stat is read again is a finished owner (1), never «unknown» (2) with a shell error.
    adm = Path(JOURNAL).parent/'vward-runtime-admission.sh'
    r = subprocess.run([*SHELL, '-c', '. "$1"; vward_pid_start_var() { VA_PS=4242; return 0; }; vlg_boot=01234567-89ab-cdef-0123-456789abcdef; '
                        'vward_lock_gate_live "$vlg_boot.999999.4242"', 'w', str(adm)], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and 'stat' not in r.stderr, (r.returncode, r.stderr)
    j = mk(f.p, 'j12'); assert planned(j).returncode == 0
    (j/'.lock').mkdir(); (j/'.lock/pid').write_text('999999\n')                # owner killed (SIGKILL / reboot)
    assert J('vward_journal_begin', j, 'op-1', GEN, pre, post, 'c').returncode == 0
    j = mk(f.p, 'j13'); assert planned(j).returncode == 0
    holder = subprocess.Popen(['sleep', '20'])
    (j/'.lock').mkdir(); (j/'.lock/pid').write_text(f'{holder.pid}\n')        # live owner: busy, not stolen
    assert J('vward_journal_begin', j, 'op-1', GEN, pre, post, 'c').returncode == 75
    holder.kill(); holder.wait()

    # ---- input discipline, secrets, purity ------------------------------------------------------------------
    j = mk(f.p, 'j14')
    assert J('vward_journal_plan', j, 'op x', planf, 'new.example', 'S', 'vward', 'verified').returncode == 2
    assert J('vward_journal_plan', j, 'op-1', planf, 'new.example', 'S', 'root', 'verified').returncode == 2
    planf.write_text(ROW.replace('new-coverage-needed', 'https://dns.example/secret-token'))
    assert J('vward_journal_plan', j, 'op-1', planf, 'new.example', 'S', 'vward', 'verified').returncode == 2
    planf.write_text(ROW + ROW)
    assert J('vward_journal_plan', j, 'op-1', planf, 'new.example', 'S', 'vward', 'verified').returncode == 2   # ambiguous row
    planf.write_text(ROW)
    open_dir = f.p/'open'; open_dir.mkdir(mode=0o755); open_dir.chmod(0o755)
    assert J('vward_journal_plan', open_dir, 'op-1', planf, 'new.example', 'S', 'vward', 'verified').returncode == 2
    assert J('vward_journal_status', 'relative').returncode == 2
    big = f.p/'big.img'; big.write_text('x' * (1024 * 1024 + 1))
    assert planned(j).returncode == 0 and J('vward_journal_begin', j, 'op-1', GEN, big, post, 'c').returncode == 2
    assert J('vward_journal_unknown', j, 'op-1', 'Bad Reason').returncode == 2
    for d in f.p.glob('j*'):
        for rec in d.rglob('*'):
            if rec.is_file(): assert 'secret' not in rec.read_text(errors='ignore')
    assert not trace.exists(), 'journal invoked an executor'
    assert f.run('sentinel=1; . "$1"; [ "$sentinel" = 1 ]', JOURNAL).returncode == 0
print('RS7_JOURNAL=PASS: plan/pending/done/failed/unknown, TERM/SIGKILL/reboot/disk/lost reply, no replay, gate, races, corruption')
