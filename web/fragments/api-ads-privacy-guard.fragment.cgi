# Dev.7 integration fragment. Merge into web/cgi-bin/api.cgi.
# Allowlist additions:
#   GET:  ads-data | ads-https-data
#   POST: ads-settings | ads-control | ads-https-control
# Keep the existing X-VWARD-Request: console and Content-Type guards.

ads_kv_json(){ [ -r "$1" ] && awk -F= 'NF>=2{k=$1;sub(/^[^=]*=/,"",$0);print k "\t" $0}' "$1" | "$JQ" -Rn '[inputs|split("\t")|{(.[0]):.[1]}]|add//{}' || echo '{}'; }
ads_valid_domain(){ printf '%s\n' "$1" | awk 'length($0)>0&&length($0)<=253&&$0~/^[a-z0-9_][a-z0-9_.-]*[a-z0-9_]$/&&index($0,".")>0{exit 0}{exit 1}'; }
ads_console_tmp(){ umask 077; mktemp "/tmp/vward-console-${1}.XXXXXX"; }

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
  header_json; [ "${REQUEST_METHOD:-GET}" = POST ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }; [ ! -e /opt/var/run/vward/updater.lock ] || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }
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
  header_json; [ "${REQUEST_METHOD:-GET}" = POST ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }; [ ! -e /opt/var/run/vward/updater.lock ] || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }
  LEN=${CONTENT_LENGTH:-0}; case "$LEN" in ''|*[!0-9]*) LEN=0;; esac; [ "$LEN" -gt 0 ]&&[ "$LEN" -le 3072 ] || { echo '{"ok":false,"error":"invalid_body"}'; exit 0; }; BODY=$(dd bs=1 count="$LEN" 2>/dev/null)
  val(){ printf '%s\n' "$BODY"|tr '&' '\n'|awk -F= -v k="$1" '$1==k{print substr($0,index($0,"=")+1);exit}'; }
  UNKNOWN="$(printf '%s\n' "$BODY"|tr '&' '\n'|cut -d= -f1|awk '$0!="ENABLED"&&$0!="RUN_MODE"&&$0!="SCHEDULE_INTERVAL_MIN"&&$0!="DYNAMIC_MIN_INTERVAL_SEC"&&$0!="DYNAMIC_MAX_LOAD_PER_CPU_X100"&&$0!="DYNAMIC_MIN_MEM_AVAILABLE_KB"&&$0!="DYNAMIC_MIN_OPT_FREE_KB"&&$0!="DYNAMIC_MAX_CANDIDATES_PER_RUN"&&$0!="AUTO_SOURCE_UPDATE"&&$0!="SOURCE_UPDATE_INTERVAL_HOURS"&&$0!="QUERY_SOURCE"&&$0!="AUTO_RULE_SCOPE"&&$0!="PUBLISH_MODE"&&$0!="AUTO_PUBLISH"&&$0!="confirm"{print;exit}')"; [ -z "$UNKNOWN" ] || { echo '{"ok":false,"error":"unknown_parameter"}'; exit 0; }
  set -- set; for K in ENABLED RUN_MODE SCHEDULE_INTERVAL_MIN DYNAMIC_MIN_INTERVAL_SEC DYNAMIC_MAX_LOAD_PER_CPU_X100 DYNAMIC_MIN_MEM_AVAILABLE_KB DYNAMIC_MIN_OPT_FREE_KB DYNAMIC_MAX_CANDIDATES_PER_RUN AUTO_SOURCE_UPDATE SOURCE_UPDATE_INTERVAL_HOURS QUERY_SOURCE AUTO_RULE_SCOPE PUBLISH_MODE AUTO_PUBLISH; do V="$(val "$K")"; [ -n "$V" ]&&set -- "$@" "$K" "$V"; done
  [ "$(val AUTO_PUBLISH)" != 1 ] || [ "$(val confirm)" = ADS_AUTO_PUBLISH ] || { echo '{"ok":false,"error":"confirmation_required"}'; exit 0; }
  OUT="$(ads_console_tmp ads-settings)" || { echo '{"ok":false,"error":"temporary_file_failed"}'; exit 0; }; /opt/bin/vward-ads-privacy-settings.sh "$@" >"$OUT" 2>&1; RC=$?; RES="$(head -c 12000 "$OUT")"; rm -f "$OUT"; "$JQ" -n --argjson ok "$([ "$RC" -eq 0 ]&&echo true||echo false)" --argjson rc "$RC" --arg output "$RES" '{ok:$ok,rc:$rc,output:$output}'; exit 0
