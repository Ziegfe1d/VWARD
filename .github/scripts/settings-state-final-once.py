#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[2]
api_path = root / 'web/cgi-bin/api.cgi'
html_path = root / 'web/index.html'
test_path = root / 'tests/repository/check-console-bindings.py'
consistency_path = root / 'tests/repository/run-consistency-checks.sh'
doc_path = root / 'docs/CONSOLE.md'
changelog_path = root / 'CHANGELOG.md'

api = api_path.read_text(encoding='utf-8')
html = html_path.read_text(encoding='utf-8')
test = test_path.read_text(encoding='utf-8')
consistency = consistency_path.read_text(encoding='utf-8')
doc = doc_path.read_text(encoding='utf-8')
changelog = changelog_path.read_text(encoding='utf-8')


def once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f'{label}: expected 1 match, found {n}')
    return text.replace(old, new, 1)

# ------------------------------------------------------------------
# API: updater state/action availability + bounded log tail count.
# ------------------------------------------------------------------
api = once(
    api,
    '    status|ping|log|settings|route-data|diagnostics|route-probe|control|update-control) ;;',
    '    status|ping|log|settings|route-data|diagnostics|route-probe|update-data|control|update-control) ;;',
    'update-data allowlist',
)

update_data = r'''
if [ "$ACTION" = "update-data" ]; then
    header_json
    [ "${REQUEST_METHOD:-GET}" = GET ] || {
        echo '{"ok":false,"error":"method_not_allowed"}'
        exit 0
    }

    STATE=/opt/var/lib/vward/updater
    JOURNAL=$STATE/journal.state
    PENDING_DIR=$STATE/pending
    RUN_LOCK=/opt/var/run/vward/updater.lock
    PHASE="$(sed -n 's/^phase=//p' "$JOURNAL" 2>/dev/null | tail -n 1)"
    [ -n "$PHASE" ] || PHASE=IDLE

    BUSY=false
    OWNER="$(sed -n '1p' "$RUN_LOCK/owner" 2>/dev/null)"
    PID="${OWNER%%:*}"
    case "$PID" in
        ''|*[!0-9]*) ;;
        *)
            if kill -0 "$PID" 2>/dev/null && [ -r "/proc/$PID/cmdline" ] &&
               tr '\000' ' ' < "/proc/$PID/cmdline" | grep -q 'vward-update'; then
                BUSY=true
            fi
            ;;
    esac

    PENDING=false
    PENDING_VERSION=""
    PENDING_PRIORITY=""
    PENDING_SEQUENCE=""
    if [ -r "$PENDING_DIR/manifest.json" ] && [ -r "$PENDING_DIR/pending.state" ]; then
        if "$JQ" -e '.signed.version and .signed.priority and .signed.sequence' "$PENDING_DIR/manifest.json" >/dev/null 2>&1; then
            PENDING=true
            PENDING_VERSION="$($JQ -r '.signed.version' "$PENDING_DIR/manifest.json" 2>/dev/null)"
            PENDING_PRIORITY="$($JQ -r '.signed.priority' "$PENDING_DIR/manifest.json" 2>/dev/null)"
            PENDING_SEQUENCE="$($JQ -r '.signed.sequence' "$PENDING_DIR/manifest.json" 2>/dev/null)"
        fi
    fi

    ACTIVE_BACKUP="$(sed -n 's/^active_backup=//p' "$JOURNAL" 2>/dev/null | tail -n 1)"
    ROLLBACK=false
    case "$ACTIVE_BACKUP" in
        /opt/var/backups/vward/*)
            [ -r "$ACTIVE_BACKUP/files.tsv" ] && [ -r "$ACTIVE_BACKUP/backup.meta" ] && ROLLBACK=true
            ;;
    esac

    UPDATE_ENABLED="$(sed -n 's/^update_enabled=//p' /opt/etc/vward/update.conf 2>/dev/null | tail -n 1)"
    [ "$UPDATE_ENABLED" = 1 ] || UPDATE_ENABLED=0

    CHECK_ALLOWED=false
    APPLY_ALLOWED=false
    RETRY_ALLOWED=false
    ROLLBACK_ALLOWED=false
    RECOVER_ALLOWED=false

    if [ "$BUSY" = false ] && [ "$UPDATE_ENABLED" = 1 ]; then
        CHECK_ALLOWED=true
        if [ "$PENDING" = true ]; then
            case "$PHASE" in
                AVAILABLE|VERIFIED|IDLE|COMMITTED) APPLY_ALLOWED=true ;;
                FAILED) RETRY_ALLOWED=true ;;
            esac
        fi
        [ "$ROLLBACK" = true ] && ROLLBACK_ALLOWED=true
        case "$PHASE" in
            INSTALLING|VERIFYING|ROLLING_BACK|RECOVERY_REQUIRED|COMMIT_PREPARED|CHECKING|VERIFIED|BACKING_UP)
                RECOVER_ALLOWED=true
                ;;
        esac
    fi

    "$JQ" -n \
      --arg phase "$PHASE" \
      --arg version "$PENDING_VERSION" \
      --arg priority "$PENDING_PRIORITY" \
      --arg sequence "$PENDING_SEQUENCE" \
      --argjson busy "$BUSY" \
      --argjson pending "$PENDING" \
      --argjson rollback "$ROLLBACK" \
      --argjson check_allowed "$CHECK_ALLOWED" \
      --argjson apply_allowed "$APPLY_ALLOWED" \
      --argjson retry_allowed "$RETRY_ALLOWED" \
      --argjson rollback_allowed "$ROLLBACK_ALLOWED" \
      --argjson recover_allowed "$RECOVER_ALLOWED" \
      '{ok:true,phase:$phase,busy:$busy,pending:{present:$pending,version:$version,priority:$priority,sequence:$sequence},rollback_available:$rollback,allowed:{check:$check_allowed,apply:$apply_allowed,retry:$retry_allowed,rollback:$rollback_allowed,recover:$recover_allowed}}'
    exit 0
fi
'''

