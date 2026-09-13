#!/opt/bin/sh
PATH="/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH

JQ=/opt/bin/jq
CURL=/opt/bin/curl

header_json()
{
    echo 'Content-Type: application/json; charset=utf-8'
    echo 'Cache-Control: no-store'
    echo 'X-Content-Type-Options: nosniff'
    echo "Content-Security-Policy: default-src 'none'; frame-ancestors 'none'"
    echo
}

header_text()
{
    echo 'Content-Type: text/plain; charset=utf-8'
    echo 'Cache-Control: no-store'
    echo 'X-Content-Type-Options: nosniff'
    echo
}

case "${REQUEST_METHOD:-GET}" in
    GET|POST) ;;
    OPTIONS)
        header_json
        echo '{"ok":true}'
        exit 0
        ;;
    *)
        echo 'Status: 405 Method Not Allowed'
        header_json
        echo '{"ok":false,"error":"method_not_allowed"}'
        exit 0
        ;;
esac

qget()
{
    echo "$QUERY_STRING" |
    tr '&' '\n' |
    awk -F= -v k="$1" '$1==k {
        print substr($0,index($0,"=")+1)
        exit
    }'
}

fetch_json()
{
    DATA="$("$CURL" --fail --silent --show-error \
        --connect-timeout 2 --max-time 3 "$1" 2>/dev/null)"

    echo "$DATA" |
    "$JQ" -c . 2>/dev/null ||
    echo '{}'
}

ACTION="$(qget action)"
[ -n "$ACTION" ] || ACTION=status

case "$ACTION" in
    status|ping|log|settings|route-data|diagnostics|route-probe|update-data|control|update-control) ;;
    *)
        header_json
        echo '{"ok":false,"error":"unknown_action"}'
        exit 0
        ;;
esac

if [ "${REQUEST_METHOD:-GET}" = POST ]; then
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

if [ "$ACTION" = "settings" ]; then
    header_json

    [ "${REQUEST_METHOD:-GET}" = POST ] || {
        echo '{"ok":false,"error":"method_not_allowed"}'
        exit 0
    }
    [ "${HTTP_X_VWARD_REQUEST:-}" = console ] || {
        echo '{"ok":false,"error":"request_guard_failed"}'
        exit 0
    }
    [ ! -e /opt/var/run/vward/updater.lock ] || {
        echo '{"ok":false,"error":"updater_busy"}'
        exit 0
    }

    LENGTH=${CONTENT_LENGTH:-0}
    case "$LENGTH" in ''|*[!0-9]*) LENGTH=0 ;; esac
    [ "$LENGTH" -gt 0 ] && [ "$LENGTH" -le 256 ] || {
        echo '{"ok":false,"error":"invalid_body"}'
        exit 0
    }
    BODY=$(dd bs=1 count="$LENGTH" 2>/dev/null)

    UNKNOWN_KEYS="$(printf '%s\n' "$BODY" | tr '&' '\n' | cut -d= -f1 | awk '$0!="auto_apply" && $0!="auto_critical" && $0!="auto_important" && $0!="auto_routine" {print; exit}')"
    [ -z "$UNKNOWN_KEYS" ] || {
        echo '{"ok":false,"error":"unknown_parameter"}'
        exit 0
    }

    value()
    {
        printf '%s\n' "$BODY" | tr '&' '\n' |
        awk -F= -v k="$1" '$1==k {print $2; exit}'
    }

    AUTO_APPLY=$(value auto_apply)
    AUTO_CRITICAL=$(value auto_critical)
    AUTO_IMPORTANT=$(value auto_important)
    AUTO_ROUTINE=$(value auto_routine)
    for FLAG in "$AUTO_APPLY" "$AUTO_CRITICAL" "$AUTO_IMPORTANT" "$AUTO_ROUTINE"; do
        case "$FLAG" in 0|1) ;; *) echo '{"ok":false,"error":"invalid_value"}'; exit 0 ;; esac
    done

    CONFIG=/opt/etc/vward/update.conf
    [ -r "$CONFIG" ] && [ -w "$CONFIG" ] || {
        echo '{"ok":false,"error":"config_unavailable"}'
        exit 0
    }
    STAMP=$(date '+%Y%m%d-%H%M%S')
    BACKUP=/opt/var/backups/vward/update.conf.console-$STAMP
    mkdir -p /opt/var/backups/vward || {
        echo '{"ok":false,"error":"backup_failed"}'
        exit 0
    }
    cp -p "$CONFIG" "$BACKUP" || {
        echo '{"ok":false,"error":"backup_failed"}'
        exit 0
    }
    TMP=$CONFIG.new.$$
    sed \
        -e "s/^auto_apply=.*/auto_apply=$AUTO_APPLY/" \
        -e "s/^auto_critical=.*/auto_critical=$AUTO_CRITICAL/" \
        -e "s/^auto_important=.*/auto_important=$AUTO_IMPORTANT/" \
        -e "s/^auto_routine=.*/auto_routine=$AUTO_ROUTINE/" \
        "$CONFIG" > "$TMP" && chmod 0600 "$TMP" && mv "$TMP" "$CONFIG" || {
            cp -p "$BACKUP" "$CONFIG" 2>/dev/null
            rm -f "$TMP"
            echo '{"ok":false,"error":"write_failed"}'
            exit 0
        }
    grep -q "^auto_apply=$AUTO_APPLY$" "$CONFIG" &&
    grep -q "^auto_critical=$AUTO_CRITICAL$" "$CONFIG" &&
    grep -q "^auto_important=$AUTO_IMPORTANT$" "$CONFIG" &&
    grep -q "^auto_routine=$AUTO_ROUTINE$" "$CONFIG" || {
        cp -p "$BACKUP" "$CONFIG" 2>/dev/null
        echo '{"ok":false,"error":"verification_failed"}'
        exit 0
    }
    printf '%s|CONSOLE_SETTINGS|auto_apply=%s critical=%s important=%s routine=%s\n' \
        "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$AUTO_APPLY" "$AUTO_CRITICAL" "$AUTO_IMPORTANT" "$AUTO_ROUTINE" \
        >> /opt/var/log/vward/console-audit.log
    echo '{"ok":true,"result":"saved","verified":true,"backup_created":true,"requires_restart":false}'
    exit 0