fi

if [ "$ACTION" = ads-control ]; then
  header_json; [ "${REQUEST_METHOD:-GET}" = POST ] || { echo '{"ok":false,"error":"method_not_allowed"}'; exit 0; }; [ ! -e /opt/var/run/vward/updater.lock ] || { echo '{"ok":false,"error":"updater_busy"}'; exit 0; }
  LEN=${CONTENT_LENGTH:-0}; case "$LEN" in ''|*[!0-9]*) LEN=0;; esac; [ "$LEN" -gt 0 ]&&[ "$LEN" -le 1024 ] || { echo '{"ok":false,"error":"invalid_body"}'; exit 0; }; BODY=$(dd bs=1 count="$LEN" 2>/dev/null)
  val(){ printf '%s\n' "$BODY"|tr '&' '\n'|awk -F= -v k="$1" '$1==k{print substr($0,index($0,"=")+1);exit}'; }
  OP="$(val op)"; DOMAIN="$(val domain|tr '[:upper:]' '[:lower:]')"; SCOPE="$(val scope)"; [ -n "$SCOPE" ]||SCOPE=exact
  case "$OP" in pause|resume|allow|block|remove-override|source-mode|enqueue) ;; *) echo '{"ok":false,"error":"invalid_operation"}'; exit 0;; esac
  RC=0; OUT="$(ads_console_tmp ads-control)" || { echo '{"ok":false,"error":"temporary_file_failed"}'; exit 0; }
  case "$OP" in
    pause|resume) /opt/bin/vward-ads-privacy-control.sh "$OP" >"$OUT" 2>&1||RC=$? ;;
    allow|block|remove-override) ads_valid_domain "$DOMAIN" || { echo '{"ok":false,"error":"invalid_domain"}'; exit 0; }; case "$SCOPE" in exact|suffix);;*) echo '{"ok":false,"error":"invalid_scope"}'; exit 0;;esac; C="$OP"; [ "$OP" = remove-override ]&&C=remove; /opt/bin/vward-ads-privacy-control.sh "$C" "$DOMAIN" "$SCOPE" >"$OUT" 2>&1||RC=$? ;;
    source-mode) SID="$(val source)"; MODE="$(val mode)"; /opt/bin/vward-ads-privacy-source-control.sh set "$SID" "$MODE" >"$OUT" 2>&1||RC=$? ;;
    enqueue) JOB="$(val job)"; case "$JOB" in scan|sources-update|rules-rebuild);;publish) [ "$(val confirm)" = ADS_PUBLISH ]||{ echo '{"ok":false,"error":"confirmation_required"}'; exit 0;};;probe) ads_valid_domain "$DOMAIN"||{ echo '{"ok":false,"error":"invalid_domain"}'; exit 0;};;*) echo '{"ok":false,"error":"invalid_job"}'; exit 0;;esac; /opt/bin/vward-ads-privacy-job.sh enqueue "$JOB" "$DOMAIN" >"$OUT" 2>&1||RC=$? ;;
  esac
  RES="$(head -c 12000 "$OUT" 2>/dev/null)"; rm -f "$OUT"; printf '%s|ADS_CONTROL|op=%s rc=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$OP" "$RC" >>/opt/var/log/vward/console-audit.log; "$JQ" -n --argjson ok "$([ "$RC" -eq 0 ]&&echo true||echo false)" --argjson rc "$RC" --arg result "$RES" '{ok:$ok,rc:$rc,result:$result}'; exit 0
fi
