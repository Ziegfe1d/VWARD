#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[2]
api_path = root / 'web/cgi-bin/api.cgi'
html_path = root / 'web/index.html'
test_path = root / 'tests/repository/check-console-bindings.py'
doc_path = root / 'docs/CONSOLE.md'
changelog_path = root / 'CHANGELOG.md'

api = api_path.read_text(encoding='utf-8')
html = html_path.read_text(encoding='utf-8')
test = test_path.read_text(encoding='utf-8')
doc = doc_path.read_text(encoding='utf-8')
changelog = changelog_path.read_text(encoding='utf-8')


def once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f'{label}: expected 1 match, found {n}')
    return text.replace(old, new, 1)

# Logs: explicit All/Reset controls requested by the prompt.
html = once(
    html,
    '<div class="log-actions"><input class="log-search" id="logSearch"',
    '<div class="log-actions"><button class="btn" id="logAll">Все</button><button class="btn" id="logReset">Сброс</button><input class="log-search" id="logSearch"',
    'log all/reset buttons',
)

html = once(
    html,
    "document.querySelectorAll('#logSources input[data-log]').forEach(e=>e.onchange=()=>loadLogs(false));$('logSearch').oninput=renderLogs;",
    "document.querySelectorAll('#logSources input[data-log]').forEach(e=>e.onchange=()=>loadLogs(false));$('logAll').onclick=()=>{document.querySelectorAll('#logSources input[data-log]').forEach(x=>x.checked=true);loadLogs(false)};$('logReset').onclick=()=>{document.querySelectorAll('#logSources input[data-log]').forEach(x=>x.checked=false);$('logSearch').value='';loadLogs(false)};$('logSearch').oninput=renderLogs;",
    'log all/reset handlers',
)

html = once(
    html,
    "txt('logMeta','Источники: '+(names.map(n=>logLabels[n]).join(', ')||'не выбраны')+' · '+(logUpdated?'обновлено '+logUpdated:'ещё не обновлялось'))",
    "txt('logMeta','Источники: '+(names.map(n=>logLabels[n]).join(', ')||'не выбраны')+' · '+(logUpdated?'обновлено '+logUpdated:'ещё не обновлялось')+' · авто '+(logAuto?'вкл':'выкл'))",
    'log metadata auto state',
)

# Tunnel Guard: all discovered tunnels remain visible, plus a read-only selector.
html = once(
    html,
    '<div class="actions"><button class="btn" id="tunnelHealthBtn">Проверить туннель</button><button class="btn" data-log-open="tunnel">Открыть журнал VPN</button></div><pre class="action-result" id="tunnelActionResult" hidden></pre>',
    '<div class="panel"><div class="panel-head"><div><h3>Туннели</h3><div class="sub">Read-only просмотр всех обнаруженных WireGuard-интерфейсов</div></div><select class="input" id="tunnelSelect" aria-label="Выбрать WireGuard туннель"></select></div><div class="stats" id="tunnelSelectedStats"></div></div><div class="actions"><button class="btn" id="tunnelHealthBtn">Проверить VWARD-туннель</button><button class="btn" data-log-open="tunnel">Открыть журнал VPN</button></div><pre class="action-result" id="tunnelActionResult" hidden></pre>',
    'tunnel selector',
)

# Route Engine list tools and explicit lifecycle limitation.
html = once(
    html,
    '<div class="two"><div class="panel"><div class="panel-head"><div><h3>Домены и AdaptiveAuto</h3>',
    '<div class="probe-bar"><input id="routeListSearch" class="input" type="search" placeholder="Фильтр доменов и IP-категорий" aria-label="Фильтр списков маршрутизации"><select id="routeListSort" class="input" aria-label="Сортировка списков"><option value="asc">А-Я / A-Z</option><option value="desc">Я-А / Z-A</option></select></div><div class="two"><div class="panel"><div class="panel-head"><div><h3>Домены и AdaptiveAuto</h3>',
    'route list controls',
)

