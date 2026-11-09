#!/usr/bin/env python3
"""A first request killed after the canonical ROOT transfer must be explicitly
recoverable: inspect is read-only, abort quarantines (never deletes) only an
own, dead, byte-exact observation0, and the next ordinary request re-imports.

Actual copied console closure; faults are SIGKILL of the actual coordinator at
four boundaries of the installed bootstrap (before ACK, after ACK before J2,
after J2 plan before its first step, after the
state-set write before its J2 finish). No adoption, replay or native write."""
import hashlib
import os
import shutil
import subprocess
from fixture import digest
from live_fixture import LiveFixture

BOUNDARY={
    'before-ack':('vward-routing-bootstrap.sh',
        "    printf 'acknowledged-root-transfer\\n' > \"$vrl_root/.bootstrap/completion\" &&\n"),
    'after-ack':('vward-routing-bootstrap.sh',
        '    vrb_execute2 "$vrb_j/.migrations/$vrb_op/lowered"\n'),
    'after-plan':('vward-routing-pipeline.sh',
        '    vward_journal2_plan "$vrb_j" "$vrb_op" "$vrb_t/plan" || return 75\n'),
    # Batch executor (08.11.2026): after a step's write, before the shared
    # readback and J2 finish of the batch.
    'after-write':('vward-routing-pipeline.sh',
        '            vrb_write_scope "$vrb_kind" "$vrb_id" "$vrb_n" post || vrb_rc=$?\n'),
}

def arm(f,point):
    name,line=BOUNDARY[point]
    lib=f.prefix/'opt/lib/vward'/name
    text=lib.read_text();assert text.count(line)==1,(point,'fault boundary changed')
    if point in ('after-plan','after-write'):
        kill=line+'    case $vrb_op in b-*) [ ! -e "$VWARD_ROOT_PREFIX/../fault" ] || kill -KILL "$vrj2_me" ;; esac\n'
    else:
        kill='    [ ! -e "$VWARD_ROOT_PREFIX/../fault" ] || kill -KILL "$vrj2_me"\n'+line
    lib.write_text(text.replace(line,kill));lib.chmod(0o644)
    (f.p/'fault').touch()

def boot(f):
    f.install_console()
    if os.environ.get('RS6_BUSYBOX'):(f.p/'poison/mv').symlink_to(os.environ['RS6_BUSYBOX'])
    r=f.console('service','off','svc');assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    shutil.rmtree(f.live)

def strand(f,point):
    boot(f);arm(f,point)
    native=f.native.read_bytes();saved=f.startup.read_bytes()
    r=f.console('service','on','svc','Wireguard1',preserve_profile=True)
    assert r.returncode!=0,(point,'fault did not interrupt',r.stdout,r.stderr)
    (f.p/'fault').unlink()
    version='2' if point=='after-write' else '0'
    assert f.live.is_dir() and (f.live/'decision/version.tsv').read_text()==f'routing-state\t{version}\n',point
    assert f.native.read_bytes()==native and f.startup.read_bytes()==saved,(point,'bootstrap wrote native')
    return native,saved

def quarantine(f):
    return sorted(p for p in f.live.parent.iterdir() if p.name.startswith('.routing-root0.'))

def candidates(f):
    return sorted(p for p in f.live.parent.iterdir() if p.name.startswith('.routing-init.'))

def native_only_reads(f,mark):
    calls=f.calls.read_text().splitlines()[mark:] if f.calls.exists() else []
    return all(c.endswith('\tshow running-config') for c in calls)

