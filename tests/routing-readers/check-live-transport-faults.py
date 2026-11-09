#!/usr/bin/env python3
"""Unknown real native completion holds J2/leases across parent-only death."""
import os
import signal
import subprocess
import time
from fixture import SHELL,LIBDIR
from live_fixture import LiveFixture

def until(path):
    end=time.monotonic()+8
    while not path.exists() and time.monotonic()<end:time.sleep(.02)
    assert path.exists(),path.name

with LiveFixture() as f:
    (f.p/'native-lost-reply').write_text('object-group fqdn domain-list0\n')
    r=f.invoke('vward_routing_live_service','lost','svc','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    assert b'object-group fqdn domain-list0' in f.native.read_bytes(),'lost-reply fixture did not really apply'
    assert (f.live/'journal/lost/state').read_text()=='unknown\n','matching prefix cleared unknown'
    assert list((f.live/'journal/lost').glob('native.*/request.pending')),'lost native response discarded private pending'
    before=f.native.read_bytes()
    r=f.invoke('vward_routing_live_service','retry','svc','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==75 and f.native.read_bytes()==before,('unknown autoreplayed',r.returncode,r.stderr)

with LiveFixture() as f:
    (f.p/'save-refuse').touch()
    r=f.invoke('vward_routing_live_service','save','svc','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==3 and (f.live/'journal/save/state').read_text()=='unknown\n',(r.returncode,r.stdout,r.stderr)
    assert f.startup.read_bytes()!=f.native.read_bytes(),'save failure was not injected'
    assert list((f.live/'journal/save').glob('native.*/request.pending'))

for phase in ('before','after'):
    with LiveFixture() as f:
        (f.p/('native-pause-'+phase)).write_text('object-group fqdn domain-list0\n')
        command=f.script('vward_routing_live_service killed svc vpn VPN:Wireguard0 default 0')
        p=subprocess.Popen(SHELL+['-c',command,'fixture',*map(str,f.libs)],env=f.env,
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        try:
            until(f.p/'native-paused')
            publisher=int((f.p/'native-paused').read_text())
            lock=f.prefix/'tmp/vward-console-edit.lock'
            coordinator=int((lock/'pid').read_text())
            assert coordinator!=publisher and coordinator!=p.pid,'fault did not isolate coordinator from actual publisher'
            leases=list((f.live/'journal/killed/workers').glob('*.'+str(publisher)+'.*'))
            assert any(not x.name.endswith('.sha') for x in leases),'actual NDMC process was not durably leased'
            os.kill(coordinator,signal.SIGKILL)
            before=f.native.read_bytes()
            r=f.invoke('vward_routing_live_service','contender','svc','vpn','VPN:Wireguard1','default',0)
            assert r.returncode==75 and f.native.read_bytes()==before,('live late transport was bypassed',r.returncode,r.stderr)
            (f.p/'native-resume').touch()
            p.communicate(timeout=8)
            # The late publisher may really finish, but no dead coordinator or
            # orphan worker may turn that into a forward/recovery commitment.
            assert b'object-group fqdn domain-list0' in f.native.read_bytes()
            assert (f.live/'journal/killed/state').read_text()!='committed\n'
            assert list((f.live/'journal/killed').glob('native.*/request.pending')),'orphan worker cleared pending after parent-only death'
            before=f.native.read_bytes()
            r=f.invoke('vward_routing_live_service','later','svc','vpn','VPN:Wireguard1','default',0)
            assert r.returncode==75 and f.native.read_bytes()==before
        finally:
            try:os.killpg(p.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            p.communicate(timeout=5)
print('LIVE_NATIVE_FAULTS=PASS real lost reply/save refusal; parent-only death before/after write retains native PID leases/J2/pending, no replay')
