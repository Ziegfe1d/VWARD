#!/usr/bin/env python3
"""Each significant native/local step refuses, then only its own prefix undoes."""
from fixture import PipelineFixture,digest
native=['object-group fqdn domain-list0',
        'object-group fqdn domain-list0 include x.example',
        'object-group fqdn domain-list0 include y.example',
        'dns-proxy route object-group domain-list0 Wireguard0 auto']
local=['domain-list0','resources','proofs','choices','enabled']
for kind,values in [('refuse',native),('local-fails',local)]:
    for i,value in enumerate(values):
        with PipelineFixture() as f:
            op='fault'+str(i)
            before=digest(f.decision);config=(f.e/'running.cfg').read_bytes()
            owner=f.e/'owner-kept';owner.write_bytes(b'foreign bytes\n');owner.chmod(0o400)
            (f.e/kind).write_text(value+'\n')
            r=f.invoke('vward_routing_pipeline2',f.j,op,'svc','vpn','VPN:Wireguard0','default',0)
            assert r.returncode==3,(kind,value,r.returncode,r.stdout,r.stderr)
            assert (f.j/op/'state').read_text()=='unknown\n',(kind,value,'partial success escaped the parent barrier')
            assert f.invoke('vward_routing_update_eligibility2',f.j).returncode==75
            (f.e/kind).unlink()
            r=f.invoke('vward_routing_pipeline_recover2',f.j,op,'compensate')
            assert r.returncode==0,(kind,value,r.returncode,r.stdout,r.stderr)
            assert digest(f.decision)==before and (f.e/'running.cfg').read_bytes()==config,(kind,value,'baseline was not byte exact')
            assert not list((f.e/'services/owned').iterdir()) and (f.e/'services/enabled.tsv').read_bytes()==b''
            assert owner.read_bytes()==b'foreign bytes\n' and owner.stat().st_mode&0o777==0o400
            assert (f.j/op/'state').read_text()=='compensated\n'
            assert f.invoke('vward_routing_update_eligibility2',f.j).returncode==0
            r=f.invoke('vward_routing_pipeline2',f.j,op,'svc','vpn','VPN:Wireguard0','default',0)
            assert r.returncode==75,'compensated operation ID was replayed'
            assert digest(f.decision)==before and (f.e/'running.cfg').read_bytes()==config
print('B_STEP_FAULTS=PASS 4 native commands + 5 local steps, global barrier, exact prefix compensation/foreign0400/reused-ID refusal')
