#!/usr/bin/env python3
"""Actual common DNS/VPN/ISP/Auto actions over an external native process."""
from live_fixture import LiveFixture
import shutil

def why(f):
    return [(str(p.relative_to(f.live)),p.read_text()[:1000])
            for p in f.live.rglob('*') if p.is_file() and p.name in ('typed','read.status','state')]

with LiveFixture() as f:
    f.configure_dns('keenetic')
    for name in ('policies','upstreams','context','bindings'):
        shutil.copy2(f.decision/(name+'.tsv'),f.live/'decision'/(name+'.tsv'))
    # Foreign neighbours are deliberately on another URL and must survive every
    # real URL-wide deletion; the next test covers a conflicting shared URL.
    keep='    https upstream https://foreign.example.test/dns-query domain owner.example\n'
    f.native.write_text(f.native.read_text().replace('dns-proxy\n','dns-proxy\n'+keep))
    for op,action,target,dns,rev in (
        ('dns','dns','ISP','policy1',0),('vpn','vpn','VPN:Wireguard0','default',1),
        ('isp','isp','ISP','default',2),('back','dns','ISP','policy1',3),('auto','auto','-','-',4)):
        r=f.invoke('vward_routing_live_service',op,'svc',action,target,dns,rev)
        assert r.returncode==0,(op,r.returncode,r.stdout,r.stderr,why(f))
        assert keep in f.native.read_text() and f.native.read_bytes()==f.startup.read_bytes(),op
        assert (f.live/'journal'/op/'state').read_text()=='committed\n',op
        if action=='dns':
            assert 'https://dns.example.test/dns-query dnsm domain x.example' in f.native.read_text(),op
            assert 'https://dns.example.test/dns-query dnsm domain y.example' in f.native.read_text(),op
            assert 'route object-group domain-list' not in f.native.read_text(),op
        else:assert 'https://dns.example.test/dns-query' not in f.native.read_text(),op
    assert '\tauto\t-\t-\t' in (f.live/'decision/choices.tsv').read_text()
print('LIVE_KEENETIC_DNS=PASS actual native DNS-VPN-ISP-DNS-Auto/readback/save, foreign other URL preserved; no DATA ACK')
