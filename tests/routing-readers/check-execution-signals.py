#!/usr/bin/env python3
"""Explicit compensation after TERM/native post or SIGKILL/late local post."""
import ctypes,os,signal,subprocess,time
from fixture import PipelineFixture,SHELL,LIBDIR,function_source,digest
assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
for sig,step in [(signal.SIGTERM,1),(signal.SIGKILL,6)]:
    with PipelineFixture() as f:
        config=(f.e/'running.cfg').read_bytes();ledger=digest(f.decision)
        real=function_source(LIBDIR/'vward-routing-pipeline.sh','vrb_write_scope').replace('vrb_write_scope() (','vrb_write_scope_real() (',1)
        hook=real+'''
        vrb_write_scope() {
            vrb_write_scope_real "$@"; signal_rc=$?
            if [ "$3" = "$FAULT_STEP" ];then
                : > "$vrb_e/fault-ready"
                while :;do sleep .02;done
            fi
            return "$signal_rc"
        }
        vward_routing_pipeline2 "$@"
        '''
        p=subprocess.Popen(SHELL+['-c',f.script(hook),'signal',*map(str,f.libs),str(f.j),'interrupted','svc','vpn','VPN:Wireguard0','default','0'],
            env=f.env|{'FAULT_STEP':str(step)},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        try:
            end=time.monotonic()+45
            while not (f.e/'fault-ready').exists() and p.poll() is None and time.monotonic()<end:time.sleep(.02)
            assert (f.e/'fault-ready').exists(),('fault point not reached',sig,step,p.poll())
            assert (f.e/'running.cfg').read_bytes()!=config,'fixture missed a real native post'
            os.killpg(p.pid,sig);p.wait(timeout=5)
            end=time.monotonic()+2
            while time.monotonic()<end:
                try:
                    child,_status=os.waitpid(-1,os.WNOHANG)
                    if child==0:time.sleep(.01)
                except ChildProcessError:break
            try:os.killpg(p.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            for _ in range(200):
                try:
                    child,_status=os.waitpid(-1,os.WNOHANG)
                    if child==0:time.sleep(.01)
                except ChildProcessError:break
            assert f.invoke('vward_routing_update_eligibility2',f.j).returncode==75,'dead PID hid the persistent pending operation'
            r=f.invoke('vward_routing_pipeline_recover2',f.j,'interrupted','inspect')
            assert r.returncode==3,'inspect replayed an interrupted write'
            r=f.invoke('vward_routing_pipeline_recover2',f.j,'interrupted','compensate')
            assert r.returncode==0,(sig,step,r.returncode,r.stdout,r.stderr)
            assert (f.e/'running.cfg').read_bytes()==config and digest(f.decision)==ledger
            assert (f.j/'interrupted/state').read_text()=='compensated\n'
            assert f.invoke('vward_routing_update_eligibility2',f.j).returncode==0
        finally:
            try:os.killpg(p.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            p.communicate(timeout=5)
print('B_EXECUTION_SIGNALS=PASS TERM after native post/SIGKILL after late metadata, persistent barrier/inspect/explicit own baseline compensation')