html = once(
    html,
    '<select id="routeProbeType" class="input"><option value="domain">Домен</option><option value="ip">IPv4</option></select><input id="routeProbeValue" class="input" placeholder="example.org" autocomplete="off" spellcheck="false"><button class="btn primary" id="routeProbeBtn">Проверить</button>',
    '<select id="routeProbeType" class="input"><option value="domain">Домен / DNS</option><option value="ip">IPv4</option><option value="group">FQDN-группа</option></select><input id="routeProbeValue" class="input" placeholder="example.org" autocomplete="off" spellcheck="false"><button class="btn primary" id="routeProbeBtn">Проверить / разрешить DNS</button>',
    'route group probe UI',
)

html = once(
    html,
    '<div class="notice">Проверка домена/IP работает read-only. Операции, способные изменить AdaptiveAuto или Policy Sync, требуют явного подтверждения и выполняют только фиксированные VWARD-команды без произвольного shell/ndmc API.</div></section>',
    '<div class="notice">Проверка домена, DNS, IP и FQDN-группы работает read-only. Операции, способные изменить AdaptiveAuto или Policy Sync, требуют явного подтверждения и выполняют только фиксированные VWARD-команды без произвольного shell/ndmc API.</div><div class="notice">Runtime сейчас не хранит отдельную достоверную state-machine очереди «обнаружен → ожидает → обрабатывается → исключён → ошибка». Console показывает только авторитетные persistent/generated state, текущие каталоги и журналы; выдуманные счётчики очереди не создаются.</div></section>',
    'route lifecycle truth notice',
)

# Tunnel read-only selector renderer. Wireguard1 is the managed Tunnel Guard target;
# other discovered tunnels are observation-only until a per-tunnel actuator exists.
html = once(
    html,
    "function interfaceState(x){return x&&(x.link||x.connected||x.state)}function fill(d,ms){",
    "function interfaceState(x){return x&&(x.link||x.connected||x.state)}function renderTunnelSelector(wi,g){const sel=$('tunnelSelect'),prev=sel.value,items=Array.isArray(wi)?wi:[];sel.innerHTML=items.length?items.map(x=>'<option value=\"'+esc(x.name)+'\">'+esc(x.description||x.name)+'</option>').join(''):'<option value=\"\">Туннели не найдены</option>';if(items.some(x=>x.name===prev))sel.value=prev;const x=items.find(v=>v.name===sel.value)||items[0];if(!x){$('tunnelSelectedStats').innerHTML='<div class=\"empty\">WireGuard-интерфейсы не обнаружены</div>';return}const managed=x.name==='Wireguard1';$('tunnelSelectedStats').innerHTML=stat([['Интерфейс',x.name],['Описание',x.description||'-'],['Состояние',online(interfaceState(x))?'В сети':'Не в сети'],['Link',valueOrDash(x.link)],['Connected',valueOrDash(x.connected)],['VWARD Tunnel Guard',managed?'Управляемый туннель':'Только наблюдение'],['Fail-open',managed?(g.failopen_active?'Активен':'Не активен'):'Не относится']])}function fill(d,ms){",
    'tunnel selector renderer',
)

html = once(
    html,
    "badge('tunnelPill',tn>0&&t===tn,t+' из '+tn);$('tunnelStats').innerHTML=stat((wi.length?wi.map(x=>[x.name||'WireGuard',online(interfaceState(x))?'В сети':'Не в сети']):[['WireGuard','Не найден']]).concat([['Неудачных проверок подряд',valueOrDash(g.down_streak)],['Fail-open активен',g.failopen_active?'Да':'Нет']]));",
    "badge('tunnelPill',tn>0&&t===tn,t+' из '+tn);$('tunnelStats').innerHTML=stat((wi.length?wi.map(x=>[x.name||'WireGuard',online(interfaceState(x))?'В сети':'Не в сети']):[['WireGuard','Не найден']]).concat([['Неудачных проверок подряд',valueOrDash(g.down_streak)],['Fail-open активен',g.failopen_active?'Да':'Нет']]));renderTunnelSelector(wi,g);",
    'render tunnel selector in fill',
)

