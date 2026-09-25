#!/opt/bin/sh
PATH="/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH

JQ=${JQ:-/opt/bin/jq}
CURL=${CURL:-/opt/bin/curl}

VWARD_PROFILE_LIB=${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}
VWARD_RCI_BASE=http://127.0.0.1:79/rci
PROFILE_READY=false
if [ -r "$VWARD_PROFILE_LIB" ]; then
    . "$VWARD_PROFILE_LIB"
    vward_profile_load >/dev/null 2>&1 && PROFILE_READY=true
fi
# No policy group is fine: only the domain operations need one, and
# vward-console-config.sh refuses those itself.
[ -n "${VWARD_WAN_INTERFACE:-}" ] || PROFILE_READY=false

header_json()
{
    echo 'Content-Type: application/json; charset=utf-8'
    echo 'Cache-Control: no-store'
    echo 'X-Content-Type-Options: nosniff'
    echo 'X-Frame-Options: DENY'
    echo 'Referrer-Policy: no-referrer'
    echo 'Permissions-Policy: camera=(), geolocation=(), microphone=()'
    echo "Content-Security-Policy: default-src 'none'; frame-ancestors 'none'"
    echo
}

header_text()
{
    echo 'Content-Type: text/plain; charset=utf-8'
    echo 'Cache-Control: no-store'
    echo 'X-Content-Type-Options: nosniff'
    echo 'X-Frame-Options: DENY'
    echo 'Referrer-Policy: no-referrer'
    echo 'Permissions-Policy: camera=(), geolocation=(), microphone=()'
    echo
}

case "${REQUEST_METHOD:-GET}" in
    GET|POST) ;;
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

    FETCH_OUT="$(printf '%s\n' "$DATA" |
        "$JQ" -cs 'if length == 1 and (.[0] | type) == "object" then .[0] else {} end' 2>/dev/null)"
    [ -n "$FETCH_OUT" ] || FETCH_OUT='{}'
    printf '%s\n' "$FETCH_OUT"
}

# ndm_cached NAME TTL COMMAND: a Keenetic "show" answer kept TTL seconds in RAM
# (root-only), so a console refreshing every few seconds does not make the
# router serialize its whole configuration each time.  Any POST drops the
# cache first, so a change is never followed by the old state.  With ndmc
# replaced (tests) the cache is off unless VWARD_CONSOLE_CACHE_TTL says otherwise.
NDM_CACHE_DIR=${VWARD_CONSOLE_CACHE_DIR:-/tmp/vward-console-cache}
ndm_cached()
{
    nc_file="$NDM_CACHE_DIR/$1" nc_ttl="$2"
    [ -z "${VWARD_NDMC:-}" ] || nc_ttl=${VWARD_CONSOLE_CACHE_TTL:-0}
    [ -z "${VWARD_CONSOLE_CACHE_TTL:-}" ] || nc_ttl=$VWARD_CONSOLE_CACHE_TTL
    if [ "$nc_ttl" -gt 0 ] 2>/dev/null && [ -r "$nc_file" ]; then
        nc_at=0; read -r nc_at < "$nc_file" || nc_at=0
        case "$nc_at" in ''|*[!0-9]*) nc_at=0 ;; esac
        if [ $(( $(date +%s) - nc_at )) -lt "$nc_ttl" ]; then sed 1d "$nc_file"; return 0; fi
    fi
    nc_out="$("${VWARD_NDMC:-ndmc}" -c "$3" 2>/dev/null | tr -d '\r')"
    [ -n "$nc_out" ] || return 1
    if [ "$nc_ttl" -gt 0 ] 2>/dev/null; then
        (umask 077; mkdir -p "$NDM_CACHE_DIR" && { date +%s; printf '%s\n' "$nc_out"; } > "$nc_file.$$" && mv -f "$nc_file.$$" "$nc_file") 2>/dev/null
    fi
    printf '%s\n' "$nc_out"
}

# kv_file FILE KEY=VAR...: sets each VAR to the last value of KEY in a
# KEY=VALUE file without starting a process. Variable names come from this
# script only; values are assigned, never evaluated.
kv_file()
{
    kv_f=$1
    shift
    for kv_p; do eval "${kv_p#*=}="; done
    [ -r "$kv_f" ] || return 0
    while IFS= read -r kv_line || [ -n "$kv_line" ]; do
        kv_k=${kv_line%%=*}
        [ "$kv_k" != "$kv_line" ] || continue
        kv_v=${kv_line#*=}
        for kv_p; do
            [ "$kv_k" = "${kv_p%%=*}" ] && eval "${kv_p#*=}=\$kv_v"
        done
    done < "$kv_f"
}

# read_first FILE VAR: first line of FILE into VAR, empty when unreadable.
read_first()
{
    eval "$2="
    [ -r "$1" ] || return 0
    IFS= read -r rf_line < "$1" || [ -n "$rf_line" ] || return 0
    eval "$2=\$rf_line"
}

ACTION="$(qget action)"
[ -n "$ACTION" ] || ACTION=status

case "$ACTION" in
    status|ping|log|settings|settings-data|security-data|route-data|lists-data|diagnostics|route-probe|tunnel-probe|update-data|control-data|control|update-control|config-data|config|cron-data|auth|wifi-data|wifi-control|ads-data|ads-view|ads-https-data|ads-settings|ads-control|ads-https-control|agh-auth|tunnel-conf|backup-data|backup-control|backup-download|wifi-host|files) ;;
    *)
        header_json
        echo '{"ok":false,"error":"unknown_action"}'
        exit 0
        ;;
esac

if [ "${REQUEST_METHOD:-GET}" = POST ]; then
    rm -rf "${NDM_CACHE_DIR:?}"
    [ "${HTTP_X_VWARD_REQUEST:-}" = console ] || {
        echo 'Status: 403 Forbidden'
        header_json
        echo '{"ok":false,"error":"request_guard_failed"}'
        exit 0
    }
    case "${CONTENT_TYPE:-}" in
        application/x-www-form-urlencoded|application/x-www-form-urlencoded\;*) ;;
        *)
            echo 'Status: 415 Unsupported Media Type'
            header_json
            echo '{"ok":false,"error":"unsupported_media_type"}'
            exit 0
            ;;
    esac
    case "$ACTION" in
        settings|control|update-control|config|auth|wifi-control|ads-settings|ads-control|ads-https-control|agh-auth|tunnel-conf|backup-control|wifi-host) ;;
        *)
            echo 'Status: 405 Method Not Allowed'
            header_json
            echo '{"ok":false,"error":"method_not_allowed"}'
            exit 0
            ;;
    esac
fi

ads_kv_json(){ [ -r "$1" ] && awk -F= 'NF>=2{k=$1;sub(/^[^=]*=/,"",$0);print k "\t" $0}' "$1" | "$JQ" -Rn '[inputs|split("\t")|{(.[0]):.[1]}]|add//{}' || echo '{}'; }
ads_valid_domain(){ printf '%s\n' "$1" | awk 'length($0)>0&&length($0)<=253&&index($0,".")>0&&$0!~/\.\./ {n=split($0,a,".");for(i=1;i<=n;i++)if(length(a[i])<1||length(a[i])>63||a[i]!~/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/)exit 1;exit 0}{exit 1}'; }
ads_valid_source_id(){ printf '%s\n' "$1" | awk 'length($0)>=1&&length($0)<=64&&$0~/^[a-z0-9][a-z0-9._-]*$/{exit 0}{exit 1}'; }
# Strict form decoding for URLs: printable ASCII only, anything else is refused.
form_url_decode(){ printf '%s' "$1" | awk 'BEGIN{h="0123456789abcdef"} {s=tolower($0); o=""; while (match(s, /%[0-9a-f][0-9a-f]/)) { c=(index(h,substr(s,RSTART+1,1))-1)*16+index(h,substr(s,RSTART+2,1))-1; if (c<33||c>126) exit 1; o=o substr($0,1,RSTART-1) sprintf("%c",c); $0=substr($0,RSTART+3); s=substr(s,RSTART+3)} print o $0}'; }
ads_console_tmp(){ umask 077; mktemp "/tmp/vward-console-${1}.XXXXXX"; }
updater_mutation_busy(){ [ -e /opt/var/run/vward/updater.lock ] || [ -L /opt/var/run/vward/updater.lock ] || [ -e /tmp/vward-update-requested ] || [ -L /tmp/vward-update-requested ] || [ -e /tmp/vward-update.lock ] || [ -L /tmp/vward-update.lock ]; }
console_mutation_enter(){
  VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
  [ -r "$VWARD_ADMISSION_LIB" ] || return 1
  . "$VWARD_ADMISSION_LIB"
  vward_admission_enter console-mutation
}
COMPONENT_STATE=${VWARD_COMPONENT_STATE:-/opt/etc/vward/components}
component_disabled(){ [ -e "$COMPONENT_STATE/$1.disabled" ]; }
console_mutation_leave(){ command -v vward_admission_leave >/dev/null 2>&1 && vward_admission_leave 2>/dev/null || true; }
UPDATE_RUN_DIR=${VWARD_CONSOLE_UPDATE_RUN:-/opt/var/run/vward/console-update}
CONTROL_RUN_DIR=${VWARD_CONSOLE_CONTROL_RUN:-/opt/var/run/vward/console-control}
# Long operations outlast the browser's 10-second request, so they run
# detached; update-data and control-data report the output and exit code.
run_detached(){
  rd_dir=$1
  mkdir -p "$rd_dir" || { echo '{"ok":false,"error":"action_unavailable"}'; exit 0; }
  rd_pid="$(sed -n 's/^pid=//p' "$rd_dir/run.meta" 2>/dev/null)"
  if ! grep -q '^rc=' "$rd_dir/run.meta" 2>/dev/null && [ -n "$rd_pid" ] && kill -0 "$rd_pid" 2>/dev/null; then
    printf '{"ok":false,"error":"%s"}\n' "$2"; exit 0
  fi
  printf 'label=%s\nstarted=%s\n' "$LABEL" "$START" > "$rd_dir/run.meta"
  (
    if [ -n "$ARGS" ]; then set -f; "$CMD" $ARGS; elif [ -n "$ARG" ]; then "$CMD" "$ARG"; else "$CMD"; fi > "$rd_dir/run.log" 2>&1
    rd_rc=$?
    printf 'rc=%s\n' "$rd_rc" >> "$rd_dir/run.meta"
    printf '%s|CONSOLE_ACTION|action=%s rc=%s\n' "$START" "$LABEL" "$rd_rc" >> /opt/var/log/vward/console-audit.log
  ) </dev/null >/dev/null 2>&1 &
  printf 'pid=%s\n' "$!" >> "$rd_dir/run.meta"
  printf '{"ok":true,"action":"%s","started":true}\n' "$LABEL"
  exit 0
}
run_json(){
  rj_rc="$(sed -n 's/^rc=//p' "$1/run.meta" 2>/dev/null)"
  case "$rj_rc" in ''|*[!0-9]*) rj_rc=null ;; esac
  rj_pid="$(sed -n 's/^pid=//p' "$1/run.meta" 2>/dev/null)"
  rj_active=false
  [ "$rj_rc" = null ] && [ -n "$rj_pid" ] && kill -0 "$rj_pid" 2>/dev/null && rj_active=true
  "$JQ" -nc --arg label "$(sed -n 's/^label=//p' "$1/run.meta" 2>/dev/null)" \
    --arg started "$(sed -n 's/^started=//p' "$1/run.meta" 2>/dev/null)" \
    --argjson running "$rj_active" --argjson rc "$rj_rc" \
    --arg output "$(tail -n 40 "$1/run.log" 2>/dev/null | grep -v '^  \[')" \
    '{label:$label,started:$started,running:$running,finished:($rc != null),rc:$rc,output:$output}'
}

CONFIG_ETC=${VWARD_CONSOLE_ETC:-/opt/etc/vward}
CONFIG_ROUTE_STATE=${VWARD_ROUTE_STATE:-/opt/var/lib/vward/route-engine}
CONFIG_HELPER=${VWARD_CONSOLE_CONFIG_BIN:-/opt/bin/vward-console-config.sh}

# ---------- Console login with the Keenetic account ----------
# Off by default.  The router checks the password (challenge-response on its
# own /auth); VWARD keeps only a hash of the session token with an expiry.
AUTH_CONF=${VWARD_CONSOLE_AUTH_CONF:-/opt/etc/vward/console/auth.conf}
AUTH_SESSIONS=${VWARD_CONSOLE_SESSIONS:-/tmp/vward-console-sessions}
AUTH_URL=${VWARD_KEENETIC_AUTH_URL:-http://${VWARD_LAN_ADDRESS:-127.0.0.1}/auth}
# One pass over the file, no process: this runs on every request.
kv_file "$AUTH_CONF" AUTH_ENABLED=AUTH_ENABLED SESSION_HOURS=AUTH_HOURS DEVICES_ONLY=DEVICES_ONLY
[ "$AUTH_ENABLED" = 1 ] || AUTH_ENABLED=0
[ "$DEVICES_ONLY" = 1 ] || DEVICES_ONLY=0
case "$AUTH_HOURS" in ''|*[!0-9]*) AUTH_HOURS=12 ;; esac
[ "$AUTH_HOURS" -ge 1 ] && [ "$AUTH_HOURS" -le 168 ] || AUTH_HOURS=12
AUTH_LOGIN=""

auth_cookie_token(){ printf '%s\n' "${HTTP_COOKIE:-}" | tr ';' '\n' | sed 's/^ *//' | awk -F= '$1=="vward_session"{print $2; exit}'; }
auth_token_id(){ printf '%s' "$1" | sha256sum | cut -c1-64; }
auth_session_valid(){
    at="$(auth_cookie_token)"
    case "$at" in ''|*[!0-9a-f]*) return 1 ;; esac
    [ "${#at}" -eq 64 ] || return 1
    af="$AUTH_SESSIONS/$(auth_token_id "$at")"
    [ -f "$af" ] && [ ! -L "$af" ] || return 1
    aexp="$(awk -F= '$1=="expires"{print $2; exit}' "$af")"
    case "$aexp" in ''|*[!0-9]*) return 1 ;; esac
    [ "$(date +%s)" -lt "$aexp" ] || { rm -f "$af"; return 1; }
    AUTH_LOGIN="$(awk -F= '$1=="login"{print $2; exit}' "$af")"
}

# ---------- Only devices registered in Keenetic ----------
# Off by default.  The caller's address must belong to a registered host in the
# router's host list (kept 30 s in RAM, re-read at once for an unknown address).
# The router itself always passes; when the host list cannot be read at all the
# request passes too, so a router hiccup never locks the owner out.
DEVICES_CACHE=${VWARD_CONSOLE_DEVICES_CACHE:-/tmp/vward-console-devices}
CLIENT_IP=${REMOTE_ADDR:-}; CLIENT_IP=${CLIENT_IP#::ffff:}
devices_refresh(){
    dr_tmp="$DEVICES_CACHE.$$"
    fetch_json "$VWARD_RCI_BASE/show/ip/hotspot" | "$JQ" -r '(.host // .hosts // []) | (if type == "object" then [.[]] else . end)
        | if length == 0 then error("empty") else . end
        | .[] | select(type == "object" and .registered == true and (.ip // "") != "" and .ip != "0.0.0.0") | .ip' > "$dr_tmp" 2>/dev/null ||
        { rm -f "$dr_tmp"; return 1; }
    { date +%s; cat "$dr_tmp"; } > "$dr_tmp.c" && mv -f "$dr_tmp.c" "$DEVICES_CACHE"; rm -f "$dr_tmp"
}
# device_state: registered | unregistered | unknown
device_state(){
    case "$CLIENT_IP" in 127.0.0.1|::1) echo registered; return ;; '') echo unregistered; return ;; esac
    ds_now="$(date +%s)"; ds_at=0
    [ ! -r "$DEVICES_CACHE" ] || read -r ds_at < "$DEVICES_CACHE"
    case "$ds_at" in ''|*[!0-9]*) ds_at=0 ;; esac
    if [ $((ds_now - ds_at)) -ge 30 ]; then devices_refresh || { echo unknown; return; }; ds_at=$ds_now; fi
    if grep -qxF "$CLIENT_IP" "$DEVICES_CACHE" 2>/dev/null; then echo registered; return; fi
    # A device registered a moment ago: one fresh look before saying no.
    if [ $((ds_now - ds_at)) -ge 5 ]; then
        devices_refresh || { echo unknown; return; }
        grep -qxF "$CLIENT_IP" "$DEVICES_CACHE" 2>/dev/null && { echo registered; return; }
    fi
    echo unregistered
}
if [ "$DEVICES_ONLY" = 1 ] && [ "$ACTION" != ping ] && [ "$(device_state)" = unregistered ]; then
    echo 'Status: 403 Forbidden'
    header_json
    echo '{"ok":false,"error":"device_not_registered"}'
    exit 0
fi

if [ "$AUTH_ENABLED" = 1 ] && [ "$ACTION" != auth ] && [ "$ACTION" != ping ] && ! auth_session_valid; then
    echo 'Status: 401 Unauthorized'
    header_json
    echo '{"ok":false,"error":"auth_required"}'
    exit 0
fi

