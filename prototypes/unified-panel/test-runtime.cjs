'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync(require('node:path').join(__dirname,'index.html'),'utf8');
const js=(html.match(/<script>([\s\S]*?)<\/script>/)||[])[1]||'';
const first=js.indexOf('function encodeRouteSegment('),last=js.indexOf('function makeRow(',first);
const ctx={};
vm.runInNewContext(js.slice(first,last),ctx,{timeout:1000});
test('runtime URLs are encoded, and traversal/invalid names are rejected',()=>{
  assert.equal(ctx.tunnelPath({name:'OpkgTun4'}),'/vpn/tunnel/OpkgTun4');
  assert.equal(ctx.listPath({name:'Мои домены'}),'/domains/lists/%D0%9C%D0%BE%D0%B8%20%D0%B4%D0%BE%D0%BC%D0%B5%D0%BD%D1%8B');
  for(const name of ['..','../../admin','bad\\name','\0','']) assert.equal(ctx.listPath({name}), '');
});
test('dynamic links and search use one live route generator',()=>{
  for(const func of ['renderRuntimePages','visibleStaticPage','createLiveLink','runtimeGroup','tunnelPath','listPath']) assert.ok(js.includes('function '+func+'('));
  assert.match(js,/var path=tunnelPath\(t\)/);
  assert.match(js,/var path=listPath\(l\)/);
  assert.match(html,/id="live-runtime-links"/);
  assert.match(html,/data-live-path="\/domains\/services"/);
});
test('API failures remove stale links and frozen parts',()=>{
  assert.match(js,/if\(err\)\{data\[slot\]=null/);
  assert.match(js,/if\(slot==='status'\|\|slot==='lists'\)renderRuntimePages\(\)/);
  assert.match(js,/renderComponentPages\(null\)/);
  assert.match(js,/hidden\.indexOf\(p\)!==-1/);
  assert.match(js,/part\.kind==='retired'/);
});
test('preserve expanded directory groups; read-only without polling',()=>{
  assert.match(js,/details\[open\]/);
  assert.match(js,/wrap\.open=true/);
  assert.match(js,/group\.open=wasOpen/);
  assert.doesNotMatch(js,/\.open\(['"]POST['"]/);
  assert.doesNotMatch(js,/setInterval\s*\(/);
});
