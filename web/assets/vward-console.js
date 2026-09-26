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
const lastApplyNote = la => { if (!la) return ''; const n = la.changed_files, kb = Math.ceil((la.fetched_bytes || 0) / 1024); return 'последнее обновление: ' + (n ? 'заменено ' + n + ' ' + plural(n, 'файл', 'файла', 'файлов') + ', скачано ' + fmtKB(kb) : 'файлы не менялись'); };
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
  list: '<rect x="4.5" y="3.5" width="15" height="17" rx="2"/><path d="M8 8h8"/><path d="M8 12h8"/><path d="M8 16h5"/>',
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
  let r;
  try { r = await fetch(url, Object.assign({ cache: 'no-store', credentials: 'same-origin' }, options || {}, { signal: controller.signal })); }
  catch (e) { throw new Error(e.name === 'AbortError' ? 'роутер не ответил за 10 секунд' : 'нет связи с роутером'); }
  finally { clearTimeout(timer); }
  if (r.status === 401) { showLogin(); throw new Error('нужно войти'); }
  if (r.status === 403 && r.headers.get('Content-Type') && r.headers.get('Content-Type').includes('json')) {
    const x = await r.clone().json().catch(() => ({}));
    if (x.error === 'device_not_registered') { showDeviceBlocked(); throw new Error('устройство не зарегистрировано'); }
  }
  return r;
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
  not_upgradable: 'обновление уже не нужно - проверьте ещё раз', ext_update_busy: 'уже идёт проверка или установка',
  notes_unavailable: 'описание версии не найдено', invalid_version: 'неверная версия',
  smartdns_agh_failed: 'AdGuard Home не принял изменение строк Smart DNS', smartdns_agh_unavailable: 'модуль AdGuard Home не установлен', upstream_file_unsupported: 'upstream AdGuard Home заданы файлом - строки Smart DNS меняйте в нём вручную',
  this_device_not_registered: 'это устройство не зарегистрировано в Keenetic - вы потеряли бы доступ', devices_unavailable: 'список устройств Keenetic сейчас недоступен', device_not_registered: 'устройство не зарегистрировано в Keenetic', host_not_allowed: 'VWARD открыт по чужому имени - откройте его по IP-адресу роутера или добавьте имя в ALLOWED_HOSTS файла /opt/etc/vward/console/auth.conf',
  file_closed: 'файл закрыт: в нём ключи или пароли', not_found: 'не найдено', invalid_path: 'недопустимый путь', folder_missing: 'папки нет на роутере',
  not_a_file: 'это не файл', not_a_folder: 'это не папка', invalid_root: 'неизвестная папка',
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
  write_failed: 'не удалось записать файл', custom_manifest_url: 'адрес манифеста задан вручную - канал меняется в update.conf', invalid_tunnel: 'недопустимое имя туннеля', tunnel_no_handshake: 'сервер не ответил на рукопожатие за 30 секунд - туннель не изменён', main_tunnel: 'этот туннель используется VWARD для маршрутов', invalid_subnet: 'нужна подсеть IPv4, например 149.154.160.0/20 (не шире /8)', invalid_description: 'название: до 64 символов, без кавычек', no_free_tunnel: 'на роутере нет свободного номера туннеля',
  conf_empty: 'файл пустой', conf_syntax: 'это не файл WireGuard', conf_peer_count: 'в файле должен быть ровно один [Peer]', conf_key_private: 'неверный PrivateKey', conf_public_key: 'неверный PublicKey', conf_preshared_key: 'неверный PresharedKey', conf_address: 'нет адреса IPv4 в Address', conf_endpoint: 'неверный Endpoint (нужно сервер:порт)', conf_mtu: 'MTU вне 1280-1500', conf_keepalive: 'неверный PersistentKeepalive', conf_allowed_ips: 'неверный AllowedIPs', conf_awg: 'неверные параметры AmneziaWG', tunnel_device_missing: 'туннель не поднят на роутере', unknown_tunnel: 'туннель не найден или это не WireGuard',
  failopen_active: 'VPN недоступен и трафик идёт напрямую: дождитесь восстановления туннеля', policy_sync_busy: 'идёт обновление IP-категорий, повторите позже',
  unsupported_route: 'правило маршрута группы задано нестандартно: переключите туннель в веб-интерфейсе Keenetic',
  profile_verification_failed: 'профиль устройства не принял новый туннель, изменения отменены',
  rollback_incomplete: 'откат не завершён: проверьте маршруты групп в веб-интерфейсе Keenetic',
  temporary_file_unavailable: 'нет места для временного файла', component_disabled: 'компонент выключен: включите его в «Система → Компоненты»',
  core_component: 'базовый компонент нельзя выключить', wrong_credentials: 'неверный логин или пароль', invalid_mac: 'неверный MAC-адрес', invalid_backup: 'неверное имя копии', unknown_backup: 'копия не найдена', backup_damaged: 'копия повреждена', backup_failed: 'не удалось создать копию', restore_failed: 'не удалось восстановить', adguard_rejected: 'AdGuard Home не принял изменение', unknown_filter: 'такого списка нет в AdGuard Home', invalid_service: 'неизвестный сервис', invalid_setting: 'неизвестная настройка', invalid_name: 'недопустимое название', invalid_password: 'пароль: только латиница, цифры и обычные знаки, до 128 символов', too_many_attempts: 'слишком много попыток - подождите 5 минут',
  router_auth_unavailable: 'роутер не ответил на проверку пароля', invalid_login: 'недопустимый логин', auth_required: 'нужно войти', invalid_url: 'неверный адрес: нужен https без пробелов и логина', invalid_format: 'неизвестный формат списка',
  adguard_unavailable: 'AdGuard Home не ответил', adguard_not_configured: 'AdGuard Home не подключён: нет адреса в профиле роутера', adguard_auth_required: 'AdGuard Home требует логин и пароль — подключение не настроено', invalid_search: 'в поиске допустимы буквы, цифры, точки и дефисы', invalid_category: 'нет такой категории', invalid_component: 'нет такого компонента', registry_unavailable: 'реестр компонентов недоступен'
};
const errText = x => API_ERRORS[x && x.error] || (x && /^conf_rejected_/.test(x.error || '') ? 'роутер не принял настройку ' + x.error.slice(14).replace(/_/g, ' ') + ' - туннель не изменён' : '') || (x && x.error) || ('код ' + (x && x.rc));

