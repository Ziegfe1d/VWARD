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
[ -n "${VWARD_WAN_INTERFACE:-}" ] && [ -n "${VWARD_POLICY_GROUP:-}" ] || PROFILE_READY=false

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

    echo "$DATA" |
    "$JQ" -c . 2>/dev/null ||
    echo '{}'
}

ACTION="$(qget action)"
[ -n "$ACTION" ] || ACTION=status

case "$ACTION" in
    status|ping|log|settings|settings-data|security-data|route-data|diagnostics|route-probe|update-data|control|update-control|wifi-data|wifi-control|ads-data|ads-https-data|ads-settings|ads-control|ads-https-control) ;;
    *)
        header_json
        echo '{"ok":false,"error":"unknown_action"}'
        exit 0
        ;;
esac

if [ "${REQUEST_METHOD:-GET}" = POST ]; then
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
        settings|control|update-control|wifi-control|ads-settings|ads-control|ads-https-control) ;;
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
ads_console_tmp(){ umask 077; mktemp "/tmp/vward-console-${1}.XXXXXX"; }
updater_mutation_busy(){ [ -e /opt/var/run/vward/updater.lock ] || [ -L /opt/var/run/vward/updater.lock ] || [ -e /tmp/vward-update-requested ] || [ -L /tmp/vward-update-requested ] || [ -e /tmp/vward-update.lock ] || [ -L /tmp/vward-update.lock ]; }
console_mutation_enter(){
  VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
  [ -r "$VWARD_ADMISSION_LIB" ] || return 1
  . "$VWARD_ADMISSION_LIB"
  vward_admission_enter console-mutation
}
console_mutation_leave(){ command -v vward_admission_leave >/dev/null 2>&1 && vward_admission_leave 2>/dev/null || true; }