if [ "$ACTION" = auth ]; then
    if [ "${REQUEST_METHOD:-GET}" = GET ]; then
        header_json
        LOGGED=false; auth_session_valid && LOGGED=true
        "$JQ" -cn --argjson enabled "$([ "$AUTH_ENABLED" = 1 ] && echo true || echo false)" --argjson logged "$LOGGED" --arg login "$AUTH_LOGIN" --argjson hours "$AUTH_HOURS" \
            --argjson devices_only "$([ "$DEVICES_ONLY" = 1 ] && echo true || echo false)" --arg ip "$CLIENT_IP" --arg state "$(device_state)" \
            '{ok:true,enabled:$enabled,logged_in:$logged,login:$login,session_hours:$hours,devices_only:$devices_only,device:{ip:$ip,state:$state}}'
        exit 0
    fi
    LENGTH=${CONTENT_LENGTH:-0}; case "$LENGTH" in ''|*[!0-9]*) LENGTH=0;; esac
    [ "$LENGTH" -gt 0 ] && [ "$LENGTH" -le 1024 ] || { header_json; echo '{"ok":false,"error":"invalid_body"}'; exit 0; }
    BODY=$(dd bs=1 count="$LENGTH" 2>/dev/null)
    aval(){ printf '%s\n' "$BODY" | tr '&' '\n' | awk -F= -v k="$1" '$1==k{print substr($0,index($0,"=")+1);exit}'; }
    AOP="$(aval op)"
    umask 077
    mkdir -p "$AUTH_SESSIONS" 2>/dev/null; chmod 0700 "$AUTH_SESSIONS" 2>/dev/null
    FAILS="$AUTH_SESSIONS/.failures"

    # Password field decoded to raw bytes from stdin, so it never appears in argv.
    auth_password_bytes(){ printf '%s\n' "$BODY" | tr '&' '\n' | LC_ALL=C awk -F= '
        BEGIN {h = "0123456789abcdef"}
        $1 == "password" {
            v = substr($0, index($0, "=") + 1); gsub(/\+/, " ", v); o = ""
            while (match(tolower(v), /%[0-9a-f][0-9a-f]/)) {
                c = (index(h, tolower(substr(v, RSTART + 1, 1))) - 1) * 16 + index(h, tolower(substr(v, RSTART + 2, 1))) - 1
                o = o substr(v, 1, RSTART - 1) sprintf("%c", c); v = substr(v, RSTART + 3)
            }
            printf "%s", o v; exit
        }'; }

    # Challenge-response against the router: never sends or stores the password.
    auth_keenetic(){
        ak_login="$1"; ak_jar="$(mktemp /tmp/vward-console-auth.XXXXXX)" || return 2; ak_hdr="$ak_jar.h"; ak_body="$ak_jar.b"
        ak_code="$("$CURL" -s -o /dev/null -D "$ak_hdr" -c "$ak_jar" --connect-timeout 3 --max-time 6 -w '%{http_code}' "$AUTH_URL" 2>/dev/null)"
        if [ "$ak_code" != 401 ]; then rm -f "$ak_jar" "$ak_hdr" "$ak_body"; return 2; fi
        ak_realm="$(tr -d '\r' < "$ak_hdr" | awk -F': ' 'tolower($1)=="x-ndm-realm"{print $2; exit}')"
        ak_chal="$(tr -d '\r' < "$ak_hdr" | awk -F': ' 'tolower($1)=="x-ndm-challenge"{print $2; exit}')"
        case "$ak_realm$ak_chal" in *[!A-Za-z0-9._\ -]*|'') rm -f "$ak_jar" "$ak_hdr" "$ak_body"; return 2 ;; esac
        ak_md5="$({ printf '%s:%s:' "$ak_login" "$ak_realm"; auth_password_bytes; } | md5sum | cut -c1-32)"
        ak_sha="$(printf '%s%s' "$ak_chal" "$ak_md5" | sha256sum | cut -c1-64)"
        printf '{"login":"%s","password":"%s"}' "$ak_login" "$ak_sha" > "$ak_body"
        ak_code="$("$CURL" -s -o /dev/null -b "$ak_jar" -c "$ak_jar" -H 'Content-Type: application/json' --data-binary "@$ak_body" --connect-timeout 3 --max-time 6 -w '%{http_code}' "$AUTH_URL" 2>/dev/null)"
        rm -f "$ak_jar" "$ak_hdr" "$ak_body"
        [ "$ak_code" = 200 ] && return 0
        return 1
    }

    auth_new_session(){
        find "$AUTH_SESSIONS" -type f ! -name '.*' -mmin +$((AUTH_HOURS * 60)) -exec rm -f {} + 2>/dev/null
        an_token="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
        [ "${#an_token}" -eq 64 ] || return 1
        printf 'login=%s\nexpires=%s\n' "$1" $(( $(date +%s) + AUTH_HOURS * 3600 )) > "$AUTH_SESSIONS/$(auth_token_id "$an_token")" || return 1
        AUTH_COOKIE="vward_session=$an_token; Path=/; HttpOnly; SameSite=Strict; Max-Age=$((AUTH_HOURS * 3600))"
    }

    auth_login_checked(){
        # Brute force: 5 failures within 5 minutes block further attempts for 5 minutes.
        now="$(date +%s)"
        recent="$(awk -v n="$now" '$1+0 > n-300 {c++} END{print c+0}' "$FAILS" 2>/dev/null)"
        [ "${recent:-0}" -lt 5 ] || { header_json; echo '{"ok":false,"error":"too_many_attempts"}'; exit 0; }
        ALOGIN="$(aval login)"
        printf '%s\n' "$ALOGIN" | grep -Eq '^[A-Za-z0-9._@-]{1,64}$' || { header_json; echo '{"ok":false,"error":"invalid_login"}'; exit 0; }
        auth_keenetic "$ALOGIN"; arc=$?
        if [ "$arc" = 2 ]; then header_json; echo '{"ok":false,"error":"router_auth_unavailable"}'; exit 0; fi
        if [ "$arc" != 0 ]; then
            echo "$now" >> "$FAILS"; tail -n 20 "$FAILS" > "$FAILS.t" 2>/dev/null && mv "$FAILS.t" "$FAILS"
            printf '%s|CONSOLE_AUTH|login_failed login=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$ALOGIN" >> /opt/var/log/vward/console-audit.log 2>/dev/null
            header_json; echo '{"ok":false,"error":"wrong_credentials"}'; exit 0
        fi
        : > "$FAILS"
    }

    case "$AOP" in
        login|enable)
            auth_login_checked
            if [ "$AOP" = enable ]; then
                [ -x "$CONFIG_HELPER" ] || { header_json; echo '{"ok":false,"error":"action_unavailable"}'; exit 0; }
                AOUT="$("$CONFIG_HELPER" console-auth 1 2>/dev/null | tail -n 1)"
                case "$AOUT" in result=*) ;; *) header_json; "$JQ" -cn --arg e "${AOUT#error=}" '{ok:false,error:$e}'; exit 0 ;; esac
            fi
            auth_new_session "$ALOGIN" || { header_json; echo '{"ok":false,"error":"session_failed"}'; exit 0; }
            printf '%s|CONSOLE_AUTH|%s login=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$AOP" "$ALOGIN" >> /opt/var/log/vward/console-audit.log 2>/dev/null
            echo "Set-Cookie: $AUTH_COOKIE"; header_json; echo '{"ok":true}'
            ;;
        logout)
            at="$(auth_cookie_token)"; case "$at" in ''|*[!0-9a-f]*) ;; *) rm -f "$AUTH_SESSIONS/$(auth_token_id "$at")" ;; esac
            echo 'Set-Cookie: vward_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'; header_json; echo '{"ok":true}'
            ;;
        disable)
            header_json
            [ "$AUTH_ENABLED" = 0 ] || auth_session_valid || { echo '{"ok":false,"error":"auth_required"}'; exit 0; }
            [ "$(aval confirm)" = CONSOLE_AUTH_DISABLE ] || { echo '{"ok":false,"error":"confirmation_required"}'; exit 0; }
            [ -x "$CONFIG_HELPER" ] || { echo '{"ok":false,"error":"action_unavailable"}'; exit 0; }
            AOUT="$("$CONFIG_HELPER" console-auth 0 2>/dev/null | tail -n 1)"
            case "$AOUT" in result=*) echo '{"ok":true}' ;; *) "$JQ" -cn --arg e "${AOUT#error=}" '{ok:false,error:$e}' ;; esac
            ;;
        devices)
            header_json
            [ "$AUTH_ENABLED" = 0 ] || auth_session_valid || { echo '{"ok":false,"error":"auth_required"}'; exit 0; }
            DV="$(aval value)"; case "$DV" in 0|1) ;; *) echo '{"ok":false,"error":"invalid_value"}'; exit 0 ;; esac
            # Turning it on from a device that would be shut out is refused.
            if [ "$DV" = 1 ]; then
                case "$(device_state)" in registered) ;; unknown) echo '{"ok":false,"error":"devices_unavailable"}'; exit 0 ;; *) echo '{"ok":false,"error":"this_device_not_registered"}'; exit 0 ;; esac
            fi
            [ -x "$CONFIG_HELPER" ] || { echo '{"ok":false,"error":"action_unavailable"}'; exit 0; }
            AOUT="$("$CONFIG_HELPER" console-devices "$DV" 2>/dev/null | tail -n 1)"
            printf '%s|CONSOLE_DEVICES|only_registered=%s ip=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$DV" "$CLIENT_IP" >> /opt/var/log/vward/console-audit.log 2>/dev/null
            case "$AOUT" in result=*) echo '{"ok":true}' ;; *) "$JQ" -cn --arg e "${AOUT#error=}" '{ok:false,error:$e}' ;; esac
            ;;
        *) header_json; echo '{"ok":false,"error":"invalid_operation"}' ;;
    esac
    exit 0
fi

if [ "$ACTION" = wifi-data ]; then
    header_json
    [ "${REQUEST_METHOD:-GET}" = GET ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }
    WCONF=/opt/etc/vward/wifi-client-guard.conf
    WSTATE=/opt/var/lib/vward/wifi-client-guard
    wconf(){ awk -F= -v k="$1" '$1==k{print substr($0,index($0,"=")+1);exit}' "$WCONF" 2>/dev/null; }
    ENABLED="$(wconf ENABLED)"; [ "$ENABLED" = 1 ] || ENABLED=0
    CONTROL_ENABLED="$(wconf CONTROL_ENABLED)"; [ "$CONTROL_ENABLED" = 1 ] || CONTROL_ENABLED=0
    AUTO_APPLY="$(wconf AUTO_APPLY)"; [ "$AUTO_APPLY" = 1 ] || AUTO_APPLY=0
    CLIENTS="$(awk -F '\t' 'NF>=9 && $2 ~ /^([0-9a-fA-F][0-9a-fA-F]:){5}[0-9a-fA-F][0-9a-fA-F]$/ {print $2 "\t" $3 "\t" $4 "\t" $5 "\t" $6 "\t" $7 "\t" $8 "\t" $9}' "$WSTATE/analysis.tsv" 2>/dev/null | head -n 100 | "$JQ" -Rn '[inputs|split("\t")|{mac:.[0],band:.[1],health:.[2],recommendation:.[3],reason:.[4],switches:(.[5]|(tonumber? // 0)),weak_5g:(.[6]|(tonumber? // 0)),min_5g_rssi:.[7]}]')"
    [ -n "$CLIENTS" ] || CLIENTS='[]'
    RC="$(cat /tmp/vward-wifi-client-guard.cron.rc 2>/dev/null)"; case "$RC" in ''|*[!0-9]*) RC=-1;; esac
    LAST="$(cat /tmp/vward-wifi-client-guard.cron.last 2>/dev/null | tr '\n' ' ' | cut -c1-80)"
    COUNT="$(printf '%s' "$CLIENTS" | "$JQ" 'length' 2>/dev/null)"; case "$COUNT" in ''|*[!0-9]*) COUNT=0;; esac
    # Names, addresses and access from the router's host list, by MAC.
    HOSTS="$(fetch_json "$VWARD_RCI_BASE/show/ip/hotspot" | "$JQ" -c '(.host // .hosts // []) | (if type == "object" then [.[]] else . end)
        | map(select(type == "object" and (.mac // "") != "") | {key: (.mac | ascii_downcase), value: {name: (.name // ""), hostname: (.hostname // ""), ip: (.ip // ""),
            registered: (.registered == true), access: (.access // ""), active: (.active == true), uptime: (.uptime // null),
            rx: (.rxbytes // null), tx: (.txbytes // null), rssi: (.rssi // null), txrate: (.txrate // null), ssid: (.ssid // "")}}) | from_entries' 2>/dev/null)"
    [ -n "$HOSTS" ] || HOSTS='{}'
    CLIENTS="$(printf '%s' "$CLIENTS" | "$JQ" -c --argjson h "$HOSTS" 'map(. + {host: ($h[.mac | ascii_downcase] // null)})')"
    "$JQ" -n --argjson enabled "$([ "$ENABLED" = 1 ] && echo true || echo false)" --argjson control_enabled "$([ "$CONTROL_ENABLED" = 1 ] && echo true || echo false)" --argjson auto_apply "$([ "$AUTO_APPLY" = 1 ] && echo true || echo false)" --argjson clients "$CLIENTS" --arg last "$LAST" --argjson rc "$RC" --argjson count "$COUNT" '{ok:true,component:"wifi-client-guard",enabled:$enabled,control_enabled:$control_enabled,auto_apply:$auto_apply,clients:$clients,count:$count,scheduler:{last:$last,rc:$rc}}'
    exit 0
fi

if [ "$ACTION" = wifi-control ]; then
    header_json
    [ "${REQUEST_METHOD:-GET}" = POST ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }
    ! updater_mutation_busy || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }
    console_mutation_enter || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }
    trap console_mutation_leave EXIT
    LENGTH=${CONTENT_LENGTH:-0}; case "$LENGTH" in ''|*[!0-9]*) LENGTH=0;; esac
    [ "$LENGTH" -gt 0 ] && [ "$LENGTH" -le 256 ] || { echo '{"ok":false,"error":"invalid_body"}'; exit 0; }
    BODY=$(dd bs=1 count="$LENGTH" 2>/dev/null)
    wvalue(){ printf '%s\n' "$BODY" | tr '&' '\n' | awk -F= -v k="$1" '$1==k{print substr($0,index($0,"=")+1);exit}'; }
    UNKNOWN="$(printf '%s\n' "$BODY" | tr '&' '\n' | cut -d= -f1 | awk '$0!="op" && $0!="mac" && $0!="confirm" {print;exit}')"
    [ -z "$UNKNOWN" ] || { echo '{"ok":false,"error":"unknown_parameter"}'; exit 0; }
    OP="$(wvalue op)"; MAC="$(wvalue mac | tr 'A-F' 'a-f')"; CONFIRM="$(wvalue confirm)"
    case "$OP" in bind-2g) REQUIRED=WIFI_BIND_2G;; bind-5g) REQUIRED=WIFI_BIND_5G;; auto) REQUIRED=WIFI_BAND_AUTO;; *) echo '{"ok":false,"error":"invalid_operation"}'; exit 0;; esac
    printf '%s\n' "$MAC" | grep -Eiq '^([0-9a-f]{2}:){5}[0-9a-f]{2}$' || { echo '{"ok":false,"error":"invalid_mac"}'; exit 0; }
    [ "$CONFIRM" = "$REQUIRED" ] || { echo '{"ok":false,"error":"confirmation_required"}'; exit 0; }
    ! component_disabled wifi-client-guard || { echo '{"ok":false,"error":"component_disabled"}'; exit 0; }
    WCTL=/opt/bin/vward-wifi-client-control.sh; [ -x "$WCTL" ] || { echo '{"ok":false,"error":"action_unavailable"}'; exit 0; }
    OUT="$("$WCTL" "$OP" "$MAC" "$CONFIRM" 2>&1)"; RC=$?
    printf '%s|CONSOLE_ACTION|action=wifi-%s mac=%s rc=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$OP" "$MAC" "$RC" >> /opt/var/log/vward/console-audit.log
    OUT_JSON="$(printf '%s' "$OUT" | tail -n 80 | "$JQ" -Rs .)"
    [ "$RC" -eq 0 ] && OK=true || OK=false
    printf '{"ok":%s,"action":"wifi-%s","rc":%s,"output":%s}\n' "$OK" "$OP" "$RC" "$OUT_JSON"
    exit 0
fi


if [ "$ACTION" = config-data ]; then
    header_json
    [ "${REQUEST_METHOD:-GET}" = GET ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }
    list_json(){ "$JQ" -Rn '[inputs|select(length>0)]'; }
    kv_get(){ awk -F= -v k="$2" '$1==k{print substr($0,index($0,"=")+1);exit}' "$1" 2>/dev/null; }
    ROUTER=false; ROUTE_DOMAINS='[]'
    if [ "$PROFILE_READY" = true ]; then
        RUNNING="$(ndm_cached running 10 "show running-config")"
        if [ -n "$RUNNING" ]; then
            ROUTER=true
            ROUTE_DOMAINS="$(printf '%s\n' "$RUNNING" | awk -v g="$VWARD_POLICY_GROUP" '
                /^object-group fqdn / {cur=$3; next}
                /^!/ {cur=""; next}
                cur==g && $1=="include" {print tolower($2)}' | head -n 500 | list_json)"
        fi
    fi
    FORCE="$(sed 's/#.*//' "$CONFIG_ETC/route-engine/force-vpn.conf" 2>/dev/null | awk 'NF{print tolower($1)}' | head -n 500 | list_json)"
    ADAPT="$(tr -d '\r' < "$CONFIG_ROUTE_STATE/adaptive-persist.txt" 2>/dev/null | awk 'NF{print tolower($1)}' | head -n 500 | list_json)"
    CATS="$(awk -F'|' 'NF>=5 && $1!~/^[[:space:]]*#/ {print $1 "\t" $2 "\t" $5}' "$CONFIG_ETC/route-engine/categories.tsv" 2>/dev/null | head -n 100 |
        "$JQ" -Rn '[inputs|split("\t")|{id:.[0],title:.[1],enabled:(.[2]=="1")}]')"
    TG=true; [ -e "$CONFIG_ETC/tunnel-guard.disabled" ] && TG=false
    WG_ON=true; [ -e "$CONFIG_ETC/wan-guard.disabled" ] && WG_ON=false
    AD_ON=true; [ -e "$CONFIG_ETC/route-engine/adaptive.disabled" ] && AD_ON=false
    CL_ON=true; [ "$(kv_get "$CONFIG_ETC/route-engine/domain-classifier.conf" CLASSIFIER_ENABLED)" = 0 ] && CL_ON=false
    IPX="$(awk 'NF{print $1}' "${VWARD_POLICY_EXCLUDED:-$CONFIG_ETC/policy-sync/excluded.categories}" 2>/dev/null | head -n 500 | list_json)"
    WCONF=${VWARD_WIFI_CLIENT_GUARD_CONF:-$CONFIG_ETC/wifi-client-guard.conf}
    UCONF=${VWARD_UPDATE_CONFIG:-$CONFIG_ETC/update.conf}
    GCONF=${VWARD_WAN_GUARD_CONF:-$CONFIG_ETC/wan-guard.conf}
    gnum(){ V="$(kv_get "$GCONF" "$1")"; case "$V" in ''|*[!0-9]*) V=$2;; esac; printf '%s' "$V"; }
    WAN_PARAMS="$("$JQ" -cn --arg a "$(gnum CONFIRM_FAILURES 3)" --arg b "$(gnum RENEW_COOLDOWN 600)" --arg c "$(gnum BOUNCE_COOLDOWN 1800)" \
        --arg d "$(gnum MAX_RENEW_HOUR 3)" --arg e "$(gnum MAX_BOUNCE_HOUR 2)" --arg f "$(gnum MAX_BOUNCE_DAY 6)" \
        '{CONFIRM_FAILURES:($a|tonumber),RENEW_COOLDOWN:($b|tonumber),BOUNCE_COOLDOWN:($c|tonumber),MAX_RENEW_HOUR:($d|tonumber),MAX_BOUNCE_HOUR:($e|tonumber),MAX_BOUNCE_DAY:($f|tonumber)}')"
    [ -n "$WAN_PARAMS" ] || WAN_PARAMS='{}'
    wnum(){ V="$(kv_get "$WCONF" "$1")"; case "$V" in ''|*[!0-9-]*) V=$2;; esac; printf '%s' "$V"; }
    COMPONENT_REGISTRY=${VWARD_COMPONENT_REGISTRY:-/opt/share/vward/updater/current/component-registry.json}
    DISABLED="$(for F in "$COMPONENT_STATE"/*.disabled; do [ -e "$F" ] && basename "$F" .disabled; done | list_json)"
    COMPONENTS="$("$JQ" -c --argjson off "${DISABLED:-[]}" '[.components[] | {id, core:(.core == true), depends_on:(.depends_on // []), requires_running:(.requires_running // []), uses:(.uses // []), enabled:((.id | IN($off[])) | not)}]' "$COMPONENT_REGISTRY" 2>/dev/null)"
    [ -n "$COMPONENTS" ] || COMPONENTS='[]'
    W_EN="$(kv_get "$WCONF" ENABLED)"; [ "$W_EN" = 1 ] || W_EN=0
    W_CTL="$(kv_get "$WCONF" CONTROL_ENABLED)"; [ "$W_CTL" = 1 ] || W_CTL=0
    "$JQ" -n \
      --arg group "${VWARD_POLICY_GROUP:-}" --argjson router "$ROUTER" \
      --argjson route_domains "${ROUTE_DOMAINS:-[]}" --argjson force "${FORCE:-[]}" --argjson adaptive "${ADAPT:-[]}" \
      --argjson categories "${CATS:-[]}" --argjson tunnel_guard "$TG" --argjson wan_guard "$WG_ON" --argjson components "$COMPONENTS" \
      --argjson adaptive_on "$AD_ON" --argjson classifier_on "$CL_ON" --argjson ip_excluded "${IPX:-[]}" \
      --argjson w_en "$W_EN" --argjson w_ctl "$W_CTL" \
      --argjson wan_params "$WAN_PARAMS" \
      --arg w_window "$(wnum WINDOW_SEC 86400)" --arg w_switch "$(wnum BAND_SWITCH_WARN 20)" \
      --arg w_weak "$(wnum WEAK_5G_SAMPLE_WARN 5)" --arg w_rssi "$(wnum WEAK_5G_RSSI -75)" \
      --arg u_start "$(kv_get "$UCONF" safe_window_start)" --arg u_end "$(kv_get "$UCONF" safe_window_end)" \
      --arg u_interval "$(kv_get "$UCONF" check_interval_seconds)" \
      --arg u_window "$(kv_get "$UCONF" apply_window)" \
      --arg u_feed "$(kv_get "$UCONF" manifest_url | sed -n -E 's#^https://raw[.]githubusercontent[.]com/[^/]+/[^/]+/(beta|dev)/updates/[a-z0-9-]+/update-manifest[.]json$#\1#p')" \
      --argjson writable "$([ -x "$CONFIG_HELPER" ] && echo true || echo false)" \
      '{ok:true,writable:$writable,
        route:{group:$group,router_available:$router,domains:$route_domains,force_vpn:$force,adaptive:$adaptive,categories:$categories,adaptive_enabled:$adaptive_on,classifier_enabled:$classifier_on,ip_excluded:$ip_excluded},
        tunnel_guard:{enabled:$tunnel_guard},wan_guard:{enabled:$wan_guard,params:$wan_params},components:$components,
        wifi:{ENABLED:($w_en==1),CONTROL_ENABLED:($w_ctl==1),WINDOW_SEC:($w_window|(tonumber? // null)),BAND_SWITCH_WARN:($w_switch|(tonumber? // null)),WEAK_5G_SAMPLE_WARN:($w_weak|(tonumber? // null)),WEAK_5G_RSSI:($w_rssi|(tonumber? // null))},
        update:{safe_window_start:$u_start,safe_window_end:$u_end,check_interval_seconds:($u_interval|(tonumber? // null)),apply_window:(if $u_window == "any" then "any" else "window" end),feed:(if $u_feed == "" then "custom" else $u_feed end)}}'
    exit 0
fi

if [ "$ACTION" = config ]; then
    header_json
    [ "${REQUEST_METHOD:-GET}" = POST ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }
    ! updater_mutation_busy || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }
    console_mutation_enter || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }
    trap console_mutation_leave EXIT
    LENGTH=${CONTENT_LENGTH:-0}; case "$LENGTH" in ''|*[!0-9]*) LENGTH=0;; esac
    [ "$LENGTH" -gt 0 ] && [ "$LENGTH" -le 512 ] || { echo '{"ok":false,"error":"invalid_body"}'; exit 0; }
    BODY=$(dd bs=1 count="$LENGTH" 2>/dev/null)
    UNKNOWN="$(printf '%s\n' "$BODY" | tr '&' '\n' | cut -d= -f1 | awk '$0!="op"&&$0!="action"&&$0!="target"&&$0!="value"&&$0!="confirm"{print;exit}')"
    [ -z "$UNKNOWN" ] || { echo '{"ok":false,"error":"unknown_parameter"}'; exit 0; }
    # Only the characters the helper accepts; ':' and '-' may arrive percent-encoded.
    fval(){ printf '%s\n' "$BODY" | tr '&' '\n' | awk -F= -v k="$1" '$1==k{print substr($0,index($0,"=")+1);exit}' | sed 's/%3[Aa]/:/g;s/%2[Dd]/-/g'; }
    OP="$(fval op)"; ACT="$(fval action)"; TARGET="$(fval target)"; VALUE="$(fval value)"; CONFIRM="$(fval confirm)"
    for F in "$OP" "$ACT" "$TARGET" "$VALUE" "$CONFIRM"; do
        case "$F" in *[!A-Za-z0-9._:-]*) echo '{"ok":false,"error":"invalid_value"}'; exit 0 ;; esac
        [ "${#F}" -le 253 ] || { echo '{"ok":false,"error":"invalid_value"}'; exit 0; }
    done
    REQUIRED=
    case "$OP" in
        route-domain|force-vpn|adaptive) set -- "$OP" "$ACT" "$TARGET" ;;
        domain-category|wifi|update|wan-param) set -- "$OP" "$TARGET" "$VALUE" ;;
        tunnel-guard) set -- "$OP" "$VALUE"; [ "$VALUE" != 0 ] || REQUIRED=TUNNEL_GUARD_DISABLE ;;
        wan-guard) set -- "$OP" "$VALUE"; [ "$VALUE" != 0 ] || REQUIRED=WAN_GUARD_DISABLE ;;
        component) set -- "$OP" "$TARGET" "$VALUE"; [ "$VALUE" != 0 ] || REQUIRED=COMPONENT_DISABLE ;;
        adaptive-mode|classifier|smartdns-guard) set -- "$OP" "$VALUE" ;;
        ip-category) set -- "$OP" "$TARGET" "$VALUE" ;;
        tunnel) set -- "$OP" "$TARGET"; REQUIRED=TUNNEL_SWITCH ;;
        domain-list|domain-list-watch) set -- "$OP" "$TARGET" "$VALUE" ;;
        update-feed) set -- "$OP" "$TARGET"; [ "$TARGET" != dev ] || REQUIRED=UPDATE_FEED_DEV ;;
        *) echo '{"ok":false,"error":"invalid_operation"}'; exit 0 ;;
    esac
    [ "$OP:$TARGET:$VALUE" != wifi:CONTROL_ENABLED:1 ] || REQUIRED=WIFI_CONTROL_ENABLE
    [ -z "$REQUIRED" ] || [ "$CONFIRM" = "$REQUIRED" ] || { echo '{"ok":false,"error":"confirmation_required"}'; exit 0; }
    [ -x "$CONFIG_HELPER" ] || { echo '{"ok":false,"error":"action_unavailable"}'; exit 0; }
    OUT="$("$CONFIG_HELPER" "$@" 2>/dev/null | tail -n 1)"
    case "$OUT" in
        result=changed|result=unchanged) "$JQ" -cn --arg op "$OP" --arg r "${OUT#result=}" '{ok:true,op:$op,result:$r}' ;;
        error=*) E="${OUT#error=}"; case "$E" in *[!a-z0-9_]*) E=helper_failed;; esac; "$JQ" -cn --arg op "$OP" --arg e "$E" '{ok:false,op:$op,error:$e}' ;;
        *) "$JQ" -cn --arg op "$OP" '{ok:false,op:$op,error:"helper_failed"}' ;;
    esac
    exit 0
