#!/usr/bin/env python3
"""Pure B single-scope policy projection, no installed state or writer."""
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'routing-readers'))
from fixture import AUDIT, Fixture

with Fixture() as f:
    evidence=f.p/'policy-evidence'; trace=f.p/'trace'; shim=f.p/'poison';shim.mkdir()
    if os.environ.get('RS6_BUSYBOX'):
        (shim/'awk').symlink_to(Path(os.environ['RS6_BUSYBOX']).resolve())
    for name in ('ndmc','curl','nslookup','ip','comm','cksum','vward-console-config.sh'):
        p=shim/name;p.write_text('#!/bin/sh\necho called >> "'+str(trace)+'"\nexit 99\n');p.chmod(0o755)
    env=f.env|{'PATH':str(shim)+':'+os.environ['PATH']}
    def run(mode='auto',target='-',dns='-',rev=0,floor=0,rows=''):
        evidence.write_text('schema\t1\n'+rows);before=evidence.read_bytes()
        r=f.run('. "$1"; vward_routing_service_policy "$2" "$3" "$4" "$5" "$6" "$7"',
                AUDIT,mode,target,dns,rev,floor,evidence,env=env)
        assert evidence.read_bytes()==before
        return r
    def project(*args,**kw):
        r=run(*args,**kw);assert r.returncode==0,(r.stdout,r.stderr)
        lines=[x.split('\t') for x in r.stdout.splitlines()]
        assert lines[0][:2]==['policy','1'] and lines[0][-2:]==['denied','unknown']
        return lines[0][2],{(x[1],x[2]):x[3:] for x in lines[1:]}
    auto='A\ta1\tVPN:tun1\tdefault\t1\tactive\t0\tbound\n'
    manual='M\tm1\tVPN:tun1\tdefault\t1\texplicit\t0\tpeer\n'
    assert project()[0]=='inactive'
    assert project(rows=auto)[1][('A','a1')][2]=='active'
    # VPN reuses compatible Auto; DNS/ISP suppress only the bound automatic intent.
    status,rows=project('vpn','VPN:tun1','default',1,0,auto+manual)
    assert status=='desired' and all(x[2]=='active' for x in rows.values())
    for mode,dns in [('dns','policy1'),('isp','default')]:
        status,rows=project(mode,'ISP',dns,2,0,auto)
        assert status=='desired' and rows[('A','a1')][2:]==['suppressed','explicit-pin']
        assert project(mode,'ISP',dns,2,0,auto+manual)[0]=='unresolved','manual pin silently overridden'
    assert project('vpn','VPN:tun2','default',3,0,auto)[1][('A','a1')][2]=='suppressed'
    assert project('vpn','VPN:tun2','default',3,0,manual)[0]=='unresolved'
    # Returning Auto invalidates old persist; only current positive evidence restores.
    for kind,epoch,want in [('active',0,'inactive'),('history',4,'inactive'),
                            ('positive',3,'inactive'),('positive',4,'active'),
                            ('active',4,'active'),('unknown',4,'unknown')]:
        row=f'A\ta1\tVPN:tun1\tdefault\t1\t{kind}\t{epoch}\tbound\n'
        assert project('auto','-','-',4,4,row)[1][('A','a1')][2]==want,(kind,epoch)
    for membership,want in [('excluded','inactive'),('unknown','unknown')]:
        row=auto.replace('bound',membership)
        result,rows=project('dns','ISP','policy1',1,0,row)
        assert rows[('A','a1')][2]==want
        if want=='unknown':assert result=='unknown'
    # Disabled contributions never acquire authority; source order never chooses winner.
    peer='S\ts-peer\tISP\tpolicy2\t1\texplicit\t0\tpeer\n'
    assert project('vpn','VPN:tun1','default',1,0,peer)[0]=='unresolved'
    assert project(rows=manual+peer)==project(rows=peer+manual)
    assert project(rows=manual.replace('\t1\texplicit','\t0\texplicit'))[0]=='inactive'
    # Compose the two real functions: an intermediate VPN cannot erase the pin epoch.
    ledger=f.p/'choices';ledger.write_text('schema\t1\n');revision=0
    for action,target,dns in [('on','VPN:tun1','default'),('dns','ISP','policy1'),
                               ('vpn','VPN:tun1','default'),('off','-','-')]:
        c=f.run('. "$1"; vward_routing_choice "$2" svc "$3" "$4" "$5" "$6"',
                AUDIT,ledger,action,target,dns,revision,env=env)
        assert c.returncode==0,c.stderr
        ledger.write_text(c.stdout);_,_,revision,mode,target,dns,floor=c.stdout.splitlines()[1].split('\t')
        revision=int(revision);floor=int(floor)
        verdict,rows=project(mode,target,dns,revision,floor,auto)
        if action=='off':assert verdict=='inactive' and rows[('A','a1')][3]=='stale-auto-evidence'
    for bad in [auto+auto,auto.replace('bound','shared'),auto.replace('VPN:tun1','VPN:*'),
                auto.replace('\t0\tbound','\t5\tbound'),manual.replace('explicit','positive'),
                manual.replace('default','https://dns.example.test/dns-query'),
                'S\tchoice\tISP\tdefault\t1\texplicit\t0\tpeer\n']:
        r=run(rows=bad);assert r.returncode==2 and not r.stdout,(bad,r.stdout,r.stderr)
    r=run('dns','ISP','default');assert r.returncode==2 and not r.stdout
    r=run('dns','ISP',r'pol\151cy1');assert r.returncode==2 and not r.stdout,'escaped DNS ID accepted'
    r=run(rev=1,floor=2);assert r.returncode==2 and not r.stdout
    for invalid in ['schema\t2\n', 'schema\t1\n'*2, 'schema\t1\n'+'x\n'*4096,
                    'schema\t1\n'+'x'*1048576,
                    'schema\t1\n'+''.join(f'M\tm{i}\tISP\tdefault\t0\texplicit\t0\tpeer\n' for i in range(1025))]:
        evidence.write_text(invalid)
        r=f.run('. "$1"; vward_routing_service_policy auto - - 0 0 "$2"',AUDIT,evidence,env=env)
        assert r.returncode==2 and not r.stdout
    # A policy stream cannot be passed as v1 INTENTS or granted PLAN.
    r=run('vpn','VPN:tun1','default',1,0,auto);evidence.write_text(r.stdout)
    s=f.p/'snapshot';s.write_text('snapshot\tg1\tknown\n')
    r=f.run('. "$1"; vward_routing_audit "$2" "$3"',AUDIT,evidence,s)
    assert r.returncode==2 and not r.stdout
    # Suppression never hides an observed conflicting physical route from the v1 audit.
    evidence.write_text('S\tchoice\tx.example\texact\tISP\tpolicy1\t1\n')
    s.write_text('snapshot\tg1\tknown\n'+''.join(f'source\t{x}\t1\tknown\n' for x in 'MSA')+
                 'health\tDNS\tavailable\nhealth\tAGH\tavailable\n'+
                 'route\ta1\tx.example\texact\tVPN:tun1\tdefault\tunknown\treference\n')
    r=f.run('. "$1"; vward_routing_audit "$2" "$3"',AUDIT,evidence,s)
    assert r.returncode==0 and r.stdout.split('\t')[7]=='unresolved',r.stdout
    assert not trace.exists(),'policy projection called platform/transport command'
print('B_SERVICE_POLICY=PASS pins/Auto/history/peers/unknown, denied, no live calls')
