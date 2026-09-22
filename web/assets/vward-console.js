'use strict';
(function () {

/* ---------- Утилиты ---------- */
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const dom = d => esc(d).replace(/\./g, '.<wbr>');
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* хранилище браузера недоступно */ } },
  del(k) { try { localStorage.removeItem(k); } catch (e) { /* хранилище браузера недоступно */ } }
};
const num = v => (v == null || v === '' || isNaN(Number(v))) ? null : Number(v);
const fmtInt = v => num(v) == null ? '—' : Number(v).toLocaleString('ru-RU');
const fmtKB = kb => { const n = num(kb); if (n == null) return '—'; if (n >= 1048576) return (n / 1048576).toFixed(1).replace('.', ',') + ' ГБ'; if (n >= 1024) return Math.round(n / 1024) + ' МБ'; return n + ' КБ'; };
const fmtUptime = s => { const n = num(s); if (n == null) return '—'; const d = Math.floor(n / 86400), h = Math.floor(n % 86400 / 3600), m = Math.floor(n % 3600 / 60); return d ? d + ' д ' + h + ' ч' : h ? h + ' ч ' + m + ' мин' : m + ' мин'; };
const fmtSpeed = v => { const n = num(v); return n == null ? '' : n >= 1000 ? (n / 1000).toString().replace('.', ',') + ' Гбит/с' : n + ' Мбит/с'; };
const isTrue = v => v === true || v === 'true' || v === '1' || v === 1 || v === 'yes' || v === 'up';
const IPV4 = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/;
const DOMAIN = /^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;

/* ---------- Иконки: одна сетка 24×24, одна толщина линии ---------- */
const ICON_PATHS = {
  home: '<path d="M4 10.5 12 4l8 6.5"/><path d="M6 9v11h4.5v-5.5h3V20H18V9"/>',
  platform: '<rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/>',
  refresh: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5V9H15"/>',
  globe: '<circle cx="12" cy="12" r="8"/><path d="M4 12h16"/><path d="M12 4c2.2 2.3 3.2 5 3.2 8s-1 5.7-3.2 8c-2.2-2.3-3.2-5-3.2-8s1-5.7 3.2-8z"/>',
  shield: '<path d="M12 3.8 5.5 6.3v5c0 4.2 2.7 7.4 6.5 8.9 3.8-1.5 6.5-4.7 6.5-8.9v-5z"/><path d="m9.3 12.2 1.9 1.9 3.6-3.8"/>',
  route: '<circle cx="6.5" cy="17.5" r="2"/><circle cx="17.5" cy="6.5" r="2"/><path d="M8.5 17.5H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.5"/>',
  wifi: '<path d="M3.5 9.5a12 12 0 0 1 17 0"/><path d="M6.5 12.8a7.8 7.8 0 0 1 11 0"/><path d="M9.5 16a3.6 3.6 0 0 1 5 0"/><path d="M12 19.2h.01"/>',
  block: '<circle cx="12" cy="12" r="8"/><path d="m6.4 6.4 11.2 11.2"/>',
  lock: '<rect x="5" y="10.5" width="14" height="9.5" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/><path d="M12 14.5v2"/>',
  sliders: '<path d="M4 7h9"/><path d="M17 7h3"/><circle cx="15" cy="7" r="2"/><path d="M4 17h3"/><path d="M11 17h9"/><circle cx="9" cy="17" r="2"/>',
  logs: '<path d="M9 6.5h11"/><path d="M9 12h11"/><path d="M9 17.5h11"/><path d="M4.5 6.5h.01"/><path d="M4.5 12h.01"/><path d="M4.5 17.5h.01"/>',
  runtime: '<circle cx="12" cy="12" r="8"/><path d="M12 7.5V12l3 2"/>',
  storage: '<ellipse cx="12" cy="6.5" rx="7" ry="2.5"/><path d="M5 6.5v11c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-11"/><path d="M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5"/>',
  bell: '<path d="M6.5 16.5V11a5.5 5.5 0 0 1 11 0v5.5l1.5 1.5H5z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
  sun: '<circle cx="12" cy="12" r="3.8"/><path d="M12 3.5v1.8M12 18.7v1.8M3.5 12h1.8M18.7 12h1.8M6 6l1.3 1.3M16.7 16.7 18 18M6 18l1.3-1.3M16.7 7.3 18 6"/>',
  moon: '<path d="M19.5 14.2A7.8 7.8 0 1 1 9.8 4.5a6.2 6.2 0 0 0 9.7 9.7z"/>',
  auto: '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor" stroke="none"/>',
  back: '<path d="M19 12H5.5"/><path d="m11 6-6 6 6 6"/>',
  chevron: '<path d="m9.5 6 6 6-6 6"/>',
  close: '<path d="m6.5 6.5 11 11M17.5 6.5l-11 11"/>',
  alert: '<path d="M12 4.5 3.5 19h17z"/><path d="M12 10v4"/><path d="M12 16.8h.01"/>',
  check: '<path d="m5.5 12.5 4 4 9-9"/>',
  edit: '<path d="M5 19h3.5L18.2 9.3a2 2 0 0 0-2.8-2.8L5.7 16.2z"/><path d="m14 8 2.8 2.8"/>',
  eye: '<path d="M3 12s3.3-6 9-6 9 6 9 6-3.3 6-9 6-9-6-9-6z"/><circle cx="12" cy="12" r="2.5"/>',
  eyeOff: '<path d="M4 4l16 16"/><path d="M9.9 6.3A9 9 0 0 1 12 6c5.7 0 9 6 9 6a15 15 0 0 1-2.6 3.3M6.3 7.7A15 15 0 0 0 3 12s3.3 6 9 6a8.7 8.7 0 0 0 3.6-.8"/>',
  more: '<path d="M5.5 12h.01M12 12h.01M18.5 12h.01"/>',
  undo: '<path d="M9 14.5 4.5 10 9 5.5"/><path d="M4.5 10H14a5.5 5.5 0 0 1 0 11h-2"/>',
  up: '<path d="m6 15 6-6 6 6"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6.5a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2"/>',
  share: '<circle cx="17.5" cy="6" r="2.2"/><circle cx="6.5" cy="12" r="2.2"/><circle cx="17.5" cy="18" r="2.2"/><path d="m8.5 11 7-3.9M8.5 13l7 3.9"/>',
  save: '<path d="M12 4.5v10"/><path d="m7.5 10.5 4.5 4.5 4.5-4.5"/><path d="M5 19.5h14"/>',
  archive: '<rect x="4" y="4.5" width="16" height="4.5" rx="1.5"/><path d="M5.5 9v9a1.5 1.5 0 0 0 1.5 1.5h10a1.5 1.5 0 0 0 1.5-1.5V9"/><path d="M10 13h4"/>',
  wrap: '<path d="M4 6.5h16"/><path d="M4 12h12.5a3 3 0 0 1 0 6H13"/><path d="m15 16-2 2 2 2"/><path d="M4 17.5h5"/>',
  external: '<path d="M14 4.5h5.5V10"/><path d="M19.5 4.5 11 13"/><path d="M18 13.5V18a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 5 18V8a1.5 1.5 0 0 1 1.5-1.5H11"/>',
  user: '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>'
};
function iconSvg(name, cls) { return '<svg class="icon' + (cls ? ' ' + cls : '') + '" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' + (ICON_PATHS[name] || ICON_PATHS.platform) + '</svg>'; }
const ico = iconSvg;

/* ---------- API ---------- */
const API = '/cgi-bin/api.cgi';
async function apiFetch(url, options) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 10000);
  try { return await fetch(url, Object.assign({ cache: 'no-store' }, options || {}, { signal: controller.signal })); }
  catch (e) { throw new Error(e.name === 'AbortError' ? 'роутер не ответил за 10 секунд' : 'нет связи с роутером'); }
  finally { clearTimeout(timer); }
}
async function apiGet(action, params) {
  const q = new URLSearchParams(Object.assign({ action: action }, params || {}));
  const r = await apiFetch(API + '?' + q.toString());
  return r.json();
}
async function apiText(action, params) {
  const q = new URLSearchParams(Object.assign({ action: action }, params || {}));
  const r = await apiFetch(API + '?' + q.toString());
  return r.text();
}
async function apiPost(action, fields) {
  const r = await apiFetch(API + '?action=' + encodeURIComponent(action), {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-VWARD-Request': 'console' },
    body: new URLSearchParams(fields).toString()
  });
  return r.json();
}
const API_ERRORS = {
  updater_busy: 'идёт обновление, повторите позже', confirmation_required: 'требуется подтверждение',
  action_unavailable: 'действие недоступно на этом роутере', invalid_domain: 'неверный домен',
  invalid_ipv4: 'неверный IPv4-адрес', control_busy: 'другое действие ещё выполняется',
  no_pending_update: 'нет загруженного обновления', state_action_not_allowed: 'в текущем состоянии обновления это недоступно',
  rollback_unavailable: 'нет резервной копии для отката', recovery_not_required: 'восстановление не требуется',
  config_unavailable: 'файл настроек недоступен', invalid_mac: 'неверный MAC-адрес',
  invalid_value: 'недопустимое значение', invalid_window: 'начало и конец окна совпадают', invalid_category: 'нет такой категории',
  router_rejected: 'роутер отклонил изменение', verification_failed: 'изменение не подтвердилось и отменено',
  config_save_failed: 'роутер не сохранил конфигурацию', router_config_unavailable: 'не удалось прочитать конфигурацию роутера',
  route_change_busy: 'маршруты сейчас меняет другая задача, повторите', profile_unavailable: 'профиль устройства не определён',
  policy_group_unavailable: 'группа маршрутизации не найдена', list_full: 'список заполнен', backup_failed: 'не удалось сделать резервную копию',
  write_failed: 'не удалось записать файл'
};
const errText = x => API_ERRORS[x && x.error] || (x && x.error) || ('код ' + (x && x.rc));

/* ---------- Данные ---------- */
const S = { status: null, route: null, update: null, security: null, diag: null, wifi: null, ads: null, https: null, config: null, logs: {}, errors: {}, loadedAt: {} };
const LOADERS = {
  status: () => apiGet('status'), route: () => apiGet('route-data'), update: () => apiGet('update-data'),
  security: () => apiGet('security-data'), diag: () => apiGet('diagnostics'), wifi: () => apiGet('wifi-data'),
  ads: () => apiGet('ads-data'), https: () => apiGet('ads-https-data'), config: () => apiGet('config-data')
};
const inflight = {};
async function load(key, force) {
  if (inflight[key]) return inflight[key];
  if (!force && S[key] && Date.now() - (S.loadedAt[key] || 0) < 5000) return S[key];
  inflight[key] = (async () => {
    try { S[key] = await LOADERS[key](); S.errors[key] = null; }
    catch (e) { S.errors[key] = e.message; }
    finally { S.loadedAt[key] = Date.now(); delete inflight[key]; }
    return S[key];
  })();
  return inflight[key];
}
const st = () => S.status || {};
const plat = () => st().platform || {};
const prof = () => (S.security && S.security.profile) || {};
const cfg = () => S.config || {};
const cfgOk = () => !!(S.config && S.config.ok && S.config.writable);
const cfgRoute = () => cfg().route || {};