api = once(api, 'if [ "$ACTION" = "control" ] || [ "$ACTION" = "update-control" ]; then\n', update_data + '\nif [ "$ACTION" = "control" ] || [ "$ACTION" = "update-control" ]; then\n', 'insert update-data')

# Server-side state preconditions for updater mutations.
api = once(
    api,
    '''    else
        CMD=/opt/share/vward/updater/current/vward-update.sh
        case "$OP" in
            check) ARG=--check; LABEL=update-check ;;
            apply) ARG=--apply-pending; REQUIRED=APPLY_UPDATE; LABEL=update-apply ;;
            retry) ARG=--apply-pending; REQUIRED=RETRY_UPDATE; LABEL=update-retry ;;
            rollback) ARG=--rollback; REQUIRED=ROLLBACK_UPDATE; LABEL=update-rollback ;;
            recover) ARG=--recover; REQUIRED=RECOVER_UPDATE; LABEL=update-recover ;;
            *) echo '{"ok":false,"error":"unknown_update_action"}'; exit 0 ;;
        esac
    fi
''',
    '''    else
        CMD=/opt/share/vward/updater/current/vward-update.sh
        USTATE=/opt/var/lib/vward/updater
        UPHASE="$(sed -n 's/^phase=//p' "$USTATE/journal.state" 2>/dev/null | tail -n 1)"
        [ -n "$UPHASE" ] || UPHASE=IDLE
        UPENDING=0
        [ -r "$USTATE/pending/manifest.json" ] && [ -r "$USTATE/pending/pending.state" ] && UPENDING=1
        UBACKUP="$(sed -n 's/^active_backup=//p' "$USTATE/journal.state" 2>/dev/null | tail -n 1)"
        UROLLBACK=0
        case "$UBACKUP" in /opt/var/backups/vward/*) [ -r "$UBACKUP/files.tsv" ] && [ -r "$UBACKUP/backup.meta" ] && UROLLBACK=1 ;; esac
        case "$OP" in
            check) ARG=--check; LABEL=update-check ;;
            apply)
                [ "$UPENDING" -eq 1 ] || { echo '{"ok":false,"error":"no_pending_update"}'; exit 0; }
                case "$UPHASE" in AVAILABLE|VERIFIED|IDLE|COMMITTED) ;; *) echo '{"ok":false,"error":"state_action_not_allowed"}'; exit 0 ;; esac
                ARG=--apply-pending; REQUIRED=APPLY_UPDATE; LABEL=update-apply
                ;;
            retry)
                [ "$UPENDING" -eq 1 ] && [ "$UPHASE" = FAILED ] || { echo '{"ok":false,"error":"state_action_not_allowed"}'; exit 0; }
                ARG=--apply-pending; REQUIRED=RETRY_UPDATE; LABEL=update-retry
                ;;
            rollback)
                [ "$UROLLBACK" -eq 1 ] || { echo '{"ok":false,"error":"rollback_unavailable"}'; exit 0; }
                ARG=--rollback; REQUIRED=ROLLBACK_UPDATE; LABEL=update-rollback
                ;;
            recover)
                case "$UPHASE" in INSTALLING|VERIFYING|ROLLING_BACK|RECOVERY_REQUIRED|COMMIT_PREPARED|CHECKING|VERIFIED|BACKING_UP) ;; *) echo '{"ok":false,"error":"recovery_not_required"}'; exit 0 ;; esac
                ARG=--recover; REQUIRED=RECOVER_UPDATE; LABEL=update-recover
                ;;
            *) echo '{"ok":false,"error":"unknown_update_action"}'; exit 0 ;;
        esac
    fi
''',
    'updater server preconditions',
)

