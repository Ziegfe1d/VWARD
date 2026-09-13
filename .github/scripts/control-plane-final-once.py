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

# ---------------- API: explicit actions only ----------------
api = once(
    api,
    '    status|ping|log|settings|route-data) ;;',
    '    status|ping|log|settings|route-data|diagnostics|route-probe|control|update-control) ;;',
    'api action allowlist',
)

api = once(
    api,
    '''if [ "${REQUEST_METHOD:-GET}" = POST ] && [ "$ACTION" != settings ]; then
    echo 'Status: 405 Method Not Allowed'
    header_json
    echo '{"ok":false,"error":"method_not_allowed"}'
    exit 0
fi
''',
    '''if [ "${REQUEST_METHOD:-GET}" = POST ]; then
    case "$ACTION" in
        settings|control|update-control) ;;
        *)
            echo 'Status: 405 Method Not Allowed'
            header_json
            echo '{"ok":false,"error":"method_not_allowed"}'
            exit 0
            ;;
    esac
fi
''',
    'api post allowlist',
)

# Reject unknown settings keys instead of silently ignoring them.
api = once(
    api,
    '''    BODY=$(dd bs=1 count="$LENGTH" 2>/dev/null)

    value()
''',
    '''    BODY=$(dd bs=1 count="$LENGTH" 2>/dev/null)

    UNKNOWN_KEYS="$(printf '%s\\n' "$BODY" | tr '&' '\\n' | cut -d= -f1 | awk '$0!="auto_apply" && $0!="auto_critical" && $0!="auto_important" && $0!="auto_routine" {print; exit}')"
    [ -z "$UNKNOWN_KEYS" ] || {
        echo '{"ok":false,"error":"unknown_parameter"}'
        exit 0
    }

    value()
''',
    'settings unknown key guard',
)