fi

if [ "$ACTION" = cron-data ]; then
    header_json
    [ "${REQUEST_METHOD:-GET}" = GET ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }
    CRONTAB=${VWARD_CRONTAB:-/opt/var/spool/cron/crontabs/root}
    [ -r "$CRONTAB" ] || CRONTAB=${VWARD_CRONTAB_SHIPPED:-/opt/etc/vward/cron/root.crontab}
    COMPONENT_REGISTRY=${VWARD_COMPONENT_REGISTRY:-/opt/share/vward/updater/current/component-registry.json}
    OWNERS="$("$JQ" -c '[.components[] | .id as $id | .runtime_targets[] | {(.): $id}] | add // {}' "$COMPONENT_REGISTRY" 2>/dev/null)"
    [ -n "$OWNERS" ] || OWNERS='{}'
    # One row per job: the 5 schedule fields, the entry point and its status file prefix.
    JOBS="$(awk '$1 !~ /^#/ && NF >= 6 {
            match($0, /\/opt\/(bin|etc\/init\.d)\/[A-Za-z0-9_.-]+/); script = (RSTART ? substr($0, RSTART, RLENGTH) : "")
            match($0, /date > \/tmp\/[A-Za-z0-9_.-]+\.cron\.last/); tag = (RSTART ? substr($0, RSTART + 12, RLENGTH - 22) : "")
            if (script != "") print $1 " " $2 " " $3 " " $4 " " $5 "\t" script "\t" tag
        }' "$CRONTAB" 2>/dev/null | head -n 40 |
        while IFS="$(printf '\t')" read -r SCHED SCRIPT TAG; do
            case "$TAG" in ''|*[!A-Za-z0-9_.-]*) LASTV=""; RCV="" ;; *)
                LASTV="$(head -n 1 "/tmp/$TAG.cron.last" 2>/dev/null | cut -c1-60)"; RCV="$(head -n 1 "/tmp/$TAG.cron.rc" 2>/dev/null)" ;; esac
            case "$RCV" in *[!0-9]*) RCV="" ;; esac
            printf '%s\t%s\t%s\t%s\n' "$SCHED" "$SCRIPT" "$LASTV" "$RCV"
        done | "$JQ" -Rn --argjson owners "$OWNERS" '[inputs | split("\t") | {schedule: .[0], script: .[1], name: (.[1] | split("/") | last), component: ($owners[.[1]] // ""), last: .[2], rc: (.[3] | tonumber? // null)}]')"
    [ -n "$JOBS" ] || JOBS='[]'
    CRON_UP=false; pidof crond >/dev/null 2>&1 && CRON_UP=true
    "$JQ" -cn --argjson jobs "$JOBS" --argjson up "$CRON_UP" '{ok: true, crond: $up, jobs: $jobs}'
    exit 0
fi

if [ "$ACTION" = ads-view ]; then
  header_json; [ "${REQUEST_METHOD:-GET}" = GET ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }
  V="$(qget view)"; F="$(qget filter)"; Q="$(qget search | tr '[:upper:]' '[:lower:]')"; K="$(qget kind)"
  for X in "$V" "$F" "$Q" "$K"; do case "$X" in *[!a-z0-9.-]*) echo '{"ok":false,"error":"invalid_value"}'; exit 0 ;; esac; done
  case "$V" in querylog|stats|list|publish-status|agh) ;; *) echo '{"ok":false,"error":"invalid_view"}'; exit 0 ;; esac
  VIEW_BIN=${VWARD_ADS_VIEW_BIN:-/opt/bin/vward-ads-privacy-view.sh}; [ -x "$VIEW_BIN" ] || { echo '{"ok":false,"error":"action_unavailable"}'; exit 0; }
  case "$V" in
    querylog) OUTV="$("$VIEW_BIN" querylog "${F:-all}" "$Q" 2>/dev/null)" ;;
    stats) OUTV="$("$VIEW_BIN" stats 2>/dev/null)" ;;
    list) OUTV="$("$VIEW_BIN" list "$K" "$Q" 2>/dev/null)" ;;
    publish-status) OUTV="$("$VIEW_BIN" publish-status 2>/dev/null)" ;;
    agh) OUTV="$("$VIEW_BIN" agh 2>/dev/null)" ;;
    *) echo '{"ok":false,"error":"invalid_view"}'; exit 0 ;;
  esac
  printf '%s\n' "$OUTV" | "$JQ" -ce 'if type == "object" then . else error end' 2>/dev/null || echo '{"ok":false,"error":"view_failed"}'
  exit 0
fi

if [ "$ACTION" = ads-data ]; then
  header_json; [ "${REQUEST_METHOD:-GET}" = GET ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }
  AETC=/opt/etc/vward/ads-privacy-guard; AST=/opt/var/lib/vward/ads-privacy-guard; ASH=/opt/share/vward/ads-privacy-guard
  SETTINGS=/opt/bin/vward-ads-privacy-settings.sh; SRCCTL=/opt/bin/vward-ads-privacy-source-control.sh; JOB=/opt/bin/vward-ads-privacy-job.sh
  SETJSON="$([ -x "$SETTINGS" ] && "$SETTINGS" show 2>/dev/null | awk -F= '$1!="PAUSED"&&NF>=2{k=$1;sub(/^[^=]*=/,"",$0);print k "\t" $0}' | "$JQ" -Rn '[inputs|split("\t")|{(.[0]):.[1]}]|add//{}' || echo '{}')"
  PAUSED="$([ -r "$AST/control.state" ] && awk -F= '$1=="paused"{print $2;exit}' "$AST/control.state")"; [ "$PAUSED" = 1 ] || PAUSED=0
  BLOCKED="$(awk -F'|' '$3=="BLOCK"{n++}END{print n+0}' "$AST/verdicts.tsv" 2>/dev/null)"; REVIEW="$(awk -F'|' '$2=="SUSPECT"{n++}END{print n+0}' "$AST/verdicts.tsv" 2>/dev/null)"; ALLOW="$(awk -F'|' '$2=="ALLOW"{n++}END{print n+0}' "$AST/verdicts.tsv" 2>/dev/null)"; TRUST="$(awk -F'|' '$2=="TRUST"{n++}END{print n+0}' "$AST/verdicts.tsv" 2>/dev/null)"
  MANUAL="$({ awk -F'|' 'NF>=2&&$1!~/^[[:space:]]*#/{print "allow|"$1"|"$2"|"$3}' "$AETC/allowlist.tsv" 2>/dev/null; awk -F'|' 'NF>=2&&$1!~/^[[:space:]]*#/{print "block|"$1"|"$2"|"$3}' "$AETC/denylist.tsv" 2>/dev/null; } | head -n 300 | "$JQ" -Rn '[inputs|split("|")|{type:.[0],domain:.[1],scope:.[2],note:(.[3:]|join("|"))}]')"
  SOURCES="$([ -x "$SRCCTL" ] && "$SRCCTL" list 2>/dev/null | "$JQ" -Rn --arg state "$AST/sources" '[inputs|split("|")|{id:.[0],mode:.[1],name:.[2],cached:(.[3]=="1"),purpose:.[4],custom:(.[5]=="1")}]' || echo '[]')"
  JOBS="$([ -x "$JOB" ] && "$JOB" status 2>/dev/null | awk -F= 'NF>=2{k=$1;sub(/^[^=]*=/,"",$0);print k "\t" $0}' | "$JQ" -Rn '[inputs|split("\t")|{(.[0]):.[1]}]|add//{}' || echo '{}')"
  LAST_OUTPUT_PATH="$(printf '%s' "$JOBS" | "$JQ" -r '.LAST_output // ""' 2>/dev/null)"; LAST_OUTPUT=""
  case "$LAST_OUTPUT_PATH" in "$AST/jobs/"*.out) [ -r "$LAST_OUTPUT_PATH" ] && LAST_OUTPUT="$(head -c 20000 "$LAST_OUTPUT_PATH" 2>/dev/null)" ;; esac
  AGH_ON=false; [ -s "${VWARD_ADS_AGH_AUTH_FILE:-$AETC/agh-api.auth}" ] && AGH_ON=true
  # The last scan and the newest domains it judged (the built-in trusted ones are left out).
  SCAN="$([ -r "$AST/last-run.status" ] && awk -F= 'NF>=2{k=$1;sub(/^[^=]*=/,"",$0);print k "\t" $0}' "$AST/last-run.status" | "$JQ" -Rn '[inputs|split("\t")|{(.[0]):.[1]}]|add//{}' 2>/dev/null)"; [ -n "$SCAN" ] || SCAN='{}'
  RECENT="$(awk -F'|' 'NF>=8 && $2!="TRUST" {print $5 "\t" $1 "\t" $2 "\t" $3 "\t" $8}' "$AST/verdicts.tsv" 2>/dev/null | sort -r | head -n 10 | "$JQ" -Rn '[inputs|split("\t")|{first_seen:.[0],domain:.[1],verdict:.[2],action:.[3],reason:.[4]}]' 2>/dev/null)"; [ -n "$RECENT" ] || RECENT='[]'
  "$JQ" -n --argjson scan "$SCAN" --argjson recent "$RECENT" --argjson agh "$AGH_ON" --argjson paused "$([ "$PAUSED" = 1 ]&&echo true||echo false)" --argjson settings "$SETJSON" --argjson sources "$SOURCES" --argjson manual "$MANUAL" --argjson jobsraw "$JOBS" --arg job_output "$LAST_OUTPUT" --argjson b "${BLOCKED:-0}" --argjson r "${REVIEW:-0}" --argjson a "${ALLOW:-0}" --argjson t "${TRUST:-0}" '{ok:true,component:"ads-privacy-guard",agh_connected:$agh,scan:$scan,recent:$recent,paused:$paused,settings:$settings,sources:$sources,manual_rules:$manual,counts:{blocked:$b,review:$r,allow:$a,trust:$t},categories:($sources | group_by(.purpose) | map({id:.[0].purpose, total:length, active:(map(select(.mode != "off")) | length)})),jobs:{queued:($jobsraw.JOB_QUEUE//"0"|(tonumber? // 0)),current:{state:($jobsraw.CURRENT_state//"IDLE"),type:($jobsraw.CURRENT_type//"")},last:{id:($jobsraw.LAST_id//""),state:($jobsraw.LAST_state//"NONE"),type:($jobsraw.LAST_type//""),arg:($jobsraw.LAST_arg//""),output:$job_output}}}'
  exit 0
fi


if [ "$ACTION" = ads-https-data ]; then
  header_json; [ "${REQUEST_METHOD:-GET}" = GET ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }
  HTTPSCTL=/opt/bin/vward-ads-privacy-https.sh
  [ -x "$HTTPSCTL" ] || { echo '{"ok":false,"error":"https_backend_missing"}'; exit 0; }
  OUT="$(ads_console_tmp ads-https-data)" || { echo '{"ok":false,"error":"temporary_file_failed"}'; exit 0; }; "$HTTPSCTL" status >"$OUT" 2>&1; RC=$?
  if [ "$RC" -ne 0 ]; then RES="$(head -c 12000 "$OUT")"; rm -f "$OUT"; "$JQ" -n --arg output "$RES" --argjson rc "$RC" '{ok:false,error:"https_status_failed",rc:$rc,output:$output}'; exit 0; fi
  STATUS="$(awk -F= 'NF>=2{k=$1;sub(/^[^=]*=/,"",$0);print k "\t" $0}' "$OUT" | "$JQ" -Rn '[inputs|split("\t")|{(.[0]):.[1]}]|add//{}')"; rm -f "$OUT"
  "$JQ" -n --argjson status "$STATUS" '{ok:true,status:$status}'
  exit 0
fi

if [ "$ACTION" = ads-https-control ]; then
  header_json; [ "${REQUEST_METHOD:-GET}" = POST ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }; ! updater_mutation_busy || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }; console_mutation_enter || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }; trap console_mutation_leave EXIT
  ! component_disabled ads-privacy-guard || { echo '{"ok":false,"error":"component_disabled"}'; exit 0; }
  LEN=${CONTENT_LENGTH:-0}; case "$LEN" in ''|*[!0-9]*) LEN=0;; esac; [ "$LEN" -gt 0 ]&&[ "$LEN" -le 512 ] || { echo '{"ok":false,"error":"invalid_body"}'; exit 0; }; BODY=$(dd bs=1 count="$LEN" 2>/dev/null)
  val(){ printf '%s\n' "$BODY"|tr '&' '\n'|awk -F= -v k="$1" '$1==k{print substr($0,index($0,"=")+1);exit}'; }
  OP="$(val op)"; CONFIRM="$(val confirm)"; case "$OP" in validate|render|pac|stop) ;; ca-init) [ "$CONFIRM" = HTTPS_CA_INIT ] || { echo '{"ok":false,"error":"confirmation_required"}'; exit 0; } ;; start|restart) [ "$CONFIRM" = HTTPS_START ] || { echo '{"ok":false,"error":"confirmation_required"}'; exit 0; } ;; *) echo '{"ok":false,"error":"invalid_operation"}'; exit 0;; esac
  HTTPSCTL=/opt/bin/vward-ads-privacy-https.sh; [ -x "$HTTPSCTL" ] || { echo '{"ok":false,"error":"https_backend_missing"}'; exit 0; }
  OUT="$(ads_console_tmp ads-https-control)" || { echo '{"ok":false,"error":"temporary_file_failed"}'; exit 0; }; RC=0
  case "$OP" in ca-init) "$HTTPSCTL" ca-init --confirm >"$OUT" 2>&1||RC=$? ;; start) "$HTTPSCTL" start --confirm >"$OUT" 2>&1||RC=$? ;; restart) "$HTTPSCTL" restart --confirm >"$OUT" 2>&1||RC=$? ;; *) "$HTTPSCTL" "$OP" >"$OUT" 2>&1||RC=$? ;; esac
  RES="$(head -c 12000 "$OUT" 2>/dev/null)"; rm -f "$OUT"; printf '%s|ADS_HTTPS|op=%s rc=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$OP" "$RC" >>/opt/var/log/vward/console-audit.log
  "$JQ" -n --argjson ok "$([ "$RC" -eq 0 ]&&echo true||echo false)" --argjson rc "$RC" --arg output "$RES" '{ok:$ok,rc:$rc,output:$output}'
  exit 0
fi