/* ---------- Структура разделов ---------- */
const PAGES = [
  { id: 'overview', title: 'Обзор', icon: 'home', group: 'Главное', data: ['status', 'route', 'wifi', 'ads'] },
  { id: 'logs', title: 'Журналы', icon: 'logs', group: 'Главное', data: [] },
  { id: 'wan', title: 'Интернет', icon: 'globe', group: 'Сеть', data: ['status', 'security'] },
  { id: 'vpn', title: 'VPN', icon: 'shield', group: 'Сеть', data: ['status', 'security', 'config'] },
  { id: 'routes', title: 'Маршрутизация', icon: 'route', group: 'Сеть', data: ['route', 'security', 'status', 'config'] },
  { id: 'wifi', title: 'Wi-Fi клиенты', icon: 'wifi', group: 'Сеть', data: ['wifi', 'security', 'config'] },
  { id: 'ads', title: 'Реклама и трекеры', icon: 'block', group: 'Сеть', data: ['ads', 'security'] },
  { id: 'system', title: 'Система', icon: 'platform', group: 'VWARD', data: ['status', 'diag', 'security'] },
  { id: 'updates', title: 'Обновления', icon: 'refresh', group: 'VWARD', data: ['status', 'update', 'config'] },
  { id: 'settings', title: 'Настройки', icon: 'sliders', group: 'VWARD', data: ['security'] }
];
const SHORT = { overview: 'Обзор', logs: 'Журналы', wan: 'Интернет', vpn: 'VPN', routes: 'Маршруты', wifi: 'Wi-Fi', ads: 'Реклама', system: 'Система', updates: 'Обновл.', settings: 'Настройки' };
const COMPONENTS = [
  { id: 'route-engine', name: 'Движок маршрутизации', desc: 'Отправляет выбранные домены через VPN и ведёт AdaptiveAuto.', deps: ['runtime'], page: 'routes', log: 'routing' },
  { id: 'route-reconciler', name: 'Сверка маршрутов', desc: 'Каждые 5 минут сверяет маршруты роутера с каталогом и исправляет расхождения.', deps: ['route-engine', 'runtime'], page: 'routes', log: 'routing' },
  { id: 'route-tools', name: 'Инструменты маршрутов', desc: 'Проверка адресов и обновление подсказок каталога.', deps: ['runtime'], page: 'routes', log: 'routing' },
  { id: 'policy-sync', name: 'IP-категории', desc: 'Раз в сутки обновляет IP-категории и маршруты по ним.', deps: ['runtime'], page: 'routes', log: 'policy' },
  { id: 'tunnel-guard', name: 'Защита VPN', desc: 'Следит за туннелем WireGuard и включает fail-open, если VPN упал.', deps: ['runtime'], page: 'vpn', log: 'tunnel' },
  { id: 'wan-guard', name: 'Защита интернета', desc: 'Проверяет интернет и поэтапно восстанавливает подключение.', deps: ['runtime'], page: 'wan', log: 'wan' },
  { id: 'wifi-client-guard', name: 'Контроль Wi-Fi клиентов', desc: 'Наблюдает за переходами клиентов между 2.4 и 5 ГГц.', deps: ['runtime'], page: 'wifi', log: 'wifi' },
  { id: 'ads-privacy-guard', name: 'Блокировка рекламы', desc: 'Управляет правилами AdGuard Home и источниками списков.', deps: ['runtime'], page: 'ads', log: 'ads' },
  { id: 'runtime', name: 'Среда выполнения', desc: 'cron, supervisor и служебная очистка. На ней работают почти все компоненты.', deps: [], page: 'system', log: 'cron' },
  { id: 'console', name: 'Console', desc: 'Этот веб-интерфейс и его API.', deps: ['runtime'], page: 'settings', log: 'console' },
  { id: 'update-engine', name: 'Установщик обновлений', desc: 'Проверяет, устанавливает и откатывает подписанные обновления.', deps: ['platform-core'], page: 'updates', log: 'updater' },
  { id: 'platform-core', name: 'Ядро платформы', desc: 'Версия, реестр компонентов и карта установки.', deps: [], page: 'system', log: 'console' }
];
const comp = id => COMPONENTS.find(c => c.id === id);
const LOG_TABS = [
  { id: 'wan', label: 'Интернет' }, { id: 'recovery', label: 'Восстановление' }, { id: 'tunnel', label: 'VPN' },
  { id: 'routing', label: 'Маршрутизация' }, { id: 'policy', label: 'IP-категории' }, { id: 'wifi', label: 'Wi-Fi' },
  { id: 'ads', label: 'Реклама' }, { id: 'updater', label: 'Обновления' }, { id: 'cron', label: 'Расписание' }, { id: 'console', label: 'Console' }
];
const logLabel = id => (LOG_TABS.find(t => t.id === id) || {}).label || id;
const DETAILS = {
  'd-components': { title: 'Компоненты', parent: 'system' },
  'd-diag': { title: 'Диагностика', parent: 'system' },
  'd-cron': { title: 'Задания по расписанию', parent: 'system' },
  'd-mydomains': { title: 'Мои домены', parent: 'routes' },
  'd-force': { title: 'Всегда через VPN', parent: 'routes' },
  'd-dcats': { title: 'Категории доменов', parent: 'routes' },
  'd-adaptive': { title: 'AdaptiveAuto', parent: 'routes' },
  'd-ipcats': { title: 'Активные IP-категории', parent: 'routes' },
  'd-rules': { title: 'Мои правила', parent: 'ads' },
  'd-sources': { title: 'Источники списков', parent: 'ads' },
  'd-jobs': { title: 'Задания', parent: 'ads' },
  'd-https': { title: 'HTTPS-фильтр', parent: 'ads' }
};
COMPONENTS.forEach(c => { DETAILS['c-' + c.id] = { title: c.name, parent: 'd-components' }; });
function page(id) {
  if (!id) return null;
  const p = PAGES.find(x => x.id === id);
  if (p) return p;
  if (DETAILS[id]) return Object.assign({ id: id }, DETAILS[id]);
  if (id.startsWith('t-')) return { id: id, title: id.slice(2), parent: 'vpn' };
  if (id.startsWith('w-')) return { id: id, title: id.slice(2), parent: 'wifi' };
  return null;
}
const parentOf = id => { const p = page(id); return p && p.parent; };
const navId = id => { let x = id; while (parentOf(x)) x = parentOf(x); return x; };
const DATA_FOR = id => { const p = PAGES.find(x => x.id === navId(id)); return p ? p.data : []; };

/* ---------- Состояние интерфейса ---------- */
const TAB_MAX = 4, TAB_DEFAULT = ['overview', 'wan', 'vpn', 'logs'];
let tabIds = store.get('vward-tabs', TAB_DEFAULT).filter(id => PAGES.some(p => p.id === id)).slice(0, TAB_MAX);
if (!tabIds.length) tabIds = TAB_DEFAULT.slice();
let theme = store.get('vward-theme', 'system');
let refreshSec = store.get('vward-refresh', 15);
const CARD_IDS = ['system', 'updates', 'wan', 'vpn', 'routes', 'wifi', 'ads', 'runtime', 'storage'];
let cardOrder = store.get('vward-card-order', CARD_IDS).filter(id => CARD_IDS.includes(id));
CARD_IDS.forEach(id => { if (!cardOrder.includes(id)) cardOrder.push(id); });
let hiddenCards = store.get('vward-card-hidden', []).filter(id => CARD_IDS.includes(id));
let cardView = store.get('vward-card-view', 'grid'); if (!['grid', 'list'].includes(cardView)) cardView = 'grid';
let current = 'overview', editing = false, confirm = null, logTab = 'wan', logWrap = true, actionResult = null;

/* ---------- Построение блоков ---------- */
function panel(title, body, opts) {
  opts = opts || {};
  const p = page(current), same = p && p.title === title, extra = opts.readonly || opts.right;
  const head = same && !extra ? '' : '<div class="panel-head">' + (same ? '' : '<h2>' + esc(title) + '</h2>') + (opts.readonly ? '<span class="note">' + ico('lock') + 'Только чтение</span>' : '') + (opts.right || '') + '</div>';
  return '<section class="panel' + (same ? ' no-title' : '') + '"' + (same ? ' aria-label="' + esc(title) + '"' : '') + '>' + head + (opts.desc ? '<p class="panel-desc">' + esc(opts.desc) + '</p>' : '') + body + '</section>';
}
/* Строка: [название, значение, метка состояния, переход (страница или http-адрес), доп. атрибуты перехода, подсказка] */
function kv(rows) {
  return '<dl class="kv">' + rows.filter(Boolean).map(r => {
    const ext = r[3] && /^https?:/.test(r[3]);
    const val = r[2] ? '<span class="pill ' + r[2] + '">' + esc(r[1]) + '</span>' : '<span class="num">' + esc(r[1]) + '</span>';
    const link = r[3] && !ext;
    return '<div class="kv-row' + (link ? ' link" role="button" tabindex="0" data-go="' + esc(r[3]) + '"' + (r[4] || '') : '"') + ' data-key="' + esc(r[0]) + '"><dt>' + esc(r[0]) + (r[5] ? '<span class="hint">' + esc(r[5]) + '</span>' : '') + '</dt><dd>' +
      (ext ? '<a class="kv-ext" href="' + esc(r[3]) + '" target="_blank" rel="noopener">' + val + ico('external', 'chev') + '</a>' : val + (link ? ico('chevron', 'chev') : '')) + '</dd></div>';
  }).join('') + '</dl>';
}
function ctrlRow(key, control, hint, cls) { return '<div class="kv-row' + (cls ? ' ' + cls : '') + '" data-key="' + esc(key) + '"><dt>' + esc(key) + (hint ? '<span class="hint">' + esc(hint) + '</span>' : '') + '</dt><dd>' + control + '</dd></div>'; }
const sw = (attr, on, label, disabled) => '<label class="switch"><input type="checkbox" ' + attr + (on ? ' checked' : '') + (disabled ? ' disabled' : '') + ' aria-label="' + esc(label) + '"><i></i></label>';
const sel = (attr, label, opts, value) => '<select class="input compact" ' + attr + ' aria-label="' + esc(label) + '">' + opts.map(o => '<option value="' + esc(o[0]) + '"' + (String(value) === String(o[0]) ? ' selected' : '') + '>' + esc(o[1]) + '</option>').join('') + '</select>';
const btn = (act, icon, label, cls, extra) => '<button class="btn' + (cls ? ' ' + cls : '') + '" type="button" data-act="' + act + '"' + (extra || '') + '>' + (icon ? ico(icon) : '') + esc(label) + '</button>';
const empty = t => '<div class="empty">' + esc(t) + '</div>';
function confirmBox(id, text, yesLabel, danger) {
  if (!confirm || confirm.id !== id) return '';
  return '<div class="confirm"><span>' + esc(text) + '</span><button class="btn small ' + (danger ? 'danger' : 'primary') + '" type="button" data-act="confirm-yes">' + esc(yesLabel) + '</button><button class="btn small" type="button" data-act="confirm-no">Отмена</button></div>';
}
function resultBox(id) {
  if (!actionResult || actionResult.id !== id) return '';
  return '<pre class="logbox result">' + esc(actionResult.text) + '</pre>';
}
function loadError(keys) {
  const errs = keys.map(k => S.errors[k]).filter(Boolean);
  return errs.length ? '<p class="field-warn">Часть данных не получена: ' + esc(errs[0]) + '. Повторим автоматически.</p>' : '';
}

/* ---------- Уведомления ---------- */
function notifications() {
  const n = [], s = S.status;
  if (S.errors.status) n.push({ sev: 'crit', title: 'Нет связи с Console API', text: S.errors.status, to: 'system' });
  if (!s) return n;
  const w = s.wan || {}, wg = s.wg || {}, sv = s.services || {}, p = s.platform || {}, stg = s.storage || {};
  if (w.internet === false) n.push({ sev: 'crit', title: 'Нет интернета', text: 'Защита интернета восстанавливает подключение', to: 'wan' });
  const tunnels = wg.interfaces || [], down = tunnels.filter(t => !isTrue(t.connected));
  if (down.length) n.push({ sev: 'warn', title: down.length === tunnels.length ? 'VPN не в сети' : 'Не все туннели в сети', text: down.map(t => t.name + (t.description ? ' · ' + t.description : '')).join(', '), to: 'vpn' });
  if (isTrue(wg.failopen_active)) n.push({ sev: 'warn', title: 'Включён fail-open', text: 'Трафик списков VPN временно идёт напрямую', to: 'vpn' });
  if (sv.crond === false || sv.supervisor === false) n.push({ sev: 'crit', title: 'Задания по расписанию остановлены', text: 'cron или supervisor не запущен', to: 'd-cron' });
  const total = num(stg.total_kb), free = num(stg.free_kb);
  if (total && free != null && free / total < 0.1) n.push({ sev: 'warn', title: 'Мало места в хранилище', text: 'свободно ' + fmtKB(free), to: 'system' });
  if (['FAILED', 'RECOVERY_REQUIRED'].includes(p.phase)) n.push({ sev: 'crit', title: 'Обновление требует внимания', text: phaseText(p.phase), to: 'updates' });
  if (S.update && S.update.pending && S.update.pending.present) n.push({ sev: 'warn', title: 'Доступно обновление', text: S.update.pending.version || '', to: 'updates' });
  const wc = ((S.wifi && S.wifi.clients) || []).filter(c => c.health === 'WARNING').length;
  if (wc) n.push({ sev: 'warn', title: 'Wi-Fi: ' + wc + ' ' + plural(wc, 'клиент требует', 'клиента требуют', 'клиентов требуют') + ' внимания', text: 'частые переходы между 2.4 и 5 ГГц', to: 'wifi' });
  if (S.config && S.config.tunnel_guard && S.config.tunnel_guard.enabled === false) n.push({ sev: 'warn', title: 'Защита VPN выключена', text: 'при падении туннеля сайты из списков VPN будут недоступны', to: 'vpn' });
  if (S.ads && S.ads.paused) n.push({ sev: 'warn', title: 'Блокировка рекламы на паузе', text: 'реклама не блокируется', to: 'ads' });
  return n;
}
function plural(n, one, few, many) { const a = n % 10, b = n % 100; return a === 1 && b !== 11 ? one : a >= 2 && a <= 4 && (b < 12 || b > 14) ? few : many; }
function phaseText(p) { return ({ IDLE: 'Ожидание', CHECKING: 'Проверка', AVAILABLE: 'Доступно обновление', VERIFIED: 'Проверено', BACKING_UP: 'Резервная копия', INSTALLING: 'Установка', VERIFYING: 'Проверка установки', COMMIT_PREPARED: 'Завершение', COMMITTED: 'Установлено', ROLLING_BACK: 'Откат', FAILED: 'Ошибка', RECOVERY_REQUIRED: 'Нужно восстановление' })[p] || p || '—'; }

