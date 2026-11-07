#!/usr/bin/env python3
"""Real HTTP completion/parent lifetime: keep unknown before/planned and no replay."""
import os
import signal
import subprocess
import time
from pathlib import Path
from agh_live_fixture import AghLiveFixture,CURL
from fixture import SHELL,LIBDIR

with AghLiveFixture() as f:
    f.lost=True
    r=f.invoke('vward_routing_live_service','lost','svc','dns','ISP','policy1',0)
    assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    op=f.live/'journal/lost';e=op/'dns-evidence/evidence.1'
    assert (e/'request.pending').exists() and (e/'dns.before.json').exists() and (e/'dns.planned.json').exists()
    assert not (e/'completion').exists() and (op/'state').read_text()=='unknown\n'
    assert (f.live/'decision/choices.tsv').read_text()=='schema\t1\n'
    image=f.agh.read_bytes();posts=sum(x[0]=='POST' for x in f.http_calls)
    r=f.invoke('vward_routing_live_service','retry','svc','dns','ISP','policy1',0)
    assert r.returncode==75 and f.agh.read_bytes()==image
    r=f.invoke('vward_routing_live_recover','lost','compensate')
    assert r.returncode==75 and f.agh.read_bytes()==image and sum(x[0]=='POST' for x in f.http_calls)==posts

for phase in ('before','after'):
    with AghLiveFixture() as f:
        f.env['VWARD_PROFILE_LIB']=str(LIBDIR/'vward-device-profile.sh')
        r=f.invoke('vward_routing_scope_gate','domain','unrelated.example')
        assert r.returncode==0,('old installed reader unavailable',r.returncode,r.stderr)
        f.pause=phase
        p=subprocess.Popen(SHELL+['-c',f.script('"$@"'),'x',*map(str,f.libs),
                          'vward_routing_live_service','death','svc','dns','ISP','policy1','0'],
                          env=f.env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        try:
            assert f.entered.wait(8),('actual HTTP request did not reach pause',phase)
            op=f.live/'journal/death'
            publishers=[q for q in (op/'workers').iterdir() if not q.name.endswith('.sha')]
            assert len(publishers)==1,publishers
            _,pid,start=publishers[0].name.rsplit('.',2);pid=int(pid)
            assert Path(f'/proc/{pid}/exe').resolve()==Path(CURL).resolve(),('registered publisher was not the actual chosen curl executable',pid)
            assert Path(f'/proc/{pid}/stat').read_text().rsplit(') ',1)[1].split()[19]==start
            owner=(f.prefix/'tmp/vward-console-edit.lock/owner').read_text().split('\t')
            coordinator=int(owner[0]);assert coordinator!=pid and coordinator!=p.pid
            os.kill(coordinator,signal.SIGKILL)
            # The actual curl is STILL alive; the coordinator alone died.
            os.kill(pid,0)
            r=f.invoke('vward_routing_scope_gate','domain','unrelated.example')
            assert r.returncode==75,('old writer bypassed surviving HTTP publisher',phase,r.returncode)
            r=f.invoke('vward_routing_live_service','contender','svc','dns','ISP','policy1',0)
            assert r.returncode==75,('new writer bypassed surviving HTTP publisher',phase,r.returncode)
            f.resume.set();p.communicate(timeout=8)
            assert (op/'dns-evidence/evidence.1/request.pending').exists(),'parent death inferred HTTP ACK'
            assert not (op/'dns-evidence/evidence.1/completion').exists(),'dead coordinator received authority'
            posts=sum(x[0]=='POST' for x in f.http_calls)
            r=f.invoke('vward_routing_update_eligibility2',f.live/'journal')
            assert r.returncode==75,'quiet/dead curl cleared persistent unknown'
            r=f.invoke('vward_routing_live_service','after-death','svc','dns','ISP','policy1',0)
            assert r.returncode==75 and sum(x[0]=='POST' for x in f.http_calls)==posts,'late HTTP completion was replayed/adopted'
        finally:
            f.resume.set()
            if p.poll() is None:os.killpg(p.pid,signal.SIGKILL)
            p.communicate(timeout=8)
print('LIVE_AGH_FAULTS=PASS real HTTP lost reply and parent-only death before/after server write; actual curl PID lease; old/new/updater fenced; before/planned/pending retained/no replay')
