#!/usr/bin/env python3
"""A derived legacy input is permitted only when bound to the same sealed AGH JSON."""
from agh_live_fixture import AghLiveFixture
from fixture import LIBDIR,function_source

for remove_relationship_check in (False,True):
    with AghLiveFixture() as f:
        body=function_source(LIBDIR/'vward-routing-live-agh.sh','vrl_agh_observe').replace('vrl_agh_observe() {','real_vrl_agh_observe() {',1)
        hook=body+'''
vrl_agh_observe() {
    real_vrl_agh_observe || return $?
    if grep -qF dns.example.test/dns-query "$vrl_cache/agh.json" 2>/dev/null;then
        printf 'unrelated-injected.example\\n' >> "$vrl_cache/agh-domains"
    fi
}
'''
        if remove_relationship_check:
            # Private negative control: allow only the label, without proving
            # that its actual bytes follow from the SAME sealed API image.
            hook+='vrl_agh_derived_deltas() { [ "$3:$4" != dns-scope:agh ] || printf "agh\\n"; }\n'
        r=f.run(f.script(hook+'"$@"'),*f.libs,'vward_routing_live_service','derived','svc','dns','ISP','policy1',0,env=f.env,timeout=45)
        if remove_relationship_check:
            assert r.returncode==0,('negative control did not expose unbound input admission',r.returncode,r.stdout,r.stderr)
        else:
            assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
            assert (f.live/'journal/derived/state').read_text()=='unknown\n'
            # Batch executor (owner decision 08.11.2026): the foreign derived
            # input is found by the ONE shared readback after the batch, so
            # own later steps were dispatched; none is committed and recovery
            # compensates each from its own journal record.
            assert (f.live/'journal/derived/reason').read_text()=='input-changed-during-step\n'
            assert (f.live/'journal/derived/state').read_text()!='committed\n'
        assert any(c[0]=='POST' for c in f.http_calls),'fixture did not reach physical AGH write'
print('LIVE_AGH_DERIVED=PASS actual foreign derived-input edit rejected; removing exact relationship check admits it (negative control), no guard weakening')