# tunnel-conf: a WireGuard/AmneziaWG .conf from the browser.  check parses it;
# replace and create prove it on the router and run in the background
# (control-data reports them); delete and subnet-add/-remove are quick.
if [ "$ACTION" = tunnel-conf ]; then
  header_json; [ "${REQUEST_METHOD:-GET}" = POST ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }
  ! updater_mutation_busy || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }
  [ -x "$CONFIG_HELPER" ] || { echo '{"ok":false,"error":"action_unavailable"}'; exit 0; }
  LEN=${CONTENT_LENGTH:-0}; case "$LEN" in ''|*[!0-9]*) LEN=0;; esac
  [ "$LEN" -gt 0 ] && [ "$LEN" -le 49152 ] || { echo '{"ok":false,"error":"invalid_body"}'; exit 0; }
  BODY=$(dd bs=4096 count=$(( (LEN + 4095) / 4096 )) 2>/dev/null | head -c "$LEN")
  val(){ printf '%s\n' "$BODY" | tr '&' '\n' | awk -F= -v k="$1" '$1==k{print substr($0,index($0,"=")+1);exit}'; }
  TOP="$(val op)"; TNAME="$(val name)"; TCONF="$(val confirm)"
  case "$TNAME" in *[!A-Za-z0-9_.-]*) echo '{"ok":false,"error":"invalid_tunnel"}'; exit 0 ;; esac
  # A decoded value: printable text, tabs and line breaks only.
  tdecode(){ printf '%s\n' "$BODY" | tr '&' '\n' | LC_ALL=C awk -F= -v k="$1" '
      BEGIN {h = "0123456789abcdef"}
      $1 == k {
        v = substr($0, index($0, "=") + 1); gsub(/\+/, " ", v); o = ""
        while (match(tolower(v), /%[0-9a-f][0-9a-f]/)) {
          c = (index(h, tolower(substr(v, RSTART + 1, 1))) - 1) * 16 + index(h, tolower(substr(v, RSTART + 2, 1))) - 1
          if (c < 32 && c != 9 && c != 10 && c != 13 || c > 126) exit 1
          o = o substr(v, 1, RSTART - 1) sprintf("%c", c); v = substr(v, RSTART + 3)
        }
        printf "%s", o v; exit
      }'; }
  case "$TOP" in
    check|replace|create)
      TUNNEL_TMP=${VWARD_CONSOLE_TUNNEL_TMP:-/opt/var/run/vward/console-tunnel}
      (umask 077; mkdir -p "$TUNNEL_TMP") || { echo '{"ok":false,"error":"temporary_file_unavailable"}'; exit 0; }
      TFILE="$(umask 077; mktemp "$TUNNEL_TMP/upload.XXXXXX" 2>/dev/null)" || { echo '{"ok":false,"error":"temporary_file_unavailable"}'; exit 0; }
      tdecode conf > "$TFILE" || { rm -f "$TFILE"; echo '{"ok":false,"error":"conf_syntax"}'; exit 0; }
      [ -s "$TFILE" ] || { rm -f "$TFILE"; echo '{"ok":false,"error":"conf_empty"}'; exit 0; }
      if [ "$TOP" = check ]; then
        TOUT="$("$CONFIG_HELPER" tunnel-conf check "$TFILE" 2>/dev/null)"; rm -f "$TFILE"
        case "$(printf '%s\n' "$TOUT" | tail -n 1)" in
          result=checked) printf '%s\n' "$TOUT" | sed -n 's/^info\.//p' | "$JQ" -Rn '[inputs | split("=") | {(.[0]): (.[1:] | join("="))}] | add + {ok: true}' ;;
          error=*) E="$(printf '%s\n' "$TOUT" | tail -n 1)"; E=${E#error=}; case "$E" in *[!a-z0-9_]*) E=helper_failed;; esac; printf '{"ok":false,"error":"%s"}\n' "$E" ;;
          *) echo '{"ok":false,"error":"helper_failed"}' ;;
        esac
        exit 0
      fi
      if [ "$TOP" = replace ]; then
        [ -n "$TNAME" ] || { rm -f "$TFILE"; echo '{"ok":false,"error":"invalid_tunnel"}'; exit 0; }
        [ "$TCONF" = TUNNEL_REPLACE ] || { rm -f "$TFILE"; echo '{"ok":false,"error":"confirmation_required"}'; exit 0; }
        ARGS="tunnel-conf replace $TFILE $TNAME"
      else
        TDESC="$(tdecode description | tr -d '\t\r\n')" || TDESC=""
        case "$TDESC" in ''|*'"'*|*"$(printf '\134')"*) rm -f "$TFILE"; echo '{"ok":false,"error":"invalid_description"}'; exit 0 ;; esac
        [ "${#TDESC}" -le 64 ] || { rm -f "$TFILE"; echo '{"ok":false,"error":"invalid_description"}'; exit 0; }
        # The description may hold spaces: it goes through a file, not the argument list.
        printf '%s' "$TDESC" > "$TFILE.desc"
        ARGS="tunnel-conf create $TFILE @$TFILE.desc"
      fi
      CMD="$CONFIG_HELPER" LABEL="tunnel-$TOP" START="$(date '+%Y-%m-%dT%H:%M:%S%z')" ARG=""
      run_detached "$CONTROL_RUN_DIR" control_busy ;;
    delete|subnet-add|subnet-remove)
      console_mutation_enter || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }; trap console_mutation_leave EXIT
      if [ "$TOP" = delete ]; then
        [ "$TCONF" = TUNNEL_DELETE ] || { echo '{"ok":false,"error":"confirmation_required"}'; exit 0; }
        TTO="$(val target)"; case "$TTO" in ''|*[!A-Za-z0-9_.-]*) echo '{"ok":false,"error":"invalid_value"}'; exit 0 ;; esac
        set -- tunnel-delete "$TNAME" "$TTO"
      else
        TNET="$(tdecode subnet)" || TNET=""
        case "$TNET" in ''|*[!0-9./]*) echo '{"ok":false,"error":"invalid_subnet"}'; exit 0 ;; esac
        set -- tunnel-subnet "$TNAME" "${TOP#subnet-}" "$TNET"
      fi
      TOUT="$("$CONFIG_HELPER" "$@" 2>/dev/null | tail -n 1)"
      case "$TOUT" in
        result=changed|result=unchanged) "$JQ" -cn --arg r "${TOUT#result=}" '{ok:true,result:$r}' ;;
        error=*) E="${TOUT#error=}"; case "$E" in *[!a-z0-9_]*) E=helper_failed;; esac; printf '{"ok":false,"error":"%s"}\n' "$E" ;;
        *) echo '{"ok":false,"error":"helper_failed"}' ;;
      esac ;;
    *) echo '{"ok":false,"error":"invalid_operation"}' ;;
  esac
  exit 0
fi

# wifi-host: a Wi-Fi client's name in Keenetic and its internet access.
if [ "$ACTION" = wifi-host ]; then
  header_json; [ "${REQUEST_METHOD:-GET}" = POST ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }
  ! updater_mutation_busy || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }
  [ -x "$CONFIG_HELPER" ] || { echo '{"ok":false,"error":"action_unavailable"}'; exit 0; }
  LEN=${CONTENT_LENGTH:-0}; case "$LEN" in ''|*[!0-9]*) LEN=0;; esac; [ "$LEN" -gt 0 ] && [ "$LEN" -le 1024 ] || { echo '{"ok":false,"error":"invalid_body"}'; exit 0; }
  BODY=$(dd bs=1 count="$LEN" 2>/dev/null)
  val(){ printf '%s\n' "$BODY" | tr '&' '\n' | awk -F= -v k="$1" '$1==k{print substr($0,index($0,"=")+1);exit}'; }
  WMAC="$(val mac | sed 's/%3[Aa]/:/g')"
  printf '%s\n' "$WMAC" | grep -Eq '^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$' || { echo '{"ok":false,"error":"invalid_mac"}'; exit 0; }
  case "$(val op)" in
    name)
      # The name as UTF-8 text: no control characters, quotes or backslashes.
      WNAME="$(printf '%s\n' "$BODY" | tr '&' '\n' | LC_ALL=C awk -F= '
        BEGIN {h = "0123456789abcdef"}
        $1 == "name" {
          v = substr($0, index($0, "=") + 1); gsub(/\+/, " ", v); o = ""
          while (match(tolower(v), /%[0-9a-f][0-9a-f]/)) {
            c = (index(h, tolower(substr(v, RSTART + 1, 1))) - 1) * 16 + index(h, tolower(substr(v, RSTART + 2, 1))) - 1
            if (c < 32 || c == 34 || c == 92 || c == 127) exit 1
            o = o substr(v, 1, RSTART - 1) sprintf("%c", c); v = substr(v, RSTART + 3)
          }
          printf "%s", o v; exit
        }')" || { echo '{"ok":false,"error":"invalid_name"}'; exit 0; }
      [ -n "$WNAME" ] && [ "${#WNAME}" -le 64 ] || { echo '{"ok":false,"error":"invalid_name"}'; exit 0; }
      WFILE="$(umask 077; mktemp /tmp/vward-console-name.XXXXXX 2>/dev/null)" || { echo '{"ok":false,"error":"temporary_file_unavailable"}'; exit 0; }
      printf '%s' "$WNAME" > "$WFILE"
      set -- wifi-host "$WMAC" name "@$WFILE" ;;
    access)
      WV="$(val value)"; case "$WV" in permit|deny) ;; *) echo '{"ok":false,"error":"invalid_value"}'; exit 0 ;; esac
      [ "$WV" = permit ] || [ "$(val confirm)" = WIFI_ACCESS_DENY ] || { echo '{"ok":false,"error":"confirmation_required"}'; exit 0; }
      set -- wifi-host "$WMAC" access "$WV" ;;
    *) echo '{"ok":false,"error":"invalid_operation"}'; exit 0 ;;
  esac
  WOUT="$("$CONFIG_HELPER" "$@" 2>/dev/null | tail -n 1)"
  [ -z "${WFILE:-}" ] || rm -f "$WFILE"
  case "$WOUT" in
    result=changed|result=unchanged) "$JQ" -cn --arg r "${WOUT#result=}" '{ok:true,result:$r}' ;;
    error=*) E="${WOUT#error=}"; case "$E" in *[!a-z0-9_]*) E=helper_failed;; esac; printf '{"ok":false,"error":"%s"}\n' "$E" ;;
    *) echo '{"ok":false,"error":"helper_failed"}' ;;
  esac
  exit 0
fi

# Backups of VWARD's settings: list, create, restore, download.
SNAPSHOT_DIR=${VWARD_SNAPSHOT_DIR:-/opt/var/backups/vward/snapshots}
if [ "$ACTION" = backup-data ]; then
  header_json; [ "${REQUEST_METHOD:-GET}" = GET ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }
  ls -ln "$SNAPSHOT_DIR" 2>/dev/null | awk '$9 ~ /^vward-[0-9]+-[0-9]+(-[a-z]+)?[.]tar[.]gz$/ {print $9 "\t" $5}' | sort -r |
    "$JQ" -Rn '[inputs | split("\t") | {name: .[0], size: (.[1] | tonumber? // 0),
      kind: (.[0] | ltrimstr("vward-") | rtrimstr(".tar.gz") | split("-") | if length > 2 then .[2] else "manual" end),
      created: (.[0] | ltrimstr("vward-") | .[0:4] + "-" + .[4:6] + "-" + .[6:8] + "T" + .[9:11] + ":" + .[11:13] + ":" + .[13:15])}] | {ok: true, backups: .}'
  exit 0
fi
if [ "$ACTION" = backup-download ]; then
  BN="$(qget name)"
  printf '%s\n' "$BN" | grep -Eq '^vward-[0-9]{8}-[0-9]{6}(-[a-z]+)?\.tar\.gz$' && [ -f "$SNAPSHOT_DIR/$BN" ] && [ ! -L "$SNAPSHOT_DIR/$BN" ] || { header_json; echo '{"ok":false,"error":"unknown_backup"}'; exit 0; }
  echo 'Content-Type: application/gzip'
  echo "Content-Disposition: attachment; filename=\"$BN\""
  echo 'Cache-Control: no-store'
  echo 'X-Content-Type-Options: nosniff'
  echo "Content-Length: $(wc -c < "$SNAPSHOT_DIR/$BN" | tr -d ' ')"
  echo
  cat "$SNAPSHOT_DIR/$BN"
  exit 0
fi
# Files: VWARD's own folders, read only.  Secrets never leave the router: the
# tunnel store, keys, logins and every file only root may read are listed as
# closed and are neither shown nor downloaded.  Links are not followed.
if [ "$ACTION" = files ]; then
  FOP="$(qget op)"; FROOT="$(qget root)"; FPATH="$(qget path | sed 's/%2[Ff]/\//g; s/%40/@/g; s/%2[Bb]/+/g')"
  fdie() { header_json; printf '{"ok":false,"error":"%s"}\n' "$1"; exit 0; }
  case "$FROOT" in
    etc) FBASE=/opt/etc/vward ;; state) FBASE=/opt/var/lib/vward ;; logs) FBASE=/opt/var/log/vward ;; share) FBASE=/opt/share/vward ;;
    *) fdie invalid_root ;;
  esac
  FBASE="${VWARD_ROOT_PREFIX:-}$FBASE"
  [ "${#FPATH}" -le 300 ] || fdie invalid_path
  case "/$FPATH/" in */../*|*/./*|//*) [ -z "$FPATH" ] || fdie invalid_path ;; esac
  printf '%s' "$FPATH" | grep -q '[^A-Za-z0-9._@+/-]' && fdie invalid_path
  FPATH="${FPATH%/}"
  FFULL="$FBASE${FPATH:+/$FPATH}"
  [ -d "$FBASE" ] || fdie folder_missing
  # A closed path: secrets by place or name.
  file_closed() {
    case "/$1" in
      /tunnels|/tunnels/*|*/https/ca|*/https/ca/*) return 0 ;;
      *.key|*.auth|*private*|*secret*|*password*|*token*|*session*) return 0 ;;
    esac
    return 1
  }
  # Every part of the path must be a real folder or file, not a link.
  FCHK="$FBASE"; FREST="$FPATH"
  while [ -n "$FREST" ]; do
    FPART="${FREST%%/*}"; FCHK="$FCHK/$FPART"
    [ "$FREST" = "$FPART" ] && FREST="" || FREST="${FREST#*/}"
    [ ! -L "$FCHK" ] || fdie not_found
  done
  [ -e "$FFULL" ] || fdie not_found
  case "$FOP" in
    list)
      [ -d "$FFULL" ] || fdie not_a_folder
      [ -z "$FPATH" ] || ! file_closed "$FPATH" || fdie file_closed
      header_json
      ls -lnA "$FFULL" 2>/dev/null | awk -v pre="$FPATH" '
        NR == 1 && /^total/ { next }
        {
          mode = $1; size = $5; line = $0
          for (i = 1; i <= 8; i++) sub(/^[^ ]+ +/, "", line)
          t = substr(mode, 1, 1)
          if (t == "l") next
          kind = t == "d" ? "dir" : t == "-" ? "file" : "other"
          # Private: others may not read it.
          priv = substr(mode, 8, 1) != "r" ? 1 : 0
          print kind "\t" size "\t" priv "\t" $6 " " $7 " " $8 "\t" line
          if (++n >= 500) exit
        }' | while IFS='	' read -r FK FS FP FT FN; do
          FREL="${FPATH:+$FPATH/}$FN"; FC=0
          if [ "$FP" = 1 ] && [ "$FK" = file ]; then FC=1; fi
          file_closed "$FREL" && FC=1
          printf '%s\t%s\t%s\t%s\t%s\n' "$FK" "$FS" "$FC" "$FT" "$FN"
        done | "$JQ" -Rn --arg root "$FROOT" --arg path "$FPATH" '[inputs | split("\t") | {kind: .[0], size: (.[1] | tonumber? // null), closed: (.[2] == "1"), time: .[3], name: .[4]}]
          | {ok: true, root: $root, path: $path, entries: (sort_by(.kind != "dir", .name))}'
      exit 0 ;;
    read|download)
      [ -f "$FFULL" ] || fdie not_a_file
      file_closed "$FPATH" && fdie file_closed
      [ "$(ls -ln "$FFULL" 2>/dev/null | cut -c8)" = r ] || fdie file_closed
      FSIZE="$(wc -c < "$FFULL" | tr -d ' ')"
      if [ "$FOP" = download ]; then
        FNAME="$(basename "$FFULL")"
        echo 'Content-Type: application/octet-stream'
        echo "Content-Disposition: attachment; filename=\"$FNAME\""
        echo 'Cache-Control: no-store'
        echo 'X-Content-Type-Options: nosniff'
        echo "Content-Length: $FSIZE"
        echo
        cat "$FFULL"
        exit 0
      fi
      FLIM=65536
      # Logs are read from the end: the newest lines matter.
      if [ "$FROOT" = logs ] && [ "$FSIZE" -gt "$FLIM" ]; then FCUT=tail; else FCUT=head; fi
      FBIN="$($FCUT -c 4096 "$FFULL" | tr -d '\000' | wc -c | tr -d ' ')"
      FHEAD="$($FCUT -c 4096 "$FFULL" | wc -c | tr -d ' ')"
      header_json
      if [ "$FBIN" != "$FHEAD" ] || case "$FFULL" in *.gz|*.tar|*.tgz|*.bin) true ;; *) false ;; esac; then
        "$JQ" -n --argjson size "$FSIZE" --arg path "$FPATH" '{ok: true, path: $path, size: $size, binary: true}'
      else
        $FCUT -c "$FLIM" "$FFULL" | "$JQ" -Rs --argjson size "$FSIZE" --argjson lim "$FLIM" --arg path "$FPATH" --arg cut "$FCUT" \
          '{ok: true, path: $path, size: $size, binary: false, truncated: ($size > $lim), from_end: ($cut == "tail" and $size > $lim), text: .}'
      fi
      exit 0 ;;
    *) fdie invalid_operation ;;
  esac
fi
if [ "$ACTION" = backup-control ]; then
  header_json; [ "${REQUEST_METHOD:-GET}" = POST ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }
  ! updater_mutation_busy || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }
  [ -x "$CONFIG_HELPER" ] || { echo '{"ok":false,"error":"action_unavailable"}'; exit 0; }
  LEN=${CONTENT_LENGTH:-0}; case "$LEN" in ''|*[!0-9]*) LEN=0;; esac; [ "$LEN" -gt 0 ] && [ "$LEN" -le 512 ] || { echo '{"ok":false,"error":"invalid_body"}'; exit 0; }
  BODY=$(dd bs=1 count="$LEN" 2>/dev/null)
  val(){ printf '%s\n' "$BODY" | tr '&' '\n' | awk -F= -v k="$1" '$1==k{print substr($0,index($0,"=")+1);exit}'; }
  case "$(val op)" in
    create) set -- backup-create manual ;;
    restore) [ "$(val confirm)" = BACKUP_RESTORE ] || { echo '{"ok":false,"error":"confirmation_required"}'; exit 0; }
      BN="$(val name)"; printf '%s\n' "$BN" | grep -Eq '^vward-[0-9]{8}-[0-9]{6}(-[a-z]+)?\.tar\.gz$' || { echo '{"ok":false,"error":"invalid_backup"}'; exit 0; }
      set -- backup-restore "$BN" ;;
    *) echo '{"ok":false,"error":"invalid_operation"}'; exit 0 ;;
  esac
  BOUT="$("$CONFIG_HELPER" "$@" 2>/dev/null)"; BLAST="$(printf '%s\n' "$BOUT" | tail -n 1)"
  case "$BLAST" in
    result=changed|result=unchanged) "$JQ" -cn --arg n "$(printf '%s\n' "$BOUT" | sed -n 's/^info\.name=//p')" '{ok: true, name: $n}' ;;
    error=*) E="${BLAST#error=}"; case "$E" in *[!a-z0-9_]*) E=helper_failed;; esac; printf '{"ok":false,"error":"%s"}\n' "$E" ;;
    *) echo '{"ok":false,"error":"helper_failed"}' ;;
  esac
  exit 0
fi