fail=[]
for point in ('before-ack','after-ack','after-plan','after-write'):
    with LiveFixture() as f:
        native,saved=strand(f,point)
        retained=digest(f.live)
        # Stranded observation0 refuses every ordinary request (fail-closed).
        r=f.console('service','on','svc','Wireguard1',preserve_profile=True)
        assert r.returncode!=0 and digest(f.live)==retained,(point,r.returncode,r.stdout)
        mark=len(f.calls.read_text().splitlines()) if f.calls.exists() else 0
        r=f.console('routing-root','inspect',preserve_profile=True)
        if r.returncode!=0 or 'root0=' not in r.stdout:
            fail.append((point,'no explicit Root0 inspect',r.returncode,r.stdout,r.stderr));continue
        assert digest(f.live)==retained and native_only_reads(f,mark),(point,'inspect wrote')
        if point=='after-write':
            assert 'root0=journal-unresolved' in r.stdout,(point,r.stdout)
            r=f.console('routing-root','abort',preserve_profile=True)
            assert r.returncode==75 and digest(f.live)==retained and not quarantine(f),(point,'abort over unresolved J2',r.stdout)
            r=f.console('routing-root','compensate',preserve_profile=True)
            assert r.returncode==0,(point,'own J2 compensation',r.returncode,r.stdout,r.stderr)
            assert (f.live/'decision/version.tsv').read_text()=='routing-state\t0\n'
            retained=digest(f.live)
            r=f.console('routing-root','inspect',preserve_profile=True)
        assert 'root0=abortable' in r.stdout,(point,r.stdout)
        r=f.console('routing-root','abort',preserve_profile=True)
        assert r.returncode==0 and 'result=changed' in r.stdout,(point,r.returncode,r.stdout,r.stderr)
        q=quarantine(f)
        assert not f.live.exists() and len(q)==1 and digest(q[0])==retained,(point,'quarantine is not the exact retained root')
        assert f.native.read_bytes()==native and f.startup.read_bytes()==saved and native_only_reads(f,mark)
        r=f.console('routing-root','inspect',preserve_profile=True)
        assert r.returncode==0 and 'root0=absent' in r.stdout,(point,r.stdout)
        r=f.console('service','on','svc','Wireguard1',preserve_profile=True)
        assert r.returncode==0 and 'result=changed' in r.stdout,(point,'fresh re-import after abort',r.returncode,r.stdout,r.stderr)
        assert (f.live/'decision/version.tsv').read_text()=='routing-state\t2\n'
        assert '\tvpn\tVPN:Wireguard1\tdefault\t' in (f.live/'decision/choices.tsv').read_text()
        assert ' Wireguard1 auto' in f.native.read_text() and f.startup.read_bytes()==f.native.read_bytes()
        assert digest(q[0])==retained,(point,'quarantine changed by later request')
assert not fail,fail

def refused(f,why,expect):
    retained=digest(f.live) if f.live.exists() or f.live.is_symlink() else None
    r=f.console('routing-root','inspect',preserve_profile=True)
    assert r.returncode==0 and f'root0={expect}' in r.stdout,(why,r.returncode,r.stdout,r.stderr)
    r=f.console('routing-root','abort',preserve_profile=True)
    assert r.returncode==75,(why,'abort accepted',r.returncode,r.stdout,r.stderr)
    after=digest(f.live) if f.live.exists() or f.live.is_symlink() else None
    assert after==retained and not quarantine(f),(why,'refused abort changed bytes')

# Live coordinator identity (sealed parent rewritten to a running process).
with LiveFixture() as f:
    strand(f,'before-ack')
    holder=subprocess.Popen(['sleep','30'])
    try:
        start=open(f'/proc/{holder.pid}/stat').read().rsplit(')',1)[1].split()[19]
        boot_id=open('/proc/sys/kernel/random/boot_id').read().strip()
        parent=f.live/'.bootstrap/parent'
        op=parent.read_text().split('\t')[0]
        parent.write_text(f'{op}\t{holder.pid}\t{start}\t{boot_id}\n')
        (f.live/'.bootstrap/parent.sha').write_text(hashlib.sha256(parent.read_bytes()).hexdigest()+'\n')
        refused(f,'live parent','live')
    finally:
        holder.kill();holder.wait()
# Any decision byte differs from the sealed empty observation0.
with LiveFixture() as f:
    strand(f,'before-ack')
    with (f.live/'decision/choices.tsv').open('a') as out:out.write('service\tx\t1\tvpn\tVPN:auto\tdefault\t1\n')
    refused(f,'modified decision','modified')
# Unknown extra entry at ROOT level is never part of our transfer.
with LiveFixture() as f:
    strand(f,'before-ack')
    (f.live/'owner.file').write_bytes(b'foreign\n')
    refused(f,'extra entry','foreign')
# Foreign/empty ROOT without our bootstrap seal.
with LiveFixture() as f:
    boot(f);f.live.mkdir(mode=0o700)
    refused(f,'empty foreign root','foreign')
# Ready (version 2) ROOT is never an abort target.
with LiveFixture() as f:
    f.install_console()
    r=f.console('service','off','svc');assert r.returncode==0,(r.stdout,r.stderr)
    assert (f.live/'decision/version.tsv').read_text()=='routing-state\t2\n'
    refused(f,'ready root','ready')
# Occupied quarantine name: no clobber, nothing moved.
with LiveFixture() as f:
    strand(f,'before-ack')
    op=(f.live/'.bootstrap/parent').read_text().split('\t')[0]
    occupied=f.live.parent/f'.routing-root0.{op}';occupied.mkdir(mode=0o700)
    retained=digest(f.live)
    r=f.console('routing-root','abort',preserve_profile=True)
    assert r.returncode==75 and digest(f.live)==retained and list(occupied.iterdir())==[],'quarantine clobbered'
print('LIVE_ROOT0_RECOVERY=PASS before-ack/after-ack/after-plan/after-write kill: inspect read-only, own J2 compensate, abort quarantines exact root, fresh re-import; live/modified/foreign/ready/occupied refused')
