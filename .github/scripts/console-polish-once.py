#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[2]
p = root / "web/index.html"
s = p.read_text(encoding="utf-8")


def once(old: str, new: str, label: str) -> None:
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"{label}: expected 1 match, found {n}")
    s = s.replace(old, new, 1)


once(
    '<button class="btn" id="refreshBtn" aria-label="Обновить">↻</button><button class="btn" id="themeBtn" aria-label="Тема">◐</button>',
    '<button class="btn" id="refreshBtn" aria-label="Обновить">↻</button><button class="btn" id="helpBtn" aria-label="Подсказка" aria-expanded="false">?</button><button class="btn" id="themeBtn" aria-label="Тема">◐</button>',
    "top help button",
)

for old, new in {
    '<h2>VWARD Update Engine</h2>': '<h2>Состояние обновлений</h2>',
    '<h2>VWARD WAN Guard</h2>': '<h2>Состояние WAN</h2>',
    '<h2>VWARD Tunnel Guard</h2>': '<h2>Состояние туннелей</h2>',
    '<h2>VWARD Route Engine</h2>': '<h2>Состояние маршрутизации</h2>',
    '<h2>VWARD Runtime</h2>': '<h2>Среда выполнения</h2>',
    '<h2>VWARD Console</h2>': '<h2>Состояние Console</h2>',
}.items():
    once(old, new, "detail heading " + old)

old_logs = '<section class="section" id="logs"><div class="panel"><h2>Журналы</h2><div class="sub">Не более 200 строк из разрешённых файлов</div><div class="log-tabs"><button class="log-tab active" data-log="wan">WAN</button><button class="log-tab" data-log="recovery">Восстановление</button><button class="log-tab" data-log="cron">Задания</button><button class="log-tab" data-log="routing">Маршруты</button><button class="log-tab" data-log="updater">Обновления</button><button class="log-tab" data-log="tunnel">VPN</button><button class="log-tab" data-log="policy">Политики</button><button class="log-tab" data-log="console">Console</button></div><div class="logbox" id="logbox">Загрузка...</div></div></section>'
new_logs = '<section class="section" id="logs"><div class="panel"><div class="panel-head"><div><h2>Журналы</h2><div class="sub">До 200 последних строк из каждого выбранного источника</div></div><span class="pill" id="logCount">0 строк</span></div><div class="log-toolbar"><div class="log-sources" id="logSources"><label class="log-source selected"><input type="checkbox" data-log="wan" checked>WAN</label><label class="log-source"><input type="checkbox" data-log="recovery">Восстановление</label><label class="log-source"><input type="checkbox" data-log="cron">Задания</label><label class="log-source"><input type="checkbox" data-log="routing">Маршруты</label><label class="log-source"><input type="checkbox" data-log="updater">Обновления</label><label class="log-source"><input type="checkbox" data-log="tunnel">VPN</label><label class="log-source"><input type="checkbox" data-log="policy">Политики</label><label class="log-source"><input type="checkbox" data-log="console">Console</label></div><div class="log-actions"><input class="log-search" id="logSearch" type="search" placeholder="Поиск в журнале" aria-label="Поиск в журнале"><button class="btn" id="logRefresh">Обновить</button><label class="log-auto"><input id="logAuto" type="checkbox" checked> Авто</label><button class="btn" id="logCopy">Копировать</button><button class="btn" id="logSave">Сохранить</button><button class="btn" id="logShare">Поделиться</button></div><div class="log-meta" id="logMeta">Источник: WAN · ещё не обновлялся</div></div><div class="logbox" id="logbox">Откройте раздел, чтобы загрузить журнал.</div></div></section>'
once(old_logs, new_logs, "logs workspace")

once(
    '</nav><div class="toast" id="toast" role="status" aria-live="polite">Готово</div>',
    '</nav><aside class="help-pop" id="helpPanel" role="dialog" aria-label="Подсказка"><div class="help-head"><b id="helpTitle">Подсказка</b><button class="btn" id="helpClose" aria-label="Закрыть">×</button></div><div id="helpText">Данные ещё загружаются.</div></aside><div class="toast" id="toast" role="status" aria-live="polite">Готово</div>',
    "help popover",
)

