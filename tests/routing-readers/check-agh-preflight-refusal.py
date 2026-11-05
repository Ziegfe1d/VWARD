#!/usr/bin/env python3
"""An AGH owner edit between final GET and POST is a refusal, not inverse rights."""
from fixture import PipelineFixture,ROOT,function_source
with PipelineFixture() as f:
    f.configure_dns('agh')
    source=ROOT/'components/ads-privacy-guard/scripts/vward-ads-privacy-control.sh'
    real=function_source(source,'agh_unchanged').replace('agh_unchanged() {','agh_unchanged_real() {',1)
    hook=real+'''
    agh_unchanged() {
        agh_unchanged_real; owner_rc=$?
        if [ "$owner_rc" = 0 ] && [ "$vrb_am_model" = "$vrb_e/agh.json" ];then
            "$ADS_JQ" -cS --slurpfile p "$W/plan.json" '.upstream_dns=$p[0].upstream_dns' "$vrb_am_model" > "$vrb_e/owner-agh.json"
            cp "$vrb_e/owner-agh.json" "$vrb_am_model"
        fi
        return "$owner_rc"
    }
    vward_routing_pipeline2 "$@"
    '''
    r=f.run(f.script(hook),*f.libs,f.j,'race','svc','dns','ISP','policy1',0,timeout=45)
    assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    assert (f.j/'race/state').read_text()=='unknown\n'
    assert (f.decision/'resources.tsv').read_bytes()==b'' and (f.decision/'proofs.tsv').read_bytes()==b''
    owner=(f.e/'agh.json').read_bytes()
    r=f.invoke('vward_routing_pipeline_recover2',f.j,'race','compensate')
    assert r.returncode==75 and (f.e/'agh.json').read_bytes()==owner,(r.returncode,r.stdout,r.stderr,'known pre-POST refusal granted inverse authority over an owner matching image')
print('B_AGH_PREFLIGHT_REFUSAL=PASS owner matching planned POST is not dispatched by us; no inverse/adoption')