/* ---------- Карточки обзора ---------- */
function cardData(id) {
  const s = st(), p = plat(), w = s.wan || {}, wg = s.wg || {}, sv = s.services || {}, g = s.storage || {}, r = S.route || {}, wf = S.wifi || {}, a = S.ads || {};
  const tunnels = wg.interfaces || [], up = tunnels.filter(t => isTrue(t.connected)).length;
  const comps = Object.keys(p.components || {}).length;
  const warnWifi = (wf.clients || []).filter(c => c.health === 'WARNING').length;
  switch (id) {
    case 'system': return { icon: 'platform', title: 'Система', to: 'system', value: p.version || '—', sub: comps ? comps + ' ' + plural(comps, 'компонент', 'компонента', 'компонентов') : 'версия VWARD', pill: p.version ? ['ok', 'Норма'] : ['', '—'] };
    case 'updates': return { icon: 'refresh', title: 'Обновления', to: 'updates', value: phaseText(p.phase), sub: '№ ' + (p.last_sequence || 0) + (p.active_slot ? ' · слот ' + p.active_slot : ''), pill: ['info', isTrue(p.auto_apply) ? 'График' : 'Вручную'] };
    case 'wan': return { icon: 'globe', title: 'Интернет', to: 'wan', value: w.internet ? 'В сети' : s.wan ? 'Нет связи' : '—', sub: (w.address || 'адрес не получен') + (w.speed ? ' · ' + fmtSpeed(w.speed) : ''), pill: w.internet ? ['ok', 'Норма'] : s.wan ? ['crit', 'Сбой'] : ['', '—'] };
    case 'vpn': return { icon: 'shield', title: 'VPN', to: 'vpn', value: up + ' из ' + tunnels.length, sub: isTrue(wg.failopen_active) ? 'fail-open включён' : 'fail-open не активен', pill: !tunnels.length ? ['', 'Нет туннелей'] : up === tunnels.length ? ['ok', 'Норма'] : ['warn', 'Внимание'] };
    case 'routes': return { icon: 'route', title: 'Маршрутизация', to: 'routes', value: fmtInt(r.ip && r.ip.managed_routes) + ' ' + plural(num(r.ip && r.ip.managed_routes) || 0, 'маршрут', 'маршрута', 'маршрутов'), sub: fmtInt(r.domains && r.domains.unique) + ' доменов · ' + fmtInt(r.domains && r.domains.categories) + ' категорий', pill: S.route ? ['ok', 'Норма'] : ['', '—'] };
    case 'wifi': return { icon: 'wifi', title: 'Wi-Fi клиенты', to: 'wifi', value: fmtInt(wf.count) + ' ' + plural(num(wf.count) || 0, 'клиент', 'клиента', 'клиентов'), sub: wf.enabled ? (warnWifi ? warnWifi + ' требуют внимания' : 'без замечаний') : 'сбор данных выключен', pill: !S.wifi ? ['', '—'] : warnWifi ? ['warn', 'Внимание'] : wf.enabled ? ['ok', 'Норма'] : ['', 'Выключен'] };
    case 'ads': { const c = a.counts || {}; return { icon: 'block', title: 'Реклама', to: 'ads', value: fmtInt(c.blocked), sub: 'заблокировано доменов', pill: !S.ads ? ['', '—'] : a.paused ? ['warn', 'Пауза'] : ['ok', 'Норма'] }; }
    case 'runtime': return { icon: 'runtime', title: 'Среда выполнения', to: 'system', value: sv.crond && sv.supervisor ? 'Работает' : s.services ? 'Сбой' : '—', sub: 'cron · supervisor', pill: sv.crond && sv.supervisor ? ['ok', 'Норма'] : s.services ? ['crit', 'Сбой'] : ['', '—'] };
    case 'storage': { const t = num(g.total_kb), f = num(g.free_kb), used = t ? Math.round((t - f) / t * 100) : null; return { icon: 'storage', title: 'Хранилище', to: 'system', value: fmtKB(f), sub: 'свободно' + (t ? ' из ' + fmtKB(t) : '') + (g.filesystem ? ' · ' + g.filesystem : ''), pill: used == null ? ['', '—'] : used > 90 ? ['warn', used + ' %'] : ['ok', used + ' %'], meter: used }; }
  }
  return null;
}