# Preserve selected tunnel view on select change using current status state.
insert_after = "$('wanCheckBtn').onclick=()=>refresh(true);$('tunnelHealthBtn').onclick=()=>postConsoleAction('control','tunnel-health','', 'tunnelActionResult');"
html = once(
    html,
    insert_after,
    insert_after + "$('tunnelSelect').onchange=()=>{const d=data||{};renderTunnelSelector(((d.wg||{}).interfaces)||[],d.wg||{})};",
    'tunnel selector handler',
)

# Route list filtering/sorting, source timestamps and Policy Sync deltas.
old_render_route = "function listRows(items,emptyText){return items&&items.length?items.map(x=>'<div class=\"row\"><b>'+esc(x)+'</b><span></span><span class=\"pill ok\">активно</span></div>').join(''):'<div class=\"empty\">'+esc(emptyText)+'</div>'}function renderRouteData(r){routeData=r;const d=r.domains||{},a=r.adaptive||{},ip=r.ip||{},ds=d.sources||{},ics=ip.source_categories||{};badge('domainCatalogPill',d.unique>0,d.unique?d.unique+' доменов':'Нет данных');$('domainCatalogStats').innerHTML=stat([['Уникальных доменов',d.unique],['Категорий',d.categories],['itdoginfo, записей',ds.itdog],['V2Fly, записей',ds.v2fly],['AdaptiveAuto',a.count],['Всего связей',d.rows]]);$('adaptiveDomainList').innerHTML='<div class=\"sub\" style=\"margin:12px 0 6px\">Последние домены AdaptiveAuto</div>'+listRows(a.recent||[],'AdaptiveAuto пока пуст');badge('ipCatalogPill',ip.categories>0,ip.active_count+' активных');$('ipCatalogStats').innerHTML=stat([['IP/CIDR категорий',ip.categories],['CIDR в каталоге',ip.cidr_total],['Активных категорий',ip.active_count],['Маршрутов Policy Sync',ip.managed_routes],['itdoginfo, категорий',ics.itdog],['Loyalsoldier, категорий',ics.loyalsoldier]]);$('activeIpCategoryList').innerHTML='<div class=\"sub\" style=\"margin:12px 0 6px\">Активные IP-категории</div>'+listRows(ip.active||[],'Активных IP-категорий пока нет');const when=new Date();txt('routeDataUpdated','Обновлено '+when.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}));renderHelp()}"
new_render_route = "function listRows(items,emptyText){return items&&items.length?items.map(x=>'<div class=\"row\"><b>'+esc(x)+'</b><span></span><span class=\"pill ok\">активно</span></div>').join(''):'<div class=\"empty\">'+esc(emptyText)+'</div>'}function routeItems(items){const q=($('routeListSearch').value||'').trim().toLowerCase(),dir=$('routeListSort').value==='desc'?-1:1;return [...(items||[])].filter(x=>!q||String(x).toLowerCase().includes(q)).sort((a,b)=>String(a).localeCompare(String(b),'ru')*dir)}function syncMetric(s,k){const m=String(s||'').match(new RegExp('(?:^|\\s)'+k+'=([0-9]+)'));return m?m[1]:'-'}function renderRouteData(r){routeData=r;const d=r.domains||{},a=r.adaptive||{},ip=r.ip||{},ds=d.sources||{},ics=ip.source_categories||{};badge('domainCatalogPill',d.unique>0,d.unique?d.unique+' доменов':'Нет данных');$('domainCatalogStats').innerHTML=stat([['Уникальных доменов',d.unique],['Категорий',d.categories],['itdoginfo, записей',ds.itdog],['V2Fly, записей',ds.v2fly],['AdaptiveAuto',a.count],['Всего связей',d.rows],['Последнее обновление',d.last_update||'-']]);$('adaptiveDomainList').innerHTML='<div class=\"sub\" style=\"margin:12px 0 6px\">Домены AdaptiveAuto · ограниченный persistent view</div>'+listRows(routeItems(a.recent||[]),'AdaptiveAuto пока пуст');badge('ipCatalogPill',ip.categories>0,ip.active_count+' активных');$('ipCatalogStats').innerHTML=stat([['IP/CIDR категорий',ip.categories],['CIDR в каталоге',ip.cidr_total],['Активных категорий',ip.active_count],['Маршрутов Policy Sync',ip.managed_routes],['itdoginfo, категорий',ics.itdog],['Loyalsoldier, категорий',ics.loyalsoldier],['Добавлено / удалено',syncMetric(ip.last_sync,'added')+' / '+syncMetric(ip.last_sync,'removed')],['Последняя сверка',ip.last_sync||'-']]);$('activeIpCategoryList').innerHTML='<div class=\"sub\" style=\"margin:12px 0 6px\">Активные IP-категории</div>'+listRows(routeItems(ip.active||[]),'Активных IP-категорий пока нет');const when=new Date();txt('routeDataUpdated','Обновлено '+when.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}));renderHelp()}"
html = once(html, old_render_route, new_render_route, 'route renderer filter/deltas')