# Tail limit is user-selectable but server bounded to 20..200.
api = once(
    api,
    '''    header_text

    if [ -n "$FILE" ] && [ -r "$FILE" ]; then
        tail -n 200 "$FILE" 2>/dev/null
''',
    '''    COUNT="$(qget count)"
    case "$COUNT" in ''|*[!0-9]*) COUNT=200 ;; esac
    [ "$COUNT" -ge 20 ] 2>/dev/null && [ "$COUNT" -le 200 ] 2>/dev/null || COUNT=200

    header_text

    if [ -n "$FILE" ] && [ -r "$FILE" ]; then
        tail -n "$COUNT" "$FILE" 2>/dev/null
''',
    'bounded log count',
)

# Settings save result exposes only safe metadata, no backup path.
api = once(api, "    echo '{\"ok\":true,\"result\":\"saved\"}'\n", "    echo '{\"ok\":true,\"result\":\"saved\",\"verified\":true,\"backup_created\":true,\"requires_restart\":false}'\n", 'settings save result')

# ------------------------------------------------------------------
# HTML: settings layer + update action state gating.
# ------------------------------------------------------------------
old_settings = '<section class="section" id="settings"><button class="back" data-go="overview">← Назад к обзору</button><div class="panel"><div class="panel-head"><div><h2>Настройки и диагностика</h2><div class="sub">Безопасный обзор параметров VWARD</div></div><span class="pill ok">Только VWARD</span></div><div class="settings-grid"><div><h3>Устройство</h3><div class="stats" id="settingsDevice"></div></div><div><h3>Подключения</h3><div class="stats" id="settingsNetwork"></div></div><div><h3>Обновления</h3><div class="stats" id="settingsUpdate"></div><div class="actions"><button class="btn primary" data-go="updater">Изменить политику обновлений</button></div></div><div><h3>Диагностика</h3><div class="stats" id="settingsDiagnostics"></div><div class="actions"><button class="btn" id="runDiagnostics">Запустить диагностику</button></div></div></div><div class="notice">Изменять можно только четыре проверенных параметра Update Engine. Настройки WAN, WireGuard и маршрутизации показаны без возможности записи.</div></div></section>'
new_settings = '''<section class="section" id="settings"><button class="back" data-go="overview">← Назад к обзору</button><div class="panel"><div class="panel-head"><div><h2>Настройки и диагностика</h2><div class="sub">Безопасный settings layer VWARD</div></div><span class="pill ok">Только VWARD</span></div><div class="settings-search"><input class="input" id="settingsSearch" type="search" placeholder="Поиск по настройкам" aria-label="Поиск по настройкам"></div><div class="settings-grid" id="settingsGrid"><div class="settings-block" data-settings-search="устройство модель keeneticos версия файловая система read only"><h3>Устройство <span class="pill">READ ONLY</span></h3><div class="stats" id="settingsDevice"></div></div><div class="settings-block" data-settings-search="подключения wan ipv4 wireguard маршрутизация read only"><h3>Подключения <span class="pill">READ ONLY</span></h3><div class="stats" id="settingsNetwork"></div></div><div class="settings-block" data-settings-search="обновления update engine политика editable авто критические важные плановые"><h3>VWARD Update Engine <span class="pill ok">EDITABLE</span></h3><div class="stats" id="settingsUpdate"></div><div class="actions"><button class="btn primary" data-go="updater">Изменить политику обновлений</button></div></div><div class="settings-block" data-settings-search="console интерфейс тема плотность масштаб анимация refresh"><h3>VWARD Console <span class="pill ok">LOCAL</span></h3><div class="local-settings"><label class="setting"><span><b>Тема</b><small>Локально в браузере · restart не требуется</small></span><select class="input" id="prefTheme"><option value="system">Системная</option><option value="light">Светлая</option><option value="dark">Тёмная</option></select></label><label class="setting"><span><b>Компактный режим</b><small>Уменьшает внутренние отступы</small></span><span class="switch"><input id="prefCompact" type="checkbox"><i></i></span></label><label class="setting"><span><b>Минимум анимации</b><small>Локальная настройка доступности</small></span><span class="switch"><input id="prefMotion" type="checkbox"><i></i></span></label><label class="setting"><span><b>Обновление статусов</b><small>Период опроса Console API</small></span><select class="input" id="prefRefresh"><option value="15">15 сек</option><option value="30">30 сек</option><option value="60">60 сек</option></select></label></div></div><div class="settings-block" data-settings-search="журналы автообновление строки перенос tail interval"><h3>Журналы <span class="pill ok">LOCAL</span></h3><div class="local-settings"><label class="setting"><span><b>Интервал автообновления</b><small>Работает только при включённом «Авто»</small></span><select class="input" id="prefLogInterval"><option value="15">15 сек</option><option value="30">30 сек</option><option value="60">60 сек</option><option value="120">120 сек</option></select></label><label class="setting"><span><b>Строк на источник</b><small>Backend ограничивает диапазон 20..200</small></span><select class="input" id="prefLogCount"><option value="50">50</option><option value="100">100</option><option value="150">150</option><option value="200">200</option></select></label><label class="setting"><span><b>Перенос длинных строк</b><small>Выключи для горизонтального scroll</small></span><span class="switch"><input id="prefLogWrap" type="checkbox" checked><i></i></span></label></div></div><div class="settings-block" data-settings-search="диагностика проверка компоненты runtime wan vpn route update"><h3>Диагностика <span class="pill">READ ONLY</span></h3><div class="stats" id="settingsDiagnostics"></div><div class="actions"><button class="btn" id="runDiagnostics">Запустить диагностику</button></div></div></div><div class="notice">Backend-изменение разрешено только для четырёх параметров VWARD Update Engine. Настройки интерфейса и журналов локальны для браузера. WAN, WireGuard и routing config остаются read-only.</div></div></section>'''
html = once(html, old_settings, new_settings, 'settings layer')