fi

if [ "$ACTION" = "route-data" ]; then
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
        {n=split($0,b,"/"); if(n!=2) next; net=ipn(b[1]); p=b[2]+0; if(p<0||p>32) next; size=2^(32-p); base=int(net/size)*size; if(target>=base && target<base+size){print $0; exit}}
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

    if [ "$ACTION" = control ] && [ -e /opt/var/run/vward/updater.lock ]; then
        echo '{"ok":false,"error":"updater_busy"}'
        exit 0
    fi

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

if [ "$ACTION" = "ping" ]; then
    header_json
    echo '{"ok":true,"service":"vward-console"}'
    exit 0
fi

if [ "$ACTION" = "log" ]; then

    NAME="$(qget name)"

    case "$NAME" in
        wan)
            FILE=/opt/var/log/wan-guardian.log
            ;;
        recovery)
            FILE=/opt/var/log/wan-guardian-recovery.log
            ;;
        cron)
            FILE=/opt/var/log/crond.log
            ;;
        routing)
            FILE=/tmp/adaptive-auto-maint.cron.out
            ;;
        updater)
            FILE=/opt/var/log/vward/updater-watch.log
            ;;
        tunnel)
            FILE=/opt/var/log/wg-failopen.log
            ;;
        policy)
            FILE=/opt/var/log/vpn-audit-summary.log
            ;;
        console)
            FILE=/opt/var/log/vward/console-audit.log
            ;;
        *)
            FILE=
            ;;
    esac

    COUNT="$(qget count)"
    case "$COUNT" in ''|*[!0-9]*) COUNT=200 ;; esac
    [ "$COUNT" -ge 20 ] 2>/dev/null && [ "$COUNT" -le 200 ] 2>/dev/null || COUNT=200

    header_text

    if [ -n "$FILE" ] && [ -r "$FILE" ]; then
        tail -n "$COUNT" "$FILE" 2>/dev/null
    else
        echo "Лог пока пуст или недоступен."
    fi

    exit 0
fi

VER="$(
    fetch_json \
    'http://127.0.0.1:79/rci/show/version'
)"

ISP="$(
    fetch_json \
    'http://127.0.0.1:79/rci/show/interface?name=ISP'
)"

INET="$(
    fetch_json \
    'http://127.0.0.1:79/rci/show/internet/status'
)"

IFACES="$(
    fetch_json \
    'http://127.0.0.1:79/rci/show/interface'
)"

WG_NAMES="$(
    printf '%s\n' "$IFACES" |
    "$JQ" -r 'keys[]' 2>/dev/null |
    grep -E '^Wireguard[0-9][0-9]*$'
)"

