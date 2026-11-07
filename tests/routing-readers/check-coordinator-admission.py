#!/usr/bin/env python3
"""Actual updater must see an orphaned live coordinator/final publisher."""
import os,signal,subprocess,time
from fixture import PipelineFixture,SHELL,ROOT,function_source
with PipelineFixture() as f:
    (f.e/'publish-pause').touch()
    proc=subprocess.Popen(SHELL+['-c',f.script('vward_routing_pipeline2 "$@"'),'admit',*map(str,f.libs),str(f.j),'admit','svc','vpn','VPN:Wireguard0','default','0'],
                          env=f.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    try:
        deadline=time.monotonic()+8
        while not (f.e/'publish-waiting').exists() and time.monotonic()<deadline:time.sleep(.02)
        assert (f.e/'publish-waiting').exists(),'publisher did not reach the fault point'
        coordinator=int((f.e/'root/tmp/vward-console-edit.lock/owner').read_text().split()[0])
        assert coordinator!=proc.pid,'test did not expose the subshell PID boundary'
        os.kill(proc.pid,signal.SIGKILL);proc.wait(timeout=8)
        updater=ROOT/'components/update-engine/vward-update-common-base.sh'
        body=function_source(updater,'vu_pid_start')+function_source(updater,'vu_activity_clear')
        run=f.e/'updater';run.mkdir(mode=0o700)
        r=f.run(body+'\nVU_ROOT_PREFIX=$1;VU_RUN_DIR=$2;vu_activity_clear;rc=$?;printf "%s\\n" "$VU_ACTIVITY_WHY";exit "$rc"',f.e/'root',run,env=f.env)
        assert r.returncode==1,(r.returncode,r.stdout,r.stderr,'updater declared quiescent while real coordinator/publisher lived')
        slots=f.e/'root/tmp/vward-runtime-active'
        active_pids={int(p.read_text()) for p in slots.glob('*/pid')}
        assert coordinator in active_pids,'only the dead parent shell had an admission lease'
    finally:
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        proc.wait(timeout=8)
print('B_ACTUAL_ADMISSION=PASS actual updater sees coordinator/publisher after top-shell SIGKILL')
