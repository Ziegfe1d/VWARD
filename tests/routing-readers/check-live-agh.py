#!/usr/bin/env python3
"""Existing AGH locked worker over real curl/HTTP, not a DATA rename receipt."""
import json
from agh_live_fixture import AghLiveFixture

with AghLiveFixture() as f:
    baseline=json.loads(f.agh.read_text())
    foreign='[/owner.example/]https://dns.example.test/dns-query'
    baseline['upstream_dns'].append(foreign);f.agh.write_text(json.dumps(baseline))
    native=f.native.read_bytes()
    r=f.invoke('vward_routing_live_service','dns','svc','dns','ISP','policy1',0)
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    state=json.loads(f.agh.read_text())
    assert state['upstream_dns'][0]=='9.9.9.9' and any('x.example' in x for x in state['upstream_dns']),state
    assert any(c[0]=='POST' for c in f.http_calls),'no physical HTTP request completed'
    assert f.native.read_bytes()==native and f.startup.read_bytes()==native
    assert all(x.endswith('\tshow running-config') for x in f.calls.read_text().splitlines()),'AGH-only action wrote/saved unrelated native config'
    assert (f.live/'journal/dns/state').read_text()=='committed\n'
    dto=json.loads((f.live/'journal/dns/prepared/outcome.json').read_text())
    assert dto['activation']=='live' and dto['client_path_verified'] is False
    assert not (f.live/'journal/.emu').exists()
    posts=sum(c[0]=='POST' for c in f.http_calls);native_calls=f.calls.read_text()
    r=f.invoke('vward_routing_live_service','repeat','svc','dns','ISP','policy1',1)
    assert r.returncode==0 and 'unchanged' in r.stdout,(r.returncode,r.stdout,r.stderr)
    assert sum(c[0]=='POST' for c in f.http_calls)==posts and all(x.endswith('\tshow running-config') for x in f.calls.read_text().splitlines()[len(native_calls.splitlines()):])
    for op,mode,target,policy,rev in (
        ('vpn','vpn','VPN:Wireguard1','default',1),('isp','isp','ISP','default',2),
        ('dnsagain','dns','ISP','policy1',3),('auto','auto','-','-',4)):
        r=f.invoke('vward_routing_live_service',op,'svc',mode,target,policy,rev)
        assert r.returncode==0,(op,r.returncode,r.stdout,r.stderr)
        state=json.loads(f.agh.read_text())
        assert foreign in state['upstream_dns'] and state['protection_enabled'] is True,(op,state)
        assert (f.live/'journal'/op/'state').read_text()=='committed\n',op
        assert f.native.read_bytes()==f.startup.read_bytes(),op
        if mode!='dns':assert state==baseline,(op,state)
    assert f.native.read_bytes()==native and json.loads(f.agh.read_text())==baseline
print('LIVE_AGH=PASS real curl HTTP/common J2 DNS-repeat-VPN-ISP-DNS-Auto/readback/save; foreign same-URL neighbour/settings preserved, no DATA ACK')
