#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[2]

# --- API: add a fixed read-only route-data endpoint. ---
ap = root / 'web/cgi-bin/api.cgi'
a = ap.read_text(encoding='utf-8')

def replace_once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f'{label}: expected 1 match, found {n}')
    return text.replace(old, new, 1)

a = replace_once(a, '    status|ping|log|settings) ;;', '    status|ping|log|settings|route-data) ;;', 'API allowlist')

route_api = r'''if [ "$ACTION" = "route-data" ]; then
    header_json

    [ "${REQUEST_METHOD:-GET}" = GET ] || {
        echo '{"ok":false,"error":"method_not_allowed"}'
        exit 0
    }

    HINT_CATALOG=/opt/etc/adaptive-route/hints-catalog.tsv
    ADAPTIVE_PERSIST=/opt/var/lib/adaptive-live/adaptive-persist.txt
    IP_INDEX=/opt/var/lib/vpn-subnets/catalog.index
    IP_ACTIVE=/opt/var/lib/vpn-subnets/active.categories
    IP_OWNED=/opt/var/lib/vpn-subnets/owned.dynamic.routes
    IP_ITDOG=/opt/var/lib/vpn-subnets/source-catalog/itdog
    IP_LOYAL=/opt/var/lib/vpn-subnets/source-catalog/loyalsoldier

    DOMAIN_ROWS=0
    DOMAIN_UNIQUE=0
    DOMAIN_CATEGORIES=0
    DOMAIN_ITDOG=0
    DOMAIN_V2FLY=0

    if [ -r "$HINT_CATALOG" ]; then
        HSTATS="$(awk -F'|' '
            NF>=3 {
                rows++
                domains[$1]=1
                categories[$3]=1
                sources[$2]++
            }
            END {
                dc=0; cc=0
                for (x in domains) dc++
                for (x in categories) cc++
                printf "%d|%d|%d|%d|%d", rows+0,dc+0,cc+0,sources["itdog"]+0,sources["v2fly"]+0
            }
        ' "$HINT_CATALOG" 2>/dev/null)"
        DOMAIN_ROWS="$(printf '%s' "$HSTATS" | cut -d'|' -f1)"
        DOMAIN_UNIQUE="$(printf '%s' "$HSTATS" | cut -d'|' -f2)"
        DOMAIN_CATEGORIES="$(printf '%s' "$HSTATS" | cut -d'|' -f3)"
        DOMAIN_ITDOG="$(printf '%s' "$HSTATS" | cut -d'|' -f4)"
        DOMAIN_V2FLY="$(printf '%s' "$HSTATS" | cut -d'|' -f5)"
    fi

    ADAPTIVE_COUNT="$(wc -l < "$ADAPTIVE_PERSIST" 2>/dev/null)"
    [ -n "$ADAPTIVE_COUNT" ] || ADAPTIVE_COUNT=0
    ADAPTIVE_RECENT="$(
        if [ -r "$ADAPTIVE_PERSIST" ]; then
            tail -n 20 "$ADAPTIVE_PERSIST" 2>/dev/null |
            "$JQ" -Rsc 'split("\n") | map(select(length>0))'
        else
            echo '[]'
        fi
    )"

    IP_CATEGORIES=0
    IP_CIDR_TOTAL=0
    if [ -r "$IP_INDEX" ]; then
        ISTATS="$(awk -F'|' 'NF>=2 {c++; n+=$2} END {printf "%d|%d",c+0,n+0}' "$IP_INDEX" 2>/dev/null)"
        IP_CATEGORIES="$(printf '%s' "$ISTATS" | cut -d'|' -f1)"
        IP_CIDR_TOTAL="$(printf '%s' "$ISTATS" | cut -d'|' -f2)"
    fi

    ACTIVE_COUNT="$(wc -l < "$IP_ACTIVE" 2>/dev/null)"
    MANAGED_ROUTES="$(wc -l < "$IP_OWNED" 2>/dev/null)"
    [ -n "$ACTIVE_COUNT" ] || ACTIVE_COUNT=0
    [ -n "$MANAGED_ROUTES" ] || MANAGED_ROUTES=0

    ACTIVE_CATEGORIES="$(
        if [ -r "$IP_ACTIVE" ]; then
            head -n 40 "$IP_ACTIVE" 2>/dev/null |
            "$JQ" -Rsc 'split("\n") | map(select(length>0))'
        else
            echo '[]'
        fi
    )"

    ITDOG_IP_CATEGORIES="$(find "$IP_ITDOG" -type f -name '*.cidr' 2>/dev/null | wc -l)"
    LOYAL_IP_CATEGORIES="$(find "$IP_LOYAL" -type f -name '*.cidr' 2>/dev/null | wc -l)"
    [ -n "$ITDOG_IP_CATEGORIES" ] || ITDOG_IP_CATEGORIES=0
    [ -n "$LOYAL_IP_CATEGORIES" ] || LOYAL_IP_CATEGORIES=0

    HINT_LAST="$(tail -n 1 /opt/var/log/adaptive-hints-update.log 2>/dev/null)"
    IP_LAST="$(tail -n 1 /opt/var/log/vpn-subnet-sync.log 2>/dev/null)"

    "$JQ" -n \
      --arg ts "$(date '+%Y-%m-%dT%H:%M:%S%z')" \
      --arg hint_last "$HINT_LAST" \
      --arg ip_last "$IP_LAST" \
      --argjson domain_rows "$DOMAIN_ROWS" \
      --argjson domain_unique "$DOMAIN_UNIQUE" \
      --argjson domain_categories "$DOMAIN_CATEGORIES" \
      --argjson domain_itdog "$DOMAIN_ITDOG" \
      --argjson domain_v2fly "$DOMAIN_V2FLY" \
      --argjson adaptive_count "$ADAPTIVE_COUNT" \
      --argjson adaptive_recent "$ADAPTIVE_RECENT" \
      --argjson ip_categories "$IP_CATEGORIES" \
      --argjson ip_cidr_total "$IP_CIDR_TOTAL" \
      --argjson active_count "$ACTIVE_COUNT" \
      --argjson managed_routes "$MANAGED_ROUTES" \
      --argjson active_categories "$ACTIVE_CATEGORIES" \
      --argjson itdog_ip_categories "$ITDOG_IP_CATEGORIES" \
      --argjson loyal_ip_categories "$LOYAL_IP_CATEGORIES" \
      '{
        ok:true,
        ts:$ts,
        domains:{
            rows:$domain_rows,
            unique:$domain_unique,
            categories:$domain_categories,
            sources:{itdog:$domain_itdog,v2fly:$domain_v2fly},
            last_update:$hint_last
        },
        adaptive:{count:$adaptive_count,recent:$adaptive_recent},
        ip:{
            categories:$ip_categories,
            cidr_total:$ip_cidr_total,
            active_count:$active_count,
            managed_routes:$managed_routes,
            source_categories:{itdog:$itdog_ip_categories,loyalsoldier:$loyal_ip_categories},
            active:$active_categories,
            last_sync:$ip_last
        }
      }'
    exit 0
fi

'''
marker = 'if [ "$ACTION" = "ping" ]; then\n'
if a.count(marker) != 1:
    raise SystemExit('API route-data insertion marker mismatch')