/* ---------- Разделы ---------- */
const RENDER = {
  overview() {
    const list = cardOrder.filter(id => editing || !hiddenCards.includes(id));
    const ts = S.loadedAt.status ? new Date(S.loadedAt.status).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : '—';
    let html = '<div class="overview-bar"><span>Обновлено ' + ts + '</span><button class="icon-btn" type="button" data-act="reload" aria-label="Обновить данные">' + ico('refresh') + '</button><span class="spacer"></span>' +
      (editing ? btn('edit', 'check', 'Готово', 'small primary') : btn('edit', 'edit', 'Настроить', 'small')) + '</div>';
    if (editing) html += '<div class="edit-bar"><span>Вид</span><div class="segmented" role="group" aria-label="Вид карточек"><button type="button" data-view="grid" aria-pressed="' + (cardView === 'grid') + '">' + ico('platform') + 'Плитки</button><button type="button" data-view="list" aria-pressed="' + (cardView === 'list') + '">' + ico('logs') + 'Список</button></div><button class="link-btn" type="button" data-act="cards-reset">Сбросить</button></div>';
    html += '<div class="cards' + (editing ? ' editing' : '') + '" data-view="' + cardView + '">' + list.map((id, n) => {
      const c = cardData(id), h = hiddenCards.includes(id);
      return '<div class="card' + (h ? ' is-hidden' : '') + '"' + (editing ? '' : ' role="button" tabindex="0" data-go="' + c.to + '"') + '><div class="card-icon">' + ico(c.icon) + '</div><span class="pill ' + c.pill[0] + '">' + esc(c.pill[1]) + '</span><div class="card-title">' + esc(c.title) + '</div><div class="card-value num">' + esc(c.value) + '</div><div class="card-sub">' + esc(c.sub) + '</div>' +
        (c.meter != null ? '<div class="meter"><i data-width="' + c.meter + '"></i></div>' : '') +
        (editing ? '<div class="card-edit"><button class="icon-btn" type="button" data-card-move="' + id + ':up" aria-label="Выше"' + (n === 0 ? ' disabled' : '') + '>' + ico('up') + '</button><button class="icon-btn" type="button" data-card-move="' + id + ':down" aria-label="Ниже"' + (n === list.length - 1 ? ' disabled' : '') + '>' + ico('down') + '</button><button class="icon-btn" type="button" data-card-toggle="' + id + '" aria-label="' + (h ? 'Показать' : 'Скрыть') + ' карточку">' + ico(h ? 'eyeOff' : 'eye') + '</button></div>' : '') + '</div>';
    }).join('') + '</div>';
    return loadError(['status']) + html;
  },

  wan() {
    const w = st().wan || {}, pr = prof(), stage = num(w.recovery_stage) || 0;
    const steps = ['3 неудачные проверки подряд', 'обновить адрес по DHCP - не чаще раза в 10 минут, до 3 в час', 'переподключить интерфейс - не чаще раза в 30 минут, до 6 в сутки'];
    return loadError(['status']) +
      panel('Подключение', kv([
        ['Состояние', w.internet ? 'В сети' : 'Нет связи', w.internet ? 'ok' : 'crit'],
        ['Интерфейс', (pr.wan_interface || '—') + (pr.wan_device ? ' (' + pr.wan_device + ')' : '')],
        ['Кабель', isTrue(w.carrier) ? 'подключён' + (w.speed ? ' · ' + fmtSpeed(w.speed) : '') : 'нет сигнала'],
        ['IPv4', w.address || '—'],
        ['Шлюз', (w.gateway || '—') + (w.gateway ? (w.gateway_accessible ? ' · доступен' : ' · недоступен') : '')],
        ['DNS', w.dns_accessible ? 'отвечает' : 'не отвечает']
      ]) + '<div class="panel-actions even">' + btn('reload', 'check', 'Проверить') + btn('open-log', 'logs', 'Журнал', '', ' data-log-tab="wan"') + '</div>', { desc: 'Интерфейс определён автоматически.' }) +
      panel('Защита интернета', '<p class="panel-desc">Порядок восстановления:</p><ol class="steps">' + steps.map((x, i) => '<li' + (i + 1 === stage ? ' class="now"' : '') + '>' + esc(x) + '</li>').join('') + '</ol>' +
        kv([['Сейчас', stage ? 'Восстановление, шаг ' + stage : 'Норма', stage ? 'warn' : 'ok'], ['Попыток восстановления подряд', String(num(w.recovery_count) || 0)], ['История восстановлений', 'журнал', '', 'logs', ' data-log-go="recovery"']]));
  },

  vpn() {
    const wg = st().wg || {}, list = wg.interfaces || [], managed = prof().tunnel_interface || '';
    const row = t => { const up = isTrue(t.connected); return '<li class="row link" role="button" tabindex="0" data-go="t-' + esc(t.name) + '"><div class="row-main"><b>' + esc(t.name) + (t.description ? ' · ' + esc(t.description) : '') + '</b><small>' + (t.name === managed ? '<span class="st ok">для маршрутов</span> · ' : '') + esc(t.state || '') + '</small></div><span class="pill ' + (up ? 'ok' : 'warn') + '">' + (up ? 'В сети' : 'Не в сети') + '</span>' + ico('chevron', 'chev') + '</li>'; };
    return loadError(['status']) +
      panel('Туннели', list.length ? '<ul class="rows">' + list.map(row).join('') + '</ul>' : empty('Туннели WireGuard не найдены'), { desc: 'Туннели WireGuard найдены автоматически. Нажмите на туннель, чтобы открыть подробности.' }) +
      panel('Защита VPN', '<dl class="kv">' + ctrlRow('Автоматическая защита', sw('data-cfg-tg', !S.config || cfg().tunnel_guard.enabled !== false, 'Автоматическая защита VPN', !cfgOk())) + '</dl>' +
        confirmBox('tg-off', 'Выключить защиту VPN? Если туннель упадёт, сайты из списков VPN станут недоступны, пока он не восстановится.', 'Выключить', true) + kv([
        ['fail-open', isTrue(wg.failopen_active) ? 'Включён' : 'Не активен', isTrue(wg.failopen_active) ? 'warn' : ''],
        ['Проверка туннеля', 'каждую минуту', '', 'logs', ' data-log-go="tunnel"'],
        ['Потерь подряд', String(num(wg.down_streak) || 0)]
      ]) + '<div class="panel-actions even">' + btn('tunnel-health', 'check', 'Проверить') + btn('open-log', 'logs', 'Журнал', '', ' data-log-tab="tunnel"') + '</div>' + resultBox('tunnel-health'),
      { desc: 'Если туннель упал, трафик из списков VPN временно идёт напрямую, пока VPN не восстановится.' });
  },

  routes() {
    const r = S.route || {}, d = r.domains || {}, ip = r.ip || {}, ad = r.adaptive || {}, pr = prof();
    return loadError(['route']) +
      panel('Сводка', kv([
        ['Туннель для маршрутов', pr.tunnel_interface || '—', '', 'vpn'],
        ['Доменов в каталоге', fmtInt(d.unique)],
        ['Категорий в каталоге', fmtInt(d.categories)],
        ['Маршрутов VWARD', fmtInt(ip.managed_routes)],
        ['Группа маршрутизации', pr.policy_group || '—']
      ])) +
      panel('Что идёт через VPN', kv([
        ['Мои домены', S.config ? (cfgRoute().router_available ? countText((cfgRoute().domains || []).length) : 'нет данных') : '—', '', 'd-mydomains'],
        ['Всегда через VPN', S.config ? countText((cfgRoute().force_vpn || []).length) : '—', '', 'd-force'],
        ['Категории доменов', S.config ? (cfgRoute().categories || []).filter(c => c.enabled).length + ' из ' + (cfgRoute().categories || []).length + ' включены' : '—', '', 'd-dcats'],
        ['AdaptiveAuto', S.config ? countText((cfgRoute().adaptive || []).length) : fmtInt(ad.count) + ' ' + plural(num(ad.count) || 0, 'домен', 'домена', 'доменов'), '', 'd-adaptive'],
        ['Активные IP-категории', fmtInt(ip.active_count) + ' из ' + fmtInt(ip.categories), '', 'd-ipcats'],
        ['Источники каталога', 'itdog ' + fmtInt(d.sources && d.sources.itdog) + ' · v2fly ' + fmtInt(d.sources && d.sources.v2fly)]
      ])) +
      panel('Проверить адрес', '<form class="inline-form" data-form="probe"><input class="input" id="probeInput" placeholder="домен или IPv4, например claude.ai" aria-label="Домен или IPv4" autocomplete="off"><button class="btn primary" type="submit">' + ico('search') + 'Проверить</button></form><div id="probeResult"></div>', { desc: 'Покажет, через какой интерфейс пойдёт трафик.' }) +
      panel('Обслуживание', kv([
        ['Сверка маршрутов', 'каждые 5 минут', '', 'logs', ' data-log-go="routing"'],
        ['Каталог обновлён', d.last_update || '—'],
        ['IP-категории обновлены', ip.last_sync || '—', '', 'logs', ' data-log-go="policy"']
      ]) +
        (confirmBox('route-reconcile', 'Сверить маршруты роутера с каталогом сейчас?', 'Выполнить') || confirmBox('policy-refresh', 'Скачать IP-категории заново и пересобрать маршруты? Это займёт 1-2 минуты.', 'Выполнить') ||
          '<div class="panel-actions even">' + btn('ask', 'check', 'Сверить маршруты', '', ' data-confirm="route-reconcile"') + btn('ask', 'refresh', 'Обновить IP-категории', '', ' data-confirm="policy-refresh"') + btn('refresh-hints', 'refresh', 'Обновить подсказки') + '</div>') +
        resultBox('routes'));
  },

  wifi() {
    const w = S.wifi || {}, clients = w.clients || [], sc = w.scheduler || {};
    const wc = Object.assign({ ENABLED: !!w.enabled, CONTROL_ENABLED: !!w.control_enabled, WINDOW_SEC: 86400, BAND_SWITCH_WARN: 20, WEAK_5G_RSSI: -75, WEAK_5G_SAMPLE_WARN: 5 }, cfg().wifi || {});
    return loadError(['wifi']) +
      panel('Контроль Wi-Fi клиентов', '<dl class="kv">' +
        ctrlRow('Сбор данных', sw('data-cfg-wifi="ENABLED"', wc.ENABLED, 'Сбор данных о Wi-Fi клиентах', !cfgOk()), 'переходы между 2.4 и 5 ГГц и уровень сигнала') +
        ctrlRow('Ручное управление', sw('data-cfg-wifi="CONTROL_ENABLED"', wc.CONTROL_ENABLED, 'Ручное закрепление диапазона', !cfgOk()), 'закрепление устройства за 2.4 или 5 ГГц по вашей команде') +
        '</dl>' + confirmBox('wifi-ctl-on', 'Разрешить закреплять устройства за диапазоном? Изменение применяется только по вашей команде для выбранного устройства.', 'Разрешить') + kv([
        ['Домашний сегмент', prof().lan_interface || '—'],
        ['Последний сбор', sc.last ? sc.last + (num(sc.rc) === 0 ? ' · успешно' : ' · код ' + sc.rc) : '—', '', 'logs', ' data-log-go="wifi"']
      ])) +
      panel('Клиенты', clients.length ? '<ul class="rows">' + clients.map(c => '<li class="row link" role="button" tabindex="0" data-go="w-' + esc(c.mac) + '"><div class="row-main"><b class="mono">' + esc(c.mac) + ' · ' + esc(bandText(c.band)) + '</b><small>' + fmtInt(c.switches) + ' ' + plural(num(c.switches) || 0, 'переход', 'перехода', 'переходов') + (num(c.weak_5g) ? ' · слабый 5 ГГц ' + c.weak_5g + ' раз' : '') + (c.min_5g_rssi && c.min_5g_rssi !== '-' ? ' · мин. ' + esc(c.min_5g_rssi) + ' дБм' : '') + '</small></div><span class="pill ' + (c.health === 'WARNING' ? 'warn' : 'ok') + '">' + esc(recText(c)) + '</span>' + ico('chevron', 'chev') + '</li>').join('') + '</ul>' : empty(w.enabled ? 'Клиентов пока нет' : 'Сбор данных выключен'), { desc: 'Рекомендации не применяются автоматически.' }) +
      panel('Когда предупреждать', '<dl class="kv">' +
        ctrlRow('Окно анализа', sel('data-cfg-wifi="WINDOW_SEC"', 'Окно анализа', withCur([[21600, '6 часов'], [43200, '12 часов'], [86400, '24 часа'], [172800, '2 суток'], [604800, '7 суток']], wc.WINDOW_SEC, ' с'), wc.WINDOW_SEC), 'за какой период считать переходы') +
        ctrlRow('Переходов между диапазонами', sel('data-cfg-wifi="BAND_SWITCH_WARN"', 'Переходов между диапазонами', withCur([[5, 'от 5'], [10, 'от 10'], [20, 'от 20'], [30, 'от 30'], [50, 'от 50']], wc.BAND_SWITCH_WARN, ''), wc.BAND_SWITCH_WARN)) +
        ctrlRow('Слабый сигнал 5 ГГц', sel('data-cfg-wifi="WEAK_5G_RSSI"', 'Слабый сигнал 5 ГГц', withCur([[-65, '-65 дБм'], [-70, '-70 дБм'], [-75, '-75 дБм'], [-80, '-80 дБм'], [-85, '-85 дБм']], wc.WEAK_5G_RSSI, ' дБм'), wc.WEAK_5G_RSSI), 'и ниже') +
        ctrlRow('Слабых замеров', sel('data-cfg-wifi="WEAK_5G_SAMPLE_WARN"', 'Слабых замеров', withCur([[3, 'от 3'], [5, 'от 5'], [10, 'от 10'], [20, 'от 20']], wc.WEAK_5G_SAMPLE_WARN, ''), wc.WEAK_5G_SAMPLE_WARN), 'за окно анализа') +
        '</dl>', { desc: 'Клиент получает предупреждение, когда часто переключается между диапазонами и при этом слабо ловит 5 ГГц.' });
  },

  ads() {
    const a = S.ads || {}, c = a.counts || {}, s = a.settings || {}, j = a.jobs || {}, ag = (S.security && S.security.external_services && S.security.external_services.adguard) || {};
    const aghHost = ag.address || location.hostname, aghUrl = ag.port ? 'http://' + aghHost + ':' + ag.port + '/' : '';
    const runMode = s.RUN_MODE || 'scheduled';
    return loadError(['ads']) +
      panel('Блокировка', '<dl class="kv">' + ctrlRow('Блокировка рекламы и трекеров', sw('data-ads-pause', !a.paused, 'Блокировка рекламы', !S.ads), a.paused ? 'на паузе - реклама не блокируется' : '') + '</dl>' +
        kv([aghUrl ? ['AdGuard Home', aghHost + ':' + ag.port, '', aghUrl] : ['AdGuard Home', 'адрес не настроен']])) +
      panel('Списки и правила', kv([
        ['Заблокировано доменов', fmtInt(c.blocked)],
        ['На проверке', fmtInt(c.review), num(c.review) ? 'warn' : ''],
        ['Разрешено автоматически', fmtInt(num(c.allow) != null ? num(c.allow) + (num(c.trust) || 0) : null)],
        ['Мои правила', fmtInt((a.manual_rules || []).length), '', 'd-rules'],
        ['Источники', (a.sources || []).filter(x => x.mode === 'active').length + ' из ' + (a.sources || []).length + ' активны', '', 'd-sources'],
        ['Задания', j.current && j.current.state && j.current.state !== 'IDLE' ? 'выполняется' : (num(j.queued) ? j.queued + ' в очереди' : 'нет активных'), '', 'd-jobs'],
        ['HTTPS-фильтр', S.https && S.https.ok ? (S.https.status && isTrue(S.https.status.ENABLED) ? 'Включён' : 'Выключен') : 'недоступен', '', 'd-https']
      ])) +
      panel('Публикация в AdGuard Home', kv([['Публиковать автоматически', isTrue(s.AUTO_PUBLISH) ? 'Включено' : 'Выключено', '', null, '', 'без ручного подтверждения']]) +
        (confirmBox('ads-publish', 'Отправить правила в AdGuard Home? Они применятся сразу.', 'Опубликовать') || '<div class="panel-actions">' + btn('ask', 'check', 'Опубликовать правила', 'primary', ' data-confirm="ads-publish"') + '</div>')) +
      panel('Проверить домен', '<form class="inline-form" data-form="ads-probe"><input class="input" id="adsProbe" placeholder="например, mc.yandex.ru" aria-label="Домен" autocomplete="off"><button class="btn primary" type="submit">' + ico('search') + 'Проверить</button></form>', { desc: 'Проверка ставится в очередь заданий; результат появится в «Задания».' }) +
      panel('Настройки блокировки', '<dl class="kv">' +
        ctrlRow('Режим работы', sel('data-ads-set="RUN_MODE"', 'Режим работы', [['scheduled', 'По расписанию'], ['dynamic', 'По запросам'], ['manual', 'Вручную']], runMode), ({ scheduled: 'новые домены проверяются пачкой раз в интервал', dynamic: 'каждый новый домен проверяется сразу', manual: 'проверка только по кнопке' })[runMode]) +
        (runMode === 'scheduled' ? ctrlRow('Интервал', sel('data-ads-set="SCHEDULE_INTERVAL_MIN"', 'Интервал', [['5', '5 минут'], ['10', '10 минут'], ['30', '30 минут'], ['60', '1 час']], s.SCHEDULE_INTERVAL_MIN || '10')) : '') +
        ctrlRow('Обновлять источники автоматически', sw('data-ads-set="AUTO_SOURCE_UPDATE"', isTrue(s.AUTO_SOURCE_UPDATE), 'Обновлять источники автоматически', !S.ads), 'раз в ' + (s.SOURCE_UPDATE_INTERVAL_HOURS || 24) + ' ч') +
        ctrlRow('Новые правила применять к', sel('data-ads-set="AUTO_RULE_SCOPE"', 'Новые правила', [['exact', 'Только домену'], ['suffix', 'Домену и поддоменам']], s.AUTO_RULE_SCOPE || 'exact')) +
        '</dl>' + resultBox('ads'));
  },

  system() {
    const s = st(), r = s.router || {}, p = plat(), g = s.storage || {}, dg = S.diag && S.diag.checks || [];
    const bad = dg.filter(x => x.status !== 'PASS').length;
    return loadError(['status']) +
      panel('Устройство', kv([
        ['Модель', r.model || '—'], ['KeeneticOS', r.version || '—'],
        ['Веб-интерфейс Keenetic', prof().lan_address || location.hostname, '', 'http://' + (prof().lan_address || location.hostname) + '/'],
        ['Версия VWARD', p.version || '—', '', 'updates'], ['Время работы', fmtUptime(r.uptime_sec)]
      ])) +
      panel('Состояние', kv([
        ['Компоненты', COMPONENTS.length + ' ' + plural(COMPONENTS.length, 'компонент', 'компонента', 'компонентов'), '', 'd-components'],
        ['Задания по расписанию', (s.services && s.services.crond ? 'cron работает' : 'cron остановлен'), s.services && s.services.crond ? '' : 'crit', 'd-cron'],
        ['Диагностика', dg.length ? (dg.length - bad) + ' из ' + dg.length + ' в норме' : 'не запускалась', bad ? 'warn' : '', 'd-diag']
      ])) +
      panel('Хранилище', kv([['Свободно', fmtKB(g.free_kb) + ' из ' + fmtKB(g.total_kb)], ['Файловая система', g.filesystem || '—'], ['Служебная очистка', 'каждый час', '', 'logs', ' data-log-go="cron"']]));
  },

  updates() {
    const p = plat(), u = S.update || {}, al = u.allowed || {}, pend = u.pending || {};
    const mode = isTrue(p.auto_apply) ? 'schedule' : 'manual', uc = cfg().update || {};
    const winStart = uc.safe_window_start || String(p.safe_window || '').split(/\s*[-–]\s*/)[0], winEnd = uc.safe_window_end || String(p.safe_window || '').split(/\s*[-–]\s*/)[1];
    const interval = uc.check_interval_seconds || p.check_interval_seconds;
    const acts = [];
    if (al.check) acts.push(btn('update-op', 'refresh', 'Проверить', 'primary', ' data-op="check"'));
    if (al.apply) acts.push(btn('ask', 'save', 'Установить ' + (pend.version || ''), 'primary', ' data-confirm="update-apply"'));
    if (al.retry) acts.push(btn('ask', 'refresh', 'Повторить', '', ' data-confirm="update-retry"'));
    if (al.rollback) acts.push(btn('ask', 'undo', 'Откатить', 'danger', ' data-confirm="update-rollback"'));
    if (al.recover) acts.push(btn('ask', 'alert', 'Восстановить', 'danger', ' data-confirm="update-recover"'));
    const conf = confirmBox('update-apply', 'Установить обновление ' + (pend.version || '') + '? Компоненты перезапустятся.', 'Установить') ||
      confirmBox('update-retry', 'Повторить установку обновления?', 'Повторить') ||
      confirmBox('update-rollback', 'Вернуть предыдущую версию? Компоненты перезапустятся.', 'Откатить', true) ||
      confirmBox('update-recover', 'Восстановить прерванное обновление?', 'Восстановить', true);
    return loadError(['update', 'status']) +
      panel('Состояние', kv([
        ['Состояние', phaseText(u.phase || p.phase), (u.phase || p.phase) === 'FAILED' ? 'crit' : 'ok'],
        ['Версия', (p.version || '—') + ' · № ' + (p.last_sequence || 0)],
        pend.present ? ['Доступно', (pend.version || '') + (pend.priority ? ' · ' + pend.priority : ''), 'info'] : null,
        ['Последняя проверка', p.last_health_check || '—', '', 'logs', ' data-log-go="updater"'],
        ['Откат', u.rollback_available ? 'Доступен' : 'Недоступен', u.rollback_available ? 'info' : '']
      ]) + (conf || (acts.length ? '<div class="panel-actions even">' + acts.join('') + '</div>' : '')) + resultBox('updates')) +
      panel('Настройки обновлений', '<dl class="kv">' +
        ctrlRow('Установка обновлений', sel('data-upd="mode"', 'Установка обновлений', [['schedule', 'По расписанию'], ['manual', 'Вручную']], mode), mode === 'schedule' ? 'в окно установки, критические исправления - сразу' : 'только проверка и уведомление') +
        (mode === 'schedule' ? ctrlRow('Окно установки', '<span class="time-range">' + sel('data-cfg-upd="safe_window_start"', 'Начало окна установки', withCur(HOURS, winStart, ''), winStart) + '–' + sel('data-cfg-upd="safe_window_end"', 'Конец окна установки', withCur(HOURS, winEnd, ''), winEnd) + '</span>', '', 'stack') : '') +
        ctrlRow('Интервал проверки', sel('data-cfg-upd="check_interval_seconds"', 'Интервал проверки', withCur([[900, '15 минут'], [1800, '30 минут'], [3600, '1 час'], [10800, '3 часа'], [21600, '6 часов'], [43200, '12 часов'], [86400, '24 часа']], interval, ' с'), interval)) +
        '</dl>' + kv([['Канал', p.channel === 'dev' ? 'Dev' : p.channel === 'beta' ? 'Бета' : (p.channel || '—')]]),
      { desc: 'Изменения сохраняются сразу. Канал обновлений меняется в update.conf на роутере.' });
  },

  settings() {
    const sec = S.security || {}, l = sec.listener || {}, api = sec.api || {};
    return loadError(['security']) +
      panel('Доступ к Console', kv([
        ['Адрес Console', (l.address || location.hostname) + ':' + (l.port || location.port || '80')],
        ['Вход по учётной записи Keenetic', api.authentication ? 'Включён' : 'Выключен', api.authentication ? 'ok' : 'warn'],
        ['Защита запросов', api.mutation_guard ? 'Включена' : 'Выключена', api.mutation_guard ? 'ok' : 'crit'],
        ['Доступ с других сайтов', api.cors ? 'Разрешён' : 'Запрещён', api.cors ? 'crit' : 'ok']
      ]) + (api.authentication ? '' : '<p class="field-warn">Пока вход выключен, Console открыта любому устройству в домашней сети.</p>'),
      { desc: 'Вход по логину и паролю Keenetic появится в отдельном этапе; на время разработки он выключен.' }) +
      panel('Нижняя панель на телефоне', '<div class="tabbar preview" data-key="Разделы на панели">' + tabsHtml() + '</div><dl class="kv">' + PAGES.map(p => {
        const on = tabIds.includes(p.id), i = tabIds.indexOf(p.id);
        return ctrlRow(p.title, (on ? '<span class="order-btns"><button class="icon-btn" type="button" data-move="' + p.id + ':up" aria-label="Выше"' + (i === 0 ? ' disabled' : '') + '>' + ico('up') + '</button><button class="icon-btn" type="button" data-move="' + p.id + ':down" aria-label="Ниже"' + (i === tabIds.length - 1 ? ' disabled' : '') + '>' + ico('down') + '</button></span>' : '') + sw('data-tabpick="' + p.id + '"', on, 'Показывать «' + p.title + '» на панели'));
      }).join('') + '</dl>', { desc: 'До ' + TAB_MAX + ' разделов и их порядок. Остальные разделы - в меню «Ещё».' }) +
      panel('Интерфейс', '<dl class="kv">' + ctrlRow('Обновлять данные', sel('data-pref="refresh"', 'Обновлять данные', [['15', 'каждые 15 секунд'], ['30', 'каждые 30 секунд'], ['60', 'каждую минуту']], refreshSec)) + '</dl><div class="panel-actions">' + btn('ui-reset', 'undo', 'Сбросить вид Console') + '</div>', { desc: 'Порядок и вид карточек, нижняя панель и тема хранятся в этом браузере.' });
  },

  logs() {
    const text = S.logs[logTab];
    return '<section class="panel" aria-label="Журналы"><div class="panel-head"><div class="panel-tools">' +
      '<button class="icon-btn" type="button" data-act="log-copy" aria-label="Копировать" title="Копировать">' + ico('copy') + '</button>' +
      '<button class="icon-btn" type="button" data-act="log-share" aria-label="Поделиться" title="Поделиться">' + ico('share') + '</button>' +
      '<button class="icon-btn" type="button" data-act="log-save" aria-label="Сохранить журнал в .txt" title="Сохранить журнал в .txt">' + ico('save') + '</button>' +
      '<button class="icon-btn" type="button" data-act="log-save-all" aria-label="Сохранить все журналы" title="Сохранить все журналы">' + ico('archive') + '</button>' +
      '<button class="icon-btn" type="button" data-act="log-wrap" aria-pressed="' + logWrap + '" aria-label="Перенос строк" title="Перенос строк">' + ico('wrap') + '</button>' +
      '<button class="icon-btn" type="button" data-act="log-reload" aria-label="Обновить журнал" title="Обновить журнал">' + ico('refresh') + '</button></div></div>' +
      '<div class="segmented" role="group" aria-label="Журнал">' + LOG_TABS.map(t => '<button type="button" data-log="' + t.id + '" aria-pressed="' + (t.id === logTab) + '">' + esc(t.label) + '</button>').join('') + '</div>' +
      '<pre class="logbox' + (logWrap ? '' : ' nowrap') + '" id="logBox">' + esc(text == null ? 'Загрузка…' : text) + '</pre></section>';
  },

  'd-components'() {
    const pc = plat().components || {};
    return panel('Компоненты', '<ul class="rows">' + COMPONENTS.map(c => { const x = pc[c.id] || {}; return '<li class="row link" role="button" tabindex="0" data-go="c-' + c.id + '"><div class="row-main"><b>' + esc(c.name) + '</b><small>' + esc(x.release || plat().version || '—') + (x.installed_at ? ' · установлен ' + esc(x.installed_at) : '') + '</small></div><span class="pill ' + (x.health === 'PASS' ? 'ok' : '') + '">' + (x.health === 'PASS' ? 'Норма' : 'Нет данных') + '</span>' + ico('chevron', 'chev') + '</li>'; }).join('') + '</ul>');
  },
  'd-diag'() {
    const d = S.diag, map = { 'console-api': 'settings', opt: 'system', lighttpd: 'c-console', crond: 'd-cron', supervisor: 'c-runtime', adguard: 'ads', adaptive: 'c-route-engine', updater: 'updates', config: 'updates', wan: 'wan', wg: 'vpn' };
    return panel('Диагностика', (d && d.checks ? '<ul class="rows">' + d.checks.map(x => { const to = map[x.id]; return '<li class="row' + (to ? ' link" role="button" tabindex="0" data-go="' + to + '"' : '"') + '><div class="row-main"><b>' + esc(x.label) + '</b><small>' + esc(x.detail || '') + '</small></div><span class="pill ' + (x.status === 'PASS' ? 'ok' : x.status === 'FAIL' ? 'crit' : 'warn') + '">' + (x.status === 'PASS' ? 'Норма' : x.status === 'FAIL' ? 'Сбой' : 'Внимание') + '</span>' + (to ? ico('chevron', 'chev') : '') + '</li>'; }).join('') + '</ul>' : empty(S.errors.diag ? 'Диагностика не выполнена: ' + S.errors.diag : 'Загрузка…')) +
      '<div class="panel-actions">' + btn('diag-run', 'check', 'Запустить проверку', 'primary') + '</div>');
  },
  'd-cron'() {
    const c = st().cron || {}, sv = st().services || {};
    const jobs = [['Защита интернета', c.guardian_rc, c.guardian_last, 'wan-guard'], ['Защита VPN', c.wg_rc, c.wg_last, 'tunnel-guard'], ['Сверка маршрутов', c.routing_rc, c.routing_last, 'route-reconciler']];
    return panel('Служба расписания', kv([['cron', sv.crond ? 'Работает' : 'Остановлен', sv.crond ? 'ok' : 'crit'], ['Supervisor', sv.supervisor ? 'Работает' : 'Остановлен', sv.supervisor ? 'ok' : 'crit']])) +
      panel('Последние запуски', '<ul class="rows">' + jobs.map(j => { const ok = String(j[1]) === '0'; return '<li class="row link" role="button" tabindex="0" data-go="c-' + j[3] + '"><div class="row-main"><b>' + esc(j[0]) + '</b><small>' + esc(j[2] || 'ещё не запускалось') + '</small></div><span class="pill ' + (j[1] === '' || j[1] == null ? '' : ok ? 'ok' : 'crit') + '">' + (j[1] === '' || j[1] == null ? 'Нет данных' : ok ? 'Успешно' : 'Код ' + esc(j[1])) + '</span>' + ico('chevron', 'chev') + '</li>'; }).join('') + '</ul>');
  },
  'd-mydomains'() {
    const r = cfgRoute(), list = r.domains || [];
    return cfgNote() + panel('Добавить домен', addForm('route-domain', 'например, claude.ai'), { desc: 'Домен и все его поддомены пойдут через ' + (prof().tunnel_interface || 'VPN') + '. Изменение сохраняется в конфигурации роутера.' }) +
      panel('Мои домены', S.config && !r.router_available ? empty('Не удалось прочитать конфигурацию роутера') : domainRows(list, d => rowBtn('route-domain', 'remove', d, 'close', 'Убрать ' + d + ' из VPN')) || empty('Список пуст'),
        { desc: 'Группа ' + (r.group || prof().policy_group || '—') + ' в Keenetic.' });
  },
  'd-force'() {
    const list = cfgRoute().force_vpn || [];
    return cfgNote() + panel('Добавить домен', addForm('force-vpn', 'например, youtube.com'), { desc: 'Эти домены не уходят из VPN, даже если напрямую они открываются.' }) +
      panel('Всегда через VPN', domainRows(list, d => rowBtn('force-vpn', 'remove', d, 'close', 'Убрать ' + d + ' из списка')) || empty('Список пуст'), { desc: 'Правило действует и на поддомены. Сверка применяет список в течение 5 минут.' });
  },
  'd-dcats'() {
    const cats = cfgRoute().categories || [];
    return cfgNote() + panel('Категории доменов', cats.length ? '<dl class="kv">' + cats.map(c => ctrlRow(c.title || c.id, sw('data-cfg-cat="' + esc(c.id) + '"', c.enabled, 'Категория ' + (c.title || c.id), !cfgOk()))).join('') + '</dl>' : empty('Категории не найдены'),
      { desc: 'Новые домены из включённых категорий автоматически попадают в VPN.' });
  },
  'd-adaptive'() {
    const list = S.config ? cfgRoute().adaptive || [] : (S.route && S.route.adaptive && S.route.adaptive.recent) || [];
    return cfgNote() + panel('AdaptiveAuto', domainRows(list.map(d => typeof d === 'string' ? d : d.domain || ''), d => rowBtn('adaptive', 'pin', d, 'lock', 'Закрепить ' + d + ' в моих доменах') + rowBtn('adaptive', 'remove', d, 'close', 'Вернуть ' + d + ' на прямой маршрут'), 'недоступен напрямую - идёт через VPN') || empty('Пока пусто'),
      { desc: 'Домены, которые VWARD сам отправил через VPN после неудачной прямой проверки. «Закрепить» переносит домен в мои домены, «убрать» - возвращает на прямой маршрут.' });
  },
  'd-ipcats'() {
    const act = (S.route && S.route.ip && S.route.ip.active) || [];
    return panel('Активные IP-категории', act.length ? '<ul class="rows">' + act.map(x => '<li class="row"><div class="row-main"><b>' + esc(typeof x === 'string' ? x : x.name || '') + '</b></div><span class="pill ok">Через VPN</span></li>').join('') + '</ul>' : empty('Активных категорий нет'), { desc: 'Сети сервисов, которые идут через VPN по IP-адресам.' });
  },
  'd-rules'() {
    const rules = (S.ads && S.ads.manual_rules) || [];
    return panel('Добавить правило', '<form class="inline-form" data-form="ads-rule"><input class="input" id="adsRuleDomain" placeholder="домен, например example.com" aria-label="Домен" autocomplete="off"><select class="input compact" id="adsRuleType" aria-label="Действие"><option value="block">Блокировать</option><option value="allow">Разрешить</option></select><select class="input compact" id="adsRuleScope" aria-label="Область"><option value="exact">Только домен</option><option value="suffix">С поддоменами</option></select><button class="btn primary" type="submit">Добавить</button></form>' + resultBox('ads-rule')) +
      panel('Мои правила', rules.length ? '<ul class="rows">' + rules.map(r => '<li class="row"><div class="row-main"><b>' + dom(r.domain) + '</b><small><span class="st ' + (r.type === 'allow' ? 'ok' : 'crit') + '">' + (r.type === 'allow' ? 'разрешён' : 'заблокирован') + '</span> · ' + (r.scope === 'suffix' ? 'домен и поддомены' : 'только домен') + '</small></div><button class="icon-btn" type="button" title="Удалить правило" data-ads-remove="' + esc(r.domain) + '" data-scope="' + esc(r.scope || 'exact') + '" aria-label="Удалить правило ' + esc(r.domain) + '">' + ico('close') + '</button></li>').join('') + '</ul>' : empty('Правил пока нет'), { desc: 'Ручные правила важнее списков и автоматических решений.' });
  },
  'd-sources'() {
    const src = (S.ads && S.ads.sources) || [];
    return panel('Источники списков', src.length ? '<ul class="rows">' + src.map(x => '<li class="row"><div class="row-main"><b>' + esc(x.name || x.id) + '</b><small>' + esc(x.purpose || '') + (x.cached ? ' · загружен' : ' · ещё не загружен') + '</small></div>' + sel('data-ads-source="' + esc(x.id) + '"', 'Режим ' + (x.name || x.id), [['off', 'Выключен'], ['check', 'Проверка'], ['active', 'Активен']], x.mode) + '</li>').join('') + '</ul>' : empty('Источники не найдены'), { desc: '«Проверка» - источник учитывается при оценке, но сам ничего не блокирует. «Активен» - блокирует.' });
  },
  'd-jobs'() {
    const j = (S.ads && S.ads.jobs) || {}, cur = j.current || {}, last = j.last || {};
    return panel('Задания', kv([['Сейчас', cur.state && cur.state !== 'IDLE' ? (cur.type || cur.state) : 'нет активных', cur.state && cur.state !== 'IDLE' ? 'info' : ''], ['В очереди', fmtInt(j.queued || 0)], ['Последнее', (last.type || '—') + (last.state ? ' · ' + last.state : '')]]) +
      '<div class="panel-actions even">' + btn('ads-job', 'search', 'Проверить новые домены', '', ' data-job="scan"') + btn('ads-job', 'refresh', 'Обновить источники', '', ' data-job="sources-update"') + btn('ads-job', 'check', 'Пересобрать правила', '', ' data-job="rules-rebuild"') + '</div>' +
      (last.output ? '<pre class="logbox">' + esc(last.output) + '</pre>' : '') + resultBox('ads-job'));
  },
  'd-https'() {
    const h = S.https;
    if (!h || !h.ok) return panel('HTTPS-фильтр', empty(h && h.error === 'https_backend_missing' ? 'HTTPS-фильтр не установлен на этом роутере' : 'Состояние недоступно'));
    const s = h.status || {};
    return panel('HTTPS-фильтр', kv(Object.keys(s).slice(0, 12).map(k => [k, s[k]])) +
      (confirmBox('https-start', 'Запустить HTTPS-фильтр? Устройства, использующие прокси, пойдут через него.', 'Запустить') || confirmBox('https-ca', 'Создать собственный сертификат для HTTPS-фильтра?', 'Создать') ||
        '<div class="panel-actions even">' + btn('https-op', 'check', 'Проверить настройки', '', ' data-op="validate"') + btn('ask', 'refresh', 'Запустить', '', ' data-confirm="https-start"') + btn('https-op', 'close', 'Остановить', '', ' data-op="stop"') + btn('ask', 'lock', 'Создать сертификат', '', ' data-confirm="https-ca"') + '</div>') + resultBox('https'),
      { desc: 'Экспериментальный фильтр в режиме явного прокси. По умолчанию выключен.' });
  }
};
const HOURS = Array.from({ length: 24 }, (x, i) => { const h = (i < 10 ? '0' : '') + i + ':00'; return [h, h]; });
function withCur(opts, v, unit) { return v == null || v === '' || opts.some(o => String(o[0]) === String(v)) ? opts : opts.concat([[v, v + unit]]); }
function countText(n) { return n + ' ' + plural(n, 'домен', 'домена', 'доменов'); }
function cfgNote() { return !S.config ? '' : !S.config.writable ? '<p class="field-warn">Изменение настроек из Console недоступно: на роутере нет vward-console-config.sh. Установите обновление VWARD.</p>' : ''; }
function addForm(op, placeholder) { return '<form class="inline-form" data-form="cfg-add" data-op="' + op + '"><input class="input" name="domain" placeholder="' + esc(placeholder) + '" aria-label="Домен" autocomplete="off"' + (cfgOk() ? '' : ' disabled') + '><button class="btn primary" type="submit"' + (cfgOk() ? '' : ' disabled') + '>Добавить</button></form>'; }
function rowBtn(op, action, d, icon, label) { return '<button class="icon-btn" type="button" data-cfg-op="' + op + '" data-cfg-action="' + action + '" data-cfg-target="' + esc(d) + '" aria-label="' + esc(label) + '" title="' + esc(label) + '"' + (cfgOk() ? '' : ' disabled') + '>' + ico(icon) + '</button>'; }
function domainRows(list, acts, sub) { return list.length ? '<ul class="rows">' + list.map(d => '<li class="row"><div class="row-main"><b>' + dom(d) + '</b>' + (sub ? '<small>' + esc(sub) + '</small>' : '') + '</div><span class="row-acts">' + acts(d) + '</span></li>').join('') + '</ul>' : ''; }
function bandText(b) { return b === '5' ? '5 ГГц' : b === '2.4' ? '2.4 ГГц' : 'диапазон неизвестен'; }
function recText(c) { return c.recommendation === 'bind_2g' ? 'Закрепить за 2.4' : c.recommendation === 'review' ? 'Проверить' : c.health === 'WARNING' ? 'Внимание' : 'Норма'; }

