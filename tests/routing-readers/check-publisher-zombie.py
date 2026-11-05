#!/usr/bin/env python3
"""A dead unreaped coordinator cannot authorise an orphan DATA publisher."""
import ctypes,os,signal,subprocess,time
from pathlib import Path
from fixture import PipelineFixture,SHELL
assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0  # own child subreaper
with PipelineFixture() as f:
    before=(f.e/'running.cfg').read_bytes();(f.e/'publish-pause').touch()
    p=subprocess.Popen(SHELL+['-c',f.script('vward_routing_pipeline2 "$@"'),'zombie',*map(str,f.libs),str(f.j),'zombie','svc','vpn','VPN:Wireguard0','default','0'],
        env=f.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    try:
        end=time.monotonic()+8
        while not (f.e/'publish-waiting').exists() and time.monotonic()<end:time.sleep(.02)
        assert (f.e/'publish-waiting').exists(),'publisher did not reach the fault point'
        owner=int((f.e/'root/tmp/vward-console-edit.lock/owner').read_text().split()[0])
        worker=int((f.j/'zombie/worker').read_text().split()[0])
        os.kill(p.pid,signal.SIGKILL);p.wait(timeout=5)
        os.kill(owner,signal.SIGKILL);os.kill(worker,signal.SIGKILL)
        end=time.monotonic()+4
        while time.monotonic()<end:
            if Path(f'/proc/{owner}/stat').read_text().rsplit(') ',1)[1].startswith('Z '):break
            time.sleep(.02)
        assert Path(f'/proc/{owner}/stat').read_text().rsplit(') ',1)[1].startswith('Z '),'fixture did not retain the zombie owner'
        (f.e/'publish-pause').unlink();p.communicate(timeout=8)
        assert (f.e/'running.cfg').read_bytes()==before,'zombie owner authorised an orphan final write'
        assert not list((f.j/'zombie/step.1').glob('dispatched.*')),'a dead owner authorised a dispatch receipt'
    finally:
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        p.wait(timeout=5)
        for _ in range(100):
            try:
                child,_status=os.waitpid(-1,os.WNOHANG)
                if child==0:time.sleep(.01)
            except ChildProcessError:break
print('B_ZOMBIE_PUBLISHER=PASS unreaped dead owner cannot authorise receipt or final publication; actual kernel lifetime test')
