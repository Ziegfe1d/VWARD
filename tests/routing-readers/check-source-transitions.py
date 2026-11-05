#!/usr/bin/env python3
"""One connected state through all 8 vertices and 24 directed cube edges."""
import time
from fixture import PipelineFixture

# Euler circuit: every single-bit directed transition exactly once.
edges={n:[n^(1<<b) for b in range(3)] for n in range(8)}
stack=[0];walk=[]
while stack:
    n=stack[-1]
    if edges[n]:stack.append(edges[n].pop())
    else:walk.append(stack.pop())
walk.reverse()
assert len(walk)==25 and len(set(zip(walk,walk[1:])))==24 and set(walk)==set(range(8))
with PipelineFixture() as f:
    f.clock=('11111111-1111-1111-1111-111111111111',100)
    (f.decision/'bindings.tsv').write_text('svc\tx.example\texact\tconfirmed\tipv4\tknown\n')
    (f.decision/'evidence.tsv').write_text('M\tm1\tx.example\texact\tVPN:Wireguard0\tdefault\t1\texplicit\t0\t-\nA\ta1\tx.example\texact\tVPN:Wireguard0\tdefault\t1\tactive\t0\tsvc\n')
    seen=set();started=time.monotonic()
    for index,n in enumerate(walk):
        flags={src:int(bool(n&(1<<b))) for b,src in enumerate('MSA')}
        (f.decision/'context.tsv').write_text(''.join(f'source:{s}\t{v}\n' for s,v in flags.items())+'VPN:Wireguard0\tavailable\nVPN:Wireguard1\tavailable\nprobe:a1\tfresh\nprobe-boot:a1\t11111111-1111-1111-1111-111111111111\nprobe-until:a1\t155\n')
        r=f.invoke('vward_routing_pipeline2',f.j,f'edge{index}','svc','vpn','VPN:Wireguard0','default',int(index>0))
        assert r.returncode==0,(index,n,r.returncode,r.stdout,r.stderr)
        assert (f.j/f'edge{index}'/'state').read_text()=='committed\n' or not n
        rows=(f.decision/'resources.tsv').read_text().splitlines()
        expected={s+':'+{'M':'m1','S':'svc','A':'a1'}[s] for s in 'MSA' if flags[s]}
        assert bool(rows)==bool(n),(index,n,rows)
        if rows:
            assert len(rows)==1 and set(rows[0].split('\t')[10].split(','))==expected,(index,n,rows,expected)
        cfg=(f.e/'running.cfg').read_text()
        assert cfg.count('include x.example')==int(bool(n)),(index,n,cfg)
        enabled=(f.e/'services/enabled.tsv').read_text()
        assert bool(enabled)==bool(flags['S']),(index,n,enabled,'legacy projection disagrees with actual S claim')
        if n not in seen:
            seen.add(n)
            calls=(f.e/'calls').read_bytes() if (f.e/'calls').exists() else b''
            before=(f.e/'running.cfg').read_bytes()
            r=f.invoke('vward_routing_pipeline2',f.j,f'repeat{n}','svc','vpn','VPN:Wireguard0','default',1)
            assert r.returncode==0,(n,'repeat',r.returncode,r.stdout,r.stderr)
            assert (f.e/'running.cfg').read_bytes()==before
            assert ((f.e/'calls').read_bytes() if (f.e/'calls').exists() else b'')==calls,'repeat called native transport'
    assert not f.trace.exists()
    calls=(f.e/'calls').read_text().splitlines()
    print(f'B_SOURCE_CHAIN=PASS 8 combinations/24 directed transitions/8 repeats; native DATA calls={len(calls)} elapsed_host={time.monotonic()-started:.2f}s; not MIPS',flush=True)