function tunnelPage(name) {
  const t = ((st().wg || {}).interfaces || []).find(x => x.name === name) || { name: name };
  const up = isTrue(t.connected), managed = prof().tunnel_interface === name;
  return panel(name + (t.description ? ' · ' + t.description : ''), kv([
    ['Состояние', up ? 'В сети' : 'Не в сети', up ? 'ok' : 'warn'], ['Канал связи', t.link || '—'], ['Статус интерфейса', t.state || '—'],
    ['Используется для маршрутов', managed ? 'Да' : 'Нет', managed ? 'info' : '']
  ]), { desc: managed ? 'Через этот туннель идут все домены и сети из «Маршрутизации».' : 'Туннель для маршрутов задаётся в device.conf на роутере.' });
}
function wifiClientPage(mac) {
  const c = ((S.wifi && S.wifi.clients) || []).find(x => x.mac === mac) || { mac: mac };
  const ctl = S.config && S.config.wifi ? S.config.wifi.CONTROL_ENABLED : S.wifi && S.wifi.control_enabled;
  const ops = [['auto', 'Авто', 'WIFI_BAND_AUTO'], ['bind-2g', 'Только 2.4 ГГц', 'WIFI_BIND_2G'], ['bind-5g', 'Только 5 ГГц', 'WIFI_BIND_5G']];
  return panel(mac, kv([['Сейчас', bandText(c.band)], ['Состояние', recText(c), c.health === 'WARNING' ? 'warn' : 'ok'], ['Переходов за окно', fmtInt(c.switches)], ['Слабый 5 ГГц', fmtInt(c.weak_5g) + ' раз'], ['Мин. сигнал 5 ГГц', c.min_5g_rssi && c.min_5g_rssi !== '-' ? c.min_5g_rssi + ' дБм' : '—'], ['Причина', c.reason || '—']])) +
    panel('Диапазон для устройства', '<div class="segmented" role="group" aria-label="Диапазон">' + ops.map(o => '<button type="button" data-wifi-bind="' + o[0] + '" aria-pressed="false"' + (ctl ? '' : ' disabled') + '>' + o[1] + '</button>').join('') + '</div>' +
      (ctl ? '' : '<p class="panel-desc">Закрепление выключено: включите «Ручное управление» в разделе «Wi-Fi клиенты».</p>') +
      (confirm && confirm.id === 'wifi-bind' ? '<div class="confirm"><span>Применить «' + esc(ops.find(o => o[0] === confirm.op)[1]) + '» для ' + esc(mac) + '? Перед изменением сохранится резервная копия настроек, при ошибке изменение откатится.</span><button class="btn small primary" type="button" data-act="confirm-yes">Применить</button><button class="btn small" type="button" data-act="confirm-no">Отмена</button></div>' : '') + resultBox('wifi'),
    { desc: 'Закрепление через штатную настройку Keenetic для зарегистрированных устройств.' });
}
function compPage(c) {
  const x = (plat().components || {})[c.id] || {}, dependents = COMPONENTS.filter(d => d.deps.includes(c.id));
  const link = id => '<li class="row link" role="button" tabindex="0" data-go="c-' + id + '"><div class="row-main"><b>' + esc(comp(id).name) + '</b></div>' + ico('chevron', 'chev') + '</li>';
  return panel(c.name, kv([['Состояние', x.health === 'PASS' ? 'Норма' : 'Нет данных', x.health === 'PASS' ? 'ok' : ''], ['Версия', x.release || plat().version || '—'], ['Установлен', x.installed_at || '—'], ['Обновление', x.update_id || '—']]) +
    '<div class="panel-actions even">' + (c.page ? '<button class="btn" type="button" data-go="' + c.page + '">Открыть раздел</button>' : '') + btn('open-log', 'logs', 'Журнал', '', ' data-log-tab="' + c.log + '"') + '</div>', { desc: c.desc }) +
    panel('Зависит от', c.deps.length ? '<ul class="rows">' + c.deps.map(link).join('') + '</ul>' : '<p class="panel-desc">Ни от чего не зависит.</p>') +
    panel('От него зависят', dependents.length ? '<ul class="rows">' + dependents.map(d => link(d.id)).join('') + '</ul>' : '<p class="panel-desc">Никто не зависит.</p>');
}

