#!/usr/bin/env python3
"""One existing segmented storage control, factual counts and explicit preference."""
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]
js = (root / 'web/assets/vward-console.js').read_text()
assert "['Где хранится'" not in js and "ctrlRow('Новые домены хранить'" not in js
assert 'data-sd-store' not in js
start = js.index('function sdStoreRow(')
end = js.index('\n}', start) + 2
code = '''
const cfgOk=()=>true, fmtInt=String, esc=String;
const ctrlRow=(a,b,c)=>a+b+c;
const choiceSlider=(key,opts,cur)=>JSON.stringify({key,opts,cur});
let SDSTORE_BUSY=false;
'''+js[start:end]+'''
let sd={store:'auto',keenetic:0,agh_domains:0,storage:{component:'AdGuard Home',available:false,reason:'not_running',target:'keenetic'}};
let x=sdStoreRow({},sd);
if(!x.includes('Привязок пока нет') || !x.includes('"cur":"auto"') || !x.includes('Роутер')) throw Error(x);
sd={...sd,store:'agh',keenetic:2,agh_domains:3}; x=sdStoreRow({},sd);
if(!x.includes('"cur":"agh"') || !x.includes('Роутер: 2') || !x.includes('AdGuard Home: 3') || !x.includes('не запущен')) throw Error(x);
'''
subprocess.run(['node', '-e', code], check=True, capture_output=True, text=True)
assert 'confirmed.smartdns.store === v' in js, 'a POST reply alone must not select the preference'
assert 'Незавершённая операция сервисов' not in js
assert "actionRecovery(a && a.recovery)" in js and 'actionRecovery(V.recovery)' in js

def fn(name):
    at = js.index('async function '+name+'(')
    return js[at:js.index('\n}',at)+2]

functional = '''
let S={ai:{services:[],smartdns:{store:'auto'}}}, SVC={busy:false}, SDSTORE_BUSY=false;
let actionResult=null,AIBUSY=null,AIQ=null,SVREC_ACTION=false;
const AIRES={},AIREF={}; const render=()=>{},load=async()=>{},errText=x=>x.error||'unknown';
let nextReadback, nextJob={ok:true,done:true,x:{ok:true}};
let apiPost=async()=>{throw Error('lost reply')},apiGet=async()=>nextReadback,bgJob=async()=>nextJob;
'''+fn('sdStoreSet')+'\n'+fn('aiJob')+'''
(async()=>{
  nextReadback={ok:true,services:[],smartdns:{store:'agh'}};
  await sdStoreSet('agh');
  if(SDSTORE_BUSY || S.ai.smartdns.store!=='agh' || !actionResult.text.includes('сохранено')) throw Error('lost reply not read back');
  nextReadback={ok:true,services:[],smartdns:{store:'auto'}};
  await sdStoreSet('agh');
  if(SDSTORE_BUSY || S.ai.smartdns.store!=='auto' || !actionResult.text.includes('не подтверждён')) throw Error('rejection replaced preference');
  nextReadback=null;
  await sdStoreSet('agh');
  if(SDSTORE_BUSY || S.ai.smartdns.store!=='auto') throw Error('missing readback changed preference');
  nextReadback={ok:true,services:[{id:'s',selected:'dns',effective:'dns'}],smartdns:{}};
  await aiJob('s','dns','verified');
  if(SVC.busy || AIRES.s!=='verified') throw Error('mode not verified');
  nextReadback={ok:true,services:[{id:'s',selected:'dns',effective:'mixed'}],smartdns:{}};
  await aiJob('s','dns','verified');
  if(SVC.busy || !AIRES.s.includes('пересекающиеся')) throw Error('conflict hidden');
  nextReadback=null;
  await aiJob('s','dns','verified');
  if(SVC.busy || !AIRES.s.includes('не подтверждён')) throw Error('missing readback declared success');
  bgJob=async()=>{throw Error('broken body')};
  await aiJob('s','vpn','verified');
  if(SVC.busy || !AIRES.s.includes('Не выполнено')) throw Error('waiting never ended');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
subprocess.run(['node','-e',functional],check=True,capture_output=True,text=True)
print('SMARTDNS_STORAGE_UI=PASS')