# agh-auth: connect VWARD to AdGuard Home's API.  The login is checked against
# AdGuard Home itself before it is kept; the password never reaches argv or a log.
if [ "$ACTION" = agh-auth ]; then
  header_json; [ "${REQUEST_METHOD:-GET}" = POST ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }
  ! updater_mutation_busy || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }
  console_mutation_enter || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }; trap console_mutation_leave EXIT
  LEN=${CONTENT_LENGTH:-0}; case "$LEN" in ''|*[!0-9]*) LEN=0;; esac; [ "$LEN" -gt 0 ] && [ "$LEN" -le 1024 ] || { echo '{"ok":false,"error":"invalid_body"}'; exit 0; }
  BODY=$(dd bs=1 count="$LEN" 2>/dev/null)
  val(){ printf '%s\n' "$BODY" | tr '&' '\n' | awk -F= -v k="$1" '$1==k{print substr($0,index($0,"=")+1);exit}'; }
  AGH_AUTH=${VWARD_ADS_AGH_AUTH_FILE:-/opt/etc/vward/ads-privacy-guard/agh-api.auth}
  AGH_BASE="http://${VWARD_ADGUARD_ADDRESS:-127.0.0.1}:${VWARD_ADGUARD_PORT:-3000}/control"
  case "$(val op)" in
    connect)
      ALOGIN="$(val login)"
      printf '%s\n' "$ALOGIN" | grep -Eq '^[A-Za-z0-9._@-]{1,64}$' || { echo '{"ok":false,"error":"invalid_login"}'; exit 0; }
      # Decoded password, printable ASCII only; kept in a variable, never in argv.
      APASS="$(printf '%s\n' "$BODY" | tr '&' '\n' | LC_ALL=C awk -F= '
        BEGIN {h = "0123456789abcdef"}
        $1 == "password" {
          v = substr($0, index($0, "=") + 1); gsub(/\+/, " ", v); o = ""
          while (match(tolower(v), /%[0-9a-f][0-9a-f]/)) {
            c = (index(h, tolower(substr(v, RSTART + 1, 1))) - 1) * 16 + index(h, tolower(substr(v, RSTART + 2, 1))) - 1
            if (c < 32 || c > 126) exit 1
            o = o substr(v, 1, RSTART - 1) sprintf("%c", c); v = substr(v, RSTART + 3)
          }
          printf "%s", o v; exit
        }')" || { echo '{"ok":false,"error":"invalid_password"}'; exit 0; }
      [ -n "$APASS" ] && [ "${#APASS}" -le 128 ] || { echo '{"ok":false,"error":"invalid_password"}'; exit 0; }
      # curl reads the credentials from a config on stdin: "user" with \ and " escaped.
      AESC="$(printf '%s:%s' "$ALOGIN" "$APASS" | awk 'BEGIN {b = sprintf("%c", 92); q = sprintf("%c", 34)}
        {for (i = 1; i <= length($0); i++) {c = substr($0, i, 1); printf "%s", ((c == b || c == q) ? b : "") c}}')"
      ACODE="$(printf 'user = "%s"\n' "$AESC" | "$CURL" -K - -s -o /dev/null -w '%{http_code}' --connect-timeout 3 --max-time 6 "$AGH_BASE/status" 2>/dev/null)"
      case "$ACODE" in
        200) ;;
        401|403) echo '{"ok":false,"error":"wrong_credentials"}'; exit 0 ;;
        *) echo '{"ok":false,"error":"adguard_unavailable"}'; exit 0 ;;
      esac
      umask 077; mkdir -p "$(dirname "$AGH_AUTH")" || { echo '{"ok":false,"error":"write_failed"}'; exit 0; }
      ATMP="$(mktemp "$AGH_AUTH.XXXXXX" 2>/dev/null)" || { echo '{"ok":false,"error":"write_failed"}'; exit 0; }
      printf '%s:%s\n' "$ALOGIN" "$APASS" > "$ATMP" && chmod 0600 "$ATMP" && mv -f "$ATMP" "$AGH_AUTH" || { rm -f "$ATMP"; echo '{"ok":false,"error":"write_failed"}'; exit 0; }
      printf '%s|CONSOLE_ACTION|action=agh-connect login=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$ALOGIN" >> /opt/var/log/vward/console-audit.log 2>/dev/null
      echo '{"ok":true,"connected":true}' ;;
    disconnect)
      [ "$(val confirm)" = AGH_DISCONNECT ] || { echo '{"ok":false,"error":"confirmation_required"}'; exit 0; }
      rm -f "$AGH_AUTH" || { echo '{"ok":false,"error":"write_failed"}'; exit 0; }
      printf '%s|CONSOLE_ACTION|action=agh-disconnect\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" >> /opt/var/log/vward/console-audit.log 2>/dev/null
      echo '{"ok":true,"connected":false}' ;;
    *) echo '{"ok":false,"error":"invalid_operation"}' ;;
  esac
  exit 0
fi

if [ "$ACTION" = ads-settings ]; then
  header_json; [ "${REQUEST_METHOD:-GET}" = POST ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }; ! updater_mutation_busy || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }; console_mutation_enter || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }; trap console_mutation_leave EXIT
  LEN=${CONTENT_LENGTH:-0}; case "$LEN" in ''|*[!0-9]*) LEN=0;; esac; [ "$LEN" -gt 0 ]&&[ "$LEN" -le 3072 ] || { echo '{"ok":false,"error":"invalid_body"}'; exit 0; }; BODY=$(dd bs=1 count="$LEN" 2>/dev/null)
  val(){ printf '%s\n' "$BODY"|tr '&' '\n'|awk -F= -v k="$1" '$1==k{print substr($0,index($0,"=")+1);exit}'; }
  UNKNOWN="$(printf '%s\n' "$BODY"|tr '&' '\n'|cut -d= -f1|awk '$0!="ENABLED"&&$0!="RUN_MODE"&&$0!="SCHEDULE_INTERVAL_MIN"&&$0!="DYNAMIC_MIN_INTERVAL_SEC"&&$0!="DYNAMIC_MAX_LOAD_PER_CPU_X100"&&$0!="DYNAMIC_MIN_MEM_AVAILABLE_KB"&&$0!="DYNAMIC_MIN_OPT_FREE_KB"&&$0!="DYNAMIC_MAX_CANDIDATES_PER_RUN"&&$0!="AUTO_SOURCE_UPDATE"&&$0!="SOURCE_UPDATE_INTERVAL_HOURS"&&$0!="QUERY_SOURCE"&&$0!="AUTO_RULE_SCOPE"&&$0!="PUBLISH_MODE"&&$0!="AUTO_PUBLISH"&&$0!="confirm"{print;exit}')"; [ -z "$UNKNOWN" ] || { echo '{"ok":false,"error":"unknown_parameter"}'; exit 0; }
  set -- set; for K in ENABLED RUN_MODE SCHEDULE_INTERVAL_MIN DYNAMIC_MIN_INTERVAL_SEC DYNAMIC_MAX_LOAD_PER_CPU_X100 DYNAMIC_MIN_MEM_AVAILABLE_KB DYNAMIC_MIN_OPT_FREE_KB DYNAMIC_MAX_CANDIDATES_PER_RUN AUTO_SOURCE_UPDATE SOURCE_UPDATE_INTERVAL_HOURS QUERY_SOURCE AUTO_RULE_SCOPE PUBLISH_MODE AUTO_PUBLISH; do V="$(val "$K")"; [ -n "$V" ]&&set -- "$@" "$K" "$V"; done
  [ "$(val AUTO_PUBLISH)" != 1 ] || [ "$(val confirm)" = ADS_AUTO_PUBLISH ] || { echo '{"ok":false,"error":"confirmation_required"}'; exit 0; }
  SETTINGSCTL=/opt/bin/vward-ads-privacy-settings.sh; [ -x "$SETTINGSCTL" ] || { echo '{"ok":false,"error":"settings_backend_missing"}'; exit 0; }
  OUT="$(ads_console_tmp ads-settings)" || { echo '{"ok":false,"error":"temporary_file_failed"}'; exit 0; }; "$SETTINGSCTL" "$@" >"$OUT" 2>&1; RC=$?; RES="$(head -c 12000 "$OUT")"; rm -f "$OUT"; "$JQ" -n --argjson ok "$([ "$RC" -eq 0 ]&&echo true||echo false)" --argjson rc "$RC" --arg output "$RES" '{ok:$ok,rc:$rc,output:$output}'; exit 0
fi

if [ "$ACTION" = ads-control ]; then
  header_json; [ "${REQUEST_METHOD:-GET}" = POST ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }; ! updater_mutation_busy || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }; console_mutation_enter || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }; trap console_mutation_leave EXIT
  ! component_disabled ads-privacy-guard || { echo '{"ok":false,"error":"component_disabled"}'; exit 0; }
  LEN=${CONTENT_LENGTH:-0}; case "$LEN" in ''|*[!0-9]*) LEN=0;; esac; [ "$LEN" -gt 0 ]&&[ "$LEN" -le 1024 ] || { echo '{"ok":false,"error":"invalid_body"}'; exit 0; }; BODY=$(dd bs=1 count="$LEN" 2>/dev/null)
  val(){ printf '%s\n' "$BODY"|tr '&' '\n'|awk -F= -v k="$1" '$1==k{print substr($0,index($0,"=")+1);exit}'; }
  OP="$(val op)"; DOMAIN="$(val domain|tr '[:upper:]' '[:lower:]')"; SCOPE="$(val scope)"; [ -n "$SCOPE" ]||SCOPE=exact
  case "$OP" in pause|resume|allow|block|remove-override|source-mode|source-add|source-delete|source-category|enqueue|agh) ;; *) echo '{"ok":false,"error":"invalid_operation"}'; exit 0;; esac
  case "$OP" in
    allow|block|remove-override) ads_valid_domain "$DOMAIN" || { echo '{"ok":false,"error":"invalid_domain"}'; exit 0; }; case "$SCOPE" in exact|suffix) ;; *) echo '{"ok":false,"error":"invalid_scope"}'; exit 0 ;; esac ;;
    source-mode) SID="$(val source)"; MODE="$(val mode)"; ads_valid_source_id "$SID" || { echo '{"ok":false,"error":"invalid_source"}'; exit 0; }; case "$MODE" in off|check|active) ;; *) echo '{"ok":false,"error":"invalid_source_mode"}'; exit 0 ;; esac ;;
    source-add) SURL="$(form_url_decode "$(val url)")" || { echo '{"ok":false,"error":"invalid_url"}'; exit 0; }; SFMT="$(val format)"
      printf '%s\n' "$SURL" | grep -Eq '^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?/[A-Za-z0-9._~/%+=&?-]*$' && [ "${#SURL}" -le 300 ] || { echo '{"ok":false,"error":"invalid_url"}'; exit 0; }
      case "$SFMT" in adblock|hosts|domains) ;; *) echo '{"ok":false,"error":"invalid_format"}'; exit 0 ;; esac ;;
    source-delete) SID="$(val source)"; case "$SID" in custom-*) ads_valid_source_id "$SID" || { echo '{"ok":false,"error":"invalid_source"}'; exit 0; } ;; *) echo '{"ok":false,"error":"invalid_source"}'; exit 0 ;; esac ;;
    source-category) SPUR="$(val category)"; SST="$(val state)"; case "$SPUR" in ''|*[!a-z-]*) echo '{"ok":false,"error":"invalid_category"}'; exit 0 ;; esac; case "$SST" in on|off) ;; *) echo '{"ok":false,"error":"invalid_value"}'; exit 0 ;; esac ;;
    agh) AGS="$(val setting)"; AGV="$(val value)"
      case "$AGS" in
        protection|filtering|safebrowsing|parental|safesearch) case "$AGV" in 0|1) ;; *) echo '{"ok":false,"error":"invalid_value"}'; exit 0 ;; esac
          [ "$AGS:$AGV" != protection:0 ] || [ "$(val confirm)" = AGH_PROTECTION_OFF ] || { echo '{"ok":false,"error":"confirmation_required"}'; exit 0; }
          set -- "$AGS" "$AGV" ;;
        interval) case "$AGV" in 0|1|12|24|72|168) ;; *) echo '{"ok":false,"error":"invalid_value"}'; exit 0 ;; esac; set -- interval "$AGV" ;;
        filters-refresh) set -- filters-refresh ;;
        filter-enable|filter-add|filter-remove)
          AGU="$(form_url_decode "$(val url)")" || { echo '{"ok":false,"error":"invalid_url"}'; exit 0; }
          printf '%s\n' "$AGU" | grep -Eq '^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?/[A-Za-z0-9._~/%+=&?-]*$' && [ "${#AGU}" -le 300 ] || { echo '{"ok":false,"error":"invalid_url"}'; exit 0; }
          case "$AGS" in
            filter-enable) case "$AGV" in 0|1) ;; *) echo '{"ok":false,"error":"invalid_value"}'; exit 0 ;; esac; set -- filter-enable "$AGU" "$AGV" ;;
            filter-add) AGN="$(val name | sed 's/+/ /g; s/%20/ /g')"
              case "$AGN" in ''|*[!A-Za-z0-9\ ._-]*) echo '{"ok":false,"error":"invalid_name"}'; exit 0 ;; esac
              set -- filter-add "$AGU" "$AGN" ;;
            filter-remove) [ "$(val confirm)" = AGH_FILTER_REMOVE ] || { echo '{"ok":false,"error":"confirmation_required"}'; exit 0; }; set -- filter-remove "$AGU" ;;
          esac ;;
        service) AGI="$(val service)"; case "$AGI" in ''|*[!a-z0-9_]*) echo '{"ok":false,"error":"invalid_service"}'; exit 0 ;; esac
          case "$AGV" in 0|1) ;; *) echo '{"ok":false,"error":"invalid_value"}'; exit 0 ;; esac; set -- service "$AGI" "$AGV" ;;
        *) echo '{"ok":false,"error":"invalid_setting"}'; exit 0 ;;
      esac ;;
    enqueue) JOB="$(val job)"; case "$JOB" in scan|sources-update|rules-rebuild) ;; publish) [ "$(val confirm)" = ADS_PUBLISH ] || { echo '{"ok":false,"error":"confirmation_required"}'; exit 0; } ;; probe) ads_valid_domain "$DOMAIN" || { echo '{"ok":false,"error":"invalid_domain"}'; exit 0; } ;; *) echo '{"ok":false,"error":"invalid_job"}'; exit 0 ;; esac ;;
  esac
  RC=0; OUT="$(ads_console_tmp ads-control)" || { echo '{"ok":false,"error":"temporary_file_failed"}'; exit 0; }
  case "$OP" in
    pause|resume) /opt/bin/vward-ads-privacy-control.sh "$OP" >"$OUT" 2>&1||RC=$? ;;
    allow|block|remove-override) C="$OP"; [ "$OP" = remove-override ]&&C=remove; /opt/bin/vward-ads-privacy-control.sh "$C" "$DOMAIN" "$SCOPE" >"$OUT" 2>&1||RC=$? ;;
    source-mode) /opt/bin/vward-ads-privacy-source-control.sh set "$SID" "$MODE" >"$OUT" 2>&1||RC=$? ;;
    source-add) /opt/bin/vward-ads-privacy-source-control.sh add "$SURL" "$SFMT" >"$OUT" 2>&1||RC=$? ;;
    source-delete) /opt/bin/vward-ads-privacy-source-control.sh delete "$SID" >"$OUT" 2>&1||RC=$? ;;
    source-category) /opt/bin/vward-ads-privacy-source-control.sh category "$SPUR" "$SST" >"$OUT" 2>&1||RC=$? ;;
    enqueue) /opt/bin/vward-ads-privacy-job.sh enqueue "$JOB" "$DOMAIN" >"$OUT" 2>&1||RC=$? ;;
    agh) "${VWARD_ADS_CONTROL_BIN:-/opt/bin/vward-ads-privacy-control.sh}" agh "$@" >"$OUT" 2>&1||RC=$? ;;
  esac
  RES="$(head -c 12000 "$OUT" 2>/dev/null)"; rm -f "$OUT"; printf '%s|ADS_CONTROL|op=%s rc=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$OP" "$RC" >>/opt/var/log/vward/console-audit.log; "$JQ" -n --argjson ok "$([ "$RC" -eq 0 ]&&echo true||echo false)" --argjson rc "$RC" --arg result "$RES" '{ok:$ok,rc:$rc,result:$result}'; exit 0
fi

