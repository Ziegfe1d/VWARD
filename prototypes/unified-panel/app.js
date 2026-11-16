/* Панель VWARD / единый обзор — отдельный read-only прототип.
   Все сетевые значения только из действующих API. Никаких POST/фиктивных данных. */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const $all = s => Array.from(document.querySelectorAll(s));
  const state = { status: null, lists: null, ai: null, ads: null, notes: null, errors: {}, last: 0, busy: false };
  const API = '/cgi-bin/api.cgi';
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const present = v => v == null || v === '' ? '—' : String(v);
  const known = v => v !== null && v !== undefined;
  const number = v => v === null || v === '' || v === undefined || !Number.isFinite(Number(v)) ? null : Number(v);
  const fmt = v => known(v) ? Number(v).toLocaleString('ru-RU') : '—';
  const nameOf = t => t && (t.description || t.title || t.name) || 'Без названия';
  const empty = (v, message) => { v.textContent = message || 'Нет данных'; v.classList.add('empty-live'); };
  const modeName = { vpn: 'VPN', isp: 'Провайдер', bypass: 'Провайдер', dns: 'Smart DNS', auto: 'Авто', unknown: 'Не подтверждено', mixed: 'Смешанный путь', none: 'Не задан' };
  function label(mode) { return modeName[mode] || 'Не подтверждено'; }
  function errorMessage(ex) {
    if (!ex) return 'Нет ответа';
    return ex.message || String(ex);
  }
  function alertMessage(text) {
    const el = $('live-message');
    el.textContent = text;
    el.hidden = false;
    window.clearTimeout(alertMessage.t);
    alertMessage.t = window.setTimeout(() => { el.hidden = true; }, 5600);
  }
  async function read(action, params) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 20000);
    const search = new URLSearchParams(Object.assign({ action }, params || {}));
    try {
      const reply = await fetch(API + '?' + search, {
        credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
        headers: { Accept: 'application/json' }
      });
      if (reply.status === 401) throw Error('Требуется вход в Панель VWARD');
      if (reply.status === 403) throw Error('Доступ к Панели запрещён');
      if (!reply.ok) throw Error('Ошибка API: HTTP ' + reply.status);
      const value = await reply.json();
      if (!value || typeof value !== 'object') throw Error('Неполный ответ API');
      if (value.ok === false) throw Error('Отказ API: ' + present(value.error));
      return value;
    } catch (ex) {
      if (ex.name === 'AbortError') throw Error('Роутер не ответил за 20 секунд');
      throw ex;
    } finally { window.clearTimeout(timer); }
  }
  async function load(key, action, params) {
    try {
      const data = await read(action, params);
      state[key] = data;
      state.errors[key] = null;
    } catch (ex) {
      state[key] = null; // Never show stale data as if current
      state.errors[key] = errorMessage(ex);
    }
    render();
  }
  function summary() {
    const s = state.status || {};
    const wan = s.wan || {};
    const wg = s.wg || {};
    const interfaces = Array.isArray(wg.interfaces) && !wg.interfaces_unknown ? wg.interfaces : null;
    const active = interfaces ? interfaces.filter(t => String(t.state || '').toLowerCase() !== 'down') : null;
    const up = active ? active.filter(t => t.connected === true || t.connected === 'true' || t.connected === 1 || t.connected === '1') : null;
    const ls = state.lists && Array.isArray(state.lists.lists) ? state.lists.lists : null;
    const counts = { vpn: 0, isp: 0, dns: 0, unknown: 0 };
    if (ls) for (const item of ls) counts[viaOf(item)]++;
    const countsKnown = ls ? ls.every(l => number(l.count) !== null) : false;
    const domains = countsKnown ? ls.reduce((sum, l) => sum + number(l.count), 0) : null;
    const sd = state.ai && state.ai.smartdns || null;
    return { wan: wan.internet === true ? true : wan.internet === false ? false : null,
      wanAddress: wan.address || null, interfaces, active, up, lists: ls, counts, domains, sd,
      services: state.ai && Array.isArray(state.ai.services) ? state.ai.services : null,
      smart: smartState(sd), ads: state.ads, platform: s.platform || null };
  }
  function smartState(sd) {
    if (!sd) return { title: '—', component: 'Нет данных', health: 'unknown' };
    if (Array.isArray(sd.server_rows) && !sd.server_rows.length && !sd.own)
      return { title: 'Не настроен', component: 'Не настроен', health: 'warn' };
    if (sd.alive === 'yes') return { title: 'Доступен', component: 'Работает', health: 'ok' };
    if (sd.alive === 'no') return { title: 'Недоступен', component: 'Нет ответа', health: 'bad' };
    return { title: 'Не проверен', component: 'Не проверен', health: 'warn' };
  }
  function versionText(v, seq) {
    const m = /^(\d+\.\d+\.\d+)(?:-(rc|rp)\.(\d+))?(?:\.fix\.(\d+)(?:\.(\d+))?)?$/.exec(String(v || ''));
    if (!m) return v || '—';
    const d = /^20(\d{6})\d*$/.exec(String(seq || ''));
    return m[1] + (m[2] ? ' ' + m[2].toUpperCase() + m[3] : '') +
      (m[4] ? ' #' + m[4] + '.' + (m[5] || '0') + (d ? '.' + d[1] : '') : '');
  }
  function viaOf(item) {
    if (item && (item.dns_mode === true || item.dns_mode === 1 || item.dns_mode === '1')) return 'dns';
    if (item && item.via === 'vpn') return 'vpn';
    if (item && (item.via === 'bypass' || item.via === 'isp')) return 'isp';
    return 'unknown';
  }
  function setMetric(id, value, detail, health) {
    $(id).textContent = present(value);
    $(id + '-detail').textContent = present(detail);
    const light = document.querySelector('[data-light="' + id + '"]');
    if (!light) return;
    light.className = 'dot' + (health === 'bad' ? ' error' : health === 'warn' ? ' warn' : health === 'unknown' ? ' purple' : '');
    light.style.boxShadow = health === 'ok' ? '' : 'none';
  }
  function drawMetrics(v) {
    setMetric('metric-internet', v.wan === null ? '—' : v.wan ? 'В сети' : 'Нет связи',
      v.wan === null ? state.errors.status || 'Нет подтверждения' : v.wanAddress || 'По данным роутера',
      v.wan === null ? 'unknown' : v.wan ? 'ok' : 'bad');
    const vpnN = v.active === null ? null : v.up.length + ' из ' + v.active.length;
    setMetric('metric-vpn', vpnN, v.active === null ? state.errors.status || 'Нет данных' : v.active.length ? 'Подключённые туннели' : 'Активных туннелей нет',
      v.active === null ? 'unknown' : v.up.length === v.active.length ? 'ok' : 'warn');
    const sd = v.sd;
    setMetric('metric-dns', v.smart.title,
      !sd ? state.errors.ai || 'Нет данных' : v.smart.health === 'ok' ? 'Сервер отвечает' : 'Проверка Smart DNS',
      v.smart.health);
    setMetric('metric-domains', fmt(v.domains), v.lists ? v.lists.length + ' доменных списков' : state.errors.lists || 'Нет данных',
      v.lists ? 'ok' : 'unknown');
    $('live-version').textContent = v.platform ? versionText(v.platform.version, v.platform.last_sequence) : '—';
    $('live-channel').textContent = v.platform ? present(v.platform.channel) : '—';
    $('live-updated').textContent = state.last ? new Date(state.last).toLocaleTimeString('ru-RU') : '—';
  }
  function row(labelText, value) {
    return '<div class="data-line"><span>' + esc(labelText) + '</span><strong>' + esc(present(value)) + '</strong></div>';
  }
  function drawDns(v) {
    const el = $('live-dns');
    if (!v.sd) { empty(el, state.errors.ai || 'Состояние Smart DNS недоступно'); return; }
    el.classList.remove('empty-live');
    const serverCount = Array.isArray(v.sd.server_rows) ? v.sd.server_rows.length : null;
    el.innerHTML = row('Smart DNS', v.smart.component)
      + row('Серверы', known(serverCount) ? serverCount : null)
      + row('DNS роутера', 'Keenetic') + '<a href="/dns" class="button ghost">Открыть DNS</a>';
  }
  function drawAds(v) {
    const el = $('live-ads');
    if (!v.ads) { empty(el, state.errors.ads || 'Нет данных о компоненте'); return; }
    el.classList.remove('empty-live');
    const off = v.ads.component_enabled === false;
    const running = off ? 'Выключен' : v.ads.paused === true ? 'На паузе' : v.ads.paused === false ? 'Не на паузе' : 'Не подтверждено';
    el.innerHTML = row('Режим', running)
      + row('Проверка доменов', known(v.ads.total_checked) ? fmt(number(v.ads.total_checked)) : '—')
      + '<a href="/ads" class="button ghost">Реклама и трекеры</a>';
  }
  function drawComponents(v) {
    const el = $('components');
    const values = [
      ['Интернет', v.wan === null ? 'Нет данных' : v.wan ? 'Работает' : 'Нет связи'],
      ['VPN', v.active === null ? 'Нет данных' : v.active.length ? v.up.length + ' из ' + v.active.length : 'Выключен'],
      ['Smart DNS', v.smart.component],
      ['Реклама', !v.ads ? 'Нет данных' : v.ads.component_enabled === false ? 'Выключена' : v.ads.paused === true ? 'На паузе' : 'Состояние не подтверждено']
    ];
    el.innerHTML = values.map(x => '<div class="status-item"><span class="status-icon">●</span><div class="status-name">' + esc(x[0]) + '</div><div class="status-value">' + esc(x[1]) + '</div></div>').join('');
  }
  function drawChart(v) {
    const el = $('live-chart');
    if (!v.lists) { empty(el, state.errors.lists || 'Нет данных о доменных списках'); $('chart-count').textContent = ''; return; }
    el.classList.remove('empty-live');
    const max = Math.max(1, v.lists.length);
    const names = [['vpn','VPN'],['isp','Провайдер'],['dns','Smart DNS'],['unknown','Неизвестно']];
    el.innerHTML = names.map(n => '<div class="dist-line"><span>' + n[1] + '</span><div class="dist-track"><i style="width:' + (100 * v.counts[n[0]] / max).toFixed(2) + '%"></i></div><strong>' + v.counts[n[0]] + '</strong></div>').join('');
    $('chart-count').textContent = 'Всего: ' + v.lists.length + ' списков. Распределение по назначенным маршрутам.';
  }
  const SVG = 'http://www.w3.org/2000/svg';
  function addSvg(parent,tag,attr,text) {
    const element=document.createElementNS(SVG,tag);
    for(const key in attr)element.setAttribute(key,attr[key]);
    if(known(text))element.textContent=String(text);
    parent.appendChild(element);return element;
  }
  function drawMap(v) {
    const el = $('live-map');
    if (!v.lists) { empty(el, state.errors.lists || 'Нет данных о маршрутах'); return; }
    if (!v.lists.length) { empty(el,'Доменных списков нет'); return; }
    el.classList.remove('empty-live');
    el.replaceChildren();
    const top = v.lists.slice(0, 6), height = 70 + Math.max(top.length * 52, 180);
    const svg = addSvg(el,'svg',{viewBox:'0 0 900 ' + height,role:'img','aria-label':'Настроенные доменные списки и выходы'});
    addSvg(svg,'text',{x:30,y:30,fill:'#ae91ff'},'Списки Keenetic');
    addSvg(svg,'text',{x:403,y:30,fill:'#ae91ff'},'Маршрут');
    addSvg(svg,'text',{x:680,y:30,fill:'#ae91ff'},'Назначение');
    const positions = {vpn:110,isp:178,dns:246,unknown:314};
    const titles = {vpn:'VPN',isp:'Провайдер',dns:'Smart DNS',unknown:'Не определён'};
    for(const via of Object.keys(positions)){
      const y=positions[via];
      addSvg(svg,'circle',{cx:655,cy:y,r:7,fill:via==='unknown'?'#ffb36f':'#55d6e7'});
      addSvg(svg,'text',{x:679,y:y+5},titles[via]);
    }
    top.forEach((item,i)=>{
      const y=65+i*52,via=viaOf(item),dest=positions[via];
      addSvg(svg,'path',{d:'M290 '+y+' C400 '+y+' 525 '+dest+' 655 '+dest,fill:'none',stroke:via==='unknown'?'#ffb36f':'#b193f5','stroke-width':2,opacity:.7});
      addSvg(svg,'circle',{cx:290,cy:y,r:6,fill:'#ffb36f'});
      let name=nameOf(item);if(name.length>28)name=name.slice(0,27)+'…';
      addSvg(svg,'text',{x:278,y:y+5,'text-anchor':'end'},name);
    });
    if(v.lists.length>6)addSvg(svg,'text',{x:30,y:height-5,class:'muted'},'И ещё '+(v.lists.length-6)+' списков');
    const compact=document.createElement('div');compact.className='live-map-mobile';
    top.forEach(item=>{
      const entry=document.createElement('div');entry.className='live-map-row';
      const title=document.createElement('span');title.textContent=nameOf(item);
      const dest=document.createElement('strong');dest.textContent=label(viaOf(item));
      entry.append(title,dest);compact.append(entry);
    });
    if(v.lists.length>6){
      const more=document.createElement('div');more.className='live-status';
      more.textContent='И ещё '+(v.lists.length-6)+' списков';compact.append(more);
    }
    el.append(compact);
  }
  function drawServices(v) {
    const el = $('live-services');
    if (!v.services) { empty(el, state.errors.ai || 'Нет данных о сервисах'); return; }
    if (!v.services.length) { empty(el, 'Сервисы не настроены'); return; }
    el.classList.remove('empty-live');
    el.replaceChildren();
    v.services.forEach(service=>{
      const card=document.createElement('div');card.className='live-service';
      const left=document.createElement('div'),right=document.createElement('div');
      const title=document.createElement('strong');title.textContent=present(service.title || service.name || service.id);
      const info=document.createElement('small');
      info.textContent=service.coverage && number(service.coverage.catalog)!==null && number(service.coverage.routed)!==null
        ? 'Домены: ' + fmt(service.coverage.routed) + ' из ' + fmt(service.coverage.catalog) : 'Режимы сервиса';
      left.append(title,info);
      const route=document.createElement('div');route.className='live-route';
      const selected=document.createElement('span');
      const applied=document.createElement('span');
      selected.textContent='Выбрано: '+(service.selected === null ? 'Не задано' : label(service.selected || service.via));
      applied.textContent='Маршруты: '+label(service.effective || 'unknown');
      route.append(selected,applied);
      const extra=document.createElement('small');extra.textContent=service.effective === 'mixed' ? 'Пересечение маршрутов или DNS' : 'Путь клиента проверяется отдельно';
      const link=document.createElement('a');link.href='/dns';link.textContent='Изменить в Панели VWARD';
      right.append(route,extra,link);card.append(left,right);el.append(card);
    });
  }
  function drawEvents() {
    const el=$('live-events'), notes=state.notes && Array.isArray(state.notes.items)?state.notes.items:null;
    if(!notes){empty(el,state.errors.notes||'История уведомлений недоступна');return;}
    if(!notes.length){empty(el,'Нет сохранённых уведомлений');return;}
    el.classList.remove('empty-live');el.replaceChildren();
    notes.slice().sort((a,b)=>Number(b.at||0)-Number(a.at||0)).slice(0,6).forEach(n=>{
      const box=document.createElement('div');box.className='event';
      const dot=document.createElement('span');dot.className='dot '+(['crit','err','error'].includes(n.sev)?'error':n.sev==='warn'?'warn':'purple');
      const content=document.createElement('div'),t=document.createElement('div'),sub=document.createElement('div'),time=document.createElement('time');
      t.className='event-title';sub.className='event-desc';t.textContent=present(n.title);sub.textContent=n.text||'';
      if(number(n.at)!==null){const date=new Date(Number(n.at)*1000);if(!isNaN(date.getTime())){time.textContent=date.toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});time.dateTime=date.toISOString();}}
      content.append(t,sub);box.append(dot,content,time);el.append(box);
    });
  }
  function render() {
    const v=summary();
    drawMetrics(v);drawChart(v);drawMap(v);drawComponents(v);drawServices(v);drawDns(v);drawAds(v);drawEvents();
  }
  async function refresh() {
    if(state.busy)return;
    state.busy=true;const b=$('refresh');
    b.disabled=true;b.setAttribute('aria-busy','true');
    try {
      await load('status','status');
      if (/вход|доступ/i.test(state.errors.status || '')) return;
      await Promise.all([load('lists','lists-data'),load('ai','ai-data')]);
      await Promise.all([load('ads','ads-data'),load('notes','notes')]);
      if (state.status || state.lists || state.ai || state.ads || state.notes) state.last=Date.now(); render();
      const failed=Object.keys(state.errors).filter(k=>state.errors[k]);
      if(failed.length)alertMessage('Часть данных недоступна: '+failed.map(k=>state.errors[k]).join('; ').slice(0,200));
    } finally {state.busy=false;b.disabled=false;b.removeAttribute('aria-busy');}
  }
  function navigation() {
    const button=$('more-toggle'),sheet=$('more-sheet');
    function close(){sheet.hidden=true;button.setAttribute('aria-expanded','false');}
    $all('.tabbar a,.more-sheet a').forEach(a=>a.addEventListener('click',()=>{
      const href=a.getAttribute('href');
      $all('.tabbar a').forEach(x=>{const active=x.getAttribute('href')===href;x.classList.toggle('is-active',active);if(active)x.setAttribute('aria-current','page');else x.removeAttribute('aria-current');});
      close();
    }));
    button.addEventListener('click',()=>{const open=sheet.hidden;sheet.hidden=!open;button.setAttribute('aria-expanded',String(open));});
    document.addEventListener('click',e=>{if(!sheet.hidden&&!sheet.contains(e.target)&&!button.contains(e.target))close();});
    document.addEventListener('keydown',e=>{if(e.key==='Escape')close();});
  }
  // The router is not polled in the background: no extra load on ndm.
  // Refresh is explicit; credentials and API remain strictly same-origin.
  $all('a[href="#vpn"]').forEach(a=>a.setAttribute('href','#control'));
  $('refresh').addEventListener('click',refresh);
  navigation();render();refresh();
})();
