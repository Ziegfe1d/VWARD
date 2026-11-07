#!/usr/bin/env python3
"""Fixed installed coordinator uses a real child transport, never DATA publication as ACK."""
from live_fixture import LiveFixture
import json
import shlex

with LiveFixture() as f:
    before=f.native.read_bytes()
    r=f.invoke('vward_routing_live_service','live-on','svc','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert f.native.read_bytes()!=before and b'include x.example' in f.native.read_bytes()
    assert f.startup.read_bytes()==f.native.read_bytes(),'native save was not completed'
    assert '\tobject-group fqdn ' in f.calls.read_text(),'coordinator only changed DATA files'
    assert (f.live/'journal/live-on/state').read_text()=='committed\n'
    dto=json.loads((f.live/'journal/live-on/prepared/outcome.json').read_text())
    assert dto['activation']=='live' and dto['configured']['state']=='verified' and dto['client_path_verified'] is False,dto
    assert '\tnative\n' in r.stdout and 'emulated' not in r.stdout,r.stdout
    assert (f.etc/'services/enabled.tsv').read_text().startswith('svc\t')
    calls=f.calls.read_text().splitlines()
    reads=sum(x.endswith('\tshow running-config') for x in calls)
    mutations=len(calls)-reads
    steps=sum(x.startswith('step\t') for x in (f.live/'journal/live-on/plan').read_text().splitlines())
    # One before/after native read per physical command and per logical scope,
    # plus initial/final observations. Transport ACK readback must not cause
    # another identical query just to return that same result to its caller.
    assert reads<=2*mutations+2*steps+2,('redundant native reads',reads,mutations,steps)
    assert not (f.live/'journal/.emu').exists(),'live operation invented a DATA backend'
    assert not f.trace.exists(),'poisoned emulator transport used'

with LiveFixture() as f:
    # The normal device has an unqualified ndmc name and the profile's shell
    # wrapper. The final publisher must still exec the actual external utility
    # in its leased PID; it must not re-enter OLD admission for its own J2.
    f.env.pop('VWARD_NDMC',None);f.env.pop('NDMC',None)
    shim=f.p/'poison/ndmc'
    shim.write_text('#!/bin/sh\nexec '+shlex.quote(str(f.ndmc))+' "$@"\n');shim.chmod(0o755)
    r=f.invoke('vward_routing_live_service','default-ndmc','svc','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert (f.live/'journal/default-ndmc/state').read_text()=='committed\n'
    assert f.startup.read_bytes()==f.native.read_bytes() and b'include x.example' in f.native.read_bytes()
print('LIVE_TRANSPORT=PASS canonical installed state -> common plan/J2 -> actual child NDMC -> readback/save/registry')
