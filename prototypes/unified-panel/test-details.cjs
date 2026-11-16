'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync(require('node:path').join(__dirname,'index.html'),'utf8');
const js=(html.match(/<script>([\s\S]*?)<\/script>/)||[])[1]||'';
const first=js.indexOf('function knownBoolean('),last=js.indexOf('function revealSections()',first);
assert.ok(first>0&&last>first);
const ctx={
 DASH:'—',array:Array.isArray,short:x=>String(x||''),
 num:x=>x==null||x===''?null:Number(x),format:String,
 vpnState:t=>[t.connected===true?'Подключён':'—'],
 statusName:p=>[p.running===true?'Работает':'—'],
 via:l=>l.via==='vpn'?'vpn':l.via==='bypass'?'isp':'unknown',
 routeNames:{vpn:'VPN',isp:'Провайдер',unknown:'—'},
 dynamicComponentRoutes:{'route-engine':'/utilities/route-engine'},
 tunnelPath:t=>'/vpn/tunnel/'+encodeURIComponent(t.name),
 listPath:l=>'/domains/lists/'+encodeURIComponent(l.name),
 data:{status:{wg:{interfaces:[{name:'OpkgTun4',description:'VPN 1',connected:'unknown'}]},
  parts:{list:[{id:'route-engine',title:'Маршрутизация',enabled:true,installed:true,running:true},
  {id:'retired',kind:'retired'}],hidden:['retired']}},
  lists:{lists:[{name:'Мой список',via:'vpn',count:12,watch:false}]}}
};
vm.runInNewContext(js.slice(first,last),ctx,{timeout:3000});
test('detail view only uses source data',()=>{
 const d=ctx.detailData('list','Мой список');
 assert.equal(d.title,'Мой список');
 assert.equal(d.path,'/domains/lists/%D0%9C%D0%BE%D0%B9%20%D1%81%D0%BF%D0%B8%D1%81%D0%BE%D0%BA');
 assert.equal(d.rows.find(x=>x[0]==='Назначенный путь')[1],'VPN');
 assert.equal(d.rows.find(x=>x[0]==='Доменов в списке')[1],'12');
});
test('unknown VPN state remains unknown, not offline',()=>{
 assert.equal(ctx.knownBoolean('unknown'),null);
 const d=ctx.detailData('tunnel','OpkgTun4');
 assert.equal(d.rows.find(x=>x[0]==='Соединение')[1],'—');
 assert.equal(d.path,'/vpn/tunnel/OpkgTun4');
});
test('hidden and retired components cannot be opened',()=>{
 assert.equal(ctx.detailData('component','retired'),null);
 assert.equal(ctx.detailData('component','nonexistent'),null);
 const d=ctx.detailData('component','route-engine');
 assert.equal(d.title,'Маршрутизация');
 assert.equal(d.rows.find(x=>x[0]==='Запущен')[1],'Да');
});
test('native details and keyboard focus boundaries are present',()=>{
 assert.match(html,/id="detail-panel"/);
 assert.match(html,/id="detail-title" tabindex="-1"/);
 assert.match(js,/if\(activeOverlay&&\(key==='Tab'/);
 assert.match(js,/function updateDetailIfOpen\(/);
 assert.match(js,/if\(slot==='status'\|\|slot==='lists'\)updateDetailIfOpen\(\)/);
});
test('no writes, no extra polling, text-only facts',()=>{
 assert.match(js,/dd\.textContent=/);
 assert.doesNotMatch(js,/\.innerHTML\s*=/);
 assert.match(js,/xhr\.open\('GET'/);
 assert.doesNotMatch(js,/\b(?:POST|PUT|PATCH|DELETE)\b/);
 assert.doesNotMatch(js,/setInterval\s*\(/);
});