#!/usr/bin/env python3
"""Logical service default follows captured category/default; an explicit pin wins."""
from fixture import Fixture,LIBDIR,READ,OBSERVE,SNAP,AUDIT

libs=[READ,OBSERVE,SNAP,AUDIT]+[LIBDIR/('vward-routing-'+n+'.sh') for n in
      ('project','plan','journal','workers','dns','migrate','state','pipeline')]
with Fixture() as f:
    f.cfg.write_text('interface Wireguard0\n!\ninterface Wireguard1\n!\ndns-proxy\n!\n')
    f.enabled.write_text('');f.persist.write_text('');f.cats.write_text('ai\tWireguard1\n')
    d=f.p/'decision';d.mkdir(mode=0o700)
    names='version choices bindings evidence policies saved queue tombstones context resources proofs upstreams'.split()
    for name in names:(d/(name+'.tsv')).write_text('');(d/(name+'.tsv')).chmod(0o600)
    (d/'version.tsv').write_text('routing-state\t2\n');(d/'choices.tsv').write_text('schema\t1\n')
    (d/'bindings.tsv').write_text('svc\tx.example\texact\tconfirmed\tipv4\tknown\n')
    base='source:M\t1\nsource:S\t1\nsource:A\t1\nVPN:Wireguard0\tavailable\nVPN:Wireguard1\tavailable\n'
    def project(target,context,index):
        (d/'context.tsv').write_text(base+context)
        stage=f.p/f'stage{index}';stage.mkdir(mode=0o700)
        out=f.p/f'project{index}';out.mkdir(mode=0o700)
        low=f.p/f'lowered{index}';low.mkdir(mode=0o700)
        args=' '.join('"${'+str(i)+'}"' for i in range(1,len(libs)+1))
        script='for lib in '+args+';do . "$lib";done;shift '+str(len(libs))+'''
vward_routing_consistent_read2 "$1" "$2" >/dev/null &&
vward_routing_choice "$1/decision/choices.tsv" svc vpn "$3" default 0 > "$4/next" &&
vward_routing_project2 "$1" svc "$4/next" "$4" &&
vward_routing_plan2 "$1" "$4" select > "$4/plan" &&
vward_routing_lower2 "$1" "$4/plan" "$5"
'''
        r=f.run(script,*libs,stage,d,target,out,low,timeout=10)
        assert r.returncode==0,(index,r.returncode,r.stdout,r.stderr,(out/'plan').read_text() if (out/'plan').exists() else 'no plan')
        return out,low
    out,low=project('VPN:auto','default-vpn\tVPN:Wireguard0\nservice-vpn:svc\tVPN:Wireguard1\n',0)
    assert '\tvpn\tVPN:auto\tdefault\t' in (low/'choices.after').read_text(),'default became a fixed pin'
    assert '\tVPN:Wireguard1\t' in (low/'resources.after').read_text(),'captured category was ignored'
    assert (low/'enabled.after').read_text().rstrip().endswith('\tauto'),'legacy registration lost default selector'
    out,low=project('VPN:Wireguard0','default-vpn\tVPN:Wireguard1\nservice-vpn:svc\tVPN:Wireguard1\n',1)
    assert '\tVPN:Wireguard0\t' in (low/'resources.after').read_text(),'category overrode explicit service pin'
    assert (low/'enabled.after').read_text().rstrip().endswith('\tWireguard0')
    out,low=project('VPN:auto','default-vpn\tVPN:Wireguard1\n',2)
    assert '\tVPN:Wireguard1\t' in (low/'resources.after').read_text(),'unassigned category ignored profile default'
    (d/'bindings.tsv').write_text('svc\tx.example\texact\texcluded\tipv4\tknown\n')
    out,low=project('VPN:auto','',3)
    assert (low/'resources.after').read_text()=='','excluded member acquired a route'
    (d/'bindings.tsv').write_text('svc\tx.example\texact\tconfirmed\tipv4\tknown\n')
    base=base.replace('source:S\t1','source:S\t0')
    out,low=project('VPN:auto','',4)
    assert (low/'resources.after').read_text()=='','disabled S required/used an unknown default'
    base=base.replace('source:S\t0','source:S\t1')
    (d/'context.tsv').write_text(base+'default-vpn\tISP\n')
    # Missing/invalid default must HOLD, never silently choose Provider.
    stage=f.p/'missing';stage.mkdir(mode=0o700);out=f.p/'missing-out';out.mkdir(mode=0o700)
    args=' '.join('"${'+str(i)+'}"' for i in range(1,len(libs)+1))
    r=f.run('for lib in '+args+';do . "$lib";done;shift '+str(len(libs))+';vward_routing_consistent_read2 "$1" "$2" >/dev/null && vward_routing_choice "$1/decision/choices.tsv" svc vpn VPN:auto default 0 > "$3/next" && vward_routing_project2 "$1" svc "$3/next" "$3" && vward_routing_plan2 "$1" "$3" select',*libs,stage,d,out,timeout=10)
    assert r.returncode==0 and '\nhold\t' in r.stdout and '\nstep\t' not in r.stdout,(r.returncode,r.stdout,r.stderr)
    assert f.enabled.read_text()=='' and 'object-group fqdn' not in f.cfg.read_text(),'pure lowering wrote a legacy/native object'
print('VPN_SELECTOR=PASS logical default/category selection stays auto, explicit pin wins, invalid default HOLD, read-only common projection/lowering')