backend_block = r'''
if [ "$ACTION" = "diagnostics" ]; then
    header_json
    [ "${REQUEST_METHOD:-GET}" = GET ] || {
        echo '{"ok":false,"error":"method_not_allowed"}'
        exit 0
    }

    diag_status()
    {
        if "$@" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi
    }

    OPT_STATUS="$(diag_status df -Pk /opt)"
    JQ_STATUS="$(diag_status command -v "$JQ")"
    CURL_STATUS="$(diag_status command -v "$CURL")"
    TCPDUMP_STATUS="$(diag_status command -v tcpdump)"
    LIGHTTPD_STATUS="$(diag_status command -v lighttpd)"
    CROND_STATUS=FAIL
    SUPERVISOR_STATUS=FAIL
    ADGUARD_STATUS=FAIL
    ADAPTIVE_STATUS=FAIL
    ps 2>/dev/null | grep -q '[c]rond -b' && CROND_STATUS=PASS
    ps 2>/dev/null | grep -q '[c]rond-supervisor.sh' && SUPERVISOR_STATUS=PASS
    ps 2>/dev/null | grep -q '[A]dGuardHome' && ADGUARD_STATUS=PASS
    ps 2>/dev/null | grep -q '[a]gh-adaptive-live.sh' && ADAPTIVE_STATUS=PASS

    UPDATE_STATUS=FAIL
    [ -x /opt/share/vward/updater/current/vward-update.sh ] && UPDATE_STATUS=PASS
    CONFIG_STATUS=FAIL
    [ -r /opt/etc/vward/update.conf ] && CONFIG_STATUS=PASS
    CGI_STATUS=PASS

    WAN_JSON="$(fetch_json 'http://127.0.0.1:79/rci/show/internet/status')"
    WAN_STATUS="$(printf '%s\\n' "$WAN_JSON" | "$JQ" -r 'if (.internet // .connected // false) == true then "PASS" else "WARN" end' 2>/dev/null)"
    case "$WAN_STATUS" in PASS|WARN) ;; *) WAN_STATUS=UNKNOWN ;; esac

    IF_JSON="$(fetch_json 'http://127.0.0.1:79/rci/show/interface')"
    WG_COUNT="$(printf '%s\\n' "$IF_JSON" | "$JQ" -r '[keys[] | select(test("^Wireguard[0-9]+$"))] | length' 2>/dev/null)"
    case "$WG_COUNT" in ''|*[!0-9]*) WG_COUNT=0 ;; esac
    [ "$WG_COUNT" -gt 0 ] && WG_STATUS=PASS || WG_STATUS=WARN

    OPT_FREE="$(df -Pk /opt 2>/dev/null | awk 'NR==2 {print $4+0}')"
    [ -n "$OPT_FREE" ] || OPT_FREE=0
    LAST_WAN_RC="$(cat /tmp/wan-guardian.cron.rc 2>/dev/null)"
    LAST_WG_RC="$(cat /tmp/wg-health-chain.cron.rc 2>/dev/null)"
    LAST_ROUTE_RC="$(cat /tmp/adaptive-auto-maint.cron.rc 2>/dev/null)"

    "$JQ" -n \
      --arg opt "$OPT_STATUS" --arg jq "$JQ_STATUS" --arg curl "$CURL_STATUS" \
      --arg tcpdump "$TCPDUMP_STATUS" --arg lighttpd "$LIGHTTPD_STATUS" \
      --arg crond "$CROND_STATUS" --arg supervisor "$SUPERVISOR_STATUS" \
      --arg adguard "$ADGUARD_STATUS" --arg adaptive "$ADAPTIVE_STATUS" \
      --arg updater "$UPDATE_STATUS" --arg config "$CONFIG_STATUS" --arg cgi "$CGI_STATUS" \
      --arg wan "$WAN_STATUS" --arg wg "$WG_STATUS" \
      --arg wan_rc "$LAST_WAN_RC" --arg wg_rc "$LAST_WG_RC" --arg route_rc "$LAST_ROUTE_RC" \
      --argjson wg_count "$WG_COUNT" --argjson opt_free "$OPT_FREE" \
      '{ok:true,checks:[
        {id:"console-api",component:"console",label:"Console API",status:$cgi,detail:"CGI отвечает"},
        {id:"opt",component:"runtime",label:"Хранилище /opt",status:$opt,detail:("Свободно КБ: "+($opt_free|tostring))},
        {id:"jq",component:"runtime",label:"jq",status:$jq,detail:"JSON обработчик"},
        {id:"curl",component:"runtime",label:"curl",status:$curl,detail:"HTTP клиент"},
        {id:"tcpdump",component:"route-engine",label:"tcpdump",status:$tcpdump,detail:"Наблюдение DNS"},
        {id:"lighttpd",component:"console",label:"lighttpd",status:$lighttpd,detail:"Локальный web server"},
        {id:"crond",component:"runtime",label:"crond",status:$crond,detail:("Последний WAN RC: "+$wan_rc)},
        {id:"supervisor",component:"runtime",label:"VWARD Runtime supervisor",status:$supervisor,detail:"Контроль crond"},
        {id:"adguard",component:"route-engine",label:"AdGuard Home",status:$adguard,detail:"DNS service"},
        {id:"adaptive",component:"route-engine",label:"Adaptive Live",status:$adaptive,detail:("Последний route RC: "+$route_rc)},
        {id:"wan",component:"wan-guard",label:"WAN",status:$wan,detail:"Read-only RCI probe"},
        {id:"wg",component:"tunnel-guard",label:"WireGuard",status:$wg,detail:("Найдено туннелей: "+($wg_count|tostring)+"; cron RC: "+$wg_rc)},
        {id:"updater",component:"update-engine",label:"VWARD Update Engine",status:$updater,detail:"Активный updater slot"},
        {id:"update-config",component:"update-engine",label:"Update config",status:$config,detail:"Конфигурация доступна для чтения"}
      ]}'
    exit 0
fi

if [ "$ACTION" = "route-probe" ]; then
    header_json
    [ "${REQUEST_METHOD:-GET}" = GET ] || {
        echo '{"ok":false,"error":"method_not_allowed"}'
        exit 0
    }

    TYPE="$(qget type)"
    VALUE="$(qget value | tr '[:upper:]' '[:lower:]')"
    [ "${#VALUE}" -le 253 ] || {
        echo '{"ok":false,"error":"value_too_long"}'
        exit 0
    }

    HINT_CATALOG=/opt/etc/adaptive-route/hints-catalog.tsv
    ADAPTIVE_PERSIST=/opt/var/lib/adaptive-live/adaptive-persist.txt
    IP_CATALOG=/opt/var/lib/vpn-subnets/catalog
    IP_ACTIVE=/opt/var/lib/vpn-subnets/active.categories
    IP_OWNED=/opt/var/lib/vpn-subnets/owned.dynamic.routes
    RUNCFG=/tmp/vward-console-route-probe.$$
    ndmc -c "show running-config" 2>/dev/null | tr -d '\r' > "$RUNCFG"
    trap 'rm -f "$RUNCFG"' EXIT INT TERM

    valid_ipv4()
    {
        printf '%s\\n' "$1" | awk -F. 'NF==4 {for(i=1;i<=4;i++){if($i !~ /^[0-9]+$/ || $i<0 || $i>255) exit 1} exit 0} {exit 1}'
    }

    ip_matches_file()
    {
        IP="$1" FILE="$2" awk '
        function ipn(s,a){split(s,a,"."); return ((a[1]*256+a[2])*256+a[3])*256+a[4]}
        BEGIN{target=ipn(ENVIRON["IP"])}
        {split($0,b,"/"); if(length(b)!=2) next; net=ipn(b[1]); p=b[2]+0; if(p<0||p>32) next; size=2^(32-p); base=int(net/size)*size; if(target>=base && target<base+size){print $0; exit}}
        ' "$FILE" 2>/dev/null
    }

    prefix_mask()
    {
        P="$1"
        awk -v p="$P" 'BEGIN{for(i=1;i<=4;i++){bits=p-(i-1)*8;if(bits>=8)o=255;else if(bits<=0)o=0;else o=256-2^(8-bits);printf "%s%d",(i>1?".":""),o}print ""}'
    }

    case "$TYPE" in
        domain)
            case "$VALUE" in
                ''|.*|*.|*..*|*[!a-z0-9.-]*)
                    echo '{"ok":false,"error":"invalid_domain"}'
                    exit 0
                    ;;
            esac

            DNS_OUT="$(/opt/bin/adaptive-resolve4.sh "$VALUE" 2>/dev/null)"
            IPS="$(printf '%s\\n' "$DNS_OUT" | awk '/^Address [0-9]+:/ && $3 ~ /^[0-9]+\\./ {print $3}' | sort -u | head -n 12)"
            IPS_JSON="$(printf '%s\\n' "$IPS" | "$JQ" -Rsc 'split("\\n")|map(select(length>0))')"

            HINTS_JSON="$(
                if [ -r "$HINT_CATALOG" ]; then
                    awk -F'|' -v h="$VALUE" '
                    NF>=3 {d=tolower($1); if(h==d || (length(h)>length(d) && substr(h,length(h)-length(d))=="." d)) print $2 "|" $3 "|" $1}' "$HINT_CATALOG" |
                    sort -u | head -n 40 | "$JQ" -Rsc 'split("\\n")|map(select(length>0)|split("|")|{source:.[0],category:.[1],match:.[2]})'
                else echo '[]'; fi
            )"

            ADAPTIVE=false
            [ -r "$ADAPTIVE_PERSIST" ] && grep -Fxiq "$VALUE" "$ADAPTIVE_PERSIST" && ADAPTIVE=true

            GROUPS="$(awk -v h="$VALUE" '
                /^object-group fqdn /{g=$3;next}
                /^!/{g="";next}
                g!="" && $1=="include" && tolower($2)==h {print g}
            ' "$RUNCFG" | sort -u)"
            GROUPS_JSON="$(printf '%s\\n' "$GROUPS" | "$JQ" -Rsc 'split("\\n")|map(select(length>0))')"
            ROUTES_JSON="$(
                printf '%s\\n' "$GROUPS" | while IFS= read -r G; do
                    [ -n "$G" ] || continue
                    awk -v g="$G" '$1=="route" && $2=="object-group" && $3==g {print g "|" $4}' "$RUNCFG"
                done | sort -u | "$JQ" -Rsc 'split("\\n")|map(select(length>0)|split("|")|{group:.[0],interface:.[1]})'
            )"

            "$JQ" -n --arg type domain --arg value "$VALUE" \
              --argjson ips "$IPS_JSON" --argjson hints "$HINTS_JSON" \
              --argjson adaptive "$ADAPTIVE" --argjson groups "$GROUPS_JSON" --argjson routes "$ROUTES_JSON" \
              '{ok:true,type:$type,value:$value,dns:{ipv4:$ips},hints:$hints,adaptive_auto:$adaptive,groups:$groups,routes:$routes}'
            ;;
        ip)
            valid_ipv4 "$VALUE" || {
                echo '{"ok":false,"error":"invalid_ipv4"}'
                exit 0
            }

            MATCHES_FILE=/tmp/vward-console-ip-matches.$$
            : > "$MATCHES_FILE"
            if [ -r "$IP_ACTIVE" ]; then
                while IFS= read -r CAT; do
                    [ -n "$CAT" ] || continue
                    FILE="$IP_CATALOG/$CAT.cidr"
                    [ -r "$FILE" ] || continue
                    CIDR="$(ip_matches_file "$VALUE" "$FILE")"
                    [ -n "$CIDR" ] && printf '%s|%s\\n' "$CAT" "$CIDR" >> "$MATCHES_FILE"
                done < "$IP_ACTIVE"
            fi
            MATCHES_JSON="$(head -n 40 "$MATCHES_FILE" | "$JQ" -Rsc 'split("\\n")|map(select(length>0)|split("|")|{category:.[0],cidr:.[1]})')"

            OWNED_CIDR=""
            if [ -r "$IP_OWNED" ]; then OWNED_CIDR="$(ip_matches_file "$VALUE" "$IP_OWNED")"; fi
            CONFIGURED=false
            ROUTE_INTERFACE=""
            if [ -n "$OWNED_CIDR" ]; then
                NET="${OWNED_CIDR%/*}"; PREFIX="${OWNED_CIDR#*/}"; MASK="$(prefix_mask "$PREFIX")"
                if grep -Fqx "ip route $NET $MASK Wireguard1 auto" "$RUNCFG"; then
                    CONFIGURED=true
                    ROUTE_INTERFACE=Wireguard1
                fi
            fi
            rm -f "$MATCHES_FILE"

            "$JQ" -n --arg type ip --arg value "$VALUE" --arg owned "$OWNED_CIDR" --arg iface "$ROUTE_INTERFACE" \
              --argjson matches "$MATCHES_JSON" --argjson configured "$CONFIGURED" \
              '{ok:true,type:$type,value:$value,policy_matches:$matches,owned_cidr:$owned,configured_route:$configured,interface:$iface}'
            ;;
        *)
            echo '{"ok":false,"error":"invalid_probe_type"}'
            ;;
    esac
    exit 0
fi

if [ "$ACTION" = "control" ] || [ "$ACTION" = "update-control" ]; then
    header_json
    [ "${REQUEST_METHOD:-GET}" = POST ] || {
        echo '{"ok":false,"error":"method_not_allowed"}'
        exit 0
    }
    [ "${HTTP_X_VWARD_REQUEST:-}" = console ] || {
        echo '{"ok":false,"error":"request_guard_failed"}'
        exit 0
    }

    LENGTH=${CONTENT_LENGTH:-0}
    case "$LENGTH" in ''|*[!0-9]*) LENGTH=0 ;; esac
    [ "$LENGTH" -gt 0 ] && [ "$LENGTH" -le 256 ] || {
        echo '{"ok":false,"error":"invalid_body"}'
        exit 0
    }
    BODY=$(dd bs=1 count="$LENGTH" 2>/dev/null)
    UNKNOWN_KEYS="$(printf '%s\\n' "$BODY" | tr '&' '\\n' | cut -d= -f1 | awk '$0!="op" && $0!="confirm" {print; exit}')"
    [ -z "$UNKNOWN_KEYS" ] || {
        echo '{"ok":false,"error":"unknown_parameter"}'
        exit 0
    }
    cvalue(){ printf '%s\\n' "$BODY" | tr '&' '\\n' | awk -F= -v k="$1" '$1==k{print $2;exit}'; }
    OP="$(cvalue op)"
    CONFIRM="$(cvalue confirm)"

    LOCK=/tmp/vward-console-control.lock
    if ! mkdir "$LOCK" 2>/dev/null; then
        echo '{"ok":false,"error":"control_busy"}'
        exit 0
    fi
    trap 'rm -rf "$LOCK"' EXIT INT TERM

    [ ! -e /opt/var/run/vward/updater.lock ] || {
        echo '{"ok":false,"error":"updater_busy"}'
        exit 0
    }

    CMD=""; ARG=""; REQUIRED=""; LABEL=""
    if [ "$ACTION" = control ]; then
        case "$OP" in
            refresh-hints) CMD=/opt/bin/adaptive-hints-update.sh; LABEL=refresh-hints ;;
            route-reconcile) CMD=/opt/bin/adaptive-auto-maint.sh; REQUIRED=ROUTE_RECONCILE; LABEL=route-reconcile ;;
            policy-refresh) CMD=/opt/bin/vpn-subnet-sync.sh; ARG=sync; REQUIRED=POLICY_REFRESH; LABEL=policy-refresh ;;
            policy-reconcile) CMD=/opt/bin/vpn-subnet-sync.sh; ARG=--reconcile; REQUIRED=POLICY_RECONCILE; LABEL=policy-reconcile ;;
            tunnel-health) CMD=/opt/bin/wg-health-watch.sh; LABEL=tunnel-health ;;
            *) echo '{"ok":false,"error":"unknown_control_action"}'; exit 0 ;;
        esac
    else
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

    [ -x "$CMD" ] || {
        echo '{"ok":false,"error":"action_unavailable"}'
        exit 0
    }
    [ -z "$REQUIRED" ] || [ "$CONFIRM" = "$REQUIRED" ] || {
        echo '{"ok":false,"error":"confirmation_required"}'
        exit 0
    }

    START="$(date '+%Y-%m-%dT%H:%M:%S%z')"
    if [ -n "$ARG" ]; then OUT="$("$CMD" "$ARG" 2>&1)"; else OUT="$("$CMD" 2>&1)"; fi
    RC=$?
    SAFE_OUT="$(printf '%s\\n' "$OUT" | tail -n 120)"
    printf '%s|CONSOLE_ACTION|action=%s rc=%s\\n' "$START" "$LABEL" "$RC" >> /opt/var/log/vward/console-audit.log
    OUT_JSON="$(printf '%s' "$SAFE_OUT" | "$JQ" -Rs .)"
    if [ "$RC" -eq 0 ]; then OK=true; else OK=false; fi
    printf '{"ok":%s,"action":"%s","rc":%s,"output":%s}\\n' "$OK" "$LABEL" "$RC" "$OUT_JSON"
    exit 0
fi
'''