html = once(
    html,
    "$('routeDataRefresh').onclick=()=>loadRouteData(true);",
    "$('routeDataRefresh').onclick=()=>loadRouteData(true);$('routeListSearch').oninput=()=>{if(routeData)renderRouteData(routeData)};$('routeListSort').onchange=()=>{if(routeData)renderRouteData(routeData)};",
    'route filter handlers',
)

# Route probe placeholder/button semantics for group vs domain/IP.
html = once(
    html,
    "$('routeProbeType').onchange=()=>{$('routeProbeValue').placeholder=$('routeProbeType').value==='domain'?'example.org':'203.0.113.10'};",
    "$('routeProbeType').onchange=()=>{const t=$('routeProbeType').value;$('routeProbeValue').placeholder=t==='domain'?'example.org':t==='ip'?'203.0.113.10':'domain-list1';$('routeProbeBtn').textContent=t==='domain'?'Проверить / разрешить DNS':'Проверить'};",
    'probe placeholder handler',
)

html = once(
    html,
    "function renderProbe(x){if(x.type==='domain'){const hints=(x.hints||[]).map(h=>h.source+' / '+h.category+' · '+h.match),routes=(x.routes||[]).map(r=>r.group+' → '+r.interface);$('routeProbeResult').innerHTML=stat([['Домен',x.value],['IPv4',(x.dns&&x.dns.ipv4||[]).join(', ')||'Не разрешён'],['AdaptiveAuto',x.adaptive_auto?'Да':'Нет'],['Группы',(x.groups||[]).join(', ')||'Нет'],['Маршрут',routes.join(', ')||'Прямое правило не найдено'],['Каталог',hints.join('; ')||'Совпадений нет']])}else{$('routeProbeResult').innerHTML=stat([['IPv4',x.value],['Policy Sync',(x.policy_matches||[]).map(m=>m.category+' '+m.cidr).join('; ')||'Совпадений нет'],['Owned CIDR',x.owned_cidr||'Нет'],['Настроенный маршрут',x.configured_route?'Да':'Нет'],['Интерфейс',x.interface||'Не определён']])}}",
    "function renderProbe(x){if(x.type==='domain'){const hints=(x.hints||[]).map(h=>h.source+' / '+h.category+' · '+h.match),routes=(x.routes||[]).map(r=>r.group+' → '+r.interface);$('routeProbeResult').innerHTML=stat([['Домен',x.value],['IPv4',(x.dns&&x.dns.ipv4||[]).join(', ')||'Не разрешён'],['AdaptiveAuto',x.adaptive_auto?'Да':'Нет'],['Группы',(x.groups||[]).join(', ')||'Нет'],['Маршрут',routes.join(', ')||'Прямое правило не найдено'],['Каталог',hints.join('; ')||'Совпадений нет']])}else if(x.type==='ip'){$('routeProbeResult').innerHTML=stat([['IPv4',x.value],['Policy Sync',(x.policy_matches||[]).map(m=>m.category+' '+m.cidr).join('; ')||'Совпадений нет'],['Owned CIDR',x.owned_cidr||'Нет'],['Настроенный маршрут',x.configured_route?'Да':'Нет'],['Интерфейс',x.interface||'Не определён']])}else{$('routeProbeResult').innerHTML=stat([['FQDN-группа',x.group||x.value],['Участников',x.member_count],['Показано',(x.members||[]).length],['Домены',(x.members||[]).join(', ')||'Группа пуста'],['Маршруты',(x.routes||[]).join(', ')||'Не назначены']])}}",
    'group probe renderer',
)

