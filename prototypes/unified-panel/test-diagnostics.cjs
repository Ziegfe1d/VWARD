'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'index.html'),'utf8');
const js=(html.match(/<script>([\s\S]*?)<\/script>/)||[])[1]||'';

test('diagnostic reporting is a disabled, opt-in future setting',()=>{
  assert.match(html,/id="diagnostic-sharing"/);
  assert.match(html,/id="diagnostic-sharing-toggle"\s+type="checkbox"\s+disabled/);
  assert.doesNotMatch(html,/id="diagnostic-sharing-toggle"[^>]*\bchecked\b/);
  assert.match(html,/Сейчас никакие диагностические данные не отправляются/);
  assert.match(html,/Состав отчёта, его просмотр перед отправкой/);
  assert.match(html,/Адреса, домены, ключи и токены не должны отправляться автоматически/);
});
test('no uploader, no new endpoint, existing read-only API unchanged',()=>{
  assert.doesNotThrow(()=>new vm.Script(js));
  assert.doesNotMatch(js,/diagnostic-sharing-toggle/);
  assert.doesNotMatch(js,/telemetry|diagnostics-upload|report-upload|send-diagnostics/i);
  assert.doesNotMatch(js,/\b(?:POST|PUT|PATCH|DELETE)\b/);
  assert.match(js,/xhr\.open\('GET'/);
  assert.doesNotMatch(js,/setInterval\s*\(/);
});