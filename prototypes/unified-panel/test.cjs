'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'index.html'),'utf8');
const scripts=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)];
const script=scripts[scripts.length-1]?.[1]||'';
test('self-contained HTML5: no CDN, no demo metrics',()=>{
  assert.match(html,/^<!doctype html>/i);
  assert.equal(scripts.length,1);
  assert.doesNotMatch(html,/<script[^>]*\bsrc=/i);
  for(const x of ['1 248','27 614','58%','Интерактивный макет'])assert.ok(!html.includes(x));
  assert.match(script,/var DASH = '—'/);
});
test('ES5-style script parses with no recent JavaScript syntax',()=>{
  assert.doesNotThrow(()=>new vm.Script(script));
  assert.doesNotMatch(script,/\b(?:const|let|class)\s+[A-Za-z_$]/);
  assert.doesNotMatch(script,/=>|\?\.|\?\?|\.at\(/);
  assert.match(script,/new XMLHttpRequest\(/);
});
test('read-only five-endpoint API, no polling or writes',()=>{
  assert.match(script,/\/cgi-bin\/api\.cgi\?action=/);
  assert.match(script,/xhr\.open\('GET'/);
  assert.doesNotMatch(script,/\b(?:POST|PUT|PATCH|DELETE)\b/);
  assert.doesNotMatch(script,/setInterval\s*\(/);
  for(const a of ['status','lists-data','ai-data','ads-data','notes'])assert.ok(script.includes("['"+a+"'"));
});
test('header: search, notifications, four themes, accessible overlay',()=>{
  for(const id of ['searchBtn','bellBtn','themeBtn','ui-overlay','search-panel','notes-panel','search-input','search-results','notes-content','unread-count'])assert.ok(html.includes('id="'+id+'"'),id);
  assert.match(script,/var themes=\['system','time','light','dark'\]/);
  assert.match(script,/function openOverlay\(/);
  assert.match(script,/function closeOverlay\(/);
});
test('source-derived values only; text injection prevented',()=>{
  assert.doesNotMatch(script,/\.innerHTML\s*=/);
  assert.match(script,/\.textContent\s*=/);
  assert.match(script,/function smartState\(/);
  assert.match(script,/function renderParts\(/);
  assert.match(script,/if\(err\)\{data\[slot\]=null/);
});
test('legacy fallback and modern effects both present',()=>{
  assert.match(html,/-ms-high-contrast/);
  assert.match(html,/prefers-reduced-motion:reduce/);
  assert.match(html,/IntersectionObserver/);
  assert.match(html,/backdrop-filter:blur/);
  assert.match(script,/function reduceMotion\(/);
});
