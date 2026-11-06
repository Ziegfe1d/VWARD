#!/usr/bin/env python3
"""Lost native DNS replies/capacity/shared URL cannot become success or ownership."""
import shutil
from live_fixture import LiveFixture


def seeded(f):
    f.configure_dns('keenetic')
    for name in ('policies','upstreams','context','bindings'):
        shutil.copy2(f.decision/(name+'.tsv'),f.live/'decision'/(name+'.tsv'))

with LiveFixture() as f:
    seeded(f)
    command='dns-proxy https upstream https://dns.example.test/dns-query dnsm domain x.example'
    (f.p/'native-lost-reply').write_text(command)
    r=f.invoke('vward_routing_live_service','lost','svc','dns','ISP','policy1',0)
    assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    assert 'domain x.example' in f.native.read_text() and 'domain y.example' not in f.native.read_text(),'unknown response advanced another command'
    assert f.native.read_bytes()!=f.startup.read_bytes(),'unknown DNS write was saved'
    assert (f.live/'decision/choices.tsv').read_text()=='schema\t1\n'
    pending=list((f.live/'journal/lost').glob('native.*/request.pending'))
    assert pending and (f.live/'journal/lost/state').read_text()=='unknown\n'
    image=f.native.read_bytes();calls=f.calls.read_text()
    r=f.invoke('vward_routing_live_service','retry','svc','dns','ISP','policy1',0)
    assert r.returncode==75 and f.calls.read_text()==calls and f.native.read_bytes()==image
    r=f.invoke('vward_routing_live_recover','lost','compensate')
    assert r.returncode==75 and f.calls.read_text()==calls and f.native.read_bytes()==image
    assert all(p.exists() for p in pending),'unknown native evidence was removed'

with LiveFixture() as f:
    seeded(f)
    rows=''.join(f'    https upstream https://foreign{i}.example.test/dns-query domain keep{i}.example\n' for i in range(8))
    f.native.write_text(f.native.read_text().replace('dns-proxy\n','dns-proxy\n'+rows))
    image=f.native.read_bytes()
    r=f.invoke('vward_routing_live_service','full','svc','dns','ISP','policy1',0)
    assert r.returncode==75 and f.native.read_bytes()==image,(r.returncode,r.stdout,r.stderr)
    assert all(x.endswith('\tshow running-config') for x in f.calls.read_text().splitlines()),'capacity refusal wrote transport'

with LiveFixture() as f:
    seeded(f)
    r=f.invoke('vward_routing_live_service','own','svc','dns','ISP','policy1',0)
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    # An independent owner adds a neighbour AFTER our successful publication.
    foreign='    https upstream https://dns.example.test/dns-query dnsm domain owner.example\n'
    f.native.write_text(f.native.read_text().replace('dns-proxy\n','dns-proxy\n'+foreign))
    before=f.native.read_bytes();calls=f.calls.read_text().splitlines()
    r=f.invoke('vward_routing_live_service','conflict','svc','vpn','VPN:Wireguard0','default',1)
    assert r.returncode==75 and f.native.read_bytes()==before,(r.returncode,r.stdout,r.stderr)
    assert all(x.endswith('\tshow running-config') for x in f.calls.read_text().splitlines()[len(calls):]),'foreign shared URL was withdrawn'
    assert '\tdns\tISP\tpolicy1\t' in (f.live/'decision/choices.tsv').read_text(),'refusal erased accepted DNS intent'
print('LIVE_KEENETIC_DNS_FAULTS=PASS real lost ACK persistent/no forward replay/no inverse; capacity8; foreign-after-own shared URL preserved')
