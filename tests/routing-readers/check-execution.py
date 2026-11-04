#!/usr/bin/env python3
"""One data set through native stage/real choice/policy/plan/journal/workers.

The native command worker and group_set are extracted from the EXISTING console
script; fixed DATA ndm belongs to the OFF coordinator. No fixture invents an
applied outcome, ownership proof, or policy result.
"""
import shutil
from fixture import PipelineFixture

with PipelineFixture() as f:
    j,e,decision=f.j,f.e,f.decision
    trace=f.trace
    def call(op,action='vpn',target='VPN:Wireguard0',dns='default',rev=0,more=None):
        return f.invoke('vward_routing_pipeline2',j,op,'svc',action,target,dns,rev,more=more)
    def recover(op,mode='compensate'):
        return f.invoke('vward_routing_pipeline_recover2',j,op,mode)
    def local(name,*args):return f.invoke(name,*args)
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
    # The same operation path must support real typed DNS decisions on both
    # stores, not merely print an eligible preview without a backend worker.
    base_j,base_e,base_decision=j,e,decision
    for store in ('keenetic','agh'):
        j=f.p/('dns-'+store);j.mkdir(mode=0o700)
        e=j/'.emu';shutil.copytree(base_e,e)
        decision=e/'decision'
        (decision/'policies.tsv').write_text(f'policy1\t{store}\tavailable\tactive\tnone\t1\turl1\n')
        (decision/'upstreams.tsv').write_text('url1\thttps://dns.example.test/dns-query\n');(decision/'upstreams.tsv').chmod(0o600)
        (decision/'context.tsv').write_text((decision/'context.tsv').read_text()+f'storage:{store}\tavailable\n')
        (decision/'context.tsv').write_text((decision/'context.tsv').read_text()+'scope:subtree\tavailable\n')
        (decision/'bindings.tsv').write_text((decision/'bindings.tsv').read_text().replace('exact','subtree'))
        (e/'agh.json').write_text('{"upstream_dns":["9.9.9.9"],"upstream_dns_file":""}\n');(e/'agh.json').chmod(0o600)
        r=call('dns1','dns','ISP','policy1',0)
        assert r.returncode==0,(store,r.returncode,r.stdout,r.stderr)
        assert (j/'dns1/state').read_text()=='committed\n'
        assert all(x.split('\t')[0]=='dns' for x in (decision/'resources.tsv').read_text().splitlines())
        assert (e/'services/enabled.tsv').read_text()==''
    j,e,decision=base_j,base_e,base_decision
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
