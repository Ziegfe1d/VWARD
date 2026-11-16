'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'index.html'),'utf8');
const js=(html.match(/<script>([\s\S]*?)<\/script>/)||[])[1]||'';
test('v8 standalone valid script and one local page',()=>{
  assert.match(html,/^<!doctype html>/i);
  assert.ok(js.length>25000);
  assert.doesNotThrow(()=>new vm.Script(js));
  assert.doesNotMatch(html,/<script[^>]*\bsrc=/);
});
test('all ten primary sections have local anchors',()=>{
  for(const id of ['network','vpn','routes','ads','dns','components','system','settings','events','overview'])assert.match(html,new RegExp('\\bid="'+id+'"'));
});
test('exactly 45 known detail page routes present',()=>{
  assert.equal((html.match(/data-page-id="/g)||[]).length,45);
  for(const href of ['/domains/lists','/domains/autopick','/ai/smartdns','/system/vward','/system/diag','/network/wifi','/utilities/vless']){
    assert.ok(html.includes('data-live-path="'+href+'"'),href);
  }
});
test('About, license, history and help are real, not dummy buttons',()=>{
  for(const id of ['directory','about','changes','help','about-version','about-channel','about-dependencies'])assert.ok(html.includes('id="'+id+'"'),id);
  assert.match(html,/MIT License[\s\S]*?Copyright \(c\) 2026 Ziegfe1d/);
  for(const file of ['LICENSE','CHANGELOG.md','docs/INSTALL.md','docs/PANEL.md','docs/ROADMAP.md','docs/ARCHITECTURE.md'])assert.ok(html.includes('Ziegfe1d/VWARD')&&html.includes(file),file);
  assert.match(js,/function renderAbout\(/);
});
test('no router mutation or invented third-party license',()=>{
  assert.doesNotMatch(js,/xhr\.open\(['"]POST['"]/);
  assert.doesNotMatch(js,/setInterval\s*\(/);
  assert.match(js,/license\.textContent=DASH/);
  assert.match(js,/function renderComponentPages\(/);
  assert.match(js,/status/);
});
