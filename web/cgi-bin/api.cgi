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
    GET) ;;
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
    status|ping|log) ;;
    *)
        header_json
        echo '{"ok":false,"error":"unknown_action"}'
        exit 0
        ;;
esac

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

ISP="$(
    fetch_json \
    'http://127.0.0.1:79/rci/show/interface?name=ISP'
)"

INET="$(
    fetch_json \
    'http://127.0.0.1:79/rci/show/internet/status'
)"

WG0="$(
    fetch_json \
    'http://127.0.0.1:79/rci/show/interface?name=Wireguard0'
)"

WG1="$(
    fetch_json \
    'http://127.0.0.1:79/rci/show/interface?name=Wireguard1'
)"

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
BARRIER_READY="$(sed -n 's/^barrier_integration_ready=//p' /opt/etc/vward/update.conf 2>/dev/null)"

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
  --argjson wg0 "$WG0" \
  --argjson wg1 "$WG1" \
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
  --arg barrier_ready "$BARRIER_READY" \
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
    barrier_ready:($barrier_ready=="1"),
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
    wg0:{
      link:($wg0.link // ""),
      connected:($wg0.connected // ""),
      state:($wg0.state // "")
    },

    wg1:{
      link:($wg1.link // ""),
      connected:($wg1.connected // ""),
      state:($wg1.state // "")
    }
  },

  services:{
    crond:($crond=="1"),
    crond_pid:$crond_pid,
    supervisor:($supervisor=="1"),
    adguard:($adguard=="1")
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
