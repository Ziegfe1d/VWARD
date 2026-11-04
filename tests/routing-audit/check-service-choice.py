#!/usr/bin/env python3
"""B intent-only model: one service choice, never a router mutation or permission."""
import itertools
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'routing-readers'))
from fixture import AUDIT, Fixture

with Fixture() as f:
    state=f.p/'choices'; state.write_text('schema\t1\n')
    shim=f.p/'poison'; shim.mkdir(); trace=f.p/'trace'
    if os.environ.get('RS6_BUSYBOX'):
        (shim/'awk').symlink_to(Path(os.environ['RS6_BUSYBOX']).resolve())
    for name in ('ndmc','curl','nslookup','ip','iptables','ipset','comm','cksum',
                 'vward-console-config.sh','vward-route-engine.sh'):
        p=shim/name; p.write_text('#!/bin/sh\necho '+name+' >> "'+str(trace)+'"\nexit 99\n');p.chmod(0o755)
    env=f.env|{'PATH':str(shim)+':'+os.environ['PATH']}
    def call(action,target='-',dns='-',rev=0,sid='claude.ai',path=state):
        before=state.read_bytes()
        r=f.run('. "$1"; vward_routing_choice "$2" "$3" "$4" "$5" "$6" "$7"',
                AUDIT,path,sid,action,target,dns,rev,env=env)
        assert state.read_bytes()==before,'pure transition wrote its input'
        return r
    def choice(action,target='-',dns='-',rev=0):
        r=call(action,target,dns,rev)
        assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
        rows=[line.split('\t') for line in r.stdout.splitlines()]
        assert rows[0]==['schema','1']
        row=next((r for r in rows[1:] if r[1]=='claude.ai'),None)
        state.write_text(r.stdout) # caller saves fixture data; library never writes
        return row
    assert choice('on','VPN:tun1','default')==['service','claude.ai','1','vpn','VPN:tun1','default','0']
    assert choice('vpn','VPN:tun1','default',1)[2]=='1','repeat changed revision'
    assert choice('off',rev=1)==['service','claude.ai','2','auto','-','-','0']
    assert choice('dns','ISP','dns-policy1',2)==['service','claude.ai','3','dns','ISP','dns-policy1','0']
    stable=state.read_text()
    assert choice('off',rev=3)[3]=='dns' and state.read_text()==stable,'rendered VPN-off erased DNS pin'
    assert choice('auto',rev=3)==['service','claude.ai','4','auto','-','-','4'],'Auto could replay pre-pin history'
    assert choice('isp','ISP','default',4)[3]=='isp'
    assert choice('off',rev=5)[3]=='isp','VPN-off erased explicit ISP'
    assert choice('on','VPN:tun2','default',5)[3:]==['vpn','VPN:tun2','default','6'],'pin -> VPN -> off can replay pre-pin Auto'
    assert choice('off',rev=6)[-1]=='6','ordinary off invalidated independent Auto'
    assert choice('auto',rev=7)[2]=='7','repeat auto changed revision'
    # Every base combination and one-bit transition: S off removes only S.
    states=list(itertools.product((0,1),repeat=3)); edges=0
    for bits in states:
        for index in range(3):
            other=list(bits);other[index]^=1; edges+=1
            for mask in (bits,tuple(other),tuple(other)):
                state.write_text('schema\t1\n')
                row=choice('on','VPN:tun1','default') if mask[1] else choice('off')
                selected=int(row is not None and row[3]=='vpn')
                intents=f.p/'intent-model'
                intents.write_text(''.join(f'{src}\t{src.lower()}\tx.example\texact\tVPN:tun1\tdefault\t{on}\n'
                                          for src,on in zip('MSA',(mask[0],selected,mask[2]))))
                snapshot=f.p/'snapshot-model'
                snapshot.write_text('snapshot\tg1\tknown\n'+''.join(f'source\t{s}\t1\tknown\n' for s in 'MSA')+
                                    'health\tDNS\tavailable\nhealth\tAGH\tavailable\nhealth\tVPN:tun1\tavailable\n')
                r=f.run('. "$1"; vward_routing_audit "$2" "$3"',AUDIT,intents,snapshot,env=env)
                assert r.returncode==0,r.stderr
                active=r.stdout.split('\t')[2]
                want=','.join(s+':'+s.lower() for s,on in zip('AMS',(mask[2],mask[0],selected)) if on) or '-'
                assert active==want,(mask,active,want)
    assert edges==24
    # Refuse stale/invalid input with no partial state; missing never becomes auto.
    state.write_text('schema\t1\nservice\tclaude.ai\t9\tvpn\tVPN:tun1\tdefault\t0\n')
    r=call('off',rev=8); assert r.returncode==3 and not r.stdout,(r.stdout,r.stderr)
    for action,target,dns in [('delete','-','-'),('vpn','ISP','default'),('dns','ISP','default'),
                              ('on','VPN:tun1','https://dns.example.test/dns-query'),('off','ISP','default')]:
        r=call(action,target,dns,9);assert r.returncode==2 and not r.stdout,(action,r.stdout,r.stderr)
    for broken in ('', 'schema\t2\n', 'schema\t1\n'*2,
                   'schema\t1\nservice\tclaude.ai\t1\tvpn\tISP\tdefault\t0\n',
                   'schema\t1\nservice\tclaude.ai\t1\tauto\t-\t-\t2\n',
                   'schema\t1\n'+('service\tclaude.ai\t1\tauto\t-\t-\t0\n'*2)):
        state.write_text(broken);r=call('off');assert r.returncode==2 and not r.stdout,(broken,r.stdout,r.stderr)
    state.write_text('schema\t1\n')
    for path in (f.p/'missing',):
        r=call('off',path=path);assert r.returncode==2 and not r.stdout
    link=f.p/'alias';link.symlink_to(state)
    r=call('off',path=link);assert r.returncode==2 and not r.stdout
    fifo=f.p/'fifo';os.mkfifo(fifo)
    r=call('off',path=fifo);assert r.returncode==2 and not r.stdout
    state.write_text('schema\t1\nservice\tclaude.ai\t2147483647\tvpn\tVPN:tun1\tdefault\t0\n')
    r=call('off',rev=2147483647);assert r.returncode==2 and not r.stdout
    state.write_text('schema\t1\nservice\tclaude.ai\t2147483646\tvpn\tVPN:tun1\tdefault\t0\n')
    r=call('off',rev=2147483646)
    assert r.returncode==0 and r.stdout.splitlines()[1].split('\t')[2]=='2147483647','revision rounded or exponential'
    # Other service intent is preserved; input order cannot decide policy.
    rows=['service\tz-last\t7\tdns\tISP\tpolicy1\t0\n',
          'service\ta-first\t2\tisp\tISP\tdefault\t0\n']
    outputs=[]
    for ordered in (rows,list(reversed(rows))):
        state.write_text('schema\t1\n'+''.join(ordered));r=call('off')
        assert r.returncode==0;outputs.append(r.stdout)
    assert outputs[0]==outputs[1]=='schema\t1\n'+''.join(reversed(rows))
    # Real maximum key count, under the fixture existing timeout (not enlarged).
    state.write_text('schema\t1\n'+''.join(f'service\ts{i:04d}\t0\tauto\t-\t-\t0\n' for i in reversed(range(1024))))
    started=time.monotonic();r=call('off',sid='s0000');elapsed=time.monotonic()-started
    assert r.returncode==0 and len(r.stdout.splitlines())==1025
    r=call('on','VPN:tun1','default');assert r.returncode==2 and not r.stdout
    state.write_text(state.read_text()+'service\textra\t0\tauto\t-\t-\t0\n')
    r=call('off');assert r.returncode==2 and not r.stdout
    for invalid in ('schema\t1\n'+'x\n'*4096,'schema\t1\n'+'x'*1048576):
        state.write_text(invalid);r=call('off');assert r.returncode==2 and not r.stdout
    assert not trace.exists(),'pure function called a transport or platform command'
print(f'B_SERVICE_CHOICE=PASS one intent, 8/24, no live calls; 1024 keys elapsed={elapsed:.4f}s (host)')