# Update action status line.
html = once(
    html,
    '<div class="actions action-wrap"><button class="btn" data-update-op="check">Проверить сейчас</button>',
    '<div class="sub update-action-state" id="updateActionState">Проверяем доступные действия...</div><div class="actions action-wrap"><button class="btn" data-update-op="check">Проверить сейчас</button>',
    'update action state line',
)

# Extra settings styles.
html = once(
    html,
    '</style>',
    '''.settings-search{margin:14px 0}.settings-search .input{width:100%}.settings-block{min-width:0}.settings-block h3{display:flex;gap:8px;align-items:center}.local-settings{border-top:1px solid var(--line);margin-top:9px}.local-settings .input{min-width:118px}.update-action-state{margin-top:12px}.logbox.nowrap{white-space:pre;overflow:auto}[data-density=compact] .panel{padding:13px}[data-density=compact] .card{padding:11px;min-height:158px}[data-density=compact] .stat{padding:9px}[data-motion=reduce] *,[data-motion=reduce] *:before,[data-motion=reduce] *:after{transition:none!important;animation:none!important;scroll-behavior:auto!important}@media(max-width:720px){.local-settings .setting{gap:12px}.local-settings .input{max-width:45%}}\n</style>''',
    'settings styles',
)

# State variables include preferences/timers/update state.
html = once(
    html,
    "let busy=false,data=null,latency=0,settingsDirty=false,activeSection='overview',logAuto=true,logRaw={},logUpdated='',routeDataBusy=false,routeData=null;",
    "let busy=false,data=null,latency=0,settingsDirty=false,activeSection='overview',logAuto=true,logRaw={},logUpdated='',routeDataBusy=false,routeData=null,updateData=null,refreshTimer=null,logTimer=null,prefs={theme:'system',compact:false,motion:false,refresh:15,logInterval:30,logCount:200,logWrap:true};",
    'state vars prefs',
)