# API: preserve raw group case and add exact, bounded FQDN-group inspection.
api = once(
    api,
    '''    TYPE="$(qget type)"
    VALUE="$(qget value | tr '[:upper:]' '[:lower:]')"
    [ "${#VALUE}" -le 253 ] || {
''',
    '''    TYPE="$(qget type)"
    RAW_VALUE="$(qget value)"
    VALUE="$RAW_VALUE"
    [ "$TYPE" = group ] || VALUE="$(printf '%s' "$VALUE" | tr '[:upper:]' '[:lower:]')"
    [ "${#VALUE}" -le 253 ] || {
''',
    'route probe raw group value',
)

group_branch = r'''        group)
            case "$VALUE" in
                ''|*[!A-Za-z0-9._-]*)
                    echo '{"ok":false,"error":"invalid_group"}'
                    exit 0
                    ;;
            esac
            GROUP_NAME="$(awk -v wanted="$VALUE" '$1=="object-group" && $2=="fqdn" && tolower($3)==tolower(wanted){print $3; exit}' "$RUNCFG")"
            [ -n "$GROUP_NAME" ] || {
                echo '{"ok":false,"error":"group_not_found"}'
                exit 0
            }
            MEMBER_COUNT="$(awk -v wanted="$GROUP_NAME" '
                $1=="object-group" && $2=="fqdn" {g=$3; next}
                $1=="!" {g=""; next}
                g==wanted && $1=="include" {n++}
                END{print n+0}
            ' "$RUNCFG")"
            MEMBERS_JSON="$(awk -v wanted="$GROUP_NAME" '
                $1=="object-group" && $2=="fqdn" {g=$3; next}
                $1=="!" {g=""; next}
                g==wanted && $1=="include" {print $2}
            ' "$RUNCFG" | sort -u | head -n 100 | "$JQ" -Rsc 'split("\n")|map(select(length>0))')"
            ROUTES_JSON="$(awk -v g="$GROUP_NAME" '$1=="route" && $2=="object-group" && $3==g {print $4}' "$RUNCFG" | sort -u | "$JQ" -Rsc 'split("\n")|map(select(length>0))')"
            "$JQ" -n --arg type group --arg value "$VALUE" --arg group "$GROUP_NAME" \
              --argjson member_count "$MEMBER_COUNT" --argjson members "$MEMBERS_JSON" --argjson routes "$ROUTES_JSON" \
              '{ok:true,type:$type,value:$value,group:$group,member_count:$member_count,members:$members,routes:$routes}'
            ;;
'''
api = once(api, '        *)\n            echo \'{"ok":false,"error":"invalid_probe_type"}\'\n', group_branch + '        *)\n            echo \'{"ok":false,"error":"invalid_probe_type"}\'\n', 'group probe backend')