if [ "$ACTION" = wifi-data ]; then
    header_json
    [ "${REQUEST_METHOD:-GET}" = GET ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }
    WCONF=/opt/etc/vward/wifi-client-guard.conf
    WSTATE=/opt/var/lib/vward/wifi-client-guard
    wconf(){ awk -F= -v k="$1" '$1==k{print substr($0,index($0,"=")+1);exit}' "$WCONF" 2>/dev/null; }
    ENABLED="$(wconf ENABLED)"; [ "$ENABLED" = 1 ] || ENABLED=0
    CONTROL_ENABLED="$(wconf CONTROL_ENABLED)"; [ "$CONTROL_ENABLED" = 1 ] || CONTROL_ENABLED=0
    AUTO_APPLY="$(wconf AUTO_APPLY)"; [ "$AUTO_APPLY" = 1 ] || AUTO_APPLY=0
    CLIENTS="$(awk -F '\t' 'NF>=9 && $2 ~ /^([0-9a-fA-F][0-9a-fA-F]:){5}[0-9a-fA-F][0-9a-fA-F]$/ {print $2 "\t" $3 "\t" $4 "\t" $5 "\t" $6 "\t" $7 "\t" $8 "\t" $9}' "$WSTATE/analysis.tsv" 2>/dev/null | head -n 100 | "$JQ" -Rn '[inputs|split("\t")|{mac:.[0],band:.[1],health:.[2],recommendation:.[3],reason:.[4],switches:(.[5]|tonumber?//0),weak_5g:(.[6]|tonumber?//0),min_5g_rssi:.[7]}]')"
    [ -n "$CLIENTS" ] || CLIENTS='[]'
    RC="$(cat /tmp/vward-wifi-client-guard.cron.rc 2>/dev/null)"; case "$RC" in ''|*[!0-9]*) RC=-1;; esac
    LAST="$(cat /tmp/vward-wifi-client-guard.cron.last 2>/dev/null | tr '\n' ' ' | cut -c1-80)"
    COUNT="$(printf '%s' "$CLIENTS" | "$JQ" 'length' 2>/dev/null)"; case "$COUNT" in ''|*[!0-9]*) COUNT=0;; esac
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
    WCTL=/opt/bin/vward-wifi-client-control.sh; [ -x "$WCTL" ] || { echo '{"ok":false,"error":"action_unavailable"}'; exit 0; }
    OUT="$("$WCTL" "$OP" "$MAC" "$CONFIRM" 2>&1)"; RC=$?
    printf '%s|CONSOLE_ACTION|action=wifi-%s mac=%s rc=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$OP" "$MAC" "$RC" >> /opt/var/log/vward/console-audit.log
    OUT_JSON="$(printf '%s' "$OUT" | tail -n 80 | "$JQ" -Rs .)"
    [ "$RC" -eq 0 ] && OK=true || OK=false
    printf '{"ok":%s,"action":"wifi-%s","rc":%s,"output":%s}\n' "$OK" "$OP" "$RC" "$OUT_JSON"
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
  SOURCES="$([ -x "$SRCCTL" ] && "$SRCCTL" list 2>/dev/null | "$JQ" -Rn --arg state "$AST/sources" '[inputs|split("|")|{id:.[0],mode:.[1],name:.[2],cached:(.[3]=="1"),purpose:.[4]}]' || echo '[]')"
  JOBS="$([ -x "$JOB" ] && "$JOB" status 2>/dev/null | awk -F= 'NF>=2{k=$1;sub(/^[^=]*=/,"",$0);print k "\t" $0}' | "$JQ" -Rn '[inputs|split("\t")|{(.[0]):.[1]}]|add//{}' || echo '{}')"
  LAST_OUTPUT_PATH="$(printf '%s' "$JOBS" | "$JQ" -r '.LAST_output // ""' 2>/dev/null)"; LAST_OUTPUT=""
  case "$LAST_OUTPUT_PATH" in "$AST/jobs/"*.out) [ -r "$LAST_OUTPUT_PATH" ] && LAST_OUTPUT="$(head -c 20000 "$LAST_OUTPUT_PATH" 2>/dev/null)" ;; esac
  "$JQ" -n --argjson paused "$([ "$PAUSED" = 1 ]&&echo true||echo false)" --argjson settings "$SETJSON" --argjson sources "$SOURCES" --argjson manual "$MANUAL" --argjson jobsraw "$JOBS" --arg job_output "$LAST_OUTPUT" --argjson b "${BLOCKED:-0}" --argjson r "${REVIEW:-0}" --argjson a "${ALLOW:-0}" --argjson t "${TRUST:-0}" '{ok:true,component:"ads-privacy-guard",paused:$paused,settings:$settings,sources:$sources,manual_rules:$manual,counts:{blocked:$b,review:$r,allow:$a,trust:$t},jobs:{queued:($jobsraw.JOB_QUEUE//"0"|tonumber?//0),current:{state:($jobsraw.CURRENT_state//"IDLE"),type:($jobsraw.CURRENT_type//"")},last:{state:($jobsraw.LAST_state//"NONE"),type:($jobsraw.LAST_type//""),output:$job_output}}}'
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
  LEN=${CONTENT_LENGTH:-0}; case "$LEN" in ''|*[!0-9]*) LEN=0;; esac; [ "$LEN" -gt 0 ]&&[ "$LEN" -le 1024 ] || { echo '{"ok":false,"error":"invalid_body"}'; exit 0; }; BODY=$(dd bs=1 count="$LEN" 2>/dev/null)
  val(){ printf '%s\n' "$BODY"|tr '&' '\n'|awk -F= -v k="$1" '$1==k{print substr($0,index($0,"=")+1);exit}'; }
  OP="$(val op)"; DOMAIN="$(val domain|tr '[:upper:]' '[:lower:]')"; SCOPE="$(val scope)"; [ -n "$SCOPE" ]||SCOPE=exact
  case "$OP" in pause|resume|allow|block|remove-override|source-mode|enqueue) ;; *) echo '{"ok":false,"error":"invalid_operation"}'; exit 0;; esac
  case "$OP" in
    allow|block|remove-override) ads_valid_domain "$DOMAIN" || { echo '{"ok":false,"error":"invalid_domain"}'; exit 0; }; case "$SCOPE" in exact|suffix) ;; *) echo '{"ok":false,"error":"invalid_scope"}'; exit 0 ;; esac ;;
    source-mode) SID="$(val source)"; MODE="$(val mode)"; ads_valid_source_id "$SID" || { echo '{"ok":false,"error":"invalid_source"}'; exit 0; }; case "$MODE" in off|check|active) ;; *) echo '{"ok":false,"error":"invalid_source_mode"}'; exit 0 ;; esac ;;
    enqueue) JOB="$(val job)"; case "$JOB" in scan|sources-update|rules-rebuild) ;; publish) [ "$(val confirm)" = ADS_PUBLISH ] || { echo '{"ok":false,"error":"confirmation_required"}'; exit 0; } ;; probe) ads_valid_domain "$DOMAIN" || { echo '{"ok":false,"error":"invalid_domain"}'; exit 0; } ;; *) echo '{"ok":false,"error":"invalid_job"}'; exit 0 ;; esac ;;
  esac
  RC=0; OUT="$(ads_console_tmp ads-control)" || { echo '{"ok":false,"error":"temporary_file_failed"}'; exit 0; }
  case "$OP" in
    pause|resume) /opt/bin/vward-ads-privacy-control.sh "$OP" >"$OUT" 2>&1||RC=$? ;;
    allow|block|remove-override) C="$OP"; [ "$OP" = remove-override ]&&C=remove; /opt/bin/vward-ads-privacy-control.sh "$C" "$DOMAIN" "$SCOPE" >"$OUT" 2>&1||RC=$? ;;
    source-mode) /opt/bin/vward-ads-privacy-source-control.sh set "$SID" "$MODE" >"$OUT" 2>&1||RC=$? ;;
    enqueue) /opt/bin/vward-ads-privacy-job.sh enqueue "$JOB" "$DOMAIN" >"$OUT" 2>&1||RC=$? ;;
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
        def typed($v): if .type=="boolean" then ($v=="1") elif .type=="integer" and ($v|test("^[0-9]+$")) then ($v|tonumber) else $v end;
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
      '{ok:true,profile_ready:$ready,listener:{scope:$listener_scope,address:$listener_address,port:$listener_port,wildcard:$listener_wildcard,socket_state:$socket_state,source:"generated_config"},profile:{lan_address:$lan_address,lan_subnet:$lan_subnet,dns_server:$dns_server,wan_device:$wan_device,wan_interface:$wan_interface,tunnel_device:$tunnel_device,tunnel_interface:$tunnel_interface,policy_group:$policy_group,console_port:$console_port,adguard_address:$adguard_address,adguard_port:$adguard_port},external_services:{adguard:{address:$adguard_address,port:$adguard_port}},server:{config_test:$config_test,mod_setenv:$mod_setenv},api:{mutation_guard:true,cors:false,directory_listing:false,authentication:false}}'
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
    ps 2>/dev/null | grep -q '[v]ward-route-engine.sh' && ADAPTIVE_STATUS=PASS

    UPDATE_STATUS=FAIL
    [ -x /opt/share/vward/updater/current/vward-update.sh ] && UPDATE_STATUS=PASS
    CONFIG_STATUS=FAIL
    [ -r /opt/etc/vward/update.conf ] && CONFIG_STATUS=PASS
    CGI_STATUS=PASS

    WAN_JSON="$(fetch_json "$VWARD_RCI_BASE/show/internet/status")"
    WAN_STATUS="$(printf '%s\\n' "$WAN_JSON" | "$JQ" -r 'if (.internet // .connected // false) == true then "PASS" else "WARN" end' 2>/dev/null)"
    case "$WAN_STATUS" in PASS|WARN) ;; *) WAN_STATUS=UNKNOWN ;; esac

    IF_JSON="$(fetch_json "$VWARD_RCI_BASE/show/interface")"
    WG_COUNT="$(printf '%s\\n' "$IF_JSON" | "$JQ" -r '[to_entries[] | select((.value | type) == "object" and ((.value.type // "") | test("^wireguard$"; "i")))] | length' 2>/dev/null)"
    case "$WG_COUNT" in ''|*[!0-9]*) WG_COUNT=0 ;; esac
    [ "$WG_COUNT" -gt 0 ] && WG_STATUS=PASS || WG_STATUS=WARN

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

            DNS_OUT="$(/opt/bin/vward-route-resolve4.sh "$VALUE" 2>/dev/null)"
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
    trap 'rm -rf "$LOCK"; console_mutation_leave' EXIT
    trap 'exit 1' HUP INT TERM

    if [ "$ACTION" = control ] && updater_mutation_busy; then
        echo '{"ok":false,"error":"updater_busy"}'
        exit 0
    fi
    if [ "$ACTION" = control ]; then
        console_mutation_enter || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }
    fi

    CMD=""; ARG=""; REQUIRED=""; LABEL=""
    if [ "$ACTION" = control ]; then
        case "$OP" in
            refresh-hints) CMD=/opt/bin/vward-route-hints-update.sh; LABEL=refresh-hints ;;
            route-reconcile) CMD=/opt/bin/vward-route-reconciler.sh; REQUIRED=ROUTE_RECONCILE; LABEL=route-reconcile ;;
            policy-refresh) CMD=/opt/bin/vward-policy-sync.sh; ARG=sync; REQUIRED=POLICY_REFRESH; LABEL=policy-refresh ;;
            policy-reconcile) CMD=/opt/bin/vward-policy-sync.sh; ARG=--reconcile; REQUIRED=POLICY_RECONCILE; LABEL=policy-reconcile ;;
            tunnel-health) CMD=/opt/bin/vward-tunnel-health.sh; LABEL=tunnel-health ;;
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
    "$VWARD_RCI_BASE/show/version"
)"

