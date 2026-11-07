#!/usr/bin/env python3
"""One connected server replacement/deletion and withdrawal fence, both stores."""
import json
from fixture import PipelineFixture

for store in ('keenetic','agh'):
    with PipelineFixture() as f:
        f.configure_dns(store)
        p=f.decision/'upstreams.tsv';p.write_text(p.read_text()+'replacement\thttps://replacement.example.test/dns-query\n')
        p=f.e/'running.cfg';p.write_text(p.read_text().replace('dns-proxy\n','dns-proxy\n    https upstream https://other.example.test/dns-query\n'))
        original=p.read_bytes()
        r=f.invoke('vward_routing_pipeline2',f.j,'seed','svc','dns','ISP','policy1',0)
        assert r.returncode==0,(store,r.returncode,r.stdout,r.stderr)
        ids={x.split('\t')[3]:(x.split('\t')[1],x.split('\t')[9]) for x in (f.decision/'resources.tsv').read_text().splitlines()}
        r=f.invoke('vward_routing_server2',f.j,'replace','policy1','replace','replacement',1)
        assert r.returncode==0,(store,'replace',r.returncode,r.stdout,r.stderr)
        assert ids=={x.split('\t')[3]:(x.split('\t')[1],x.split('\t')[9]) for x in (f.decision/'resources.tsv').read_text().splitlines()},'endpoint replacement renamed resource/birth'
        own=p.read_text()+'\n'+(f.e/'agh.json').read_text()
        assert 'https://dns.example.test/' not in own and 'https://replacement.example.test/' in own
        assert 'https://other.example.test/' in p.read_text()
        gen=(f.j/'replace/generation').read_text().strip()
        (f.decision/'saved.tsv').write_text('svc\tpolicy1\t2\t'+gen+'\t1\t'+'1'*64+'\nother\tother-policy\t1\t'+gen+'\t0\t'+'2'*64+'\n')
        (f.decision/'queue.tsv').write_text('q1\tpolicy1\t2\tsvc\tx.example\tdns\tISP\tpolicy1\t1\t'+gen+'\nq2\tother-policy\t1\tother\tother.example\tdns\tISP\tother-policy\t0\t'+gen+'\n')
        (f.decision/'evidence.tsv').write_text('A\ta1\tx.example\texact\tISP\tpolicy1\t1\tactive\t1\tsvc\n')
        r=f.invoke('vward_routing_server2',f.j,'delete','policy1','delete','-',2)
        assert r.returncode==0,(store,'delete',r.returncode,r.stdout,r.stderr)
        assert p.read_bytes()==original
        assert json.loads((f.e/'agh.json').read_text())['upstream_dns']==['9.9.9.9']
        assert (f.decision/'resources.tsv').read_text()=='' and (f.decision/'proofs.tsv').read_text()==''
        assert '\tauto\t-\t-\t' in (f.decision/'choices.tsv').read_text()
        assert '\tpolicy1\t' not in (f.decision/'saved.tsv').read_text() and '\tpolicy1\t' not in (f.decision/'queue.tsv').read_text()
        assert 'other-policy' in (f.decision/'saved.tsv').read_text() and 'other-policy' in (f.decision/'queue.tsv').read_text()
        assert '\t0\thistory\t0\t' in (f.decision/'evidence.tsv').read_text()
        assert 'policy1\t3\tdeleted\n' in (f.decision/'tombstones.tsv').read_text()
        calls=(f.e/'calls').read_bytes() if (f.e/'calls').exists() else b''
        r=f.invoke('vward_routing_pipeline2',f.j,'afterdelete','svc','auto','-','-',2)
        assert r.returncode==0,(store,'restore',r.returncode,r.stdout,r.stderr)
        assert ((f.e/'calls').read_bytes() if (f.e/'calls').exists() else b'')==calls,'old evidence resurrected DNS'
        (f.decision/'tombstones.tsv').write_text('')
        r=f.invoke('vward_routing_pipeline2',f.j,'oldtomb','svc','auto','-','-',2)
        assert r.returncode==75,'old restored tombstone ledger bypassed a durable server withdrawal'
        assert not f.trace.exists()
print('B_SERVER_CHAIN=PASS both stores, stable identity replacement, own deletion, saved/queue/history withdrawal and no resurrection')
