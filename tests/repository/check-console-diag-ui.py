#!/usr/bin/env python3
"""Panel, 01.11: «Запустить проверку» shows progress and the result on the page (a failed run is
not «выполнена»), and «Управление» names the switched-off components, not a bare count."""
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

js = (Path(__file__).resolve().parents[2] / "web/assets/vward-console.js").read_text()


def fail(m):
    raise SystemExit(f"CONSOLE_DIAG_UI=FAIL: {m}")


if "a === 'diag-run') diagRun()" not in js:
    fail("diag-run must call diagRun()")
if "load('diag', true).then(() => { render(); toast('Диагностика выполнена'); })" in js:
    fail("the old toast-only handler is back")
m = re.search(r"function diagRun\(\) \{.*?\n\}\n", js, re.S)
if not m or "S.errors.diag" not in m.group(0) or "busy: true" not in m.group(0) or "if (DIAG_RUN && DIAG_RUN.busy) return" not in m.group(0):
    fail("diagRun must show busy, ignore a second click and report S.errors.diag")
if "Проверка выполняется" not in js or "diagRunNote() +" not in js:
    fail("the page must say the check is running and show the result")
if "'выключено: ' + n :" in js or "off.join(', ')" not in js:
    fail("«Управление» must name the switched-off components")
# Smart DNS (01.11): a server that does not answer is said so; «Убрать свой сервер» tells what was cleared.
if "sd.alive === 'no'" not in js or "Smart DNS не отвечает" not in js:
    fail("the Panel must say that the Smart DNS server does not answer")
if "в Keenetic строк ' + (c.keenetic || 0)" not in js or "Убирать нечего" not in js:
    fail("«Убрать свой сервер» must report what was cleared, and say when there was nothing")
# 13 (owner 02.11): «DNS» screen - one status line of the chosen way with a dot, a spinner pill while a
# check runs (no toast), «Проверить» with the refresh icon and disabled meanwhile, Smart DNS segment
# off with its reason when the server does not answer; not installed components folded.
if "{ id: 'ai', title: 'DNS'," not in js or "const SHORT = { ai: 'DNS'," not in js:
    fail("«ИИ-сервисы»/«ИИ» must be «DNS»")
if "[/^Проверить/, 'refresh']" not in js or "[/^Переустановить/, 'refresh']" not in js:
    fail("«Проверить» and «Переустановить» use the refresh icon")
at = js.index('  const status = s => {', js.index('function aiPage()'))
status = js[at:js.index('\n  };', at)+5]
at = js.index('function aiSlider(')
slider = js[at:js.index('\n}', at)+2]
# The owner's «Smart DNS» switch (08.11) the slider reads; S.ai has no smartdns_enabled here (on).
feature = re.search(r"^const sdFeatureOff = .*$", js, re.M).group()
slider = feature + "\n" + slider
# Rendering must meet the contract even when the reason is assembled rather
# than written as one source-code literal. No UI guard is bypassed here.
checks = '''
const assert=require('node:assert/strict');
const esc=String,tunLabel=String,prof=()=>({tunnel_interface:'tun'});
const cfgOk=()=>true, S={ai:{}}, SVC={busy:false};
const AICHK={},SVC_VERDICT={},aiPrev={}; const AIBUSY=null;
const AI_VIA=[['vpn','VPN'],['dns','Smart DNS'],['isp','Провайдер']];
const wayName={vpn:'VPN',dns:'Smart DNS',isp:'Провайдер'};
let sdDown=false,sdServerDown=false,sdReason='';
'''+status+'\n'+slider+'''
assert(status({id:'s',via:'vpn',selected:'vpn'}).includes('VPN · не проверен'));
AICHK.s={busy:true};
let text=status({id:'s',via:'vpn',selected:null});
assert(text.includes('busy-pill') && text.includes('class="spin"') && text.includes('проверяется'));
delete AICHK.s; sdDown=true; sdServerDown=true;
for(const why of ['сервер не отвечает','сервер не настроен','ответ сервера не подтверждён']) {
  sdReason=why;
  text=status({id:'s',via:'dns',selected:'dns'});
  assert(text.includes('Smart DNS · '+why) && text.includes('dot crit'));
  text=aiSlider('s','vpn','service',false,true,why);
  const dns=text.match(/<button[^>]*data-ai-via="dns"[^>]*>/)[0];
  assert(dns.includes(' disabled') && dns.includes('title="'+why+'"'));
  assert(text.includes('Smart DNS: '+why));
  for(const way of ['vpn','isp'])
    assert(!text.match(new RegExp('<button[^>]*data-ai-via="'+way+'"[^>]*>'))[0].includes(' disabled'));
}
text=aiSlider('s','dns','service',false,true,'сервер не отвечает');
assert(!text.match(/<button[^>]*data-ai-via="dns"[^>]*>/)[0].includes(' disabled'));
'''
r = subprocess.run(['node', '-e', checks], capture_output=True, text=True)
if r.returncode:
    fail('card/slider render: ' + r.stderr[-700:])
# The complete status gets its own full-width row; the check button must not
# consume its width. Render the real card template, then inspect semantic DOM.
at=js.index('  const row = s =>',js.index('function aiPage()'))
card=js[at:js.index('  // Smart DNS first:',at)]
prepared_note=re.search(r'^function routingOutcomeNote\(o\) \{.*?^\}\n',js,re.M|re.S).group()
markup=subprocess.check_output(['node','-e', '''
const esc=String,AICHK={},AIRES={},tuns=[],sdDown=false,sdReason='';
const status=()=>'<span class="stat">Длинный статус сервиса с подробной причиной</span>';
const btn=(a,i,t,c,x)=>'<button '+x+'>'+t+'</button>';
const busyBtn=()=>false,aiSlider=()=>'',aiReferenceChoice=()=>'',detail=()=>'';
'''+prepared_note+card+'''console.log(row({id:'canva',title:'Canva',domain:'canva.example',selected:'vpn',via:'vpn'}));'''],text=True)
class Card(HTMLParser):
    def __init__(self):super().__init__();self.stack=[];self.parents={}
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if a.get('class')=='ai-status':self.parents['status']=list(self.stack)
        if tag=='button':self.parents['button']=list(self.stack)
        if tag not in ('input','br','img','hr'):self.stack.append((tag,a.get('class','')))
    def handle_endtag(self,tag):
        if self.stack and self.stack[-1][0]==tag:self.stack.pop()
p=Card();p.feed(markup)
if p.parents.get('status',[])[-1:]!=[('div','ai-head')] or p.parents.get('button')!=p.parents.get('status'):
    fail('the service status needs its own header row, outside the title/button width')
if "Не установлены (' + missing.length + ')" not in js:
    fail("«Компоненты»: not installed folded into «Не установлены (N)»")
# 14: «Управление» everywhere; AmneziaWG «Установить»; a not installed package shows no update rows.
if "if (id === 'awg' && S.awg && !S.awg.installed) return [b('install', 'primary')];" not in js:
    fail("AmneziaWG not installed: «Установить» in «Управление»")
cc = js[js.index("function compCard("):js.index("const TUN_TYPE =")]
if "f.installed ? [['Автопроверка обновлений'" not in cc or "mgmtNote(" not in cc or "(f.installed ? loadError(['status']) : '')" not in cc:
    fail("a not installed package: state, source, use and «Управление» only, no data warning")
if "fix.3" in js[js.index("function soonPanel("):js.index("function soonPanel(") + 600] or "<span class=\"tag soon\">скоро</span>" not in js:
    fail("«В разработке» shows «скоро», not a fix number")
print("CONSOLE_DIAG_UI=PASS")
