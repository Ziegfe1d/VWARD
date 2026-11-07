#!/usr/bin/env python3
"""A coordinator admitted before a request must recheck after waiting EDIT/CHANGE."""
import os
import shlex
import shutil
import signal
import subprocess
import time
from fixture import ROOT,LIBDIR,SHELL,function_source,digest
from live_fixture import LiveFixture

def until(path):
    end=time.monotonic()+8
    while not path.exists() and time.monotonic()<end:time.sleep(.02)
    assert path.exists(),path.name

def stop(p):
    if p is None:return
    try:os.killpg(p.pid,signal.SIGKILL)
    except ProcessLookupError:pass
    p.communicate(timeout=5)

with LiveFixture() as f:
    installed=f.prefix/'opt/lib/vward';installed.mkdir(parents=True)
    for lib in LIBDIR.glob('*.sh'):shutil.copy2(lib,installed/lib.name)
    paused=f.p/'before-edit';resume=f.p/'resume-edit';request=f.p/'request-held';finish=f.p/'finish-update'
    source=function_source(LIBDIR/'vward-routing-live.sh','vrl_envelope')
    point='    vrb_shared_lock "$vrb_edit_path" || return 75;vrb_edit=1\n'
    assert source.count(point)==1,'EDIT handoff fault point changed'
    source=source.replace(point,'''    printf paused > "$PAUSED"
    while [ ! -e "$RESUME" ];do sleep .02;done
'''+point)
    env=f.env|{'PAUSED':str(paused),'RESUME':str(resume)}
    native_before=f.native.read_bytes();state_before=digest(f.live)
    p=subprocess.Popen(SHELL+['-c',f.script(source+'vward_routing_live_service race svc vpn VPN:Wireguard0 default 0'),
                            'coordinator',*map(str,f.libs)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    q=None
    try:
        until(paused)
        updater=ROOT/'components/update-engine'
        script='SELF_DIR='+shlex.quote(str(updater))+'\n. "$SELF_DIR/vward-update-common.sh"\n'
        script+='''vu_lock_acquire || exit 90
trap 'vu_barrier_leave;vu_lock_release' EXIT
vu_barrier_request || exit 91
printf held > "$1"
while [ ! -e "$2" ];do sleep .02;done
'''
        q=subprocess.Popen(SHELL+['-c',script,'updater',str(request),str(finish)],env=f.env,
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        until(request)
        assert not (f.prefix/'tmp/vward-console-edit.lock').exists(),'request kept EDIT during quiescence'
        resume.touch()
        out,err=p.communicate(timeout=8)
        assert p.returncode==75,(p.returncode,out,err)
        assert f.native.read_bytes()==native_before and not f.calls.exists(),'admitted-before-request coordinator reached native transport'
        assert digest(f.live)==state_before,'coordinator created J2/cache/state after request handoff'
        finish.touch();q.communicate(timeout=8)
        assert q.returncode==0,q.returncode
        assert not (f.prefix/'tmp/vward-update-requested').exists()
    finally:
        stop(q);stop(p)
print('LIVE_UPDATER_RACE=PASS actual admission-before-request/EDIT handoff refuses before J2/cache/native IO; updater releases EDIT before quiescence')