css = """
.help-pop{position:fixed;right:22px;top:76px;width:min(360px,calc(100vw - 28px));display:none;background:var(--panel);border:1px solid var(--line);border-radius:12px;box-shadow:0 12px 34px rgba(20,32,48,.22);padding:14px;z-index:45;color:var(--text)}.help-pop.show{display:block}.help-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}.help-head .btn{min-height:32px;padding:0 9px}.help-pop #helpText{color:var(--muted);font-size:12px;line-height:1.55}.log-toolbar{margin:14px 0 10px}.log-sources{display:flex;flex-wrap:wrap;gap:7px}.log-source{display:flex;align-items:center;gap:6px;min-height:36px;padding:0 10px;border:1px solid var(--line);border-radius:18px;background:var(--soft);cursor:pointer;font-size:11px}.log-source.selected{border-color:var(--blue);color:var(--blue);background:var(--soft)}.log-source input{accent-color:var(--blue)}.log-actions{display:flex;flex-wrap:wrap;gap:7px;align-items:center;margin-top:10px}.log-search{flex:1 1 220px;min-height:40px;border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:0 11px;outline:0}.log-search:focus{border-color:var(--blue);box-shadow:0 0 0 2px rgba(8,111,197,.16)}.log-auto{display:flex;align-items:center;gap:5px;min-height:40px;padding:0 8px;color:var(--muted);font-size:11px}.log-meta{margin-top:8px;color:var(--muted);font-size:10px}.logbox.loading{opacity:.65}.pill.log-ok{color:var(--green)}
@media(max-width:720px){.help-pop{left:10px;right:10px;top:auto;bottom:88px;width:auto;max-height:55vh;overflow:auto}.log-actions .btn{flex:1 1 calc(33.333% - 7px);padding:0 7px}.log-search{flex-basis:100%}.log-source{min-height:38px}.logbox{min-height:300px;max-height:52vh}}
"""
once("</style>", css + "</style>", "console styles")

old_settings_icon = "settings:'<circle cx=\"12\" cy=\"12\" r=\"3\"/><path d=\"M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a8 8 0 0 0-1.8-1L14.4 3h-4.8l-.3 3.1a8 8 0 0 0-1.8 1l-2.4-1-2 3.4 2 1.5a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a8 8 0 0 0 1.8 1l.3 3.1h4.8l.3-3.1a8 8 0 0 0 1.8-1l2.4 1 2-3.4-2-1.5a7 7 0 0 0 .1-1Z\"/>'"
new_settings_icon = old_settings_icon + ",bulb:'<path d=\"M9 18h6M10 22h4\"/><path d=\"M8.2 14.7A7 7 0 1 1 15.8 14.7C14.7 15.5 14.4 16.2 14.4 17H9.6c0-.8-.3-1.5-1.4-2.3Z\"/>'"
once(old_settings_icon, new_settings_icon, "bulb icon")

old_symbol = "const symbolIcons={'⌂':'home','V':'platform','↻':'update','⌁':'wan','◇':'shield','⇄':'route','◷':'runtime','▣':'console','▱':'storage','≡':'logs','◐':'theme','⚙':'settings'};document.querySelectorAll('.ico,.mobile button span[aria-hidden=\"true\"],.tools button').forEach(function(e){const key=(e.textContent||'').trim();if(symbolIcons[key])e.innerHTML=svgIcon(symbolIcons[key])});"
new_symbol = old_symbol + "$('helpBtn').innerHTML=svgIcon('bulb');"
once(old_symbol, new_symbol, "bulb render")

once(
    "let busy=false,data=null,latency=0,logName='wan',settingsDirty=false;const H=",
    "let busy=false,data=null,latency=0,settingsDirty=false,activeSection='overview',logAuto=true,logRaw={},logUpdated='';const logLabels={wan:'WAN',recovery:'Восстановление',cron:'Задания',routing:'Маршруты',updater:'Обновления',tunnel:'VPN',policy:'Политики',console:'Console'};const H=",
    "state variables",
)