WG_INTERFACES="$(
    printf '%s\n' "$WG_NAMES" |
    while IFS= read -r WG_NAME
    do
        [ -n "$WG_NAME" ] || continue

        printf '%s\n' "$IFACES" |
        "$JQ" -c --arg n "$WG_NAME" '
            .[$n] |
            {
                name:$n,
                description:(.description // ""),
                link:(.link // ""),
                connected:(.connected // ""),
                state:(.state // "")
            }
        ' 2>/dev/null
    done |
    "$JQ" -s -c '.' 2>/dev/null
)"

[ -n "$WG_INTERFACES" ] || WG_INTERFACES='[]'

GOUT=/tmp/wan-guardian.cron.out

GVERSION="$(
    sed -n 's/^VERSION=//p' "$GOUT" 2>/dev/null |
    tail -n 1
)"

GMODE="$(
    sed -n 's/^MODE=//p' "$GOUT" 2>/dev/null |
    tail -n 1
)"

GCLASS="$(
    sed -n 's/^CLASS=//p' "$GOUT" 2>/dev/null |
    tail -n 1
)"

GACTION="$(
    sed -n 's/^ACTION=//p' "$GOUT" 2>/dev/null |
    tail -n 1
)"

DETAIL="$(
    grep '^carrier=' "$GOUT" 2>/dev/null |
    tail -n 1
)"

detail()
{
    echo "$DETAIL" |
    tr ' ' '\n' |
    awk -F= -v k="$1" '$1==k {
        print $2
        exit
    }'
}

CARRIER="$(detail carrier)"
REC_COUNT="$(detail recovery_count)"
REC_STAGE="$(detail recovery_stage)"

[ -n "$REC_COUNT" ] || REC_COUNT=0
[ -n "$REC_STAGE" ] || REC_STAGE=0

CROND=0
SUPERVISOR=0
ADGUARD=0

CROND_PID="$(
    ps 2>/dev/null |
    awk '/[c]rond -b/ {
        print $1
        exit
    }'
)"

[ -n "$CROND_PID" ] && CROND=1

ps 2>/dev/null |
grep -q '[c]rond-supervisor.sh' &&
SUPERVISOR=1

ps 2>/dev/null |
grep -q '[A]dGuardHome' &&
ADGUARD=1

UPTIME_SEC="$(
    cut -d. -f1 /proc/uptime 2>/dev/null
)"

GRC="$(cat /tmp/wan-guardian.cron.rc 2>/dev/null)"
GLAST="$(cat /tmp/wan-guardian.cron.last 2>/dev/null)"

WGRC="$(cat /tmp/wg-health-chain.cron.rc 2>/dev/null)"
WGLAST="$(cat /tmp/wg-health-chain.cron.last 2>/dev/null)"

RRC="$(cat /tmp/adaptive-auto-maint.cron.rc 2>/dev/null)"
RLAST="$(cat /tmp/adaptive-auto-maint.cron.last 2>/dev/null)"

VWARD_VERSION="$(sed -n '1p' /opt/share/vward/VERSION 2>/dev/null)"
UPDATER_STATE=/opt/var/lib/vward/updater
COMPONENTS="$($JQ -c '.components // {}' "$UPDATER_STATE/components.json" 2>/dev/null || echo '{}')"
INSTALLED_UPDATE_ID="$(sed -n 's/^installed_update_id=//p' "$UPDATER_STATE/committed.state" 2>/dev/null)"
LAST_SEQUENCE="$(sed -n 's/^last_sequence=//p' "$UPDATER_STATE/committed.state" 2>/dev/null)"
LAST_HEALTH="$(sed -n 's/^last_health_check=//p' "$UPDATER_STATE/committed.state" 2>/dev/null)"
UPDATE_PHASE="$(sed -n 's/^phase=//p' "$UPDATER_STATE/journal.state" 2>/dev/null)"
HIGHEST_SEQUENCE="$(sed -n 's/^highest_seen_sequence=//p' "$UPDATER_STATE/trust.state" 2>/dev/null)"
ACTIVE_SLOT="$(CDPATH= cd -- /opt/share/vward/updater/current 2>/dev/null && pwd -P)"

