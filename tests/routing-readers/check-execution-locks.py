#!/usr/bin/env python3
"""New OFF coordinator and actual legacy console share the SAME lock paths."""
import os,signal,subprocess,time
from fixture import PipelineFixture,SHELL

with PipelineFixture() as f:
    r=f.run(f.script('umask 022; vrb_envelope "$@"'),*f.libs,f.j,'prepare');assert r.returncode==0,(r.returncode,r.stderr)
    lock=f.e/'root/tmp/vward-console-edit.lock'
    # Existing legacy record (pid only), held by this live test process.
    lock.mkdir(mode=0o700);(lock/'pid').write_text(str(os.getpid())+'\n')
    before=(f.e/'running.cfg').read_bytes()
    r=f.invoke('vward_routing_pipeline2',f.j,'legacybusy','svc','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==75,(r.returncode,r.stdout,r.stderr)
    assert (lock/'pid').read_text()==str(os.getpid())+'\n'
    assert (f.e/'running.cfg').read_bytes()==before and not (f.e/'calls').exists()
    (lock/'pid').unlink();lock.rmdir()
    # An abandoned unproven record is unknown, not new ownership.
    lock.mkdir(mode=0o700)
    r=f.invoke('vward_routing_pipeline2',f.j,'unproven','svc','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==75 and lock.exists(),'empty legacy reservation was stolen'
print('B_LEGACY_LOCK=PASS same default paths, live/empty legacy holders refuse before writes')

with PipelineFixture() as f:
    (f.e/'publish-pause').touch()
    cmd=f.script('vward_routing_pipeline2 "$@"')
    args=[str(f.j),'owner','svc','vpn','VPN:Wireguard0','default','0']
    proc=subprocess.Popen(SHELL+['-c',cmd,'owner',*map(str,f.libs),*args],env=f.env,
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    contender=None
    try:
        deadline=time.monotonic()+8
        while not (f.e/'publish-waiting').exists() and time.monotonic()<deadline:time.sleep(.03)
        assert (f.e/'publish-waiting').exists(),'coordinator never acquired shared lock'
        lock=f.e/'root/tmp/vward-console-edit.lock';signal_path=f.e/'legacy-entered'
        contender=subprocess.Popen(SHELL+['-c',f.script('dir_lock "$1" && : > "$2"'),'legacy',*map(str,f.libs),str(lock),str(signal_path)],
                                   env=f.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        time.sleep(1.2)
        assert contender.poll() is None and not signal_path.exists(),'actual legacy worker entered over the B holder'
        r=f.invoke('vward_routing_pipeline2',f.j,'second','svc','vpn','VPN:Wireguard0','default',0)
        assert r.returncode==75,(r.returncode,r.stdout,r.stderr)
        assert not (f.j/'second').exists(),'competing operation reached a child journal'
    finally:
        for child in (contender,proc):
            if child is not None:
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                child.wait(timeout=8)
print('B_SHARED_LOCK=PASS actual legacy dir_lock waits; competing B operation cannot enter')