once(
    "function valueOrDash(x){return x===undefined||x===null||x===''?'-':x}function esc(x)",
    "function phaseText(x){return ({COMMITTED:'Установлено',IDLE:'Ожидание',CHECKING:'Проверка',VERIFIED:'Проверено',AVAILABLE:'Доступно обновление',APPLYING:'Установка',ROLLING_BACK:'Откат',ROLLED_BACK:'Откат выполнен',RECOVERING:'Восстановление',FAILED:'Ошибка'}[String(x||'').toUpperCase()]||valueOrDash(x))}function wanClassText(x){return ({HEALTHY:'Норма',OK:'Норма',DEGRADED:'Нестабильно',DOWN:'Нет связи',RECOVERY:'Восстановление',UNKNOWN:'Нет данных'}[String(x||'').toUpperCase()]||valueOrDash(x))}function rcText(x){return String(x)==='0'?'Норма':(x===undefined||x===null||x===''?'-':'Код '+x)}function valueOrDash(x){return x===undefined||x===null||x===''?'-':x}function esc(x)",
    "status helpers",
)

help_js = """function helpMessage(){const d=data||{},p=d.platform||{},w=d.wan||{},g=d.wg||{},s=d.services||{},c=d.cron||{};switch(activeSection){case'overview':return w.internet===true&&s.adaptive_live_count===1?'Все основные контуры отвечают. Если карточка показывает предупреждение, откройте её для причины и связанных данных.':'Есть отклонение. Откройте карточку с предупреждением и проверьте связанный журнал.';case'updater':return 'Update Engine: '+phaseText(p.phase)+'. Автоприменение '+(p.auto_apply?'включено':'выключено')+'. Здесь меняются только четыре проверенные политики автообновления.';case'wan':return w.internet===true?'WAN доступен, вмешательство не требуется. Последний класс: '+wanClassText(w.class)+'.':'WAN недоступен или нестабилен. Сначала проверьте состояние и журнал WAN; опасных команд восстановления в Console пока нет.';case'tunnel':return (g.interfaces||[]).length?'Обнаружено туннелей: '+(g.interfaces||[]).length+'. Fail-open '+(g.failopen_active?'активен':'не активен')+'. Ключи через Console не передаются.':'WireGuard-туннели сейчас не обнаружены. Проверьте VPN-журнал и состояние Runtime.';case'route':return s.adaptive_live_count===1&&s.tcpdump_count===1?'Adaptive Live работает и наблюдает DNS. Обслуживание маршрутов: '+rcText(c.routing_rc)+'.':'Route Engine требует внимания. Проверьте Adaptive Live, наблюдение DNS и журнал маршрутов.';case'runtime':return s.crond&&s.supervisor?'Планировщик и supervisor работают. Runtime поддерживает фоновые задачи VWARD.':'Один из runtime-компонентов не отвечает. Проверьте crond, supervisor и журнал заданий.';case'logs':return 'Выберите один или несколько источников, используйте поиск, затем скопируйте, сохраните или поделитесь текущим отфильтрованным результатом.';case'settings':return 'Изменяемые параметры вынесены в Update Engine. Остальные настройки пока показаны только для чтения, пока нет безопасного backend path.';default:return 'Здесь показано фактическое состояние компонента. Управление появляется только для действий с безопасным allowlisted backend path.'}}function renderHelp(){txt('helpTitle',(M[activeSection]&&M[activeSection][0]?M[activeSection][0]+' · подсказка':'Подсказка'));txt('helpText',helpMessage())}function setHelp(open){$('helpPanel').classList.toggle('show',open);$('helpBtn').setAttribute('aria-expanded',open?'true':'false')}$('helpBtn').onclick=()=>setHelp(!$('helpPanel').classList.contains('show'));$('helpClose').onclick=()=>setHelp(false);document.addEventListener('keydown',e=>{if(e.key==='Escape')setHelp(false)});
"""
if s.count("function go(id){") != 1:
    raise SystemExit("help insertion marker mismatch")
s = s.replace("function go(id){", help_js + "function go(id){", 1)

once(
    "function go(id){if(!$(id)||!M[id])return;document.querySelectorAll('.section').forEach(e=>e.classList.toggle('active',e.id===id));document.querySelectorAll('[data-section]').forEach(e=>{const active=e.dataset.section===id;e.classList.toggle('active',active);if(active)e.setAttribute('aria-current','page');else e.removeAttribute('aria-current')});txt('pageTitle',M[id][0]);txt('pageSub',M[id][1]);if(id==='logs')loadLog(logName);window.scrollTo(0,0)}",
    "function go(id){if(!$(id)||!M[id])return;activeSection=id;document.querySelectorAll('.section').forEach(e=>e.classList.toggle('active',e.id===id));document.querySelectorAll('[data-section]').forEach(e=>{const active=e.dataset.section===id;e.classList.toggle('active',active);if(active)e.setAttribute('aria-current','page');else e.removeAttribute('aria-current')});txt('pageTitle',M[id][0]);txt('pageSub',M[id][1]);if(id==='logs')loadLogs(false);renderHelp();setHelp(false);window.scrollTo(0,0)}",
    "navigation context",
)