api = once(
    api,
    'if [ "$ACTION" = "ping" ]; then\n',
    backend_block + '\nif [ "$ACTION" = "ping" ]; then\n',
    'backend blocks before ping',
)

# ---------------- UI: add operational controls ----------------
html = once(
    html,
    '<div class="notice">Параметры восстановления встроены в рабочий скрипт и пока доступны только для чтения. Опасных WAN-команд в Console нет.</div></section>',
    '<div class="actions"><button class="btn" id="wanCheckBtn">Проверить WAN</button><button class="btn" data-log-open="wan">Открыть журнал WAN</button></div><div class="notice">Проверка WAN обновляет только read-only состояние Console. Рабочий цикл VWARD WAN Guard может запускать recovery, поэтому отдельной кнопки его принудительного запуска здесь нет.</div></section>',
    'wan safe controls',
)

html = once(
    html,
    '<div class="notice">Ключи и конфигурация WireGuard никогда не передаются через Console API.</div></section>',
    '<div class="actions"><button class="btn" id="tunnelHealthBtn">Проверить туннель</button><button class="btn" data-log-open="tunnel">Открыть журнал VPN</button></div><pre class="action-result" id="tunnelActionResult" hidden></pre><div class="notice">Ручная проверка запускает только VWARD Tunnel Guard health probe. PrivateKey, PresharedKey и конфигурация WireGuard через Console API не передаются.</div></section>',
    'tunnel controls',
)