ISP='{}'
[ -z "${VWARD_WAN_INTERFACE:-}" ] || ISP="$(fetch_json "$VWARD_RCI_BASE/show/interface?name=$VWARD_WAN_INTERFACE")"

INET="$(
    fetch_json \
    "$VWARD_RCI_BASE/show/internet/status"
)"

IFACES="$(
    fetch_json \
    "$VWARD_RCI_BASE/show/interface"
)"

WG_NAMES="$(
    printf '%s\n' "$IFACES" |
    "$JQ" -r 'to_entries[] | select((.value | type) == "object" and ((.value.type // "") | test("^wireguard$"; "i"))) | .key' 2>/dev/null
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

GOUT=/tmp/vward-wan-guard.cron.out

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

GRC="$(cat /tmp/vward-wan-guard.cron.rc 2>/dev/null)"
GLAST="$(cat /tmp/vward-wan-guard.cron.last 2>/dev/null)"

WGRC="$(cat /tmp/vward-tunnel-health-chain.cron.rc 2>/dev/null)"
WGLAST="$(cat /tmp/vward-tunnel-health-chain.cron.last 2>/dev/null)"

RRC="$(cat /tmp/vward-route-reconciler-maint.cron.rc 2>/dev/null)"
RLAST="$(cat /tmp/vward-route-reconciler-maint.cron.last 2>/dev/null)"

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

LIVE_PID="$(cat /opt/var/run/vward/route-engine.pid 2>/dev/null)"
CONSOLE_PID="$(cat /opt/var/run/vward-console-lighttpd.pid 2>/dev/null)"
LIVE_COUNT="$(ps w 2>/dev/null | awk '$6=="/opt/bin/vward-route-engine.sh"{n++} END{print n+0}')"
TCPDUMP_COUNT="$(ps w 2>/dev/null | awk -v subnet="$VWARD_LAN_SUBNET" -v address="$VWARD_LAN_ADDRESS" '$5=="tcpdump" && index($0,"src net " subnet) && index($0,"dst host " address){n++} END{print n+0}')"
FAILOPEN_STATE=/opt/var/lib/vward/tunnel-guard/state
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
