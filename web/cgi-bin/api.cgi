#!/opt/bin/sh
PATH="/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH

JQ=/opt/bin/jq
CURL=/opt/bin/curl
DISCOVERY="${VWARD_DISCOVERY:-/opt/bin/vward-discovery.sh}"

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
    status|ping|log|settings) ;;
    *)
        header_json
        echo '{"ok":false,"error":"unknown_action"}'
        exit 0
        ;;
esac

if [ "${REQUEST_METHOD:-GET}" = POST ] && [ "$ACTION" != settings ]; then
    echo 'Status: 405 Method Not Allowed'
    header_json
    echo '{"ok":false,"error":"method_not_allowed"}'
    exit 0
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
    echo '{"ok":true,"result":"saved"}'
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

    header_text

    if [ -n "$FILE" ] && [ -r "$FILE" ]; then
        tail -n 200 "$FILE" 2>/dev/null
    else
        echo "Лог пока пуст или недоступен."
    fi

    exit 0
fi

VER="$(
    fetch_json \
    'http://127.0.0.1:79/rci/show/version'
)"

INET="$(
    fetch_json \
    'http://127.0.0.1:79/rci/show/internet/status'
)"

DISCOVERY_PROVIDER=vward-discovery
DISCOVERY_STATE=UNAVAILABLE
WG_DISCOVERY_STATE=UNAVAILABLE
WG_INTERFACES='[]'
WAN_DISCOVERY_STATE=UNAVAILABLE
WAN_DISCOVERY_SELECTION=''
WAN_INTERFACE='{}'

if [ -x "$DISCOVERY" ]; then
    DISCOVERY_SNAPSHOT="$(
        "$DISCOVERY" snapshot 2>/dev/null
    )"

    if printf '%s\n' "$DISCOVERY_SNAPSHOT" |
        "$JQ" -e '
            type == "object" and
            .kind == "snapshot" and
            (.wireguard.interfaces | type == "array") and
            (.wan.interfaces | type == "array") and
            (.roles.tunnel_guard | type == "object") and
            (.roles.wan_guard | type == "object")
        ' >/dev/null 2>&1
    then
        DISCOVERY_PROVIDER="$(
            printf '%s\n' "$DISCOVERY_SNAPSHOT" |
            "$JQ" -r '.provider // "vward-discovery"' 2>/dev/null
        )"
        DISCOVERY_STATE=READY

        WG_INTERFACES="$(
            printf '%s\n' "$DISCOVERY_SNAPSHOT" |
            "$JQ" -c '[
                .wireguard.interfaces[] |
                {
                    name:(.rci_id // ""),
                    rci_id:(.rci_id // ""),
                    linux_if:(.linux_if // ""),
                    mapping:(.mapping // ""),
                    description:(.description // ""),
                    type:(.type // ""),
                    index:(.index // null),
                    address:(.address // ""),
                    link:(.link // ""),
                    connected:(.connected // ""),
                    state:(.state // "")
                }
            ]' 2>/dev/null
        )"
        [ -n "$WG_INTERFACES" ] || WG_INTERFACES='[]'
        WG_DISCOVERY_STATE=READY

        WAN_DISCOVERY_STATE="$(
            printf '%s\n' "$DISCOVERY_SNAPSHOT" |
            "$JQ" -r '.roles.wan_guard.state // "UNAVAILABLE"' 2>/dev/null
        )"
        WAN_DISCOVERY_SELECTION="$(
            printf '%s\n' "$DISCOVERY_SNAPSHOT" |
            "$JQ" -r '.roles.wan_guard.selection // ""' 2>/dev/null
        )"
        WAN_INTERFACE="$(
            printf '%s\n' "$DISCOVERY_SNAPSHOT" |
            "$JQ" -c '.roles.wan_guard.interface // {}' 2>/dev/null
        )"
        [ -n "$WAN_INTERFACE" ] || WAN_INTERFACE='{}'
    fi
fi

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
  --argjson wan_interface "$WAN_INTERFACE" \
  --argjson inet "$INET" \
  --arg discovery_provider "$DISCOVERY_PROVIDER" \
  --arg discovery_state "$DISCOVERY_STATE" \
  --arg wan_discovery_state "$WAN_DISCOVERY_STATE" \
  --arg wan_discovery_selection "$WAN_DISCOVERY_SELECTION" \
  --argjson wg_interfaces "$WG_INTERFACES" \
  --arg wg_discovery_state "$WG_DISCOVERY_STATE" \
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

  discovery:{
    provider:$discovery_provider,
    state:$discovery_state
  },

  wan:{
    discovery:{
      provider:$discovery_provider,
      state:$wan_discovery_state,
      selection:$wan_discovery_selection
    },
    observer_source:"legacy-wan-guardian",
    class:$gc,
    version:$gv,
    mode:$gm,
    action:$ga,

    rci_id:($wan_interface.rci_id // ""),
    interface_name:($wan_interface.interface_name // ""),
    linux_if:($wan_interface.linux_if // ""),
    mapping:($wan_interface.mapping // ""),
    via_rci_id:($wan_interface.via_rci_id // ""),
    via_linux_if:($wan_interface.via_linux_if // ""),
    type:($wan_interface.type // ""),

    link:($wan_interface.link // ""),
    connected:($wan_interface.connected // ""),
    state:($wan_interface.state // ""),

    address:($wan_interface.address // ""),
    gateway:($inet.gateway.address // ""),

    speed:($wan_interface.port_speed // ""),
    duplex:($wan_interface.port_duplex // ""),
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
    discovery:{
      provider:$discovery_provider,
      state:$wg_discovery_state
    },
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