html = once(
    html,
    '<div class="notice">Доступны только четыре проверенных булевых параметра. Создаётся backup; при активной транзакции запись блокируется.</div></div></div></section>',
    '<div class="notice">Доступны только четыре проверенных булевых параметра. Создаётся backup; при активной транзакции запись блокируется.</div><div class="panel"><div class="panel-head"><div><h3>Ручные операции VWARD Update Engine</h3><div class="sub">Только штатные CLI-переходы state machine</div></div></div><div class="actions action-wrap"><button class="btn" data-update-op="check">Проверить сейчас</button><button class="btn primary" data-update-op="apply">Установить pending</button><button class="btn" data-update-op="retry">Повторить</button><button class="btn" data-update-op="rollback">Rollback</button><button class="btn" data-update-op="recover">Recovery</button><button class="btn" data-log-open="updater">Журнал обновлений</button></div><pre class="action-result" id="updateActionResult" hidden></pre></div></div></div></section>',
    'updater controls',
)

old_route_tail = '<div class="actions"><span class="sub" id="routeDataUpdated">Сведения ещё не загружены</span><button class="btn" id="routeDataRefresh">Обновить сведения</button></div><div class="notice">Это только фактическое read-only состояние каталогов VWARD. Редактор доменов, IP и маршрутов не включён без отдельного безопасного backend path.</div></section>'
new_route_tail = '''<div class="actions"><span class="sub" id="routeDataUpdated">Сведения ещё не загружены</span><button class="btn" id="routeDataRefresh">Обновить сведения</button></div>
<div class="panel"><div class="panel-head"><div><h3>Проверка домена или IP</h3><div class="sub">DNS, каталог, AdaptiveAuto, группа, правило и настроенный маршрут</div></div><span class="pill">READ ONLY</span></div><div class="probe-bar"><select id="routeProbeType" class="input"><option value="domain">Домен</option><option value="ip">IPv4</option></select><input id="routeProbeValue" class="input" placeholder="example.org" autocomplete="off" spellcheck="false"><button class="btn primary" id="routeProbeBtn">Проверить</button></div><div class="components" id="routeProbeResult"><div class="empty">Введите домен или IPv4</div></div></div>
<div class="panel"><div class="panel-head"><div><h3>Ручное управление</h3><div class="sub">Только заранее разрешённые операции VWARD</div></div></div><div class="actions action-wrap"><button class="btn" data-control-op="refresh-hints">Обновить доменные источники</button><button class="btn" data-control-op="route-reconcile">Обработать AdaptiveAuto</button><button class="btn" data-control-op="policy-refresh">Обновить IP/CIDR и политики</button><button class="btn" data-control-op="policy-reconcile">Сверить IP-политики</button><button class="btn" data-log-open="routing">Журнал маршрутов</button><button class="btn" data-log-open="policy">Журнал политик</button></div><pre class="action-result" id="routeActionResult" hidden></pre></div>
<div class="notice">Проверка домена/IP работает read-only. Операции, способные изменить AdaptiveAuto или Policy Sync, требуют явного подтверждения и выполняют только фиксированные VWARD-команды без произвольного shell/ndmc API.</div></section>'''
html = once(html, old_route_tail, new_route_tail, 'route probe and controls')