a = a.replace(marker, route_api + marker, 1)
ap.write_text(a, encoding='utf-8')

# --- Frontend: enrich Route Engine page, still read-only. ---
hp = root / 'web/index.html'
h = hp.read_text(encoding='utf-8')
old_route = '<section class="section" id="route"><button class="back" data-go="overview">← Назад к обзору</button><div class="panel"><div class="panel-head"><div><h2>Состояние маршрутизации</h2><div class="sub">Adaptive Live и обслуживание маршрутов</div></div><span class="pill" id="routePill">-</span></div><div class="stats" id="routeStats"></div><div class="wide" data-chart="route"></div></div><div class="notice">Постоянное состояние остаётся источником фактических данных. Редактор доменов не включён без отдельной транзакционной записи.</div></section>'
new_route = '<section class="section" id="route"><button class="back" data-go="overview">← Назад к обзору</button><div class="panel"><div class="panel-head"><div><h2>Состояние маршрутизации</h2><div class="sub">Adaptive Live и обслуживание маршрутов</div></div><span class="pill" id="routePill">-</span></div><div class="stats" id="routeStats"></div><div class="wide" data-chart="route"></div></div><div class="two"><div class="panel"><div class="panel-head"><div><h3>Домены и AdaptiveAuto</h3><div class="sub">Каталоги itdoginfo + V2Fly и фактически выученные домены</div></div><span class="pill" id="domainCatalogPill">-</span></div><div class="stats" id="domainCatalogStats"><div class="empty">Загрузка по открытию раздела</div></div><div class="components" id="adaptiveDomainList"></div></div><div class="panel"><div class="panel-head"><div><h3>IP/CIDR и Policy Sync</h3><div class="sub">Каталог itdoginfo + Loyalsoldier и активированные категории</div></div><span class="pill" id="ipCatalogPill">-</span></div><div class="stats" id="ipCatalogStats"><div class="empty">Загрузка по открытию раздела</div></div><div class="components" id="activeIpCategoryList"></div></div></div><div class="actions"><span class="sub" id="routeDataUpdated">Сведения ещё не загружены</span><button class="btn" id="routeDataRefresh">Обновить сведения</button></div><div class="notice">Это только фактическое read-only состояние каталогов VWARD. Редактор доменов, IP и маршрутов не включён без отдельного безопасного backend path.</div></section>'
h = replace_once(h, old_route, new_route, 'Route detail page')

