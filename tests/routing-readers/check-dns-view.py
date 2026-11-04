#!/usr/bin/env python3
"""Native DNS observations remain references, including global capacity slots."""
import os
from pathlib import Path
from fixture import Fixture,READ,OBSERVE,SNAP,AUDIT,LIBDIR
with Fixture() as f:
    inputs=f.p/'decision';inputs.mkdir(mode=0o700)
    for name in ('version','choices','bindings','evidence','policies','saved','queue','tombstones','context','resources','proofs','upstreams'):
        (inputs/(name+'.tsv')).write_text('')
    (inputs/'version.tsv').write_text('routing-state\t2\n')
    (inputs/'choices.tsv').write_text('schema\t1\n')
    (inputs/'upstreams.tsv').write_text('url1\thttps://dns.example.test/dns-query\n')
    (inputs/'policies.tsv').write_text('policy1\tkeenetic\tavailable\tactive\tnone\t1\turl1\n')
    f.cfg.write_text('interface Wireguard0\n!\ndns-proxy\n    https upstream https://dns.example.test/dns-query domain x.example\n    https upstream https://other.example.test/dns-query\n!\n')
    stage=f.p/'stage';stage.mkdir(mode=0o700)
    agh=f.p/'agh.json';agh.write_text('{"upstream_dns":["9.9.9.9","[/a.example/b.example/]https://dns.example.test/dns-query"],"upstream_dns_file":""}\n')
    shim=f.p/'bin';shim.mkdir()
    if os.environ.get('RS6_BUSYBOX'):(shim/'awk').symlink_to(Path(os.environ['RS6_BUSYBOX']).resolve())
    env=f.env|{'VWARD_ROUTING_AGH_IMAGE':str(agh),'PATH':str(shim)+':'+os.environ['PATH']}
    r=f.run('. "$1"; . "$2"; . "$3"; vward_routing_consistent_read2 "$4" "$5"',READ,OBSERVE,SNAP,stage,inputs,env=env)
    assert r.returncode==0,(r.stdout,r.stderr)
    r=f.run('. "$1"; vr2_dns_view "$2"',LIBDIR/'vward-routing-project.sh',stage,env=env)
    assert r.returncode==0,(r.stdout,r.stderr)
    rows=[x.split('\t') for x in r.stdout.splitlines()]
    resources=[x for x in rows if x[0]=='dns']
    assert len(resources)==4,rows
    assert {x[3] for x in resources}=={'x.example','-','a.example','b.example'}
    assert all(x[8:]==['manual','reference','-'] for x in resources),'an observation granted ownership'
    assert ['backend','keenetic','known','2'] in rows,rows
    assert ['backend','agh','known','2'] in rows,rows
    assert 'https://' not in r.stdout,'private URLs leaked into normalized references'
    first=r.stdout
    native_id=next(x[1] for x in resources if x[3]=='x.example')
    witnesses={x[1]:x[2] for x in rows if x[0]=='witness'}
    assert native_id in witnesses,'native DNS has no exact content witness'
    f.cfg.write_text(f.cfg.read_text().replace(' domain x.example',' dnsm on ISP domain x.example'))
    x=f.run('. "$1"; . "$2"; . "$3"; vward_routing_consistent_read2 "$4" "$5"',READ,OBSERVE,SNAP,stage,inputs,env=env)
    assert x.returncode==0
    x=f.run('. "$1"; vr2_dns_view "$2"',LIBDIR/'vward-routing-project.sh',stage,env=env)
    changed_witnesses={x[1]:x[2] for x in (line.split('\t') for line in x.stdout.splitlines()) if x[0]=='witness'}
    assert changed_witnesses[native_id]!=witnesses[native_id],'owner metadata edit retained a DNS ownership witness'
    f.cfg.write_text(f.cfg.read_text().replace(' dnsm on ISP domain x.example',' domain x.example'))
    x=f.run('. "$1"; . "$2"; . "$3"; vward_routing_consistent_read2 "$4" "$5"',READ,OBSERVE,SNAP,stage,inputs,env=env)
    assert x.returncode==0
    r=f.run('. "$1"; vr2_dns_view "$2"',LIBDIR/'vward-routing-project.sh',stage,env=env)
    assert r.stdout==first
    # Policy/URL key is a logical reference, not physical content identity.
    # Renaming that key preserves the native binding, while editing the URL
    # changes the content witness even if the logical key remains unchanged.
    (inputs/'upstreams.tsv').write_text('url2\thttps://dns.example.test/dns-query\n')
    (inputs/'policies.tsv').write_text('policy1\tkeenetic\tavailable\tactive\tnone\t1\turl2\n')
    def view():
        x=f.run('. "$1"; . "$2"; . "$3"; vward_routing_consistent_read2 "$4" "$5"',READ,OBSERVE,SNAP,stage,inputs,env=env)
        assert x.returncode==0,(x.stdout,x.stderr)
        x=f.run('. "$1"; vr2_dns_view "$2"',LIBDIR/'vward-routing-project.sh',stage,env=env)
        assert x.returncode==0,(x.stdout,x.stderr)
        return {p[3]:p for p in (r.split('\t') for r in x.stdout.splitlines()) if p[0]=='dns'}
    same=view();old={p[3]:p for p in resources}
    assert same['x.example'][2]==old['x.example'][2],'a logical key rename changed native identity'
    for p in (inputs/'upstreams.tsv',f.cfg,agh):
        p.write_text(p.read_text().replace('dns.example.test','replacement.example.test'))
    changed=view()
    assert changed['x.example'][2]!=same['x.example'][2],'physical URL edit retained an old content witness'
    # Restore the same native bytes for the CRLF test below.
    for p in (inputs/'upstreams.tsv',f.cfg,agh):
        p.write_text(p.read_text().replace('replacement.example.test','dns.example.test'))
    (inputs/'upstreams.tsv').write_text('url1\thttps://dns.example.test/dns-query\n')
    (inputs/'policies.tsv').write_text('policy1\tkeenetic\tavailable\tactive\tnone\t1\turl1\n')
    f.cfg.write_bytes(f.cfg.read_bytes().replace(b'\n',b'\r\n'))
    r=f.run('. "$1"; . "$2"; . "$3"; vward_routing_consistent_read2 "$4" "$5"',READ,OBSERVE,SNAP,stage,inputs,env=env)
    assert r.returncode==0,(r.stdout,r.stderr)
    r=f.run('. "$1"; vr2_dns_view "$2"',LIBDIR/'vward-routing-project.sh',stage,env=env)
    assert r.returncode==0 and r.stdout==first,'CRLF hid existing native DNS references/slots'
print('B_DNS_VIEW=PASS native+AGH shared rows/global slots, reference-only, deterministic opaque IDs')