html = once(
    html,
    '<div><h3>Диагностика</h3><div class="stats" id="settingsDiagnostics"></div></div>',
    '<div><h3>Диагностика</h3><div class="stats" id="settingsDiagnostics"></div><div class="actions"><button class="btn" id="runDiagnostics">Запустить диагностику</button></div></div>',
    'diagnostics button',
)

# Lightweight styles for inputs/action output.
html = once(
    html,
    '</style>',
    '''.probe-bar{display:flex;gap:8px;align-items:center;margin-top:14px}.input{min-height:42px;border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:0 10px;min-width:0}.probe-bar input{flex:1}.action-wrap{flex-wrap:wrap}.action-result{margin:12px 0 0;max-height:260px;overflow:auto;background:#10161d;color:#cfdae7;border-radius:7px;padding:12px;white-space:pre-wrap;font:12px/1.5 ui-monospace,Consolas,monospace}.diag-list .row{grid-template-columns:1fr auto}.diag-list .pill{min-width:72px;text-align:center}@media(max-width:720px){.probe-bar{display:grid;grid-template-columns:110px 1fr}.probe-bar .btn{grid-column:1/-1}.action-wrap .btn{flex:1 1 calc(50% - 8px)}}\n</style>''',
    'control styles',
)

# JS functions inserted after Route Engine data loader.
js_marker = "function renderSettings(p){"
if html.count(js_marker) != 1:
    raise SystemExit('js insertion marker mismatch')