UPDATE_ENABLED="$(sed -n 's/^update_enabled=//p' /opt/etc/vward/update.conf 2>/dev/null)"
AUTO_APPLY="$(sed -n 's/^auto_apply=//p' /opt/etc/vward/update.conf 2>/dev/null)"
AUTO_CRITICAL="$(sed -n 's/^auto_critical=//p' /opt/etc/vward/update.conf 2>/dev/null)"
AUTO_IMPORTANT="$(sed -n 's/^auto_important=//p' /opt/etc/vward/update.conf 2>/dev/null)"
AUTO_ROUTINE="$(sed -n 's/^auto_routine=//p' /opt/etc/vward/update.conf 2>/dev/null)"
BARRIER_READY="$(sed -n 's/^barrier_integration_ready=//p' /opt/etc/vward/update.conf 2>/dev/null)"
UPDATE_CHANNEL="$(sed -n 's/^channel=//p' /opt/etc/vward/update.conf 2>/dev/null)"
SAFE_START="$(sed -n 's/^safe_window_start=//p' /opt/etc/vward/update.conf 2>/dev/null)"
SAFE_END="$(sed -n 's/^safe_window_end=//p' /opt/etc/vward/update.conf 2>/dev/null)"
CHECK_INTERVAL="$(sed -n 's/^check_interval_seconds=//p' /opt/etc/vward/update.conf 2>/dev/null)"

LIVE_PID="$(cat /opt/var/run/agh-adaptive-live.pid 2>/dev/null)"
CONSOLE_PID="$(cat /opt/var/run/keenetic-apps-lighttpd.pid 2>/dev/null)"
LIVE_COUNT="$(ps w 2>/dev/null | awk '$6=="/opt/bin/agh-adaptive-live.sh"{n++} END{print n+0}')"
TCPDUMP_COUNT="$(ps w 2>/dev/null | awk '$5=="tcpdump" && index($0,"udp dst port 53"){n++} END{print n+0}')"
FAILOPEN_STATE=/opt/var/lib/wg-failopen/state
DOWN_STREAK="$(sed -n 's/^DOWN_STREAK=//p' "$FAILOPEN_STATE" 2>/dev/null)"
FAILOPEN_ACTIVE="$(sed -n 's/^FAILOPEN_ACTIVE=//p' "$FAILOPEN_STATE" 2>/dev/null)"
[ -n "$DOWN_STREAK" ] || DOWN_STREAK=0
[ -n "$FAILOPEN_ACTIVE" ] || FAILOPEN_ACTIVE=0

OPT_TOTAL_KB="$(df -Pk /opt 2>/dev/null | awk 'NR==2 {print $2}')"
OPT_USED_KB="$(df -Pk /opt 2>/dev/null | awk 'NR==2 {print $3}')"
OPT_FREE_KB="$(df -Pk /opt 2>/dev/null | awk 'NR==2 {print $4}')"
OPT_FS="$(df -PT /opt 2>/dev/null | awk 'NR==2 {print $2}')"

JQ_VERSION="$($JQ --version 2>/dev/null)"
CURL_VERSION="$(curl --version 2>/dev/null | awk 'NR==1 {print $2}')"
LIGHTTPD_VERSION="$(/opt/sbin/lighttpd -v 2>&1 | awk 'NR==1 {print $1}')"

header_json

"$JQ" -n \
  --arg ts "$(date '+%Y-%m-%dT%H:%M:%S%z')" \
  --argjson ver "$VER" \
  --argjson isp "$ISP" \
  --argjson inet "$INET" \
  --argjson wg_interfaces "$WG_INTERFACES" \
  --arg gv "$GVERSION" \
  --arg gm "$GMODE" \
  --arg gc "$GCLASS" \
  --arg ga "$GACTION" \
  --arg carrier "$CARRIER" \
  --arg rcnt "$REC_COUNT" \
  --arg rstage "$REC_STAGE" \
  --arg crond "$CROND" \
  --arg crond_pid "$CROND_PID" \
  --arg supervisor "$SUPERVISOR" \
  --arg adguard "$ADGUARD" \
  --arg uptime "$UPTIME_SEC" \
  --arg grc "$GRC" \
  --arg glast "$GLAST" \
  --arg wgrc "$WGRC" \
  --arg wglast "$WGLAST" \
  --arg rrc "$RRC" \
  --arg rlast "$RLAST" \
  --arg vward_version "$VWARD_VERSION" \
  --arg installed_update_id "$INSTALLED_UPDATE_ID" \
  --arg last_sequence "$LAST_SEQUENCE" \
  --arg last_health "$LAST_HEALTH" \
  --arg update_phase "$UPDATE_PHASE" \
  --arg highest_sequence "$HIGHEST_SEQUENCE" \
  --arg active_slot "$ACTIVE_SLOT" \
  --arg update_enabled "$UPDATE_ENABLED" \
  --arg auto_apply "$AUTO_APPLY" \
  --arg auto_critical "$AUTO_CRITICAL" \
  --arg auto_important "$AUTO_IMPORTANT" \
  --arg auto_routine "$AUTO_ROUTINE" \
  --arg barrier_ready "$BARRIER_READY" \
  --arg update_channel "$UPDATE_CHANNEL" \
  --arg safe_start "$SAFE_START" \
  --arg safe_end "$SAFE_END" \
  --arg check_interval "$CHECK_INTERVAL" \
  --arg live_pid "$LIVE_PID" \
  --arg console_pid "$CONSOLE_PID" \
  --arg live_count "$LIVE_COUNT" \
  --arg tcpdump_count "$TCPDUMP_COUNT" \
  --arg down_streak "$DOWN_STREAK" \
  --arg failopen_active "$FAILOPEN_ACTIVE" \
  --argjson components "$COMPONENTS" \
  --arg opt_total_kb "$OPT_TOTAL_KB" \
  --arg opt_used_kb "$OPT_USED_KB" \
  --arg opt_free_kb "$OPT_FREE_KB" \
  --arg opt_fs "$OPT_FS" \
  --arg jq_version "$JQ_VERSION" \
  --arg curl_version "$CURL_VERSION" \
  --arg lighttpd_version "$LIGHTTPD_VERSION" \