/* ---------- Данные ---------- */
const S = { auth: null, cron: null, status: null, route: null, lists: null, update: null, security: null, diag: null, wifi: null, ads: null, https: null, config: null, adsstats: null, adspub: null, agh: null, ext: null, listd: null, backups: null, qlog: null, review: null, blocked: null, logs: {}, tprobe: {}, errors: {}, loadedAt: {} };
const ADSV = { filter: 'all', search: '', blockedSearch: '' };
// Files page: the open folder.
const FILES = { root: '', path: '' };
const LOADERS = {
  status: () => apiGet('status'), route: () => apiGet('route-data'), update: () => apiGet('update-data'), lists: () => apiGet('lists-data'),
  security: () => apiGet('security-data'), diag: () => apiGet('diagnostics'), wifi: () => apiGet('wifi-data'),
  ads: () => apiGet('ads-data'), https: () => apiGet('ads-https-data'), config: () => apiGet('config-data'),
  adsstats: () => apiGet('ads-view', { view: 'stats' }), agh: () => apiGet('ads-view', { view: 'agh' }), backups: () => apiGet('backup-data'), ext: () => apiGet('ext-update-data'),
  listd: () => current.startsWith('l-') ? apiGet('list-data', { name: current.slice(2) }) : Promise.resolve(null), files: () => FILES.root ? apiGet('files', { op: 'list', root: FILES.root, path: FILES.path }) : Promise.resolve(null), adspub: () => apiGet('ads-view', { view: 'publish-status' }),
  qlog: () => apiGet('ads-view', { view: 'querylog', filter: ADSV.filter, search: ADSV.search }),
  review: () => apiGet('ads-view', { view: 'list', kind: 'review' }),
  cron: () => apiGet('cron-data'), auth: () => apiGet('auth'),
  blocked: () => apiGet('ads-view', { view: 'list', kind: 'blocked', search: ADSV.blockedSearch })
};
// The last answers are kept in the browser: a reopened console shows them at once
// and refreshes from the router in the background.  Nothing secret is in them;
// a login prompt or «Выйти» drops them.
const CACHE_KEYS = ['status', 'route', 'lists', 'update', 'security', 'wifi', 'ads', 'config', 'adsstats', 'agh', 'backups', 'cron'];
const CACHE_TTL = 86400000, CACHE_MAX = 400000;
S.cached = {};
function cacheRead() {
  CACHE_KEYS.forEach(k => {
    const c = store.get('vward-cache-' + k, null);
    if (c && c.d && Date.now() - c.t < CACHE_TTL) { S[k] = c.d; S.cached[k] = c.t; }
  });
}
function cacheWrite(k) {
  if (!CACHE_KEYS.includes(k)) return;
  const v = JSON.stringify({ t: Date.now(), d: S[k] });
  if (v.length < CACHE_MAX) { try { localStorage.setItem('vward-cache-' + k, v); } catch (e) { /* хранилище браузера недоступно */ } }
}
function cacheDrop() { CACHE_KEYS.forEach(k => store.del('vward-cache-' + k)); S.cached = {}; }
const inflight = {};
async function load(key, force) {
  if (inflight[key]) return inflight[key];
  if (!force && S[key] && Date.now() - (S.loadedAt[key] || 0) < 5000) return S[key];
  inflight[key] = (async () => {
    try { S[key] = await LOADERS[key](); S.errors[key] = null; delete S.cached[key]; cacheWrite(key); }
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
  { id: 'overview', title: 'Обзор', icon: 'home', group: 'Главное', data: ['status', 'route', 'wifi', 'ads', 'lists'] },
  { id: 'logs', title: 'Журналы', icon: 'logs', group: 'Главное', data: [] },
  { id: 'wan', title: 'Интернет', icon: 'globe', group: 'Сеть', data: ['status', 'security', 'config'] },
  { id: 'vpn', title: 'VPN', icon: 'shield', group: 'Сеть', data: ['status', 'security', 'config'] },
  { id: 'lists', title: 'Доменные списки', icon: 'list', group: 'Сеть', data: ['lists', 'config'] },
  { id: 'routes', title: 'Маршрутизация', icon: 'route', group: 'Сеть', data: ['route', 'security', 'status', 'config'] },
  { id: 'wifi', title: 'Wi-Fi клиенты', icon: 'wifi', group: 'Сеть', data: ['wifi', 'security', 'config'] },
  { id: 'ads', title: 'Реклама и трекеры', icon: 'block', group: 'Сеть', data: ['ads', 'security', 'adsstats', 'adspub', 'agh'] },
  { id: 'system', title: 'Система', icon: 'platform', group: 'VWARD', data: ['status', 'diag', 'security', 'config'] },
  { id: 'updates', title: 'Обновления', icon: 'refresh', group: 'VWARD', data: ['status', 'update', 'ext', 'config'] },
  { id: 'settings', title: 'Настройки', icon: 'sliders', group: 'VWARD', data: ['security', 'auth', 'status', 'config', 'backups'] }
];
const SHORT = { overview: 'Обзор', logs: 'Журналы', wan: 'Интернет', vpn: 'VPN', lists: 'Списки', routes: 'Маршруты', wifi: 'Wi-Fi', ads: 'Реклама', system: 'Система', updates: 'Обновл.', settings: 'Настройки' };
const COMPONENTS = [
  { id: 'route-engine', name: 'Движок маршрутизации', desc: 'Отправляет выбранные домены через VPN и ведёт AdaptiveAuto.', when: 'постоянно, как служба', page: 'routes', log: 'adaptive' },
  { id: 'route-reconciler', name: 'Сверка маршрутов', desc: 'Каждые 5 минут сверяет маршруты роутера с каталогом и исправляет расхождения.', when: 'каждые 5 минут', page: 'routes', log: 'routing' },
  { id: 'route-tools', name: 'Инструменты маршрутов', desc: 'Проверка адресов и обновление подсказок каталога.', when: 'подсказки - раз в сутки', page: 'routes', log: 'routing' },
  { id: 'policy-sync', name: 'IP-категории', desc: 'Раз в сутки обновляет IP-категории и маршруты по ним.', when: 'раз в сутки, в 00:10', page: 'routes', log: 'policy' },
  { id: 'tunnel-guard', name: 'Защита VPN', desc: 'Следит за туннелем WireGuard и, если VPN упал, временно пускает трафик списков напрямую.', when: 'каждую минуту', page: 'vpn', log: 'tunnel' },
  { id: 'wan-guard', name: 'Восстановление интернета', desc: 'Проверяет интернет и поэтапно восстанавливает подключение.', when: 'каждую минуту', page: 'wan', log: 'wan' },
  { id: 'wifi-client-guard', name: 'Контроль Wi-Fi клиентов', desc: 'Наблюдает за переходами клиентов между 2.4 и 5 ГГц.', when: 'каждые 5 минут', page: 'wifi', log: 'wifi' },
  { id: 'ads-privacy-guard', name: 'Блокировка рекламы', desc: 'Управляет правилами AdGuard Home и источниками списков.', when: 'каждую минуту', page: 'ads', log: 'ads' },
  { id: 'runtime', name: 'Среда выполнения', desc: 'cron, supervisor и служебная очистка. На ней работают почти все компоненты.', when: 'постоянно', page: 'system', log: 'cron' },
  { id: 'console', name: 'Веб-интерфейс VWARD', desc: 'Эта страница управления и её API.', when: 'постоянно', page: 'settings', log: 'console' },
  { id: 'update-engine', name: 'Установщик обновлений', desc: 'Проверяет, устанавливает и откатывает подписанные обновления.', when: 'по настройкам обновлений', page: 'u-vward', log: 'updater' },
  { id: 'platform-core', name: 'Ядро платформы', desc: 'Версия, реестр компонентов и карта установки.', when: 'не запускается - это файлы версии и карты установки', page: 'system', log: 'console' }
];
const comp = id => COMPONENTS.find(c => c.id === id);
/* Граф компонентов приходит из реестра через API (config-data). */
const graphOf = id => ((cfg().components) || []).find(x => x.id === id);
const compOn = id => { const g = graphOf(id); return !g || g.enabled !== false; };
/* Что включится или выключится вместе с компонентом - как в vward-console-config.sh. */
function compCascade(id, off) {
  const g = cfg().components || [];
  let set = [id], grow = true;
  while (grow) {
    const add = off ? g.filter(x => x.requires_running.some(d => set.includes(d))).map(x => x.id)
      : g.filter(x => set.includes(x.id)).reduce((a, x) => a.concat(x.requires_running), []);
    const fresh = add.filter(x => !set.includes(x));
    grow = fresh.length > 0; set = set.concat(fresh);
  }
  return set.slice(1).filter(x => off ? compOn(x) : !compOn(x));
}
const compNames = ids => ids.map(x => '«' + ((comp(x) || {}).name || x) + '»').join(', ');
const LOG_TABS = [
  { id: 'wan', label: 'Интернет' }, { id: 'recovery', label: 'Восстановление' }, { id: 'tunnel', label: 'VPN' },
  { id: 'adaptive', label: 'AdaptiveAuto' }, { id: 'routing', label: 'Сверка маршрутов' }, { id: 'policy', label: 'IP-категории' }, { id: 'wifi', label: 'Wi-Fi' },
  { id: 'ads', label: 'Реклама' }, { id: 'updater', label: 'Обновления' }, { id: 'cron', label: 'Расписание' }, { id: 'console', label: 'Веб-интерфейс' }
];
const logLabel = id => (LOG_TABS.find(t => t.id === id) || {}).label || id;
const DETAILS = {
  'd-components': { title: 'Компоненты', parent: 'system' },
  'd-diag': { title: 'Диагностика', parent: 'system' },
  'd-files': { title: 'Файлы VWARD', parent: 'system', data: ['files'] },
  'd-cron': { title: 'Задания по расписанию', parent: 'd-diag' },
  'u-vward': { title: 'VWARD', parent: 'updates', data: ['status', 'update', 'config'] },
  'u-agh': { title: 'AdGuard Home', parent: 'updates', data: ['ext'] },
  'u-fw': { title: 'Прошивка Keenetic', parent: 'updates', data: ['ext'] },
  'u-opkg': { title: 'Пакеты Entware', parent: 'updates', data: ['ext'] },
  'd-notes': { title: 'Что нового', parent: 'u-vward', data: ['status', 'update'] },
  'd-mydomains': { title: 'Мои домены', parent: 'routes' },
  'd-force': { title: 'Всегда через VPN', parent: 'routes' },
  'd-dcats': { title: 'Категории доменов', parent: 'routes' },
  'd-adaptive': { title: 'AdaptiveAuto', parent: 'routes' },
  'd-smartdns': { title: 'Smart DNS', parent: 'lists', data: ['lists', 'config'] },
  'd-services': { title: 'Проверяемые сервисы', parent: 'routes' },
  'd-ipcats': { title: 'Активные IP-категории', parent: 'routes' },
  'd-querylog': { title: 'Журнал запросов', parent: 'ads' },
  'd-review': { title: 'На проверке', parent: 'ads' },
  'd-blocked': { title: 'Заблокировано', parent: 'ads' },
  'd-adcats': { title: 'Категории блокировки', parent: 'ads' },
  'd-rules': { title: 'Мои правила', parent: 'ads' },
  'd-sources': { title: 'Источники списков', parent: 'ads' },
  'd-jobs': { title: 'Задания', parent: 'ads' },
  'd-https': { title: 'HTTPS-фильтр', parent: 'ads' },
  'd-agh': { title: 'AdGuard Home', parent: 'ads', data: ['ads', 'agh'] },
  'd-aghfilters': { title: 'Фильтры AdGuard Home', parent: 'd-agh', data: ['agh', 'ads'] },
  'd-aghservices': { title: 'Блокировка сервисов', parent: 'd-agh', data: ['agh', 'ads'] }
};
COMPONENTS.forEach(c => { DETAILS['c-' + c.id] = { title: c.name, parent: 'd-components' }; DETAILS['deps-' + c.id] = { title: 'Зависимости', parent: 'c-' + c.id }; });
function page(id) {
  if (!id) return null;
  const p = PAGES.find(x => x.id === id);
  if (p) return p;
  if (DETAILS[id]) return Object.assign({ id: id }, DETAILS[id]);
  if (id.startsWith('t-')) return { id: id, title: id.slice(2), parent: 'vpn' };
  if (id.startsWith('l-')) { const l = ((S.lists && S.lists.lists) || []).find(x => x.name === id.slice(2)); return { id: id, title: l ? l.description || l.name : 'Список', parent: 'lists' }; }
  if (id.startsWith('w-')) return { id: id, title: typeof wifiName === 'function' ? wifiName(id.slice(2)) : id.slice(2), parent: 'wifi' };
  return null;
}
const parentOf = id => { const p = page(id); return p && p.parent; };
const navId = id => { let x = id; while (parentOf(x)) x = parentOf(x); return x; };
const DATA_FOR = id => { if (DETAILS[id] && DETAILS[id].data) return DETAILS[id].data; const p = PAGES.find(x => x.id === navId(id)); return p ? p.data : []; };

/* ---------- Состояние интерфейса ---------- */
const TAB_MAX = 4, TAB_DEFAULT = ['overview', 'wan', 'vpn', 'logs'];
let tabIds = store.get('vward-tabs', TAB_DEFAULT).filter(id => PAGES.some(p => p.id === id)).slice(0, TAB_MAX);
if (!tabIds.length) tabIds = TAB_DEFAULT.slice();
let theme = store.get('vward-theme', 'system'); if (!['system', 'time', 'light', 'dark'].includes(theme)) theme = 'system';
const REFRESH_SEC = 15;
const CARD_IDS = ['system', 'updates', 'wan', 'vpn', 'lists', 'routes', 'wifi', 'ads', 'runtime', 'storage'];
let cardOrder = store.get('vward-card-order', CARD_IDS).filter(id => CARD_IDS.includes(id));
CARD_IDS.forEach((id, i) => { if (!cardOrder.includes(id)) cardOrder.splice(Math.min(i, cardOrder.length), 0, id); });
let hiddenCards = store.get('vward-card-hidden', []).filter(id => CARD_IDS.includes(id));
let cardView = store.get('vward-card-view', 'grid'); if (!['grid', 'list'].includes(cardView)) cardView = 'grid';
let authForm = false, loginOpen = false;
let current = 'overview', editing = false, confirm = null, logTab = 'wan', logWrap = true, actionResult = null;

/* ---------- Построение блоков ---------- */
// The heading and its description sit above the card; the card holds only the content.
// A block's own status sits in its heading instead of a first row repeating the title.
const headPill = (cls, text) => '<span class="pill ' + (cls || '') + ' head-pill">' + esc(text) + '</span>';
function panel(title, body, opts) {
  opts = opts || {};
  const p = page(current), same = p && p.title === title, extra = opts.readonly || opts.right;
  const head = same && !extra ? '' : '<div class="block-head">' + (same ? '' : '<h2>' + esc(title) + '</h2>') + (opts.readonly ? '<span class="note">' + ico('lock') + 'Только чтение</span>' : '') + (opts.right || '') + '</div>';
  return '<section class="block"' + (same ? ' aria-label="' + esc(title) + '"' : '') + '>' + head + (opts.desc ? '<p class="block-desc">' + esc(opts.desc) + '</p>' : '') + (body ? '<div class="panel">' + body + '</div>' : '') + '</section>';
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
const sel = (attr, label, opts, value) => '<select class="input compact" ' + attr + ' aria-label="' + esc(label) + '">' + opts.map(o => '<option value="' + esc(o[0]) + '"' + (String(value) === String(o[0]) ? ' selected' : '') + (o[2] ? ' disabled' : '') + '>' + esc(o[1]) + '</option>').join('') + '</select>';
const btn = (act, icon, label, cls, extra) => '<button class="btn' + (cls ? ' ' + cls : '') + '" type="button" data-act="' + act + '"' + (extra || '') + '>' + (icon ? ico(icon) : '') + esc(label) + '</button>';
const empty = t => '<div class="empty">' + esc(t) + '</div>';
function confirmBox(id, text, yesLabel, danger) {
  if (!confirm || confirm.id !== id) return '';
  return '<div class="confirm' + (danger ? ' danger' : '') + '"><span>' + esc(text) + '</span><button class="btn small ' + (danger ? 'danger' : 'primary') + '" type="button" data-act="confirm-yes">' + esc(yesLabel) + '</button><button class="btn small" type="button" data-act="confirm-no">Отмена</button></div>';
}
function resultBox(id) {
  if (!actionResult || actionResult.id !== id) return '';
  // One short line: the details are in «Журналы».
  const t = String(actionResult.text || '').split('\n')[0].slice(0, 160);
  return t ? '<p class="result-note">' + esc(t) + '</p>' : '';
}
function loadError(keys) {
  const errs = keys.map(k => S.errors[k]).filter(Boolean);
  return errs.length ? '<p class="field-warn">Часть данных не получена: ' + esc(errs[0]) + '. Повторим автоматически.</p>' : '';
}

/* ---------- Обновления других программ ---------- */
const extVer = v => String(v || '—').replace(/^v(?=\d)/, '');
const autoText = on => on ? 'автоматически' : 'вручную';
// Keenetic's check stamp: "Sep 26 18:07:08", no year.
const fwStamp = t => { const m = /^([A-Z][a-z]{2}) +(\d{1,2}) (\d\d:\d\d)/.exec(String(t || '')); return m && MON[m[1]] ? ('0' + m[2]).slice(-2) + '.' + ('0' + MON[m[1]]).slice(-2) + ' ' + m[3] : (t || '—'); };
const fwChannel = c => ({ stable: 'Основной', preview: 'Предварительный', draft: 'Тестовый' })[c] || c;
const EXT_RESULT = { ok: 'установлено', rolled_back: 'не прошло проверку, возвращена прежняя версия', rollback_failed: 'ошибка возврата' };
function extHistory(hist, keep) {
  const h = (hist || []).filter(keep).slice(0, 5);
  return h.length ? panel('Последние установки', kv(h.map(r => [r.name + ' ' + extVer(r.to), EXT_RESULT[r.result] || r.result, r.result === 'ok' ? 'ok' : 'crit', null, '', fmtStamp(r.at) + ' · было ' + extVer(r.from)]))) : '';
}
function extRunNote(run, pkg) {
  if (!run || !run.running || runningId === 'ext') return '';
  if (pkg && run.label !== 'ext-upgrade-' + pkg) return '';
  return '<p class="result-note">Выполняется: ' + esc(run.label === 'ext-check' ? 'проверка' : 'установка') + '…</p>';
}
// While a check runs, its button says so: no separate progress line.
const extCheckBtn = label => btn('ext-check', 'refresh', runningId === 'ext' ? 'Проверяем…' : label, '', runningId === 'ext' ? ' disabled' : '');
const EXT_OK = { check: 'Проверка завершена', upgrade: 'Обновление установлено' };
function extOp(op, pkg, token) {
  return runLong('ext', 'ext-update-control', pkg ? { op: op, pkg: pkg, confirm: token } : { op: op }, 'ext-update-data', EXT_OK[op])
    .then(() => load('ext', true)).then(render);
}

/* ---------- Уведомления ---------- */
function notifications() {
  const n = [], s = S.status;
  if (S.errors.status) n.push({ sev: 'crit', title: 'Нет связи с роутером', text: S.errors.status, to: 'system' });
  const sdc = ((S.lists && S.lists.lists) || []).filter(l => l.smartdns_conflict);
  if (sdc.length) n.push({ sev: 'warn', title: 'Smart DNS уйдёт в VPN', text: 'Домены Smart DNS есть в списках через VPN: ' + sdc.map(l => l.description || l.name).join(', '), to: 'lists' });
  if (!s) return n;
  const w = s.wan || {}, wg = s.wg || {}, sv = s.services || {}, p = s.platform || {}, stg = s.storage || {};
  if (w.internet === false) n.push({ sev: 'crit', title: 'Нет интернета', text: 'VWARD восстанавливает подключение', to: 'wan' });
  const tunnels = wg.interfaces || [], down = tunnels.filter(t => !isTrue(t.connected));
  if (down.length) n.push({ sev: 'warn', title: down.length === tunnels.length ? 'VPN не в сети' : 'Не все туннели в сети', text: down.map(t => t.name + (t.description ? ' · ' + t.description : '')).join(', '), to: 'vpn' });
  if (isTrue(wg.failopen_active)) n.push({ sev: 'warn', title: 'VPN недоступен', text: 'Трафик списков VPN временно идёт напрямую', to: 'vpn' });
  if (sv.crond === false || sv.supervisor === false) n.push({ sev: 'crit', title: 'Задания по расписанию остановлены', text: 'cron или supervisor не запущен', to: 'd-cron' });
  const total = num(stg.total_kb), free = num(stg.free_kb);
  if (total && free != null && free / total < 0.1) n.push({ sev: 'warn', title: 'Мало места в хранилище', text: 'свободно ' + fmtKB(free), to: 'system' });
  if (['FAILED', 'RECOVERY_REQUIRED'].includes(p.phase)) n.push({ sev: 'crit', title: 'Обновление требует внимания', text: phaseText(p.phase), to: 'u-vward' });
  if (S.update && S.update.pending && S.update.pending.present) n.push({ sev: 'news', icon: 'save', title: 'Вышла новая версия VWARD', text: (S.update.pending.version || '') + ' - нажмите, чтобы посмотреть и установить', to: 'u-vward' });
  const wc = ((S.wifi && S.wifi.clients) || []).filter(c => c.health === 'WARNING').length;
  if (wc) n.push({ sev: 'warn', title: 'Wi-Fi: ' + wc + ' ' + plural(wc, 'клиент требует', 'клиента требуют', 'клиентов требуют') + ' внимания', text: 'частые переходы между 2.4 и 5 ГГц', to: 'wifi' });
  const offComps = ((S.config && S.config.components) || []).filter(x => x.enabled === false);
  if (offComps.length) n.push({ sev: 'warn', title: 'Выключено компонентов: ' + offComps.length, text: offComps.map(x => (comp(x.id) || {}).name || x.id).join(', '), to: 'd-components' });
  if (S.config && S.config.wan_guard && S.config.wan_guard.enabled === false) n.push({ sev: 'warn', title: 'Восстановление интернета выключено', text: 'при сбое интернет не восстановится автоматически', to: 'wan' });
  if (S.config && S.config.tunnel_guard && S.config.tunnel_guard.enabled === false) n.push({ sev: 'warn', title: 'Защита VPN выключена', text: 'при падении туннеля сайты из списков VPN будут недоступны', to: 'vpn' });
  if (S.ads && S.ads.paused) n.push({ sev: 'warn', title: 'Блокировка рекламы на паузе', text: 'реклама не блокируется', to: 'ads' });
  return n;
}
function plural(n, one, few, many) { const a = n % 10, b = n % 100; return a === 1 && b !== 11 ? one : a >= 2 && a <= 4 && (b < 12 || b > 14) ? few : many; }
function phaseText(p) { return ({ IDLE: 'Ожидание', CHECKING: 'Проверка', AVAILABLE: 'Доступно обновление', VERIFIED: 'Проверено', BACKING_UP: 'Резервная копия', INSTALLING: 'Установка', VERIFYING: 'Проверка установки', COMMIT_PREPARED: 'Завершение', COMMITTED: 'Установлено', ROLLING_BACK: 'Откат', FAILED: 'Ошибка', RECOVERY_REQUIRED: 'Нужно восстановление' })[p] || p || '—'; }

/* ---------- Карточки обзора ---------- */
const viaIs = (l, v) => l.via === v;
function cardData(id) {
  const s = st(), p = plat(), w = s.wan || {}, wg = s.wg || {}, sv = s.services || {}, g = s.storage || {}, r = S.route || {}, wf = S.wifi || {}, a = S.ads || {};
  const tunnels = wg.interfaces || [], up = tunnels.filter(t => isTrue(t.connected)).length;
  const comps = Object.keys(p.components || {}).length;
  const warnWifi = (wf.clients || []).filter(c => c.health === 'WARNING').length;
  switch (id) {
    case 'system': return { icon: 'platform', title: 'Система', to: 'system', value: p.version || '—', sub: comps ? comps + ' ' + plural(comps, 'компонент', 'компонента', 'компонентов') : 'версия VWARD', pill: p.version ? ['ok', 'Норма'] : ['', '—'] };
    case 'updates': return { icon: 'refresh', title: 'Обновления', to: 'updates', value: ['IDLE', 'COMMITTED', undefined, ''].includes(p.phase) ? 'Новых нет' : phaseText(p.phase), sub: '№ ' + (p.last_sequence || 0) + (p.active_slot ? ' · слот ' + p.active_slot : ''), pill: ['FAILED', 'RECOVERY_REQUIRED'].includes(p.phase) ? ['crit', 'Ошибка'] : ['', ''] };
    case 'wan': return { icon: 'globe', title: 'Интернет', to: 'wan', value: w.internet ? 'В сети' : s.wan ? 'Нет связи' : '—', sub: (w.address || 'адрес не получен') + (w.speed ? ' · ' + fmtSpeed(w.speed) : ''), pill: w.internet ? ['ok', 'Норма'] : s.wan ? ['crit', 'Сбой'] : ['', '—'] };
    case 'vpn': return { icon: 'shield', title: 'VPN', to: 'vpn', value: up + ' из ' + tunnels.length, sub: isTrue(wg.failopen_active) ? 'трафик идёт напрямую' : 'трафик идёт через VPN', pill: !tunnels.length ? ['', 'Нет туннелей'] : up === tunnels.length ? ['ok', 'Норма'] : ['warn', 'Внимание'] };
    case 'lists': {
      const ls = (S.lists && S.lists.lists) || [], vpn = ls.filter(l => viaIs(l, 'vpn')).length, around = ls.filter(l => viaIs(l, 'bypass')).length, auto = ls.filter(l => l.auto && viaIs(l, 'vpn')).length;
      return { icon: 'route', title: 'Доменные списки', to: 'lists', value: S.lists ? vpn + ' через VPN' : '—', sub: S.lists ? around + ' в обход VPN' : 'списки Keenetic', pill: !S.lists ? ['', '—'] : auto ? ['warn', 'Переведено авто: ' + auto] : ['info', ls.length + ' ' + plural(ls.length, 'список', 'списка', 'списков')] };
    }
    case 'routes': return { icon: 'route', title: 'Маршрутизация', to: 'routes', value: fmtInt(r.ip && r.ip.managed_routes) + ' ' + plural(num(r.ip && r.ip.managed_routes) || 0, 'маршрут', 'маршрута', 'маршрутов'), sub: fmtInt(r.domains && r.domains.unique) + ' доменов · ' + fmtInt(r.domains && r.domains.categories) + ' категорий', pill: S.route ? ['ok', 'Норма'] : ['', '—'] };
    case 'wifi': return { icon: 'wifi', title: 'Wi-Fi клиенты', to: 'wifi', value: fmtInt(wf.count) + ' ' + plural(num(wf.count) || 0, 'клиент', 'клиента', 'клиентов'), sub: wf.enabled ? (warnWifi ? warnWifi + ' требуют внимания' : 'без замечаний') : 'сбор данных выключен', pill: !S.wifi ? ['', '—'] : warnWifi ? ['warn', 'Внимание'] : wf.enabled ? ['ok', 'Норма'] : ['', 'Выключен'] };
    case 'ads': { const c = a.counts || {}; return { icon: 'block', title: 'Реклама', to: 'ads', value: fmtInt(c.blocked), sub: 'заблокировано доменов', pill: !S.ads ? ['', '—'] : a.paused ? ['warn', 'Пауза'] : ['ok', 'Норма'] }; }
    case 'runtime': return { icon: 'runtime', title: 'Среда выполнения', to: 'system', value: sv.crond && sv.supervisor ? 'Работает' : s.services ? 'Сбой' : '—', sub: !s.services ? 'планировщик и сторож заданий' : sv.crond && sv.supervisor ? 'планировщик и сторож заданий работают' : 'не работает: ' + [sv.crond ? '' : 'планировщик', sv.supervisor ? '' : 'сторож заданий'].filter(Boolean).join(' и '), pill: sv.crond && sv.supervisor ? ['ok', 'Норма'] : s.services ? ['crit', 'Сбой'] : ['', '—'] };
    case 'storage': { const t = num(g.total_kb), f = num(g.free_kb), used = t ? Math.round((t - f) / t * 100) : null; return { icon: 'storage', title: 'Хранилище', to: 'system', value: fmtKB(f), sub: 'свободно' + (t ? ' из ' + fmtKB(t) : '') + (g.filesystem ? ' · ' + g.filesystem : ''), pill: used == null ? ['', '—'] : used > 90 ? ['warn', used + ' %'] : ['ok', used + ' %'], meter: used }; }
  }
  return null;
}

// How a Keenetic domain list goes: through which tunnel, around VPN or nowhere.
function listPath(l) {
  const tuns = (st().wg && st().wg.interfaces) || [];
  return tuns.length > 1 && l.route && tuns.some(t => t.name === l.route) ? 'через ' + tunLabel(l.route) : viaIs(l, 'vpn') ? 'через VPN' : viaIs(l, 'bypass') ? 'в обход VPN' + (l.doh.length ? ', Smart DNS: ' + l.doh.join(', ') : '') : viaIs(l, 'none') ? 'без маршрута' : 'через ' + l.route;
}
let listWant = '';
// One Keenetic domain list: where it goes, its domains and exclusions, all editable here.
function listPage(name) {
  const l = ((S.lists && S.lists.lists) || []).find(x => x.name === name), d = S.listd, ok = cfgOk();
  const tuns = (st().wg && st().wg.interfaces) || [];
  if (!l) return loadError(['lists']) + panel('Список', empty(S.lists ? 'Такого списка нет в Keenetic' : 'Загрузка…'));
  if ((!d || d.name !== name) && listWant !== name) { listWant = name; load('listd', true).then(render); }
  const fresh = d && d.name === name, title = l.description || l.name, can = ok && (viaIs(l, 'vpn') || viaIs(l, 'bypass'));
  const rm = (act, v, label) => '<button class="icon-btn" type="button" data-list-dom="' + act + '" data-dom="' + esc(v) + '" aria-label="' + esc(label) + '" title="' + esc(label) + '"' + (ok ? '' : ' disabled') + '>' + ico('close') + '</button>';
  const addF = (kind, ph) => '<form class="inline-form" data-form="list-add" data-kind="' + kind + '"><input class="input" name="domain" placeholder="' + esc(ph) + '" aria-label="Домен" autocomplete="off"' + (ok ? '' : ' disabled') + '><button class="btn" type="submit"' + (ok ? '' : ' disabled') + '>Добавить</button></form>';
  const inc = fresh ? d.include : [], exc = fresh ? d.exclude : [];
  return cfgNote() + (fresh || !d || !d.error ? '' : '<p class="field-warn">' + esc(errText(d)) + '</p>') +
    panel(title, '<dl class="kv">' +
      (tuns.length > 1 ? ctrlRow('Куда идёт', listViaSel(l, tuns, ok)) : ctrlRow('В обход VPN', sw('data-list-bypass="' + esc(l.name) + '"', viaIs(l, 'bypass'), 'В обход VPN: ' + title, !can), viaIs(l, 'bypass') ? 'сейчас идёт через провайдера' : 'сейчас идёт через VPN')) +
      ctrlRow('Следить', sw('data-list-watch="' + esc(l.name) + '"', l.watch, 'Следить: ' + title, !ok), 'если в обход VPN сервис перестанет открываться, VWARD сам переведёт список на VPN') + '</dl>' +
      kv([['Адресов узнано', l.addresses != null ? fmtInt(l.addresses) : '—', '', null, '', 'IP-адреса, которые Keenetic получил для доменов списка']]) +
      (l.smartdns_conflict ? '<p class="field-warn">В списке есть домены Smart DNS: их общий адрес уйдёт в VPN, и Smart DNS перестанет работать для всех сервисов. Переведите список в обход VPN или уберите эти домены.</p>' : '') +
      (l.auto && viaIs(l, 'vpn') ? '<p class="field-warn">Переведён на VPN автоматически ' + esc(l.auto.at) + ': не открылся ' + esc(l.auto.host) + '</p>' : '')) +
    panel('Домены', addF('add', 'например, example.com') +
      (inc.length > 8 ? '<input class="input list-filter" data-list-filter placeholder="Найти в списке" aria-label="Найти домен в списке" autocomplete="off">' : '') +
      (!fresh ? empty('Загрузка…') : inc.length ? '<ul class="rows" data-list-rows>' + inc.map(v => '<li class="row" data-d="' + esc(v) + '"><div class="row-main"><b>' + dom(v) + '</b></div><span class="row-acts">' + rm('remove', v, 'Убрать ' + v + ' из списка') + '</span></li>').join('') + '</ul>' : empty('В списке нет доменов')),
      { desc: fmtInt(inc.length || l.count) + ' ' + plural(inc.length || l.count, 'домен', 'домена', 'доменов') + '. Домен действует вместе с поддоменами. Изменения сразу сохраняются в Keenetic.' }) +
    panel('Исключения', addF('exclude', 'поддомен, который не входит в список') +
      (!fresh ? '' : exc.length ? '<ul class="rows">' + exc.map(v => '<li class="row"><div class="row-main"><b>' + dom(v) + '</b></div><span class="row-acts">' + rm('unexclude', v, 'Убрать исключение ' + v) + '</span></li>').join('') + '</ul>' : empty('Исключений нет')),
      { desc: 'Поддомены, которые идут мимо этого списка, хотя их домен в нём есть.' });
}

// A card is marked only when something needs attention: «Норма» on every card said nothing.
const cardAlert = p => p && (p[0] === 'warn' || p[0] === 'crit') ? '<span class="pill card-alert ' + p[0] + '">' + ico('alert') + esc(p[1]) + '</span>' : '';

/* ---------- Разделы ---------- */
const RENDER = {
  overview() {
    const list = cardOrder.filter(id => editing || !hiddenCards.includes(id));
    const at = S.cached.status || S.loadedAt.status, ts = at ? new Date(at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : '—';
    // While cached data is shown the refresh icon spins; the text stays short so the bar never overflows.
    let html = '<div class="overview-bar"><span class="ob-time">' + (S.cached.status ? 'Данные на ' + ts + (S.errors.status ? ' · нет ответа роутера' : '') : 'Обновлено ' + ts) + '</span><button class="icon-btn' + (S.cached.status && !S.errors.status ? ' spinning' : '') + '" type="button" data-act="reload" aria-label="' + (S.cached.status ? 'Данные обновляются' : 'Обновить данные') + '">' + ico('refresh') + '</button><span class="spacer"></span>' +
      (editing ? btn('edit', 'check', 'Готово', 'small primary') : btn('edit', 'edit', 'Настроить', 'small')) + '</div>';
    if (editing) html += '<div class="edit-bar"><span>Вид</span><div class="segmented" role="group" aria-label="Вид карточек"><button type="button" data-view="grid" aria-pressed="' + (cardView === 'grid') + '">' + ico('platform') + 'Плитки</button><button type="button" data-view="list" aria-pressed="' + (cardView === 'list') + '">' + ico('logs') + 'Список</button></div><button class="link-btn" type="button" data-act="cards-reset">Сбросить</button></div>';
    html += '<div class="cards' + (editing ? ' editing' : '') + '" data-view="' + cardView + '">' + list.map((id, n) => {
      const c = cardData(id), h = hiddenCards.includes(id);
      return '<div class="card' + (h ? ' is-hidden' : '') + '"' + (editing ? '' : ' role="button" tabindex="0" data-go="' + c.to + '"') + '><div class="card-icon">' + ico(c.icon) + '</div>' + cardAlert(c.pill) + '<div class="card-title">' + esc(c.title) + '</div><div class="card-value num">' + esc(c.value) + '</div><div class="card-sub">' + esc(c.sub) + '</div>' +
        (c.meter != null ? '<div class="meter"><i data-width="' + c.meter + '"></i></div>' : '') +
        (editing ? '<div class="card-edit"><button class="icon-btn" type="button" data-card-move="' + id + ':up" aria-label="Выше"' + (n === 0 ? ' disabled' : '') + '>' + ico('up') + '</button><button class="icon-btn" type="button" data-card-move="' + id + ':down" aria-label="Ниже"' + (n === list.length - 1 ? ' disabled' : '') + '>' + ico('down') + '</button><button class="icon-btn" type="button" data-card-toggle="' + id + '" aria-label="' + (h ? 'Показать' : 'Скрыть') + ' карточку">' + ico(h ? 'eyeOff' : 'eye') + '</button></div>' : '') + '</div>';
    }).join('') + '</div>';
    return loadError(['status']) + html;
  },

  wan() {
    const w = st().wan || {}, pr = prof(), stage = num(w.recovery_stage) || 0, guardOn = !S.config || !cfg().wan_guard || cfg().wan_guard.enabled !== false;
    const STAGE = { 1: 'сбой замечен, проверяем ещё раз', 2: 'запрошен новый адрес у провайдера', 3: 'интернет переподключается' };
    const busy = runningId === 'wan';
    return loadError(['status']) +
      panel('Подключение', kv([
        ['Интерфейс', (pr.wan_interface || '—') + (pr.wan_device ? ' (' + pr.wan_device + ')' : '')],
        ['Кабель', isTrue(w.carrier) ? 'подключён' + (w.speed ? ' · ' + fmtSpeed(w.speed) : '') : 'нет сигнала'],
        ['IPv4', w.address || '—'],
        ['Шлюз', (w.gateway || '—') + (w.gateway ? (w.gateway_accessible ? ' · доступен' : ' · недоступен') : '')],
        ['DNS', w.dns_accessible ? 'отвечает' : 'не отвечает']
      ]), { right: st().wan && !w.internet ? headPill('crit', 'Нет связи') : '' }) +
      // One place: the automatic recovery switch and one button for «right now».
      panel('Восстановление интернета', '<dl class="kv">' +
        ctrlRow('Восстанавливать автоматически', sw('data-cfg-wg', guardOn, 'Восстанавливать интернет автоматически', !cfgOk()), guardOn ? '' : 'выключено: при сбое нажмите кнопку ниже') +
        (guardOn ? ctrlRow('Проверять', sel('data-cfg-wanp="CHECK_INTERVAL_MIN"' + (cfgOk() ? '' : ' disabled'), 'Как часто проверять интернет', [[1, 'раз в минуту'], [2, 'раз в 2 минуты'], [5, 'раз в 5 минут'], [10, 'раз в 10 минут'], [15, 'раз в 15 минут'], [30, 'раз в 30 минут']], ((cfg().wan_guard || {}).params || {}).CHECK_INTERVAL_MIN || 1), 'при сбое - каждую минуту, пока связь не вернётся') : '') + '</dl>' +
        confirmBox('wg-off', 'Выключить автоматическое восстановление? При сбое интернет придётся восстанавливать кнопкой.', 'Выключить', true) +
        (guardOn && stage ? '<p class="field-warn">Сейчас: ' + esc(STAGE[stage] || 'идёт восстановление') + '</p>' : '') +
        (confirmBox('wan-bounce', 'Переподключить интернет? Он пропадёт примерно на 10 секунд, домашняя сеть продолжит работать.', 'Переподключить') ||
          '<div class="panel-actions">' + btn('ask', 'refresh', busy ? 'Переподключаем…' : 'Переподключить интернет', '', ' data-confirm="wan-bounce"' + (busy ? ' disabled' : '')) + '</div>'),
        { desc: 'Если интернет от провайдера пропал, VWARD сам запросит новый адрес, а если не поможет - переподключит интернет. Кнопка переподключает сразу.' });
  },

  vpn() {
    const wg = st().wg || {}, list = wg.interfaces || [], managed = prof().tunnel_interface || '';
    const row = t => { const up = isTrue(t.connected); return '<li class="row link" role="button" tabindex="0" data-go="t-' + esc(t.name) + '"><div class="row-main"><b>' + esc(t.name) + (t.description ? ' · ' + esc(t.description) : '') + '</b><small>' + (t.name === managed ? '<span class="st ok">для маршрутов</span> · ' : '') + esc(t.handshake != null ? 'рукопожатие ' + agoText(num(t.handshake)) : (t.state || '')) + '</small></div><span class="pill ' + (up ? 'ok' : 'warn') + '">' + (up ? 'В сети' : 'Не в сети') + '</span>' + ico('chevron', 'chev') + '</li>'; };
    return loadError(['status']) +
      panel('Туннели', (list.length ? '<ul class="rows">' + list.map(row).join('') + '</ul>' : empty('Туннели WireGuard не найдены')) +
        '<div class="panel-actions">' + btn('tunnel-create', 'route', 'Создать туннель из файла .conf', '', cfgOk() ? '' : ' disabled') + '</div>' + resultBox('tunnels'),
        { desc: 'Туннели WireGuard найдены автоматически. Нажмите на туннель, чтобы открыть подробности, заменить его конфигурацию или направить через него списки и подсети.' }) +
      panel('Защита VPN', '<dl class="kv">' + ctrlRow('Автоматическая защита', sw('data-cfg-tg', !S.config || cfg().tunnel_guard.enabled !== false, 'Автоматическая защита VPN', !cfgOk())) + '</dl>' +
        confirmBox('tg-off', 'Выключить защиту VPN? Если туннель упадёт, сайты из списков VPN станут недоступны, пока он не восстановится.', 'Выключить', true) + kv([
        ['Трафик списков', isTrue(wg.failopen_active) ? 'Напрямую, пока VPN недоступен' : 'Через VPN', isTrue(wg.failopen_active) ? 'warn' : 'ok'],
        ['Проверка туннеля', 'каждую минуту', '', 'logs', ' data-log-go="tunnel"'],
        ['Попытка восстановления', 'каждые 5 минут', '', null, '', 'пока трафик идёт напрямую'],
        ['Потерь подряд', String(num(wg.down_streak) || 0)]
      ]) + '<div class="panel-actions even">' + btn('tunnel-health', 'check', 'Проверить') + btn('open-log', 'logs', 'Журнал', '', ' data-log-tab="tunnel"') + '</div>' + resultBox('tunnel-health'),
      { desc: 'Если туннель упал, трафик из списков VPN временно идёт напрямую, пока VPN не восстановится.' });
  },

  routes() {
    const r = S.route || {}, d = r.domains || {}, ip = r.ip || {}, ad = r.adaptive || {}, pr = prof();
    const tuns = (st().wg && st().wg.interfaces) || [], curT = pr.tunnel_interface || '';
    // One tunnel: the choice is shown but greyed out - there is nothing to switch to.
    const tunOpts = tuns.map(t => [t.name, tunLabel(t.name)]);
    if (curT && !tuns.some(t => t.name === curT)) tunOpts.unshift([curT, curT]);
    return loadError(['route']) +
      panel('Сводка', '<dl class="kv">' + ctrlRow('Туннель для маршрутов', sel('data-route-tunnel' + (tunOpts.length > 1 && cfgOk() ? '' : ' disabled'), 'Туннель для маршрутов', tunOpts.length ? tunOpts : [['', '—']], curT), tunOpts.length > 1 ? '' : 'другого туннеля нет') + '</dl>' +
        confirmBox('route-tunnel', 'Перевести маршруты VWARD' + (curT ? ' с ' + curT : '') + ' на ' + ((confirm && confirm.to) || '') + '? Мои домены, AdaptiveAuto и IP-категории пойдут через новый туннель.', 'Перевести') +
        kv([
        ['Доменов в каталоге', fmtInt(d.unique)],
        ['Категорий в каталоге', fmtInt(d.categories)],
        ['Маршрутов VWARD', fmtInt(ip.managed_routes), '', 'd-ipcats'],
        ['Группа маршрутизации', pr.policy_group || cfgRoute().group || '—']
      ])) +
      panel('Что идёт через VPN', kv([
        ['Мои домены', S.config ? (cfgRoute().router_available ? countText((cfgRoute().domains || []).length) : 'нет данных') : '—', '', 'd-mydomains'],
        ['Всегда через VPN', S.config ? countText((cfgRoute().force_vpn || []).length) : '—', '', 'd-force'],
        ['Категории доменов', S.config ? (cfgRoute().categories || []).filter(c => c.enabled).length + ' из ' + (cfgRoute().categories || []).length + ' включены' : '—', '', 'd-dcats'],
        ['AdaptiveAuto', S.config ? countText((cfgRoute().adaptive || []).length) : fmtInt(ad.count) + ' ' + plural(num(ad.count) || 0, 'домен', 'домена', 'доменов'), '', 'd-adaptive'],
        ['IP-категории', fmtInt(ip.active_count) + ' активны из ' + fmtInt(ip.categories), '', 'd-ipcats'],
        ['Проверяемые сервисы', fmtInt((r.services || []).length), '', 'd-services'],
        ['Источники каталога', 'itdog ' + fmtInt(d.sources && d.sources.itdog) + ' · v2fly ' + fmtInt(d.sources && d.sources.v2fly)]
      ])) +
      panel('Настройки маршрутизации', '<dl class="kv">' +
        ctrlRow('AdaptiveAuto', sw('data-cfg-rt="adaptive-mode"', cfgRoute().adaptive_enabled !== false, 'AdaptiveAuto', !cfgOk()), 'отправлять через VPN домены, недоступные напрямую') +
        ctrlRow('Автоопределение категории', sw('data-cfg-rt="classifier"', cfgRoute().classifier_enabled !== false, 'Автоопределение категории новых доменов', !cfgOk()), 'новые домены попадают в подходящую категорию') +
        '</dl>', { desc: 'Выключение AdaptiveAuto не убирает уже добавленные домены - только перестаёт добавлять новые.' }) +
      panel('Проверить адрес', '<form class="inline-form" data-form="probe"><input class="input" id="probeInput" placeholder="домен или IPv4, например claude.ai" aria-label="Домен или IPv4" autocomplete="off"><button class="btn primary" type="submit">' + ico('search') + 'Проверить</button></form><div id="probeResult"></div>', { desc: 'Покажет, через какой интерфейс пойдёт трафик.' }) +
      panel('Обслуживание', kv([
        ['Решения AdaptiveAuto', 'журнал проверок доменов', '', 'logs', ' data-log-go="adaptive"'],
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
        ['Последний сбор', sc.last ? fmtStamp(sc.last) + (num(sc.rc) === 0 ? ' · успешно' : ' · код ' + sc.rc) : '—', '', 'logs', ' data-log-go="wifi"']
      ])) +
      panel('Клиенты', clients.length ? '<ul class="rows">' + clients.map(c => '<li class="row link" role="button" tabindex="0" data-go="w-' + esc(c.mac) + '"><div class="row-main"><b' + (c.host && (c.host.name || c.host.hostname) ? '' : ' class="mono"') + '>' + esc(wifiName(c.mac)) + '</b><small>' + esc(bandText(c.band)) + (c.host && c.host.ip ? ' · ' + esc(c.host.ip) : '') + (c.host && c.host.access === 'deny' ? ' · интернет запрещён' : '') + ' · ' + fmtInt(c.switches) + ' ' + plural(num(c.switches) || 0, 'переход', 'перехода', 'переходов') + (num(c.weak_5g) ? ' · слабый 5 ГГц ' + c.weak_5g + ' раз' : '') + (c.min_5g_rssi && c.min_5g_rssi !== '-' ? ' · мин. ' + esc(c.min_5g_rssi) + ' дБм' : '') + '</small></div><span class="pill ' + (c.health === 'WARNING' ? 'warn' : 'ok') + '">' + esc(recText(c)) + '</span>' + ico('chevron', 'chev') + '</li>').join('') + '</ul>' : empty(w.enabled ? 'Клиентов пока нет' : 'Сбор данных выключен'), { desc: 'Рекомендации не применяются автоматически.' }) +
      panel('Когда предупреждать', '<dl class="kv">' +
        ctrlRow('Окно анализа', sel('data-cfg-wifi="WINDOW_SEC"', 'Окно анализа', withCur([[21600, '6 часов'], [43200, '12 часов'], [86400, '24 часа'], [172800, '2 суток'], [604800, '7 суток']], wc.WINDOW_SEC, ' с'), wc.WINDOW_SEC), 'за какой период считать переходы') +
        ctrlRow('Переходов между диапазонами', sel('data-cfg-wifi="BAND_SWITCH_WARN"', 'Переходов между диапазонами', withCur([[5, 'от 5'], [10, 'от 10'], [20, 'от 20'], [30, 'от 30'], [50, 'от 50']], wc.BAND_SWITCH_WARN, ''), wc.BAND_SWITCH_WARN)) +
        ctrlRow('Слабый сигнал 5 ГГц', sel('data-cfg-wifi="WEAK_5G_RSSI"', 'Слабый сигнал 5 ГГц', withCur([[-65, '-65 дБм'], [-70, '-70 дБм'], [-75, '-75 дБм'], [-80, '-80 дБм'], [-85, '-85 дБм']], wc.WEAK_5G_RSSI, ' дБм'), wc.WEAK_5G_RSSI), 'и ниже') +
        ctrlRow('Слабых замеров', sel('data-cfg-wifi="WEAK_5G_SAMPLE_WARN"', 'Слабых замеров', withCur([[3, 'от 3'], [5, 'от 5'], [10, 'от 10'], [20, 'от 20']], wc.WEAK_5G_SAMPLE_WARN, ''), wc.WEAK_5G_SAMPLE_WARN), 'за окно анализа') +
        '</dl>', { desc: 'Клиент получает предупреждение, когда часто переключается между диапазонами и при этом слабо ловит 5 ГГц.' });
  },

  ads() {
    const a = S.ads || {}, c = a.counts || {}, s = a.settings || {}, j = a.jobs || {}, sc = a.scan || {}, ag = (S.security && S.security.external_services && S.security.external_services.adguard) || {};
    const aghHost = ag.address || location.hostname, aghUrl = ag.port ? 'http://' + aghHost + ':' + ag.port + '/' : '';
    const runMode = s.RUN_MODE || 'scheduled', st1 = S.adsstats, pub = S.adspub || {}, g = S.agh;
    const pending = (num(pub.added) || 0) + (num(pub.removed) || 0);
    const cur = j.current || {}, busy = cur.state && cur.state !== 'IDLE';
    const now = !S.ads ? ['', 'загрузка…'] : a.paused ? ['warn', 'На паузе'] : !a.agh_connected ? ['warn', 'Нет подключения к AdGuard Home', 'd-agh'] :
      busy ? ['info', cur.type === 'scan' ? 'Проверяет новые домены' : 'Выполняет задание', 'd-jobs'] : num(j.queued) ? ['info', fmtInt(j.queued) + ' в очереди', 'd-jobs'] :
      ['ok', ({ scheduled: 'Ждёт следующей проверки', dynamic: 'Проверяет новые домены сразу', manual: 'Проверка только по кнопке' })[runMode] || 'Работает'];
    const where = !pub.ok ? '—' : pub.mode === 'staged' ? 'не отправляются' : isTrue(s.AUTO_PUBLISH) ? 'автоматически' : 'после подтверждения';
    const recent = a.recent || [];
    return loadError(['ads']) +
      panel('Проверка VWARD', '<dl class="kv">' + ctrlRow('Проверка рекламы и трекеров', sw('data-ads-pause', !a.paused, 'Проверка рекламы и трекеров', !S.ads), a.paused ? 'на паузе - новые домены не проверяются' : '') + '</dl>' +
        kv([['Сейчас', now[1], now[0], now[2]],
          ['Последняя проверка', sc.last_run ? fmtStamp(String(sc.last_run).replace(' ', 'T')) : 'ещё не было', '', 'd-jobs'],
          sc.last_run ? ['Просмотрено', fmtInt(sc.unique_allowed) + ' ' + plural(num(sc.unique_allowed) || 0, 'домен', 'домена', 'доменов'), '', 'd-querylog', '', 'из ' + fmtInt(sc.allowed_records) + ' ' + plural(num(sc.allowed_records) || 0, 'запроса', 'запросов', 'запросов')] : null,
          sc.last_run ? ['Новых на проверку', fmtInt(sc.candidates)] : null,
          ['Заблокировано', fmtInt(c.blocked), '', 'd-blocked'],
          ['На проверке', fmtInt(c.review), num(c.review) ? 'warn' : '', 'd-review'],
          ['Разрешено', fmtInt(num(c.allow) != null ? num(c.allow) + (num(c.trust) || 0) : null)],
          ['Правила в AdGuard Home', where, '', null, '', pub.ok && pub.mode === 'staged' ? 'VWARD их собирает, но пока не применяет' : '']]) +
        '<div class="panel-actions">' + btn('ads-job', 'search', 'Проверить сейчас', 'primary', ' data-job="scan"') + '</div>' + resultBox('ads-job'),
        { desc: 'VWARD берёт домены, которые AdGuard Home пропустил, сверяет их с источниками и блокирует найденную рекламу и трекеры.' }) +
      panel('Последние решения', !S.ads ? empty('Загрузка…') : recent.length ? '<ul class="rows">' + recent.map(r => {
        const v = ADS_VERDICT[r.verdict] || ['', r.verdict];
        return '<li class="row"><div class="row-main"><b>' + esc(r.domain) + '</b><small>' + esc(ADS_REASON[r.reason] || r.reason || '') + (r.first_seen ? ' · замечен ' + esc(fmtTime(r.first_seen)) : '') + '</small></div><span class="pill ' + v[0] + '">' + esc(v[1]) + '</span>' +
          adsRuleBtn(r.domain, r.action === 'BLOCK' ? 'allow' : 'block') + '</li>';
      }).join('') + '</ul>' : empty('Проверок ещё не было'), { desc: 'Новые домены и что VWARD с ними сделал.' }) +
      panel('Публикация в AdGuard Home', kv([['Не опубликовано', !pub.ok ? '—' : pending ? pending + ' ' + plural(pending, 'изменение', 'изменения', 'изменений') : 'всё опубликовано', pending ? 'warn' : 'ok', null, '', pub.ok && pub.mode === 'staged' ? 'режим подготовки: правила собираются, но не отправляются' : '']]) +
        '<dl class="kv">' + ctrlRow('Публиковать автоматически', sw('data-ads-autopub', isTrue(s.AUTO_PUBLISH), 'Публиковать автоматически', !S.ads), 'новые правила уходят в AdGuard Home без подтверждения') + '</dl>' +
        (confirmBox('ads-autopub', 'Публиковать правила автоматически? Новые правила будут применяться в AdGuard Home без вашего подтверждения.', 'Включить') ||
         confirmBox('ads-publish', 'Отправить правила в AdGuard Home? Они применятся сразу.', 'Опубликовать') || '<div class="panel-actions">' + btn('ask', 'check', 'Опубликовать правила', 'primary', ' data-confirm="ads-publish"') + '</div>')) +
      panel('Проверить домен', '<form class="inline-form" data-form="ads-probe"><input class="input" id="adsProbe" placeholder="например, mc.yandex.ru" aria-label="Домен" autocomplete="off"' + (PROBE ? ' value="' + esc(PROBE.domain) + '"' : '') + '><button class="btn primary" type="submit"' + (PROBE && !PROBE.done ? ' disabled' : '') + '>' + ico('search') + 'Проверить</button></form>' + probeResult(), { desc: 'Что VWARD знает о домене: решение, источники, запросы в журнале AdGuard Home.' }) +
      panel('Списки и правила', kv([
        ['Журнал запросов', 'последние 100', '', 'd-querylog'],
        ['Категории блокировки', (a.categories || []).filter(x => x.active).length + ' из ' + (a.categories || []).length + ' включены', '', 'd-adcats'],
        ['Мои правила', fmtInt((a.manual_rules || []).length), '', 'd-rules'],
        ['Источники', (a.sources || []).filter(x => x.mode === 'active').length + ' из ' + (a.sources || []).length + ' активны', '', 'd-sources'],
        ['Задания', busy ? 'выполняется' : (num(j.queued) ? j.queued + ' в очереди' : 'нет активных'), '', 'd-jobs'],
        ['HTTPS-фильтр', S.https && S.https.ok ? (S.https.status && isTrue(S.https.status.ENABLED) ? 'Включён' : 'Выключен') : 'недоступен', '', 'd-https']
      ])) +
      panel('Настройки проверки', '<dl class="kv">' +
        ctrlRow('Режим работы', sel('data-ads-set="RUN_MODE"', 'Режим работы', [['scheduled', 'По расписанию'], ['dynamic', 'По запросам'], ['manual', 'Вручную']], runMode), ({ scheduled: 'новые домены проверяются пачкой раз в интервал', dynamic: 'каждый новый домен проверяется сразу', manual: 'проверка только по кнопке' })[runMode]) +
        (runMode === 'scheduled' ? ctrlRow('Интервал', sel('data-ads-set="SCHEDULE_INTERVAL_MIN"', 'Интервал', [['5', '5 минут'], ['10', '10 минут'], ['30', '30 минут'], ['60', '1 час']], s.SCHEDULE_INTERVAL_MIN || '10')) : '') +
        ctrlRow('Обновлять источники автоматически', sw('data-ads-set="AUTO_SOURCE_UPDATE"', isTrue(s.AUTO_SOURCE_UPDATE), 'Обновлять источники автоматически', !S.ads), 'раз в ' + (s.SOURCE_UPDATE_INTERVAL_HOURS || 24) + ' ч') +
        ctrlRow('Новые правила применять к', sel('data-ads-set="AUTO_RULE_SCOPE"', 'Новые правила', [['exact', 'Только домену'], ['suffix', 'Домену и поддоменам']], s.AUTO_RULE_SCOPE || 'exact')) +
        '</dl>' + resultBox('ads')) +
      panel('AdGuard Home', kv([aghUrl ? ['Адрес', aghHost + ':' + ag.port, '', aghUrl] : ['Адрес', 'не настроен'],
          S.ads ? ['Подключение VWARD', a.agh_connected ? 'Подключено' : 'Не подключено', a.agh_connected ? 'ok' : 'warn', 'd-agh'] : null,
          g && g.ok && g.protection != null ? ['Защита', g.protection ? 'Включена' : 'Выключена', g.protection ? 'ok' : 'warn', 'd-agh'] : null,
          st1 && st1.ok ? ['Запросов за сутки', fmtInt(st1.queries), '', 'd-querylog'] : null,
          st1 && st1.ok ? ['Заблокировано за сутки', fmtInt(st1.blocked) + (st1.queries ? ' · ' + Math.round(100 * st1.blocked / st1.queries) + '%' : ''), '', 'd-querylog', ' data-qfilter="blocked"'] : null,
          ['Настройки AdGuard Home', 'фильтры, сервисы, защита', '', 'd-agh']]),
        { desc: 'Первая линия: блокирует по своим фильтрам. VWARD проверяет то, что он пропустил.' });
  },
  'd-agh'() {
    const a = S.ads || {};
    return loadError(['ads']) + aghConnectPanel(a) + aghSettingsPanel(a);
  },

  system() {
    const s = st(), r = s.router || {}, p = plat(), g = s.storage || {}, dg = S.diag && S.diag.checks || [];
    const bad = dg.filter(x => x.status !== 'PASS').length;
    return loadError(['status']) +
      panel('Устройство', kv([
        ['Модель', r.model || '—'], ['KeeneticOS', r.version || '—'],
        ['Веб-интерфейс Keenetic', prof().lan_address || location.hostname, '', 'http://' + (prof().lan_address || location.hostname) + '/'],
        ['Версия VWARD', p.version || '—', '', 'u-vward'], ['Время работы', fmtUptime(r.uptime_sec)]
      ])) +
      panel('Состояние', kv([
        ['Компоненты', COMPONENTS.length + ' ' + plural(COMPONENTS.length, 'компонент', 'компонента', 'компонентов'), '', 'd-components'],
        ['Диагностика', dg.length ? (dg.length - bad) + ' из ' + dg.length + ' в норме' : 'не запускалась', bad ? 'warn' : '', 'd-diag'],
        ['Файлы', 'просмотр', '', 'd-files']
      ])) +
      panel('Хранилище', kv([['Свободно', fmtKB(g.free_kb) + ' из ' + fmtKB(g.total_kb)], ['Файловая система', g.filesystem || '—'], ['Сжатие журналов', 'каждый час', '', 'd-cron']]) +
        '<div class="panel-actions">' + btn('housekeeping', 'archive', 'Сжать журналы сейчас') + '</div>' + resultBox('storage'),
        { desc: 'Журналы больше лимита сжимаются, хранятся две предыдущие копии.' });
  },

  updates() {
    const p = plat(), u = S.update || {}, pend = u.pending || {}, x = S.ext || {}, fw = x.firmware || {}, agh = x.agh || {};
    const pk = x.packages || [], checked = x.checked_at ? fmtStamp(x.checked_at) : '';
    const vwardVal = pend.present ? 'доступна ' + (pend.version || 'новая версия') : (p.version || '—');
    const aghVal = agh.available ? 'доступна ' + extVer(agh.available) : agh.installed ? extVer(agh.installed) : S.ext ? 'не установлен' : '—';
    const fwVal = !x.firmware ? (S.ext ? 'нет данных' : '—') : fw.update_available ? 'доступна новая' : fw.title || fw.release;
    return loadError(['update', 'ext']) +
      panel('Обновления', kv([
        ['VWARD', vwardVal, pend.present ? 'info' : '', 'u-vward', '', pend.present ? 'установлена ' + (p.version || '—') : autoText(isTrue(p.auto_apply))],
        ['AdGuard Home', aghVal, agh.available ? 'info' : '', 'u-agh', '', agh.available ? 'установлена ' + extVer(agh.installed) : autoText(x.auto && x.auto.agh)],
        ['Прошивка Keenetic', fwVal, fw.update_available ? 'info' : '', 'u-fw', '', fw.channel ? 'канал ' + fwChannel(fw.channel) + ' · ' + autoText(fw.auto_update) : ''],
        ['Пакеты Entware', pk.length ? pk.length + ' ' + plural(pk.length, 'обновление', 'обновления', 'обновлений') : S.ext && !x.checked_at ? 'не проверялись' : 'актуальны', pk.length ? 'info' : '', 'u-opkg', '', x.installed_count ? 'установлено ' + x.installed_count + ' · ' + autoText(x.auto && x.auto.entware) : '']
      ]) + '<div class="panel-actions">' + extCheckBtn('Проверить всё') + '</div>' + resultBox('ext'),
      { desc: checked ? 'Последняя проверка: ' + checked + '. Проверка идёт сама раз в сутки, во время установки обновлений VWARD.' : 'Проверка идёт сама раз в сутки, во время установки обновлений VWARD.' });
  },

  'u-agh'() {
    const x = S.ext || {}, a = x.agh || {}, run = x.run || {};
    const conf = confirmBox('ext-upgrade', 'Обновить AdGuard Home до ' + extVer(a.available) + '? DNS прервётся на несколько секунд. Перед установкой сохранится копия, при сбое вернётся прежняя версия.', 'Обновить');
    return loadError(['ext']) +
      panel('AdGuard Home', kv([
        ['Установлена', a.installed ? extVer(a.installed) : 'не установлен'],
        ['Доступна', a.available ? extVer(a.available) : 'новее нет', a.available ? 'info' : ''],
        ['Обновляется через', 'opkg']
      ]) + (conf || (a.available ? '<div class="panel-actions">' + btn('ask', 'save', 'Обновить', 'primary', ' data-confirm="ext-upgrade" data-pkg="adguardhome-go"') + '</div>' : '')) + extRunNote(run, 'adguardhome-go') + resultBox('ext'), { desc: 'AdGuard Home установлен пакетом Entware adguardhome-go, поэтому его обновляет opkg, а не он сам.' }) +
      panel('Настройки', '<dl class="kv">' + ctrlRow('Обновлять автоматически', sw('data-ext-auto="agh"', x.auto && x.auto.agh, 'Обновлять AdGuard Home автоматически'), 'раз в сутки, во время установки обновлений VWARD') + '</dl>') +
      extHistory(x.history, h => h.name === 'adguardhome-go');
  },

  'u-fw'() {
    const x = S.ext || {}, f = x.firmware;
    if (!f) return loadError(['ext']) + panel('Прошивка Keenetic', empty(S.ext ? 'Роутер не сообщил данные о прошивке. Нажмите «Проверить всё» в разделе «Обновления».' : 'Загрузка…'));
    const chans = (f.channels || []).filter(c => ['stable', 'preview', 'draft'].includes(c.name));
    const cur = (f.channels || []).find(c => c.name === f.channel) || {};
    return loadError(['ext']) +
      panel('Прошивка Keenetic', kv([
        ['Установлена', (f.title || '') + (f.release ? ' (' + f.release + ')' : '')],
        ['Доступна', f.update_available == null ? 'роутер пока не сообщил' : f.update_available ? (cur.version || 'новая версия') : 'новее нет', f.update_available ? 'info' : ''],
        ['Проверена роутером', fwStamp(f.checked)]
      ]), { desc: f.update_available ? 'Прошивку устанавливает сам Keenetic: в его веб-интерфейсе или автоматически. Во время установки роутер перезагрузится.' : '' }) +
      panel('Настройки', '<dl class="kv">' +
        ctrlRow('Обновлять автоматически', sw('data-fw-auto', f.auto_update, 'Обновлять прошивку автоматически'), 'Keenetic сам установит новую версию канала, роутер перезагрузится') +
        ctrlRow('Канал обновлений', sel('data-fw-channel', 'Канал обновлений', chans.map(c => [c.name, fwChannel(c.name)]), f.channel), (f.channel === 'stable' ? 'проверенные версии' : 'тестовые версии, возможны ошибки') + (cur.version ? ' · ' + cur.version : '')) +
        '</dl>' + confirmBox('fw-channel', 'Перейти на тестовый канал? Тестовые прошивки могут работать с ошибками.', 'Перейти', true),
        { desc: 'Это те же настройки, что в веб-интерфейсе Keenetic.' });
  },

  'u-opkg'() {
    const x = S.ext || {}, pk = x.packages || [], run = x.run || {};
    const c = confirm && confirm.id === 'ext-upgrade' ? pk.find(p => p.name === confirm.pkg) : null;
    const rows = pk.map(p => '<div class="kv-row" data-key="' + esc(p.name) + '"><dt>' + esc(p.name) + '<span class="hint">' + esc(extVer(p.installed) + ' → ' + extVer(p.available)) + (p.critical ? ' · системный пакет' : '') + '</span></dt><dd>' +
      btn('ask', 'save', 'Обновить', 'small', ' data-confirm="ext-upgrade" data-pkg="' + esc(p.name) + '"') + '</dd></div>').join('');
    return loadError(['ext']) +
      panel('Пакеты Entware', pk.length ? '<dl class="kv">' + rows + '</dl>' +
        (c ? confirmBox('ext-upgrade', (c.critical ? 'Системный пакет: если он сломается, может пропасть SSH или командная строка. ' : '') + 'Обновить ' + c.name + ' до ' + extVer(c.available) + '? Перед установкой сохранится копия, при сбое вернётся прежняя версия.', 'Обновить', c.critical) : '') +
        extRunNote(run) + resultBox('ext') :
        empty(x.checked_at ? (x.feed_ok === false ? 'Список пакетов Entware не скачался. Повторите проверку позже.' : 'Все пакеты актуальны.') : 'Пакеты ещё не проверялись.') + '<div class="panel-actions">' + extCheckBtn('Проверить') + '</div>' + resultBox('ext'),
        { desc: 'Программы Entware, на которых работают VWARD и AdGuard Home: cron, curl, jq, веб-сервер, SSH и другие.' }) +
      panel('Настройки', '<dl class="kv">' + ctrlRow('Обновлять автоматически', sw('data-ext-auto="entware"', x.auto && x.auto.entware, 'Обновлять пакеты Entware автоматически'), 'кроме системных пакетов: их - только вручную') + '</dl>') +
      extHistory(x.history, h => h.name !== 'adguardhome-go');
  },

  'u-vward'() {
    const p = plat(), u = S.update || {}, al = u.allowed || {}, pend = u.pending || {};
    const uc = cfg().update || {}, mode = updModeShown || (!isTrue(p.auto_apply) ? 'manual' : uc.apply_window === 'any' ? 'auto' : 'schedule'), feed = uc.feed;
    const winStart = uc.safe_window_start || String(p.safe_window || '').split(/\s*[-–]\s*/)[0];
    const interval = uc.check_interval_seconds || p.check_interval_seconds;
    const acts = [];
    if (al.check || runningId === 'updates') acts.push(btn('update-op', 'refresh', runningId === 'updates' ? 'Проверяем…' : 'Проверить', 'primary', ' data-op="check"' + (runningId === 'updates' ? ' disabled' : '')));
    if (al.apply) acts.push(btn('ask', 'save', 'Установить', 'primary', ' data-confirm="update-apply"'));
    if (al.retry) acts.push(btn('ask', 'refresh', 'Повторить', '', ' data-confirm="update-retry"'));
    if (al.rollback) acts.push(btn('ask', 'undo', 'Откатить', 'danger', ' data-confirm="update-rollback"'));
    if (al.recover) acts.push(btn('ask', 'alert', 'Восстановить', 'danger', ' data-confirm="update-recover"'));
    const conf = confirmBox('update-apply', 'Установить обновление ' + (pend.version || '') + '? Компоненты перезапустятся.', 'Установить') ||
      confirmBox('update-retry', 'Повторить установку обновления?', 'Повторить') ||
      confirmBox('update-rollback', 'Вернуть предыдущую версию? Компоненты перезапустятся.', 'Откатить', true) ||
      confirmBox('update-recover', 'Восстановить прерванное обновление?', 'Восстановить', true);
    return loadError(['update', 'status']) +
      panel('Состояние', kv([
        ['Версия', p.version || '—', '', 'd-notes', '', 'сборка № ' + (p.last_sequence || 0) + ' · что нового'],
        pend.present ? ['Доступно', (pend.version || '') + (pend.priority ? ' · ' + ({ ROUTINE: 'обычное', IMPORTANT: 'важное', CRITICAL: 'критическое' }[String(pend.priority).toUpperCase()] || pend.priority) : ''), 'info', 'd-notes'] : null,
        ['Последняя проверка', fmtStamp(p.last_health_check) || '—', '', 'logs', ' data-log-go="updater"'],
        u.engine ? ['Движок обновлений', u.engine.version === '1' ? '1.x' : u.engine.version, '', null, '', lastApplyNote(u.last_apply)] : null
      ]) + (conf || (acts.length ? '<div class="panel-actions even">' + acts.join('') + '</div>' : '')) + resultBox('updates'),
      { right: ['FAILED', 'RECOVERY_REQUIRED'].includes(u.phase || p.phase) ? headPill('crit', phaseText(u.phase || p.phase)) : '' }) +
      panel('Настройки обновлений', '<dl class="kv">' +
        ctrlRow('Установка обновлений', sel('data-upd="mode"', 'Установка обновлений', [['auto', 'Автоматическая'], ['schedule', 'По расписанию'], ['manual', 'Ручная']], mode), ({ auto: 'сразу после проверки подписи', schedule: 'в ' + (winStart || '03:00') + ', критические исправления - сразу', manual: 'только проверка и уведомление' })[mode]) +
        (mode === 'schedule' ? ctrlRow('Время установки', sel('data-cfg-upd="install_time"', 'Время установки', withCur(HOURS, winStart, ''), winStart), 'обновление ставится при первой проверке после этого времени') : '') +
        ctrlRow('Интервал проверки', sel('data-cfg-upd="check_interval_seconds"', 'Интервал проверки', withCur([[900, '15 минут'], [1800, '30 минут'], [3600, '1 час'], [10800, '3 часа'], [21600, '6 часов'], [43200, '12 часов'], [86400, '24 часа']], interval, ' с'), interval)) +
        (feed === 'beta' || feed === 'dev' ? ctrlRow('Канал', sel('data-upd-feed', 'Канал обновлений', [['stable', 'Stable (рекомендуется)', true], ['beta', 'Beta'], ['dev', 'Dev']], feed), feed === 'dev' ? 'сборки в разработке, возможны ошибки' : 'проверенные сборки; Stable откроется с первым выпуском') : '') +
        '</dl>' + (feed === 'custom' ? kv([['Канал', 'свой адрес манифеста', '', null, '', 'задан в update.conf на роутере']]) : '') +
        confirmBox('feed-dev', 'Перейти на канал Dev? Это сборки в разработке: в них возможны ошибки. Вернуться на бету можно в любой момент - обновления с беты придут, когда она догонит установленную версию.', 'Перейти', true),
      { desc: 'Изменения сохраняются сразу. Подпись и защита от отката версии проверяются на любом канале.' });
  },

  settings() {
    const sec = S.security || {}, l = sec.listener || {}, api = sec.api || {}, au = S.auth || {};
    return loadError(['security']) +
      panel('Оформление', '<dl class="kv">' + ctrlRow('Тема', sel('data-theme-pick', 'Тема оформления', Object.keys(THEMES).map(k => [k, THEMES[k].charAt(0).toUpperCase() + THEMES[k].slice(1)]), theme), theme === 'time' ? 'светлая с 07:00 до 20:00, тёмная ночью' : '') + '</dl>',
        { desc: 'Тема хранится в этом браузере.' }) +
      panel('Доступ к VWARD', '<dl class="kv">' + ctrlRow('Вход по учётной записи Keenetic', sw('data-auth', !!(au.enabled || authForm), 'Вход по учётной записи Keenetic', !S.auth),
          au.enabled ? (au.logged_in ? 'вы вошли как ' + au.login + ' · сессия ' + au.session_hours + ' ч' : 'нужен вход') : 'пароль проверяет роутер, VWARD его не хранит') +
        (S.auth && au.devices_only != null ? ctrlRow('Только зарегистрированные устройства', sw('data-auth-devices', !!au.devices_only, 'Только зарегистрированные устройства', !au.devices_only && (au.device || {}).state !== 'registered'), devicesHint(au)) : '') + '</dl>' +
        (authForm && !au.enabled ? '<form class="inline-form" data-form="auth-enable"><input class="input" name="login" placeholder="логин Keenetic" aria-label="Логин" autocomplete="username"><input class="input" name="password" type="password" placeholder="пароль" aria-label="Пароль" autocomplete="current-password"><button class="btn primary" type="submit">Включить вход</button></form><p class="panel-desc">Введите логин и пароль от веб-интерфейса роутера: вход включится, только если роутер их примет.</p>' : '') +
        confirmBox('auth-off', 'Выключить вход? VWARD снова будет открыт любому устройству в домашней сети.', 'Выключить', true) +
        kv([
          ['Адрес VWARD', (l.address || location.hostname) + ':' + (l.port || location.port || '80')],
          ['Защита запросов', api.mutation_guard ? 'Включена' : 'Выключена', api.mutation_guard ? 'ok' : 'crit'],
          ['Доступ с других сайтов', api.cors ? 'Разрешён' : 'Запрещён', api.cors ? 'crit' : 'ok']
        ]) + (au.enabled ? (au.logged_in ? '<div class="panel-actions">' + btn('logout', 'undo', 'Выйти') + '</div>' : '') : '<p class="field-warn">Пока вход выключен, VWARD открыт любому устройству в домашней сети.</p>'),
      { desc: 'Сессия действует ' + (au.session_hours || 12) + ' ч. После 5 неверных попыток вход блокируется на 5 минут.' + (au.devices_only ? ' Если доступ потерян: по SSH выполните /opt/bin/vward-console-config.sh console-devices 0.' : '') }) +
      backupPanel() +
      panel('Нижняя панель на телефоне', '<div class="tabbar preview" data-key="Разделы на панели">' + tabsHtml() + '</div><dl class="kv">' + PAGES.map(p => {
        const on = tabIds.includes(p.id), i = tabIds.indexOf(p.id);
        return ctrlRow(p.title, (on ? '<span class="order-btns"><button class="icon-btn" type="button" data-move="' + p.id + ':up" aria-label="Выше"' + (i === 0 ? ' disabled' : '') + '>' + ico('up') + '</button><button class="icon-btn" type="button" data-move="' + p.id + ':down" aria-label="Ниже"' + (i === tabIds.length - 1 ? ' disabled' : '') + '>' + ico('down') + '</button></span>' : '') + sw('data-tabpick="' + p.id + '"', on, 'Показывать «' + p.title + '» на панели'));
      }).join('') + '</dl>', { desc: 'До ' + TAB_MAX + ' разделов и их порядок. Остальные разделы - в меню «Ещё».' });
  },

  logs() {
    const text = S.logs[logTab];
    return '<section class="block" aria-label="Журналы"><div class="block-head"><div class="panel-tools">' +
      '<button class="icon-btn" type="button" data-act="log-copy" aria-label="Копировать" title="Копировать">' + ico('copy') + '</button>' +
      '<button class="icon-btn" type="button" data-act="log-share" aria-label="Поделиться" title="Поделиться">' + ico('share') + '</button>' +
      '<button class="icon-btn" type="button" data-act="log-save" aria-label="Сохранить журнал в .txt" title="Сохранить журнал в .txt">' + ico('save') + '</button>' +
      '<button class="icon-btn" type="button" data-act="log-save-all" aria-label="Сохранить все журналы" title="Сохранить все журналы">' + ico('archive') + '</button>' +
      '<button class="icon-btn" type="button" data-act="log-wrap" aria-pressed="' + logWrap + '" aria-label="Перенос строк" title="Перенос строк">' + ico('wrap') + '</button>' +
      '<button class="icon-btn" type="button" data-act="log-reload" aria-label="Обновить журнал" title="Обновить журнал">' + ico('refresh') + '</button></div></div><div class="panel">' +
      '<div class="segmented" role="group" aria-label="Журнал">' + LOG_TABS.map(t => '<button type="button" data-log="' + t.id + '" aria-pressed="' + (t.id === logTab) + '">' + esc(t.label) + '</button>').join('') + '</div>' +
      '<pre class="logbox' + (logWrap ? '' : ' nowrap') + '" id="logBox">' + esc(text == null ? 'Загрузка…' : text) + '</pre></div></section>';
  },

  'd-components'() {
    const pc = plat().components || {};
    return panel('Компоненты', '<ul class="rows">' + COMPONENTS.map(c => { const x = pc[c.id] || {}; return '<li class="row link" role="button" tabindex="0" data-go="c-' + c.id + '"><div class="row-main"><b>' + esc(c.name) + '</b><small>' + esc(x.release || plat().version || '—') + (x.installed_at ? ' · установлен ' + esc(x.installed_at) : '') + '</small></div>' + (compOn(c.id) ? '<span class="pill ' + (x.health === 'PASS' ? 'ok' : '') + '">' + (x.health === 'PASS' ? 'Норма' : 'Нет данных') + '</span>' : '<span class="pill warn">Выключен</span>') + ico('chevron', 'chev') + '</li>'; }).join('') + '</ul>');
  },
  'd-diag'() {
    const d = S.diag, map = { 'console-api': 'settings', opt: 'system', lighttpd: 'c-console', crond: 'd-cron', supervisor: 'd-cron', adguard: 'ads', adaptive: 'c-route-engine', updater: 'u-vward', config: 'u-vward', wan: 'wan', wg: 'vpn', smartdns: 'lists' };
    const sv = st().services || {};
    return panel('Задания по расписанию', kv([['Задания по расписанию', sv.crond && sv.supervisor ? 'Работают' : sv.crond ? 'Supervisor остановлен' : 'cron остановлен', sv.crond && sv.supervisor ? 'ok' : 'crit', 'd-cron']]),
        { desc: 'Здесь - сводка. Нажмите, чтобы открыть список заданий и их последние запуски.' }) +
      panel('Диагностика', (d && d.checks ? '<ul class="rows">' + d.checks.map(x => { const to = map[x.id]; return '<li class="row' + (to ? ' link" role="button" tabindex="0" data-go="' + to + '"' : '"') + '><div class="row-main"><b>' + esc(x.label) + '</b><small>' + esc(x.detail || '') + '</small></div><span class="pill ' + (x.status === 'PASS' ? 'ok' : x.status === 'FAIL' ? 'crit' : 'warn') + '">' + (x.status === 'PASS' ? 'Норма' : x.status === 'FAIL' ? 'Сбой' : 'Внимание') + '</span>' + (to ? ico('chevron', 'chev') : '') + '</li>'; }).join('') + '</ul>' : empty(S.errors.diag ? 'Диагностика не выполнена: ' + S.errors.diag : 'Загрузка…')) +
      '<div class="panel-actions">' + btn('diag-run', 'check', 'Запустить проверку', 'primary') + '</div>');
  },
  'd-cron'() {
    const sv = st().services || {}, cr = S.cron;
    const jobs = cr && cr.ok ? cr.jobs : [];
    const row = x => { const comp = JOB_COMPONENT[x.name] || x.component, on = compOn(comp), ok = x.rc === 0;
      return '<li class="row link" role="button" tabindex="0" data-go="c-' + esc(comp) + '"><div class="row-main"><b>' + esc(JOB_NAMES[x.name] || x.name) + '</b><small>' + esc(cronText(x.schedule)) + ' · ' + esc(fmtStamp(x.last) || 'ещё не запускалось') + '</small></div>' +
        '<span class="pill ' + (!on ? 'warn' : x.rc == null ? '' : ok ? 'ok' : 'crit') + '">' + (!on ? 'Выключен' : x.rc == null ? 'Нет данных' : ok ? 'Успешно' : 'Код ' + x.rc) + '</span>' + ico('chevron', 'chev') + '</li>'; };
    return panel('Служба расписания', kv([['cron', sv.crond ? 'Работает' : 'Остановлен', sv.crond ? 'ok' : 'crit'], ['Supervisor', sv.supervisor ? 'Работает' : 'Остановлен', sv.supervisor ? 'ok' : 'crit']])) +
      panel('Задания', !cr ? empty('Загрузка…') : !cr.ok ? empty(errText(cr)) : jobs.length ? '<ul class="rows">' + jobs.map(row).join('') + '</ul>' : empty('Задания не найдены'),
        { desc: 'Все задания VWARD из crontab роутера. Нажмите на задание, чтобы открыть его компонент.' });
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
  lists() {
    if (!S.lists) return loadError(['lists']) + panel('Доменные списки', empty('Загрузка…'));
    const L = S.lists, items = L.lists || [], ok = cfgOk(), path = listPath;
    // A row opens its list: switches, domains and exclusions live there.
    const row = l => '<li class="row link" role="button" tabindex="0" data-go="l-' + esc(l.name) + '"><div class="row-main"><b>' + esc(l.description || l.name) + '</b><small>' + fmtInt(l.count) + ' ' + plural(l.count, 'домен', 'домена', 'доменов') + ' · ' + esc(path(l)) + '</small>' +
      (l.smartdns_conflict || (l.auto && viaIs(l, 'vpn')) ? '<small class="st warn">' + ico('alert') + (l.smartdns_conflict ? 'конфликт со Smart DNS' : 'переведён на VPN автоматически') + '</small>' : '') + '</div>' + ico('chevron', 'chev') + '</li>';
    const sd = L.smartdns_domains || [];
    return cfgNote() + panel('Доменные списки', items.length ? '<ul class="rows">' + items.map(row).join('') + '</ul>' : empty('В Keenetic нет доменных списков'),
        { desc: 'Нажмите на список, чтобы изменить его домены и куда он идёт.' }) +
      panel('Smart DNS', kv([
        ['Защита Smart DNS', L.smartdns_guard !== false ? 'включена' : 'выключена', L.smartdns_guard !== false ? '' : 'warn', 'd-smartdns'],
        ['Домены', sd.length ? sd.length + ' ' + plural(sd.length, 'домен', 'домена', 'доменов') + ' · ' + smartdnsWhere(L) : 'нет', '', 'd-smartdns']
      ]));
  },
  'd-smartdns'() {
    const L = S.lists;
    if (!L) return loadError(['lists']) + panel('Smart DNS', empty('Загрузка…'));
    const sd = L.smartdns_domains || [], src = L.smartdns_sources || {}, ok = cfgOk();
    const from = d => ((src.adguard || []).includes(d) ? 'AdGuard Home' : '') + ((src.keenetic || []).includes(d) ? ((src.adguard || []).includes(d) ? ' и ' : '') + 'Keenetic' : '');
    return cfgNote() +
      panel('Защита', '<dl class="kv">' + ctrlRow('Защита Smart DNS', sw('data-smartdns-guard', L.smartdns_guard !== false, 'Защита Smart DNS', !ok), 'AdaptiveAuto не отправляет эти домены в VPN') + '</dl>' +
        (L.doh_limit ? kv([['Строк DNS-over-HTTPS в Keenetic', fmtInt(L.doh_used || 0) + ' из ' + fmtInt(L.doh_limit), L.doh_used >= L.doh_limit ? 'warn' : '']]) : ''),
        { desc: 'Smart DNS отвечает на все свои домены одним адресом прокси. Если этот адрес уйдёт в VPN, перестанут работать все сервисы Smart DNS сразу.' }) +
      panel('Домены Smart DNS', sd.length ? '<ul class="rows">' + sd.map(d => '<li class="row"><div class="row-main"><b>' + dom(d) + '</b><small>' + esc(from(d) || smartdnsWhere(L)) + '</small></div></li>').join('') + '</ul>' : empty('Smart DNS не настроен'),
        { desc: (src.adguard || []).length ? 'Эти домены заданы в AdGuard Home: «Настройки» → «Настройки DNS» → «Upstream DNS-серверы», строки вида [/домен/]адрес. VWARD их читает, но не меняет: Smart DNS - ваша настройка.' : 'Эти домены заданы в Keenetic: «Интернет-фильтры» → DNS-over-HTTPS. VWARD их читает, но не меняет.' });
  },
  'd-adaptive'() {
    const list = S.config ? cfgRoute().adaptive || [] : (S.route && S.route.adaptive && S.route.adaptive.recent) || [];
    return cfgNote() + panel('AdaptiveAuto', domainRows(list.map(d => typeof d === 'string' ? d : d.domain || ''), d => rowBtn('adaptive', 'pin', d, 'lock', 'Закрепить ' + d + ' в моих доменах') + rowBtn('adaptive', 'remove', d, 'close', 'Вернуть ' + d + ' на прямой маршрут'), 'недоступен напрямую - идёт через VPN') || empty('Пока пусто'),
      { desc: 'Домены, которые VWARD сам отправил через VPN после неудачной прямой проверки. «Закрепить» переносит домен в мои домены, «убрать» - возвращает на прямой маршрут.' });
  },
  'd-ipcats'() {
    const ip = (S.route && S.route.ip) || {}, act = ip.active || [], idx = (ip.index || []).slice().sort((a, b) => (act.includes(b.name) - act.includes(a.name)) || a.name.localeCompare(b.name)), off = cfgRoute().ip_excluded || [];
    return cfgNote() + panel('IP-категории', idx.length ? '<dl class="kv">' + idx.map(x => ctrlRow(x.name, sw('data-ipcat="' + esc(x.name) + '"', !off.includes(x.name), 'IP-категория ' + x.name, !cfgOk()), fmtInt(x.cidr) + ' ' + plural(x.cidr, 'сеть', 'сети', 'сетей') + (act.includes(x.name) ? ' · сейчас через VPN' : ''))).join('') + '</dl>' : empty('Каталог IP-категорий ещё не загружен'),
      { desc: 'Категория включается автоматически, когда её домены идут через VPN. Выключенная категория не получит маршрутов; изменение применится при следующей сверке IP-категорий.' });
  },
  'd-services'() {
    const list = (S.route && S.route.services) || [];
    return panel('Проверяемые сервисы', list.length ? '<ul class="rows">' + list.map(x => '<li class="row"><div class="row-main"><b>' + esc(x.name) + '</b><small>' + dom(x.host) + (x.fails ? ' · неудач подряд: ' + x.fails : '') + '</small></div><span class="pill ' + (x.oks != null && x.oks > 0 ? 'info' : '') + '">' + (x.fails == null && x.oks == null ? 'ещё не проверялся' : 'проверяется') + '</span></li>').join('') + '</ul>' : empty('Сервисы не заданы'),
      { desc: 'Сервисы из services.conf: VWARD проверяет их напрямую и переключает через VPN, если прямой доступ пропал.' });
  },
  'd-querylog'() {
    const q = S.qlog, f = [['all', 'Все'], ['blocked', 'Заблокированные'], ['allowed', 'Разрешённые'], ['review', 'На проверке']];
    return panel('Журнал запросов', '<div class="segmented" role="group" aria-label="Фильтр">' + f.map(x => '<button type="button" data-qfilter="' + x[0] + '" aria-pressed="' + (ADSV.filter === x[0]) + '">' + x[1] + '</button>').join('') + '</div>' +
      '<form class="inline-form" data-form="ads-qsearch"><input class="input" name="q" value="' + esc(ADSV.search) + '" placeholder="часть домена, например yandex" aria-label="Поиск по домену" autocomplete="off"><button class="btn" type="submit">' + ico('search') + 'Найти</button></form>' +
      (!q ? empty('Загрузка…') : !q.ok ? empty(errText(q)) : q.entries.length ? '<ul class="rows">' + q.entries.map(e => '<li class="row"><div class="row-main"><b>' + dom(e.domain) + '</b><small><span class="st ' + (e.blocked ? 'crit' : 'ok') + '">' + (e.blocked ? 'заблокирован' : 'разрешён') + '</span>' + (e.verdict === 'SUSPECT' ? ' · на проверке' : '') + ' · ' + esc(fmtTime(e.time)) + ' · ' + esc(e.client) + '</small></div><span class="row-acts">' + adsRuleBtn(e.domain, e.blocked ? 'allow' : 'block') + '</span></li>').join('') + '</ul>' : empty('Запросов не найдено')),
      { desc: 'Последние запросы из AdGuard Home. Кнопка у строки добавляет правило для этого домена.' });
  },
  'd-review'() {
    const r = S.review;
    return panel('На проверке', !r ? empty('Загрузка…') : !r.ok ? empty(errText(r)) : r.entries.length ? '<ul class="rows">' + r.entries.map(e => '<li class="row"><div class="row-main"><b>' + dom(e.domain) + '</b><small>' + esc(reasonText(e.reason)) + (e.action === 'BLOCK' ? ' · <span class="st crit">пока заблокирован</span>' : '') + '</small></div><span class="row-acts">' + adsRuleBtn(e.domain, 'allow') + adsRuleBtn(e.domain, 'block') + '</span></li>').join('') + '</ul>' : empty('Нечего проверять'),
      { desc: 'Домены, по которым источники расходятся. Решение сохраняется как ваше правило.' });
  },
  'd-blocked'() {
    const r = S.blocked;
    return panel('Заблокировано', '<form class="inline-form" data-form="ads-bsearch"><input class="input" name="q" value="' + esc(ADSV.blockedSearch) + '" placeholder="часть домена" aria-label="Поиск по домену" autocomplete="off"><button class="btn" type="submit">' + ico('search') + 'Найти</button></form>' +
      (!r ? empty('Загрузка…') : !r.ok ? empty(errText(r)) : r.entries.length ? '<ul class="rows">' + r.entries.map(e => '<li class="row"><div class="row-main"><b>' + dom(e.domain) + '</b><small>' + esc(reasonText(e.reason)) + '</small></div><span class="row-acts">' + adsRuleBtn(e.domain, 'allow') + '</span></li>').join('') + '</ul>' + (r.total > r.entries.length ? '<p class="panel-desc">Показаны ' + r.entries.length + ' из ' + fmtInt(r.total) + ' - уточните поиск.</p>' : '') : empty('Ничего не найдено')),
      { desc: 'Домены, которые VWARD заблокировал автоматически.' });
  },
  'd-adcats'() {
    const cats = (S.ads && S.ads.categories) || [];
    return panel('Категории блокировки', cats.length ? '<dl class="kv">' + cats.map(c => ctrlRow(catText(c.id), sw('data-ads-cat="' + esc(c.id) + '"', c.active > 0, 'Категория ' + catText(c.id), !S.ads), c.active + ' из ' + c.total + ' ' + plural(c.total, 'источника', 'источников', 'источников') + ' включены')).join('') + '</dl>' : empty('Категории не найдены'),
      { desc: 'Выключение категории выключает все её источники; включение возвращает им режим по умолчанию.' });
  },
  'd-rules'() {
    const rules = (S.ads && S.ads.manual_rules) || [];
    return panel('Добавить правило', '<form class="inline-form" data-form="ads-rule"><input class="input" id="adsRuleDomain" placeholder="домен, например example.com" aria-label="Домен" autocomplete="off"><select class="input compact" id="adsRuleType" aria-label="Действие"><option value="block">Блокировать</option><option value="allow">Разрешить</option></select><select class="input compact" id="adsRuleScope" aria-label="Область"><option value="exact">Только домен</option><option value="suffix">С поддоменами</option></select><button class="btn primary" type="submit">Добавить</button></form>' + resultBox('ads-rule')) +
      panel('Мои правила', rules.length ? '<ul class="rows">' + rules.map(r => '<li class="row"><div class="row-main"><b>' + dom(r.domain) + '</b><small><span class="st ' + (r.type === 'allow' ? 'ok' : 'crit') + '">' + (r.type === 'allow' ? 'разрешён' : 'заблокирован') + '</span> · ' + (r.scope === 'suffix' ? 'домен и поддомены' : 'только домен') + '</small></div><button class="icon-btn" type="button" title="Удалить правило" data-ads-remove="' + esc(r.domain) + '" data-scope="' + esc(r.scope || 'exact') + '" aria-label="Удалить правило ' + esc(r.domain) + '">' + ico('close') + '</button></li>').join('') + '</ul>' : empty('Правил пока нет'), { desc: 'Ручные правила важнее списков и автоматических решений.' });
  },
  'd-sources'() {
    const src = (S.ads && S.ads.sources) || [];
    return panel('Источники списков', src.length ? '<ul class="rows">' + src.map(x => '<li class="row"><div class="row-main"><b>' + esc(x.name || x.id) + '</b><small>' + esc(catText(x.purpose)) + (x.cached ? ' · загружен' : ' · ещё не загружен') + '</small></div>' + sel('data-ads-source="' + esc(x.id) + '"', 'Режим ' + (x.name || x.id), [['off', 'Выключен'], ['check', 'Проверка'], ['active', 'Активен']], x.mode) + (x.custom ? '<button class="icon-btn" type="button" data-ads-srcdel="' + esc(x.id) + '" aria-label="Удалить источник" title="Удалить источник">' + ico('close') + '</button>' : '') + '</li>').join('') + '</ul>' : empty('Источники не найдены'), { desc: '«Проверка» - источник учитывается при оценке, но сам ничего не блокирует. «Активен» - блокирует.' }) +
      panel('Добавить свой источник', '<form class="inline-form" data-form="ads-srcadd"><input class="input" name="url" placeholder="https://example.org/list.txt" aria-label="Адрес списка" autocomplete="off" inputmode="url"><select class="input compact" name="format" aria-label="Формат"><option value="adblock">Adblock</option><option value="hosts">hosts</option><option value="domains">Список доменов</option></select><button class="btn primary" type="submit">Добавить</button></form>' + resultBox('ads-src'),
        { desc: 'Только https. Новый источник начинает в режиме «Проверка»; размер и формат проверяются при загрузке - список больше 8 МБ или меньше 10 записей не принимается. До 10 своих источников.' });
  },
  'd-files'() {
    if (!FILES.root) return panel('Папки VWARD', '<ul class="rows">' + FILE_ROOTS.map(r => '<li class="row link" role="button" tabindex="0" data-files-root="' + r[0] + '"><div class="row-main"><b>' + esc(r[1]) + '</b><small>' + esc(r[2]) + '</small></div>' + ico('chevron', 'chev') + '</li>').join('') + '</ul>',
      { desc: 'Только просмотр и скачивание. Ключи туннелей, пароли и служебные файлы закрыты.' });
    const x = S.files, here = x && x.ok && x.root === FILES.root && x.path === FILES.path ? x : null;
    const title = [FILE_ROOTS.find(r => r[0] === FILES.root)[1]].concat(FILES.path ? FILES.path.split('/') : []).join(' / ');
    const up = '<li class="row link" role="button" tabindex="0" data-files-up="1"><div class="row-main"><b>..</b><small>' + (FILES.path ? 'на уровень выше' : 'к списку папок') + '</small></div>' + ico('up', 'chev') + '</li>';
    return panel(title, !here ? (x && !x.ok && !S.errors.files ? '<ul class="rows">' + up + '</ul>' + empty(errText(x)) : empty('Загрузка…')) : '<ul class="rows">' + up + here.entries.map(e => {
      const dir = e.kind === 'dir', open = !e.closed && (dir || e.kind === 'file');
      return '<li class="row' + (open ? ' link" role="button" tabindex="0" data-files-' + (dir ? 'dir' : 'open') + '="' + esc(e.name) + '"' : '"') + '><div class="row-main"><b>' + esc(e.name) + (dir ? '/' : '') + '</b><small>' + (dir ? 'папка' : fmtBytes(e.size)) + (e.time ? ' · ' + esc(e.time) : '') + '</small></div>' +
        (e.closed ? '<span class="pill">закрыт</span>' : ico(dir ? 'chevron' : 'eye', 'chev')) + '</li>';
    }).join('') + '</ul>' + (here.entries.length ? '' : empty('Папка пуста')));
  },
  'd-notes'() {
    const p = plat(), pend = (S.update && S.update.pending) || {};
    return (pend.present && pend.version ? panel('Доступно: ' + pend.version, notesHtml(pend.version)) : '') +
      panel('Установлено: ' + (p.version || '—'), notesHtml(p.version));
  },
  'd-jobs'() {
    const JOB_TEXT = { scan: 'проверка новых доменов', 'sources-update': 'обновление источников', 'rules-rebuild': 'пересборка правил', publish: 'публикация', probe: 'проверка домена' };
    const JOB_STATE = { DONE: 'выполнено', PASS: 'выполнено', FAILED: 'ошибка', RUNNING: 'идёт', QUEUED: 'в очереди' };
    const j = (S.ads && S.ads.jobs) || {}, cur = j.current || {}, last = j.last || {};
    return panel('Задания', kv([['Сейчас', cur.state && cur.state !== 'IDLE' ? (cur.type || cur.state) : 'нет активных', cur.state && cur.state !== 'IDLE' ? 'info' : ''], ['В очереди', fmtInt(j.queued || 0)], ['Последнее', !last.type || last.state === 'NONE' ? 'ещё не было' : (JOB_TEXT[last.type] || last.type) + ' · ' + (JOB_STATE[last.state] || last.state), last.state === 'FAILED' ? 'crit' : '']]) +
      '<div class="panel-actions even">' + btn('ads-job', 'search', 'Проверить новые домены', '', ' data-job="scan"') + btn('ads-job', 'refresh', 'Обновить источники', '', ' data-job="sources-update"') + btn('ads-job', 'check', 'Пересобрать правила', '', ' data-job="rules-rebuild"') + '</div>' +
      resultBox('ads-job'), { desc: 'Задания выполняются по одному, когда роутер не загружен. Подробности - в «Журналах» → «Реклама».' });
  },
  'd-aghfilters'() {
    const g = S.agh, fl = (g && g.filtering && g.filtering.filters) || [];
    const rm = confirm && confirm.id === 'agh-filter-remove' ? confirm.url : '';
    return panel('Фильтры AdGuard Home', !g ? empty('Загрузка…') : !g.ok ? empty(errText(g)) : (fl.length ? '<ul class="rows">' + fl.map(f => '<li class="row"><div class="row-main"><b>' + esc(f.name || f.url) + '</b><small>' + fmtInt(f.rules) + ' ' + plural(f.rules, 'правило', 'правила', 'правил') + (f.updated ? ' · обновлён ' + esc(fmtTime(f.updated)) : '') + '</small>' +
        '</div>' +
        '<span class="row-acts">' + sw('data-agh-filter="' + esc(f.url) + '"', f.enabled, 'Список ' + (f.name || f.url)) + '<button class="icon-btn" type="button" data-agh-filter-rm="' + esc(f.url) + '" aria-label="Удалить ' + esc(f.name || f.url) + '" title="Удалить">' + ico('close') + '</button></span>' +
        (rm === f.url ? '<div class="confirm danger"><span>Удалить список из AdGuard Home?</span><button class="btn small danger" type="button" data-act="confirm-yes">Удалить</button><button class="btn small" type="button" data-act="confirm-no">Отмена</button></div>' : '') + '</li>').join('') + '</ul>' : empty('Списков нет')) +
      '<form class="inline-form" data-form="agh-filter-add"><input class="input" name="url" placeholder="https://… адрес списка" aria-label="Адрес списка" autocomplete="off"><input class="input" name="name" placeholder="Название" aria-label="Название списка" maxlength="64"><button class="btn" type="submit">Добавить</button></form>' +
      '<div class="panel-actions">' + btn('agh-filters-refresh', 'refresh', 'Обновить списки сейчас') + '</div>' + resultBox('agh'),
      { desc: 'Списки блокировки самого AdGuard Home. Выключенный список остаётся, но не применяется.' });
  },
  'd-aghservices'() {
    const g = S.agh, sv = g && g.services, bl = (sv && sv.blocked) || [];
    const list = sv ? sv.available.slice().sort((a, b) => (bl.includes(b.id) - bl.includes(a.id)) || a.name.localeCompare(b.name)) : [];
    return panel('Блокировка сервисов', !g ? empty('Загрузка…') : !g.ok ? empty(errText(g)) : !sv ? empty('Эта версия AdGuard Home не отдаёт список сервисов') :
      '<dl class="kv">' + list.map(x => ctrlRow(x.name, sw('data-agh-service="' + esc(x.id) + '"', bl.includes(x.id), 'Блокировать ' + x.name))).join('') + '</dl>',
      { desc: 'Сервис блокируется целиком для всех устройств: включите, чтобы закрыть его, выключите, чтобы открыть.' });
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
function cfgNote() { return !S.config ? '' : !S.config.writable ? '<p class="field-warn">Изменение настроек из VWARD недоступно: на роутере нет vward-console-config.sh. Установите обновление VWARD.</p>' : ''; }
function addForm(op, placeholder) { return '<form class="inline-form" data-form="cfg-add" data-op="' + op + '"><input class="input" name="domain" placeholder="' + esc(placeholder) + '" aria-label="Домен" autocomplete="off"' + (cfgOk() ? '' : ' disabled') + '><button class="btn primary" type="submit"' + (cfgOk() ? '' : ' disabled') + '>Добавить</button></form>'; }
function rowBtn(op, action, d, icon, label) { return '<button class="icon-btn" type="button" data-cfg-op="' + op + '" data-cfg-action="' + action + '" data-cfg-target="' + esc(d) + '" aria-label="' + esc(label) + '" title="' + esc(label) + '"' + (cfgOk() ? '' : ' disabled') + '>' + ico(icon) + '</button>'; }
function domainRows(list, acts, sub) { return list.length ? '<ul class="rows">' + list.map(d => '<li class="row"><div class="row-main"><b>' + dom(d) + '</b>' + (sub ? '<small>' + esc(sub) + '</small>' : '') + '</div><span class="row-acts">' + acts(d) + '</span></li>').join('') + '</ul>' : ''; }
const CAT_NAMES = { 'ads-tracking-security': 'Реклама, трекеры и угрозы', 'ads-tracking-security-aggressive': 'Усиленная защита', 'popup-ads': 'Всплывающая реклама', 'ads-tracking': 'Реклама и трекеры', ads: 'Реклама', tracking: 'Трекеры', 'ads-malware': 'Реклама и вредоносные сайты', 'mobile-ads': 'Реклама в приложениях', custom: 'Свои источники' };
const catText = id => CAT_NAMES[id] || id || '';
const REASONS = { source_consensus: 'несколько источников согласны', single_source: 'только один источник', block_revalidation_pending: 'ждёт повторной проверки', block_evidence_disappeared_review: 'источники больше не подтверждают', no_block_evidence: 'нет причин блокировать' };
const reasonText = r => REASONS[r] || (r || '').replace(/_/g, ' ');
// Router stamps come from `date` ("Thu Sep 24 18:20:02 MSK 2026"), ISO or epoch seconds.
const MON = { Jan: 1, Feb: 2, Mar: 3, Apr: 4, May: 5, Jun: 6, Jul: 7, Aug: 8, Sep: 9, Oct: 10, Nov: 11, Dec: 12 };
function fmtStamp(t) {
  if (t == null || t === '') return '';
  const s = String(t).trim(), m = /^[A-Z][a-z]{2} ([A-Z][a-z]{2}) +(\d{1,2}) (\d\d:\d\d)(?::\d\d)?(?: \S+)? (\d{4})$/.exec(s);
  if (m && MON[m[1]]) return ('0' + m[2]).slice(-2) + '.' + ('0' + MON[m[1]]).slice(-2) + ' ' + m[3];
  if (/^\d{9,10}$/.test(s)) return fmtTime(Number(s) * 1000);
  return fmtTime(s);
}
function fmtTime(t) { const d = new Date(t); return isNaN(d) ? (t || '') : d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); }
const FILE_ROOTS = [['etc', 'Настройки', '/opt/etc/vward'], ['state', 'Состояние', '/opt/var/lib/vward'], ['logs', 'Журналы', '/opt/var/log/vward'], ['share', 'Программа', '/opt/share/vward']];
const filePath = name => (FILES.path ? FILES.path + '/' : '') + name;
function filesGo(root, path) { FILES.root = root; FILES.path = path; S.files = null; render(); load('files', true).then(render); }
async function fileOpen(name) {
  const path = filePath(name), dl = '/cgi-bin/api.cgi?action=files&op=download&root=' + encodeURIComponent(FILES.root) + '&path=' + encodeURIComponent(path);
  openSheet(name, '<div class="sheet-body">' + empty('Загрузка…') + '</div>', 'wide');
  let x; try { x = await apiGet('files', { op: 'read', root: FILES.root, path: path }); } catch (e) { x = { ok: false, error: e.message }; }
  const note = !x.ok ? errText(x) : x.binary ? 'Двоичный или сжатый файл: можно только скачать.' : x.truncated ? (x.from_end ? 'Показан конец файла - последние 64 КБ.' : 'Показано начало файла - первые 64 КБ.') : '';
  const body = '<div class="sheet-body"><p class="panel-desc">' + esc(fmtBytes(x.size)) + (note ? ' · ' + esc(note) : '') + '</p>' +
    (x.ok ? '<div class="panel-actions"><a class="btn" href="' + esc(dl) + '" download>' + ico('save') + 'Скачать</a></div>' : '') + (x.ok && !x.binary ? '<pre class="logbox">' + esc(x.text) + '</pre>' : '') + '</div>';
  const sh = document.querySelector('#layer .sheet');
  if (!sh || sh.getAttribute('aria-label') !== name) return;
  sh.querySelector('.sheet-body').outerHTML = body;
  // A log is read from its end: show the newest lines first.
  if (FILES.root === 'logs') { const b = sh.querySelector('.sheet-body'); b.scrollTop = b.scrollHeight; }
}
// Domain check: queued as a job; the page waits for its report and sums it up.
let PROBE = null;
async function adsProbe(domain) {
  PROBE = { domain: domain, text: 'в очереди…' }; render();
  let x;
  try { x = await apiPost('ads-control', { op: 'enqueue', job: 'probe', domain: domain }); } catch (e) { x = { ok: false, error: e.message }; }
  const id = x.ok && (/JOB_ID=(\S+)/.exec(x.result || '') || [])[1];
  if (!id) { PROBE = { domain: domain, done: true, error: errText(x) }; render(); return; }
  for (let i = 0; i < 60 && PROBE && PROBE.domain === domain; i++) {
    await new Promise(r => setTimeout(r, 3000));
    await load('ads', true);
    const j = (S.ads && S.ads.jobs) || {}, l = j.last || {};
    if (l.id === id) { PROBE = { domain: domain, done: true, failed: l.state === 'FAILED', out: l.output || '' }; render(); return; }
    PROBE.text = j.current && j.current.type === 'probe' ? 'проверяется…' : 'в очереди…'; render();
  }
  if (PROBE && PROBE.domain === domain && !PROBE.done) { PROBE = { domain: domain, done: true, error: 'проверка ещё в очереди - результат появится в «Задания»' }; render(); }
}
function probeResult() {
  const p = PROBE;
  if (!p) return '';
  if (!p.done) return '<p class="result-note">' + esc(p.domain) + ': ' + esc(p.text) + '</p>';
  if (p.error || p.failed) return '<p class="result-note">' + esc(p.domain) + ': ' + esc(p.error || 'проверка не удалась, подробности в «Журналах»') + '</p>';
  const o = p.out, has = k => new RegExp('^' + k + '=MATCH$', 'm').test(o);
  const sec2 = (o.split('=== 2.')[1] || '').split('\n').map(x => x.trim()).filter(Boolean)[1] || '';
  const vr = sec2.split('|'), known = vr.length >= 8 && vr[0] === p.domain;
  const v = known ? (ADS_VERDICT[vr[1]] || ['', vr[1]]) : null;
  const names = (o.match(/^[^|\n]+\|mode=[a-z]+\|match=[^\n]*$/gm) || []).map(l => (/\|name=(.*)$/.exec(l) || [])[1]).filter(Boolean);
  const q = num((/^QUERY_COUNT=(\d+)/m.exec(o) || [])[1]);
  return kv([
    ['Решение VWARD', v ? v[1] : 'ещё не проверялся', v ? v[0] : '', null, '', known ? ADS_REASON[vr[7]] || vr[7] : ''],
    has('ALLOWLIST') ? ['Ваше правило', 'Разрешить', 'ok'] : has('DENYLIST') ? ['Ваше правило', 'Блокировать', 'crit'] : null,
    has('TRUST') ? ['Доверенный сервис', 'Да', 'ok'] : null,
    ['Найден в источниках', names.length ? fmtInt(names.length) + ' ' + plural(names.length, 'источник', 'источника', 'источников') : 'нет', '', null, '', names.slice(0, 3).join(', ')],
    ['Запросов в журнале', q != null ? fmtInt(q) : '—']
  ]) + '<div class="panel-actions">' + adsRuleBtn(p.domain, 'allow') + adsRuleBtn(p.domain, 'block') + btn('probe-report', 'logs', 'Полный отчёт', 'small') + '</div>';
}
function devicesHint(au) {
  const d = au.device || {}, where = d.ip ? ' (' + d.ip + ')' : '';
  if (d.state === 'registered') return 'это устройство зарегистрировано' + where;
  if (d.state === 'unknown') return 'список устройств Keenetic сейчас недоступен';
  return 'это устройство не зарегистрировано' + where + ' - сначала зарегистрируйте его в Keenetic';
}
// Smart DNS rows may sit in Keenetic, in AdGuard Home, or in both.
function smartdnsWhere(L) {
  const src = L.smartdns_sources || {}, k = (src.keenetic || []).length, a = (src.adguard || []).length;
  return k && a ? 'Keenetic и AdGuard Home' : a ? 'AdGuard Home' : k ? 'Keenetic' : 'не найден';
}
// «Что нового»: a version's section of the CHANGELOG, from the router (installed)
// or from the update feed (an update on offer).
const NOTES = {};
function notesVersions() { const p = plat(), pend = (S.update && S.update.pending) || {}; return [pend.present && pend.version, p.version].filter(Boolean); }
async function loadNotes(v) {
  if (NOTES[v] && NOTES[v].ok) return;
  try { NOTES[v] = await apiGet('release-notes', { version: v }); } catch (e) { NOTES[v] = { ok: false, error: e.message }; }
  if (current === 'd-notes') render();
}
function notesHtml(v) {
  if (!v) return empty('Версия неизвестна');
  const n = NOTES[v];
  if (!n) return empty('Загрузка…');
  if (!n.ok) return empty(n.error === 'notes_unavailable' ? 'Описание этой версии не найдено' : errText(n));
  const fmt = t => esc(t).replace(/`([^`]+)`/g, '<code>$1</code>');
  let html = '', items = [], title = '';
  const flush = () => { if (items.length) { html += '<ul class="notes">' + items.map(i => '<li>' + fmt(i) + '</li>').join('') + '</ul>'; items = []; } };
  n.text.split('\n').forEach(l => {
    if (l.startsWith('#title ')) { title = l.slice(7); return; }
    if (!l.trim()) return;
    if (/^- /.test(l)) items.push(l.slice(2));
    else if (/^\s+\S/.test(l) && items.length) items[items.length - 1] += ' ' + l.trim();
    else { flush(); html += '<p class="notes-sub">' + fmt(l.trim()) + '</p>'; }
  });
  flush();
  return (title ? '<p class="panel-desc">' + esc(title) + '</p>' : '') + (html || empty('Без описания'));
}
const ADS_VERDICT = { BLOCK: ['crit', 'Заблокирован'], SUSPECT: ['warn', 'На проверке'], ALLOW: ['ok', 'Разрешён'], TRUST: ['ok', 'Доверенный'] };
const ADS_REASON = { manual_denylist: 'ваше правило', manual_allowlist: 'ваше правило', trusted_registry: 'доверенный сервис', dedicated_block_feed: 'есть в специальном списке рекламы', multi_source_consensus: 'найден в нескольких источниках', external_verifier: 'внешняя проверка', source_catalog_degraded: 'источники недоступны, решение отложено', block_evidence_disappeared_review: 'пропал из источников, перепроверяется', no_block_evidence: 'признаков рекламы нет' };
function adsRuleBtn(d, type) { return '<button class="icon-btn" type="button" data-ads-rule="' + type + '" data-domain="' + esc(d) + '" aria-label="' + (type === 'allow' ? 'Разрешить ' : 'Заблокировать ') + esc(d) + '" title="' + (type === 'allow' ? 'Разрешить' : 'Заблокировать') + '">' + ico(type === 'allow' ? 'check' : 'block') + '</button>'; }
async function adsViews() { await Promise.all(['ads', 'adspub', 'qlog', 'review', 'blocked'].map(k => S[k] || k === 'ads' || k === 'adspub' ? load(k, true) : null)); render(); }
function fmtBytes(b) { b = num(b); if (b == null) return '—'; const u = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']; let i = 0; while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; } return (i ? b.toFixed(1) : String(b)) + ' ' + u[i]; }
function agoText(sec) { if (sec == null || isNaN(sec)) return '—'; if (sec < 60) return sec + ' с назад'; if (sec < 3600) return Math.round(sec / 60) + ' мин назад'; if (sec < 86400) return Math.round(sec / 3600) + ' ч назад'; return Math.round(sec / 86400) + ' д назад'; }
const JOB_NAMES = { 'vward-route-reconciler.sh': 'Сверка маршрутов', 'S91vward-route-engine': 'Сторож движка маршрутизации', 'vward-policy-chain.sh': 'Обновление IP-категорий', 'vward-route-hints-update.sh': 'Подсказки каталога', 'vward-tunnel-health.sh': 'Защита VPN', 'S92vward-runtime': 'Сторож supervisor', 'vward-wan-guard.sh': 'Восстановление интернета', 'vward-housekeeping.sh': 'Сжатие журналов', 'vward-ads-privacy-scheduler.sh': 'Блокировка рекламы', 'vward-wifi-client-scheduler.sh': 'Контроль Wi-Fi клиентов' };
const JOB_COMPONENT = { 'S91vward-route-engine': 'route-engine' };
function cronText(c) {
  const f = String(c || '').split(' ');
  if (f.length !== 5) return c || '';
  if (f.join(' ') === '* * * * *') return 'каждую минуту';
  if (/^\*\/\d+$/.test(f[0]) && f.slice(1).join(' ') === '* * * *') return 'каждые ' + f[0].slice(2) + ' мин';
  if (/^\d+$/.test(f[0]) && f.slice(1).join(' ') === '* * * *') return 'каждый час в :' + ('0' + f[0]).slice(-2);
  if (/^\d+$/.test(f[0]) && /^\d+$/.test(f[1]) && f.slice(2).join(' ') === '* * *') return 'каждый день в ' + ('0' + f[1]).slice(-2) + ':' + ('0' + f[0]).slice(-2);
  return c;
}
function bandText(b) { return b === '5' ? '5 ГГц' : b === '2.4' ? '2.4 ГГц' : 'диапазон неизвестен'; }
const WIFI_REASONS = { stable: 'переходы редкие, сигнал в норме', frequent_band_switches: 'часто переходит между 2.4 и 5 ГГц', frequent_switches_and_weak_5g: 'часто переходит и слабый сигнал 5 ГГц' };
function recText(c) { return c.recommendation === 'bind_2g' ? 'Закрепить за 2.4' : c.recommendation === 'review' ? 'Проверить' : c.health === 'WARNING' ? 'Внимание' : 'Норма'; }

function tunnelPage(name) {
  const wg = st().wg || {}, t = (wg.interfaces || []).find(x => x.name === name) || { name: name };
  const up = isTrue(t.connected), cur = prof().tunnel_interface, managed = cur === name, failopen = isTrue(wg.failopen_active);
  const use = managed ? '' : failopen ? '<p class="field-warn">Сейчас VPN недоступен и трафик идёт напрямую: переключение станет доступно, когда ' + esc(cur || 'текущий туннель') + ' восстановится.</p>' :
    confirmBox('tunnel-use', 'Перевести маршруты VWARD' + (cur ? ' с ' + cur : '') + ' на ' + name + '? Мои домены, AdaptiveAuto и IP-категории пойдут через ' + name + '.' + (up ? '' : ' Туннель сейчас не в сети: сайты из списков VPN будут недоступны, пока он не подключится.'), 'Переключить', !up) ||
    '<div class="panel-actions">' + btn('ask', 'route', 'Использовать для маршрутов', up ? 'primary' : '', ' data-confirm="tunnel-use"' + (cfgOk() ? '' : ' disabled')) + '</div>';
  return panel(name + (t.description ? ' · ' + t.description : ''), kv([
    ['Канал связи', t.link || '—'], ['Статус интерфейса', t.state || '—'],
    ['Сервер', t.endpoint || '—'], ['Адрес в туннеле', t.address || '—'], ['MTU', t.mtu != null ? String(t.mtu) : '—'],
    ['Последнее рукопожатие', t.handshake != null ? agoText(num(t.handshake)) : '—', t.handshake != null && num(t.handshake) > 180 ? 'warn' : ''],
    ['Трафик', t.rx != null || t.tx != null ? '↓ ' + fmtBytes(t.rx) + ' · ↑ ' + fmtBytes(t.tx) : '—'],
    ['Время работы', t.uptime != null ? fmtUptime(t.uptime) : '—'],
    ['Используется для маршрутов', managed ? 'Да' : 'Нет', managed ? 'info' : '']
  ]) + use + cfgNote(), { desc: managed ? 'Через этот туннель идут все домены и сети из «Маршрутизации».' : 'Переключение переносит маршруты групп в Keenetic, сохраняет выбор в device.conf и отменяется целиком при любой ошибке.', right: headPill(up ? 'ok' : 'warn', up ? 'В сети' : 'Не в сети') }) +
    tunnelManagePanel(name, managed)[0] + tunnelProbePanel(name) + tunnelTrafficPanel(name) + tunnelManagePanel(name, managed)[1];
}
// Filled only by «Проверить сейчас»: the router does not do this in the background.
const tunLabel = n => { const t = ((st().wg && st().wg.interfaces) || []).find(x => x.name === n); return n + (t && t.description ? ' · ' + t.description : ''); };
// With several tunnels a list chooses its way: the provider or any tunnel.
function listViaSel(l, tuns, ok) {
  const cur = viaIs(l, 'bypass') ? 'bypass' : tuns.some(t => t.name === l.route) ? l.route : '';
  const opts = [['bypass', 'Провайдер (в обход VPN)']].concat(tuns.map(t => [t.name, tunLabel(t.name)]));
  if (!cur) opts.unshift(['', l.route ? 'через ' + l.route : 'без маршрута', true]);
  return sel('data-list-via="' + esc(l.name) + '"' + (ok && (cur || !l.route) ? '' : ' disabled'), 'Куда идёт «' + (l.description || l.name) + '»', opts, cur);
}
document.addEventListener('input', e => { const f = e.target.closest && e.target.closest('[data-form="tunnel-conf"]'); if (f && e.target.name === 'conf' && f.dataset.checked === '1') { f.dataset.checked = ''; $('tcPreview').innerHTML = ''; f.querySelector('[type=submit]').textContent = 'Проверить файл'; } });
async function wifiHostSet(fields, okMsg) {
  let x;
  try { x = await apiPost('wifi-host', fields); } catch (e) { toast('Ошибка: ' + e.message); return; }
  toast(x.ok ? (x.result === 'unchanged' ? 'Уже так' : okMsg) : 'Не сохранено: ' + errText(x));
  await load('wifi', true); render();
}
async function tunnelSubnet(name, op, subnet) {
  let x;
  try { x = await apiPost('tunnel-conf', { op: 'subnet-' + op, name: name, subnet: subnet }); }
  catch (e) { toast('Ошибка: ' + e.message); return; }
  toast(x.ok ? (x.result === 'unchanged' ? 'Уже так' : op === 'add' ? subnet + ' идёт через ' + name : subnet + ' убрана из ' + name) : 'Не сохранено: ' + errText(x));
  await load('lists', true); render();
}
// Long tunnel jobs report "info.key=value" lines and a last "result=" or "error=" line.
function tunnelJobText(out) {
  const lines = String(out || '').trim().split('\n'), last = lines[lines.length - 1] || '';
  const info = {}; lines.forEach(l => { const m = /^info\.([a-z]+)=(.*)$/.exec(l); if (m) info[m[1]] = m[2]; });
  if (/^result=/.test(last)) return 'Готово' + (info.name ? ': создан ' + info.name : '') + (info.endpoint ? ' · сервер ' + info.endpoint : '') + (info.address ? ' · адрес ' + info.address : '');
  if (/^error=/.test(last)) return 'Не выполнено: ' + errText({ error: last.slice(6) });
  return 'Проверяем новый сервер… до минуты';
}
async function tunnelJob(resultId, fields) {
  const show = text => { actionResult = { id: resultId, text: text }; render(); };
  render();
  let x;
  try { x = await apiPost('tunnel-conf', fields); } catch (e) { show('Ошибка: ' + e.message); return; }
  if (!x.ok) { show('Не выполнено: ' + errText(x)); return; }
  const deadline = Date.now() + 5 * 60 * 1000;
  let run = {};
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 3000));
    try { run = (await apiGet('control-data')).run || {}; } catch (e) { continue; }
    show(tunnelJobText(run.output));
    if (run.finished) break;
  }
  toast(run.finished && run.rc === 0 ? 'Готово' : run.finished ? 'Не выполнено' : 'Ещё выполняется, проверьте позже');
  await Promise.all([load('status', true), load('lists', true)]); render();
}
function tunnelConfSheet(mode, name) {
  openSheet(mode === 'create' ? 'Новый туннель' : 'Заменить конфигурацию · ' + name,
    '<div class="sheet-body"><form class="stack-form" data-form="tunnel-conf" data-mode="' + mode + '" data-name="' + esc(name || '') + '">' +
    (mode === 'create' ? '<input class="input" name="description" maxlength="64" placeholder="Название, например Германия-2" aria-label="Название туннеля">' : '') +
    '<label class="file-pick">' + ico('save') + '<span>Выбрать файл .conf</span><input type="file" name="file" accept=".conf,text/plain" data-conf-file></label>' +
    '<textarea class="input mono" name="conf" rows="7" spellcheck="false" autocomplete="off" aria-label="Текст конфигурации" placeholder="или вставьте текст: [Interface] PrivateKey = …"></textarea>' +
    '<div id="tcPreview"></div>' +
    '<p class="panel-desc">' + (mode === 'create' ? 'VWARD создаст туннель и дождётся ответа сервера. Если сервер не ответит, туннель удалится.' :
      'Сначала конфигурация проверяется на временном туннеле. Только если сервер ответил, она записывается в ' + esc(name) + ': маршруты и списки остаются на месте.') + ' Ключи не показываются и не пишутся в журналы.</p>' +
    '<button class="btn primary" type="submit">Проверить файл</button></form></div>');
}
function tunnelTrafficPanel(name) {
  const L = S.lists || {}, lists = (L.lists || []).filter(l => l.route === name), nets = (L.subnets || {})[name] || [];
  const netRows = nets.map(n => '<li class="row"><div class="row-main"><b class="mono">' + esc(n) + '</b></div><span class="row-acts">' + rowBtn('tsubnet', 'remove', n, 'close', 'Убрать ' + n + ' из туннеля') + '</span></li>').join('');
  return panel('Что идёт через туннель', (!S.lists ? empty('Загрузка…') :
      // Lists are changed in one place, «Доменные списки»: here only how many go this way.
      kv([['Доменные списки', lists.length ? String(lists.length) : 'нет', '', 'lists']]) +
      '<p class="panel-desc">Подсети: ' + (nets.length ? fmtInt(nets.length) : 'нет') + '</p>' + (nets.length ? '<ul class="rows">' + netRows + '</ul>' : '') +
      '<form class="inline-form" data-form="tunnel-subnet" data-name="' + esc(name) + '"><input class="input mono" name="subnet" placeholder="149.154.160.0/20" aria-label="Подсеть" autocomplete="off"><button class="btn" type="submit"' + (cfgOk() ? '' : ' disabled') + '>Добавить подсеть</button></form>') + resultBox('tunnel-traffic'),
    { desc: 'Списки доменов и подсети IPv4, которые Keenetic отправляет через этот туннель. Списки меняются в разделе «Доменные списки», подсети - здесь.' });
}
function tunnelManagePanel(name, managed) {
  const others = ((st().wg && st().wg.interfaces) || []).filter(t => t.name !== name);
  const del = managed ? '<p class="panel-desc">Этот туннель используется VWARD для маршрутов, его нельзя удалить. Сначала переключите маршруты на другой туннель.</p>' :
    (confirm && confirm.id === 'tunnel-delete' ? '<div class="confirm danger"><span>Удалить ' + esc(name) + '? Его списки и подсети перейдут: ' + esc(confirm.to === 'bypass' ? 'на провайдера' : confirm.to === 'vpn' ? 'в туннель VWARD' : confirm.to) + '. Ключи туннеля удалятся.</span><button class="btn small danger" type="button" data-act="confirm-yes">Удалить</button><button class="btn small" type="button" data-act="confirm-no">Отмена</button></div>' :
      '<dl class="kv">' + ctrlRow('Куда передать списки и подсети', sel('data-tunnel-del-to', 'Куда передать', [['vpn', 'Туннель VWARD'], ['bypass', 'Провайдер']].concat(others.filter(t => t.name !== prof().tunnel_interface).map(t => [t.name, tunLabel(t.name)])), 'vpn')) + '</dl>' +
      '<div class="panel-actions">' + btn('tunnel-delete', 'close', 'Удалить туннель', 'danger', cfgOk() ? '' : ' disabled') + '</div>');
  return [panel('Конфигурация', '<div class="panel-actions even">' + btn('tunnel-replace', 'refresh', 'Заменить конфигурацию', 'primary', cfgOk() ? '' : ' disabled') + '</div>' + resultBox('tunnel-conf'),
      { desc: 'Новый файл .conf от провайдера VPN записывается в этот же туннель: имя, маршруты и списки не меняются.' }),
    panel('Удаление', del, { desc: 'Перед удалением VWARD переносит списки и подсети туннеля, чтобы ничего не потерялось.' })];
}
// Snapshots of VWARD's settings: one a day automatically, or by the button.
function backupPanel() {
  const b = S.backups, list = (b && b.backups) || [], kinds = { manual: 'вручную', auto: 'автоматически', prerestore: 'перед восстановлением' };
  const rows = list.map(x => '<li class="row"><div class="row-main"><b>' + esc(fmtTime(x.created)) + '</b><small>' + esc(kinds[x.kind] || x.kind) + ' · ' + esc(fmtBytes(x.size)) + '</small>' +
    '</div>' +
    '<span class="row-acts"><a class="icon-btn" href="/cgi-bin/api.cgi?action=backup-download&amp;name=' + encodeURIComponent(x.name) + '" download aria-label="Скачать" title="Скачать">' + ico('save') + '</a>' +
    '<button class="icon-btn" type="button" data-backup-restore="' + esc(x.name) + '" aria-label="Восстановить" title="Восстановить"' + (cfgOk() ? '' : ' disabled') + '>' + ico('undo') + '</button></span>' +
    (confirm && confirm.id === 'backup-restore' && confirm.name === x.name ? '<div class="confirm danger"><span>Восстановить настройки VWARD на это время? Текущие сохранятся отдельной копией.</span><button class="btn small danger" type="button" data-act="confirm-yes">Восстановить</button><button class="btn small" type="button" data-act="confirm-no">Отмена</button></div>' : '') + '</li>').join('');
  return panel('Резервные копии', (!b ? empty('Загрузка…') : !b.ok ? empty(errText(b)) : list.length ? '<ul class="rows">' + rows + '</ul>' : empty('Копий пока нет')) +
    '<div class="panel-actions">' + btn('backup-create', 'archive', 'Создать копию сейчас', '', cfgOk() ? '' : ' disabled') + '</div>' + resultBox('backup'),
    { desc: 'Настройки VWARD, доменные списки, Smart DNS, туннели и вход AdGuard Home. Копия делается раз в сутки сама, хранятся последние 7. Скачанный файл - без ключей туннелей, паролей и конфигурации роутера: они остаются в копии на роутере и возвращаются при восстановлении.' });
}
// AdGuard Home's own ad settings, changed through its API (the rest stays in its web UI).
function aghSettingsPanel(a) {
  if (!S.ads || !a.agh_connected) return '';
  const g = S.agh;
  if (!g) return panel('AdGuard Home', empty('Загрузка…'));
  if (!g.ok) return panel('AdGuard Home', empty(errText(g)));
  const f = g.filtering || {}, fl = f.filters || [], sv = g.services, on = cfgOk() || true;
  const row = (key, label, val, hint, extra) => val == null ? '' : ctrlRow(label, sw('data-agh="' + key + '"', val, label), hint);
  return panel('AdGuard Home', '<dl class="kv">' +
      row('protection', 'Защита AdGuard Home', g.protection, g.protection ? 'блокирует по всем фильтрам и правилам' : 'выключена - реклама не блокируется') +
      confirmBox('agh-protection-off', 'Выключить защиту AdGuard Home? Реклама и трекеры перестанут блокироваться на всех устройствах.', 'Выключить', true) +
      (f.enabled == null ? '' : row('filtering', 'Фильтрация по спискам', f.enabled, fmtInt(fl.filter(x => x.enabled).length) + ' из ' + fmtInt(fl.length) + ' списков включены')) +
      (f.interval == null ? '' : ctrlRow('Обновлять списки', sel('data-agh-interval', 'Обновлять списки', [[0, 'не обновлять'], [1, 'каждый час'], [12, 'каждые 12 ч'], [24, 'раз в сутки'], [72, 'раз в 3 дня'], [168, 'раз в неделю']], f.interval))) +
      row('safebrowsing', 'Безопасная навигация', g.safebrowsing, 'блокирует фишинг и вредоносные сайты') +
      row('parental', 'Родительский контроль', g.parental, 'блокирует сайты для взрослых') +
      row('safesearch', 'Безопасный поиск', g.safesearch, 'строгий режим в поисковиках и YouTube') + '</dl>' +
      kv([f.filters ? ['Фильтры', fmtInt(fl.filter(x => x.enabled).length) + ' из ' + fmtInt(fl.length) + ' · ' + fmtInt(fl.reduce((n, x) => n + (x.enabled ? x.rules : 0), 0)) + ' правил', '', 'd-aghfilters'] : null,
        sv ? ['Блокировка сервисов', sv.blocked.length ? fmtInt(sv.blocked.length) + ' заблокировано' : 'нет', '', 'd-aghservices'] : null]) + resultBox('agh'),
    { desc: 'Настройки блокировки самого AdGuard Home' + (g.version ? ' ' + g.version : '') + '. Меняются сразу; остальное (DNS-серверы, клиенты, журнал) - в его веб-интерфейсе.' });
}
async function aghSet(fields, okMsg) {
  let x;
  try { x = await apiPost('ads-control', Object.assign({ op: 'agh' }, fields)); }
  catch (e) { toast('Ошибка: ' + e.message); return; }
  const err = /ERROR=([a-z_]+)/.exec(x.result || '');
  toast(x.ok ? okMsg : 'Не выполнено: ' + (err ? errText({ error: err[1] }) : errText(x)));
  await load('agh', true); render();
}
// AdGuard Home asks for a login: VWARD keeps it (root-only file) after AdGuard accepts it.
function aghConnectPanel(a) {
  if (!S.ads) return '';
  if (a.agh_connected) return panel('Подключение к AdGuard Home', (confirmBox('agh-off', 'Отключить VWARD от AdGuard Home? Статистика и журнал запросов перестанут показываться.', 'Отключить', true) ||
    '<div class="panel-actions">' + btn('ask', 'undo', 'Отключить', '', ' data-confirm="agh-off"') + '</div>'), { desc: 'VWARD читает статистику и журнал запросов AdGuard Home под сохранённым логином.' });
  return panel('Подключение к AdGuard Home', '<form class="inline-form" data-form="agh-connect"><input class="input" name="login" placeholder="логин AdGuard Home" aria-label="Логин AdGuard Home" autocomplete="username"><input class="input" name="password" type="password" placeholder="пароль" aria-label="Пароль AdGuard Home" autocomplete="current-password"><button class="btn primary" type="submit">Подключить</button></form>',
    { desc: 'Логин и пароль от веб-интерфейса AdGuard Home. VWARD сначала проверит их у AdGuard Home, потом сохранит в защищённый файл на роутере.' });
}
function tunnelProbePanel(name) {
  const r = S.tprobe[name], ex = r && r.exit, sv = (r && r.server) || {}, pg = (r && r.ping) || {};
  const place = ex ? [ex.city, ex.region, ex.country].filter(Boolean).join(', ') : '';
  const body = !r ? '' : r.busy ? empty('Проверка… до 10 секунд') : !r.ok ? empty(errText(r)) : kv([
    ['Внешний IP', ex ? ex.ip : 'не определён', ex ? '' : 'warn'],
    ['Местоположение', place || '—'],
    ['Провайдер', (ex && ex.org) || '—'],
    ['Пинг до ' + (pg.target || '1.1.1.1'), pg.avg_ms != null ? Math.round(pg.avg_ms) + ' мс' : 'нет ответа', pg.avg_ms != null ? '' : 'warn'],
    ['Потери', pg.loss != null ? pg.loss + '%' : '—', pg.loss ? (pg.loss >= 50 ? 'crit' : 'warn') : ''],
    ['Сервер', (sv.host || '—') + (sv.port ? ':' + sv.port : '')],
    ['Обфускация AmneziaWG', sv.awg ? 'Включена' : 'Выключена'],
    ['Keepalive', sv.keepalive ? sv.keepalive + ' с' : 'выключен']
  ]) + '<p class="panel-desc">Проверено в ' + esc(r.at) + '</p>';
  return panel('Проверка туннеля', body + '<div class="panel-actions">' + btn('tunnel-probe', 'check', 'Проверить сейчас', 'primary', ' data-name="' + esc(name) + '"' + (r && r.busy ? ' disabled' : '')) + '</div>',
    { desc: 'Внешний адрес и страна выхода, пинг и потери внутри туннеля, настройки сервера. Запускается только по кнопке.' });
}
const wifiHost = mac => { const c = ((S.wifi && S.wifi.clients) || []).find(x => x.mac === mac); return (c && c.host) || null; };
const wifiName = mac => { const h = wifiHost(mac); return (h && (h.name || h.hostname)) || mac; };
const segPrev = {};
// Auto / 2.4 / 5 GHz as one slider: the thumb sits on the band Keenetic has
// pinned (or on the one being confirmed) and glides to a new choice.
function segSlider(mac, ops, on) {
  const b = ((S.wifi && S.wifi.binds) || {})[String(mac).toLowerCase()];
  const cur = b === '2g' ? 'bind-2g' : b === '5g' ? 'bind-5g' : 'auto';
  const shown = confirm && confirm.id === 'wifi-bind' ? confirm.op : cur;
  const to = Math.max(0, ops.findIndex(o => o[0] === shown)), from = segPrev[mac] != null ? segPrev[mac] : to;
  segPrev[mac] = to;
  return '<div class="seg-slider' + (on ? '' : ' off') + '" role="radiogroup" aria-label="Диапазон" data-i="' + from + '" data-to="' + to + '"><i class="seg-thumb"></i>' +
    ops.map(o => '<button type="button" role="radio" data-wifi-bind="' + o[0] + '" aria-checked="' + (o[0] === shown) + '"' + (on ? '' : ' disabled') + '>' + o[1] + '</button>').join('') + '</div>';
}
function wifiClientPage(mac) {
  const c = ((S.wifi && S.wifi.clients) || []).find(x => x.mac === mac) || { mac: mac };
  const ctl = S.config && S.config.wifi ? S.config.wifi.CONTROL_ENABLED : S.wifi && S.wifi.control_enabled;
  const ops = [['auto', 'Авто', 'WIFI_BAND_AUTO', 'Авто'], ['bind-2g', '2.4 ГГц', 'WIFI_BIND_2G', 'Только 2.4 ГГц'], ['bind-5g', '5 ГГц', 'WIFI_BIND_5G', 'Только 5 ГГц']];
  const h = c.host || {}, deny = h.access === 'deny';
  const device = panel('Устройство', '<form class="inline-form" data-form="wifi-name" data-mac="' + esc(mac) + '"><input class="input" name="name" maxlength="64" value="' + esc(h.name || '') + '" placeholder="' + esc(h.hostname || 'Имя устройства') + '" aria-label="Имя устройства"><button class="btn" type="submit"' + (cfgOk() ? '' : ' disabled') + '>' + (h.registered ? 'Переименовать' : 'Сохранить имя') + '</button></form>' +
      '<dl class="kv">' + ctrlRow('Доступ в интернет', sw('data-wifi-access="' + esc(mac) + '"', !deny, 'Доступ в интернет для ' + wifiName(mac), !cfgOk()), deny ? 'запрещён: устройство видит только домашнюю сеть' : 'разрешён') + '</dl>' +
      confirmBox('wifi-deny', 'Запретить устройству «' + wifiName(mac) + '» выход в интернет? Домашняя сеть останется доступной.', 'Запретить', true) +
      kv([['MAC', mac], ['IP-адрес', h.ip || '—'], ['Имя в сети', h.hostname || '—'], ['Зарегистрировано в Keenetic', h.registered ? 'Да' : 'Нет'],
        h.ssid ? ['Сеть Wi-Fi', h.ssid] : null, h.rssi != null ? ['Сигнал', h.rssi + ' дБм', num(h.rssi) < -75 ? 'warn' : ''] : null,
        h.txrate != null ? ['Скорость', h.txrate + ' Мбит/с'] : null, h.uptime != null ? ['В сети', fmtUptime(h.uptime)] : null,
        h.rx != null || h.tx != null ? ['Трафик', '↓ ' + fmtBytes(h.rx) + ' · ↑ ' + fmtBytes(h.tx)] : null]) + cfgNote(),
    { desc: 'Имя сохраняется в Keenetic и регистрирует устройство. Запрет интернета действует на всё устройство.' });
  return device + panel('Диапазоны Wi-Fi', kv([['Сейчас', bandText(c.band)], ['Состояние', recText(c) === 'Норма' ? 'без замечаний' : recText(c), c.health === 'WARNING' ? 'warn' : '', null, '', WIFI_REASONS[c.reason] || ''], ['Переходов за окно', fmtInt(c.switches)], ['Слабый 5 ГГц', fmtInt(c.weak_5g) + ' раз'], ['Мин. сигнал 5 ГГц', c.min_5g_rssi && c.min_5g_rssi !== '-' ? c.min_5g_rssi + ' дБм' : '—']])) +
    panel('Диапазон для устройства', segSlider(mac, ops, ctl) +
      (ctl ? '' : '<p class="panel-desc">Закрепление выключено: включите «Ручное управление» в разделе «Wi-Fi клиенты».</p>') +
      (confirm && confirm.id === 'wifi-bind' ? '<div class="confirm"><span>Применить «' + esc(ops.find(o => o[0] === confirm.op)[3]) + '» для ' + esc(mac) + '? Перед изменением сохранится резервная копия настроек, при ошибке изменение откатится.</span><button class="btn small primary" type="button" data-act="confirm-yes">Применить</button><button class="btn small" type="button" data-act="confirm-no">Отмена</button></div>' : '') + resultBox('wifi'),
    { desc: 'Закрепление через штатную настройку Keenetic для зарегистрированных устройств.' });
}
function compPage(c) {
  const x = (plat().components || {})[c.id] || {}, g = graphOf(c.id), on = compOn(c.id), core = !!(g && g.core);
  const all = cfg().components || [];
  const deps = g ? g.depends_on : [], needs = g ? g.requires_running : [];
  const users = all.filter(d => d.depends_on.includes(c.id) || d.uses.includes(c.id));
  const off = compCascade(c.id, true), onWith = compCascade(c.id, false);
  const stale = all.filter(d => d.uses.includes(c.id) && compOn(d.id) && !off.includes(d.id)).map(d => d.id);
  const sw1 = core ? '<span class="num">Всегда</span>' : sw('data-comp="' + c.id + '"', on, 'Компонент «' + c.name + '» включён', !cfgOk() || !g);
  return panel(c.name, '<dl class="kv">' + ctrlRow('Компонент включён', sw1, core ? 'базовый компонент: без него VWARD не работает' : on ? '' : 'файлы установлены, но компонент не запускается') + '</dl>' +
      (confirmBox('comp-off', 'Выключить «' + c.name + '»?' + (off.length ? ' Вместе с ним остановятся: ' + compNames(off) + '.' : '') + (stale.length ? ' На устаревших данных продолжат работать: ' + compNames(stale) + '.' : '') + ' Файлы и настройки останутся, включить можно в любой момент.', 'Выключить', true) ||
       confirmBox('comp-on', 'Включить «' + c.name + '»? Вместе с ним включатся: ' + compNames(onWith) + '.', 'Включить')) +
      kv([['Запуск', c.when], ['Версия', x.release || plat().version || '—'], ['Установлен', fmtStamp(x.installed_at) || '—'], ['Обновление', x.update_id || '—'],
        g ? ['Зависимости', (deps.length ? 'нужны ' + deps.length : 'не нужны другие') + ' · ' + (users.length ? 'используют ' + users.length : 'никто не использует'), '', 'deps-' + c.id] : null]) +
      '<div class="panel-actions even">' + (c.page ? '<button class="btn" type="button" data-go="' + c.page + '">Открыть раздел</button>' : '') + btn('open-log', 'logs', 'Журнал', '', ' data-log-tab="' + c.log + '"') + '</div>' + cfgNote(),
    { desc: c.desc, right: headPill(!on ? 'warn' : x.health === 'PASS' ? 'ok' : '', !on ? 'Выключен' : x.health === 'PASS' ? 'Норма' : 'Нет данных') });
}
function depsPage(c) {
  const g = graphOf(c.id), all = cfg().components || [];
  const link = (id, note) => '<li class="row link" role="button" tabindex="0" data-go="c-' + id + '"><div class="row-main"><b>' + esc((comp(id) || {}).name || id) + '</b>' + (note ? '<small>' + esc(note) + '</small>' : '') + '</div>' + (compOn(id) ? '' : '<span class="pill warn">Выключен</span>') + ico('chevron', 'chev') + '</li>';
  if (!g) return panel('Зависимости', empty('Загрузка…'));
  const deps = g.depends_on, needs = g.requires_running, users = all.filter(d => d.depends_on.includes(c.id) || d.uses.includes(c.id));
  return panel('Нужны ему', deps.length ? '<ul class="rows">' + deps.map(id => link(id, needs.includes(id) ? 'должен работать' : 'нужны его файлы')).join('') + '</ul>' : empty('Работает сам по себе')) +
    panel('Используют его', users.length ? '<ul class="rows">' + users.map(d => link(d.id, d.requires_running.includes(c.id) ? 'остановится вместе с ним' : d.depends_on.includes(c.id) ? 'берёт его файлы' : 'берёт его данные')).join('') + '</ul>' : empty('Никто'),
      { desc: 'Выключение компонента учитывает эти связи.' });
}

/* ---------- Навигация ---------- */
// A wide screen holds every section in the bar; a phone holds the chosen ones plus «Ещё».
const WIDE = window.matchMedia('(min-width: 900px)');
const barIds = () => WIDE.matches ? PAGES.map(p => p.id) : tabIds;
function tabsHtml() {
  const cur = navId(current);
  if (WIDE.matches) return barIds().map(id => '<button class="tab" type="button" data-tab="' + id + '"' + (id === cur ? ' aria-current="page"' : '') + '>' + ico(page(id).icon) + '<span>' + SHORT[id] + '</span></button>').join('');
  return tabIds.map(id => '<button class="tab" type="button" data-tab="' + id + '"' + (id === cur ? ' aria-current="page"' : '') + '>' + ico(page(id).icon) + '<span>' + SHORT[id] + '</span></button>').join('') +
    '<button class="tab" type="button" data-tab="more"' + (tabIds.includes(cur) ? '' : ' aria-current="page"') + '>' + ico('more') + '<span>Ещё</span></button>';
}
function renderNav() {
  const cur = navId(current), warnPages = new Set(notifications().map(n => navId(n.to)));
  $('tabbar').innerHTML = tabsHtml();
  $('tabbar').querySelectorAll('[data-tab]').forEach(t => { if (warnPages.has(t.dataset.tab) && t.dataset.tab !== cur) t.insertAdjacentHTML('beforeend', '<span class="dot" aria-label="Есть уведомление"></span>'); });
  document.documentElement.style.setProperty('--tabs', WIDE.matches ? barIds().length : tabIds.length + 1);
  const n = notifications().length;
  // Good news only (a new version): a calm accent badge instead of the red one.
  const onlyNews = n && notifications().every(x => x.sev === 'news');
  $('bellBtn').innerHTML = ico('bell') + (n ? '<span class="badge' + (onlyNews ? ' news' : '') + '">' + n + '</span>' : '');
  $('bellBtn').setAttribute('aria-label', n ? 'Уведомления: ' + n : 'Уведомления');
}
// Only the blocks whose markup changed are replaced: the rest keep their scroll, focus and open details.
let rendered = null;
function patchContent(html, whole) {
  const box = $('content'), t = document.createElement('template');
  t.innerHTML = html;
  ddEnhance(t.content);
  t.content.querySelectorAll('.meter i[data-width]').forEach(i => { i.style.width = Math.max(0, Math.min(100, Number(i.dataset.width))) + '%'; });
  const fresh = [...t.content.children], old = [...box.children];
  if (whole || fresh.length !== old.length) box.replaceChildren(t.content);
  else fresh.forEach((n, i) => { if (!old[i].isEqualNode(n)) old[i].replaceWith(n); });
  // A three-way slider is drawn where it was and then moved, so the thumb glides.
  requestAnimationFrame(() => box.querySelectorAll('.seg-slider[data-to]').forEach(el => { if (el.dataset.i !== el.dataset.to) el.dataset.i = el.dataset.to; }));
}
/* ---------- Выпадающие списки ----------
   A native <select> opens a full-screen picker on phones.  Each one gets a
   button and a menu right under it; the select stays (hidden) as the value
   holder, so forms and the change handlers work as before. */
function ddLabel(sel) { const o = sel.options[sel.selectedIndex]; return o ? o.textContent : ''; }
function ddEnhance(root) {
  root.querySelectorAll('select.input:not([data-dd])').forEach(sel => {
    sel.setAttribute('data-dd', '1'); sel.classList.add('dd-native'); sel.tabIndex = -1;
    const b = document.createElement('button');
    b.type = 'button'; b.className = sel.className.replace('dd-native', '').trim() + ' dd-btn';
    b.setAttribute('aria-haspopup', 'listbox'); b.setAttribute('aria-expanded', 'false');
    if (sel.getAttribute('aria-label')) b.setAttribute('aria-label', sel.getAttribute('aria-label'));
    if (sel.disabled) b.disabled = true;
    b.innerHTML = '<span class="dd-val"></span>' + ico('chevron', 'dd-chev');
    b.firstChild.textContent = ddLabel(sel);
    sel.after(b);
  });
}
let ddOpen = null;
function ddClose(focus) {
  const m = $('ddMenu'); if (m) m.remove();
  if (ddOpen) { ddOpen.btn.setAttribute('aria-expanded', 'false'); if (focus) ddOpen.btn.focus(); }
  ddOpen = null;
}
function ddShow(btn) {
  const sel = btn.previousElementSibling;
  if (!sel || sel.tagName !== 'SELECT') return;
  ddClose();
  const m = document.createElement('div');
  m.id = 'ddMenu'; m.setAttribute('role', 'listbox');
  m.innerHTML = [...sel.options].map((o, i) => '<button type="button" role="option" class="dd-opt" data-dd-i="' + i + '" aria-selected="' + (i === sel.selectedIndex) + '"' + (o.disabled ? ' disabled' : '') + '>' + ico('check', 'dd-mark') + '<span>' + esc(o.textContent) + '</span></button>').join('');
  document.body.appendChild(m);
  const r = btn.getBoundingClientRect(), vw = document.documentElement.clientWidth, vh = window.innerHeight;
  const w = Math.min(Math.max(r.width, 200), vw - 16);
  m.style.width = w + 'px';
  m.style.left = Math.max(8, Math.min(r.left + r.width - w, vw - w - 8)) + 'px';
  const h = m.offsetHeight, below = vh - r.bottom - 8, above = r.top - 8;
  m.style.top = (h <= below || below >= above ? r.bottom + 4 : Math.max(8, r.top - Math.min(h, above) - 4)) + 'px';
  m.style.maxHeight = Math.max(160, h <= below || below >= above ? below : above) + 'px';
  ddOpen = { btn: btn, sel: sel };
  btn.setAttribute('aria-expanded', 'true');
  const cur = m.querySelector('[aria-selected="true"]') || m.querySelector('.dd-opt:not([disabled])');
  if (cur) { cur.focus({ preventScroll: true }); cur.scrollIntoView({ block: 'nearest' }); }
}
function ddPick(i) {
  if (!ddOpen) return;
  const { btn, sel } = ddOpen;
  ddClose(true);
  if (sel.selectedIndex === i) return;
  sel.selectedIndex = i;
  btn.firstChild.textContent = ddLabel(sel);
  sel.dispatchEvent(new Event('change', { bubbles: true }));
}
document.addEventListener('click', e => {
  const opt = e.target.closest('.dd-opt');
  if (opt) { e.stopPropagation(); ddPick(Number(opt.dataset.ddI)); return; }
  const b = e.target.closest('.dd-btn');
  if (b) { e.stopPropagation(); if (ddOpen && ddOpen.btn === b) ddClose(); else ddShow(b); return; }
  if (ddOpen && !e.target.closest('#ddMenu')) ddClose();
}, true);
document.addEventListener('keydown', e => {
  if (!ddOpen) {
    const b = e.target.closest && e.target.closest('.dd-btn');
    if (b && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) { e.preventDefault(); ddShow(b); }
    return;
  }
  const opts = [...document.querySelectorAll('#ddMenu .dd-opt:not([disabled])')], at = opts.indexOf(document.activeElement);
  if (e.key === 'Escape') { e.preventDefault(); ddClose(true); }
  else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); const n = opts[(at + (e.key === 'ArrowDown' ? 1 : -1) + opts.length) % opts.length]; if (n) n.focus(); }
  else if (e.key === 'Tab') ddClose();
});
window.addEventListener('resize', () => ddClose());
window.addEventListener('scroll', e => { if (ddOpen && !(e.target && e.target.closest && e.target.closest('#ddMenu'))) ddClose(); }, true);

function render() {
  const p = page(current);
  $('pageTitle').textContent = p.title;
  document.title = p.title + ' · VWARD';
  const back = $('backBtn');
  back.classList.toggle('detail', !!p.parent);
  back.hidden = current === 'overview';
  back.setAttribute('aria-label', p.parent ? 'Назад: ' + page(p.parent).title : 'Назад к обзору');
  const html = current.startsWith('c-') ? compPage(comp(current.slice(2))) : current.startsWith('deps-') ? depsPage(comp(current.slice(5))) : current.startsWith('l-') ? listPage(current.slice(2)) : current.startsWith('t-') ? tunnelPage(current.slice(2)) : current.startsWith('w-') ? wifiClientPage(current.slice(2)) : RENDER[current]();
  patchContent(html, rendered !== current);
  rendered = current;
  document.querySelectorAll('.tabbar.preview').forEach(t => t.style.setProperty('--tabs', tabIds.length + 1));
  renderNav();
}
// Every section is a browser history entry, so the back button and the back gesture stay inside VWARD.
// mode: 'pop' - called from history, 'replace' - no new entry.
const histDepth = () => (history.state && history.state.d) || 0;
function go(id, key, mode) {
  if (!page(id)) id = 'overview';
  if (mode !== 'pop') {
    const sheet = history.state && history.state.sheet;
    if (mode === 'replace' || sheet) history.replaceState({ p: id, d: histDepth() }, '', '#' + id);
    else if (id !== current) history.pushState({ p: id, d: histDepth() + 1 }, '', '#' + id);
  }
  current = id; editing = false; confirm = null; actionResult = null;
  closeLayer(true); render(); window.scrollTo(0, 0);
  if (key) { const row = [...document.querySelectorAll('[data-key]')].find(r => r.dataset.key === key); if (row) { row.scrollIntoView({ block: 'center' }); row.classList.add('flash'); } }
  refreshPage();
}
async function refreshPage() {
  const id = current, keys = DATA_FOR(id).slice();
  if (id === 'logs') { loadLog(logTab); return; }
  if (id.startsWith('t-')) keys.push('status', 'lists');
  if (id.startsWith('l-')) keys.push('listd');
  if (id.startsWith('w-')) keys.push('wifi');
  if (id === 'd-https' || id === 'ads') keys.push('https');
  if (id === 'd-notes') notesVersions().forEach(v => loadNotes(v));
  if (id === 'd-querylog') keys.push('qlog');
  if (id === 'd-cron') keys.push('cron');
  if (id === 'd-review') keys.push('review');
  if (id === 'd-blocked') keys.push('blocked');
  // Each answer is drawn as soon as it arrives: a slow source does not hold the others back.
  const draw = () => { if (current === id && !editing && !document.activeElement.matches('input,select,textarea')) render(); };
  await Promise.all(keys.map(k => load(k).then(draw, draw)));
}
async function loadLog(tab, force) {
  if (!force && S.logs[tab] != null) { render(); }
  try { S.logs[tab] = await apiText('log', { name: tab, count: 200 }); }
  catch (e) { S.logs[tab] = 'Журнал недоступен: ' + e.message; }
  if (current === 'logs' && logTab === tab) { const b = $('logBox'); if (b) b.textContent = S.logs[tab]; else render(); }
}

/* ---------- Всплывающие панели ---------- */
function closeLayer(fromHistory) {
  const open = !!$('layer').innerHTML;
  loginOpen = false; $('layer').innerHTML = '';
  if (open && !fromHistory && history.state && history.state.sheet) history.back();
  ['searchBtn', 'bellBtn'].forEach(b => $(b).setAttribute('aria-expanded', 'false'));
}
// An open sheet is a history entry too: «back» closes it instead of leaving the section.
function openSheet(title, body, cls, btnId) {
  closeLayer(true);
  if (!(history.state && history.state.sheet)) history.pushState({ p: current, d: histDepth() + 1, sheet: 1 }, '', '#' + current);
  $('layer').innerHTML = '<div class="scrim" data-act="close"></div><div class="sheet ' + (cls || '') + '" role="dialog" aria-label="' + esc(title || 'Поиск') + '">' + (title ? '<div class="sheet-head"><h2>' + esc(title) + '</h2><button class="icon-btn" type="button" data-act="close" aria-label="Закрыть">' + ico('close') + '</button></div>' : '') + body + '</div>';
  ddEnhance($('layer'));
  if (btnId) $(btnId).setAttribute('aria-expanded', 'true');
}
// Only registered devices may open VWARD, and this one is not.
function showDeviceBlocked() {
  cacheDrop();
  if (document.getElementById('deviceBlocked')) return;
  document.body.insertAdjacentHTML('beforeend', '<div id="deviceBlocked" class="blocked-screen" role="alertdialog" aria-label="Устройство не зарегистрировано"><div class="blocked-card">' + ico('lock') +
    '<h2>Устройство не зарегистрировано</h2><p>VWARD открывается только с устройств, зарегистрированных в Keenetic.</p>' +
    '<p>Зарегистрируйте это устройство в веб-интерфейсе роутера: «Список устройств» → устройство → «Зарегистрировать», затем обновите страницу.</p>' +
    '<div class="panel-actions"><a class="btn" href="http://' + esc(location.hostname) + '/" target="_blank" rel="noopener">' + ico('external') + 'Открыть Keenetic</a><button class="btn primary" type="button" data-act="page-reload">' + ico('refresh') + 'Обновить</button></div></div></div>');
}
function showLogin() {
  cacheDrop();
  if (loginOpen) return;
  openSheet('Вход в VWARD', '<div class="sheet-body"><form class="inline-form" data-form="login"><input class="input" name="login" placeholder="логин Keenetic" aria-label="Логин" autocomplete="username"><input class="input" name="password" type="password" placeholder="пароль" aria-label="Пароль" autocomplete="current-password"><button class="btn primary" type="submit">Войти</button></form><p class="panel-desc">Логин и пароль от веб-интерфейса роутера.</p></div>');
  loginOpen = true;
}
function openNotes() {
  const n = notifications();
  openSheet('Уведомления', '<div class="sheet-body">' + (n.length ? n.map(x => '<button class="note-item" type="button" data-go="' + x.to + '"><span class="sev ' + x.sev + '">' + ico(x.icon || 'alert') + '</span><span><b>' + esc(x.title) + '</b><small>' + esc(x.text) + '</small></span></button>').join('') : empty('Всё работает штатно')) + '</div>', '', 'bellBtn');
}
const SEARCH_INDEX = [
  ['system', 'Модель'], ['system', 'KeeneticOS'], ['system', 'Веб-интерфейс Keenetic'], ['system', 'Версия VWARD'], ['system', 'Компоненты'], ['system', 'Диагностика'], ['system', 'Файлы'], ['system', 'Свободно'],
  ['wan', 'Интерфейс'], ['wan', 'IPv4'], ['wan', 'Шлюз'], ['wan', 'Восстанавливать автоматически'], ['wan', 'Проверять'],
  ['settings', 'Только зарегистрированные устройства'], ['vpn', 'Автоматическая защита'], ['vpn', 'Трафик списков'], ['vpn', 'Проверка туннеля'],
  ['d-smartdns', 'Защита Smart DNS'],
  ['routes', 'Туннель для маршрутов'], ['routes', 'AdaptiveAuto'], ['routes', 'Автоопределение категории'], ['routes', 'Проверяемые сервисы'], ['routes', 'Мои домены'], ['routes', 'Всегда через VPN'], ['routes', 'Категории доменов'], ['routes', 'IP-категории'], ['routes', 'Группа маршрутизации'],
  ['wifi', 'Сбор данных'], ['wifi', 'Ручное управление'], ['wifi', 'Домашний сегмент'], ['wifi', 'Окно анализа'], ['wifi', 'Слабый сигнал 5 ГГц'],
  ['ads', 'Настройки AdGuard Home'], ['ads', 'Последняя проверка'], ['ads', 'Правила в AdGuard Home'], ['ads', 'Журнал запросов'], ['ads', 'На проверке'], ['ads', 'Категории блокировки'], ['ads', 'Не опубликовано'], ['ads', 'Мои правила'], ['ads', 'Источники'], ['ads', 'HTTPS-фильтр'], ['ads', 'Режим работы'],
  ['u-vward', 'Установка обновлений'], ['u-vward', 'Время установки'], ['u-vward', 'Интервал проверки'], ['u-vward', 'Канал'],
  ['settings', 'Адрес VWARD'], ['settings', 'Тема'], ['u-vward', 'Версия'], ['d-diag', 'Задания по расписанию'], ['settings', 'Вход по учётной записи Keenetic'], ['settings', 'Разделы на панели']
];
function openSearch() {
  openSheet('', '<div class="search-box">' + ico('search') + '<input id="searchInput" placeholder="Раздел, параметр или компонент" aria-label="Поиск по VWARD" autocomplete="off"><button class="icon-btn" type="button" data-act="close" aria-label="Закрыть">' + ico('close') + '</button></div><div class="sheet-body" id="searchResults"></div>', 'search', 'searchBtn');
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
  actionResult = null; render();
  try {
    const x = await apiPost(action, fields);
    toast(x.ok ? okMsg : 'Не выполнено: ' + errText(x));
    return x;
  } catch (e) { toast('Ошибка: ' + e.message); return null; }
  finally { render(); }
}
const CONFIRMED = {
  'ext-upgrade': c => { const p = ((S.ext && S.ext.packages) || []).find(x => x.name === c.pkg); extOp('upgrade', c.pkg, p && p.critical ? 'EXT_UPGRADE_CRITICAL' : 'EXT_UPGRADE'); },
  'fw-channel': c => cfgSet({ op: 'firmware', target: 'channel', value: c.value, confirm: 'FIRMWARE_CHANNEL_TEST' }, 'Канал прошивки: ' + fwChannel(c.value), ['ext']),
  'route-reconcile': () => runLong('routes', 'control', { op: 'route-reconcile', confirm: 'ROUTE_RECONCILE' }, 'control-data', 'Маршруты сверены').then(() => load('route', true)).then(render),
  'policy-refresh': () => runLong('routes', 'control', { op: 'policy-refresh', confirm: 'POLICY_REFRESH' }, 'control-data', 'IP-категории обновлены').then(() => load('route', true)).then(render),
  'update-apply': () => updateOp('apply', 'APPLY_UPDATE'),
  'update-retry': () => updateOp('retry', 'RETRY_UPDATE'),
  'update-rollback': () => updateOp('rollback', 'ROLLBACK_UPDATE'),
  'update-recover': () => updateOp('recover', 'RECOVER_UPDATE'),
  'ads-publish': () => runAction('ads', 'ads-control', { op: 'enqueue', job: 'publish', confirm: 'ADS_PUBLISH' }, 'Публикация поставлена в очередь').then(() => load('ads', true)).then(render),
  'https-start': () => runAction('https', 'ads-https-control', { op: 'start', confirm: 'HTTPS_START' }, 'HTTPS-фильтр запущен').then(() => load('https', true)).then(render),
  'https-ca': () => runAction('https', 'ads-https-control', { op: 'ca-init', confirm: 'HTTPS_CA_INIT' }, 'Сертификат создан').then(() => load('https', true)).then(render),
  'wifi-deny': c => wifiHostSet({ op: 'access', mac: c.mac, value: 'deny', confirm: 'WIFI_ACCESS_DENY' }, 'Интернет для устройства запрещён'),
  'backup-restore': c => apiPost('backup-control', { op: 'restore', name: c.name, confirm: 'BACKUP_RESTORE' }).then(x => { toast(x.ok ? 'Настройки восстановлены' : 'Не восстановлено: ' + errText(x)); return Promise.all(['backups', 'config', 'security', 'status'].map(k => load(k, true))); }, e => toast('Ошибка: ' + e.message)).then(render),
  'agh-protection-off': () => aghSet({ setting: 'protection', value: '0', confirm: 'AGH_PROTECTION_OFF' }, 'Защита AdGuard Home выключена'),
  'agh-filter-remove': c => aghSet({ setting: 'filter-remove', url: c.url, confirm: 'AGH_FILTER_REMOVE' }, 'Список удалён'),
  'agh-off': () => apiPost('agh-auth', { op: 'disconnect', confirm: 'AGH_DISCONNECT' }).then(x => { toast(x.ok ? 'AdGuard Home отключён' : 'Не отключено: ' + errText(x)); return load('ads', true); }).then(render, () => render()),
  'auth-off': () => apiPost('auth', { op: 'disable', confirm: 'CONSOLE_AUTH_DISABLE' }).then(x => { toast(x.ok ? 'Вход выключен' : 'Не выключено: ' + errText(x)); return Promise.all([load('auth', true), load('security', true)]); }).then(render, () => render()),
  'ads-autopub': () => adsSetting('AUTO_PUBLISH', '1').then(() => load('adspub', true)).then(render),
  'feed-dev': () => cfgSet({ op: 'update-feed', target: 'dev', confirm: 'UPDATE_FEED_DEV' }, 'Канал: Dev'),
  'comp-off': () => { const id = current.slice(2); return cfgSet({ op: 'component', target: id, value: '0', confirm: 'COMPONENT_DISABLE' }, '«' + comp(id).name + '» выключен', ['status']); },
  'comp-on': () => { const id = current.slice(2); return cfgSet({ op: 'component', target: id, value: '1' }, '«' + comp(id).name + '» включён', ['status']); },
  'tunnel-delete': c => { const name = current.slice(2); return apiPost('tunnel-conf', { op: 'delete', name: name, target: c.to, confirm: 'TUNNEL_DELETE' }).then(x => { toast(x.ok ? name + ' удалён' : 'Не удалено: ' + errText(x)); return Promise.all([load('status', true), load('lists', true)]).then(() => { if (x.ok) go('vpn', null, 'replace'); else render(); }); }, e => { toast('Ошибка: ' + e.message); render(); }); },
  'route-tunnel': c => { toast('Переключаем маршруты на ' + c.to + '…'); return cfgSet({ op: 'tunnel', target: c.to, confirm: 'TUNNEL_SWITCH' }, 'Маршруты VWARD идут через ' + c.to, ['status', 'security', 'route']); },
  'tunnel-use': () => { const name = current.slice(2); toast('Переключаем маршруты на ' + name + '…'); return cfgSet({ op: 'tunnel', target: name, confirm: 'TUNNEL_SWITCH' }, 'Маршруты VWARD идут через ' + name, ['status', 'security', 'route']); },
  'wg-off': () => cfgSet({ op: 'wan-guard', value: '0', confirm: 'WAN_GUARD_DISABLE' }, 'Восстановление интернета выключено'),
  'wan-bounce': () => wanOp('wan-bounce', 'WAN_BOUNCE', 'Интернет переподключён'),
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
const WAN_ERRORS = {
  COOLDOWN: 'между ручными действиями нужна минута', BUSY: 'VWARD сейчас сам восстанавливает связь, повторите через минуту',
  UPDATER_BUSY: 'идёт обновление, повторите позже', RENEW_FAILED: 'роутер не принял запрос адреса', DOWN_FAILED: 'роутер не отключил интерфейс, связь не менялась',
  UP_FAILED: 'интерфейс не включился - VWARD продолжит включать его каждую минуту', INCOMPLETE_BOUNCE: 'не удалось завершить прошлое переподключение',
  PROFILE_UNAVAILABLE: 'интерфейс интернета не определён', INTERRUPTED: 'действие прервано, интерфейс включён обратно'
};
async function wanOp(op, token, okMsg) {
  runningId = 'wan'; render();
  let text;
  try {
    const x = await apiPost('control', { op: op, confirm: token }), code = ((x.output || '').match(/ERROR=([A-Z_]+)/) || [])[1];
    text = x.ok ? okMsg : 'Не выполнено: ' + (WAN_ERRORS[code] || errText(x));
  } catch (e) { text = 'Ошибка: ' + e.message; }
  runningId = null; toast(text);
  await load('status', true); render();
}
/* «Автоматически» и «По расписанию» различаются окном установки (apply_window). */
let updModeShown = null;
async function updateMode(mode) {
  const p = plat(), on = mode === 'manual' ? '0' : '1';
  // Shown at once; saved in the background and put back if the router refuses.
  updModeShown = mode; render();
  if (mode !== 'manual') {
    const x = await apiPost('config', { op: 'update', target: 'apply_window', value: mode === 'auto' ? 'any' : 'window' }).catch(e => ({ ok: false, error: e.message }));
    if (!x.ok) { toast('Не сохранено: ' + errText(x)); updModeShown = null; await load('config', true); render(); return; }
  }
  await runAction('updates', 'settings', { auto_apply: on, auto_critical: isTrue(p.auto_critical) ? '1' : '0', auto_important: isTrue(p.auto_important) ? '1' : '0', auto_routine: isTrue(p.auto_routine) ? '1' : '0' }, 'Настройки обновлений сохранены');
  await Promise.all([load('status', true), load('config', true)]); updModeShown = null; render();
}
/* Long operations run in the background on the router: they outlast the 10-second request.
   The Console polls dataAction and shows the output until the run finishes. */
/* ---------- Окно установки обновления ---------- */
// Like Keenetic: a window over the page while an update installs or rolls back,
// by the button or on schedule; it follows the updater's phases.
const UPD_STEPS = [['CHECKING', 'Подготовка к установке', 5], ['VERIFIED', 'Проверка подписи', 15], ['BACKING_UP', 'Резервная копия', 30], ['INSTALLING', 'Установка файлов', 55], ['VERIFYING', 'Проверка работы', 80], ['COMMIT_PREPARED', 'Завершение', 92], ['COMMITTED', 'Готово', 100]];
const UPD_BUSY = ['BACKING_UP', 'INSTALLING', 'VERIFYING', 'COMMIT_PREPARED', 'ROLLING_BACK'];
let updOverlay = null;
// A full-screen window like Keenetic's own: a ring with the percentage and the stage under it.
// Each stage has its share; inside a stage the ring creeps on so it never looks frozen.
function updOverlayShow(o) {
  updOverlay = Object.assign(updOverlay || { op: 'apply', phase: 'CHECKING', from: plat().version || '', pct: 0 }, o);
  let el = $('updOverlay');
  if (!el) { el = document.createElement('div'); el.id = 'updOverlay'; document.body.appendChild(el); }
  const u = updOverlay, rb = u.op === 'rollback' || u.phase === 'ROLLING_BACK';
  const i = Math.max(0, UPD_STEPS.findIndex(x => x[0] === u.phase)), step = UPD_STEPS[i], next = UPD_STEPS[i + 1];
  const base = rb ? 50 : step[2], cap = rb ? 95 : next ? next[2] - 3 : 100;
  u.pct = u.done ? 100 : Math.min(cap, Math.max(u.pct || 0, base) + (u.pct >= base ? 1 : 0));
  const head = u.done ? (u.ok ? (rb ? 'Откат выполнен' : 'Обновление установлено') : 'Обновление не установлено') : (rb ? 'Откат обновления VWARD' : 'Обновление VWARD');
  const stage = u.done ? (u.ok ? 'VWARD ' + (u.version || '') + ' работает' : 'Прежняя версия работает') : rb ? 'Возврат прежней версии' : step[1];
  const text = u.done ? (u.ok ? 'Обновите страницу, чтобы открыть новую версию.' : (u.error || 'Установщик вернул прежнюю версию, всё работает как раньше. Подробности - в «Журналах» → «Обновления».'))
    : 'Не закрывайте страницу, пока не завершится обновление. Роутер и интернет продолжают работать.';
  const R = 76, C = 2 * Math.PI * R, a = (u.pct / 100) * 2 * Math.PI - Math.PI / 2;
  const state = u.done ? (u.ok ? ' ok' : ' crit') : '';
  el.innerHTML = '<div class="upd-page' + state + '" role="dialog" aria-live="polite" aria-label="' + esc(head) + '">' +
    '<h2>' + esc(head) + '</h2>' + (u.version && !u.done ? '<p class="upd-ver">' + esc((u.from ? u.from + ' → ' : '') + u.version) + '</p>' : '') +
    '<p class="upd-text">' + esc(text) + '</p>' +
    '<div class="upd-ring"><svg viewBox="0 0 180 180" aria-hidden="true"><circle class="upd-track" cx="90" cy="90" r="' + R + '"/>' +
    '<circle class="upd-arc" cx="90" cy="90" r="' + R + '" stroke-dasharray="' + C.toFixed(1) + '" stroke-dashoffset="' + (C * (1 - u.pct / 100)).toFixed(1) + '" transform="rotate(-90 90 90)"/>' +
    (u.done ? '' : '<circle class="upd-dot" cx="' + (90 + R * Math.cos(a)).toFixed(1) + '" cy="' + (90 + R * Math.sin(a)).toFixed(1) + '" r="11"/>') + '</svg>' +
    '<span class="upd-pct">' + (u.done ? ico(u.ok ? 'check' : 'alert') : u.pct + '%') + '</span></div>' +
    '<p class="upd-stage">' + esc(stage) + '</p>' +
    (u.done ? '<div class="panel-actions">' + (u.ok ? '<button class="btn primary" type="button" data-act="upd-reload">Обновить страницу</button>' : '<button class="btn" type="button" data-act="upd-close">Закрыть</button>') + '</div>' : '') + '</div>';
}
function updOverlayClose() { updOverlay = null; const el = $('updOverlay'); if (el) el.remove(); }
// Updater exit codes that are answers, not failures.
const UPDATE_RC = { 10: 'Новых обновлений нет', 11: 'Обновление отложено: версия в карантине', 20: 'Обновление найдено, установится в назначенное время', 34: 'Нет связи с сервером обновлений' };
const UPDATE_RC_OK = { 10: 1, 20: 1 };
// The id of the block whose long action is running: its button shows the progress.
let runningId = null;
async function runLong(resultId, action, fields, dataAction, okMsg) {
  const show = text => { actionResult = { id: resultId, text: text }; render(); };
  runningId = resultId; actionResult = null;
  try { return await runLongBody(resultId, action, fields, dataAction, okMsg, show); } finally { runningId = null; render(); }
}
async function runLongBody(resultId, action, fields, dataAction, okMsg, show) {
  const installing = dataAction === 'update-data' && fields && fields.op !== 'check';
  if (installing) updOverlayShow({ manual: true, op: fields.op, phase: 'CHECKING', version: (S.update && S.update.pending && S.update.pending.version) || '', done: false });
  render();
  let x;
  try { x = await apiPost(action, fields); }
  catch (e) { if (installing) updOverlayClose(); toast('Ошибка: ' + e.message); return; }
  if (!x.ok) { if (installing) updOverlayClose(); toast('Не выполнено: ' + errText(x)); return; }
  let run = {};
  const deadline = Date.now() + 15 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 3000));
    let u;
    try { u = await apiGet(dataAction); } catch (e) { continue; }
    run = u.run || {};
    if (installing && u.phase) updOverlayShow({ phase: u.phase });
    if (run.finished) break;
  }
  const done = !run.finished ? 'Ещё выполняется, проверьте позже' : run.rc === 0 ? okMsg : dataAction === 'update-data' && UPDATE_RC[run.rc] ? UPDATE_RC[run.rc] : 'Не выполнено (код ' + run.rc + ') - подробности в «Журналах»';
  const answered = run.finished && (run.rc === 0 || (dataAction === 'update-data' && UPDATE_RC_OK[run.rc]));
  if (installing) {
    if (run.finished && run.rc === 0) { await load('status', true); updOverlayShow({ done: true, ok: true, version: (updOverlay && updOverlay.version) || plat().version }); return run; }
    if (run.finished && run.rc === 20) updOverlayClose();
    else updOverlayShow({ done: true, ok: false, error: run.finished ? (UPDATE_RC[run.rc] || '') : 'Установка ещё идёт. Проверьте раздел «Обновления» через минуту.' });
  }
  // An empty okMsg: the caller reports the outcome itself.
  if (okMsg || !answered) toast(done);
  // The outcome is a toast only: no leftover line under the buttons.
  actionResult = null;
  render();
  return run;
}
const UPDATE_OK = { check: 'Проверка завершена', apply: 'Обновление установлено', retry: 'Обновление установлено', rollback: 'Откат выполнен', recover: 'Обновление восстановлено' };
function updateOp(op, token) {
  return runLong('updates', 'update-control', token ? { op: op, confirm: token } : { op: op }, 'update-data', op === 'check' ? '' : UPDATE_OK[op] || 'Готово')
    .then(() => Promise.all([load('update', true), load('status', true)])).then(() => {
      // After a check, say what it found.
      if (op === 'check') { const pd = S.update && S.update.pending; toast(pd && pd.present ? 'Найдено обновление ' + (pd.version || '') : 'Новых обновлений нет'); }
      render();
    });
}
async function adsControl(fields, okMsg, resultId) {
  const x = await runAction(resultId || 'ads', 'ads-control', fields, okMsg);
  await load('ads', true); render(); return x;
}
async function adsSetting(key, value) {
  const fields = {}; fields[key] = value;
  if (key === 'AUTO_PUBLISH' && value === '1') fields.confirm = 'ADS_AUTO_PUBLISH';
  // Shown at once (the interval row follows the mode); the router's answer confirms or puts it back.
  if (S.ads && S.ads.settings) { S.ads.settings[key] = value; render(); }
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
  const t = e.target.closest('[data-go],[data-act],[data-tab],[data-card-toggle],[data-log],[data-move],[data-card-move],[data-view],[data-ads-remove],[data-wifi-bind],[data-log-go],[data-cfg-op],[data-ads-rule],[data-qfilter],[data-ads-srcdel],[data-agh-filter-rm],[data-backup-restore],[data-files-root],[data-files-dir],[data-files-open],[data-files-up]');
  if (!t || t.disabled) return;
  if (t.dataset.cardToggle) { const id = t.dataset.cardToggle; hiddenCards = hiddenCards.includes(id) ? hiddenCards.filter(x => x !== id) : hiddenCards.concat(id); store.set('vward-card-hidden', hiddenCards); render(); return; }
  if (t.dataset.cardMove) { const [id, dir] = t.dataset.cardMove.split(':'), i = cardOrder.indexOf(id), j = i + (dir === 'up' ? -1 : 1); if (j >= 0 && j < cardOrder.length) { [cardOrder[i], cardOrder[j]] = [cardOrder[j], cardOrder[i]]; store.set('vward-card-order', cardOrder); render(); } return; }
  if (t.dataset.move) { const [id, dir] = t.dataset.move.split(':'), i = tabIds.indexOf(id), j = i + (dir === 'up' ? -1 : 1); if (j >= 0 && j < tabIds.length) { [tabIds[i], tabIds[j]] = [tabIds[j], tabIds[i]]; store.set('vward-tabs', tabIds); render(); } return; }
  if (t.dataset.view) { cardView = t.dataset.view; store.set('vward-card-view', cardView); render(); return; }
  if (t.dataset.logGo) logTab = t.dataset.logGo;
  if (t.dataset.qfilter && t.dataset.go) { ADSV.filter = t.dataset.qfilter; S.qlog = null; }
  if (t.dataset.go) { if (t.closest('.preview')) return; go(t.dataset.go, t.dataset.key); return; }
  if (t.dataset.log) { logTab = t.dataset.log; render(); loadLog(logTab, true); return; }
  if (t.dataset.adsRemove) { adsControl({ op: 'remove-override', domain: t.dataset.adsRemove, scope: t.dataset.scope || 'exact' }, 'Правило удалено', 'ads-rule'); return; }
  if (t.dataset.qfilter && !t.dataset.go) { ADSV.filter = t.dataset.qfilter; S.qlog = null; render(); load('qlog', true).then(render); return; }
  if (t.dataset.adsRule) { const d = t.dataset.domain; t.disabled = true; adsControl({ op: t.dataset.adsRule, domain: d, scope: 'exact' }, (t.dataset.adsRule === 'allow' ? d + ' разрешён' : d + ' заблокирован'), 'ads-rule').then(adsViews); return; }
  if (t.dataset.adsSrcdel) { t.disabled = true; adsControl({ op: 'source-delete', source: t.dataset.adsSrcdel }, 'Источник удалён', 'ads-src'); return; }
  if (t.dataset.filesRoot) { filesGo(t.dataset.filesRoot, ''); return; }
  if (t.dataset.filesDir) { filesGo(FILES.root, filePath(t.dataset.filesDir)); return; }
  if (t.dataset.filesOpen) { fileOpen(t.dataset.filesOpen); return; }
  if (t.dataset.filesUp) { if (FILES.path) filesGo(FILES.root, FILES.path.split('/').slice(0, -1).join('/')); else filesGo('', ''); return; }
  if (t.dataset.backupRestore) { confirm = { id: 'backup-restore', name: t.dataset.backupRestore }; render(); return; }
  if (t.dataset.aghFilterRm) { confirm = { id: 'agh-filter-remove', url: t.dataset.aghFilterRm }; render(); return; }
  if (t.dataset.listDom) { const v = t.dataset.dom, how = t.dataset.listDom; t.disabled = true; cfgSet({ op: 'list-domain', action: how, target: current.slice(2), value: v }, how === 'remove' ? v + ' убран из списка' : 'Исключение ' + v + ' убрано', ['listd', 'lists']); return; }
  if (t.dataset.cfgOp === 'tsubnet') { t.disabled = true; tunnelSubnet(current.slice(2), 'remove', t.dataset.cfgTarget); return; }
  if (t.dataset.cfgOp) { const d = t.dataset.cfgTarget, msg = { 'route-domain': d + ' убран из VPN', 'force-vpn': d + ' убран из списка', adaptive: t.dataset.cfgAction === 'pin' ? d + ' закреплён в моих доменах' : d + ' идёт напрямую' }[t.dataset.cfgOp]; t.disabled = true; cfgSet({ op: t.dataset.cfgOp, action: t.dataset.cfgAction, target: d }, msg, ['route']); return; }
  if (t.dataset.wifiBind) { if (t.getAttribute('aria-checked') === 'true') return; confirm = { id: 'wifi-bind', op: t.dataset.wifiBind }; render(); return; }
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
  else if (a === 'ask') { confirm = { id: t.dataset.confirm, pkg: t.dataset.pkg }; render(); }
  else if (a === 'ext-check') extOp('check');
  else if (a === 'confirm-no') { confirm = null; render(); }
  else if (a === 'confirm-yes') { const c = confirm; confirm = null; if (c && CONFIRMED[c.id]) CONFIRMED[c.id](c); else render(); }
  else if (a === 'open-log') { logTab = t.dataset.logTab; go('logs'); }
  else if (a === 'tunnel-probe') {
    const n = t.dataset.name; S.tprobe[n] = { busy: true }; render();
    apiGet('tunnel-probe', { name: n }).then(r => r, e => ({ ok: false, error: e.message }))
      .then(r => { S.tprobe[n] = Object.assign(r, { at: new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) }); render(); });
  }
  else if (a === 'backup-create') { actionResult = { id: 'backup', text: 'Создаём копию…' }; render(); apiPost('backup-control', { op: 'create' }).then(x => { toast(x.ok ? 'Копия создана' : 'Не выполнено: ' + errText(x)); actionResult = null; return load('backups', true); }, e => { toast('Ошибка: ' + e.message); actionResult = null; }).then(render); }
  else if (a === 'upd-reload') location.reload();
  else if (a === 'upd-close') updOverlayClose();
  else if (a === 'agh-filters-refresh') aghSet({ setting: 'filters-refresh' }, 'Списки обновляются');
  else if (a === 'tunnel-create') tunnelConfSheet('create');
  else if (a === 'tunnel-replace') tunnelConfSheet('replace', current.slice(2));
  else if (a === 'tunnel-delete') { const s2 = document.querySelector('[data-tunnel-del-to]'); confirm = { id: 'tunnel-delete', to: s2 ? s2.value : 'vpn' }; render(); }
  else if (a === 'tunnel-health') runAction('tunnel-health', 'control', { op: 'tunnel-health' }, 'Проверка туннеля выполнена').then(() => load('status', true)).then(render);
  else if (a === 'page-reload') location.reload();
  else if (a === 'probe-report' && PROBE) openSheet('Проверка ' + PROBE.domain, '<div class="sheet-body"><pre class="logbox">' + esc(PROBE.out || '') + '</pre></div>', 'wide');
  else if (a === 'logout') apiPost('auth', { op: 'logout' }).then(() => { toast('Вы вышли'); S.auth = null; showLogin(); });
  else if (a === 'housekeeping') runLong('storage', 'control', { op: 'housekeeping' }, 'control-data', 'Журналы проверены').then(() => load('status', true)).then(render);
  else if (a === 'refresh-hints') runLong('routes', 'control', { op: 'refresh-hints' }, 'control-data', 'Подсказки обновлены').then(() => load('route', true)).then(render);
  else if (a === 'update-op') updateOp(t.dataset.op);
  else if (a === 'diag-run') { load('diag', true).then(() => { render(); toast('Диагностика выполнена'); }); }
  else if (a === 'ads-job') adsControl({ op: 'enqueue', job: t.dataset.job }, 'Задание поставлено в очередь', 'ads-job');
  else if (a === 'https-op') runAction('https', 'ads-https-control', { op: t.dataset.op }, 'Готово').then(() => load('https', true)).then(render);
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
// Filters a long list in place: no re-render per key press.
document.addEventListener('input', e => {
  if (!e.target.hasAttribute('data-list-filter')) return;
  const q = e.target.value.trim().toLowerCase();
  document.querySelectorAll('[data-list-rows] > li').forEach(li => { li.hidden = !!q && !li.dataset.d.includes(q); });
});
document.addEventListener('change', e => {
  const t = e.target;
  if (t.dataset.tabpick) {
    const id = t.dataset.tabpick;
    if (t.checked) { if (tabIds.length >= TAB_MAX) { t.checked = false; toast('На панели помещается не больше ' + TAB_MAX + ' разделов'); return; } tabIds.push(id); }
    else { if (tabIds.length <= 1) { t.checked = true; toast('Оставьте хотя бы один раздел'); return; } tabIds = tabIds.filter(x => x !== id); }
    store.set('vward-tabs', tabIds); render(); return;
  }
  if (t.dataset.upd) { updateMode(t.value); return; }
  if (t.hasAttribute('data-upd-feed')) {
    if (t.value === 'dev') { t.value = 'beta'; confirm = { id: 'feed-dev' }; render(); }
    else cfgSet({ op: 'update-feed', target: 'beta' }, 'Канал: Бета');
    return;
  }
  if (t.dataset.comp) {
    const id = t.dataset.comp, want = t.checked;
    t.checked = !want;
    if (!want) { confirm = { id: 'comp-off' }; render(); }
    else if (compCascade(id, false).length) { confirm = { id: 'comp-on' }; render(); }
    else cfgSet({ op: 'component', target: id, value: '1' }, '«' + comp(id).name + '» включён', ['status']);
    return;
  }
  if (t.dataset.listBypass) {
    const g = t.dataset.listBypass, around = t.checked;
    t.disabled = true;
    cfgSet({ op: 'domain-list', target: g, value: around ? 'bypass' : 'vpn' }, around ? 'Список идёт в обход VPN' : 'Список идёт через VPN', ['lists']);
    return;
  }
  if (t.dataset.listWatch) { cfgSet({ op: 'domain-list-watch', target: t.dataset.listWatch, value: t.checked ? '1' : '0' }, t.checked ? 'Слежение включено' : 'Слежение выключено', ['lists']); return; }
  if (t.hasAttribute('data-cfg-wg')) { if (!t.checked) { t.checked = true; confirm = { id: 'wg-off' }; render(); } else cfgSet({ op: 'wan-guard', value: '1' }, 'Восстановление интернета включено'); return; }
  if (t.hasAttribute('data-cfg-tg')) { if (!t.checked) { t.checked = true; confirm = { id: 'tg-off' }; render(); } else cfgSet({ op: 'tunnel-guard', value: '1' }, 'Защита VPN включена', ['status']); return; }
  if (t.dataset.cfgWifi) {
    const key = t.dataset.cfgWifi, v = t.type === 'checkbox' ? (t.checked ? '1' : '0') : t.value;
    if (key === 'CONTROL_ENABLED' && v === '1') { t.checked = false; confirm = { id: 'wifi-ctl-on' }; render(); return; }
    cfgSet({ op: 'wifi', target: key, value: v }, 'Сохранено', ['wifi']); return;
  }
  if (t.dataset.cfgRt) { cfgSet({ op: t.dataset.cfgRt, value: t.checked ? '1' : '0' }, 'Сохранено'); return; }
  if (t.dataset.ipcat) { cfgSet({ op: 'ip-category', target: t.dataset.ipcat, value: t.checked ? '1' : '0' }, t.checked ? 'Категория включена' : 'Категория выключена - применится при следующей сверке'); return; }
  if (t.dataset.cfgCat) { cfgSet({ op: 'domain-category', target: t.dataset.cfgCat, value: t.checked ? '1' : '0' }, t.checked ? 'Категория включена' : 'Категория выключена'); return; }
  if (t.dataset.wifiAccess) {
    if (!t.checked) { t.checked = true; confirm = { id: 'wifi-deny', mac: t.dataset.wifiAccess }; render(); return; }
    t.disabled = true; wifiHostSet({ op: 'access', mac: t.dataset.wifiAccess, value: 'permit' }, 'Интернет разрешён'); return;
  }
  if (t.dataset.agh) {
    const k = t.dataset.agh, v = t.checked ? '1' : '0';
    if (k === 'protection' && v === '0') { t.checked = true; confirm = { id: 'agh-protection-off' }; render(); return; }
    t.disabled = true;
    aghSet({ setting: k, value: v }, 'Сохранено в AdGuard Home'); return;
  }
  if (t.hasAttribute('data-agh-interval')) { aghSet({ setting: 'interval', value: t.value }, 'Сохранено в AdGuard Home'); return; }
  if (t.dataset.aghFilter) { t.disabled = true; aghSet({ setting: 'filter-enable', url: t.dataset.aghFilter, value: t.checked ? '1' : '0' }, t.checked ? 'Список включён' : 'Список выключен'); return; }
  if (t.dataset.aghService) { t.disabled = true; aghSet({ setting: 'service', service: t.dataset.aghService, value: t.checked ? '1' : '0' }, t.checked ? 'Сервис заблокирован' : 'Сервис открыт'); return; }
  if (t.hasAttribute('data-conf-file')) {
    const file = t.files && t.files[0], form = t.closest('form');
    if (!file) return;
    if (file.size > 16384) { toast('Файл больше 16 КБ - это не .conf'); return; }
    const r = new FileReader();
    r.onload = () => { form.querySelector('[name=conf]').value = String(r.result || ''); form.dataset.checked = ''; $('tcPreview').innerHTML = ''; form.querySelector('[type=submit]').textContent = 'Проверить файл'; };
    r.readAsText(file);
    return;
  }
  if (t.dataset.listVia) { const v = t.value; t.disabled = true; cfgSet({ op: 'domain-list', target: t.dataset.listVia, value: v }, v === 'bypass' ? 'Список идёт через провайдера' : 'Список идёт через ' + v, ['lists']); return; }
  if (t.hasAttribute('data-theme-pick')) { setTheme(t.value); return; }
  if (t.hasAttribute('data-smartdns-guard')) { cfgSet({ op: 'smartdns-guard', value: t.checked ? '1' : '0' }, t.checked ? 'Защита Smart DNS включена' : 'Защита Smart DNS выключена', ['lists']); return; }
  if (t.dataset.extAuto) { cfgSet({ op: 'ext-auto', target: t.dataset.extAuto, value: t.checked ? '1' : '0' }, t.checked ? 'Будет обновляться автоматически' : 'Обновление только вручную', ['ext']); return; }
  if (t.hasAttribute('data-route-tunnel')) { const to = t.value; t.value = prof().tunnel_interface || ''; if (to && to !== t.value) { confirm = { id: 'route-tunnel', to: to }; render(); } return; }
  if (t.hasAttribute('data-fw-auto')) { t.disabled = true; cfgSet({ op: 'firmware', target: 'auto', value: t.checked ? '1' : '0' }, t.checked ? 'Keenetic будет обновляться автоматически' : 'Прошивка обновляется только вручную', ['ext']); return; }
  if (t.hasAttribute('data-fw-channel')) {
    const v = t.value;
    if (v !== 'stable') { t.value = ((S.ext || {}).firmware || {}).channel || 'stable'; confirm = { id: 'fw-channel', value: v }; render(); return; }
    t.disabled = true; cfgSet({ op: 'firmware', target: 'channel', value: v }, 'Канал прошивки: ' + fwChannel(v), ['ext']); return;
  }
  if (t.dataset.cfgWanp) { cfgSet({ op: 'wan-param', target: t.dataset.cfgWanp, value: t.value }, 'Сохранено', ['config']); return; }
  if (t.dataset.cfgUpd) { cfgSet({ op: 'update', target: t.dataset.cfgUpd, value: t.value }, 'Сохранено', ['status']); return; }
  if (t.hasAttribute('data-ads-pause')) { adsControl({ op: t.checked ? 'resume' : 'pause' }, t.checked ? 'Блокировка включена' : 'Блокировка на паузе'); return; }
  if (t.dataset.adsSet) { adsSetting(t.dataset.adsSet, t.type === 'checkbox' ? (t.checked ? '1' : '0') : t.value); return; }
  if (t.hasAttribute('data-auth-devices')) {
    const on = t.checked;
    apiPost('auth', { op: 'devices', value: on ? '1' : '0' }).then(x => { toast(x.ok ? (on ? 'VWARD открыт только зарегистрированным устройствам' : 'VWARD открыт всем устройствам домашней сети') : 'Не сохранено: ' + errText(x)); return load('auth', true); }, e => toast('Ошибка: ' + e.message)).then(render);
    return;
  }
  if (t.hasAttribute('data-auth')) {
    const au = S.auth || {};
    if (t.checked && !au.enabled) { authForm = true; render(); }
    else if (!t.checked && authForm && !au.enabled) { authForm = false; render(); }
    else if (!t.checked && au.enabled) { t.checked = true; confirm = { id: 'auth-off' }; render(); }
    return;
  }
  if (t.hasAttribute('data-ads-autopub')) { if (t.checked) { t.checked = false; confirm = { id: 'ads-autopub' }; render(); } else adsSetting('AUTO_PUBLISH', '0').then(() => load('adspub', true)).then(render); return; }
  if (t.dataset.adsCat) { adsControl({ op: 'source-category', category: t.dataset.adsCat, state: t.checked ? 'on' : 'off' }, t.checked ? 'Категория включена' : 'Категория выключена', 'ads-rule'); return; }
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
  if (f === 'list-add') {
    const input = e.target.querySelector('input'), v = input.value.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/[/:].*$/, '').replace(/^\*\./, '');
    if (!DOMAIN.test(v)) { toast('Введите домен, например example.com'); return; }
    const kind = e.target.dataset.kind;
    const x = await cfgSet({ op: 'list-domain', action: kind, target: current.slice(2), value: v }, kind === 'add' ? v + ' добавлен в список' : v + ' добавлен в исключения', ['listd', 'lists']);
    if (x && x.ok) { const again = document.querySelector('form[data-form="list-add"][data-kind="' + kind + '"] input'); if (again) again.value = ''; }
  }
  if (f === 'cfg-add') {
    const input = e.target.querySelector('input'), v = input.value.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/[/:].*$/, '').replace(/^\*\./, '');
    if (!DOMAIN.test(v)) { toast('Введите домен, например example.com'); return; }
    const x = await cfgSet({ op: e.target.dataset.op, action: 'add', target: v }, v + ' добавлен', ['route']);
    if (x && x.ok) { const again = document.querySelector('form[data-form="cfg-add"] input'); if (again) again.value = ''; }
  }
  if (f === 'wifi-name') {
    const v = e.target.querySelector('[name=name]').value.trim();
    if (!v || v.length > 32 || /["\\]/.test(v)) { toast('Имя: до 32 символов, без кавычек'); return; }
    await wifiHostSet({ op: 'name', mac: e.target.dataset.mac, name: v }, 'Имя сохранено в Keenetic'); return;
  }
  if (f === 'agh-filter-add') {
    const url = e.target.querySelector('[name=url]').value.trim(), name = e.target.querySelector('[name=name]').value.trim();
    if (!/^https:\/\/[A-Za-z0-9.-]+(:\d{1,5})?\/\S*$/.test(url)) { toast('Нужен адрес https://…'); return; }
    if (!/^[A-Za-z0-9 ._-]{1,64}$/.test(name)) { toast('Название: латиница, цифры, пробел, точка, дефис'); return; }
    await aghSet({ setting: 'filter-add', url: url, name: name }, 'Список добавлен'); return;
  }
  if (f === 'tunnel-subnet') {
    const v = e.target.querySelector('[name=subnet]').value.trim();
    if (!/^\d{1,3}(\.\d{1,3}){3}(\/\d{1,2})?$/.test(v)) { toast('Введите подсеть, например 149.154.160.0/20'); return; }
    await tunnelSubnet(e.target.dataset.name, 'add', v); return;
  }
  if (f === 'tunnel-conf') {
    const form = e.target, mode = form.dataset.mode, name = form.dataset.name, text = form.querySelector('[name=conf]').value;
    const descEl = form.querySelector('[name=description]'), desc = descEl ? descEl.value.trim() : '';
    if (!/\[Interface\]/i.test(text) || !/\[Peer\]/i.test(text)) { toast('Выберите файл .conf или вставьте его текст'); return; }
    if (mode === 'create' && !desc) { toast('Введите название туннеля'); return; }
    if (form.dataset.checked !== '1') {
      let x;
      try { x = await apiPost('tunnel-conf', { op: 'check', conf: text }); } catch (err) { toast('Ошибка: ' + err.message); return; }
      if (!x.ok) { toast('Файл не подходит: ' + errText(x)); return; }
      $('tcPreview').innerHTML = kv([['Сервер', x.endpoint || '—'], ['Адрес в туннеле', x.address || '—'], ['MTU', x.mtu || 'как на роутере'],
        ['Обфускация AmneziaWG', x.awg === '1' ? 'Включена' : 'Выключена'], ['Keepalive', x.keepalive ? x.keepalive + ' с' : '25 с'], ['Разрешённые адреса', x.allowed || '—']]);
      form.dataset.checked = '1';
      form.querySelector('[type=submit]').textContent = mode === 'create' ? 'Создать туннель' : 'Заменить конфигурацию ' + name;
      return;
    }
    closeLayer();
    await tunnelJob(mode === 'create' ? 'tunnels' : 'tunnel-conf', mode === 'create' ? { op: 'create', conf: text, description: desc } : { op: 'replace', name: name, conf: text, confirm: 'TUNNEL_REPLACE' });
    return;
  }
  if (f === 'agh-connect') {
    const login = e.target.querySelector('[name=login]').value.trim(), password = e.target.querySelector('[name=password]').value;
    if (!/^[A-Za-z0-9._@-]{1,64}$/.test(login) || !password) { toast('Введите логин и пароль AdGuard Home'); return; }
    let x;
    try { x = await apiPost('agh-auth', { op: 'connect', login: login, password: password }); }
    catch (err) { toast('Ошибка: ' + err.message); return; }
    e.target.querySelector('[name=password]').value = '';
    if (!x.ok) { toast(errText(x)); return; }
    toast('AdGuard Home подключён');
    await Promise.all([load('ads', true), load('adsstats', true)]); render(); return;
  }
  if (f === 'login' || f === 'auth-enable') {
    const login = e.target.querySelector('[name=login]').value.trim(), password = e.target.querySelector('[name=password]').value;
    if (!/^[A-Za-z0-9._@-]{1,64}$/.test(login) || !password) { toast('Введите логин и пароль'); return; }
    let x;
    try { x = await apiPost('auth', { op: f === 'login' ? 'login' : 'enable', login: login, password: password }); }
    catch (err) { toast('Ошибка: ' + err.message); return; }
    e.target.querySelector('[name=password]').value = '';
    if (!x.ok) { toast(errText(x)); return; }
    loginOpen = false; authForm = false; closeLayer();
    toast(f === 'login' ? 'Вы вошли' : 'Вход включён');
    await Promise.all(['auth', 'security', 'status'].map(k => load(k, true)));
    refreshPage();
  }
  if (f === 'ads-qsearch' || f === 'ads-bsearch') {
    const v = e.target.querySelector('input').value.trim().toLowerCase();
    if (v && !/^[a-z0-9.-]{1,100}$/.test(v)) { toast('Только буквы, цифры, точки и дефисы'); return; }
    if (f === 'ads-qsearch') { ADSV.search = v; S.qlog = null; render(); await load('qlog', true); }
    else { ADSV.blockedSearch = v; S.blocked = null; render(); await load('blocked', true); }
    render();
  }
  if (f === 'ads-srcadd') {
    const url = e.target.querySelector('[name=url]').value.trim();
    if (!/^https:\/\/[A-Za-z0-9.-]+(:[0-9]{1,5})?\/[A-Za-z0-9._~\/%+=&?-]*$/.test(url) || url.length > 300) { toast('Нужен адрес https://…, без пробелов и логина'); return; }
    const x = await adsControl({ op: 'source-add', url: url, format: e.target.querySelector('[name=format]').value }, 'Источник добавлен в режиме «Проверка»', 'ads-src');
    if (x && x.ok) adsControl({ op: 'enqueue', job: 'sources-update' }, 'Источник добавлен, загрузка поставлена в очередь', 'ads-src');
  }
  if (f === 'ads-probe') {
    const v = $('adsProbe').value.trim().toLowerCase();
    if (!DOMAIN.test(v)) { toast('Введите домен, например example.com'); return; }
    adsProbe(v);
  }
  if (f === 'ads-rule') {
    const v = $('adsRuleDomain').value.trim().toLowerCase();
    if (!DOMAIN.test(v)) { toast('Введите домен, например example.com'); return; }
    await adsControl({ op: $('adsRuleType').value, domain: v, scope: $('adsRuleScope').value }, 'Правило добавлено', 'ads-rule');
  }
});

/* ---------- Тема и обновление данных ---------- */
// «По времени суток»: светлая с 07:00 до 20:00, тёмная ночью.
const THEMES = { system: 'как в системе', time: 'по времени суток', light: 'светлая', dark: 'тёмная' };
function applyTheme() {
  const r = document.documentElement, h = new Date().getHours();
  const t = theme === 'time' ? (h >= 7 && h < 20 ? 'light' : 'dark') : theme;
  if (t === 'system') r.removeAttribute('data-theme'); else r.setAttribute('data-theme', t);
  $('themeBtn').innerHTML = ico(theme === 'light' ? 'sun' : theme === 'dark' ? 'moon' : 'auto');
  $('themeBtn').setAttribute('aria-label', 'Тема: ' + THEMES[theme]);
}
function setTheme(v) { theme = THEMES[v] ? v : 'system'; store.set('vward-theme', theme); applyTheme(); if (current === 'settings') render(); }
let timer = null;
// A hidden tab does not poll the router; it catches up as soon as it is shown.
function tick() {
  if (document.hidden) return;
  const ph = plat().phase;
  if (UPD_BUSY.includes(ph)) updOverlayShow({ op: ph === 'ROLLING_BACK' ? 'rollback' : 'apply', phase: ph, done: false });
  else if (updOverlay && !updOverlay.done && !updOverlay.manual && ph === 'IDLE' && updOverlay.seenBusy) updOverlayShow({ done: true, ok: true, version: plat().version });
  if (updOverlay && UPD_BUSY.includes(ph)) updOverlay.seenBusy = true;
  if (theme === 'time') applyTheme();
  if (current !== 'logs') refreshPage();
  load('status', true).then(renderNav);
}
function restartTimer() {
  if (timer) clearInterval(timer);
  timer = setInterval(tick, REFRESH_SEC * 1000);
}
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && Date.now() - (S.loadedAt.status || 0) >= REFRESH_SEC * 1000) tick();
});

$('backBtn').innerHTML = ico('back');
$('backBtn').addEventListener('click', () => { if (histDepth() > 0) history.back(); else go(parentOf(current) || 'overview', null, 'replace'); });
window.addEventListener('popstate', e => {
  // No state: the address was typed or a link changed only the hash.
  const s = e.state || { p: decodeURIComponent(location.hash.slice(1)) || 'overview', d: 0 };
  if (!e.state) history.replaceState({ p: page(s.p) ? s.p : 'overview', d: histDepth() }, '', location.hash);
  if ($('layer').innerHTML) closeLayer(true);
  if (s.p !== current) go(s.p, null, 'pop');
});
WIDE.addEventListener('change', renderNav);
$('searchBtn').innerHTML = ico('search');
$('searchBtn').addEventListener('click', openSearch);
$('bellBtn').addEventListener('click', openNotes);
$('themeBtn').addEventListener('click', () => { setTheme(({ system: 'time', time: 'light', light: 'dark', dark: 'system' })[theme] || 'system'); toast('Тема: ' + THEMES[theme]); });
applyTheme();
{ const h = decodeURIComponent(location.hash.slice(1)); if (page(h)) current = h; }
cacheRead();
history.replaceState({ p: current, d: 0 }, '', '#' + current);
render();
Promise.all(['status', 'security', 'update'].map(k => load(k))).then(() => { render(); refreshPage(); });
restartTimer();
})();
