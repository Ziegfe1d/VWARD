#!/usr/bin/env python3
"""The actual first-ROOT publisher fences CHANGE/updater and cannot adopt a foreign postimage."""
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

def observation_only(f,before,startup):
    assert f.native.read_bytes()==before and f.startup.read_bytes()==startup,'bootstrap wrote/saved native routing'
    calls=f.calls.read_text().splitlines() if f.calls.exists() else []
    assert calls and all(row.endswith('\tshow running-config') for row in calls),('bootstrap issued a native mutation',calls)

def start(f):
    if os.environ.get('RS6_BUSYBOX'):
        (f.p/'poison/mv').symlink_to(os.environ['RS6_BUSYBOX'])
    source=function_source(LIBDIR/'vward-routing-bootstrap.sh','vrl_init_publish')
    point='    exec mv -nT "$1" "$vrl_root"\n'
    assert source.count(point)==1,'first-ROOT final utility fault boundary changed'
    source=source.replace(point,'''    printf '%s\t%s\n' "$vrl_ip_pid" "$1" > "$PAUSED"
    while [ ! -e "$RESUME" ];do sleep .02;done
'''+point)
    paused=f.p/'root-paused';resume=f.p/'root-resume'
    env=f.env|{'PAUSED':str(paused),'RESUME':str(resume)}
    p=subprocess.Popen(SHELL+['-c',f.script(source+'vward_routing_live_bootstrap first'),
                             'bootstrap',*map(str,f.libs)],env=env,
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    try:until(paused)
    except BaseException:
        stop(p);raise
    pid,stage=paused.read_text().strip().split('\t')
    from pathlib import Path
    return p,int(pid),Path(stage),resume

with LiveFixture() as f:
    shutil.rmtree(f.live)
    installed=f.prefix/'opt/lib/vward';installed.mkdir(parents=True)
    for lib in LIBDIR.glob('*.sh'):shutil.copy2(lib,installed/lib.name)
    before=f.native.read_bytes();startup=f.startup.read_bytes()
    p=None;q=None
    try:
        p,publisher,stage,resume=start(f)
        coordinator=int((f.prefix/'tmp/vward-console-edit.lock/pid').read_text())
        assert publisher!=coordinator and publisher!=p.pid
        assert not f.live.exists()
        os.kill(coordinator,signal.SIGKILL)
        # The actual final utility still owns the CHANGE election. A legacy
        # claimant cannot reclaim it merely because its former owner died.
        r=f.run('. "$1";vward_lock_take "$2"',LIBDIR/'vward-runtime-admission.sh',f.prefix/'tmp/vward-route-change.lock',env=f.env)
        assert r.returncode!=0 and not f.live.exists(),('late publisher lost CHANGE fence',r.returncode,r.stderr)
        held=f.p/'update-held';finish=f.p/'finish-update'
        updater=ROOT/'components/update-engine'
        script='SELF_DIR='+shlex.quote(str(updater))+'\n. "$SELF_DIR/vward-update-common.sh"\n'
        script+='''vu_lock_acquire || exit 90
trap 'vu_barrier_leave;vu_lock_release' EXIT
vu_barrier_request || exit 91
printf held > "$1"
while [ ! -e "$2" ];do sleep .02;done
vu_runtime_quiesce || exit 92
if vu_barrier_enter;then exit 93;fi
[ "$VU_QUIESCE_WHY" = routing-admission ] || exit 94
printf 'late-root-refused\n'
'''
        q=subprocess.Popen(SHELL+['-c',script,'updater',str(held),str(finish)],env=f.env,
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        until(held)
        resume.touch();p.communicate(timeout=8)
        assert f.live.is_dir() and not stage.exists()
        assert (f.live/'decision/version.tsv').read_text()=='routing-state\t0\n'
        assert not (f.live/'.bootstrap/completion').exists(),'dead parent invented root-publication ACK'
        observation_only(f,before,startup)
        finish.touch();out,err=q.communicate(timeout=8)
        assert q.returncode==0 and b'late-root-refused' in out,(q.returncode,out,err)
        retained=digest(f.live)
        r=f.invoke('vward_routing_live_bootstrap','no-adoption')
        assert r.returncode==75 and digest(f.live)==retained,'unacknowledged root auto-adopted/replayed'
    finally:
        stop(q);stop(p)

for foreign in ('empty','matching','extra'):
    with LiveFixture() as f:
        shutil.rmtree(f.live)
        before=f.native.read_bytes();startup=f.startup.read_bytes()
        p=None
        try:
            p,publisher,stage,resume=start(f)
            if foreign=='empty':f.live.mkdir(mode=0o700)
            else:shutil.copytree(stage,f.live)
            if foreign=='extra':(f.live/'owner.file').write_bytes(b'foreign bytes\n')
            inode=f.live.stat().st_ino;retained=digest(f.live)
            resume.touch();out,err=p.communicate(timeout=8)
            assert p.returncode==75,(foreign,p.returncode,out,err)
            assert f.live.stat().st_ino==inode and digest(f.live)==retained,(foreign,'foreign directory changed/nested/adopted')
            assert stage.is_dir() and not (f.live/'.bootstrap/completion').exists()
            observation_only(f,before,startup)
        finally:stop(p)
print('LIVE_BOOTSTRAP_LIFETIME=PASS actual publisher survives parent-only kill under CHANGE; updater refuses late0; empty/matching/extra foreign roots preserved')
