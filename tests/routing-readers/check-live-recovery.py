#!/usr/bin/env python3
"""Native recovery is explicit; dispatch/matching bytes never settle a lost reply."""
from live_fixture import LiveFixture

with LiveFixture() as f:
    (f.p/'native-lost-reply').write_text('object-group fqdn domain-list0')
    r=f.invoke('vward_routing_live_service','lost','svc','vpn','VPN:Wireguard0','default',0)
    assert r.returncode==3,(r.returncode,r.stdout,r.stderr)
    op=f.live/'journal/lost'
    pending=list(op.glob('native.*/request.pending'));assert pending
    before=f.native.read_bytes();calls=f.calls.read_text();evidence={p:p.read_bytes() for p in pending}
    r=f.invoke('vward_routing_live_recover','lost','inspect')
    assert r.returncode==3 and 'unknown' in r.stdout,(r.returncode,r.stdout,r.stderr)
    assert f.native.read_bytes()==before and f.calls.read_text()==calls,'inspection issued native traffic'
    r=f.invoke('vward_routing_live_recover','lost','compensate')
    assert r.returncode==75,(r.returncode,r.stdout,r.stderr)
    assert f.native.read_bytes()==before and f.calls.read_text()==calls,'lost response was blindly inverted/replayed'
    assert all(p.read_bytes()==b for p,b in evidence.items()) and (op/'state').read_text()=='unknown\n'
print('LIVE_RECOVERY=PASS native unknown inspect without transport; explicit compensation refuses unresolved real request, no matching-image adoption')