/* ---------- Навигация ---------- */
function tabsHtml() {
  const cur = navId(current);
  return tabIds.map(id => '<button class="tab" type="button" data-tab="' + id + '"' + (id === cur ? ' aria-current="page"' : '') + '>' + ico(page(id).icon) + '<span>' + SHORT[id] + '</span></button>').join('') +
    '<button class="tab" type="button" data-tab="more"' + (tabIds.includes(cur) ? '' : ' aria-current="page"') + '>' + ico('more') + '<span>Ещё</span></button>';
}
function renderNav() {
  const cur = navId(current), warnPages = new Set(notifications().map(n => navId(n.to)));
  let html = '', g = '';
  PAGES.forEach(p => {
    if (p.group !== g) { g = p.group; html += '<div class="nav-group">' + g + '</div>'; }
    html += '<button class="nav-item" type="button" data-go="' + p.id + '"' + (p.id === cur ? ' aria-current="page"' : '') + '>' + ico(p.icon) + '<span>' + p.title + '</span>' + (warnPages.has(p.id) ? '<span class="dot" aria-label="Есть уведомление"></span>' : '') + '</button>';
  });
  $('sideNav').innerHTML = html;
  $('tabbar').innerHTML = tabsHtml();
  document.documentElement.style.setProperty('--tabs', tabIds.length + 1);
  const n = notifications().length;
  $('bellBtn').innerHTML = ico('bell') + (n ? '<span class="badge">' + n + '</span>' : '');
  $('bellBtn').setAttribute('aria-label', n ? 'Уведомления: ' + n : 'Уведомления');
  const r = st().router || {};
  $('brandModel').textContent = r.model || 'роутер';
  $('sideVersion').textContent = 'VWARD ' + (plat().version || '');
}
function render() {
  const p = page(current);
  $('pageTitle').textContent = p.title;
  document.title = p.title + ' · VWARD Console';
  const back = $('backBtn');
  back.classList.toggle('detail', !!p.parent);
  back.hidden = current === 'overview';
  back.setAttribute('aria-label', p.parent ? 'Назад: ' + page(p.parent).title : 'Назад к обзору');
  const html = current.startsWith('c-') ? compPage(comp(current.slice(2))) : current.startsWith('t-') ? tunnelPage(current.slice(2)) : current.startsWith('w-') ? wifiClientPage(current.slice(2)) : RENDER[current]();
  $('content').innerHTML = html;
  document.querySelectorAll('.meter i[data-width]').forEach(i => { i.style.width = Math.max(0, Math.min(100, Number(i.dataset.width))) + '%'; });
  document.querySelectorAll('.tabbar.preview').forEach(t => t.style.setProperty('--tabs', tabIds.length + 1));
  renderNav();
}
function go(id, key) {
  if (!page(id)) id = 'overview';
  current = id; editing = false; confirm = null; actionResult = null;
  closeLayer(); render(); window.scrollTo(0, 0);
  if (key) { const row = [...document.querySelectorAll('[data-key]')].find(r => r.dataset.key === key); if (row) { row.scrollIntoView({ block: 'center' }); row.classList.add('flash'); } }
  refreshPage();
}
async function refreshPage() {
  const id = current, keys = DATA_FOR(id).slice();
  if (id === 'logs') { loadLog(logTab); return; }
  if (id.startsWith('t-')) keys.push('status');
  if (id.startsWith('w-')) keys.push('wifi');
  if (id === 'd-https' || id === 'ads') keys.push('https');
  await Promise.all(keys.map(k => load(k)));
  if (current === id && !editing && !document.activeElement.matches('input,select,textarea')) render();
}
async function loadLog(tab, force) {
  if (!force && S.logs[tab] != null) { render(); }
  try { S.logs[tab] = await apiText('log', { name: tab, count: 200 }); }
  catch (e) { S.logs[tab] = 'Журнал недоступен: ' + e.message; }
  if (current === 'logs' && logTab === tab) { const b = $('logBox'); if (b) b.textContent = S.logs[tab]; else render(); }
}