# Structured numeric metrics from allowlisted action output, while retaining bounded text.
api = once(
    api,
    '''    OUT_JSON="$(printf '%s' "$SAFE_OUT" | "$JQ" -Rs .)"
    if [ "$RC" -eq 0 ]; then OK=true; else OK=false; fi
    printf '{"ok":%s,"action":"%s","rc":%s,"output":%s}\\n' "$OK" "$LABEL" "$RC" "$OUT_JSON"
''',
    '''    OUT_JSON="$(printf '%s' "$SAFE_OUT" | "$JQ" -Rs .)"
    METRICS_JSON="$(printf '%s\\n' "$SAFE_OUT" | "$JQ" -Rn '[inputs | select(test("^[A-Z][A-Z0-9_]*=-?[0-9]+$")) | split("=") | {(.[0]):(.[1]|tonumber)}] | add // {}' 2>/dev/null)"
    [ -n "$METRICS_JSON" ] || METRICS_JSON='{}'
    if [ "$RC" -eq 0 ]; then OK=true; else OK=false; fi
    printf '{"ok":%s,"action":"%s","rc":%s,"metrics":%s,"output":%s}\\n' "$OK" "$LABEL" "$RC" "$METRICS_JSON" "$OUT_JSON"
''',
    'structured action metrics',
)

# Tests for the actual missing prompt items.
test_add = r'''
for marker in ("logAll", "logReset", "tunnelSelect", "tunnelSelectedStats", "routeListSearch", "routeListSort"):
    if f'id="{marker}"' not in html:
        fail(f"нет финального элемента prompt-gap closure: {marker}")
if '<option value="group">FQDN-группа</option>' not in html or 'group_not_found' not in api:
    fail("FQDN group probe is incomplete")
if 'METRICS_JSON=' not in api:
    fail("control actions do not expose structured numeric metrics")
if 'Runtime сейчас не хранит отдельную достоверную state-machine очереди' not in html:
    fail("Route Engine lifecycle limitation is not disclosed")
'''
test = once(test, '\nnode = shutil.which("node")\n', '\n' + test_add + '\nnode = shutil.which("node")\n', 'prompt gap tests')

doc += '''\n## Финальное закрытие control-plane требований\n\nЖурналы имеют явные «Все» и «Сброс». Tunnel Guard показывает selector всех\nобнаруженных WireGuard-интерфейсов, но ручной health probe остаётся привязан к\nуправляемому VWARD-туннелю; остальные интерфейсы read-only, пока нет безопасного\nper-tunnel actuator.\n\nRoute Engine добавляет локальный фильтр/сортировку ограниченных списков, время\nобновления доменных источников, последнюю Policy Sync сверку и её `added/removed`.\n`route-probe` поддерживает домен/DNS, IPv4 и точную FQDN-группу. Групповой probe\nвозвращает не более 100 участников и назначенные интерфейсы маршрутов.\n\nТекущий Adaptive Live не сохраняет отдельный структурированный lifecycle для очереди\n`discovered/pending/processing/excluded/error`; Console намеренно не синтезирует такие\nсчётчики из логов. Они появятся только после добавления authoritative runtime state.\nТакже нет отдельного безопасного «обновить один компонент»: VWARD Update Engine\nустанавливает подписанный component-aware package как одну транзакцию. Console не\nобходит эту модель.\n'''

if 'Prompt gap closure: log All/Reset, tunnel selector, route list filter/sort' not in changelog:
    changelog = changelog.replace('## [Unreleased]\n', '## [Unreleased]\n\n- Prompt gap closure: log All/Reset, tunnel selector, route list filter/sort, FQDN group probe and structured action metrics.\n', 1)

api_path.write_text(api, encoding='utf-8')
html_path.write_text(html, encoding='utf-8')
test_path.write_text(test, encoding='utf-8')
doc_path.write_text(doc, encoding='utf-8')
changelog_path.write_text(changelog, encoding='utf-8')
print('CONSOLE_GAP_CLOSE=APPLIED')
