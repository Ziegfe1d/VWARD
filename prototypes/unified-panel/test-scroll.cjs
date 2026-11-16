'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'index.html'),'utf8');
test('lower navigation points into a single scrollable page',()=>{
  for(const id of ['overview','network','vpn','routes','ads','dns','components','system','settings','events']){
    assert.ok(html.includes('id="'+id+'"'),id);
    assert.ok(html.includes('href="#'+id+'"'),id);
  }
  for(const fn of ['markNav','atScroll','focusTo','onScroll'])assert.ok(html.includes('function '+fn+'('),fn);
});
test('mode switches and metrics are not faked',()=>{
  assert.doesNotMatch(html,/<button[^>]+data-mode=/);
  assert.doesNotMatch(html,/<button[^>]+data-range=/);
  assert.doesNotMatch(html,/Интерактивный макет|Пример данных/);
});