/* ---------- Всплывающие панели ---------- */
function closeLayer() { $('layer').innerHTML = ''; ['searchBtn', 'bellBtn'].forEach(b => $(b).setAttribute('aria-expanded', 'false')); }
function openSheet(title, body, cls, btnId) {
  closeLayer();
  $('layer').innerHTML = '<div class="scrim" data-act="close"></div><div class="sheet ' + (cls || '') + '" role="dialog" aria-label="' + esc(title || 'Поиск') + '">' + (title ? '<div class="sheet-head"><h2>' + esc(title) + '</h2><button class="icon-btn" type="button" data-act="close" aria-label="Закрыть">' + ico('close') + '</button></div>' : '') + body + '</div>';
  if (btnId) $(btnId).setAttribute('aria-expanded', 'true');
}
function openNotes() {
  const n = notifications();
  openSheet('Уведомления', '<div class="sheet-body">' + (n.length ? n.map(x => '<button class="note-item" type="button" data-go="' + x.to + '"><span class="sev ' + x.sev + '">' + ico('alert') + '</span><span><b>' + esc(x.title) + '</b><small>' + esc(x.text) + '</small></span></button>').join('') : empty('Всё работает штатно')) + '</div>', '', 'bellBtn');
}
const SEARCH_INDEX = [
  ['system', 'Модель'], ['system', 'KeeneticOS'], ['system', 'Веб-интерфейс Keenetic'], ['system', 'Версия VWARD'], ['system', 'Компоненты'], ['system', 'Диагностика'], ['system', 'Задания по расписанию'], ['system', 'Свободно'],
  ['wan', 'Интерфейс'], ['wan', 'IPv4'], ['wan', 'Шлюз'], ['wan', 'История восстановлений'],
  ['vpn', 'Автоматическая защита'], ['vpn', 'fail-open'], ['vpn', 'Проверка туннеля'],
  ['routes', 'Туннель для маршрутов'], ['routes', 'Мои домены'], ['routes', 'Всегда через VPN'], ['routes', 'Категории доменов'], ['routes', 'AdaptiveAuto'], ['routes', 'Активные IP-категории'], ['routes', 'Группа маршрутизации'],
  ['wifi', 'Сбор данных'], ['wifi', 'Ручное управление'], ['wifi', 'Домашний сегмент'], ['wifi', 'Окно анализа'], ['wifi', 'Слабый сигнал 5 ГГц'],
  ['ads', 'AdGuard Home'], ['ads', 'Мои правила'], ['ads', 'Источники'], ['ads', 'HTTPS-фильтр'], ['ads', 'Режим работы'],
  ['updates', 'Установка обновлений'], ['updates', 'Окно установки'], ['updates', 'Интервал проверки'], ['updates', 'Канал'],
  ['settings', 'Адрес Console'], ['settings', 'Вход по учётной записи Keenetic'], ['settings', 'Разделы на панели'], ['settings', 'Обновлять данные']
];
function openSearch() {
  openSheet('', '<div class="search-box">' + ico('search') + '<input id="searchInput" placeholder="Раздел, параметр или компонент" aria-label="Поиск по Console" autocomplete="off"><button class="icon-btn" type="button" data-act="close" aria-label="Закрыть">' + ico('close') + '</button></div><div class="sheet-body" id="searchResults"></div>', 'search', 'searchBtn');
  const i = $('searchInput'); i.focus(); renderResults('');
}
function renderResults(q) {
  q = q.trim().toLowerCase();
  const out = [], pages = PAGES.filter(p => !q || p.title.toLowerCase().includes(q));
  const params = SEARCH_INDEX.filter(x => q && (x[1] + ' ' + page(x[0]).title).toLowerCase().includes(q));
  const comps = COMPONENTS.filter(c => q && c.name.toLowerCase().includes(q));
  if (pages.length) out.push('<div class="result-group">Разделы</div>' + pages.map(p => '<button class="result" type="button" data-go="' + p.id + '">' + ico(p.icon) + '<span>' + esc(p.title) + '</span></button>').join(''));
  if (params.length) out.push('<div class="result-group">Параметры</div>' + params.map(x => '<button class="result" type="button" data-go="' + x[0] + '" data-key="' + esc(x[1]) + '">' + ico(page(x[0]).icon) + '<span>' + esc(x[1]) + '<small>' + esc(page(x[0]).title) + '</small></span></button>').join(''));
  if (comps.length) out.push('<div class="result-group">Компоненты</div>' + comps.map(c => '<button class="result" type="button" data-go="c-' + c.id + '">' + ico('platform') + '<span>' + esc(c.name) + '<small>Система · Компоненты</small></span></button>').join(''));
  $('searchResults').innerHTML = out.join('') || empty('Ничего не найдено');
}
function toast(msg) {
  const t = document.createElement('div'); t.className = 'toast'; t.textContent = msg;
  const box = $('toasts'); box.textContent = ''; box.appendChild(t); setTimeout(() => t.remove(), 3200);
}

/* ---------- Действия ---------- */
async function runAction(resultId, action, fields, okMsg) {
  actionResult = { id: resultId, text: 'Выполняется…' }; render();
  try {
    const x = await apiPost(action, fields);
    actionResult = { id: resultId, text: (x.output || x.result || '').trim() || (x.ok ? 'Готово' : 'Ошибка: ' + errText(x)) };
    toast(x.ok ? okMsg : 'Не выполнено: ' + errText(x));
    return x;
  } catch (e) { actionResult = { id: resultId, text: 'Ошибка: ' + e.message }; toast('Ошибка: ' + e.message); return null; }
  finally { render(); }
}
const CONFIRMED = {
  'route-reconcile': () => runAction('routes', 'control', { op: 'route-reconcile', confirm: 'ROUTE_RECONCILE' }, 'Маршруты сверены').then(() => load('route', true)).then(render),
  'policy-refresh': () => runAction('routes', 'control', { op: 'policy-refresh', confirm: 'POLICY_REFRESH' }, 'IP-категории обновлены').then(() => load('route', true)).then(render),
  'update-apply': () => updateOp('apply', 'APPLY_UPDATE'),
  'update-retry': () => updateOp('retry', 'RETRY_UPDATE'),
  'update-rollback': () => updateOp('rollback', 'ROLLBACK_UPDATE'),
  'update-recover': () => updateOp('recover', 'RECOVER_UPDATE'),
  'ads-publish': () => runAction('ads', 'ads-control', { op: 'enqueue', job: 'publish', confirm: 'ADS_PUBLISH' }, 'Публикация поставлена в очередь').then(() => load('ads', true)).then(render),
  'https-start': () => runAction('https', 'ads-https-control', { op: 'start', confirm: 'HTTPS_START' }, 'HTTPS-фильтр запущен').then(() => load('https', true)).then(render),
  'https-ca': () => runAction('https', 'ads-https-control', { op: 'ca-init', confirm: 'HTTPS_CA_INIT' }, 'Сертификат создан').then(() => load('https', true)).then(render),
  'tg-off': () => cfgSet({ op: 'tunnel-guard', value: '0', confirm: 'TUNNEL_GUARD_DISABLE' }, 'Защита VPN выключена', ['status']),
  'wifi-ctl-on': () => cfgSet({ op: 'wifi', target: 'CONTROL_ENABLED', value: '1', confirm: 'WIFI_CONTROL_ENABLE' }, 'Ручное управление включено', ['wifi']),
  'wifi-bind': c => { const op = c.op, mac = current.slice(2), token = { 'bind-2g': 'WIFI_BIND_2G', 'bind-5g': 'WIFI_BIND_5G', auto: 'WIFI_BAND_AUTO' }[op]; return runAction('wifi', 'wifi-control', { op: op, mac: mac, confirm: token }, 'Диапазон изменён').then(() => load('wifi', true)).then(render); }
};
async function cfgSet(fields, okMsg, reload) {
  try {
    const x = await apiPost('config', fields);
    toast(x.ok ? (x.result === 'unchanged' ? 'Уже сохранено' : okMsg) : 'Не сохранено: ' + errText(x));
    return x;
  } catch (e) { toast('Ошибка: ' + e.message); return null; }
  finally { await Promise.all(['config'].concat(reload || []).map(k => load(k, true))); render(); }
}
function updateOp(op, token) {
  return runAction('updates', 'update-control', token ? { op: op, confirm: token } : { op: op }, 'Операция обновления выполнена').then(() => Promise.all([load('update', true), load('status', true)])).then(render);
}
async function adsControl(fields, okMsg, resultId) {
  const x = await runAction(resultId || 'ads', 'ads-control', fields, okMsg);
  await load('ads', true); render(); return x;
}
async function adsSetting(key, value) {
  const fields = {}; fields[key] = value;
  if (key === 'AUTO_PUBLISH' && value === '1') fields.confirm = 'ADS_AUTO_PUBLISH';
  const x = await runAction('ads', 'ads-settings', fields, 'Сохранено');
  await load('ads', true); render(); return x;
}
function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
const today = () => new Date().toISOString().slice(0, 10);
function copyText(text) {
  const fallback = () => {
    const box = $('logBox'); if (!box) return;
    const r = document.createRange(); r.selectNodeContents(box); const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    let ok = false; try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    toast(ok ? 'Журнал скопирован' : 'Текст выделен - скопируйте его вручную');
  };
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(() => toast('Журнал скопирован'), fallback);
  else fallback();
}