'
{
  ok:true,

  timestamp:$ts,

  platform:{
    name:"VWARD Platform",
    version:$vward_version,
    installed_update_id:$installed_update_id,
    last_sequence:($last_sequence|tonumber? // 0),
    highest_seen_sequence:($highest_sequence|tonumber? // 0),
    last_health_check:$last_health,
    phase:(if $update_phase=="" then "IDLE" else $update_phase end),
    active_slot:($active_slot | split("/") | last),
    update_enabled:($update_enabled=="1"),
    auto_apply:($auto_apply=="1"),
    auto_critical:($auto_critical=="1"),
    auto_important:($auto_important=="1"),
    auto_routine:($auto_routine=="1"),
    barrier_ready:($barrier_ready=="1"),
    channel:$update_channel,
    safe_window:($safe_start+"–"+$safe_end),
    check_interval_seconds:($check_interval|tonumber? // 0),
    components:$components
  },

  storage:{
    total_kb:($opt_total_kb|tonumber? // 0),
    used_kb:($opt_used_kb|tonumber? // 0),
    free_kb:($opt_free_kb|tonumber? // 0),
    filesystem:$opt_fs
  },

  dependencies:{
    jq:$jq_version,
    curl:$curl_version,
    lighttpd:$lighttpd_version,
    ndmc:"/bin/ndmc"
  },

  router:{
    model:($ver.model // $ver.device // ""),
    version:($ver.title // $ver.release // ""),
    release:($ver.release // ""),
    uptime_sec:($uptime|tonumber? // 0)
  },

  wan:{
    class:$gc,
    version:$gv,
    mode:$gm,
    action:$ga,

    link:($isp.link // ""),
    connected:($isp.connected // ""),
    state:($isp.state // ""),

    address:($isp.address // ""),
    gateway:($inet.gateway.address // ""),

    speed:($isp.port.speed // ""),
    duplex:($isp.port.duplex // ""),
    carrier:$carrier,

    gateway_accessible:
      ($inet["gateway-accessible"] // false),

    dns_accessible:
      ($inet["dns-accessible"] // false),

    internet:
      ($inet.internet // false),

    reliable:
      ($inet.reliable // false),

    recovery_count:
      ($rcnt|tonumber? // 0),

    recovery_stage:
      ($rstage|tonumber? // 0)
  },

  wg:{
    interfaces:$wg_interfaces,
    total:($wg_interfaces|length),
    down_streak:($down_streak|tonumber? // 0),
    failopen_active:($failopen_active=="1")
  },

  services:{
    crond:($crond=="1"),
    crond_pid:$crond_pid,
    supervisor:($supervisor=="1"),
    adguard:($adguard=="1"),
    adaptive_live_pid:$live_pid,
    adaptive_live_count:($live_count|tonumber? // 0),
    tcpdump_count:($tcpdump_count|tonumber? // 0),
    console_pid:$console_pid
  },

  cron:{
    guardian_rc:$grc,
    guardian_last:$glast,
    wg_rc:$wgrc,
    wg_last:$wglast,
    routing_rc:$rrc,
    routing_last:$rlast
  }
}
'
