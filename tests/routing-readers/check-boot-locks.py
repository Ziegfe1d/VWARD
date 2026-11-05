#!/usr/bin/env python3
"""Persisted boot identity distinguishes an old lease from a reused PID/start."""
import os,hashlib
from pathlib import Path
from fixture import PipelineFixture
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
old='11111111-1111-1111-1111-111111111111'
if boot==old:old='22222222-2222-2222-2222-222222222222'
pid=os.getpid();start=Path(f'/proc/{pid}/stat').read_text().rsplit(') ',1)[1].split()[19]
def old_lock(path):
    path.mkdir(mode=0o700)
    for name,data in [('pid',str(pid)+'\n'),('pid_start',start+'\n'),('boot',old+'\n'),('owner',f'{pid}\t{start}\t{old}\n')]:
        p=path/name;p.write_text(data);p.chmod(0o600)
    p=path/'owner.sha';p.write_text(hashlib.sha256((path/'owner').read_bytes()).hexdigest()+'\n');p.chmod(0o600)
with PipelineFixture() as f:
    r=f.invoke('vrb_envelope',f.j,'init');assert r.returncode==0
    path=f.e/'root/tmp/vward-console-edit.lock';old_lock(path)
    r=f.invoke('vward_routing_pipeline2',f.j,'afterboot','svc','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr,'old-boot shared owner was mistaken for a live reused identity')
with PipelineFixture() as f:
    old_lock(f.j/'.lock')
    plan=f.p/'plan';plan.write_text('routing-plan\t2\tg-0000000000000000\tdenied\nstep\t1\tmove\tmanifest\tcontext\t'+'a'*64+'\t'+'b'*64+'\tcreation-and-cas\t-\tgeneration,identity,postimage\trestore-own-scope\n')
    r=f.invoke('vward_journal2_plan',f.j,'afterboot',plan)
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr,'old-boot journal owner was mistaken for a live reused identity')
with PipelineFixture() as f:
    (f.e/'local-fails').write_text('choices\n')
    before=(f.e/'running.cfg').read_bytes()
    r=f.invoke('vward_routing_pipeline2',f.j,'partial','svc','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    worker=f.j/'partial/worker';worker.write_text(f'{pid}\t{start}\t{old}\n');worker.chmod(0o600)
    (f.j/'partial/worker.sha').write_text(hashlib.sha256(worker.read_bytes()).hexdigest()+'\n')
    (f.e/'local-fails').unlink()
    r=f.invoke('vward_routing_pipeline_recover2',f.j,'partial','compensate')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr,'old-boot outer worker blocked exact own recovery')
    assert (f.e/'running.cfg').read_bytes()==before
print('B_BOOT_LOCKS=PASS old-boot shared/journal/outer leases cannot impersonate a new live PID/start; DATA reboot model only')
