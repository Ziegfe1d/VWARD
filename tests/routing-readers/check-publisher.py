#!/usr/bin/env python3
"""No orphaned DATA publisher can write through recovery after its owner dies."""
import os,signal,subprocess,time
from fixture import PipelineFixture,SHELL

def until(predicate,seconds=8):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.03)
    raise AssertionError('publisher did not reach the bounded fault point')

with PipelineFixture() as f:
    original=(f.e/'running.cfg').read_bytes()
    (f.e/'publish-pause').touch()
    proc=subprocess.Popen(SHELL+['-c',f.script('vward_routing_pipeline2 "$@"'),'test',*map(str,f.libs),str(f.j),'killed','svc','vpn','VPN:Wireguard0','default','0'],
                          env=f.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    try:
        until(lambda:(f.e/'publish-waiting').exists())
        publisher,start=map(int,(f.e/'publish-waiting').read_text().split())
        boot=__import__('pathlib').Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        lease=f.j/'killed/workers'/f'{boot}.{publisher}.{start}'
        assert lease.exists(),'actual final publisher has no durable lease'
        r=f.invoke('vrb_publish_quiet',f.j/'killed');assert r.returncode==75,'live publisher declared quiet'
        worker=int((f.j/'killed/worker').read_text().split()[0])
        owner=int((f.e/'root/tmp/vward-console-edit.lock/owner').read_text().split()[0])
        # Leave the final publisher alive after killing both coordinator and
        # its outer worker. This is the orphan missed by the old single lease.
        os.kill(owner,signal.SIGKILL);os.kill(worker,signal.SIGKILL)
        r=f.invoke('vrb_publish_quiet',f.j/'killed');assert r.returncode==75,'orphan publisher escaped the quiet gate'
        assert (f.e/'running.cfg').read_bytes()==original
        (f.e/'publish-pause').unlink()
        out,err=proc.communicate(timeout=8)
        until(lambda:not __import__('pathlib').Path(f'/proc/{publisher}').exists() or
              __import__('pathlib').Path(f'/proc/{publisher}/stat').read_text().split(') ',1)[1].startswith('Z '))
        assert (f.e/'running.cfg').read_bytes()==original,'orphan published after its operation owner died'
        assert (f.j/'killed/state').read_text()=='pending\n'
    finally:
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        proc.wait(timeout=8)
print('B_PUBLISHER=PASS leased final PID/start/boot, live/orphan recovery fence, dead-owner final recheck')

with PipelineFixture() as f:
    original=(f.e/'running.cfg').read_bytes()
    foreign=f.e/'owner-kept';os.link(f.e/'running.cfg',foreign)
    r=f.invoke('vward_routing_pipeline2',f.j,'linked','svc','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    assert foreign.read_bytes()==original and (f.e/'running.cfg').read_bytes()==original,'publication followed a hard-linked authority leaf'
    assert (f.j/'linked/state').read_text()=='unknown\n'
print('B_PUBLISH_LINK=PASS foreign hard-linked authority leaf refuses before publication')