h = replace_once(h,
    "let busy=false,data=null,latency=0,settingsDirty=false,activeSection='overview',logAuto=true,logRaw={},logUpdated='';",
    "let busy=false,data=null,latency=0,settingsDirty=false,activeSection='overview',logAuto=true,logRaw={},logUpdated='',routeDataBusy=false,routeData=null;",
    'Route frontend state')

old_go = "if(id==='logs')loadLogs(false);renderHelp();setHelp(false);window.scrollTo(0,0)"
new_go = "if(id==='logs')loadLogs(false);if(id==='route')loadRouteData(false);renderHelp();setHelp(false);window.scrollTo(0,0)"
h = replace_once(h, old_go, new_go, 'Route data navigation')

route_js = r'''function listRows(items,emptyText){return items&&items.length?items.map(x=>'<div class="row"><b>'+esc(x)+'</b><span></span><span class="pill ok">активно</span></div>').join(''):'<div class="empty">'+esc(emptyText)+'</div>'}function renderRouteData(r){routeData=r;const d=r.domains||{},a=r.adaptive||{},ip=r.ip||{},ds=d.sources||{},ics=ip.source_categories||{};badge('domainCatalogPill',d.unique>0,d.unique?d.unique+' доменов':'Нет данных');$('domainCatalogStats').innerHTML=stat([['Уникальных доменов',d.unique],['Категорий',d.categories],['itdoginfo, записей',ds.itdog],['V2Fly, записей',ds.v2fly],['AdaptiveAuto',a.count],['Всего связей',d.rows]]);$('adaptiveDomainList').innerHTML='<div class="sub" style="margin:12px 0 6px">Последние домены AdaptiveAuto</div>'+listRows(a.recent||[],'AdaptiveAuto пока пуст');badge('ipCatalogPill',ip.categories>0,ip.active_count+' активных');$('ipCatalogStats').innerHTML=stat([['IP/CIDR категорий',ip.categories],['CIDR в каталоге',ip.cidr_total],['Активных категорий',ip.active_count],['Маршрутов Policy Sync',ip.managed_routes],['itdoginfo, категорий',ics.itdog],['Loyalsoldier, категорий',ics.loyalsoldier]]);$('activeIpCategoryList').innerHTML='<div class="sub" style="margin:12px 0 6px">Активные IP-категории</div>'+listRows(ip.active||[],'Активных IP-категорий пока нет');const when=new Date();txt('routeDataUpdated','Обновлено '+when.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}));renderHelp()}async function loadRouteData(show=true){if(routeDataBusy)return;routeDataBusy=true;$('routeDataRefresh').disabled=true;txt('routeDataUpdated','Получение фактических каталогов...');try{const r=await fetch('/cgi-bin/api.cgi?action=route-data&_='+Date.now(),{cache:'no-store'}),x=await r.json();if(!x.ok)throw Error(x.error||'route_data_failed');renderRouteData(x);if(show)notify('Сведения маршрутизации обновлены')}catch(e){txt('routeDataUpdated','Ошибка: '+e.message);badge('domainCatalogPill',false,'Недоступно');badge('ipCatalogPill',false,'Недоступно')}finally{routeDataBusy=false;$('routeDataRefresh').disabled=false}}$('routeDataRefresh').onclick=()=>loadRouteData(true);
'''
anchor = "function renderSettings(p){"
if h.count(anchor) != 1:
    raise SystemExit('Route JS insertion marker mismatch')
