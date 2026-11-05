#!/usr/bin/env python3
"""Known preflight refusal is not a lost ACK for somebody else's matching post."""
from fixture import PipelineFixture,LIBDIR,function_source
with PipelineFixture() as f:
    real=function_source(LIBDIR/'vward-routing-pipeline.sh','vrb_write_scope').replace('vrb_write_scope() (','vrb_write_scope_real() (',1)
    hook=real+'''
    vrb_write_scope() {
        if [ "$1" = group ];then
            awk '/^dns-proxy$/{print;print "    route object-group domain-list0 Wireguard0 auto";next}{print}' "$vrb_e/running.cfg" > "$vrb_e/owner-config"
            printf '%s\\n' 'object-group fqdn domain-list0' '    include x.example' '    include y.example' '!' >> "$vrb_e/owner-config"
            cp "$vrb_e/owner-config" "$vrb_e/running.cfg"
        fi
        vrb_write_scope_real "$@"
    }
    vward_routing_pipeline2 "$@"
    '''
    r=f.run(f.script(hook),*f.libs,f.j,'race','svc','vpn','VPN:Wireguard0','default',0,timeout=45)
    assert r.returncode==3,(r.returncode,r.stdout,r.stderr,'known refusal was adopted as lost ACK/success')
    assert (f.j/'race/state').read_text()=='unknown\n'
    assert (f.decision/'resources.tsv').read_bytes()==b'' and not list((f.e/'services/owned').iterdir()),'foreign matching post was adopted'
    assert not (f.e/'calls').exists(),'preflight refusal issued a native/save call'
    owner=(f.e/'running.cfg').read_bytes()
    r=f.invoke('vward_routing_pipeline_recover2',f.j,'race','compensate')
    assert r.returncode==75 and (f.e/'running.cfg').read_bytes()==owner,'inverse erased a foreign matching planned post'
print('B_PREFLIGHT_REFUSAL=PASS known guard refusal never becomes ACK/ownership/inverse authority for a matching owner image')