js_block = r'''function showActionResult(id,x){const e=$(id);e.hidden=false;e.textContent=(x.output||x.error||'Нет подробностей');e.scrollTop=0}async function postConsoleAction(endpoint,op,confirmValue,resultId){const q=new URLSearchParams({op:op});if(confirmValue)q.set('confirm',confirmValue);const el=$(resultId);if(el){el.hidden=false;el.textContent='Выполняется...'}try{const r=await fetch('/cgi-bin/api.cgi?action='+endpoint,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','X-VWARD-Request':'console'},body:q}),x=await r.json();if(el)showActionResult(resultId,x);if(!x.ok)throw Error(x.error||('RC '+x.rc));notify('Операция выполнена');await refresh();if(activeSection==='route')loadRouteData(false);return x}catch(e){if(el){el.hidden=false;el.textContent='Ошибка: '+e.message}notify('Ошибка: '+e.message);throw e}}
function openFilteredLog(name){document.querySelectorAll('#logSources input[data-log]').forEach(x=>{x.checked=x.dataset.log===name});go('logs');loadLogs(false)}document.querySelectorAll('[data-log-open]').forEach(b=>b.onclick=()=>openFilteredLog(b.dataset.logOpen));
$('wanCheckBtn').onclick=()=>refresh(true);$('tunnelHealthBtn').onclick=()=>postConsoleAction('control','tunnel-health','', 'tunnelActionResult');
const controlConfirm={"route-reconcile":['ROUTE_RECONCILE','AdaptiveAuto будет сверена штатным VWARD Route Reconciler. Продолжить?'],"policy-refresh":['POLICY_REFRESH','Policy Sync обновит внешние IP/CIDR-каталоги и может изменить принадлежащие ему маршруты. Продолжить?'],"policy-reconcile":['POLICY_RECONCILE','Policy Sync сверит принадлежащие ему IP-маршруты с текущим каталогом. Продолжить?']};document.querySelectorAll('[data-control-op]').forEach(b=>b.onclick=async()=>{const op=b.dataset.controlOp,c=controlConfirm[op],token=c?(confirm(c[1])?c[0]:null):'';if(c&&!token)return;b.disabled=true;try{await postConsoleAction('control',op,token,'routeActionResult')}catch(e){}finally{b.disabled=false}});
const updateConfirm={apply:['APPLY_UPDATE','Установить уже проверенное pending-обновление? Console может кратко перезапуститься.'],retry:['RETRY_UPDATE','Повторить установку pending-обновления через штатную state machine?'],rollback:['ROLLBACK_UPDATE','Запустить штатный rollback VWARD Update Engine?'],recover:['RECOVER_UPDATE','Запустить штатное recovery прерванной транзакции?']};document.querySelectorAll('[data-update-op]').forEach(b=>b.onclick=async()=>{const op=b.dataset.updateOp,c=updateConfirm[op],token=c?(confirm(c[1])?c[0]:null):'';if(c&&!token)return;b.disabled=true;try{await postConsoleAction('update-control',op,token,'updateActionResult')}catch(e){}finally{b.disabled=false}});
function renderProbe(x){if(x.type==='domain'){const hints=(x.hints||[]).map(h=>h.source+' / '+h.category+' · '+h.match),routes=(x.routes||[]).map(r=>r.group+' → '+r.interface);$('routeProbeResult').innerHTML=stat([['Домен',x.value],['IPv4',(x.dns&&x.dns.ipv4||[]).join(', ')||'Не разрешён'],['AdaptiveAuto',x.adaptive_auto?'Да':'Нет'],['Группы',(x.groups||[]).join(', ')||'Нет'],['Маршрут',routes.join(', ')||'Прямое правило не найдено'],['Каталог',hints.join('; ')||'Совпадений нет']])}else{$('routeProbeResult').innerHTML=stat([['IPv4',x.value],['Policy Sync',(x.policy_matches||[]).map(m=>m.category+' '+m.cidr).join('; ')||'Совпадений нет'],['Owned CIDR',x.owned_cidr||'Нет'],['Настроенный маршрут',x.configured_route?'Да':'Нет'],['Интерфейс',x.interface||'Не определён']])}}async function runRouteProbe(){const type=$('routeProbeType').value,value=$('routeProbeValue').value.trim();if(!value)return notify('Введите значение');$('routeProbeBtn').disabled=true;$('routeProbeResult').innerHTML='<div class="empty">Проверяем...</div>';try{const r=await fetch('/cgi-bin/api.cgi?action=route-probe&type='+encodeURIComponent(type)+'&value='+encodeURIComponent(value)+'&_='+Date.now(),{cache:'no-store'}),x=await r.json();if(!x.ok)throw Error(x.error);renderProbe(x)}catch(e){$('routeProbeResult').innerHTML='<div class="empty">Ошибка: '+esc(e.message)+'</div>'}finally{$('routeProbeBtn').disabled=false}}$('routeProbeBtn').onclick=runRouteProbe;$('routeProbeValue').addEventListener('keydown',e=>{if(e.key==='Enter')runRouteProbe()});$('routeProbeType').onchange=()=>{$('routeProbeValue').placeholder=$('routeProbeType').value==='domain'?'example.org':'203.0.113.10'};
function diagBadge(s){return s==='PASS'?'ok':s==='FAIL'?'bad':'warn'}async function runDiagnostics(show=true){$('runDiagnostics').disabled=true;try{const r=await fetch('/cgi-bin/api.cgi?action=diagnostics&_='+Date.now(),{cache:'no-store'}),x=await r.json();if(!x.ok)throw Error(x.error);$('settingsDiagnostics').innerHTML='<div class="diag-list">'+(x.checks||[]).map(c=>'<div class="row"><b>'+esc(c.label)+'<small>'+esc(c.detail||'')+'</small></b><span class="pill '+diagBadge(c.status)+'">'+esc(c.status)+'</span></div>').join('')+'</div>';if(show)notify('Диагностика завершена')}catch(e){$('settingsDiagnostics').innerHTML='<div class="empty">Ошибка диагностики: '+esc(e.message)+'</div>'}finally{$('runDiagnostics').disabled=false}}$('runDiagnostics').onclick=()=>runDiagnostics(true);
'''
html = html.replace(js_marker, js_block + js_marker, 1)