if [ "$ACTION" = "settings-data" ]; then
    header_json
    [ "${REQUEST_METHOD:-GET}" = GET ] || {
        echo '{"ok":false,"error":"method_not_allowed"}'
        exit 0
    }
    SETTINGS_REGISTRY=${VWARD_SETTINGS_REGISTRY:-/opt/share/vward/settings-registry.json}
    UPDATE_CONFIG=${VWARD_UPDATE_CONFIG:-/opt/etc/vward/update.conf}
    ADS_CONFIG=${VWARD_ADS_CONFIG:-/opt/etc/vward/ads-privacy-guard/ads-privacy-guard.conf}
    [ -r "$SETTINGS_REGISTRY" ] || {
        echo '{"ok":false,"error":"settings_registry_unavailable"}'
        exit 0
    }
    setting_value()
    {
        [ -r "$UPDATE_CONFIG" ] || return 0
        awk -F= -v key="$1" '$1==key {print substr($0,index($0,"=")+1); exit}' "$UPDATE_CONFIG"
    }
    ads_setting_value()
    {
        [ -r "$ADS_CONFIG" ] || return 0
        awk -F= -v key="$1" '$1==key {print substr($0,index($0,"=")+1); exit}' "$ADS_CONFIG"
    }
    SETTINGS_AUTO_APPLY=$(setting_value auto_apply)
    SETTINGS_AUTO_CRITICAL=$(setting_value auto_critical)
    SETTINGS_AUTO_IMPORTANT=$(setting_value auto_important)
    SETTINGS_AUTO_ROUTINE=$(setting_value auto_routine)
    SETTINGS_UPDATE_ENABLED=$(setting_value update_enabled)
    SETTINGS_CHANNEL=$(setting_value channel)
    SETTINGS_CHECK_INTERVAL=$(setting_value check_interval_seconds)
    SETTINGS_SAFE_WINDOW_START=$(setting_value safe_window_start)
    SETTINGS_SAFE_WINDOW_END=$(setting_value safe_window_end)
    SETTINGS_IMPORTANT_DELAY=$(setting_value important_max_delay_seconds)
    SETTINGS_ROUTINE_DELAY=$(setting_value routine_max_delay_seconds)
    SETTINGS_MINIMUM_FREE=$(setting_value minimum_free_kb)
    SETTINGS_MAX_MANIFEST=$(setting_value max_manifest_size)
    SETTINGS_MAX_PACKAGE=$(setting_value max_package_size)
    SETTINGS_MAX_UNPACKED=$(setting_value max_unpacked_size)
    SETTINGS_BACKUP_KEEP=$(setting_value backup_keep)
    SETTINGS_HEALTH_TIMEOUT=$(setting_value health_timeout_seconds)
    SETTINGS_REQUEST_TIMEOUT=$(setting_value request_timeout_seconds)
    SETTINGS_BARRIER_READY=$(setting_value barrier_integration_ready)
    SETTINGS_ADS_ENABLED=$(ads_setting_value ENABLED)
    SETTINGS_ADS_RUN_MODE=$(ads_setting_value RUN_MODE)
    SETTINGS_ADS_SCHEDULE_INTERVAL=$(ads_setting_value SCHEDULE_INTERVAL_MIN)
    SETTINGS_ADS_DYNAMIC_INTERVAL=$(ads_setting_value DYNAMIC_MIN_INTERVAL_SEC)
    SETTINGS_ADS_DYNAMIC_LOAD=$(ads_setting_value DYNAMIC_MAX_LOAD_PER_CPU_X100)
    SETTINGS_ADS_DYNAMIC_MEM=$(ads_setting_value DYNAMIC_MIN_MEM_AVAILABLE_KB)
    SETTINGS_ADS_DYNAMIC_OPT=$(ads_setting_value DYNAMIC_MIN_OPT_FREE_KB)
    SETTINGS_ADS_DYNAMIC_CANDIDATES=$(ads_setting_value DYNAMIC_MAX_CANDIDATES_PER_RUN)
    SETTINGS_ADS_AUTO_SOURCES=$(ads_setting_value AUTO_SOURCE_UPDATE)
    SETTINGS_ADS_SOURCE_INTERVAL=$(ads_setting_value SOURCE_UPDATE_INTERVAL_HOURS)
    SETTINGS_ADS_QUERY_SOURCE=$(ads_setting_value QUERY_SOURCE)
    SETTINGS_ADS_RULE_SCOPE=$(ads_setting_value AUTO_RULE_SCOPE)
    SETTINGS_ADS_PUBLISH_MODE=$(ads_setting_value PUBLISH_MODE)
    SETTINGS_ADS_AUTO_PUBLISH=$(ads_setting_value AUTO_PUBLISH)
    "$JQ" -c \
      --argjson profile_ready "$PROFILE_READY" \
      --arg lan_address "${VWARD_LAN_ADDRESS:-}" \
      --arg lan_subnet "${VWARD_LAN_SUBNET:-}" \
      --arg dns_server "${VWARD_DNS_SERVER:-}" \
      --arg probe_dns "${VWARD_PROBE_DNS:-}" \
      --arg adguard_address "${VWARD_ADGUARD_ADDRESS:-}" \
      --arg adguard_port "${VWARD_ADGUARD_PORT:-}" \
      --arg wan_device "${VWARD_WAN_DEVICE:-}" \
      --arg wan_interface "${VWARD_WAN_INTERFACE:-}" \
      --arg lan_interface "${VWARD_LAN_INTERFACE:-}" \
      --arg tunnel_device "${VWARD_TUNNEL_DEVICE:-}" \
      --arg tunnel_interface "${VWARD_TUNNEL_INTERFACE:-}" \
      --arg policy_group "${VWARD_POLICY_GROUP:-}" \
      --arg console_port "${VWARD_CONSOLE_PORT:-}" \
      --arg rci_base "${VWARD_RCI_BASE:-}" \
      --arg auto_apply "$SETTINGS_AUTO_APPLY" \
      --arg auto_critical "$SETTINGS_AUTO_CRITICAL" \
      --arg auto_important "$SETTINGS_AUTO_IMPORTANT" \
      --arg auto_routine "$SETTINGS_AUTO_ROUTINE" \
      --arg update_enabled "$SETTINGS_UPDATE_ENABLED" \
      --arg channel "$SETTINGS_CHANNEL" \
      --arg check_interval_seconds "$SETTINGS_CHECK_INTERVAL" \
      --arg safe_window_start "$SETTINGS_SAFE_WINDOW_START" \
      --arg safe_window_end "$SETTINGS_SAFE_WINDOW_END" \
      --arg important_max_delay_seconds "$SETTINGS_IMPORTANT_DELAY" \
      --arg routine_max_delay_seconds "$SETTINGS_ROUTINE_DELAY" \
      --arg minimum_free_kb "$SETTINGS_MINIMUM_FREE" \
      --arg max_manifest_size "$SETTINGS_MAX_MANIFEST" \
      --arg max_package_size "$SETTINGS_MAX_PACKAGE" \
      --arg max_unpacked_size "$SETTINGS_MAX_UNPACKED" \
      --arg backup_keep "$SETTINGS_BACKUP_KEEP" \
      --arg health_timeout_seconds "$SETTINGS_HEALTH_TIMEOUT" \
      --arg request_timeout_seconds "$SETTINGS_REQUEST_TIMEOUT" \
      --arg barrier_integration_ready "$SETTINGS_BARRIER_READY" \
      --arg ads_enabled "$SETTINGS_ADS_ENABLED" \
      --arg ads_run_mode "$SETTINGS_ADS_RUN_MODE" \
      --arg ads_schedule_interval "$SETTINGS_ADS_SCHEDULE_INTERVAL" \
      --arg ads_dynamic_interval "$SETTINGS_ADS_DYNAMIC_INTERVAL" \
      --arg ads_dynamic_load "$SETTINGS_ADS_DYNAMIC_LOAD" \
      --arg ads_dynamic_mem "$SETTINGS_ADS_DYNAMIC_MEM" \
      --arg ads_dynamic_opt "$SETTINGS_ADS_DYNAMIC_OPT" \
      --arg ads_dynamic_candidates "$SETTINGS_ADS_DYNAMIC_CANDIDATES" \
      --arg ads_auto_sources "$SETTINGS_ADS_AUTO_SOURCES" \
      --arg ads_source_interval "$SETTINGS_ADS_SOURCE_INTERVAL" \
      --arg ads_query_source "$SETTINGS_ADS_QUERY_SOURCE" \
      --arg ads_rule_scope "$SETTINGS_ADS_RULE_SCOPE" \
      --arg ads_publish_mode "$SETTINGS_ADS_PUBLISH_MODE" \
      --arg ads_auto_publish "$SETTINGS_ADS_AUTO_PUBLISH" '
        def raw_value:
          if .key=="VWARD_LAN_ADDRESS" then $lan_address
          elif .key=="VWARD_LAN_SUBNET" then $lan_subnet
          elif .key=="VWARD_DNS_SERVER" then $dns_server
          elif .key=="VWARD_PROBE_DNS" then $probe_dns
          elif .key=="VWARD_ADGUARD_ADDRESS" then $adguard_address
          elif .key=="VWARD_ADGUARD_PORT" then $adguard_port
          elif .key=="VWARD_WAN_DEVICE" then $wan_device
          elif .key=="VWARD_WAN_INTERFACE" then $wan_interface
          elif .key=="VWARD_LAN_INTERFACE" then $lan_interface
          elif .key=="VWARD_TUNNEL_DEVICE" then $tunnel_device
          elif .key=="VWARD_TUNNEL_INTERFACE" then $tunnel_interface
          elif .key=="VWARD_POLICY_GROUP" then $policy_group
          elif .key=="VWARD_CONSOLE_PORT" then $console_port
          elif .key=="VWARD_RCI_BASE" then $rci_base
          elif .key=="auto_apply" then $auto_apply
          elif .key=="auto_critical" then $auto_critical
          elif .key=="auto_important" then $auto_important
          elif .key=="auto_routine" then $auto_routine
          elif .key=="update_enabled" then $update_enabled
          elif .key=="channel" then $channel
          elif .key=="check_interval_seconds" then $check_interval_seconds
          elif .key=="safe_window_start" then $safe_window_start
          elif .key=="safe_window_end" then $safe_window_end
          elif .key=="important_max_delay_seconds" then $important_max_delay_seconds
          elif .key=="routine_max_delay_seconds" then $routine_max_delay_seconds
          elif .key=="minimum_free_kb" then $minimum_free_kb
          elif .key=="max_manifest_size" then $max_manifest_size
          elif .key=="max_package_size" then $max_package_size
          elif .key=="max_unpacked_size" then $max_unpacked_size
          elif .key=="backup_keep" then $backup_keep
          elif .key=="health_timeout_seconds" then $health_timeout_seconds
          elif .key=="request_timeout_seconds" then $request_timeout_seconds
          elif .key=="barrier_integration_ready" then $barrier_integration_ready
          elif .key=="ENABLED" then $ads_enabled
          elif .key=="RUN_MODE" then $ads_run_mode
          elif .key=="SCHEDULE_INTERVAL_MIN" then $ads_schedule_interval
          elif .key=="DYNAMIC_MIN_INTERVAL_SEC" then $ads_dynamic_interval
          elif .key=="DYNAMIC_MAX_LOAD_PER_CPU_X100" then $ads_dynamic_load
          elif .key=="DYNAMIC_MIN_MEM_AVAILABLE_KB" then $ads_dynamic_mem
          elif .key=="DYNAMIC_MIN_OPT_FREE_KB" then $ads_dynamic_opt
          elif .key=="DYNAMIC_MAX_CANDIDATES_PER_RUN" then $ads_dynamic_candidates
          elif .key=="AUTO_SOURCE_UPDATE" then $ads_auto_sources
          elif .key=="SOURCE_UPDATE_INTERVAL_HOURS" then $ads_source_interval
          elif .key=="QUERY_SOURCE" then $ads_query_source
          elif .key=="AUTO_RULE_SCOPE" then $ads_rule_scope
          elif .key=="PUBLISH_MODE" then $ads_publish_mode
          elif .key=="AUTO_PUBLISH" then $ads_auto_publish
          else "" end;
        def typed($v): if .type=="boolean" then ($v=="1") elif .type=="integer" and ($v | length > 0 and all(explode[]; . >= 48 and . <= 57)) then ($v|tonumber) else $v end;
        {ok:true,schema:.schema,profile_ready:$profile_ready,authentication_required_for_device_write:true,
         settings:[.settings[] | select(.secret==false) | . as $item | (raw_value) as $raw |
           . + {current:typed($raw),effective:typed($raw),discovered:null,
                validation:(if $raw=="" then "unknown" elif .source=="device.conf" and ($profile_ready|not) then "unverified" else "valid" end)}]}
      ' "$SETTINGS_REGISTRY" 2>/dev/null || echo '{"ok":false,"error":"settings_registry_invalid"}'
    exit 0
fi

if [ "$ACTION" = "security-data" ]; then
    header_json
    [ "${REQUEST_METHOD:-GET}" = GET ] || {
        echo '{"ok":false,"error":"method_not_allowed"}'
        exit 0
    }
    CONSOLE_RUNTIME_CONFIG=${VWARD_CONSOLE_RUNTIME_CONFIG:-/opt/var/run/vward/console-lighttpd.conf}
    LISTENER_ADDRESS=
    LISTENER_PORT=
    LISTENER_SCOPE=unknown
    LISTENER_WILDCARD=null
    SOCKET_STATE=unknown
    CONFIG_TEST=unknown
    MOD_SETENV=unknown

    if [ -r "$CONSOLE_RUNTIME_CONFIG" ]; then
        LISTENER_ADDRESS=$(awk -F'"' '/^[[:space:]]*server\.bind[[:space:]]*=/{print $2; exit}' "$CONSOLE_RUNTIME_CONFIG")
        LISTENER_PORT=$(awk -F= '/^[[:space:]]*server\.port[[:space:]]*=/{gsub(/[[:space:]]/,"",$2); print $2; exit}' "$CONSOLE_RUNTIME_CONFIG")
        case "$LISTENER_ADDRESS" in
            0.0.0.0|::|'') LISTENER_SCOPE=all; LISTENER_WILDCARD=true ;;
            "$VWARD_LAN_ADDRESS") LISTENER_SCOPE=lan; LISTENER_WILDCARD=false ;;
            *) LISTENER_SCOPE=custom; LISTENER_WILDCARD=false ;;
        esac
        grep -q '"mod_setenv"' "$CONSOLE_RUNTIME_CONFIG" && MOD_SETENV=enabled || MOD_SETENV=disabled
        if [ -x /opt/sbin/lighttpd ]; then
            /opt/sbin/lighttpd -tt -f "$CONSOLE_RUNTIME_CONFIG" >/dev/null 2>&1 && CONFIG_TEST=pass || CONFIG_TEST=fail
        fi
    fi

    if [ -n "$LISTENER_PORT" ]; then
        if command -v ss >/dev/null 2>&1; then
            ss -ltn 2>/dev/null | awk -v p=":$LISTENER_PORT" 'NR>1 && index($4,p)==length($4)-length(p)+1{found=1} END{exit !found}' && SOCKET_STATE=listening || SOCKET_STATE=not_listening
        elif command -v netstat >/dev/null 2>&1; then
            netstat -ltn 2>/dev/null | awk -v p=":$LISTENER_PORT" 'NR>2 && index($4,p)==length($4)-length(p)+1{found=1} END{exit !found}' && SOCKET_STATE=listening || SOCKET_STATE=not_listening
        fi
    fi

    "$JQ" -n \
      --argjson ready "$PROFILE_READY" \
      --arg lan_address "${VWARD_LAN_ADDRESS:-}" \
      --arg lan_subnet "${VWARD_LAN_SUBNET:-}" \
      --arg dns_server "${VWARD_DNS_SERVER:-}" \
      --arg wan_device "${VWARD_WAN_DEVICE:-}" \
      --arg wan_interface "${VWARD_WAN_INTERFACE:-}" \
      --arg tunnel_device "${VWARD_TUNNEL_DEVICE:-}" \
      --arg tunnel_interface "${VWARD_TUNNEL_INTERFACE:-}" \
      --arg policy_group "${VWARD_POLICY_GROUP:-}" \
      --arg console_port "${VWARD_CONSOLE_PORT:-}" \
      --arg adguard_address "${VWARD_ADGUARD_ADDRESS:-}" \
      --arg adguard_port "${VWARD_ADGUARD_PORT:-}" \
      --arg listener_address "$LISTENER_ADDRESS" \
      --arg listener_port "$LISTENER_PORT" \
      --arg listener_scope "$LISTENER_SCOPE" \
      --argjson listener_wildcard "$LISTENER_WILDCARD" \
      --arg socket_state "$SOCKET_STATE" \
      --arg config_test "$CONFIG_TEST" \
      --arg mod_setenv "$MOD_SETENV" \
      --argjson authentication "$([ "$AUTH_ENABLED" = 1 ] && echo true || echo false)" \
      '{ok:true,profile_ready:$ready,listener:{scope:$listener_scope,address:$listener_address,port:$listener_port,wildcard:$listener_wildcard,socket_state:$socket_state,source:"generated_config"},profile:{lan_address:$lan_address,lan_subnet:$lan_subnet,dns_server:$dns_server,wan_device:$wan_device,wan_interface:$wan_interface,tunnel_device:$tunnel_device,tunnel_interface:$tunnel_interface,policy_group:$policy_group,console_port:$console_port,adguard_address:$adguard_address,adguard_port:$adguard_port},external_services:{adguard:{address:$adguard_address,port:$adguard_port}},server:{config_test:$config_test,mod_setenv:$mod_setenv},api:{mutation_guard:true,cors:false,directory_listing:false,authentication:$authentication}}'
    exit 0
fi

if [ "$ACTION" = "settings" ]; then
    header_json

    [ "${REQUEST_METHOD:-GET}" = POST ] || {
        echo '{"ok":false,"error":"method_not_allowed"}'
        exit 0
    }
    ! updater_mutation_busy || {
        echo '{"ok":false,"error":"updater_busy"}'
        exit 0
    }
    console_mutation_enter || {
        echo '{"ok":false,"error":"updater_busy"}'
        exit 0
    }
    trap console_mutation_leave EXIT

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

    HINT_CATALOG=/opt/etc/vward/route-engine/hints-catalog.tsv
    ADAPTIVE_PERSIST=/opt/var/lib/vward/route-engine/adaptive-persist.txt
    IP_INDEX=/opt/var/lib/vward/policy-sync/catalog.index
    IP_ACTIVE=/opt/var/lib/vward/policy-sync/active.categories
    IP_OWNED=/opt/var/lib/vward/policy-sync/owned.dynamic.routes
    IP_ITDOG=/opt/var/lib/vward/policy-sync/source-catalog/itdog
    IP_LOYAL=/opt/var/lib/vward/policy-sync/source-catalog/loyalsoldier

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

    IP_INDEX_JSON="$(awk -F'|' 'NF>=2 && $1 ~ /^[a-z0-9][a-z0-9._-]*$/ {print $1 "\t" $2}' "$IP_INDEX" 2>/dev/null | head -n 300 | "$JQ" -Rn '[inputs | split("\t") | {name: .[0], cidr: (.[1] | tonumber? // 0)}]')"
    [ -n "$IP_INDEX_JSON" ] || IP_INDEX_JSON='[]'
    SERVICES_JSON="$(awk -F'|' 'NF>=3 && $1 !~ /^[[:space:]]*#/ && $2 ~ /^[A-Za-z0-9.-]+$/ {print $1 "\t" $2}' /opt/etc/vward/route-engine/services.conf 2>/dev/null | head -n 50 |
        while IFS="$(printf '\t')" read -r SNAME SHOST; do
            SF="$(awk -F= '$1=="FAILS"{print $2}' "/opt/var/lib/vward/route-tools/$SHOST.state" 2>/dev/null)"; SO="$(awk -F= '$1=="OKS"{print $2}' "/opt/var/lib/vward/route-tools/$SHOST.state" 2>/dev/null)"
            printf '%s\t%s\t%s\t%s\n' "$SNAME" "$SHOST" "${SF:-}" "${SO:-}"
        done | "$JQ" -Rn '[inputs | split("\t") | {name: .[0], host: .[1], fails: (.[2] | tonumber? // null), oks: (.[3] | tonumber? // null)}]')"
    [ -n "$SERVICES_JSON" ] || SERVICES_JSON='[]'
    ITDOG_IP_CATEGORIES="$(find "$IP_ITDOG" -type f -name '*.cidr' 2>/dev/null | wc -l)"
    LOYAL_IP_CATEGORIES="$(find "$IP_LOYAL" -type f -name '*.cidr' 2>/dev/null | wc -l)"
    [ -n "$ITDOG_IP_CATEGORIES" ] || ITDOG_IP_CATEGORIES=0
    [ -n "$LOYAL_IP_CATEGORIES" ] || LOYAL_IP_CATEGORIES=0

    HINT_LAST="$(tail -n 1 /opt/var/log/vward-route-hints.log 2>/dev/null)"
    IP_LAST="$(tail -n 1 /opt/var/log/vward-policy-sync-sync.log 2>/dev/null)"

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
      --argjson ip_index "$IP_INDEX_JSON" --argjson services "$SERVICES_JSON" \
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
            index:$ip_index,
            last_sync:$ip_last
        },
        services:$services
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
    ps 2>/dev/null | grep -q '[v]ward-cron-supervisor.sh' && SUPERVISOR_STATUS=PASS
    ps 2>/dev/null | grep -q '[A]dGuardHome' && ADGUARD_STATUS=PASS
    ps 2>/dev/null | grep -q '[v]ward-route-engine.sh' && ADAPTIVE_STATUS=PASS

    UPDATE_STATUS=FAIL
    [ -x /opt/share/vward/updater/current/vward-update.sh ] && UPDATE_STATUS=PASS
    CONFIG_STATUS=FAIL
    [ -r /opt/etc/vward/update.conf ] && CONFIG_STATUS=PASS
    CGI_STATUS=PASS

    WAN_JSON="$(fetch_json "$VWARD_RCI_BASE/show/internet/status")"
    WAN_STATUS="$(printf '%s\n' "$WAN_JSON" | "$JQ" -r 'if (.internet // .connected // false) == true then "PASS" else "WARN" end' 2>/dev/null)"
    case "$WAN_STATUS" in PASS|WARN) ;; *) WAN_STATUS=UNKNOWN ;; esac

    IF_JSON="$(fetch_json "$VWARD_RCI_BASE/show/interface")"
    WG_COUNT="$(printf '%s\n' "$IF_JSON" | "$JQ" -r '[to_entries[] | select((.value | type) == "object" and ((.value.type // "") | tostring | ascii_downcase == "wireguard"))] | length' 2>/dev/null)"
    case "$WG_COUNT" in ''|*[!0-9]*) WG_COUNT=0 ;; esac
    [ "$WG_COUNT" -gt 0 ] && WG_STATUS=PASS || WG_STATUS=WARN

    # Smart DNS: each domain bound to a DNS-over-HTTPS server must resolve to an
    # address that leaves through the provider, never through a tunnel.
    SMARTDNS_STATUS=PASS SMARTDNS_DETAIL="Smart DNS не используется"
    DIAG_RC="$(ndm_cached running 10 "show running-config")"
    # Smart DNS rows in Keenetic and in AdGuard Home ([/domain/]https://...).
    SD_DOMAINS="$({ printf '%s\n' "$DIAG_RC" | awk '
        /^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1)}
        ctx && $1 == "https" && $2 == "upstream" && $(NF-1) == "domain" {print tolower($NF)}'
        command -v vward_agh_smartdns_domains >/dev/null 2>&1 && vward_agh_smartdns_domains; } | sort -u | head -n 16)"
    if [ -n "$SD_DOMAINS" ]; then
        SD_BAD=""; SD_N=0
        for SD in $SD_DOMAINS; do
            case "$SD" in *[!a-z0-9.-]*) continue ;; esac
            SD_IP="$(nslookup "$SD" "${VWARD_DNS_SERVER:-127.0.0.1}" 2>/dev/null | awk '/^Name:/ {n = 1; next} n {for (i = 1; i <= NF; i++) if ($i ~ /^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$/) {print $i; exit}}')"
            [ -n "$SD_IP" ] || continue
            SD_N=$((SD_N + 1))
            SD_DEV="$(ip route get "$SD_IP" 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "dev") {print $(i + 1); exit}}')"
            if [ -n "$SD_DEV" ] && { [ "$SD_DEV" = "${VWARD_TUNNEL_DEVICE:-}" ] || [ -d "/sys/class/net/$SD_DEV/wireguard" ] || [ "$(cat "/sys/class/net/$SD_DEV/type" 2>/dev/null)" = 65534 ]; }; then
                SD_BAD="$SD_BAD $SD($SD_IP→$SD_DEV)"
            fi
        done
        if [ -n "$SD_BAD" ]; then
            SMARTDNS_STATUS=FAIL SMARTDNS_DETAIL="Уходит в туннель:$SD_BAD - Smart DNS не работает для всех своих доменов. Проверьте «Доменные списки»."
        else
            SMARTDNS_DETAIL="Доменов: $(printf '%s\n' "$SD_DOMAINS" | wc -l | tr -d ' '), проверено адресов: $SD_N, все идут через провайдера"
        fi
    fi

    # DNS chain: Keenetic hands queries to AdGuard Home, and AdGuard Home must not
    # hand them back to the router (a loop Keenetic answers by dropping requests).
    DNS_STATUS=PASS DNS_DETAIL=""
    AGH_Y="${VWARD_ADGUARD_CONFIG:-/opt/etc/AdGuardHome/AdGuardHome.yaml}"
    if [ -r "$AGH_Y" ]; then
        AGH_DNS_PORT="$(awk '/^[^ #]/ {d = ($1 == "dns:")} d && $1 == "port:" {print $2; exit}' "$AGH_Y" 2>/dev/null)"
        AGH_MAIN_UP="$(awk '/^[^ #]/ {d = ($1 == "dns:"); u = 0; next} /^  [a-z_]+:/ {u = d && ($1 == "upstream_dns:"); next}
            u && $1 == "-" {sub(/^[ \t]*-[ \t]*/, ""); gsub(/["\047]/, ""); if ($0 !~ /^\[/) print}' "$AGH_Y" 2>/dev/null)"
        KN_TO_AGH="$(printf '%s\n' "$DIAG_RC" | awk -v p=":${AGH_DNS_PORT:-x}" '$1 == "ip" && $2 == "name-server" && index($3, p) {print $3; exit}')"
        # The router: its LAN address from the profile, or loopback.
        LAN_IP="${VWARD_LAN_ADDRESS:-127.0.0.1}"
        if printf '%s\n' "$AGH_MAIN_UP" | grep -Eq "^(udp://|tcp://)?($LAN_IP|127\.0\.0\.1|localhost)(:53)?$"; then
            DNS_STATUS=FAIL DNS_DETAIL="AdGuard Home отправляет запросы обратно роутеру ($LAN_IP) - петля: Keenetic будет отбрасывать запросы. Укажите в AdGuard Home внешние серверы."
        elif [ -n "$KN_TO_AGH" ]; then
            DNS_DETAIL="Keenetic → AdGuard Home ($KN_TO_AGH) → $(printf '%s\n' "$AGH_MAIN_UP" | head -n 2 | tr '\n' ' ')"
        elif [ "${AGH_DNS_PORT:-}" = 53 ]; then
            DNS_STATUS=WARN DNS_DETAIL="AdGuard Home сам отвечает на порту 53: Keenetic не видит DNS-ответов, маршрутизация по доменам может не узнавать адреса"
        else
            DNS_STATUS=WARN DNS_DETAIL="Keenetic не передаёт запросы AdGuard Home (нет ip name-server на порт ${AGH_DNS_PORT:-?})"
        fi
    else
        DNS_DETAIL="AdGuard Home не найден: DNS обслуживает Keenetic"
    fi

    # Files as installed: every file the updater recorded, one sha256sum pass.
    FILES_STATUS=PASS FILES_DETAIL=""
    COMP_JSON="${VWARD_ROOT_PREFIX:-}/opt/var/lib/vward/updater/components.json"
    if [ -r "$COMP_JSON" ]; then
        FILES_LIST="$("$JQ" -r '[.components[].files // {} | to_entries[]] | .[] | .value + "  " + .key' "$COMP_JSON" 2>/dev/null)"
        FILES_TOTAL="$(printf '%s\n' "$FILES_LIST" | grep -c .)"
        FILES_BAD="$(printf '%s\n' "$FILES_LIST" | awk 'NF == 2 {print $2 "\t" $1}' | while IFS="$(printf '\t')" read -r F H; do
            [ -f "${VWARD_ROOT_PREFIX:-}$F" ] || { echo "нет:$F"; continue; }
            A="$(sha256sum "${VWARD_ROOT_PREFIX:-}$F" | cut -d' ' -f1)"; [ "$A" = "$H" ] || echo "изменён:$F"
          done)"
        if [ -n "$FILES_BAD" ]; then
            FILES_STATUS=WARN
            printf '%s\n' "$FILES_BAD" | grep -q '^нет:' && FILES_STATUS=FAIL
            FILES_DETAIL="$(printf '%s\n' "$FILES_BAD" | grep -c .) из $FILES_TOTAL отличаются от установленных: $(printf '%s\n' "$FILES_BAD" | head -n 5 | sed 's#:.*/#: #' | tr '\n' ' ')- обновление VWARD заменит ручные правки"
        else
            FILES_DETAIL="Все $FILES_TOTAL файлов как при установке"
        fi
    else
        FILES_STATUS=WARN FILES_DETAIL="Нет сведений об установленных файлах"
    fi

    OPT_FREE="$(df -Pk /opt 2>/dev/null | awk 'NR==2 {print $4+0}')"
    [ -n "$OPT_FREE" ] || OPT_FREE=0
    LAST_WAN_RC="$(cat /tmp/vward-wan-guard.cron.rc 2>/dev/null)"
    LAST_WG_RC="$(cat /tmp/vward-tunnel-health-chain.cron.rc 2>/dev/null)"
    LAST_ROUTE_RC="$(cat /tmp/vward-route-reconciler-maint.cron.rc 2>/dev/null)"

    "$JQ" -n \
      --arg opt "$OPT_STATUS" --arg jq "$JQ_STATUS" --arg curl "$CURL_STATUS" \
      --arg tcpdump "$TCPDUMP_STATUS" --arg lighttpd "$LIGHTTPD_STATUS" \
      --arg crond "$CROND_STATUS" --arg supervisor "$SUPERVISOR_STATUS" \
      --arg adguard "$ADGUARD_STATUS" --arg adaptive "$ADAPTIVE_STATUS" \
      --arg updater "$UPDATE_STATUS" --arg config "$CONFIG_STATUS" --arg cgi "$CGI_STATUS" \
      --arg wan "$WAN_STATUS" --arg wg "$WG_STATUS" \
      --arg smartdns "$SMARTDNS_STATUS" --arg smartdns_detail "$SMARTDNS_DETAIL" \
      --arg dns "$DNS_STATUS" --arg dns_detail "$DNS_DETAIL" --arg files "$FILES_STATUS" --arg files_detail "$FILES_DETAIL" \
      --arg wan_rc "$LAST_WAN_RC" --arg wg_rc "$LAST_WG_RC" --arg route_rc "$LAST_ROUTE_RC" \
      --argjson wg_count "$WG_COUNT" --argjson opt_free "$OPT_FREE" \
      '{ok:true,checks:[
        {id:"console-api",component:"console",label:"Веб-интерфейс VWARD",status:$cgi,detail:"API отвечает"},
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
        {id:"smartdns",component:"route-engine",label:"Smart DNS мимо VPN",status:$smartdns,detail:$smartdns_detail},
        {id:"dns-chain",component:"route-engine",label:"Цепочка DNS",status:$dns,detail:$dns_detail},
        {id:"files",component:"update-engine",label:"Файлы VWARD",status:$files,detail:$files_detail},
        {id:"updater",component:"update-engine",label:"VWARD Update Engine",status:$updater,detail:"Активный updater slot"},
        {id:"update-config",component:"update-engine",label:"Update config",status:$config,detail:"Конфигурация доступна для чтения"}
      ]}'
    exit 0
