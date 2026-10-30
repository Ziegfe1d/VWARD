#!/usr/bin/env python3
"""P-7: configuration membership and a router route never prove a client's path."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory() as td:
    t=Path(td);(t/'root/tmp').mkdir(parents=True)
    cfg=t/'running';cfg.write_text('object-group fqdn AdaptiveAuto\n    include api.ozon.ru\n!\ndns-proxy\n    route object-group AdaptiveAuto Wireguard0 auto\n!\n')
    ndm=t/'ndmc';ndm.write_text('#!/bin/sh\ncat "'+str(cfg)+'"\n');ndm.chmod(0o755)
    resolve=t/'resolve';resolve.write_text('''#!/bin/sh
case "$1" in
 api.ozon.ru) echo 'Name: api.ozon.ru'; echo 'Address 1: 192.0.2.10' ;;
 lampa.mx) echo 'Name: lampa.mx'; echo 'Address 1: 198.51.100.20' ;;
 *) exit 1 ;;
esac
''');resolve.chmod(0o755)
    ip=t/'ip';ip.write_text('''#!/bin/sh
[ "$1 $2" = 'route get' ] || exit 99
case "$3" in
 192.0.2.10) echo '192.0.2.10 via 192.0.2.1 dev eth9 src 192.0.2.2' ;;
 198.51.100.20) echo '198.51.100.20 dev tun9 src 198.51.100.2' ;;
 *) exit 1 ;;
esac
''');ip.chmod(0o755)
    env=os.environ|{'VWARD_NDMC':str(ndm),'VWARD_ROOT_PREFIX':str(t/'root'),'VWARD_RESOLVE4_BIN':str(resolve),'VWARD_IP_BIN':str(ip),'VWARD_CONSOLE_CACHE_DIR':str(t/'cache'),'REQUEST_METHOD':'GET','JQ':shutil.which('jq')}
    def probe(kind,value):
        r=subprocess.run(['sh',str(ROOT/'web/cgi-bin/api.cgi')],env=env|{'QUERY_STRING':f'action=route-probe&type={kind}&value={value}'},capture_output=True,text=True,timeout=20)
        x=json.loads(r.stdout.split('\n\n',1)[1]);assert x.get('ok'),x;return x
    oz=probe('domain','api.ozon.ru')
    assert oz['routes']==[{'group':'AdaptiveAuto','interface':'Wireguard0'}],oz
    assert oz.get('router_routes')==[{'ip':'192.0.2.10','known':True,'device':'eth9','gateway':'192.0.2.1','source':'192.0.2.2'}],oz
    assert oz.get('client_path_verified') is False,oz
    la=probe('domain','lampa.mx')
    assert la['routes']==[] and la['router_routes'][0]['device']=='tun9',la
    sc=probe('domain','game.example')
    assert sc['dns']['ipv4']==[] and sc['router_routes']==[] and sc['client_path_verified'] is False,sc
    ipx=probe('ip','198.51.100.20')
    assert ipx['router_routes'][0]['device']=='tun9' and ipx['configured_route'] is False,ipx
    assert probe('ip','203.0.113.77')['router_routes'][0]['known'] is False
    env['VWARD_ROUTE_PROBE_KERNEL']='0'
    assert probe('domain','lampa.mx')['router_routes']==[]
print('ROUTE_PROBE_EVIDENCE=PASS')
# Render the actual UI function: an absent category/list must not be called ISP.
js=(ROOT/'web/assets/vward-console.js').read_text()
fn=js[js.index('function probeText(r) {'):js.index('const ADSV =')]
node=shutil.which('node')
assert node, 'node is required for route evidence rendering'
script='''const esc=String; const tunLabel=String;
const kv=r=>JSON.stringify(r.filter(Boolean));
const st=()=>({wg:{interfaces:[]}}); const prof=()=>({tunnel_interface:'Wireguard0',wan_interface:'ISP'});
const siteState=()=>({}); const errText=()=>'';
'''+fn+'''
const assert=require('node:assert/strict');
let text=probeText({value:'lampa.mx',x:{ok:true,type:'domain',value:'lampa.mx',routes:[],groups:[],dns:{ipv4:['198.51.100.20']},router_routes:[{ip:'198.51.100.20',known:true,device:'tun9',gateway:'',source:''}]}});
assert(!text.includes('через провайдера (без VPN)'),text);
assert(text.includes('tun9') && text.includes('Путь устройства не проверен'),text);
text=probeText({x:{ok:true,type:'ip',value:'198.51.100.20',configured_route:false,router_routes:[{ip:'198.51.100.20',known:true,device:'tun9'}]}});
assert(!text.includes('через провайдера (без VPN)') && text.includes('tun9'),text);
text=probeText({x:{ok:true,type:'domain',value:'game.example',routes:[],dns:{ipv4:[]},router_routes:[]}});
assert(!text.includes('через провайдера (без VPN)') && text.includes('не определены'),text);
console.log('ROUTE_PROBE_UI_EVIDENCE=PASS');
'''
r=subprocess.run([node,'-e',script],capture_output=True,text=True)
assert r.returncode == 0,r.stderr
print(r.stdout.strip())
