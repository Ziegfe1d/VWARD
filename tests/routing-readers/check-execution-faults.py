#!/usr/bin/env python3
"""Connected execution must not absorb a concurrent policy edit into its Gi."""
from fixture import PipelineFixture,LIBDIR,function_source
with PipelineFixture() as f:
    r=f.invoke('vward_routing_pipeline2',f.j,'normal','svc','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr,(f.j/'normal/reason').read_text() if (f.j/'normal/reason').exists() else '')
    assert (f.j/'normal/state').read_text()=='committed\n'

with PipelineFixture() as f:
    # Same real DATA transport, with an external decision edit immediately
    # after one native command. The hook grants no extra executor capability.
    real=function_source(LIBDIR/'vward-routing-pipeline.sh','vrb_emu_ndm').replace('vrb_emu_ndm() (','vrb_emu_ndm_real() (',1)
    hook=real+'''
    vrb_emu_ndm() {
        vrb_emu_ndm_real "$@"; fault_rc=$?
        if [ "$1" = 'object-group fqdn domain-list0 include x.example' ]; then
            awk 'BEGIN{FS=OFS="\\t"} $1=="source:S"{$2=0}{print}' "$vrb_e/decision/context.tsv" > "$vrb_e/decision/context.next"
            mv "$vrb_e/decision/context.next" "$vrb_e/decision/context.tsv"
        fi
        return "$fault_rc"
    }
    vward_routing_pipeline2 "$@"
    '''
    r=f.run(f.script(hook),*f.libs,f.j,'genedit','svc','vpn','VPN:Wireguard0','default',0,env=f.env,timeout=45)
    assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    assert (f.j/'genedit/state').read_text()=='unknown\n','foreign decision edit was adopted as an own Gi'
    assert 'source:S\t0\n' in (f.decision/'context.tsv').read_text()
    assert (f.decision/'choices.tsv').read_text()=='schema\t1\n'
    assert (f.decision/'resources.tsv').read_text()==''
    r=f.invoke('vward_routing_pipeline_recover2',f.j,'genedit','compensate')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert 'source:S\t0\n' in (f.decision/'context.tsv').read_text(),'inverse overwrote the external choice'
    assert 'object-group fqdn domain-list' not in (f.e/'running.cfg').read_text()
    assert not f.trace.exists()
print('B_EXECUTION_FAULTS=PASS unexpected input edit closes Gi, own compensation preserves external decision')

with PipelineFixture() as f:
    real=function_source(LIBDIR/'vward-routing-pipeline.sh','vrb_emu_ndm').replace('vrb_emu_ndm() (','vrb_emu_ndm_real() (',1)
    hook=real+'''
    vrb_emu_ndm() {
        vrb_emu_ndm_real "$@"; fault_rc=$?
        if [ "$1" = 'system configuration save' ]; then
            awk 'BEGIN{FS=OFS="\\t"} $1=="source:S"{$2=0}{print}' "$vrb_e/decision/context.tsv" > "$vrb_e/decision/context.next"
            mv "$vrb_e/decision/context.next" "$vrb_e/decision/context.tsv"
        fi
        return "$fault_rc"
    }
    vward_routing_pipeline2 "$@"
    '''
    r=f.run(f.script(hook),*f.libs,f.j,'savegen','svc','vpn','VPN:Wireguard0','default',0,env=f.env,timeout=45)
    assert 'system configuration save' in (f.e/'calls').read_text(),(r.returncode,r.stdout,r.stderr)
    assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    assert (f.j/'savegen/state').read_text()=='unknown\n','save absorbed a late policy edit into committed state'
    r=f.invoke('vward_routing_pipeline_recover2',f.j,'savegen','compensate')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert 'source:S\t0\n' in (f.decision/'context.tsv').read_text()
print('B_SAVE_GENERATION=PASS late input edit cannot become a commit, own rollback preserves new source state')

with PipelineFixture() as f:
    r=f.invoke('vward_routing_pipeline2',f.j,'seed','svc','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    ctx=f.decision/'context.tsv'
    ctx.write_text(ctx.read_text().replace('source:M\t1','source:M\t0').replace('source:S\t1','source:S\t0').replace('source:A\t1','source:A\t0'))
    pending=f.e/'backup/service-transactions/txn.other/pending'
    pending.parent.mkdir(parents=True,mode=0o700);pending.write_text('pending\n')
    before=(f.e/'running.cfg').read_bytes()
    calls=(f.e/'calls').read_bytes()
    r=f.invoke('vward_routing_pipeline2',f.j,'offblocked','svc','off','-','-',1)
    assert r.returncode==75,(r.returncode,r.stdout,r.stderr)
    assert (f.e/'running.cfg').read_bytes()==before and (f.e/'calls').read_bytes()==calls,'source toggles bypassed unresolved legacy recovery'
    pending.unlink();pending.parent.rmdir()
    reservation=f.e/'backup-recovery/smartdns.empty';reservation.mkdir(mode=0o700,parents=True)
    r=f.invoke('vward_routing_pipeline2',f.j,'emptyblocked','svc','off','-','-',1)
    assert r.returncode==75,(r.returncode,r.stdout,r.stderr)
    assert (f.e/'running.cfg').read_bytes()==before and (f.e/'calls').read_bytes()==calls,'empty AGH reservation was ignored'
print('B_LEGACY_BARRIER=PASS disabled sources cannot bypass an unresolved transaction')
