#!/usr/bin/env python3
"""Versioned parent journal: evolving Gi, no replay, readback and mandatory save."""
from pathlib import Path
from fixture import Fixture,JOURNAL
G0='g-0000000000000000';G1='g-1111111111111111';G2='g-2222222222222222'
with Fixture() as f:
    j=f.p/'journal';j.mkdir(mode=0o700)
    plan=f.p/'plan';current=f.p/'current'
    post='route|r1|group:domain-list0|x.example|exact|VPN:Wireguard0|default|native|vward|p-op1-1|S:svc'
    choice='service|svc|1|vpn|VPN:Wireguard0|default|0'
    plan.write_text(f'routing-plan\t2\t{G0}\tdenied\n'+
        f'step\t1\tcreate\troute\tr1\t-\t{post}\tp-op1-1\tS:svc\tgeneration,identity,postimage,save\tremove-own-resource\n'+
        f'step\t2\tmove\tchoice\tsvc\t-\t{choice}\trevision-cas\tS:svc\tgeneration,identity,postimage,save\trestore-own-choice\n')
    def call(name,*args):return f.run('. "$1"; shift; "$@"',JOURNAL,name,*args)
    def image(row):
        current.write_text(row.replace('|','\t')+'\n');current.chmod(0o600)
    r=call('vward_journal2_plan',j,'op1',plan);assert r.returncode==0,(r.stdout,r.stderr)
    assert call('vward_journal_gate',j).returncode==75,'old v1 journal accepted v2 operation'
    assert call('vward_journal2_gate',j).returncode==0
    image('-')
    assert call('vward_journal2_begin',j,'op1',1,G1,current).returncode==75,'stale Gi accepted'
    assert call('vward_journal2_begin',j,'op1',1,G0,current).returncode==0
    assert call('vward_journal2_gate',j).returncode==75
    image(post)
    assert call('vward_journal2_finish',j,'op1',1,G1,current).returncode==0
    image('-')
    assert call('vward_journal2_begin',j,'op1',2,G0,current).returncode==75,'every step was incorrectly compared with G0'
    assert call('vward_journal2_begin',j,'op1',2,G1,current).returncode==0
    image(choice)
    assert call('vward_journal2_finish',j,'op1',2,G2,current).returncode==0
    (j/'op1/state').write_text('compensated\n')
    assert call('vward_journal2_gate',j).returncode==75,'terminal label hid unapplied inverses'
    (j/'op1/state').write_text('pending\n')
    assert call('vward_journal2_commit',j,'op1',G2).returncode==75,'committed before required save'
    assert call('vward_journal2_saved',j,'op1','done').returncode==0
    assert call('vward_journal2_commit',j,'op1',G2).returncode==0
    assert call('vward_journal2_gate',j).returncode==0
    (j/'op1/step.2').rename(j/'op1/.hold')
    assert call('vward_journal2_gate',j).returncode==75,'committed label hid missing readback evidence'
    (j/'op1/.hold').rename(j/'op1/step.2')
    (j/'op1/save').rename(j/'op1/.save')
    assert call('vward_journal2_gate',j).returncode==75,'committed label hid missing mandatory save'
    (j/'op1/.save').rename(j/'op1/save')
    assert call('vward_journal2_plan',j,'op1',plan).returncode==75,'used operation replayed'
    # Lost reply with proven post-image is accepted; another image holds the barrier.
    assert call('vward_journal2_plan',j,'op2',plan).returncode==0
    image('-');assert call('vward_journal2_begin',j,'op2',1,G0,current).returncode==0
    image('route|foreign')
    assert call('vward_journal2_finish',j,'op2',1,G1,current).returncode==3
    assert call('vward_journal2_gate',j).returncode==75
    # Torn parent update never makes a pending child look like an unused plan.
    partial=f.p/'partial';partial.mkdir(mode=0o700)
    assert call('vward_journal2_plan',partial,'op1',plan).returncode==0
    image('-');assert call('vward_journal2_begin',partial,'op1',1,G0,current).returncode==0
    (partial/'op1/state').write_text('planned\n')
    assert call('vward_journal2_gate',partial).returncode==75,'pending child hidden by older parent marker'
    assert call('vward_journal2_plan',j,'op3',plan).returncode==75
    assert (j/'op2/step.1/pre').read_text()=='-\n'
    assert (j/'op2/step.1/post').read_text()==post.replace('|','\t')+'\n'
    assert (j/'op2/state').read_text()=='unknown\n'
    assert call('vward_journal2_compensating',j,'op2',1,current).returncode==75,'foreign image authorised an inverse'
    image(post)
    assert call('vward_journal2_compensating',j,'op2',1,current).returncode==0
    image('-')
    assert call('vward_journal2_compensated',j,'op2',1,G1,current).returncode==0
    image(post)
    assert call('vward_journal2_compensating',j,'op2',1,current).returncode==75,'a compensated resource was recreated and its old inverse replayed'
    image('-')
    baseline=f.p/'baseline';baseline.mkdir(mode=0o700)
    for name in ('step.1','step.2'):
        (baseline/name).write_text('-\n');(baseline/name).chmod(0o600)
    (baseline/'generation').write_text(G1+'\n')
    assert call('vward_journal2_abort',j,'op2',G1,baseline).returncode==75,'inverse closed without saving baseline'
    assert call('vward_journal2_rollback_saved',j,'op2','done').returncode==0
    assert call('vward_journal2_abort',j,'op2',G1,baseline).returncode==0
    assert call('vward_journal2_gate',j).returncode==0
    # Plan corruption cannot enlarge permissions or alter recorded postimage.
    (j/'op2/plan').write_text(plan.read_text().replace('Wireguard0','Wireguard1'))
    image(post)
    assert call('vward_journal2_finish',j,'op2',1,G1,current).returncode!=0
    assert call('vward_journal2_gate',j).returncode==75
print('B_JOURNAL2=PASS parent/children, evolving Gi, save/readback, lost/foreign, corruption/replay, v1 refusal')