fi

# tunnel-probe NAME: on demand only - exit address and its location through the
# tunnel, ping and loss inside it, and the peer settings from the router config.
if [ "$ACTION" = tunnel-probe ]; then
    header_json
    [ "${REQUEST_METHOD:-GET}" = GET ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }
    NAME="$(qget name)"
    case "$NAME" in ''|*[!A-Za-z0-9]*) echo '{"ok":false,"error":"invalid_tunnel"}'; exit 0 ;; esac
    # Only a WireGuard interface the device map knows; its kernel device comes from the map too.
    command -v vward_map_tunnels >/dev/null 2>&1 || { echo '{"ok":false,"error":"profile_unavailable"}'; exit 0; }
    DEV="$(vward_map_tunnels "$(vward_device_map 2>/dev/null)" | awk -v n="$NAME" '$1 == n {print $2; exit}')"
    [ -n "$DEV" ] && vward_valid_ifname "$DEV" && [ -e "${VWARD_SYSFS_NET:-/sys/class/net}/$DEV" ] || { echo '{"ok":false,"error":"tunnel_device_missing"}'; exit 0; }
    PROBE_DIR="$(mktemp -d /tmp/vward-console-tunnel.XXXXXX 2>/dev/null)" || { echo '{"ok":false,"error":"temporary_file_unavailable"}'; exit 0; }
    trap 'rm -rf "$PROBE_DIR"' EXIT
    PING_TARGET=1.1.1.1
    "${VWARD_PING:-ping}" -I "$DEV" -c 4 -W 2 "$PING_TARGET" > "$PROBE_DIR/ping" 2>&1 &
    PING_PID=$!
    "$CURL" --interface "$DEV" --silent --max-time 5 https://ipinfo.io/json > "$PROBE_DIR/exit" 2>/dev/null || :
    PEER="$(ndm_cached running 10 "show running-config" |
        awk -v n="interface $NAME" '$0 == n {on = 1; next} on && /^!/ {exit} on {sub(/^ +/, ""); print}')"
    wait "$PING_PID" 2>/dev/null
    ENDPOINT="$(printf '%s\n' "$PEER" | awk '$1 == "endpoint" {print $2; exit}')"
    KEEPALIVE="$(printf '%s\n' "$PEER" | awk '$1 == "keepalive-interval" {print $2; exit}')"
    AWG=false; printf '%s\n' "$PEER" | grep -q '^wireguard asc ' && AWG=true
    PING_STATS="$(awk '/packet loss/ {for (i = 1; i <= NF; i++) if ($i ~ /%$/) {loss = $i; sub(/%/, "", loss)}}
        /min\/avg\/max/ {split($0, a, "= "); split(a[2], b, "/"); avg = b[2]}
        END {print (loss == "" ? "-" : loss), (avg == "" ? "-" : avg)}' "$PROBE_DIR/ping")"
    EXIT_JSON="$("$JQ" -c 'if type == "object" and (.ip // "") != "" then {ip, city: (.city // ""), region: (.region // ""), country: (.country // ""), org: (.org // "")} else null end' "$PROBE_DIR/exit" 2>/dev/null)"
    [ -n "$EXIT_JSON" ] || EXIT_JSON=null
    "$JQ" -cn --arg name "$NAME" --arg dev "$DEV" --arg endpoint "$ENDPOINT" --arg keepalive "$KEEPALIVE" \
        --argjson awg "$AWG" --argjson exit "$EXIT_JSON" --arg target "$PING_TARGET" \
        --arg loss "${PING_STATS% *}" --arg avg "${PING_STATS#* }" \
        '{ok: true, name: $name, device: $dev,
          server: {host: ($endpoint | if . == "" then null else (split(":") | .[0:-1] | join(":")) end),
                   port: ($endpoint | if . == "" then null else (split(":") | last | tonumber? // null) end),
                   keepalive: ($keepalive | tonumber? // null), awg: $awg},
          exit: $exit,
          ping: {target: $target, loss: ($loss | tonumber? // null), avg_ms: ($avg | tonumber? // null)}}'
    exit 0
fi

if [ "$ACTION" = "route-probe" ]; then
    header_json
    [ "${REQUEST_METHOD:-GET}" = GET ] || {
        echo '{"ok":false,"error":"method_not_allowed"}'
        exit 0
    }

    TYPE="$(qget type)"
    RAW_VALUE="$(qget value)"
    VALUE="$RAW_VALUE"
    [ "$TYPE" = group ] || VALUE="$(printf '%s' "$VALUE" | tr '[:upper:]' '[:lower:]')"
    [ "${#VALUE}" -le 253 ] || {
        echo '{"ok":false,"error":"value_too_long"}'
        exit 0
    }

    HINT_CATALOG=/opt/etc/vward/route-engine/hints-catalog.tsv
    ADAPTIVE_PERSIST=/opt/var/lib/vward/route-engine/adaptive-persist.txt
    IP_CATALOG=/opt/var/lib/vward/policy-sync/catalog
    IP_ACTIVE=/opt/var/lib/vward/policy-sync/active.categories
    IP_OWNED=/opt/var/lib/vward/policy-sync/owned.dynamic.routes
    umask 077
    RUNCFG="$(mktemp /tmp/vward-console-route-probe.XXXXXX 2>/dev/null)" || {
        echo '{"ok":false,"error":"temporary_file_unavailable"}'
        exit 0
    }
    MATCHES_FILE=""

    route_probe_cleanup()
    {
        rm -f "$RUNCFG"
        [ -z "$MATCHES_FILE" ] || rm -f "$MATCHES_FILE"
    }
    trap route_probe_cleanup EXIT
    trap 'exit 1' HUP INT TERM

    ndmc -c "show running-config" 2>/dev/null | tr -d '\r' > "$RUNCFG"

    valid_ipv4()
    {
        printf '%s\n' "$1" | awk -F. 'NF==4 {for(i=1;i<=4;i++){if($i !~ /^[0-9]+$/ || $i<0 || $i>255) exit 1} exit 0} {exit 1}'
    }

    ip_matches_file()
    {
        IP="$1" awk '
        function ipn(s,a){split(s,a,"."); return ((a[1]*256+a[2])*256+a[3])*256+a[4]}
        BEGIN{target=ipn(ENVIRON["IP"])}
        {n=split($0,b,"/"); if(n!=2) next; net=ipn(b[1]); p=b[2]+0; if(p<0||p>32) next; size=2^(32-p); base=int(net/size)*size; if(target>=base && target<base+size){print $0; exit}}
        ' "$2" 2>/dev/null
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

            DNS_OUT="$(/opt/bin/vward-route-resolve4.sh "$VALUE" 2>/dev/null)"
            IPS="$(printf '%s\n' "$DNS_OUT" | awk '/^Address [0-9]+:/ && $3 ~ /^[0-9]+\./ {print $3}' | sort -u | head -n 12)"
            IPS_JSON="$(printf '%s\n' "$IPS" | "$JQ" -Rsc 'split("\n")|map(select(length>0))')"

            HINTS_JSON="$(
                if [ -r "$HINT_CATALOG" ]; then
                    awk -F'|' -v h="$VALUE" '
                    NF>=3 {d=tolower($1); if(h==d || (length(h)>length(d) && substr(h,length(h)-length(d))=="." d)) print $2 "|" $3 "|" $1}' "$HINT_CATALOG" |
                    sort -u | head -n 40 | "$JQ" -Rsc 'split("\n")|map(select(length>0)|split("|")|{source:.[0],category:.[1],match:.[2]})'
                else echo '[]'; fi
            )"

            ADAPTIVE=false
            [ -r "$ADAPTIVE_PERSIST" ] && grep -Fxiq "$VALUE" "$ADAPTIVE_PERSIST" && ADAPTIVE=true

            GROUPS="$(awk -v h="$VALUE" '
                /^object-group fqdn /{g=$3;next}
                /^!/{g="";next}
                g!="" && $1=="include" && tolower($2)==h {print g}
            ' "$RUNCFG" | sort -u)"
            GROUPS_JSON="$(printf '%s\n' "$GROUPS" | "$JQ" -Rsc 'split("\n")|map(select(length>0))')"
            ROUTES_JSON="$(
                printf '%s\n' "$GROUPS" | while IFS= read -r G; do
                    [ -n "$G" ] || continue
                    awk -v g="$G" '$1=="route" && $2=="object-group" && $3==g {print g "|" $4}' "$RUNCFG"
                done | sort -u | "$JQ" -Rsc 'split("\n")|map(select(length>0)|split("|")|{group:.[0],interface:.[1]})'
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

            MATCHES_FILE="$(mktemp /tmp/vward-console-ip-matches.XXXXXX 2>/dev/null)" || {
                echo '{"ok":false,"error":"temporary_file_unavailable"}'
                exit 0
            }
            if [ -r "$IP_ACTIVE" ]; then
                while IFS= read -r CAT; do
                    [ -n "$CAT" ] || continue
                    FILE="$IP_CATALOG/$CAT.cidr"
                    [ -r "$FILE" ] || continue
                    CIDR="$(ip_matches_file "$VALUE" "$FILE")"
                    [ -n "$CIDR" ] && printf '%s|%s\n' "$CAT" "$CIDR" >> "$MATCHES_FILE"
                done < "$IP_ACTIVE"
            fi
            MATCHES_JSON="$(head -n 40 "$MATCHES_FILE" | "$JQ" -Rsc 'split("\n")|map(select(length>0)|split("|")|{category:.[0],cidr:.[1]})')"

            OWNED_CIDR=""
            if [ -r "$IP_OWNED" ]; then OWNED_CIDR="$(ip_matches_file "$VALUE" "$IP_OWNED")"; fi
            CONFIGURED=false
            ROUTE_INTERFACE=""
            if [ -n "$OWNED_CIDR" ]; then
                NET="${OWNED_CIDR%/*}"; PREFIX="${OWNED_CIDR#*/}"; MASK="$(prefix_mask "$PREFIX")"
                if [ -n "${VWARD_TUNNEL_DEVICE:-}" ] && grep -Fqx "ip route $NET $MASK $VWARD_TUNNEL_DEVICE auto" "$RUNCFG"; then
                    CONFIGURED=true
                    ROUTE_INTERFACE=$VWARD_TUNNEL_DEVICE
                fi
            fi
            rm -f "$MATCHES_FILE"
            MATCHES_FILE=""

            "$JQ" -n --arg type ip --arg value "$VALUE" --arg owned "$OWNED_CIDR" --arg iface "$ROUTE_INTERFACE" \
              --argjson matches "$MATCHES_JSON" --argjson configured "$CONFIGURED" \
              '{ok:true,type:$type,value:$value,policy_matches:$matches,owned_cidr:$owned,configured_route:$configured,interface:$iface}'
            ;;
        group)
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
        *)
            echo '{"ok":false,"error":"invalid_probe_type"}'
            ;;
    esac
    exit 0
fi


if [ "$ACTION" = lists-data ]; then
    header_json
    [ "${REQUEST_METHOD:-GET}" = GET ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }
    RUNNING="$(ndm_cached running 10 "show running-config")"
    [ -n "$RUNNING" ] || { echo '{"ok":false,"error":"router_config_unavailable"}'; exit 0; }
    LISTS_CONF=${VWARD_DOMAIN_LISTS_CONF:-$CONFIG_ETC/route-engine/domain-lists.conf}
    LISTS_STATE=$CONFIG_ETC/route-engine/domain-lists
    WATCHED="$(awk -F= '$1 ~ /^watch\./ && $2 == "1" {print substr($1, 7)}' "$LISTS_CONF" 2>/dev/null | "$JQ" -Rn '[inputs | select(length > 0)]')"
    RETURNS="$(ls "$LISTS_STATE" 2>/dev/null | "$JQ" -Rn '[inputs | select(length > 0)]')"
    AUTO="$(grep -h '|LIST_AUTO_VPN|' "${VWARD_ROUTE_EVENTS_LOG:-/opt/var/log/vward-route-engine-events.log}" 2>/dev/null | tail -n 50 |
        awk -F'|' 'NF >= 4 {print $4 "\t" $1 "\t" $3}' | "$JQ" -Rn '[inputs | split("\t") | {(.[0]): {at: .[1], host: .[2]}}] | add // {}')"
    [ -n "$WATCHED" ] || WATCHED='[]'
    [ -n "$RETURNS" ] || RETURNS='[]'
    [ -n "$AUTO" ] || AUTO='{}'
    # Addresses Keenetic learned for each group from DNS answers: 0 on a used list
    # means its domains' queries do not pass the router's DNS.
    ADDRS="$(ndm_cached fqdn-groups 60 "show object-group fqdn" |
        awk '$1 == "group-name:" {g = $2} $1 == "ipv4-addresses-count:" && g != "" {print g "\t" $2; g = ""}' |
        "$JQ" -Rn '[inputs | split("\t") | {(.[0]): (.[1] | tonumber? // null)}] | add // {}' 2>/dev/null)"
    [ -n "$ADDRS" ] || ADDRS='{}'
    # G name / N name description / I name domain / R name target / D domain (Smart DNS)
    printf '%s\n' "$RUNNING" | awk '
        /^object-group fqdn / {cur = $3; print "G\t" cur "\t"; next}
        /^!/ {cur = ""; ctx = 0}
        /^[^ \t!]/ {ctx = ($1 == "dns-proxy" && NF == 1)}
        cur != "" && $1 == "description" {d = $0; sub(/^[ \t]*description[ \t]*/, "", d); gsub(/"/, "", d); print "N\t" cur "\t" d}
        cur != "" && $1 == "include" {print "I\t" cur "\t" tolower($2)}
        ctx && $1 == "route" && $2 == "object-group" {print "R\t" $3 "\t" $4}
        ctx && $1 == "https" && $2 == "upstream" && $(NF-1) == "domain" {print "D\t" tolower($NF)}
        /^ip route [0-9]/ && NF >= 5 {print "S\t" $5 "\t" $3 "\t" $4}
    ' | { cat; command -v vward_agh_smartdns_domains >/dev/null 2>&1 && vward_agh_smartdns_domains | sed 's/^/A\t/'; } | "$JQ" -Rn --arg tun "${VWARD_TUNNEL_INTERFACE:-}" --arg dev "${VWARD_TUNNEL_DEVICE:-}" --arg wan "${VWARD_WAN_INTERFACE:-}" \
        --argjson guard "$([ "$(awk -F= '$1 == "smartdns_guard" {print $2; exit}' "$LISTS_CONF" 2>/dev/null)" = 0 ] && echo false || echo true)" \
        --argjson watched "$WATCHED" --argjson returns "$RETURNS" --argjson auto "$AUTO" --argjson addrs "$ADDRS" '
        def bits: {"255":8,"254":7,"252":6,"248":5,"240":4,"224":3,"192":2,"128":1,"0":0}[.] // 0;
        reduce (inputs | split("\t")) as $r ({g: {}, order: [], r: {}, doh: [], agh: [], s: {}};
            if $r[0] == "G" then (if .g[$r[1]] then . else .g[$r[1]] = {description: "", domains: []} | .order += [$r[1]] end)
            elif $r[0] == "N" then .g[$r[1]].description = $r[2]
            elif $r[0] == "I" then .g[$r[1]].domains += [$r[2]]
            elif $r[0] == "R" then .r[$r[1]] = (.r[$r[1]] // $r[2])
            elif $r[0] == "D" then .doh += [$r[1]]
            elif $r[0] == "A" then .agh += [$r[1]]
            elif $r[0] == "S" then .s[$r[1]] += [$r[2] + "/" + ($r[3] | split(".") | map(bits) | add | tostring)]
            else . end)
        # Keenetic keeps at most 8 DoH rows; AdGuard Home has no such limit.
        | .keenetic = .doh | .doh = (reduce (.doh + .agh)[] as $d ([]; if index([$d]) then . else . + [$d] end))
        | . as $s
        | {ok: true, tunnel: $tun, doh_used: ($s.keenetic | length), doh_limit: 8, smartdns_domains: $s.doh, smartdns_guard: $guard,
           smartdns_sources: {keenetic: $s.keenetic, adguard: ($s.agh | unique)},
           subnets: ($s.s | with_entries(.value |= .[:300])), subnet_counts: ($s.s | with_entries(.value |= length)),
           lists: [$s.order[] | select(. != "AdaptiveAuto") | . as $n | $s.g[$n] as $l | ($s.r[$n] // "") as $t |
             {name: $n, description: $l.description, count: ($l.domains | length), domains: $l.domains[:200], route: $t,
              via: (if $t == "" then "none" elif $t == $tun or $t == $dev then "vpn" elif $t == "ISP" or $t == $wan then "bypass" else "other" end),
              doh: [$s.doh[] as $d | select(any($l.domains[] as $i | $d == $i or ($d | endswith("." + $i)); .)) | $d],
              # Smart DNS answers every domain with one proxy address: one such domain in a
              # tunnel list sends that address - and every Smart DNS service - into the tunnel.
              smartdns_conflict: ((($t == $tun or $t == $dev) and $t != "") and
                any($s.doh[] as $d | $l.domains[] as $i | $d == $i or ($d | endswith("." + $i)) or ($i | endswith("." + $d)); .)),
              watch: ($watched | index([$n]) != null), returnable: ($returns | index([$n]) != null),
              auto: ($auto[$n] // null), addresses: ($addrs[$n] // null)}]}'
    exit 0
fi

if [ "$ACTION" = "control-data" ]; then
    header_json
    [ "${REQUEST_METHOD:-GET}" = GET ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }
    printf '{"ok":true,"run":%s}\n' "$(run_json "$CONTROL_RUN_DIR")"
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

    RUN_JSON="$(run_json "$UPDATE_RUN_DIR")"
    printf '%s' "$RUN_JSON" | "$JQ" -e .running >/dev/null 2>&1 && BUSY=true

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
      --argjson run "$RUN_JSON" \
      '{ok:true,phase:$phase,busy:$busy,pending:{present:$pending,version:$version,priority:$priority,sequence:$sequence},rollback_available:$rollback,allowed:{check:$check_allowed,apply:$apply_allowed,retry:$retry_allowed,rollback:$rollback_allowed,recover:$recover_allowed},
        run:$run}'
    exit 0
fi

if [ "$ACTION" = "control" ] || [ "$ACTION" = "update-control" ]; then
    header_json
    [ "${REQUEST_METHOD:-GET}" = POST ] || {
        echo '{"ok":false,"error":"method_not_allowed"}'
        exit 0
    }

    LENGTH=${CONTENT_LENGTH:-0}
    case "$LENGTH" in ''|*[!0-9]*) LENGTH=0 ;; esac
    [ "$LENGTH" -gt 0 ] && [ "$LENGTH" -le 256 ] || {
        echo '{"ok":false,"error":"invalid_body"}'
        exit 0
    }
    BODY=$(dd bs=1 count="$LENGTH" 2>/dev/null)
    UNKNOWN_KEYS="$(printf '%s\n' "$BODY" | tr '&' '\n' | cut -d= -f1 | awk '$0!="op" && $0!="confirm" {print; exit}')"
    [ -z "$UNKNOWN_KEYS" ] || {
        echo '{"ok":false,"error":"unknown_parameter"}'
        exit 0
    }
    cvalue(){ printf '%s\n' "$BODY" | tr '&' '\n' | awk -F= -v k="$1" '$1==k{print $2;exit}'; }
    OP="$(cvalue op)"
    CONFIRM="$(cvalue confirm)"

    LOCK=/tmp/vward-console-control.lock
    if ! mkdir "$LOCK" 2>/dev/null; then
        echo '{"ok":false,"error":"control_busy"}'
        exit 0
    fi
    trap 'rm -rf "$LOCK"; console_mutation_leave' EXIT
    trap 'exit 1' HUP INT TERM

    if [ "$ACTION" = control ] && updater_mutation_busy; then
        echo '{"ok":false,"error":"updater_busy"}'
        exit 0
    fi
    if [ "$ACTION" = control ]; then
        console_mutation_enter || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }
    fi

    CMD=""; ARG=""; REQUIRED=""; LABEL=""; COMP=""
    if [ "$ACTION" = control ]; then
        case "$OP" in
            refresh-hints) COMP=route-tools; CMD=/opt/bin/vward-route-hints-update.sh; LABEL=refresh-hints ;;
            route-reconcile) COMP=route-reconciler; CMD=/opt/bin/vward-route-reconciler.sh; REQUIRED=ROUTE_RECONCILE; LABEL=route-reconcile ;;
            policy-refresh) COMP=policy-sync; CMD=/opt/bin/vward-policy-sync.sh; ARG=sync; REQUIRED=POLICY_REFRESH; LABEL=policy-refresh ;;
            policy-reconcile) COMP=policy-sync; CMD=/opt/bin/vward-policy-sync.sh; ARG=--reconcile; REQUIRED=POLICY_RECONCILE; LABEL=policy-reconcile ;;
            tunnel-health) COMP=tunnel-guard; CMD=/opt/bin/vward-tunnel-health.sh; LABEL=tunnel-health ;;
            housekeeping) CMD=/opt/bin/vward-housekeeping.sh; LABEL=housekeeping ;;
            wan-renew) COMP=wan-guard; CMD=/opt/bin/vward-wan-recovery.sh; ARG=dhcp-renew; REQUIRED=WAN_RENEW; LABEL=wan-renew ;;
            wan-bounce) COMP=wan-guard; CMD=/opt/bin/vward-wan-recovery.sh; ARG=wan-bounce; REQUIRED=WAN_BOUNCE; LABEL=wan-bounce ;;
            *) echo '{"ok":false,"error":"unknown_control_action"}'; exit 0 ;;
        esac
    else
        CMD=${VWARD_UPDATER_BIN:-/opt/share/vward/updater/current/vward-update.sh}
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

    [ -z "$COMP" ] || ! component_disabled "$COMP" || {
        echo '{"ok":false,"error":"component_disabled"}'
        exit 0
    }
    [ -x "$CMD" ] || {
        echo '{"ok":false,"error":"action_unavailable"}'
        exit 0
    }
    [ -z "$REQUIRED" ] || [ "$CONFIRM" = "$REQUIRED" ] || {
        echo '{"ok":false,"error":"confirmation_required"}'
        exit 0
    }

    START="$(date '+%Y-%m-%dT%H:%M:%S%z')"
    # A confirmed «Установить» or «Повторить» from VWARD installs now, not at the scheduled time.
    case "$LABEL" in update-apply|update-retry) VWARD_UPDATE_MANUAL=1; export VWARD_UPDATE_MANUAL ;; esac
    [ "$ACTION" = update-control ] && run_detached "$UPDATE_RUN_DIR" updater_busy
    case "$LABEL" in
        refresh-hints|route-reconcile|policy-refresh|policy-reconcile|housekeeping) run_detached "$CONTROL_RUN_DIR" control_busy ;;
    esac
    if [ -n "$ARG" ]; then OUT="$("$CMD" "$ARG" 2>&1)"; else OUT="$("$CMD" 2>&1)"; fi
    RC=$?
    SAFE_OUT="$(printf '%s\n' "$OUT" | tail -n 120)"
    printf '%s|CONSOLE_ACTION|action=%s rc=%s\n' "$START" "$LABEL" "$RC" >> /opt/var/log/vward/console-audit.log
    OUT_JSON="$(printf '%s' "$SAFE_OUT" | "$JQ" -Rs .)"
    if [ "$RC" -eq 0 ]; then OK=true; else OK=false; fi
    printf '{"ok":%s,"action":"%s","rc":%s,"output":%s}\n' "$OK" "$LABEL" "$RC" "$OUT_JSON"
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
            FILE=/opt/var/log/vward-wan-guard.log
            ;;
        recovery)
            FILE=/opt/var/log/vward-wan-guard-recovery.log
            ;;
        cron)
            FILE=/opt/var/log/crond.log
            ;;
        routing)
            FILE=/tmp/vward-route-reconciler-maint.cron.out
            ;;
        adaptive)
            FILE=/opt/var/log/vward-route-engine-events.log
            ;;
        updater)
            FILE=/opt/var/log/vward/updater-watch.log
            ;;
        tunnel)
            FILE=/opt/var/log/vward-tunnel-guard.log
            ;;
        policy)
            FILE=/opt/var/log/vward-policy-audit-summary.log
            ;;
        console)
            FILE=/opt/var/log/vward/console-audit.log
            ;;
        wifi)
            FILE=/opt/var/log/vward-wifi-client-guard.log
            ;;
        ads)
            FILE=/opt/var/log/vward-ads-privacy-guard.log
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