# Do not overwrite the diagnostics area with old compact stats after a manual run.
html = once(
    html,
    "$('settingsDiagnostics').innerHTML=stat([['API',ms+' мс'],['crond',s.crond?'Работает':'Остановлен'],['Supervisor',s.supervisor?'Работает':'Остановлен'],['Свободно',gb(z.free_kb)]]);",
    "if(!$('settingsDiagnostics').querySelector('.diag-list'))$('settingsDiagnostics').innerHTML=stat([['API',ms+' мс'],['crond',s.crond?'Работает':'Остановлен'],['Supervisor',s.supervisor?'Работает':'Остановлен'],['Свободно',gb(z.free_kb)]]);",
    'preserve diagnostics results',
)

# Tests for the final safe control-plane bindings.
test_add = r'''
for marker in ("runDiagnostics", "routeProbeBtn", "routeProbeValue", "tunnelHealthBtn", "updateActionResult", "routeActionResult"):
    if f'id="{marker}"' not in html:
        fail(f"нет control-plane элемента: {marker}")
for action in ("diagnostics", "route-probe", "control", "update-control"):
    if action not in api:
        fail(f"нет API action: {action}")
if "action=exec" in api or "action=file" in api or "action=ndmc" in api:
    fail("обнаружен запрещённый generic control API")
for token in ("ROUTE_RECONCILE", "POLICY_REFRESH", "POLICY_RECONCILE", "APPLY_UPDATE", "ROLLBACK_UPDATE", "RECOVER_UPDATE"):
    if token not in api:
        fail(f"нет server-side confirmation token: {token}")
'''
test = once(test, '\nnode = shutil.which("node")\n', '\n' + test_add + '\nnode = shutil.which("node")\n', 'binding tests')