document.addEventListener('click', e => {
  const t = e.target.closest('[data-go],[data-act],[data-tab],[data-card-toggle],[data-log],[data-move],[data-card-move],[data-view],[data-ads-remove],[data-wifi-bind],[data-log-go],[data-cfg-op]');
  if (!t || t.disabled) return;
  if (t.dataset.cardToggle) { const id = t.dataset.cardToggle; hiddenCards = hiddenCards.includes(id) ? hiddenCards.filter(x => x !== id) : hiddenCards.concat(id); store.set('vward-card-hidden', hiddenCards); render(); return; }
  if (t.dataset.cardMove) { const [id, dir] = t.dataset.cardMove.split(':'), i = cardOrder.indexOf(id), j = i + (dir === 'up' ? -1 : 1); if (j >= 0 && j < cardOrder.length) { [cardOrder[i], cardOrder[j]] = [cardOrder[j], cardOrder[i]]; store.set('vward-card-order', cardOrder); render(); } return; }
  if (t.dataset.move) { const [id, dir] = t.dataset.move.split(':'), i = tabIds.indexOf(id), j = i + (dir === 'up' ? -1 : 1); if (j >= 0 && j < tabIds.length) { [tabIds[i], tabIds[j]] = [tabIds[j], tabIds[i]]; store.set('vward-tabs', tabIds); render(); } return; }
  if (t.dataset.view) { cardView = t.dataset.view; store.set('vward-card-view', cardView); render(); return; }
  if (t.dataset.logGo) logTab = t.dataset.logGo;
  if (t.dataset.go) { if (t.closest('.preview')) return; go(t.dataset.go, t.dataset.key); return; }
  if (t.dataset.log) { logTab = t.dataset.log; render(); loadLog(logTab, true); return; }
  if (t.dataset.adsRemove) { adsControl({ op: 'remove-override', domain: t.dataset.adsRemove, scope: t.dataset.scope || 'exact' }, 'Правило удалено', 'ads-rule'); return; }
  if (t.dataset.cfgOp) { const d = t.dataset.cfgTarget, msg = { 'route-domain': d + ' убран из VPN', 'force-vpn': d + ' убран из списка', adaptive: t.dataset.cfgAction === 'pin' ? d + ' закреплён в моих доменах' : d + ' идёт напрямую' }[t.dataset.cfgOp]; t.disabled = true; cfgSet({ op: t.dataset.cfgOp, action: t.dataset.cfgAction, target: d }, msg, ['route']); return; }
  if (t.dataset.wifiBind) { confirm = { id: 'wifi-bind', op: t.dataset.wifiBind }; render(); return; }
  if (t.dataset.tab) {
    if (t.closest('.preview')) return;
    if (t.dataset.tab === 'more') { const cur = navId(current); openSheet('Ещё', '<div class="sheet-body">' + PAGES.filter(p => !tabIds.includes(p.id)).map(p => '<button class="menu-item" type="button" data-go="' + p.id + '"' + (p.id === cur ? ' aria-current="page"' : '') + '>' + ico(p.icon) + '<span>' + esc(p.title) + '</span>' + ico('chevron', 'chev') + '</button>').join('') + '</div>'); }
    else go(t.dataset.tab);
    return;
  }
  const a = t.dataset.act;
  if (a === 'close') closeLayer();
  else if (a === 'reload') { Promise.all(DATA_FOR(current).map(k => load(k, true))).then(() => { render(); toast('Данные обновлены'); }); }
  else if (a === 'edit') { editing = !editing; render(); }
  else if (a === 'cards-reset') { cardOrder = CARD_IDS.slice(); hiddenCards = []; cardView = 'grid'; ['vward-card-order', 'vward-card-hidden', 'vward-card-view'].forEach(k => store.del(k)); render(); toast('Карточки сброшены'); }
  else if (a === 'ask') { confirm = { id: t.dataset.confirm }; render(); }
  else if (a === 'confirm-no') { confirm = null; render(); }
  else if (a === 'confirm-yes') { const c = confirm; confirm = null; if (c && CONFIRMED[c.id]) CONFIRMED[c.id](c); else render(); }
  else if (a === 'open-log') { logTab = t.dataset.logTab; go('logs'); }
  else if (a === 'tunnel-health') runAction('tunnel-health', 'control', { op: 'tunnel-health' }, 'Проверка туннеля выполнена').then(() => load('status', true)).then(render);
  else if (a === 'refresh-hints') runAction('routes', 'control', { op: 'refresh-hints' }, 'Подсказки обновлены');
  else if (a === 'update-op') updateOp(t.dataset.op);
  else if (a === 'diag-run') { load('diag', true).then(() => { render(); toast('Диагностика выполнена'); }); }
  else if (a === 'ads-job') adsControl({ op: 'enqueue', job: t.dataset.job }, 'Задание поставлено в очередь', 'ads-job');
  else if (a === 'https-op') runAction('https', 'ads-https-control', { op: t.dataset.op }, 'Готово').then(() => load('https', true)).then(render);
  else if (a === 'ui-reset') {
    ['vward-card-order', 'vward-card-hidden', 'vward-card-view', 'vward-tabs', 'vward-theme', 'vward-refresh'].forEach(k => store.del(k));
    cardOrder = CARD_IDS.slice(); hiddenCards = []; cardView = 'grid'; tabIds = TAB_DEFAULT.slice(); theme = 'system'; refreshSec = 15;
    applyTheme(); restartTimer(); render(); toast('Вид Console сброшен');
  }
  else if (a === 'log-reload') loadLog(logTab, true);
  else if (a === 'log-wrap') { logWrap = !logWrap; t.setAttribute('aria-pressed', logWrap); const b = $('logBox'); if (b) b.classList.toggle('nowrap', !logWrap); }
  else if (a === 'log-copy') copyText(S.logs[logTab] || '');
  else if (a === 'log-share') {
    const text = S.logs[logTab] || '';
    if (navigator.share) navigator.share({ title: 'Журнал VWARD: ' + logLabel(logTab), text: text }).catch(err => { if (err && err.name !== 'AbortError') toast('Поделиться не удалось - используйте «Сохранить»'); });
    else toast('«Поделиться» недоступно в этом браузере - используйте «Копировать» или «Сохранить»');
  }
  else if (a === 'log-save') download('vward-' + logTab + '-' + today() + '.txt', S.logs[logTab] || '');
  else if (a === 'log-save-all') {
    Promise.all(LOG_TABS.map(tb => apiText('log', { name: tb.id, count: 200 }).then(x => '===== ' + tb.label + ' =====\n' + x, e => '===== ' + tb.label + ' =====\nнедоступен: ' + e.message)))
      .then(parts => download('vward-logs-' + today() + '.txt', parts.join('\n\n')));
  }
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeLayer();
  if ((e.key === 'Enter' || e.key === ' ') && e.target.getAttribute && e.target.getAttribute('role') === 'button') { e.preventDefault(); e.target.click(); }
});
document.addEventListener('input', e => { if (e.target.id === 'searchInput') renderResults(e.target.value); });
document.addEventListener('change', e => {
  const t = e.target;
  if (t.dataset.tabpick) {
    const id = t.dataset.tabpick;
    if (t.checked) { if (tabIds.length >= TAB_MAX) { t.checked = false; toast('На панели помещается не больше ' + TAB_MAX + ' разделов'); return; } tabIds.push(id); }
    else { if (tabIds.length <= 1) { t.checked = true; toast('Оставьте хотя бы один раздел'); return; } tabIds = tabIds.filter(x => x !== id); }
    store.set('vward-tabs', tabIds); render(); return;
  }
  if (t.dataset.upd) {
    const p = plat(), on = t.value === 'schedule' ? '1' : '0';
    runAction('updates', 'settings', { auto_apply: on, auto_critical: isTrue(p.auto_critical) ? '1' : '0', auto_important: isTrue(p.auto_important) ? '1' : '0', auto_routine: isTrue(p.auto_routine) ? '1' : '0' }, 'Настройки обновлений сохранены')
      .then(() => load('status', true)).then(render);
    return;
  }
  if (t.hasAttribute('data-cfg-tg')) { if (!t.checked) { t.checked = true; confirm = { id: 'tg-off' }; render(); } else cfgSet({ op: 'tunnel-guard', value: '1' }, 'Защита VPN включена', ['status']); return; }
  if (t.dataset.cfgWifi) {
    const key = t.dataset.cfgWifi, v = t.type === 'checkbox' ? (t.checked ? '1' : '0') : t.value;
    if (key === 'CONTROL_ENABLED' && v === '1') { t.checked = false; confirm = { id: 'wifi-ctl-on' }; render(); return; }
    cfgSet({ op: 'wifi', target: key, value: v }, 'Сохранено', ['wifi']); return;
  }
  if (t.dataset.cfgCat) { cfgSet({ op: 'domain-category', target: t.dataset.cfgCat, value: t.checked ? '1' : '0' }, t.checked ? 'Категория включена' : 'Категория выключена'); return; }
  if (t.dataset.cfgUpd) { cfgSet({ op: 'update', target: t.dataset.cfgUpd, value: t.value }, 'Сохранено', ['status']); return; }
  if (t.dataset.pref === 'refresh') { refreshSec = Number(t.value); store.set('vward-refresh', refreshSec); restartTimer(); toast('Сохранено'); return; }
  if (t.hasAttribute('data-ads-pause')) { adsControl({ op: t.checked ? 'resume' : 'pause' }, t.checked ? 'Блокировка включена' : 'Блокировка на паузе'); return; }
  if (t.dataset.adsSet) { adsSetting(t.dataset.adsSet, t.type === 'checkbox' ? (t.checked ? '1' : '0') : t.value); return; }
  if (t.dataset.adsSource) { adsControl({ op: 'source-mode', source: t.dataset.adsSource, mode: t.value }, 'Режим источника изменён', 'ads-rule'); return; }
});
document.addEventListener('submit', async e => {
  e.preventDefault();
  const f = e.target.dataset.form;
  if (f === 'probe') {
    const v = $('probeInput').value.trim().toLowerCase(), box = $('probeResult');
    if (!IPV4.test(v) && !DOMAIN.test(v)) { box.innerHTML = '<p class="panel-desc">Введите домен или IPv4-адрес.</p>'; return; }
    box.innerHTML = '<p class="panel-desc">Проверяем…</p>';
    try {
      const x = await apiGet('route-probe', { type: IPV4.test(v) ? 'ip' : 'domain', value: v });
      if (!x.ok) { box.innerHTML = '<p class="field-warn">' + esc(errText(x)) + '</p>'; return; }
      box.innerHTML = x.type === 'ip' ? kv([['Адрес', x.value], ['Категории', (x.policy_matches || []).map(m => m.category).join(', ') || 'нет'], ['Маршрут VWARD', x.configured_route ? 'через ' + x.interface : 'нет', x.configured_route ? 'info' : '']])
        : kv([['Домен', x.value], ['IPv4', ((x.dns && x.dns.ipv4) || []).join(', ') || 'не найден'], ['Группы', (x.groups || []).join(', ') || 'нет'], ['Маршрут', (x.routes || []).map(r => r.group + ' → ' + r.interface).join(', ') || 'напрямую', (x.routes || []).length ? 'info' : ''], ['AdaptiveAuto', x.adaptive_auto ? 'Да' : 'Нет']]);
    } catch (err) { box.innerHTML = '<p class="field-warn">Ошибка: ' + esc(err.message) + '</p>'; }
  }
  if (f === 'cfg-add') {
    const input = e.target.querySelector('input'), v = input.value.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/[/:].*$/, '').replace(/^\*\./, '');
    if (!DOMAIN.test(v)) { toast('Введите домен, например example.com'); return; }
    const x = await cfgSet({ op: e.target.dataset.op, action: 'add', target: v }, v + ' добавлен', ['route']);
    if (x && x.ok) { const again = document.querySelector('form[data-form="cfg-add"] input'); if (again) again.value = ''; }
  }
  if (f === 'ads-probe') {
    const v = $('adsProbe').value.trim().toLowerCase();
    if (!DOMAIN.test(v)) { toast('Введите домен, например example.com'); return; }
    await adsControl({ op: 'enqueue', job: 'probe', domain: v }, 'Проверка поставлена в очередь - см. «Задания»');
  }
  if (f === 'ads-rule') {
    const v = $('adsRuleDomain').value.trim().toLowerCase();
    if (!DOMAIN.test(v)) { toast('Введите домен, например example.com'); return; }
    await adsControl({ op: $('adsRuleType').value, domain: v, scope: $('adsRuleScope').value }, 'Правило добавлено', 'ads-rule');
  }
});

/* ---------- Тема и обновление данных ---------- */
function applyTheme() {
  const r = document.documentElement;
  if (theme === 'system') r.removeAttribute('data-theme'); else r.setAttribute('data-theme', theme);
  $('themeBtn').innerHTML = ico(theme === 'light' ? 'sun' : theme === 'dark' ? 'moon' : 'auto');
  $('themeBtn').setAttribute('aria-label', 'Тема: ' + ({ system: 'как в системе', light: 'светлая', dark: 'тёмная' })[theme]);
}
let timer = null;
function restartTimer() {
  if (timer) clearInterval(timer);
  if (![15, 30, 60].includes(refreshSec)) refreshSec = 15;
  timer = setInterval(() => { if (!document.hidden && current !== 'logs') refreshPage(); load('status', true).then(renderNav); }, refreshSec * 1000);
}

$('backBtn').innerHTML = ico('back');
$('backBtn').addEventListener('click', () => go(parentOf(current) || 'overview'));
$('searchBtn').innerHTML = ico('search');
$('searchBtn').addEventListener('click', openSearch);
$('bellBtn').addEventListener('click', openNotes);
$('themeBtn').addEventListener('click', () => { theme = ({ system: 'light', light: 'dark', dark: 'system' })[theme] || 'system'; store.set('vward-theme', theme); applyTheme(); toast('Тема: ' + ({ system: 'как в системе', light: 'светлая', dark: 'тёмная' })[theme]); });
applyTheme();
render();
Promise.all(['status', 'security', 'update'].map(k => load(k))).then(() => { render(); refreshPage(); });
restartTimer();
})();
