#!/usr/bin/env python3
"""Cached predictions/returned ACK images never replace the final native preflight/Gi."""
import shlex
from fixture import LIBDIR,ROOT,function_source
from live_fixture import LiveFixture

actual=function_source(ROOT/'components/console/scripts/vward-console-config.sh','vward_routing_console_group_locked')
actual=actual.replace('vward_routing_console_group_locked() {','actual_group_worker() {',1)

for phase in ('before-delete','after-route-ack'):
    with LiveFixture() as f:
        if phase=='before-delete':
            r=f.invoke('vward_routing_live_service','on','svc','vpn','VPN:Wireguard0','default',0)
            assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
        external=shlex.quote(str(f.native))
        edit='''awk -v g="$2" '{print} $0=="object-group fqdn " g {print "    include owner-edit.example"}' '''+external+''' > '''+external+'''.new &&
cat '''+external+'''.new > '''+external+''' || return 99
'''
        wrapper='''vward_routing_console_group_locked() {
'''
        if phase=='before-delete':
            wrapper+='''if [ "$1" = delete ];then
'''+edit+'''fi
actual_group_worker "$@"
}
'''
            args=('vward_routing_live_service','off','svc','off','-','-',1)
        else:
            wrapper+='''result=0;actual_group_worker "$@" || result=$?
if [ "$result" = 0 ] && [ "$1" = route ] && [ "$4" = add ];then
'''+edit+'''fi
return "$result"
}
'''
            args=('vward_routing_live_service','on','svc','vpn','VPN:Wireguard0','default',0)
        r=f.run(f.script(actual+wrapper+'"$@"'),*f.libs,*args,env=f.env,timeout=45)
        assert r.returncode==3,(phase,r.returncode,r.stdout,r.stderr)
        assert 'include owner-edit.example' in f.native.read_text(),(phase,'foreign edit was deleted')
        assert (f.live/'journal'/args[1]/'state').read_text()=='unknown\n',phase
        assert f.startup.read_bytes()!=f.native.read_bytes(),'unknown foreign change was saved as committed'
print('LIVE_NATIVE_FOREIGN=PASS actual last preflight preserves edit after prediction; sealed Gi rejects edit after real ACK; no blind inverse')
