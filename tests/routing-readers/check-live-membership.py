#!/usr/bin/env python3
"""Catalog changes withdraw membership authority; own off stays reachable."""
import json
from live_fixture import LiveFixture

fail=[]
for scenario in ('domain-retired','service-retired'):
    with LiveFixture() as f:
        (f.live/'decision/bindings.tsv').write_text('')
        f.install_console()
        foreign='object-group fqdn Owner\n    include foreign.example\n!\n'
        f.native.write_text(f.native.read_text().replace('dns-proxy\n','dns-proxy\n    route object-group Owner ISP auto\n')+foreign)
        r=f.console('service','on','svc','Wireguard0')
        assert r.returncode==0,(scenario,'initial on',r.returncode,r.stdout,r.stderr)
        catalog=f.prefix/'opt/var/lib/vward/services/catalog.json'
        c=json.loads(catalog.read_text())
        if scenario=='domain-retired':
            c['services'][0]['domains']=['new.example']
        else:c['services']=[s for s in c['services'] if s['id']!='svc']
        catalog.write_text(json.dumps(c))
        before=f.native.read_bytes();choices=(f.live/'decision/choices.tsv').read_bytes()
        if scenario=='domain-retired':
            r=f.console('service','on','svc','Wireguard0')
            if not (r.returncode!=0 and f.native.read_bytes()==before and (f.live/'decision/choices.tsv').read_bytes()==choices):
                fail.append((scenario,'stale membership still authorized a native write',r.returncode,r.stdout,r.stderr))
        else:
            group=(f.etc/'services/enabled.tsv').read_text().split('\t')[1]
            proof=f.etc/'services/owned'/group;content=proof.read_bytes();mode=proof.stat().st_mode&0o777
            proof.unlink()
            r=f.console('service','off','svc')
            assert r.returncode!=0 and f.native.read_bytes()==before,'withdrawal accepted a group without its native private proof'
            proof.write_bytes(content);proof.chmod(mode)
            r=f.console('service','off','svc')
            if not (r.returncode==0 and 'object-group fqdn domain-list' not in f.native.read_text() and foreign in f.native.read_text() and (f.etc/'services/enabled.tsv').read_text()==''):
                fail.append((scenario,'own withdrawal became unreachable',r.returncode,r.stdout,r.stderr))
            else:
                before=f.native.read_bytes()
                r=f.console('service','off','svc')
                if not (r.returncode==0 and 'result=unchanged' in r.stdout and f.native.read_bytes()==before):
                    fail.append((scenario,'repeated withdrawal became an error',r.returncode,r.stdout,r.stderr))
assert not fail,fail
print('LIVE_MEMBERSHIP=PASS retired catalog membership never authorizes on; explicit off removes exact own S scope, preserves foreign')
