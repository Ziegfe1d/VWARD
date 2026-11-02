#!/usr/bin/env python3
"""Install is offered for each supported absent component; no enable is implied."""
import subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
js = (ROOT / 'web/assets/vward-console.js').read_text()
start = js.index('function compButtons(id) {')
fn = js[start:js.index('\n}\n', start) + 3]
code = '''const S={status:{},awg:{installed:false,vless:{installed:false,tunnels:[]}}};
const st=()=>({services:{}}),cfgOk=()=>true,compBusy=()=>false;
const COMP_ACT={install:'Install'};
const btn=(a,i,t,c,attrs)=>attrs;
const compModTunnels=()=>[],modOff=()=>false;
const pkgFacts=()=>({known:true,installed:false});
''' + fn + '''
for(const id of ['awg','vless','dnsmasq','singbox']) {
 const b=compButtons(id).join('');
 if(!b.includes('data-cact="install"')||b.includes('data-cact="enable"')) throw Error(id+': '+b);
}
'''
r = subprocess.run(['node', '-e', code], capture_output=True, text=True)
assert r.returncode == 0, 'INSTALL_BUTTONS=FAIL: ' + r.stderr
print('INSTALL_BUTTONS=PASS')