h = h.replace(anchor, route_js + anchor, 1)

# Contextual help gets catalog counts when already loaded.
old_help = "case'route':return s.adaptive_live_count===1&&s.tcpdump_count===1?'Adaptive Live работает и наблюдает DNS. Обслуживание маршрутов: '+rcText(c.routing_rc)+'.':'Route Engine требует внимания. Проверьте Adaptive Live, наблюдение DNS и журнал маршрутов.';"
new_help = "case'route':{const rd=routeData||{},dd=rd.domains||{},ii=rd.ip||{};return s.adaptive_live_count===1&&s.tcpdump_count===1?'Adaptive Live работает и наблюдает DNS. Каталог: '+valueOrDash(dd.unique)+' доменов, '+valueOrDash(ii.active_count)+' активных IP-категорий. Обслуживание маршрутов: '+rcText(c.routing_rc)+'.':'Route Engine требует внимания. Проверьте Adaptive Live, наблюдение DNS и журнал маршрутов.';}"
h = replace_once(h, old_help, new_help, 'Route help')
hp.write_text(h, encoding='utf-8')

# --- Tests: route-data binding + permanent JS syntax check when Node is available. ---
tp = root / 'tests/repository/check-console-bindings.py'
t = tp.read_text(encoding='utf-8')
if 'import shutil' not in t:
    t = t.replace('import re\n', 'import re\nimport shutil\nimport subprocess\nimport tempfile\n', 1)
anchor = 'if "navigator.share" not in html:\n    fail("поделиться журналом не связано с Web Share API")\n'
extra = anchor + '''\nif 'action=route-data' not in html or 'route-data)' not in api:\n    fail("Route Engine read-only data endpoint is not bound")\nif 'id="routeDataRefresh"' not in html:\n    fail("Route Engine data refresh control is missing")\n\nnode = shutil.which("node")\nif node:\n    start = html.find("<script>")\n    end = html.find("</script>", start + 8)\n    if start < 0 or end < 0:\n        fail("inline Console JavaScript block is missing")\n    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as f:\n        f.write(html[start + len("<script>"):end])\n        js_path = f.name\n    result = subprocess.run([node, "--check", js_path], capture_output=True, text=True)\n    if result.returncode != 0:\n        fail("Console JavaScript syntax: " + (result.stderr.strip() or result.stdout.strip()))\n'''
if t.count(anchor) != 1:
    raise SystemExit('Console test anchor mismatch')
t = t.replace(anchor, extra, 1)
tp.write_text(t, encoding='utf-8')

# --- Docs and changelog. ---
dp = root / 'docs/CONSOLE.md'
d = dp.read_text(encoding='utf-8')
d = d.replace('- «Защита WAN», «Защита VPN», «Маршрутизация», «Среда выполнения»: read-only данные;', '- «Защита WAN», «Защита VPN», «Маршрутизация», «Среда выполнения»: read-only данные;\n- «Маршрутизация» дополнительно показывает сводку доменного каталога, AdaptiveAuto, IP/CIDR-каталога и активных категорий Policy Sync;')
d = d.replace('WAN, WireGuard и маршрутизация доступны только для чтения. API не принимает команды\nshell, произвольные paths или команды `ndmc`.', 'WAN, WireGuard и маршрутизация доступны только для чтения. `route-data` читает только\nфиксированные generated/state paths VWARD и не принимает path или команду от frontend.\nAPI не принимает произвольные shell-команды, paths или команды `ndmc`.')
dp.write_text(d, encoding='utf-8')

cp = root / 'CHANGELOG.md'
c = cp.read_text(encoding='utf-8')
head = '## 0.1.7-dev: критический переходный hotfix VWARD Console\n\n'
bullet = '- Route Engine получил read-only сводку фактических доменных и IP/CIDR-каталогов: источники, категории, AdaptiveAuto, активные IP-категории и количество маршрутов Policy Sync без расширения mutation API.\n'
if c.count(head) != 1:
    raise SystemExit('Changelog anchor mismatch')
c = c.replace(head, head + bullet, 1)
cp.write_text(c, encoding='utf-8')

print('ROUTE_READONLY_PATCH=APPLIED')
