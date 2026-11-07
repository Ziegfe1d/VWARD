#!/usr/bin/env python3
"""Legacy file modes and foreign authority edits are not our content delta."""
from fixture import PipelineFixture,LIBDIR,function_source
with PipelineFixture() as f:
    enabled=f.e/'services/enabled.tsv';enabled.chmod(0o644)
    r=f.invoke('vward_routing_pipeline2',f.j,'on','svc','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert enabled.stat().st_mode&0o777==0o644,'legacy public registry mode changed'
    proof=f.e/'services/owned/domain-list0';proof.chmod(0o400)
    (f.e/'local-fails').write_text('choices\n')
    r=f.invoke('vward_routing_pipeline2',f.j,'off','svc','off','-','-',1)
    assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    r=f.invoke('vward_routing_pipeline_recover2',f.j,'off','compensate')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert proof.stat().st_mode&0o777==0o400,'inverse lost original private proof mode'
    assert enabled.stat().st_mode&0o777==0o644
print('B_LOCAL_MODES=PASS registry0644 and private proof0400 survive own changes/compensation')

with PipelineFixture() as f:
    real=function_source(LIBDIR/'vward-routing-pipeline.sh','vrb_emu_ndm').replace('vrb_emu_ndm() (','vrb_emu_ndm_real() (',1)
    hook=real+'''
    vrb_emu_ndm() {
        vrb_emu_ndm_real "$@"; fault_rc=$?
        if [ "$1" = 'object-group fqdn domain-list0' ]; then chmod 0400 "$vrb_e/running.cfg";fi
        return "$fault_rc"
    }
    vward_routing_pipeline2 "$@"
    '''
    r=f.run(f.script(hook),*f.libs,f.j,'chmod','svc','vpn','VPN:Wireguard0','default',0,env=f.env,timeout=45)
    assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    assert (f.e/'running.cfg').stat().st_mode&0o777==0o400,'publisher erased the owner authority edit'
    assert 'include x.example' not in (f.e/'running.cfg').read_text()
    assert (f.j/'chmod/state').read_text()=='unknown\n'
    r=f.invoke('vward_routing_pipeline_recover2',f.j,'chmod','compensate')
    assert r.returncode!=0 and (f.e/'running.cfg').stat().st_mode&0o777==0o400
print('B_FOREIGN_MODE=PASS changed owner authority closes forward and inverse publication')
