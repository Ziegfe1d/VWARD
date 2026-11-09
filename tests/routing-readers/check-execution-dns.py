#!/usr/bin/env python3
"""Both existing DNS workers on the SAME snapshot/policy/J2 execution path."""
import json
from fixture import PipelineFixture

for store in ('keenetic','agh'):
    with PipelineFixture() as f:
        f.configure_dns(store)
        # An unrelated server and the plain resolver must survive all moves.
        p=f.e/'running.cfg';p.write_text(p.read_text().replace('dns-proxy\n','dns-proxy\n    https upstream https://other.example.test/dns-query\n'))
        original=p.read_bytes();agh_original=(f.e/'agh.json').read_bytes()
        def call(op,mode='dns',target='ISP',policy='policy1',rev=0):
            return f.invoke('vward_routing_pipeline2',f.j,op,'svc',mode,target,policy,rev)
        r=call('dns');assert r.returncode==0,(store,r.returncode,r.stdout,r.stderr)
        proof=(f.decision/'proofs.tsv').read_text()
        assert all(len(x.split('\t')[10].split(':')[1])==48 for x in proof.splitlines()),proof
        before=p.read_bytes();agh_before=(f.e/'agh.json').read_bytes()
        calls=(f.e/'calls').read_bytes() if (f.e/'calls').exists() else b''
        api_calls=(f.e/'agh.calls').read_bytes() if (f.e/'agh.calls').exists() else b''
        r=call('repeat',rev=1);assert r.returncode==0,(store,'repeat',r.returncode,r.stdout,r.stderr)
        assert p.read_bytes()==before and (f.e/'agh.json').read_bytes()==agh_before
        assert ((f.e/'calls').read_bytes() if (f.e/'calls').exists() else b'')==calls,'repeat wrote transport'
        assert ((f.e/'agh.calls').read_bytes() if (f.e/'agh.calls').exists() else b'')==api_calls,'repeat called AGH transport'
        r=call('vpn','vpn','VPN:Wireguard0','default',1)
        assert r.returncode==0,(store,'vpn',r.returncode,r.stdout,r.stderr)
        assert 'https://dns.example.test' not in p.read_text()
        assert not any('dns.example.test' in x for x in json.loads((f.e/'agh.json').read_text())['upstream_dns'])
        r=call('isp','isp','ISP','default',2);assert r.returncode==0,(store,'isp',r.returncode,r.stdout,r.stderr)
        assert p.read_bytes()==original
        assert json.loads((f.e/'agh.json').read_text())==json.loads(agh_original)
        r=call('dnsagain',rev=3);assert r.returncode==0,(store,'dnsagain',r.returncode,r.stdout,r.stderr)
        r=call('auto','auto','-','-',4);assert r.returncode==0,(store,'auto',r.returncode,r.stdout,r.stderr)
        assert p.read_bytes()==original
        assert json.loads((f.e/'agh.json').read_text())==json.loads(agh_original)
        assert not f.trace.exists()
print('B_DNS_EXECUTION=PASS both backends, exact witnesses, repeat, DNS/VPN/ISP/Auto, unrelated rows preserved')

with PipelineFixture() as f:
    f.configure_dns('agh');(f.e/'agh-lost').touch()
    before=(f.e/'running.cfg').read_bytes()
    r=f.invoke('vward_routing_pipeline2',f.j,'lost','svc','dns','ISP','policy1',0)
    assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    assert (f.j/'lost/state').read_text()=='unknown\n'
    assert list((f.j/'lost/dns-evidence').glob('*/request.pending')),'lost ACK lost its durable evidence'
    assert (f.decision/'choices.tsv').read_text()=='schema\t1\n'
    image=(f.e/'agh.json').read_bytes()
    r=f.invoke('vward_routing_pipeline_recover2',f.j,'lost','compensate')
    assert r.returncode==75,(r.returncode,r.stdout,r.stderr)
    assert (f.e/'agh.json').read_bytes()==image,'unknown request authorised an inverse'
    assert (f.e/'running.cfg').read_bytes()==before
print('B_AGH_UNKNOWN=PASS lost POST retains evidence and barrier; no forward replay or blind inverse')

for store in ('keenetic','agh'):
    with PipelineFixture() as f:
        f.configure_dns(store)
        cfg=(f.e/'running.cfg').read_bytes();agh=json.loads((f.e/'agh.json').read_text())
        (f.e/'local-fails').write_text('choices\n')
        r=f.invoke('vward_routing_pipeline2',f.j,'localfail','svc','dns','ISP','policy1',0)
        assert r.returncode==3,(store,r.returncode,r.stdout,r.stderr)
        assert (f.j/'localfail/state').read_text()=='unknown\n'
        r=f.invoke('vward_routing_pipeline_recover2',f.j,'localfail','compensate')
        assert r.returncode==0,(store,'inverse',r.returncode,r.stdout,r.stderr)
        assert (f.e/'running.cfg').read_bytes()==cfg
        assert json.loads((f.e/'agh.json').read_text())==agh
        assert (f.decision/'resources.tsv').read_text()=='' and (f.decision/'proofs.tsv').read_text()==''
        assert (f.decision/'choices.tsv').read_text()=='schema\t1\n'
        if store=='agh':assert not (f.e/'calls').exists(),'AGH/local-only inverse saved unrelated native configuration'
print('B_DNS_INVERSE=PASS failed local registration, own exact backend compensation, native persistence only when needed')

with PipelineFixture() as f:
    f.configure_dns('agh')
    r=f.invoke('vward_routing_pipeline2',f.j,'seed','svc','dns','ISP','policy1',0)
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    api=(f.e/'agh.calls').read_bytes();old_proofs=(f.decision/'proofs.tsv').read_text()
    (f.e/'agh.json').write_text('{"unknown":true}\n')
    p=f.decision/'bindings.tsv';p.write_text(p.read_text()+'other\tz.example\texact\tconfirmed\tipv4\tknown\n')
    r=f.invoke('vward_routing_pipeline2',f.j,'vpn-only','other','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert 'include z.example' in (f.e/'running.cfg').read_text()
    assert (f.e/'agh.calls').read_bytes()==api,'pure VPN reached an unrelated unknown AGH backend'
    assert set(old_proofs.splitlines()).issubset((f.decision/'proofs.tsv').read_text().splitlines()),'unrelated unknown DNS evidence was recreated'
print('B_ACTION_DEPENDENCIES=PASS unrelated unavailable AGH is neither adopted nor probed by a clean VPN transition')

with PipelineFixture() as f:
    f.configure_dns('keenetic')
    p=f.e/'running.cfg';p.write_text(p.read_text().replace('dns-proxy\n','dns-proxy\n'+''.join(f'    https upstream https://s{i}.example.test/dns-query\n' for i in range(8))))
    before=p.read_bytes()
    r=f.invoke('vward_routing_pipeline2',f.j,'capacity','svc','dns','ISP','policy1',0)
    assert r.returncode==75,(r.returncode,r.stdout,r.stderr)
    assert p.read_bytes()==before and not (f.e/'calls').exists(),'capacity refusal changed a foreign/global HTTPS row'
    assert not (f.j/'capacity').exists(),'capacity overflow reached a backend journal'
print('B_DNS_CAPACITY=PASS eight actual global rows hold the entire DNS transition before any write')
