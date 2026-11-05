#!/usr/bin/env python3
"""Server withdrawal also prunes actual legacy return/proof/profile formats."""
from fixture import PipelineFixture

for store in ('keenetic','agh'):
    with PipelineFixture() as f:
        f.configure_dns(store)
        old='https://dns.example.test/dns-query';new='https://replacement.example.test/dns-query'
        other='https://other.example.test/dns-query'
        p=f.decision/'upstreams.tsv';p.write_text(p.read_text()+'replacement\t'+new+'\n')
        raw=f.e/'route-engine/domain-lists';raw.mkdir(parents=True,mode=0o700)
        proofs=f.e/'route-engine/domain-lists.dns';proofs.mkdir(mode=0o700)
        saved=raw/'domain-list0';saved.write_text('route=ISP\tauto\nsmartdns_config='+'0'*64+'\n'+
            f'doh=https upstream {old} domain x.example\nagh=y.example\t{old}\n'+f'doh=https upstream {other} domain owner.example\n')
        saved.chmod(0o400)
        proof=proofs/'domain-list0';proof.write_text(f'D https upstream {old} domain x.example\nD https upstream {other} domain owner.example\n');proof.chmod(0o600)
        owner=raw/'domain-list42';owner.write_text(f'route=Wireguard1\tauto\nagh=other.example\t{other}\n');owner.chmod(0o400)
        profile=f.e/'smartdns.conf';profile.write_text(f'SMARTDNS_URL={old}\nSMARTDNS_STORE={store}\nOWNER_KEY=preserved\n');profile.chmod(0o400)
        owner_bytes=owner.read_bytes()
        r=f.invoke('vward_routing_pipeline2',f.j,'seed','svc','dns','ISP','policy1',0)
        assert r.returncode==0,(store,r.returncode,r.stdout,r.stderr)
        r=f.invoke('vward_routing_server2',f.j,'replace','policy1','replace','replacement',1)
        assert r.returncode==0,(store,r.returncode,r.stdout,r.stderr)
        assert old not in saved.read_text()+proof.read_text(),'old legacy return/proof can resurrect a withdrawn server'
        assert f'SMARTDNS_URL={new}\n' in profile.read_text(),'selected legacy profile did not migrate'
        assert saved.read_text().startswith('route=ISP\tauto\nsmartdns_config=')
        assert other in saved.read_text() and other in proof.read_text()
        assert owner.read_bytes()==owner_bytes and owner.stat().st_mode&0o777==0o400
        assert saved.stat().st_mode&0o777==0o400 and profile.stat().st_mode&0o777==0o400
        # Reintroduced stale NEW saved rows are input observations, never proof
        # of another backend grant; withdrawing NEW must remove them too.
        saved.chmod(0o600)
        saved.write_text(saved.read_text()+f'agh=x.example\t{new}\n')
        saved.chmod(0o400)
        r=f.invoke('vward_routing_server2',f.j,'delete','policy1','delete','-',2)
        assert r.returncode==0,(store,r.returncode,r.stdout,r.stderr)
        assert new not in saved.read_text()+proof.read_text()+profile.read_text()
        assert profile.read_text()==f'SMARTDNS_STORE={store}\nOWNER_KEY=preserved\n'
        assert owner.read_bytes()==owner_bytes and other in saved.read_text()
        assert not f.trace.exists()
print('B_LEGACY_SERVER=PASS actual return/D proofs/profile pruned in both stores, other URI/manual bytes/modes preserved')
