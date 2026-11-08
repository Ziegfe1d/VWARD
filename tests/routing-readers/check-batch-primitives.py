#!/usr/bin/env python3
"""Rewritten batch primitives keep the ORIGINAL verdicts (08.11.2026 pass).

vrb_publish_quiet (one ls + one sha256sum for all leases) and
vrb_dispatch_valid / vrb_dispatch_valid_range (builtin checks, batched
digests) are compared with the c9d39f4 implementations (byte-exact copies in
reference/c9d39f4, loaded under another name in the SAME shell, with the same
helpers) on valid and corrupted lease sets / receipts. sh and BusyBox ash.
The settled-quiet marker is checked separately: it may only shortcut a
terminal operation whose lease set and plan are unchanged.
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fixture import PipelineFixture, function_source  # noqa: E402

REF = HERE/'reference'/'c9d39f4'
SHELLS = [['sh']] + ([['busybox', 'ash']] if shutil.which('busybox') else [])
BOOT = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
OTHER = '00000000-0000-4000-8000-000000000000'
H = lambda b: hashlib.sha256(b).hexdigest()
fails = []


def old(path, name):
    return function_source(path, name).replace(name + '() (', 'old_' + name + '() (', 1)


def lease(d, boot, pid, start, body=None, sha=None, mode=0o600):
    p = d/f'{boot}.{pid}.{start}'
    b = (boot + '\n').encode() if body is None else body
    p.write_bytes(b); p.chmod(mode)
    s = d/(p.name + '.sha')
    s.write_text((H(b) if sha is None else sha) + '\n'); s.chmod(0o600)
    return p


def start_of(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()[19]


with PipelineFixture() as f:
    r = f.invoke('vward_routing_pipeline2', f.j, 'base', 'svc', 'vpn', 'VPN:Wireguard0', 'default', 0)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    oldfns = old(REF/'vward-routing-pipeline.sh', 'vrb_publish_quiet') + old(REF/'vward-routing-dispatch.sh', 'vrb_dispatch_valid')
    me = os.getpid(); mystart = start_of(me)

    # ---- publish_quiet cases: (name, builder(opdir)) ------------------------
    def pq_cases():
        def none(o): pass
        def empty(o): (o/'workers').mkdir(mode=0o700)
        def dead(o): (o/'workers').mkdir(mode=0o700); lease(o/'workers', BOOT, 999999, 1)
        def live(o): (o/'workers').mkdir(mode=0o700); lease(o/'workers', BOOT, me, mystart)
        def nosha(o): dead(o); next((o/'workers').glob('*.sha')).unlink()
        def orphan_sha(o): (o/'workers').mkdir(mode=0o700); (o/'workers'/f'{BOOT}.5.6.sha').write_text(H(b'x') + '\n'); os.chmod(o/'workers'/f'{BOOT}.5.6.sha', 0o600)
        def badsha(o): (o/'workers').mkdir(mode=0o700); lease(o/'workers', BOOT, 999999, 1, sha='0' * 64)
        def otherbody(o): (o/'workers').mkdir(mode=0o700); lease(o/'workers', BOOT, 999999, 1, body=(OTHER + '\n').encode())
        def multiline(o): (o/'workers').mkdir(mode=0o700); lease(o/'workers', BOOT, 999999, 1, body=(BOOT + '\nx\n').encode())
        def mode644(o): (o/'workers').mkdir(mode=0o700); lease(o/'workers', BOOT, 999999, 1, mode=0o644)
        def badname(o): (o/'workers').mkdir(mode=0o700); lease(o/'workers', BOOT, 'x9', 1)
        def otherboot(o): (o/'workers').mkdir(mode=0o700); lease(o/'workers', OTHER, me, mystart)
        def wsym(o): (o.parent/'elsewhere').mkdir(mode=0o700, exist_ok=True); (o/'workers').symlink_to(o.parent/'elsewhere')
        def w755(o): (o/'workers').mkdir(mode=0o755); os.chmod(o/'workers', 0o755)
        def lsym(o): (o/'workers').mkdir(mode=0o700); p = lease(o/'workers', BOOT, 999999, 1); t = o/'target'; p.rename(t); p.symlink_to(t)
        def mixed(o): dead(o); lease(o/'workers', BOOT, me, mystart)
        def nonuuid(o): (o/'workers').mkdir(mode=0o700); lease(o/'workers', 'not-a-uuid', 999999, 1, body=b'not-a-uuid\n')
        return [('none', none), ('empty', empty), ('dead', dead), ('live', live), ('nosha', nosha), ('orphan-sha', orphan_sha),
                ('badsha', badsha), ('other-body', otherbody), ('multiline', multiline), ('mode644', mode644),
                ('badname', badname), ('other-boot', otherboot), ('workers-symlink', wsym), ('workers-0755', w755),
                ('lease-symlink', lsym), ('dead+live', mixed), ('non-uuid', nonuuid)]

    for shell in SHELLS:
        for name, build in pq_cases():
            o = f.p/f'pq-{shell[0]}-{name}'
            o.mkdir(mode=0o700)
            (o/'state').write_text('pending\n'); os.chmod(o/'state', 0o600)
            build(o)
            body = oldfns + 'old_vrb_publish_quiet "$1"; a=$?; vrb_publish_quiet "$1"; b=$?; echo "$a $b"'
            r = subprocess.run(shell + ['-c', f.script(body), 'x', *map(str, f.libs), str(o)], env=f.env,
                               capture_output=True, text=True, timeout=60)
            got = r.stdout.split()
            want = '0' if name in ('none', 'empty', 'dead', 'other-boot') else '75'
            if len(got) != 2 or got[0] != got[1] or got[1] != want:
                fails.append(f'{shell[0]} publish_quiet {name}: old/new {got}, expected {want} {r.stderr[-300:]}')

    # Settled marker: shortcut only for an unchanged terminal operation.
    for shell in SHELLS:
        o = f.p/f'settled-{shell[0]}'; o.mkdir(mode=0o700)
        (o/'state').write_text('committed\n'); os.chmod(o/'state', 0o600)
        (o/'plan.sha').write_text('a' * 64 + '\n'); os.chmod(o/'plan.sha', 0o600)
        (o/'workers').mkdir(mode=0o700); lease(o/'workers', BOOT, 999999, 1)
        mark = 'vrb_quiet_mark "$1"; [ -f "$1/quiet" ] && echo marked'
        r = subprocess.run(shell + ['-c', f.script(mark), 'x', *map(str, f.libs), str(o)], env=f.env, capture_output=True, text=True, timeout=60)
        assert 'marked' in r.stdout, (shell, r.stdout, r.stderr)
        lease(o/'workers', BOOT, me, mystart)  # a new live lease after the marker
        r = subprocess.run(shell + ['-c', f.script('vrb_publish_quiet "$1"; echo "rc=$?"')], env=f.env, capture_output=True, text=True, timeout=60) if False else \
            subprocess.run(shell + ['-c', f.script('vrb_publish_quiet "$1"; echo "rc=$?"'), 'x', *map(str, f.libs), str(o)], env=f.env, capture_output=True, text=True, timeout=60)
        if 'rc=75' not in r.stdout:
            fails.append(f'{shell[0]} settled marker hid a new live lease: {r.stdout}')

    # ---- dispatch_valid cases on a real committed operation ---------------
    src = f.j/'base'
    steps = [l.split('\t') for l in (src/'plan').read_text().splitlines() if l.startswith('step\t')]
    receipts = sorted(src.glob('step.*/dispatched.*[0-9a-f]'))
    assert receipts, 'no receipts in the base operation'

    def dv_cases():
        def ok(o): pass
        # The receipt of step 1's post-image (a group step has one per prefix).
        def first(o): return o/'step.1'/('dispatched.' + steps[0][6])
        def missing(o): first(o).unlink()
        def badsha(o): r = first(o); Path(str(r) + '.sha').write_text('0' * 64 + '\n')
        def extra(o):
            r = first(o); b = r.read_text().rstrip('\n') + '\textra\n'; r.write_text(b); Path(str(r) + '.sha').write_text(H(b.encode()) + '\n')
        def wrongplan(o):
            r = first(o); fields = r.read_text().rstrip('\n').split('\t'); fields[8] = 'b' * 64
            b = '\t'.join(fields) + '\n'; r.write_text(b); Path(str(r) + '.sha').write_text(H(b.encode()) + '\n')
        def mode644(o): os.chmod(first(o), 0o644)
        def hardlink(o): r = first(o); os.link(r, o/'alias')
        def biglines(o):
            r = first(o); b = r.read_text() + '\n' * 5000; r.write_text(b); Path(str(r) + '.sha').write_text(H(b.encode()) + '\n')
        def leasegone(o):
            for l in (o/'workers').glob('*'):
                l.unlink()
        def leasesha(o):
            for l in (o/'workers').glob('*.sha'):
                l.write_text('0' * 64 + '\n')
        def leaseboot(o):
            for l in (o/'workers').glob('*'):
                if not l.name.endswith('.sha'):
                    b = (OTHER + '\n').encode(); l.write_bytes(b); Path(str(l) + '.sha').write_text(H(b) + '\n')
        def leaselinks(o):
            for l in (o/'workers').glob('*'):
                if not l.name.endswith('.sha'):
                    os.link(l, o/('lease-alias-' + l.name)); break
        return [('ok', ok), ('missing', missing), ('badsha', badsha), ('extra', extra), ('wrong-plan', wrongplan),
                ('mode644', mode644), ('hardlink', hardlink), ('lines>4096', biglines), ('lease-gone', leasegone),
                ('lease-sha', leasesha), ('lease-boot', leaseboot), ('lease-links', leaselinks)]

    for shell in SHELLS:
        for name, build in dv_cases():
            j = f.p/f'dv-{shell[0]}-{name}'; j.mkdir(mode=0o700)
            shutil.copytree(src, j/'base', symlinks=True)
            build(j/'base')
            cur = j/'cur'; cur.mkdir(mode=0o700)
            for st in steps:
                (cur/f'current.{st[1]}').write_text(st[6] + '\n'); os.chmod(cur/f'current.{st[1]}', 0o600)
            body = oldfns + '''
o=;n=;for s in $(awk -F'\\t' '$1=="step"{print $2 ":" $7}' "$1/base/plan"); do
  old_vrb_dispatch_valid "$1" base "${s%%:*}" forward "${s#*:}"; a=$?
  vrb_dispatch_valid "$1" base "${s%%:*}" forward "${s#*:}"; b=$?
  [ "$a" = 0 ] && o="${o}0" || o="${o}x";[ "$b" = 0 ] && n="${n}0" || n="${n}x"
done
vrb_dispatch_valid_range "$1" base 1 ''' + str(len(steps)) + ''' "$1/cur"; rr=$?
echo "$o $n $rr"'''
            r = subprocess.run(shell + ['-c', f.script(body), 'x', *map(str, f.libs), str(j)], env=f.env,
                               capture_output=True, text=True, timeout=120)
            got = r.stdout.split()
            if len(got) == 3 and (('x' in got[0]) == (name == 'ok')):
                fails.append(f'{shell[0]} dispatch_valid {name}: case did not exercise its verdict {got}')
            if len(got) != 3 or got[0] != got[1] or (got[2] == '0') != ('x' not in got[0]):
                fails.append(f'{shell[0]} dispatch_valid {name}: old/new/range {got} {r.stderr[-300:]}')

if fails:
    print('BATCH_PRIMITIVES=FAIL\n' + '\n'.join(fails))
    sys.exit(1)
print(f'BATCH_PRIMITIVES=PASS {len(SHELLS)} shells: publish_quiet x17 lease sets and dispatch_valid/range x12 receipt/lease corruptions equal c9d39f4; settled marker never hides a new lease')
