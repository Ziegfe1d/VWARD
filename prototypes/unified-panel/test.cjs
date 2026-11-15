'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = __dirname;
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const script = fs.readFileSync(path.join(root, 'app.js'), 'utf8');

function makeElement(tag) {
  return {
    tag, children: [], style: {}, attributes: {}, innerHTML: '', textContent: '',
    hidden: false, disabled: false,
    classList: { add() {}, remove() {}, toggle() {} },
    append(...c) { this.children.push(...c); },
    appendChild(x) { this.children.push(x); },
    replaceChildren(...c) { this.children = c; },
    setAttribute(name,value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
    getAttribute(name) { return this.attributes[name]; },
    addEventListener() {}
  };
}
async function run(responses) {
  const elements = new Map(), requests = [];
  let serial = 0;
  const byId = id => {
    if (!elements.has(id)) elements.set(id, makeElement(id));
    return elements.get(id);
  };
  const document = {
    getElementById: byId, querySelectorAll() { return []; }, querySelector() { return null; },
    createElement(tag) { return makeElement(tag + serial++); },
    createElementNS(_,tag) { return makeElement(tag + serial++); },
    addEventListener() {}
  };
  const window = { setTimeout() { return 1; }, clearTimeout() {} };
  async function fetch(url, options) {
    const action = new URL(url, 'http://test.local').searchParams.get('action');
    requests.push({ action, method: options.method || 'GET', url });
    const response = responses[action];
    if (response && response.status && response.status !== 200) {
      return { status: response.status, ok: false, json: async () => response };
    }
    if (!response) throw Error('No fixture for ' + action);
    return { status: 200, ok: true, json: async () => response };
  }
  vm.runInNewContext(script, { document, window, fetch, AbortController, URLSearchParams }, { timeout: 3000 });
  // resolve the GET microtasks; none of these tests waits on real timers.
  for (let i = 0; i < 120; i++) await Promise.resolve();
  return { byId, requests };
}
const normal = {
  status: { ok:true, wan:{ internet:true, address:'192.0.2.1' },
    wg:{interfaces:[{ name:'TunA', state:'up', connected:true }]},
    platform:{version:'0.2.0',channel:'dev'} },
  'lists-data': { ok:true, lists:[{name:'Private',via:'vpn',count:12},{name:'Direct',via:'bypass',count:5}] },
  'ai-data': { ok:true, smartdns:{alive:'yes',server_rows:[{}]},
    services:[{id:'gpt',name:'ChatGPT',selected:'vpn',effective:'vpn'}] },
  'ads-data': { ok:true,paused:false,component_enabled:true,total_checked:18 },
  notes: { ok:true,items:[{at:1763220000,sev:'warn',title:'Проверка',text:'Сверка'}] }
};

test('read-only successful API rendering uses measured values', async () => {
  const x = await run(normal);
  assert.deepEqual(x.requests.map(r => r.action),
    ['status','lists-data','ai-data','ads-data','notes']);
  assert.ok(x.requests.every(r => r.method === 'GET'));
  assert.equal(x.byId('metric-internet').textContent, 'В сети');
  assert.equal(x.byId('metric-vpn').textContent, '1 из 1');
  assert.equal(x.byId('metric-dns').textContent, 'Доступен');
  assert.equal(x.byId('metric-domains').textContent, '17');
  assert.ok(x.byId('live-map').children.length > 0);
  assert.equal(x.byId('live-services').children.length, 1);
  assert.equal(x.byId('live-events').children.length, 1);
});
test('401 does not initiate further API requests or claim success', async () => {
  const x = await run({ status: {status:401} });
  assert.equal(x.requests.length, 1);
  assert.equal(x.byId('metric-internet').textContent, '—');
  assert.equal(x.byId('metric-vpn').textContent, '—');
  assert.match(x.byId('metric-internet-detail').textContent, /вход/i);
});
test('missing counters are unknown, never invented zeroes', async () => {
  const d = JSON.parse(JSON.stringify(normal));
  d.status.wan.internet = null;
  d['lists-data'].lists[1].count = null;
  d['ai-data'].smartdns.alive = 'unknown';
  const x = await run(d);
  assert.equal(x.byId('metric-internet').textContent, '—');
  assert.equal(x.byId('metric-domains').textContent, '—');
  assert.equal(x.byId('metric-dns').textContent, 'Не проверен');
});
test('HTML preserves original bottom navigation and has no demo metrics', () => {
  assert.match(html,/class="tabbar"/);
  for (const x of ['Обзор','Сеть','VPN','Маршруты','Ещё']) assert.ok(html.includes(x));
  for (const x of ['1 248','27 614','58%','Интерактивный макет']) assert.ok(!html.includes(x));
  assert.ok(!script.includes("method: 'POST'"));
  assert.match(html,/const anchors=/);
  assert.ok(!html.includes('src="./app.js"'));
});

test('server readiness is not green when Smart DNS has no server', async () => {
  const d = JSON.parse(JSON.stringify(normal));
  d['ai-data'].smartdns = {alive:'yes',server_rows:[],own:false};
  const x = await run(d);
  assert.equal(x.byId('metric-dns').textContent,'Не настроен');
  assert.match(x.byId('components').innerHTML,/Не настроен/);
});
test('version is formatted for the owner, not a service identifier', async () => {
  const d = JSON.parse(JSON.stringify(normal));
  d.status.platform.version = '0.2.0-rc.2.fix.36.1';
  d.status.platform.last_sequence = '2026111502';
  const x = await run(d);
  assert.equal(x.byId('live-version').textContent, '0.2.0 RC2 #36.1.261115');
});