# Updater section lazy loads allowed action state.
html = once(
    html,
    "if(id==='logs')loadLogs(false);if(id==='route')loadRouteData(false);renderHelp();setHelp(false);window.scrollTo(0,0)",
    "if(id==='logs')loadLogs(false);if(id==='route')loadRouteData(false);if(id==='updater')loadUpdateData(false);renderHelp();setHelp(false);window.scrollTo(0,0)",
    'go updater state',
)

# Insert update-data loader before existing updater actions.
marker = "const updateConfirm={apply:"
if html.count(marker) != 1:
    raise SystemExit('update loader marker mismatch')
update_js = r'''function renderUpdateData(x){updateData=x;const a=x.allowed||{},p=x.pending||{};document.querySelectorAll('[data-update-op]').forEach(b=>{const op=b.dataset.updateOp;b.hidden=!Boolean(a[op]);b.disabled=Boolean(x.busy)});const bits=['Состояние: '+phaseText(x.phase)];if(x.busy)bits.push('идёт операция');if(p.present)bits.push('pending '+valueOrDash(p.version)+' · '+valueOrDash(p.priority)+' · seq '+valueOrDash(p.sequence));if(x.rollback_available)bits.push('rollback доступен');txt('updateActionState',bits.join(' · '))}async function loadUpdateData(show=true){try{const r=await fetch('/cgi-bin/api.cgi?action=update-data&_='+Date.now(),{cache:'no-store'}),x=await r.json();if(!x.ok)throw Error(x.error);renderUpdateData(x);if(show)notify('Состояние Update Engine обновлено')}catch(e){txt('updateActionState','Не удалось определить доступные действия: '+e.message);document.querySelectorAll('[data-update-op]').forEach(b=>{b.hidden=b.dataset.updateOp!=='check'})}}
'''
html = html.replace(marker, update_js + marker, 1)

# Action completion refreshes updater availability.
html = once(
    html,
    "if(activeSection==='route')loadRouteData(false);return x",
    "if(activeSection==='route')loadRouteData(false);if(activeSection==='updater')loadUpdateData(false);return x",
    'refresh update actions after mutation',
)

# Updater settings: source/restart metadata + cancel.
old_render_settings = "function renderSettings(p){if(settingsDirty)return;const a=[['auto_apply','Автоматическое применение','Главный переключатель',p.auto_apply],['auto_critical','Критические','Критические обновления',p.auto_critical],['auto_important','Важные','Важные обновления',p.auto_important],['auto_routine','Плановые','Плановые обновления',p.auto_routine]];$('updaterForm').innerHTML=a.map(x=>'<label class=\"setting\"><span><b>'+x[1]+'</b><small>'+x[2]+'</small></span><span class=\"switch\"><input name=\"'+x[0]+'\" type=\"checkbox\" '+(x[3]?'checked':'')+'><i></i></span></label>').join('')+'<div class=\"actions\"><span class=\"sub\" id=\"saveState\">Без изменений</span><button class=\"btn primary\" type=\"submit\">Сохранить</button></div>'}"
new_render_settings = "function renderSettings(p){if(settingsDirty)return;const a=[['auto_apply','Автоматическое применение','Главный переключатель',p.auto_apply],['auto_critical','Критические','Критические обновления',p.auto_critical],['auto_important','Важные','Важные обновления',p.auto_important],['auto_routine','Плановые','Плановые обновления',p.auto_routine]];$('updaterForm').innerHTML=a.map(x=>'<label class=\"setting\"><span><b>'+x[1]+'</b><small>'+x[2]+' · /opt/etc/vward/update.conf · restart не требуется</small></span><span class=\"switch\"><input name=\"'+x[0]+'\" type=\"checkbox\" '+(x[3]?'checked':'')+'><i></i></span></label>').join('')+'<div class=\"actions\"><span class=\"sub\" id=\"saveState\">Без изменений</span><button class=\"btn\" type=\"button\" id=\"cancelSettings\">Отмена</button><button class=\"btn primary\" type=\"submit\">Сохранить</button></div>';$('cancelSettings').onclick=()=>{settingsDirty=false;renderSettings(((data||{}).platform)||{});notify('Изменения отменены')}}"
html = once(html, old_render_settings, new_render_settings, 'render settings cancel metadata')

