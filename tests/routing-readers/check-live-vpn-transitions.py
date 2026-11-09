#!/usr/bin/env python3
"""One/two/three discovered VPNs through the actual common native transport."""
from live_fixture import LiveFixture

def writes(f):
    return [x.split('\t',1)[1] for x in f.calls.read_text().splitlines() if not x.endswith('\tshow running-config')]

for count in (1,2,3):
    with LiveFixture(vpns=count) as f:
        owner='object-group fqdn Owner\n    include outside.example\n!\n'
        f.native.write_text(f.native.read_text().replace('dns-proxy\n','dns-proxy\n    route object-group Owner ISP auto\n')+owner)
        revision=0
        sequence=([0] if count==1 else [0,1,0] if count==2 else [0,1,2,0])
        for index,tunnel in enumerate(sequence):
            r=f.invoke('vward_routing_live_service','vpn'+str(index),'svc','vpn','VPN:Wireguard'+str(tunnel),'default',revision)
            assert r.returncode==0,(count,tunnel,r.returncode,r.stdout,r.stderr)
            revision+=1
            assert owner in f.native.read_text(),'foreign manual group changed'
            rows=[r.split('\t') for r in (f.etc/'services/enabled.tsv').read_text().splitlines() if r.startswith('svc\t')]
            assert len(rows)==1 and rows[0][2]=='Wireguard'+str(tunnel),(count,index,rows)
            assert f'route object-group {rows[0][1]} Wireguard{tunnel} auto' in f.native.read_text(),(count,index,rows,f.native.read_text())
            assert (f.etc/'services/owned'/rows[0][1]).is_file(),'applied registry lost its exact own proof'
            assert f.startup.read_bytes()==f.native.read_bytes()
            before=f.native.read_bytes();attempts=writes(f)
            r=f.invoke('vward_routing_live_service','repeat'+str(index),'svc','vpn','VPN:Wireguard'+str(tunnel),'default',revision)
            assert r.returncode==0 and 'unchanged' in r.stdout,(count,tunnel,r.returncode,r.stdout,r.stderr)
            assert f.native.read_bytes()==before and writes(f)==attempts,'repeat rewrote native state'
        r=f.invoke('vward_routing_live_service','off','svc','off','-','-',revision)
        assert r.returncode==0,(count,r.returncode,r.stdout,r.stderr)
        assert owner in f.native.read_text() and 'object-group fqdn domain-list' not in f.native.read_text()
        assert (f.etc/'services/enabled.tsv').read_text()==''
        choice=(f.live/'decision/choices.tsv').read_text()
        assert '\tauto\t-\t-\t' in choice and '\tisp\t' not in choice,choice
        before=f.native.read_bytes();attempts=writes(f)
        r=f.invoke('vward_routing_live_service','missing','svc','vpn','VPN:Wireguard77','default',revision+1)
        assert r.returncode==75 and f.native.read_bytes()==before and writes(f)==attempts, 'missing explicit tunnel silently fell back'
print('LIVE_VPN_TRANSITIONS=PASS 1/2/3 VPN; A-B-C-A/repeat/S-off != ISP; actual native+startup/registry; manual preservation/missing target refusal')