once(
    'stroke="var(--blue)" stroke-width="3" vector-effect="non-scaling-stroke"/>',
    'stroke="var(--blue)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>',
    "sparkline smoothing",
)

for old, new, label in [
    ("txt('heroSub','VWARD '+p.version+' · '+p.phase+' · API '+ms+' мс');", "txt('heroSub','VWARD '+p.version+' · '+phaseText(p.phase)+' · API '+ms+' мс');", "hero phase"),
    ("wan:[w.internet===true,w.class,w.internet===true?'В сети':'Нет связи',", "wan:[w.internet===true,wanClassText(w.class),w.internet===true?'В сети':'Нет связи',", "wan card"),
    ("badge('platformPill',up,p.phase);", "badge('platformPill',up,phaseText(p.phase));", "platform phase"),
    ("['Состояние',p.phase]", "['Состояние',phaseText(p.phase)]", "updater state"),
    ("badge('wanPill',w.internet===true,w.class);", "badge('wanPill',w.internet===true,wanClassText(w.class));", "wan pill"),
    ("[['Класс',w.class],['Режим',w.mode],['Действие',w.action]", "[['Состояние',wanClassText(w.class)],['Режим',valueOrDash(w.mode)],['Последнее действие',valueOrDash(w.action)]", "wan stats"),
    ("[['DOWN_STREAK',valueOrDash(g.down_streak)],['FAILOPEN_ACTIVE',g.failopen_active?'Да':'Нет']]", "[['Неудачных проверок подряд',valueOrDash(g.down_streak)],['Fail-open активен',g.failopen_active?'Да':'Нет']]", "tunnel labels"),
    ("[['PID Adaptive Live',s.adaptive_live_pid],['Процессов',s.adaptive_live_count],['Наблюдение DNS',s.tcpdump_count],['Код обслуживания',c.routing_rc],['Последний запуск',c.routing_last]]", "[['Adaptive Live PID',s.adaptive_live_pid],['Процессов Adaptive Live',s.adaptive_live_count],['Наблюдение DNS',s.tcpdump_count===1?'Работает':'Остановлено'],['Обслуживание маршрутов',rcText(c.routing_rc)],['Последний запуск',c.routing_last]]", "route labels"),
    ("[['crond',s.crond?'Работает':'Остановлен'],['Supervisor',s.supervisor?'Работает':'Остановлен'],['AdGuard Home',s.adguard?'Работает':'Остановлен'],['WAN cron RC',c.guardian_rc],['WG cron RC',c.wg_rc],['Route cron RC',c.routing_rc]]", "[['Планировщик crond',s.crond?'Работает':'Остановлен'],['Supervisor',s.supervisor?'Работает':'Остановлен'],['AdGuard Home',s.adguard?'Работает':'Остановлен'],['Проверка WAN',rcText(c.guardian_rc)],['Проверка VPN',rcText(c.wg_rc)],['Маршрутизация',rcText(c.routing_rc)]]", "runtime labels"),
    ("['Состояние',p.phase]", "['Состояние',phaseText(p.phase)]", "settings phase"),
]:
    once(old, new, label)

once(
    "const a=[['auto_apply','Автоматическое применение','Главный переключатель',p.auto_apply],['auto_critical','Critical','Критические обновления',p.auto_critical],['auto_important','Important','Важные обновления',p.auto_important],['auto_routine','Routine','Плановые обновления',p.auto_routine]];",
    "const a=[['auto_apply','Автоматическое применение','Главный переключатель',p.auto_apply],['auto_critical','Критические','Критические обновления',p.auto_critical],['auto_important','Важные','Важные обновления',p.auto_important],['auto_routine','Плановые','Плановые обновления',p.auto_routine]];",
    "update setting labels",
)

