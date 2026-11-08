#!/usr/bin/env python3
"""Cached predictions/returned ACK images never replace the final native preflight/Gi.

A foreign edit lands in the coordinator's own group (a) right before the only
destructive command (delete of the whole group) and (b) right after the last
acknowledged command of the batch. The seam is the actual NDMC transport (a
wrapper around the fixture), independent of how the executor batches commands.
"""
import shlex
from live_fixture import LiveFixture

def arm(f,trigger):
    real=shlex.quote(str(f.ndmc));native=shlex.quote(str(f.native))
    wrapper=f.p/'ndmc-foreign-edit'
    wrapper.write_text('''#!/bin/sh
'''+real+''' "$@";rc=$?
case $2 in '''+trigger+''')
    g=$(printf '%s\\n' "$2" | awk '{for(i=1;i<=NF;i++)if($i~/^domain-list[0-9]+$/){print $i;exit}}')
    awk -v g="$g" '{print} $0=="object-group fqdn " g {print "    include owner-edit.example"}' '''+native+''' > '''+native+'''.new &&
        cat '''+native+'''.new > '''+native+''' || exit 99 ;;
esac
exit "$rc"
''');wrapper.chmod(0o755)
    f.env['VWARD_NDMC']=str(wrapper)

for phase in ('before-delete','after-route-ack'):
    with LiveFixture() as f:
        if phase=='before-delete':
            r=f.invoke('vward_routing_live_service','on','svc','vpn','VPN:Wireguard0','default',0)
            assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
            # The command right before the delete of the own group.
            arm(f,"'dns-proxy no route object-group '*")
            args=('vward_routing_live_service','off','svc','off','-','-',1)
        else:
            arm(f,"'dns-proxy route object-group '*' auto'")
            args=('vward_routing_live_service','on','svc','vpn','VPN:Wireguard0','default',0)
        r=f.invoke(*args)
        assert r.returncode==3,(phase,r.returncode,r.stdout,r.stderr)
        assert 'include owner-edit.example' in f.native.read_text(),(phase,'foreign edit was deleted')
        assert (f.live/'journal'/args[1]/'state').read_text()=='unknown\n',phase
        assert f.startup.read_bytes()!=f.native.read_bytes(),'unknown foreign change was saved as committed'
        if phase=='before-delete':
            calls=f.calls.read_text().splitlines()
            assert not any(c.endswith('\tno object-group fqdn domain-list0') for c in calls),(phase,'delete sent over a foreign include')
print('LIVE_NATIVE_FOREIGN=PASS fresh read before the destructive group delete preserves a foreign edit; shared readback rejects an edit after real ACK; no blind inverse')
