#!/usr/bin/env python3
"""Connected native stage -> canonical transition -> real shared service policy."""
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from fixture import Fixture,READ,SNAP,OBSERVE,AUDIT,LIBDIR,probe_context
PROJECT=Path(sys.argv[1]) if len(sys.argv)>1 else LIBDIR/'vward-routing-project.sh'
with Fixture() as f:
    clean='interface Wireguard0\n!\ninterface Wireguard1\n!\ndns-proxy\n!\n'
    f.cfg.write_text(clean);f.enabled.write_text('');f.persist.write_text('')
    inputs=f.p/'decision';inputs.mkdir(mode=0o700)
    for name in ('version','choices','bindings','evidence','policies','saved','queue','tombstones','context','resources','proofs','upstreams'):
        (inputs/(name+'.tsv')).write_text('')
    def put(name,text):(inputs/(name+'.tsv')).write_text(text)
    put('version','routing-state\t2\n');put('choices','schema\t1\n')
    bindings='svc\tx.example\texact\tconfirmed\tipv4\tknown\n'
    context='source:M\t1\nsource:S\t1\nsource:A\t1\nVPN:Wireguard0\tavailable\n'
    put('bindings',bindings);put('context',context)
    stage=f.p/'stage';stage.mkdir(mode=0o700)
    out=f.p/'projection';out.mkdir(mode=0o700);next_choices=out/'choices.next'
    shim=f.p/'poison';shim.mkdir();trace=f.p/'trace'
    for name in ('ndmc','curl','comm','cksum'):
        p=shim/name;p.write_text('#!/bin/sh\necho called >> "'+str(trace)+'"\nexit 99\n');p.chmod(0o755)
    if os.environ.get('RS6_BUSYBOX'):(shim/'awk').symlink_to(Path(os.environ['RS6_BUSYBOX']).resolve())
    env=f.env|{'PATH':str(shim)+':'+os.environ['PATH']}
    def call(action='vpn',target='VPN:Wireguard0',dns='default',revision=0):
        r=f.run('. "$1"; . "$2"; . "$3"; vward_routing_consistent_read2 "$4" "$5"',READ,OBSERVE,SNAP,stage,inputs,env=env)
        assert r.returncode==0,(r.stdout,r.stderr)
        r=f.run('. "$1"; vward_routing_choice "$2" svc "$3" "$4" "$5" "$6"',AUDIT,stage/'decision/choices.tsv',action,target,dns,revision,env=env)
        assert r.returncode==0,(r.stdout,r.stderr);next_choices.write_text(r.stdout)
        r=f.run('. "$1"; . "$2"; vward_routing_project2 "$3" svc "$4" "$5"',AUDIT,PROJECT,stage,next_choices,out,env=env)
        assert r.returncode==0,(r.stdout,r.stderr)
        return [x.split('\t') for x in (out/'policy.tsv').read_text().splitlines()]
    rows=call();assert rows[0]==['x.example','policy','1','desired','denied','unknown'],rows
    assert rows[1][1:4]==['contribution','S','svc'],rows
    f.cfg.write_text(clean.replace('dns-proxy\n','dns-proxy\n    route object-group Manual ISP auto\n')+
                     'object-group fqdn Manual\n    include x.example\n!\n')
    assert call()[0][3]=='unresolved','native manual ISP missing from shared policy'
    f.cfg.write_text(clean)
    put('evidence','M\tm1\tx.example\texact\tISP\tdefault\t1\texplicit\t0\t-\n')
    assert call()[0][3]=='unresolved','manual explicit choice was overridden'
    put('evidence','A\ta1\tx.example\texact\tVPN:Wireguard0\tdefault\t1\tactive\t0\tsvc\n')
    put('context',context+probe_context())
    rows=call('dns','ISP','policy1');assert any(x[2:4]==['A','a1'] and x[6]=='suppressed' for x in rows),rows
    # Persist history cannot survive DNS->VPN->off; fresh positive current epoch can.
    put('choices','schema\t1\nservice\tsvc\t3\tauto\t-\t-\t2\n')
    assert not any(x[1]=='contribution' and x[6]=='active' for x in call('off','-','-',3))
    put('evidence','A\ta1\tx.example\texact\tVPN:Wireguard0\tdefault\t1\tpositive\t3\tsvc\n')
    put('context',context)
    rows=call('off','-','-',3);assert rows[0][3]=='unknown','probe freshness silently assumed'
    put('context',context+probe_context())
    assert any(x[1]=='contribution' and x[6]=='active' for x in call('off','-','-',3))
    put('choices','schema\t1\n');put('evidence','')
    put('bindings',bindings.replace('confirmed','shared'))
    assert call()[0][3]=='unknown','shared CDN attributed to the service'
    put('bindings',bindings.replace('confirmed','excluded'))
    assert call()[0][3]=='inactive','excluded domain inherited service pin'
    put('bindings',bindings.replace('exact','subtree'))
    put('evidence','A\ta1\tnew.x.example\texact\tVPN:Wireguard0\tdefault\t1\thistory\t0\tsvc\n')
    rows=call('dns','ISP','policy1')
    assert any(x[0]=='new.x.example' and x[1]=='contribution' and x[2]=='S' and x[5]=='policy1' and x[6]=='active' for x in rows),rows
    assert not any(x[0]=='new.x.example' and x[1]=='contribution' and x[2]=='A' and x[6]=='active' for x in rows)
    # Valid-looking edits after staging cannot reuse the old generation. Failed
    # preparation must not leave a previously successful projection marker.
    p=stage/'decision/bindings.tsv';p.write_text(p.read_text().replace('x.example','other.example'))
    r=f.run('. "$1"; . "$2"; vward_routing_project2 "$3" svc "$4" "$5"',AUDIT,PROJECT,stage,next_choices,out,env=env)
    assert r.returncode!=0 and not (out/'generation').exists(),'tampered staged input reused a valid generation'
    # SID charset is broader than a native group/target identifier. Preserve
    # the real canonical ID through peer policy without widening native paths.
    put('choices','schema\t1\nservice\tpeer@unit.example\t1\tvpn\tVPN:Wireguard0\tdefault\t0\n')
    put('bindings',bindings+'peer@unit.example\tx.example\texact\tconfirmed\tipv4\tknown\n')
    put('evidence','');put('context',context)
    rows=call();assert any(x[1:4]==['contribution','S','peer@unit.example'] for x in rows),rows
    # Literal IP observations are not FQDN membership, even if dotted.
    put('bindings',bindings.replace('x.example','192.0.2.1'))
    r=f.run('. "$1"; . "$2"; . "$3"; vward_routing_consistent_read2 "$4" "$5"',READ,OBSERVE,SNAP,stage,inputs,env=env)
    assert r.returncode==0
    r=f.run('. "$1"; . "$2"; vward_routing_project2 "$3" svc "$4" "$5"',AUDIT,PROJECT,stage,next_choices,out,env=env)
    assert r.returncode!=0,'IP was accepted as a service domain'
    assert not trace.exists(),'projection called a transport'
print('B_PROJECTION=PASS native stage + real choice/policy, peers/epochs/persist/scopes/new names, no transports')
