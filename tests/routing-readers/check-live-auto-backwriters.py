#!/usr/bin/env python3
"""Actual old Auto producers stop before metadata/probe/NDMC once common state exists."""
import shutil
from fixture import ROOT,function_source
from live_fixture import LiveFixture,LIBDIR

engine=ROOT/'components/route-engine/scripts/vward-route-engine.sh'
# Extract the actual functions, including real CHANGE acquisition/release.
body='\n'.join(function_source(engine,n) for n in
               ('change_lock','change_unlock','persist_sync_cache','restore_adaptive_from_persist','add_adaptive','add_hint_adaptive'))
for name in ('persist_sync_cache','restore_adaptive_from_persist','add_adaptive','add_hint_adaptive'):
    with LiveFixture() as f:
        f.env['VWARD_PROFILE_LIB']=str(LIBDIR/'vward-device-profile.sh')
        # Positive control proves the installed loader/current native reader
        # works; a missing dependency must not explain the Auto refusal.
        r=f.invoke('vward_routing_scope_gate','domain','unrelated.example')
        assert r.returncode==0,('scope reader not reached',r.returncode,r.stderr)
        adaptive=f.p/'adaptive';adaptive.write_text('s.example\n')
        persist=f.p/'persist';persist.write_text('owner.example\n')
        event=f.p/'events';event.write_text('')
        guard='''
CHANGE_LOCK="$1/tmp/vward-route-change.lock"
ADAPTIVE="$2";PERSIST="$3";EVENT_LOG="$4";ADAPTIVE_DISABLED="$1/no-disabled"
ADAPTIVE_FULL="$1/no-full";ADAPTIVE_FULL_MIN=60
ru_zone() { return 1; }
refresh_sets() { printf unexpected-refresh >&2;return 99; }
# The actual scope gate must deny BEFORE any refresh/native probe or side effect.
rc=0;"$5" s.example || rc=$?
printf 'result=%s\n' "$rc"
[ "$rc" = 75 ] && [ ! -e "$CHANGE_LOCK" ]
'''
        r=f.run(f.script(body+guard),*f.libs,f.prefix,adaptive,persist,event,name,env=f.env,timeout=15)
        assert r.returncode==0,(name,r.returncode,r.stdout,r.stderr)
        assert adaptive.read_text()=='s.example\n' and persist.read_text()=='owner.example\n'
        assert event.read_text()=='' and all(x.endswith('\tshow running-config') for x in f.calls.read_text().splitlines()),(name,'probe/write before common handoff')
# The absent-root path still retains the old persistence behavior.
with LiveFixture() as f:
    shutil.rmtree(f.live)
    a=f.p/'adaptive';a.write_text('s.example\ns.example\n');p=f.p/'persist';p.write_text('old.example\n')
    r=f.run(f.script(body+'ADAPTIVE="$1";PERSIST="$2";persist_sync_cache'),*f.libs,a,p,env=f.env,timeout=5)
    assert r.returncode==0 and p.read_text()=='s.example\n',(r.returncode,r.stderr)
print('LIVE_AUTO_BACKWRITERS=PASS actual restore/add/hint/persist handoff before local IO/probes; actual locks released; absent-root legacy preserved')