# Replace fixed polling with preference-driven timers.
html = once(
    html,
    "$('refreshBtn').onclick=()=>refresh(true);setInterval(refresh,15000);setInterval(()=>{if(activeSection==='logs'&&logAuto)loadLogs(false)},30000);",
    "$('refreshBtn').onclick=()=>refresh(true);function restartTimers(){if(refreshTimer)clearInterval(refreshTimer);if(logTimer)clearInterval(logTimer);refreshTimer=setInterval(refresh,Math.max(15,Number(prefs.refresh)||15)*1000);logTimer=setInterval(()=>{if(activeSection==='logs'&&logAuto)loadLogs(false)},Math.max(15,Number(prefs.logInterval)||30)*1000)}",
    'dynamic timers',
)

# Log backend count preference.
html = once(
    html,
    "fetch('/cgi-bin/api.cgi?action=log&name='+encodeURIComponent(n)+'&_='+Date.now(),{cache:'no-store'})",
    "fetch('/cgi-bin/api.cgi?action=log&name='+encodeURIComponent(n)+'&count='+encodeURIComponent(prefs.logCount)+'&_='+Date.now(),{cache:'no-store'})",
    'log count query',
)

# Local settings/search/preference initialization inserted before theme handler.
theme_marker = "$('themeBtn').onclick=()=>{const t=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=t;try{localStorage.setItem('vward-theme',t)}catch(e){}};try{document.documentElement.dataset.theme=localStorage.getItem('vward-theme')||'light'}catch(e){}"
if html.count(theme_marker) != 1:
    raise SystemExit('theme marker mismatch')
prefs_js = r'''function systemTheme(){return window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}function applyPrefs(){document.documentElement.dataset.theme=prefs.theme==='system'?systemTheme():prefs.theme;document.documentElement.dataset.density=prefs.compact?'compact':'normal';document.documentElement.dataset.motion=prefs.motion?'reduce':'normal';$('logbox').classList.toggle('nowrap',!prefs.logWrap);if($('prefTheme'))$('prefTheme').value=prefs.theme;if($('prefCompact'))$('prefCompact').checked=prefs.compact;if($('prefMotion'))$('prefMotion').checked=prefs.motion;if($('prefRefresh'))$('prefRefresh').value=String(prefs.refresh);if($('prefLogInterval'))$('prefLogInterval').value=String(prefs.logInterval);if($('prefLogCount'))$('prefLogCount').value=String(prefs.logCount);if($('prefLogWrap'))$('prefLogWrap').checked=prefs.logWrap;restartTimers()}function loadPrefs(){try{const raw=JSON.parse(localStorage.getItem('vward-prefs')||'{}');prefs={...prefs,...raw}}catch(e){};const theme=prefs.theme; if(!['system','light','dark'].includes(theme))prefs.theme='system';if(![15,30,60].includes(Number(prefs.refresh)))prefs.refresh=15;if(![15,30,60,120].includes(Number(prefs.logInterval)))prefs.logInterval=30;if(![50,100,150,200].includes(Number(prefs.logCount)))prefs.logCount=200;prefs.compact=Boolean(prefs.compact);prefs.motion=Boolean(prefs.motion);prefs.logWrap=prefs.logWrap!==false}function savePrefs(){try{localStorage.setItem('vward-prefs',JSON.stringify(prefs))}catch(e){}applyPrefs()}loadPrefs();applyPrefs();if(window.matchMedia){const mq=window.matchMedia('(prefers-color-scheme: dark)');if(mq.addEventListener)mq.addEventListener('change',()=>{if(prefs.theme==='system')applyPrefs()})}$('settingsSearch').oninput=e=>{const q=e.target.value.trim().toLowerCase();document.querySelectorAll('#settingsGrid .settings-block').forEach(b=>{b.hidden=q&&!((b.dataset.settingsSearch||'')+' '+b.textContent).toLowerCase().includes(q)})};$('prefTheme').onchange=e=>{prefs.theme=e.target.value;savePrefs()};$('prefCompact').onchange=e=>{prefs.compact=e.target.checked;savePrefs()};$('prefMotion').onchange=e=>{prefs.motion=e.target.checked;savePrefs()};$('prefRefresh').onchange=e=>{prefs.refresh=Number(e.target.value);savePrefs()};$('prefLogInterval').onchange=e=>{prefs.logInterval=Number(e.target.value);savePrefs()};$('prefLogCount').onchange=e=>{prefs.logCount=Number(e.target.value);savePrefs();if(activeSection==='logs')loadLogs(false)};$('prefLogWrap').onchange=e=>{prefs.logWrap=e.target.checked;savePrefs()};$('themeBtn').onclick=()=>{prefs.theme=(document.documentElement.dataset.theme==='dark'?'light':'dark');savePrefs()};'''
html = html.replace(theme_marker, prefs_js, 1)

