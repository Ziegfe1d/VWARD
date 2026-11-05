#!/usr/bin/env python3
"""Migration uses the same J2/publisher and cannot erase owner authority edits."""
from fixture import PipelineFixture, digest

with PipelineFixture() as f:
    (f.decision/'version.tsv').write_text('routing-state\t1\n')
    (f.decision/'evidence.tsv').write_text('A\ta1\tx.example\texact\tVPN:Wireguard0\tdefault\t1\tactive\t0\tsvc\n')
    (f.decision/'bindings.tsv').chmod(0o400)
    baseline={p.name:(p.read_bytes(),p.stat().st_mode&0o777) for p in f.decision.glob('*.tsv')}
    r=f.invoke('vward_routing_state_migrate2',f.j,'migrate')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert (f.j/'migrate/state').read_text()=='committed\n'
    assert '\tsaved\trouting-state\t' in (f.j/'migrate/plan').read_text(),'migration bypassed J2'
    assert (f.decision/'bindings.tsv').stat().st_mode&0o777==0o400
    (f.decision/'choices.tsv').chmod(0o400)
    before=digest(f.decision)
    r=f.invoke('vward_routing_state_restore1',f.j,'migrate')
    assert r.returncode==75 and digest(f.decision)==before,'downgrade erased owner chmod'
    assert (f.decision/'choices.tsv').stat().st_mode&0o777==0o400
    (f.decision/'choices.tsv').chmod(0o600)
    r=f.invoke('vward_routing_state_restore1',f.j,'migrate')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert {p.name:(p.read_bytes(),p.stat().st_mode&0o777) for p in f.decision.glob('*.tsv')}==baseline
    assert not (f.e/'calls').exists(),'local migration touched a native backend'

with PipelineFixture() as f:
    (f.decision/'version.tsv').write_text('routing-state\t1\n')
    (f.decision/'evidence.tsv').write_text('A\ta1\tx.example\texact\tVPN:Wireguard0\tdefault\t1\tactive\t0\tsvc\n')
    before=digest(f.decision)
    (f.e/'local-fails').write_text('version')
    r=f.invoke('vward_routing_state_migrate2',f.j,'partial')
    assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    assert (f.decision/'version.tsv').read_text()=='routing-state\t1\n'
    assert '\thistory\t0\t' in (f.decision/'evidence.tsv').read_text(),'fixture missed a written prefix'
    r=f.invoke('vward_routing_state_restore1',f.j,'partial')
    assert r.returncode==75,'downgrade bypassed an unresolved J2 prefix'
    (f.e/'local-fails').unlink()
    r=f.invoke('vward_routing_pipeline_recover2',f.j,'partial','compensate')
    assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
    assert digest(f.decision)==before,'prefix compensation was not byte exact'
    assert (f.j/'partial/state').read_text()=='compensated\n'
print('B_STATE_MIGRATION=PASS leased J2 state-set, owner chmod refusal, byte/mode downgrade, partial version-last prefix compensation')
