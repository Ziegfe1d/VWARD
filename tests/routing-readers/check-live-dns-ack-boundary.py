#!/usr/bin/env python3
"""Matching final DNS postimage must not publish claims after an unacknowledged request."""
import shutil
from fixture import LIBDIR,function_source
from live_fixture import LiveFixture

for remove_post_guard in (False,True):
    with LiveFixture() as f:
        f.configure_dns('keenetic')
        for name in ('policies','upstreams','context','bindings'):
            shutil.copy2(f.decision/(name+'.tsv'),f.live/'decision'/(name+'.tsv'))
        (f.p/'native-lost-reply').write_text('dns-proxy https upstream https://dns.example.test/dns-query dnsm domain y.example')
        hook=''
        if remove_post_guard:
            # Private counterfactual ONLY: remove post-worker ACK enforcement;
            # all actual locks, native entry pending gate and save refusal stay.
            hook=function_source(LIBDIR/'vward-routing-live.sh','vrl_bind').replace('vrl_bind() {','real_vrl_bind() {',1)
            hook+='\nvrl_bind() { real_vrl_bind;vrb_transport_requests_quiet() { return 0; }; }\n'
        r=f.run(f.script(hook+'"$@"'),*f.libs,'vward_routing_live_service','lost-final','svc','dns','ISP','policy1',0,env=f.env,timeout=45)
        assert r.returncode==3,(remove_post_guard,r.returncode,r.stdout,r.stderr)
        assert 'domain x.example' in f.native.read_text() and 'domain y.example' in f.native.read_text()
        assert list((f.live/'journal/lost-final').glob('native.*/request.pending'))
        choices=(f.live/'decision/choices.tsv').read_text()
        claims=(f.live/'decision/proofs.tsv').read_text()
        if remove_post_guard:
            assert choices!='schema\t1\n' and claims,'negative control failed to expose premature ownership publication'
        else:
            assert choices=='schema\t1\n' and claims=='','matching image promoted unacknowledged request to ownership'
print('LIVE_DNS_ACK_BOUNDARY=PASS real final-command lost ACK retains zero claims/choice; removing only post-worker guard reproduces premature claims before later save refusal')
