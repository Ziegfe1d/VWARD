#!/usr/bin/env python3
"""Typed planner consumes the actual staged native inventory and shared projection."""
import os,sys
import hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from fixture import Fixture,READ,OBSERVE,SNAP,AUDIT,PLAN,JOURNAL,LIBDIR
PROJECT=LIBDIR/'vward-routing-project.sh'
with Fixture() as f:
    clean='interface Wireguard0\n!\ninterface Wireguard1\n!\ndns-proxy\n!\n'
    f.cfg.write_text(clean);f.enabled.write_text('');f.persist.write_text('')
    inputs=f.p/'decision';inputs.mkdir(mode=0o700)
    for name in ('version','choices','bindings','evidence','policies','saved','queue','tombstones','context','resources','proofs','upstreams'):
        (inputs/(name+'.tsv')).write_text('');(inputs/(name+'.tsv')).chmod(0o600)
    def put(name,text):(inputs/(name+'.tsv')).write_text(text)
    put('version','routing-state\t2\n');put('choices','schema\t1\n')
    put('bindings','svc\tx.example\texact\tconfirmed\tipv4\tknown\n')
    context='source:M\t1\nsource:S\t1\nsource:A\t1\nVPN:Wireguard0\tavailable\nstorage:keenetic\tavailable\nstorage:agh\tavailable\n'
    put('context',context);put('policies','policy1\tkeenetic\tavailable\tactive\tnone\t1\turl1\n')
    stage=f.p/'stage';stage.mkdir(mode=0o700);out=f.p/'project';out.mkdir(mode=0o700)
    shim=f.p/'poison';shim.mkdir();trace=f.p/'trace'
    for name in ('ndmc','curl','comm','cksum'):
        p=shim/name;p.write_text('#!/bin/sh\necho called >> "'+str(trace)+'"\nexit 99\n');p.chmod(0o755)
    if os.environ.get('RS6_BUSYBOX'):(shim/'awk').symlink_to(Path(os.environ['RS6_BUSYBOX']).resolve())
    env=f.env|{'PATH':str(shim)+':'+os.environ['PATH']}
    def plan(action='vpn',target='VPN:Wireguard0',dns='default',rev=0):
        r=f.run('. "$1"; . "$2"; . "$3"; vward_routing_consistent_read2 "$4" "$5"',READ,OBSERVE,SNAP,stage,inputs,env=env)
        assert r.returncode==0,(r.stdout,r.stderr)
        r=f.run('. "$1"; vward_routing_choice "$2" svc "$3" "$4" "$5" "$6"',AUDIT,stage/'decision/choices.tsv',action,target,dns,rev,env=env)
        assert r.returncode==0,(r.stdout,r.stderr);(out/'next').write_text(r.stdout)
        r=f.run('. "$1"; . "$2"; . "$3"; vward_routing_project2 "$4" svc "$5" "$6" && vward_routing_plan2 "$4" "$6" op-1',
                AUDIT,PROJECT,PLAN,stage,out/'next',out,env=env)
        assert r.returncode==0,(r.stdout,r.stderr)
        rows=[x.split('\t') for x in r.stdout.splitlines()]
        assert rows[0][:2]==['routing-plan','2'] and rows[0][-1]=='denied',r.stdout
        (out/'plan.tsv').write_text(r.stdout)
        return rows
    rows=plan();assert any(r[:4]==['step','1','create','route'] for r in rows),rows
    put('context',context+'VPN:Ghost\tavailable\n')
    rows=plan(target='VPN:Ghost');assert any(r[0]=='hold' for r in rows),'context boolean invented a VPN target outside native profile'
    put('context',context);rows=plan()
    assert any(r[0]=='step' and r[3]=='choice' for r in rows)
    journal=f.p/'journal';journal.mkdir(mode=0o700)
    r=f.run('. "$1"; vward_journal2_plan "$2" op-1 "$3"',JOURNAL,journal,out/'plan.tsv',env=env)
    assert r.returncode==0,(r.stdout,r.stderr)
    r=f.run('. "$1"; vward_journal_plan "$2" legacy "$3" x.example S vward verified',JOURNAL,journal,out/'plan.tsv',env=env)
    assert r.returncode==2 and not (journal/'legacy').exists(),'old journal accepted the typed plan'
    binding=(inputs/'bindings.tsv').read_text();put('bindings','')
    rows=plan();assert any(r[0]=='hold' for r in rows) and not any(r[0]=='step' for r in rows),'empty service scope accepted'
    put('bindings',binding)
    # Existing compatible foreign coverage is reused and never adopted.
    f.cfg.write_text(clean.replace('dns-proxy\n','dns-proxy\n    route object-group Manual Wireguard0 auto\n')+'object-group fqdn Manual\n    include x.example\n!\n')
    rows=plan();assert not any(r[0]=='step' and r[3]=='route' for r in rows),rows
    rows=plan('isp','ISP','default');assert any(r[0]=='hold' for r in rows) and not any(r[0]=='step' for r in rows),rows
    put('context',context.replace('source:M\t1','source:M\t0'))
    rows=plan('off','-','-');assert not any(r[0]=='hold' for r in rows),'S off is not an ISP pin against an independent external route'
    put('context',context)
    f.cfg.write_text(f.cfg.read_text().replace('Manual Wireguard0','Manual ISP'))
    rows=plan('isp','ISP','default');assert not any(r[0]=='hold' for r in rows),'compatible manual ISP was treated as a conflict'
    f.cfg.write_text(clean)
    # VPN does not depend on an expired/unknown Smart DNS policy.
    put('policies','policy1\tkeenetic\tunavailable\tactive\tnone\t1\turl1\n')
    assert any(r[0]=='step' and r[3]=='route' for r in plan())
    rows=plan('dns','ISP','policy1');assert any(r[0]=='hold' for r in rows) and not any(r[0]=='step' for r in rows)
    put('policies','policy1\tkeenetic\tavailable\tactive\tnone\t1\turl1\n')
    put('upstreams','url1\thttps://dns.example.test/dns-query\n')
    put('bindings',binding.replace('exact','subtree'))
    put('context',context+'scope:subtree\tavailable\n')
    rows=plan('dns','ISP','policy1');assert any(r[0]=='step' and r[3]=='dns' for r in rows),rows
    # One physical suffix, all consumers. The child is confirmed by the
    # parent's subtree; its own exact attribution does not require a second
    # over-broad DNS binding or let the first atom discard the peer's claim.
    put('bindings','svc\texample.test\tsubtree\tconfirmed\tdual\tknown\npeer\tsub.example.test\texact\tconfirmed\tipv4\tknown\n')
    put('choices','schema\t1\nservice\tpeer\t1\tdns\tISP\tpolicy1\t0\n')
    rows=plan('dns','ISP','policy1')
    ds=[r for r in rows if r[0]=='step' and r[3]=='dns']
    assert not any(r[0]=='hold' for r in rows) and len(ds)==1,('subtree was duplicated or exact child lost inherited coverage',rows)
    assert ds[0][6].split('|')[3]=='example.test' and set(ds[0][6].split('|')[10].split(','))=={'S:svc','S:peer'},'shared child consumer disappeared'
    put('bindings','svc\texample.test\tsubtree\tconfirmed\tdual\tknown\nsvc\tsub.example.test\tsubtree\texcluded\tdual\tknown\n')
    put('choices','schema\t1\n')
    rows=plan('dns','ISP','policy1')
    assert any(r[0]=='hold' for r in rows) and not any(r[0]=='step' for r in rows),'parent DNS silently covered an excluded child'
    put('bindings',binding.replace('exact','subtree'))
    f.cfg.write_text(clean.replace('dns-proxy\n','dns-proxy\n    https upstream https://dns.example.test/dns-query domain x.example\n'))
    rows=plan('dns','ISP','policy1')
    assert not any(r[0]=='step' and r[3]=='dns' for r in rows),'compatible native DNS was duplicated or adopted'
    f.cfg.write_text(f.cfg.read_text().replace('dns.example.test','foreign.example.test'))
    rows=plan('dns','ISP','policy1')
    assert any(r[0]=='hold' and r[2]=='foreign-resource-conflict' for r in rows),'another server became a managed binding'
    f.cfg.write_text(clean)
    put('tombstones','policy1\t1\tdeleted\n')
    assert any(r[0]=='hold' for r in plan('dns','ISP','policy1')),'deleted policy resurrected'
    put('tombstones','')
    # Whole-transition Keenetic capacity includes foreign/global entries.
    f.cfg.write_text(clean.replace('dns-proxy\n','dns-proxy\n'+''.join(f'    https upstream https://s{i}.example.test/dns-query\n' for i in range(8))))
    assert any(r[0]=='hold' for r in plan('dns','ISP','policy1')),'slot limit ignored'
    f.cfg.write_text(clean);put('policies','policy1\tagh\tavailable\tactive\tunsupported\t1\turl1\n')
    assert any(r[0]=='hold' for r in plan('dns','ISP','policy1')),'upstream_dns_file silently ignored'
    put('bindings',binding);put('context',context)
    # Replacing a URL behind the SAME logical policy ID is a physical move.
    # Logical ID equality cannot keep an old endpoint or reuse its content proof.
    old_url='https://old.example.test/dns-query'
    new_url='https://replacement.example.test/dns-query'
    native='upstream:uh-'+hashlib.sha256(old_url.encode()).hexdigest()[:48]
    f.cfg.write_text(clean.replace('dns-proxy\n','dns-proxy\n    https upstream '+old_url+' domain x.example\n'))
    put('upstreams',f'old\t{old_url}\nnew\t{new_url}\n')
    put('policies','policy1\tkeenetic\tavailable\tactive\tnone\t2\tnew\n')
    put('bindings',binding.replace('exact','subtree'));put('context',context+'scope:subtree\tavailable\n')
    put('choices','schema\t1\nservice\tsvc\t1\tdns\tISP\tpolicy1\t0\n')
    dns_row=f'dns\town-dns\t{native}\tx.example\tsubtree\tISP\tpolicy1\tkeenetic\tvward\tp-old\tS:svc\n'
    content=hashlib.sha256(('https upstream '+old_url+' domain x.example\n').encode()).hexdigest()[:48]
    put('resources',dns_row);put('proofs','\t'.join(dns_row.strip().split('\t')[:10])+'\t1:'+content+'\n')
    rows=plan('dns','ISP','policy1',1)
    assert any(r[0]=='step' and r[2:5]==['move','dns','own-dns'] and native not in r[6] for r in rows),'policy ID equality hid a changed physical URL'
    f.cfg.write_text(f.cfg.read_text().replace(' domain x.example',' dnsm on ISP domain x.example'))
    rows=plan('dns','ISP','policy1',1)
    assert any(r[0]=='hold' and r[2]=='native-dns-proof-changed' for r in rows) and not any(r[0]=='step' for r in rows),'an owner DNS metadata edit retained mutation rights'
    f.cfg.write_text(clean);put('bindings',binding);put('context',context)
    put('resources','');put('proofs','');put('choices','schema\t1\n')
    # A proven owned route can lose S while retaining independent active A.
    f.cfg.write_text(clean.replace('dns-proxy\n','dns-proxy\n    route object-group domain-list0 Wireguard0 auto\n')+
                     'object-group fqdn domain-list0\n    include x.example\n!\n')
    f.enabled.write_text('svc\tdomain-list0\tauto\n')
    f.proof.write_text('include x.example\nroute=Wireguard0\tauto\n')
    row='route\town1\tgroup:domain-list0\tx.example\texact\tVPN:Wireguard0\tdefault\tnative\tvward\tp-old\tS:svc\n'
    put('resources',row);put('proofs','\t'.join(row.strip().split('\t')[:10])+'\t1\n')
    put('choices','schema\t1\nservice\tsvc\t1\tvpn\tVPN:Wireguard0\tdefault\t0\n')
    rows=plan('off','-','-',1)
    assert any(r[0]=='step' and r[2:4]==['remove','route'] for r in rows),rows
    put('evidence','A\ta1\tx.example\texact\tVPN:Wireguard0\tdefault\t1\tactive\t0\tsvc\n')
    rows=plan('off','-','-',1)
    assert not any(r[0]=='step' and r[2]=='remove' for r in rows),'S off deleted independent A coverage'
    assert any(r[0]=='step' and r[3]=='claims' for r in rows),rows
    put('evidence','');put('context',context+'VPN:Wireguard1\tavailable\n')
    rows=plan('vpn','VPN:Wireguard1','default',1)
    assert any(r[0]=='step' and r[2:5]==['move','route','own1'] and 'p-old' in r[6] for r in rows),'native target move lost stable resource/birth ID'
    # A common-owned A-only rule is not a new native manual intent. Turning A
    # off withdraws its known contribution; absence of an S claim is not orphan
    # ownership and must not force a redundant S-on/off workaround.
    f.enabled.write_text('')
    put('choices','schema\t1\nservice\tsvc\t1\tauto\t-\t-\t0\n')
    put('context',context.replace('source:A\t1','source:A\t0'))
    put('resources',row.replace('S:svc','A:a1'))
    put('evidence','A\ta1\tx.example\texact\tVPN:Wireguard0\tdefault\t1\tactive\t0\tsvc\n')
    rows=plan('off','-','-',1)
    assert any(r[0]=='step' and r[2:5]==['remove','route','own1'] for r in rows),('withdrawing A preserved its obsolete physical rule',rows,(out/'policy.tsv').read_text(),(stage/'intents.tsv').read_text(),(stage/'inventory.tsv').read_text())
    f.enabled.write_text('svc\tdomain-list0\tauto\n')
    put('choices','schema\t1\nservice\tsvc\t1\tvpn\tVPN:Wireguard0\tdefault\t0\n')
    put('context',context)
    put('resources',row.replace('p-old','p-reused'))
    rows=plan('off','-','-',1);assert any(r[0]=='hold' for r in rows) and not any(r[0]=='step' for r in rows),'reused identity mutated'
    assert not trace.exists()
print('B_PLAN2=PASS connected choice/policy/native inventory, typed deltas, foreign refs, per-action DNS/capacity/tombstones')
