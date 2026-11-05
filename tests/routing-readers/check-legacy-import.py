#!/usr/bin/env python3
"""Import actual deployed legacy files; data downgrade is not file rollback."""
from fixture import PipelineFixture,digest

with PipelineFixture() as f:
    # Deployed legacy has NO normalized B ledger. These are the actual native
    # registration/private proof/persist/return-state formats, not state1 TSVs.
    for p in f.decision.glob('*.tsv'):p.unlink()
    p=f.e/'running.cfg';p.write_text(p.read_text().replace('dns-proxy\n','dns-proxy\n    route object-group domain-list0 Wireguard0 auto\n    route object-group Owner ISP auto\n')+
        'object-group fqdn domain-list0\n    include x.example\n    include y.example\n!\nobject-group fqdn Owner\n    include owner.example\n!\n')
    p=f.e/'services/enabled.tsv';p.write_text('svc\tdomain-list0\tauto\n');p.chmod(0o644)
    p=f.e/'services/owned/domain-list0';p.write_text('include x.example\ninclude y.example\nroute=Wireguard0\tauto\n');p.chmod(0o400)
    (f.e/'catalog.json').write_text('{"schema":1,"services":[{"id":"svc","title":"Service","category":"ai","domains":["x.example","y.example"]}]}')
    (f.e/'route/adaptive-persist.txt').write_text('old.example\nx.example\n')
    (f.e/'route-engine').mkdir(mode=0o700)
    saved=f.e/'route-engine/domain-lists';saved.mkdir(mode=0o700)
    p=saved/'domain-list0';p.write_text('route=ISP\tauto\nsmartdns_config='+'0'*64+'\ndoh=https upstream https://old.example.test/dns-query domain x.example\nagh=y.example\thttps://other.example.test/dns-query\n');p.chmod(0o600)
    p=f.e/'smartdns.conf';p.write_text('SMARTDNS_URL=https://old.example.test/dns-query\nSMARTDNS_STORE=keenetic\n');p.chmod(0o600)
    legacy={p.relative_to(f.e): (p.read_bytes(),p.stat().st_mode&0o777) for p in f.e.rglob('*') if p.is_file()}
    r=f.invoke('vward_routing_pipeline2',f.j,'before-import','svc','off','-','-',0)
    assert r.returncode==75,'ordinary writer accepted missing B state'
    r=f.invoke('vward_routing_legacy_migrate2',f.j,'import')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    for path,(data,mode) in legacy.items():
        assert (f.e/path).read_bytes()==data and (f.e/path).stat().st_mode&0o777==mode,('migration changed native legacy',path)
    assert not (f.e/'calls').exists() and not f.trace.exists(),'import issued a backend write'
    assert (f.decision/'version.tsv').read_text()=='routing-state\t2\n'
    assert '\tvpn\tVPN:Wireguard0\tdefault\t' in (f.decision/'choices.tsv').read_text()
    evidence=(f.decision/'evidence.tsv').read_text()
    assert evidence and all('\t0\thistory\t0\t' in x for x in evidence.splitlines()),'persist became a fresh Auto proof'
    rows=(f.decision/'resources.tsv').read_text().splitlines()
    assert len(rows)==2 and all(x.split('\t')[8]=='vward' for x in rows)
    assert 'owner.example' not in (f.decision/'resources.tsv').read_text(),'manual group adopted'
    r=f.invoke('vward_routing_legacy_restore0',f.j,'import','downgrade')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert not list(f.decision.glob('*.tsv')),'old code did not receive the original absent B state'
    for path,(data,mode) in legacy.items():
        assert (f.e/path).read_bytes()==data and (f.e/path).stat().st_mode&0o777==mode
    r=f.invoke('vward_routing_legacy_migrate2',f.j,'import-again')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    r=f.invoke('vward_routing_pipeline2',f.j,'accept-off','svc','off','-','-',1)
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    before=digest(f.decision)
    r=f.invoke('vward_routing_legacy_restore0',f.j,'import-again','refuse-downgrade')
    assert r.returncode==75 and digest(f.decision)==before,'accepted state was silently lost on downgrade'
print('B_LEGACY_IMPORT=PASS actual registration/proof/persist/return states, manual preservation, history-only Auto, data guard/byte+mode exact downgrade/refusal')
