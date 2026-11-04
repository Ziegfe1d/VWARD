#!/usr/bin/env python3
"""One data set through native stage/real choice/policy/plan/journal/workers.

The native command worker and group_set are extracted from the EXISTING console
script; fixed DATA ndm belongs to the OFF coordinator. No fixture invents an
applied outcome, ownership proof, or policy result.
"""
import os
from pathlib import Path
import re
from fixture import Fixture, LIBDIR, ROOT, READ, SNAP, OBSERVE, AUDIT, PLAN, JOURNAL, DRYRUN

with Fixture() as f:
    j=f.p/'journal';j.mkdir(mode=0o700)
    e=j/'.emu';e.mkdir(mode=0o700)
    decision=e/'decision';decision.mkdir(mode=0o700)
    (e/'services/owned').mkdir(mode=0o700,parents=True)
    for name in ('version','choices','bindings','evidence','policies','saved','queue','tombstones','context','resources','proofs'):
        (decision/(name+'.tsv')).write_text('');(decision/(name+'.tsv')).chmod(0o600)
    (decision/'version.tsv').write_text('routing-state\t2\n')
    (decision/'choices.tsv').write_text('schema\t1\n')
    (decision/'bindings.tsv').write_text('svc\tx.example\texact\tconfirmed\tipv4\tknown\nsvc\ty.example\texact\tconfirmed\tipv4\tknown\n')
    (decision/'context.tsv').write_text('source:M\t1\nsource:S\t1\nsource:A\t1\nVPN:Wireguard0\tavailable\nVPN:Wireguard1\tavailable\n')
    (e/'running.cfg').write_text('interface Wireguard0\n!\ninterface Wireguard1\n!\ndns-proxy\n!\n');(e/'running.cfg').chmod(0o600)
    (e/'device.conf').write_bytes(f.dev.read_bytes())
    (e/'device-map.tsv').write_bytes(f.map.read_bytes())
    (e/'catalog.json').write_bytes(f.catalog.read_bytes())
    (e/'agh-domains').write_text('')
    (e/'services/enabled.tsv').write_text('');(e/'services/enabled.tsv').chmod(0o600)
    (e/'services/categories.tsv').write_text('ai\tWireguard0\n')
    (e/'route').mkdir(mode=0o700)
    (e/'route/adaptive-persist.txt').write_text('')
    shim=f.p/'poison';shim.mkdir();trace=f.p/'transport'
    for name in ('ndmc','curl','comm','cksum'):
        p=shim/name;p.write_text('#!/bin/sh\necho called >> "'+str(trace)+'"\nexit 99\n');p.chmod(0o755)
    if os.environ.get('RS6_BUSYBOX'):(shim/'awk').symlink_to(Path(os.environ['RS6_BUSYBOX']).resolve())
    env=f.env|{'PATH':str(shim)+':'+os.environ['PATH'],'VWARD_RS7_DRYRUN':'1'}
    console=(ROOT/'components/console/scripts/vward-console-config.sh').read_text()
    def function(name):
        m=re.search(r'^'+name+r'\(\)\s*\{\n.*?^\}\n',console,re.M|re.S)
        assert m,name
        return m[0]
    functions=f.p/'console-functions';functions.write_text(function('group_set')+'\n'+function('vward_routing_console_group_locked'))
    libs=(READ,OBSERVE,SNAP,AUDIT,LIBDIR/'vward-routing-project.sh',PLAN,JOURNAL,DRYRUN,
          LIBDIR/'vward-runtime-admission.sh',LIBDIR/'vward-routing-workers.sh',LIBDIR/'vward-routing-migrate.sh',LIBDIR/'vward-routing-pipeline.sh',functions)
    def call(op,action='vpn',target='VPN:Wireguard0',dns='default',rev=0,more=None):
        script='for lib in '+ ' '.join('"${'+str(i)+'}"' for i in range(1,len(libs)+1))+'; do . "$lib"; done\n'
        script+='shift '+str(len(libs))+'\nvward_routing_pipeline2 "$@"'
        return f.run(script,*libs,j,op,'svc',action,target,dns,rev,env=env|(more or {}),timeout=45)
    def recover(op,mode='compensate'):
        script='for lib in '+ ' '.join('"${'+str(i)+'}"' for i in range(1,len(libs)+1))+'; do . "$lib"; done\n'
        script+='shift '+str(len(libs))+'\nvward_routing_pipeline_recover2 "$@"'
        return f.run(script,*libs,j,op,mode,env=env,timeout=45)
    def local(name,*args):
        script='for lib in '+ ' '.join('"${'+str(i)+'}"' for i in range(1,len(libs)+1))+'; do . "$lib"; done\n'
        script+='shift '+str(len(libs))+'\n"$@"'
        return f.run(script,*libs,name,*args,env=env,timeout=30)
    # Data migration has its own private baseline, schema guard and downgrade
    # refusal. This is independent of an updater replacing program files.
    (decision/'version.tsv').write_text('routing-state\t1\n')
    (decision/'evidence.tsv').write_text('A\ta1\tx.example\texact\tVPN:Wireguard0\tdefault\t1\tactive\t0\tsvc\n')
    old={p.name:p.read_bytes() for p in decision.glob('*.tsv')}
    (e/'foreign.conf').write_bytes(b'owner-kept\n')
    r=call('v1denied');assert r.returncode==75
    r=local('vward_routing_state_migrate2',j,'m1');assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    r=local('vward_routing_state_gate',1,decision);assert r.returncode==75,'old schema reader accepted v2 state'
    assert '\thistory\t0\t' in (decision/'evidence.tsv').read_text(),'old active evidence became fresh'
    good=(decision/'choices.tsv').read_bytes()
    (decision/'choices.tsv').write_text('schema\t1\nservice\tsvc\t1\tdns\tISP\tpolicy1\t0\n')
    changed={p.name:p.read_bytes() for p in decision.glob('*.tsv')}
    r=local('vward_routing_state_restore1',j,'m1');assert r.returncode==75,'accepted new choice was lost on downgrade'
    assert {p.name:p.read_bytes() for p in decision.glob('*.tsv')}==changed
    (decision/'choices.tsv').write_bytes(good)
    r=local('vward_routing_state_restore1',j,'m1');assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert {p.name:p.read_bytes() for p in decision.glob('*.tsv')}==old,'v1 baseline restore was not byte-exact'
    assert (e/'foreign.conf').read_bytes()==b'owner-kept\n'
    r=local('vward_routing_state_gate',1,decision);assert r.returncode==0
    # Start the execution cases with a second fully migrated state and no
    # historical active A contributor (an explicit fixture input change).
    (decision/'evidence.tsv').write_text('')
    r=local('vward_routing_state_migrate2',j,'m2');assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    # OFF-by-default and executor override guards remain closed, even when a
    # valid native service would otherwise be eligible.
    before=(e/'running.cfg').read_bytes()
    r=call('offguard',more={'VWARD_RS7_DRYRUN':'0'});assert r.returncode==75,(r.stdout,r.stderr)
    r=call('override',more={'VWARD_DRYRUN_NDMC':'/bin/true'});assert r.returncode==75
    assert (e/'running.cfg').read_bytes()==before
    r=call('op1');assert r.returncode==0,(r.returncode,r.stdout,r.stderr[-7000:],[(str(p.relative_to(j)),p.read_text()) for p in j.glob('.operation.*/typed')])
    assert 'outcome\tcommitted\tconfigured\tverified\tfalse\temulated' in r.stdout,r.stdout
    cfg=(e/'running.cfg').read_text();assert 'include x.example' in cfg and 'include y.example' in cfg
    assert cfg.count('route object-group domain-list0 Wireguard0 auto')==1,cfg
    assert (j/'op1/state').read_text()=='committed\n'
    assert (e/'saved.cfg').read_bytes()==(e/'running.cfg').read_bytes()
    assert (e/'services/owned/domain-list0').read_text()=='include x.example\ninclude y.example\nroute=Wireguard0\tauto\n'
    assert (e/'services/enabled.tsv').read_text()=='svc\tdomain-list0\tWireguard0\n'
    # One native scope with two domains, not one full config RPC per name.
    physical=[x for x in (j/'op1/plan').read_text().splitlines() if '\tgroup\t' in x]
    assert len(physical)==1,physical
    generation=(j/'op1/generation').read_text()
    assert generation!=(j/'op1/step.1/generation').read_text(),'Gi never advanced'
    rows=(decision/'resources.tsv').read_text().splitlines();assert len(rows)==2
    assert all(row.split('\t')[8]=='vward' for row in rows)
    # Same accepted choice is idempotent, no native rewrite or duplicate group.
    calls=(e/'calls').read_text();r=call('repeat',rev=1)
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert (e/'running.cfg').read_text()==cfg
    assert (e/'calls').read_text().count('include x.example')==calls.count('include x.example')
    (decision/'bindings.tsv').write_text((decision/'bindings.tsv').read_text()+'svc\tz.example\texact\tconfirmed\tipv4\tknown\n')
    r=call('newdomain',rev=1);assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert 'include z.example' in (e/'running.cfg').read_text(),'new confirmed name did not inherit the accepted VPN pin'
    identities={r.split('\t')[3]:(r.split('\t')[1],r.split('\t')[9]) for r in (decision/'resources.tsv').read_text().splitlines()}
    r=call('move1',target='VPN:Wireguard1',rev=1);assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert {r.split('\t')[3]:(r.split('\t')[1],r.split('\t')[9]) for r in (decision/'resources.tsv').read_text().splitlines()}==identities,'target move renamed the resource or its creation origin'
    assert 'domain-list0' not in (e/'running.cfg').read_text()
    assert 'route object-group domain-list1 Wireguard1 auto' in (e/'running.cfg').read_text()
    # Off removes only this S contribution and native exact own scope, while
    # preserving unrelated manual native data.
    foreign='object-group fqdn Owner\n    include owner.example\n!\n'
    (e/'running.cfg').write_text((e/'running.cfg').read_text().replace('dns-proxy\n','dns-proxy\n    route object-group Owner ISP auto\n')+foreign)
    r=call('off1','off','-', '-',2);assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert foreign in (e/'running.cfg').read_text()
    assert 'object-group fqdn domain-list' not in (e/'running.cfg').read_text()
    assert not list((e/'services/owned').iterdir())
    assert (decision/'resources.tsv').read_text()==''
    assert (e/'services/enabled.tsv').read_text()==''
    # Native refusal after one successful include leaves a durable private
    # barrier. Explicit compensation is permitted from a PRECOMPILED prefix;
    # it never reapplies the forward operation after a lost/failed command.
    baseline=(e/'running.cfg').read_text()
    (e/'refuse').write_text('object-group fqdn domain-list0 include y.example')
    r=call('partial',rev=3);assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    partial=(e/'running.cfg').read_text();assert 'include x.example' in partial and 'include y.example' not in partial
    calls=(e/'calls').read_bytes()
    r=recover('partial','inspect');assert r.returncode==3
    assert (e/'calls').read_bytes()==calls,'inspect replayed a native write'
    r=call('blocked',rev=3);assert r.returncode==75,'pending operation did not close admission'
    (e/'refuse').unlink()
    r=recover('partial');assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert (e/'running.cfg').read_text()==baseline
    assert (j/'partial/state').read_text()=='compensated\n'
    # Save refusal cannot be called a committed transition. Compensation also
    # needs its OWN successful baseline save, not the previous forward marker.
    (e/'save-fails').touch()
    r=call('savefail',rev=3);assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    assert (j/'savefail/state').read_text()=='unknown\n'
    r=recover('savefail');assert r.returncode!=0,'baseline save refusal was ignored'
    (e/'save-fails').unlink()
    r=recover('savefail');assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert (e/'running.cfg').read_text()==baseline
    assert (e/'services/enabled.tsv').read_text()==''
    (e/'foreign-after').write_text('include')
    r=call('foreign',rev=3);assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    edited=(e/'running.cfg').read_bytes()
    assert b'owner-edit.example' in edited
    r=recover('foreign');assert r.returncode==75,'foreign postimage authorised an inverse'
    assert (e/'running.cfg').read_bytes()==edited,'compensation erased an owner edit'
    assert not trace.exists(),'transport/comm/cksum was executed'
print('B_EXECUTION=PASS connected native stage/choice/policy/typed+physical plan/journal/real console worker/readback/save/local/Gi/repeat/new-name/stable-move/off/foreign/partial-prefix/savefailure/CAS compensation/schema migration+byte-exact downgrade; DATA emulator only')
