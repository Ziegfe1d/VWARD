#!/usr/bin/env python3
"""The final leased exec must compare bytes, not only mode/owner."""
import os,signal,subprocess,time
from fixture import PipelineFixture,SHELL
with PipelineFixture() as f:
    (f.e/'publish-pause').touch()
    proc=subprocess.Popen(SHELL+['-c',f.script('vward_routing_pipeline2 "$@"'),'cas',*map(str,f.libs),str(f.j),'cas','svc','vpn','VPN:Wireguard0','default','0'],
                          env=f.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    try:
        deadline=time.monotonic()+8
        while not (f.e/'publish-waiting').exists() and time.monotonic()<deadline:time.sleep(.02)
        assert (f.e/'publish-waiting').exists(),'publisher did not reach the fault point'
        cfg=f.e/'running.cfg';foreign=cfg.read_text()+'object-group fqdn Owner\n    include owner.example\n!\n'
        cfg.write_text(foreign)
        assert cfg.stat().st_mode&0o777==0o600
        (f.e/'publish-pause').unlink()
        deadline=time.monotonic()+8
        while proc.poll() is None and 'object-group fqdn domain-list0' not in cfg.read_text() and time.monotonic()<deadline:time.sleep(.02)
        assert cfg.read_text()==foreign,'leased exec lost an owner edit with unchanged MODE/UID'
        out,err=proc.communicate(timeout=8)
        assert proc.returncode==3,(proc.returncode,out,err)
        assert (f.j/'cas/state').read_text()=='unknown\n'
        assert (f.decision/'choices.tsv').read_text()=='schema\t1\n'
    finally:
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        proc.wait(timeout=8)
print('B_FINAL_CONTENT_CAS=PASS same-mode outside edit preserved; no final publication/false commit')
