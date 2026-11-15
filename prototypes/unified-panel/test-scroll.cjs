'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname,'index.html'),'utf8');
const inline = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)].at(-1)?.[1] || '';

test('standalone HTML embeds valid JavaScript, not a remote script', () => {
  assert.match(html,/^<!doctype html>/i);
  assert.match(inline,/cgi-bin\/api.cgi/);
  assert.doesNotMatch(html,/<script\b[^>]*\bsrc=/i);
  assert.doesNotThrow(() => new vm.Script(inline));
});
test('every bottom navigation item targets this single page', () => {
  for (const id of ['overview','network','vpn','routes','components','dns','ads','system','settings','events']) {
    assert.match(html,new RegExp('\\bid="'+id+'"'));
    assert.ok(html.includes('href="#'+id+'"'));
  }
  assert.match(inline,/addEventListener\('scroll'/);
  assert.match(inline,/scrollIntoView/);
  assert.match(inline,/markNav/);
  assert.match(inline,/const anchors=/);
  assert.match(inline,/renderParts/);
  assert.match(inline,/smartState/);
});
test('no invented statistics or inert demo controls', () => {
  for (const str of ['Нет данных','Ожидает ответа API','Интерактивный макет','Данные загружаются','Маршрут не подтверждён']) {
    assert.ok(!html.includes(str),'stale placeholder '+str);
  }
  assert.doesNotMatch(html,/<button[^>]*\bdata-range=/);
  assert.doesNotMatch(html,/<button[^>]*\bdata-mode=/);
  assert.match(inline,/const DASH='—'/);
});
test('read-only: no writer and no recurring polling', () => {
  assert.doesNotMatch(inline,/method\s*:\s*['"]POST['"]/);
  assert.doesNotMatch(inline,/setInterval\s*\(/);
  assert.match(inline,/credentials:'same-origin'/);
});