old_loader = "async function loadLog(n){logName=n;document.querySelectorAll('.log-tab').forEach(e=>e.classList.toggle('active',e.dataset.log===n));txt('logbox','Загрузка...');try{const r=await fetch('/cgi-bin/api.cgi?action=log&name='+encodeURIComponent(n)+'&_='+Date.now(),{cache:'no-store'});txt('logbox',await r.text())}catch(e){txt('logbox','Журнал недоступен')}}document.querySelectorAll('.log-tab').forEach(e=>e.onclick=()=>loadLog(e.dataset.log));"
new_loader = """function selectedLogs(){return Array.from(document.querySelectorAll('#logSources input[data-log]:checked')).map(e=>e.dataset.log)}function visibleLogText(){const q=($('logSearch').value||'').trim().toLowerCase(),parts=[];selectedLogs().forEach(n=>{const raw=logRaw[n];if(raw===undefined)return;let lines=String(raw).split(/\\r?\\n/);if(q)lines=lines.filter(x=>x.toLowerCase().includes(q));if(lines.length)parts.push('===== '+logLabels[n]+' =====\\n'+lines.join('\\n'))});return parts.join('\\n\\n').trim()}function renderLogs(){const names=selectedLogs(),text=visibleLogText(),lines=text?text.split(/\\r?\\n/).length:0;txt('logbox',text||'Нет строк для выбранных источников и фильтра.');txt('logCount',lines+' строк');$('logCount').className='pill '+(lines?'log-ok':'');txt('logMeta','Источники: '+(names.map(n=>logLabels[n]).join(', ')||'не выбраны')+' · '+(logUpdated?'обновлено '+logUpdated:'ещё не обновлялось'))}async function loadLogs(show=true){const names=selectedLogs();document.querySelectorAll('#logSources .log-source').forEach(x=>x.classList.toggle('selected',x.querySelector('input').checked));if(!names.length){logRaw={};renderLogs();return}$('logbox').classList.add('loading');txt('logbox','Загрузка...');const next={...logRaw};await Promise.all(names.map(async n=>{try{const r=await fetch('/cgi-bin/api.cgi?action=log&name='+encodeURIComponent(n)+'&_='+Date.now(),{cache:'no-store'});next[n]=await r.text()}catch(e){next[n]='Журнал недоступен: '+e.message}}));logRaw=next;logUpdated=new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});$('logbox').classList.remove('loading');renderLogs();if(show)notify('Журналы обновлены');renderHelp()}function fallbackCopy(t){const a=document.createElement('textarea');a.value=t;a.style.position='fixed';a.style.opacity='0';document.body.appendChild(a);a.select();const ok=document.execCommand('copy');a.remove();return ok}document.querySelectorAll('#logSources input[data-log]').forEach(e=>e.onchange=()=>loadLogs(false));$('logSearch').oninput=renderLogs;$('logRefresh').onclick=()=>loadLogs(true);$('logAuto').onchange=e=>{logAuto=e.target.checked;notify(logAuto?'Автообновление включено':'Автообновление выключено')};$('logCopy').onclick=async()=>{const t=visibleLogText();if(!t)return notify('Нет данных для копирования');try{if(navigator.clipboard&&navigator.clipboard.writeText)await navigator.clipboard.writeText(t);else if(!fallbackCopy(t))throw Error('copy');notify('Скопировано')}catch(e){try{fallbackCopy(t)?notify('Скопировано'):notify('Копирование недоступно')}catch(_){notify('Копирование недоступно')}}};$('logSave').onclick=()=>{const t=visibleLogText();if(!t)return notify('Нет данных для сохранения');const d=new Date(),stamp=d.getFullYear()+String(d.getMonth()+1).padStart(2,'0')+String(d.getDate()).padStart(2,'0')+'-'+String(d.getHours()).padStart(2,'0')+String(d.getMinutes()).padStart(2,'0')+String(d.getSeconds()).padStart(2,'0'),a=document.createElement('a');a.href=URL.createObjectURL(new Blob([t+'\\n'],{type:'text/plain;charset=utf-8'}));a.download='VWARD-журнал-'+stamp+'.txt';document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},0);notify('Файл подготовлен')};$('logShare').onclick=async()=>{const t=visibleLogText();if(!t)return notify('Нет данных для отправки');try{const file=new File([t+'\\n'],'VWARD-журнал.txt',{type:'text/plain'});if(navigator.canShare&&navigator.canShare({files:[file]}))await navigator.share({title:'VWARD Журнал',files:[file]});else if(navigator.share)await navigator.share({title:'VWARD Журнал',text:t});else throw Error('unsupported')}catch(e){if(e.name!=='AbortError')notify('Системная отправка недоступна')}};"""
once(old_loader, new_loader, "multi-log loader")