# The four router queries run side by side: one after another they were most of
# the time the overview waited for.
ISP_URL=""
[ -z "${VWARD_WAN_INTERFACE:-}" ] || ISP_URL="$VWARD_RCI_BASE/show/interface?name=$VWARD_WAN_INTERFACE"
FETCH_DIR="$(umask 077; mktemp -d /tmp/vward-console-status.XXXXXX 2>/dev/null)" || FETCH_DIR=""
if [ -n "$FETCH_DIR" ]; then
    trap 'rm -rf "${FETCH_DIR:?}"' EXIT
    fetch_json "$VWARD_RCI_BASE/show/version" > "$FETCH_DIR/ver" &
    [ -z "$ISP_URL" ] || fetch_json "$ISP_URL" > "$FETCH_DIR/isp" &
    fetch_json "$VWARD_RCI_BASE/show/internet/status" > "$FETCH_DIR/inet" &
    fetch_json "$VWARD_RCI_BASE/show/interface" > "$FETCH_DIR/ifaces" &
    wait
    VER="$(cat "$FETCH_DIR/ver" 2>/dev/null)"
    ISP="$(cat "$FETCH_DIR/isp" 2>/dev/null)"
    INET="$(cat "$FETCH_DIR/inet" 2>/dev/null)"
    IFACES="$(cat "$FETCH_DIR/ifaces" 2>/dev/null)"
else
    VER="$(fetch_json "$VWARD_RCI_BASE/show/version")"
    ISP=""
    [ -z "$ISP_URL" ] || ISP="$(fetch_json "$ISP_URL")"
    INET="$(fetch_json "$VWARD_RCI_BASE/show/internet/status")"
    IFACES="$(fetch_json "$VWARD_RCI_BASE/show/interface")"
fi
[ -n "$VER" ] || VER='{}'
[ -n "$ISP" ] || ISP='{}'
[ -n "$INET" ] || INET='{}'
[ -n "$IFACES" ] || IFACES='{}'

WG_INTERFACES="$(
    printf '%s\n' "$IFACES" |
    "$JQ" -c '[
        to_entries[] |
        select((.value | type) == "object" and ((.value.type // "") | tostring | ascii_downcase == "wireguard")) |
        .key as $n | .value |
        ((.wireguard.peer // .peer // []) | if type == "array" then (.[0] // {}) elif type == "object" then . else {} end) as $p |
        {
            name:$n,
            description:(.description // ""),
            link:(.link // ""),
            connected:(.connected // ""),
            state:(.state // ""),
            address:((.address // "") | tostring),
            mtu:(.mtu // null),
            uptime:(.uptime // null),
            endpoint:((($p["remote-endpoint-address"] // $p.endpoint // $p["remote-address"] // "") | tostring)
                + (if ($p["remote-port"] // null) != null then ":" + ($p["remote-port"] | tostring) else "" end)),
            rx:($p.rxbytes // $p["rx-bytes"] // .rxbytes // null),
            tx:($p.txbytes // $p["tx-bytes"] // .txbytes // null),
            handshake:($p["last-handshake"] // $p.handshake // null)
        }
    ]' 2>/dev/null
)"

[ -n "$WG_INTERFACES" ] || WG_INTERFACES='[]'

GOUT=/tmp/vward-wan-guard.cron.out

# Last WAN guard report: one pass over the file instead of a pipeline per field.
GVERSION="" GMODE="" GCLASS="" GACTION="" DETAIL=""
if [ -r "$GOUT" ]; then
    while IFS= read -r GLINE || [ -n "$GLINE" ]; do
        case "$GLINE" in
            VERSION=*) GVERSION=${GLINE#VERSION=} ;;
            MODE=*) GMODE=${GLINE#MODE=} ;;
            CLASS=*) GCLASS=${GLINE#CLASS=} ;;
            ACTION=*) GACTION=${GLINE#ACTION=} ;;
            carrier=*) DETAIL=$GLINE ;;
        esac
    done < "$GOUT"
fi

CARRIER="" REC_COUNT="" REC_STAGE=""
for DWORD in $DETAIL; do
    case "$DWORD" in
        carrier=*) [ -n "$CARRIER" ] || CARRIER=${DWORD#carrier=} ;;
        recovery_count=*) [ -n "$REC_COUNT" ] || REC_COUNT=${DWORD#recovery_count=} ;;
        recovery_stage=*) [ -n "$REC_STAGE" ] || REC_STAGE=${DWORD#recovery_stage=} ;;
    esac
done

[ -n "$REC_COUNT" ] || REC_COUNT=0
[ -n "$REC_STAGE" ] || REC_STAGE=0

# One process list for every process check.
set -- $(ps w 2>/dev/null | awk -v subnet="$VWARD_LAN_SUBNET" -v address="$VWARD_LAN_ADDRESS" '
    /[c]rond -b/ && crond == "" { crond = $1 }
    /[v]ward-cron-supervisor.sh/ { sup = 1 }
    /[A]dGuardHome/ { agh = 1 }
    $6 == "/opt/bin/vward-route-engine.sh" || ($5 ~ /^[{]/ && $7 == "/opt/bin/vward-route-engine.sh") { live++ }
    $5 == "tcpdump" && index($0, "src net " subnet) && index($0, "dst host " address) { tcp++ }
    END { print (crond == "" ? "-" : crond), sup + 0, agh + 0, live + 0, tcp + 0 }')
CROND_PID=${1:--}
[ "$CROND_PID" != - ] || CROND_PID=""
SUPERVISOR=${2:-0}
ADGUARD=${3:-0}
LIVE_COUNT=${4:-0}
TCPDUMP_COUNT=${5:-0}
CROND=0
[ -n "$CROND_PID" ] && CROND=1

read -r UPTIME_SEC _ < /proc/uptime 2>/dev/null || UPTIME_SEC=""
UPTIME_SEC=${UPTIME_SEC%%.*}

read_first /tmp/vward-wan-guard.cron.rc GRC
read_first /tmp/vward-wan-guard.cron.last GLAST
read_first /tmp/vward-tunnel-health-chain.cron.rc WGRC
read_first /tmp/vward-tunnel-health-chain.cron.last WGLAST
read_first /tmp/vward-route-reconciler-maint.cron.rc RRC
read_first /tmp/vward-route-reconciler-maint.cron.last RLAST

read_first /opt/share/vward/VERSION VWARD_VERSION
UPDATER_STATE=/opt/var/lib/vward/updater
COMPONENTS="$($JQ -c '.components // {}' "$UPDATER_STATE/components.json" 2>/dev/null || echo '{}')"
kv_file "$UPDATER_STATE/committed.state" installed_update_id=INSTALLED_UPDATE_ID last_sequence=LAST_SEQUENCE last_health_check=LAST_HEALTH
kv_file "$UPDATER_STATE/journal.state" phase=UPDATE_PHASE
kv_file "$UPDATER_STATE/trust.state" highest_seen_sequence=HIGHEST_SEQUENCE
ACTIVE_SLOT="$(CDPATH= cd -- /opt/share/vward/updater/current 2>/dev/null && pwd -P)"

kv_file /opt/etc/vward/update.conf update_enabled=UPDATE_ENABLED auto_apply=AUTO_APPLY \
    auto_critical=AUTO_CRITICAL auto_important=AUTO_IMPORTANT auto_routine=AUTO_ROUTINE \
    barrier_integration_ready=BARRIER_READY channel=UPDATE_CHANNEL safe_window_start=SAFE_START \
    safe_window_end=SAFE_END check_interval_seconds=CHECK_INTERVAL

read_first /opt/var/run/vward/route-engine.pid LIVE_PID
read_first /opt/var/run/vward-console-lighttpd.pid CONSOLE_PID
kv_file /opt/var/lib/vward/tunnel-guard/state DOWN_STREAK=DOWN_STREAK FAILOPEN_ACTIVE=FAILOPEN_ACTIVE
[ -n "$DOWN_STREAK" ] || DOWN_STREAK=0
[ -n "$FAILOPEN_ACTIVE" ] || FAILOPEN_ACTIVE=0

set -- $(df -PTk /opt 2>/dev/null | awk 'NR==2 {print $2, $3, $4, $5}')
OPT_FS=${1:-} OPT_TOTAL_KB=${2:-} OPT_USED_KB=${3:-} OPT_FREE_KB=${4:-}

# Tool versions change only with opkg; they are cached in RAM until then.
VERSIONS_CACHE=/tmp/vward-console-versions
if [ ! -s "$VERSIONS_CACHE" ] || [ /opt/lib/opkg/status -nt "$VERSIONS_CACHE" ]; then
    {
        echo "jq=$($JQ --version 2>/dev/null)"
        echo "curl=$(curl --version 2>/dev/null | awk 'NR==1 {print $2}')"
        echo "lighttpd=$(/opt/sbin/lighttpd -v 2>&1 | awk 'NR==1 {print $1}')"
    } > "$VERSIONS_CACHE.$$" 2>/dev/null && mv "$VERSIONS_CACHE.$$" "$VERSIONS_CACHE" 2>/dev/null
fi
kv_file "$VERSIONS_CACHE" jq=JQ_VERSION curl=CURL_VERSION lighttpd=LIGHTTPD_VERSION

header_json

"$JQ" -n \
  --arg ts "$(date '+%Y-%m-%dT%H:%M:%S%z')" \
  --argjson ver "$VER" \
  --argjson isp "$ISP" \
  --argjson inet "$INET" \
  --argjson wg_interfaces "$WG_INTERFACES" \
  --arg managed_tunnel "${VWARD_TUNNEL_DEVICE:-}" \
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
    managed_device:$managed_tunnel,
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
