#!/usr/bin/env python3
"""Dead reclaimers must not block forever or erase the next live lock owner."""
import os,signal,subprocess,time
from fixture import PipelineFixture,SHELL

def until(path):
    end=time.monotonic()+8
    while not path.exists() and time.monotonic()<end:time.sleep(.02)
    assert path.exists(),path.name
def stop(p):
    if p is not None:
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        p.communicate(timeout=5)

with PipelineFixture() as f:
    path=f.p/'gate-target';ready=f.p/'ready'
    args=SHELL+['-c',f.script('vward_lock_gate_enter "$1" || exit $?; : > "$2"; sleep 30'),'owner',*map(str,f.libs),str(path),str(ready)]
    p=subprocess.Popen(args,env=f.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    try:
        until(ready)
    finally:stop(p)
    r=f.run(f.script('vward_lock_gate_enter "$1" && vward_lock_gate_leave "$1"'),*f.libs,path)
    assert r.returncode==0,(r.returncode,r.stderr,'SIGKILL left an eternal reclaimer')
    assert not (f.p/'.reclaim').exists()

with PipelineFixture() as f:
    path=f.p/'legacy.lock';path.mkdir(mode=0o700)
    dead=subprocess.Popen(['true']);dead.wait();(path/'pid').write_text(str(dead.pid)+'\n')
    paused=f.p/'paused';resume=f.p/'resume';held=f.p/'held';entered=f.p/'entered'
    shim=f.p/'bin';shim.mkdir()
    rm=shim/'rm';rm.write_text('''#!/bin/sh
case "$*" in *legacy.lock) : > "$PAUSED";while [ ! -f "$RESUME" ];do sleep .02;done ;; esac
exec /bin/rm "$@"
''');rm.chmod(0o755)
    command='dir_lock "$1" || exit $?; : > "$2"; sleep 30'
    p=subprocess.Popen(SHELL+['-c',f.script(command),'reclaim',*map(str,f.libs),str(path),str(held)],
        env=f.env|{'PAUSED':str(paused),'RESUME':str(resume),'PATH':str(shim)+':'+f.env['PATH']},stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    q=None
    try:
        until(paused)
        q=subprocess.Popen(SHELL+['-c',f.script('dir_lock "$1" || exit $?; : > "$2"; sleep 30'),'contender',*map(str,f.libs),str(path),str(entered)],
            env=f.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        time.sleep(.4)
        assert not entered.exists(),'a second contender entered during stale reclaim'
        resume.touch();until(held);time.sleep(.25)
        assert not entered.exists(),'stale reclaimer erased/replaced another live owner'
        pid=int((path/'pid').read_text());os.kill(pid,0)
    finally:
        stop(q);stop(p)

# Kill ONLY the gate holder while its real rm child is paused. The child
# remains the final writer, so its ticket must fence every new acquirer.
with PipelineFixture() as f:
    path=f.p/'legacy.lock';path.mkdir(mode=0o700)
    dead=subprocess.Popen(['true']);dead.wait();(path/'pid').write_text(str(dead.pid)+'\n')
    paused=f.p/'paused';resume=f.p/'resume';shim=f.p/'bin';shim.mkdir()
    rm=shim/'rm';rm.write_text('''#!/bin/sh
case "$*" in *legacy.lock) echo $$ > "$PAUSED";while [ ! -f "$RESUME" ];do sleep .02;done ;; esac
exec /bin/rm "$@"
''');rm.chmod(0o755)
    p=subprocess.Popen(SHELL+['-c',f.script('vward_lock_take "$1"'),'parent',*map(str,f.libs),str(path)],
        env=f.env|{'PAUSED':str(paused),'RESUME':str(resume),'PATH':str(shim)+':'+f.env['PATH']},
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    try:
        until(paused);worker=int(paused.read_text());os.kill(p.pid,signal.SIGKILL);p.wait(timeout=5)
        os.kill(worker,0)
        r=f.invoke('vward_lock_take',path)
        assert r.returncode!=0,'orphan final rm lost its exclusion lease'
        assert (path/'pid').read_text()==str(dead.pid)+'\n','contender replaced the lock under a live final rm'
        resume.touch()
        end=time.monotonic()+5
        from pathlib import Path
        while time.monotonic()<end:
            stat=Path(f'/proc/{worker}/stat')
            if not stat.exists() or stat.read_text().rsplit(') ',1)[1].split()[0]=='Z':break
            time.sleep(.02)
        r=f.invoke('vward_lock_take',path)
        assert r.returncode==0,(r.returncode,r.stderr,'a completed final writer blocked recovery forever')
    finally:stop(p)

# Release must use the same protocol; even a v1 caller cannot pass a live
# final v2 release utility merely because its parent died.
with PipelineFixture() as f:
    j=f.p/'locks';j.mkdir(mode=0o700);path=j/'.lock'
    paused=f.p/'paused';resume=f.p/'resume';shim=f.p/'bin';shim.mkdir()
    rm=shim/'rm';rm.write_text('''#!/bin/sh
if [ "$*" = "-rf $MATCH" ];then echo $$ > "$PAUSED";while [ ! -f "$RESUME" ];do sleep .02;done;fi
exec /bin/rm "$@"
''');rm.chmod(0o755)
    p=subprocess.Popen(SHELL+['-c',f.script('vrj2_lock "$1" && vrj2_unlock "$1"'),'release',*map(str,f.libs),str(j)],
        env=f.env|{'PAUSED':str(paused),'RESUME':str(resume),'MATCH':str(path),'PATH':str(shim)+':'+f.env['PATH']},
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    q=None
    try:
        until(paused);worker=int(paused.read_text());os.kill(p.pid,signal.SIGKILL);p.wait(timeout=5)
        r=f.invoke('vrj_lock',j)
        assert r.returncode==75 and path.exists(),'v1 bypassed an orphan v2 release utility'
        r=f.invoke('vrj2_lock',j)
        assert r.returncode==75 and path.exists(),'v2 bypassed an orphan release utility'
        resume.touch()
        end=time.monotonic()+5
        from pathlib import Path
        while time.monotonic()<end:
            stat=Path(f'/proc/{worker}/stat')
            if not stat.exists() or stat.read_text().rsplit(') ',1)[1].split()[0]=='Z':break
            time.sleep(.02)
        held=f.p/'new-held'
        q=subprocess.Popen(SHELL+['-c',f.script('vrj2_lock "$1" || exit $?; : > "$2";sleep 30'),'new',*map(str,f.libs),str(j),str(held)],
            env=f.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        until(held)
        assert path.exists() and int((path/'pid').read_text())==q.pid,'delayed old release erased the new owner'
        r=f.invoke('vrj_lock',j)
        assert r.returncode==75 and path.exists(),'v1 stole a live v2 lock'
    finally:stop(q);stop(p)
print('B_LOCK_ELECTION=PASS actual legacy stale-reclaim serialization, live owner preserved, killed gate owner recoverable')