# Settings save feedback uses structured backend result.
html = once(
    html,
    "settingsDirty=false;notify('Настройки сохранены');await refresh();txt('saveState','Сохранено')",
    "settingsDirty=false;notify('Настройки сохранены');await refresh();txt('saveState',x.verified&&x.backup_created?'Сохранено · проверено · backup создан':'Сохранено')",
    'settings save feedback',
)

# ------------------------------------------------------------------
# Tests and docs.
# ------------------------------------------------------------------
test_add = r'''
for marker in ("settingsSearch", "prefTheme", "prefRefresh", "prefLogInterval", "prefLogCount", "prefLogWrap", "updateActionState"):
    if f'id="{marker}"' not in html:
        fail(f"нет settings/update-state элемента: {marker}")
if 'action=update-data' not in html or 'update-data' not in api:
    fail("Update Engine action availability endpoint is not bound")
if 'state_action_not_allowed' not in api or 'rollback_unavailable' not in api or 'recovery_not_required' not in api:
    fail("Update Engine server-side state preconditions are incomplete")
if "count='+encodeURIComponent(prefs.logCount)" not in html:
    fail("bounded log tail preference is not bound")
'''
test = once(test, '\nnode = shutil.which("node")\n', '\n' + test_add + '\nnode = shutil.which("node")\n', 'final settings tests')

consistency = once(
    consistency,
    "if(id==='logs')loadLogs(false);if(id==='route')loadRouteData(false);renderHelp();setHelp(false);window.scrollTo(0,0)",
    "if(id==='logs')loadLogs(false);if(id==='route')loadRouteData(false);if(id==='updater')loadUpdateData(false);renderHelp();setHelp(false);window.scrollTo(0,0)",
    'navigation consistency update-data',
)

doc += '''\n## Settings layer и доступность Update Engine actions\n\nРаздел Settings различает три типа значений: `READ ONLY` для фактического состояния\nроутера, `EDITABLE` для четырёх разрешённых параметров VWARD Update Engine и `LOCAL`\nдля настроек интерфейса/журналов, сохраняемых только в браузере. Есть поиск по\nнастройкам. Локально настраиваются тема, компактность, минимум анимации, polling\nConsole, интервал автообновления журналов, 50/100/150/200 строк на источник и перенос\nдлинных строк. Backend жёстко ограничивает log tail диапазоном 20..200.\n\n`update-data` читает только updater state/pending/backup/lock и возвращает набор\nразрешённых действий. Console скрывает операции, которые сейчас не разрешены.\n`update-control` повторяет критические precondition checks server-side: apply требует\npending manifest и допустимую фазу, rollback требует валидный recorded backup, recovery\nпоказывается только для прерванных transaction phases. Окончательные trust/signature/\nsequence/compatibility проверки остаются внутри VWARD Update Engine.\n'''

if 'Settings layer: searchable read-only/editable/local preferences' not in changelog:
    changelog = changelog.replace('## [Unreleased]\n', '## [Unreleased]\n\n- Settings layer: searchable read-only/editable/local preferences, bounded log tail controls and state-gated Update Engine actions.\n', 1)

api_path.write_text(api, encoding='utf-8')
html_path.write_text(html, encoding='utf-8')
test_path.write_text(test, encoding='utf-8')
consistency_path.write_text(consistency, encoding='utf-8')
doc_path.write_text(doc, encoding='utf-8')
changelog_path.write_text(changelog, encoding='utf-8')
print('SETTINGS_STATE_FINAL_PATCH=APPLIED')
