#!/usr/bin/env python3
"""Prepared legacy handoff uses the same choice/policy and persistent barrier."""
from fixture import PipelineFixture,digest
with PipelineFixture() as f:
    r=f.invoke('vward_routing_pipeline2',f.j,'pin','svc','isp','ISP','default',0)
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    (f.decision/'evidence.tsv').write_text('A\ta1\tx.example\texact\tVPN:Wireguard0\tdefault\t1\thistory\t0\tsvc\n')
    old=(f.e/'route-engine/domain-lists');old.mkdir(parents=True,mode=0o700)
    p=old/'domain-list0';p.write_text('route=Wireguard0\tauto\nsmartdns_config='+'0'*64+'\ndoh=https upstream https://expired.example.test/dns-query domain x.example\n');p.chmod(0o600)
    before=(f.e/'running.cfg').read_bytes();calls=(f.e/'calls').read_bytes() if (f.e/'calls').exists() else b''
    choice=(f.decision/'choices.tsv').read_bytes()
    r=f.invoke('vward_routing_legacy_reconcile2',f.j,'restore','svc')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert (f.decision/'choices.tsv').read_bytes()==choice,'legacy handoff overwrote the explicit owner pin'
    assert (f.e/'running.cfg').read_bytes()==before and ((f.e/'calls').read_bytes() if (f.e/'calls').exists() else b'')==calls,'legacy return/history resurrected a VPN/DNS rule'
    for kind,key,expected in [('domain','x.example',75),('domain','outside.example',0),('auto','a1',75)]:
        r=f.run(f.script('vrb_envelope "$1" observe || exit $?;mkdir "$2";cp "$vrb_e/running.cfg" "$vrb_e/running-config";vward_routing_consistent_read2 "$2" "$vrb_e/decision" >/dev/null || exit $?;vward_routing_legacy_eligibility2 "$2" "$1" "$3" "$4"'),
            *f.libs,f.j,f.p/('stage-'+kind+'-'+key),kind,key)
        assert r.returncode==expected,(kind,key,r.returncode,r.stdout,r.stderr)
    r=f.invoke('vward_routing_update_eligibility2',f.j)
    assert r.returncode==0,(r.returncode,r.stderr)
    (f.e/'save-fails').touch()
    r=f.invoke('vward_routing_pipeline2',f.j,'uncertain','svc','vpn','VPN:Wireguard0','default',1)
    assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    before=digest(f.decision);native=(f.e/'running.cfg').read_bytes()
    r=f.invoke('vward_routing_update_eligibility2',f.j)
    assert r.returncode==75,'persistent unknown was lost after its admission PID exited'
    r=f.invoke('vward_routing_legacy_reconcile2',f.j,'again','svc')
    assert r.returncode==75 and digest(f.decision)==before and (f.e/'running.cfg').read_bytes()==native,'old handoff crossed the global unknown barrier'
print('B_BACKWRITER_PREPARATION=PASS common preserved owner choice/history floor, scoped pins, unknown persists beyond PID; no live caller wired')