once(
    "$('refreshBtn').onclick=()=>refresh(true);setInterval(refresh,15000);",
    "$('refreshBtn').onclick=()=>refresh(true);setInterval(refresh,15000);setInterval(()=>{if(activeSection==='logs'&&logAuto)loadLogs(false)},30000);",
    "log auto refresh",
)
once(
    "fill(d,Math.round(performance.now()-t));if(show)notify('Данные обновлены')",
    "fill(d,Math.round(performance.now()-t));renderHelp();if(show)notify('Данные обновлены')",
    "help refresh",
)

p.write_text(s, encoding="utf-8")

# Source-level regression checks for every new visible control.
tp = root / "tests/repository/check-console-bindings.py"
t = tp.read_text(encoding="utf-8")
anchor = 'if len(log_tabs) != 8:\n    fail(f"ожидалось 8 вкладок журналов, найдено {len(log_tabs)}")\n'
if t.count(anchor) != 1:
    raise SystemExit("test anchor mismatch")
extra = anchor + '''\nfor marker in ("helpBtn", "helpPanel", "logSearch", "logRefresh", "logAuto", "logCopy", "logSave", "logShare"):\n    if f'id="{marker}"' not in html:\n        fail(f"нет элемента Console: {marker}")\n\nif "navigator.clipboard.writeText" not in html or "fallbackCopy" not in html:\n    fail("копирование журнала не имеет Clipboard/fallback binding")\nif "navigator.share" not in html:\n    fail("поделиться журналом не связано с Web Share API")\n'''
t = t.replace(anchor, extra, 1)
tp.write_text(t, encoding="utf-8")

# Documentation: only implemented behaviour.
dp = root / "docs/CONSOLE.md"
d = dp.read_text(encoding="utf-8")
d = d.replace(
    '- «Журналы»: последние 200 строк из фиксированного списка VWARD-файлов.',
    '- «Журналы»: рабочее представление нескольких разрешённых источников с поиском, копированием, сохранением, системной отправкой и автообновлением.\n- Общая кнопка с лампочкой показывает короткую контекстную подсказку по текущему разделу и фактическому состоянию backend.',
)
d = d.replace(
    'Разрешены только имена `wan`, `recovery`, `cron`, `routing`, `updater`, `tunnel`,\n`policy`, `console`. Каждое имя жёстко связано со своим файлом в `api.cgi`.\nПроизвольный path передать нельзя. Содержимое не выходит за пределы LAN, но может\nсодержать локальные домены, поэтому его нельзя публиковать без проверки.',
    'Разрешены только имена `wan`, `recovery`, `cron`, `routing`, `updater`, `tunnel`,\n`policy`, `console`. Каждое имя жёстко связано со своим файлом в `api.cgi`.\nПроизвольный path передать нельзя. Console может одновременно загрузить несколько\nразрешённых источников, отфильтровать текущий вид по поиску, скопировать его, сохранить\nв TXT или передать через системный Web Share API. Автообновление выполняется только\nпока открыт раздел журналов. Содержимое может включать локальные домены, поэтому перед\nпубликацией его всё равно нужно проверять.',
)
d = d.replace(
    '3. Проверить все восемь вкладок журналов.',
    '3. Проверить все восемь источников журналов, множественный выбор, поиск, копирование, сохранение, Share и автообновление.',
)
dp.write_text(d, encoding="utf-8")

cp = root / "CHANGELOG.md"
c = cp.read_text(encoding="utf-8")
head = '## 0.1.7-dev: критический переходный hotfix VWARD Console\n\n'
if c.count(head) != 1:
    raise SystemExit("changelog anchor mismatch")
bullets = (
    '- Журналы переведены с одиночных вкладок на компактный multi-source workspace: выбор нескольких источников, поиск, счётчик строк, ручное и автоматическое обновление, копирование, TXT-сохранение и системный Share.\n'
    '- Добавлена общая контекстная лампочка-подсказка; текст зависит от открытого раздела и текущего backend-state.\n'
    '- Detail pages очищены от повторяющихся заголовков, видимые статусы и служебные поля частично русифицированы, графики получили скруглённые окончания и соединения.\n'
)
c = c.replace(head, head + bullets, 1)
cp.write_text(c, encoding="utf-8")

print("CONSOLE_POLISH_PATCH=APPLIED")
