#!/opt/bin/sh
PATH="/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH

JQ=/opt/bin/jq
WGET=/opt/bin/wget

header_json()
{
    echo 'Content-Type: application/json; charset=utf-8'
    echo 'Access-Control-Allow-Origin: *'
    echo 'Access-Control-Allow-Methods: GET, OPTIONS'
    echo 'Access-Control-Allow-Headers: Content-Type'
    echo 'Access-Control-Allow-Private-Network: true'
    echo 'Cache-Control: no-store'
    echo
}

header_text()
{
    echo 'Content-Type: text/plain; charset=utf-8'
    echo 'Access-Control-Allow-Origin: *'
    echo 'Access-Control-Allow-Methods: GET, OPTIONS'
    echo 'Access-Control-Allow-Headers: Content-Type'
    echo 'Access-Control-Allow-Private-Network: true'
    echo 'Cache-Control: no-store'
    echo
}

if [ "$REQUEST_METHOD" = "OPTIONS" ]; then
    header_json
    echo '{"ok":true}'
    exit 0
fi

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
    DATA="$("$WGET" -qO- "$1" 2>/dev/null)"

    echo "$DATA" |
    "$JQ" -c . 2>/dev/null ||
    echo '{}'
}

ACTION="$(qget action)"
[ -n "$ACTION" ] || ACTION=status

if [ "$ACTION" = "ping" ]; then
    header_json
    echo '{"ok":true,"service":"keenetic-apps-backend"}'
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
'
{
  ok:true,

  timestamp:$ts,

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