# Documentation reflects only implemented source behavior.
doc += '''\n## Control plane: безопасные ручные операции\n\nConsole source поддерживает четыре явных API-направления: `diagnostics`, `route-probe`,\n`control` и `update-control`. Ни одно из них не принимает shell-команду, path или `ndmc`\nстроку от браузера. `route-probe` принимает только валидированный домен или IPv4 и\nсопоставляет его с локальными каталогами/state и фиксированным снимком running-config.\n\nРазрешённые component actions: обновление доменных hints, запуск Route Reconciler,\nобновление/сверка Policy Sync и health probe Tunnel Guard. Операции, способные менять\nмаршруты, требуют отдельного server-side confirmation token. Одновременно выполняется\nтолько одна Console action; при активной updater transaction component actions\nблокируются. Результат и RC попадают в Console audit log без секретов.\n\nVWARD Update Engine вызывается только штатными флагами `--check`, `--apply-pending`,\n`--rollback` и `--recover`. Apply/retry/rollback/recovery требуют отдельного\nподтверждения. Signature/trust/sequence проверки остаются внутри Update Engine и через\nConsole не отключаются.\n\nVWARD WAN Guard намеренно не запускается принудительно из Console под видом простой\nпроверки: текущий рабочий цикл способен инициировать recovery. Кнопка «Проверить WAN»\nобновляет только read-only RCI/status. Это ограничение сохраняется до появления\nотдельного доказуемо безопасного WAN probe/actuator path.\n\n## Диагностика\n\n`diagnostics` выполняет только фиксированный набор read-only проверок: `/opt`, основные\nзависимости, `crond`, supervisor, AdGuard Home, Adaptive Live, WAN, WireGuard, lighttpd,\nактивный Update Engine slot и update config. Ответ возвращает `PASS/WARN/FAIL/UNKNOWN`\nс короткой причиной. Произвольные команды и произвольные файлы недоступны.\n'''

if 'Control plane: safe diagnostics, validated domain/IP route probe' not in changelog:
    changelog = changelog.replace('## [Unreleased]\n', '## [Unreleased]\n\n- Control plane: safe diagnostics, validated domain/IP route probe, allowlisted Route/Policy/Tunnel actions and guarded Update Engine actions.\n', 1)

api_path.write_text(api, encoding='utf-8')
html_path.write_text(html, encoding='utf-8')
test_path.write_text(test, encoding='utf-8')
doc_path.write_text(doc, encoding='utf-8')
changelog_path.write_text(changelog, encoding='utf-8')
print('FINAL_CONTROL_PLANE_PATCH=APPLIED')
