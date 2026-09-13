#!/bin/sh
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "HEALTH=FAIL"; echo "REASON=common_library_missing"; exit 1; }
. "$LIB"
ads_mkdirs >/dev/null 2>&1 || true
FAIL=0; WARN=0
check_file(){ if [ -r "$2" ]; then echo "$1=PASS"; else echo "$1=FAIL"; FAIL=$((FAIL+1)); fi; }
check_exec(){ if [ -x "$2" ]; then echo "$1=PASS"; else echo "$1=FAIL"; FAIL=$((FAIL+1)); fi; }

echo "VWARD_ADS_PRIVACY_GUARD_HEALTH"; echo "VERSION=$VWARD_ADS_VERSION"
check_file CONFIG "$ADS_CONFIG"; check_file SOURCE_REGISTRY "$ADS_SOURCE_REGISTRY"; check_file TRUST_REGISTRY "$ADS_TRUST_BUILTIN"; check_exec JQ "$ADS_JQ"; check_exec CURL "$ADS_CURL"
if [ -r "$ADS_CONFIG" ]; then
  if ! ads_secure_file_ok "$ADS_CONFIG"; then echo "CONFIG_PERMISSIONS=FAIL"; FAIL=$((FAIL+1)); else echo "CONFIG_PERMISSIONS=PASS"; fi
  ads_load_config
fi
QUERY_SOURCE="${QUERY_SOURCE:-auto}"; PUBLISH_MODE="${PUBLISH_MODE:-staged}"
echo "ENABLED=${ENABLED:-1}"; echo "RUN_MODE=${RUN_MODE:-scheduled}"; echo "QUERY_SOURCE=$QUERY_SOURCE"; echo "PUBLISH_MODE=$PUBLISH_MODE"

API_OK=0; API_TMP="${TMPDIR:-/tmp}/vward-ads-health-api.$$"; trap 'rm -f "$API_TMP"' EXIT INT TERM
if [ "$QUERY_SOURCE" != file ] && ads_agh_api_get 'querylog?limit=1&response_status=all' "$API_TMP" >/dev/null 2>&1 && "$ADS_JQ" -e '.data|type=="array"' "$API_TMP" >/dev/null 2>&1; then API_OK=1; fi
echo "ADGUARD_API=$([ "$API_OK" -eq 1 ] && echo PASS || echo UNAVAILABLE)"
FILE_OK=0; [ -r "$ADS_QUERYLOG" ] && FILE_OK=1; echo "ADGUARD_QUERYLOG_FILE=$([ "$FILE_OK" -eq 1 ] && echo PASS || echo UNAVAILABLE)"
case "$QUERY_SOURCE" in
 api) [ "$API_OK" -eq 1 ] || { echo "QUERY_INPUT=FAIL"; FAIL=$((FAIL+1)); } ;;
 file) [ "$FILE_OK" -eq 1 ] || { echo "QUERY_INPUT=FAIL"; FAIL=$((FAIL+1)); } ;;
 auto) [ "$API_OK" -eq 1 ] || [ "$FILE_OK" -eq 1 ] || { echo "QUERY_INPUT=FAIL"; FAIL=$((FAIL+1)); } ;;
 *) echo "QUERY_INPUT=FAIL"; FAIL=$((FAIL+1)) ;;
esac
[ "$FAIL" -eq 0 ] && echo "QUERY_INPUT=PASS" || true

ACTIVE=0; CHECK=0; OFF=0; INDEXES=0
if [ -r "$ADS_SOURCE_REGISTRY" ] && [ -x "$ADS_JQ" ]; then
  for sid in $("$ADS_JQ" -r '.sources[].id' "$ADS_SOURCE_REGISTRY" 2>/dev/null); do
    mode="$(ads_source_mode "$sid")"; case "$mode" in active) ACTIVE=$((ACTIVE+1)) ;; check) CHECK=$((CHECK+1)) ;; *) OFF=$((OFF+1)) ;; esac
    [ -s "$ADS_STATE/sources/$sid.domains" ] && INDEXES=$((INDEXES+1))
  done
fi
echo "SOURCES_ACTIVE=$ACTIVE"; echo "SOURCES_CHECK=$CHECK"; echo "SOURCES_OFF=$OFF"; echo "SOURCE_INDEXES=$INDEXES"
MIN_SOURCE_INDEXES="$(ads_num "${MIN_SOURCE_INDEXES:-3}" 3)"; if [ "$INDEXES" -lt "$MIN_SOURCE_INDEXES" ]; then echo "SOURCE_HEALTH=WARNING"; WARN=$((WARN+1)); else echo "SOURCE_HEALTH=PASS"; fi

PAUSED=0; [ -r "$ADS_CONTROL_STATE" ] && PAUSED="$(awk -F= '$1=="paused"{print $2;exit}' "$ADS_CONTROL_STATE")"; case "$PAUSED" in 1) ;; *) PAUSED=0 ;; esac; echo "PAUSED=$PAUSED"
[ -r "$ADS_RUNTIME_STATUS" ] && sed 's/^/RUNTIME_/' "$ADS_RUNTIME_STATUS"; [ -r "$ADS_SCHEDULER_STATUS" ] && sed 's/^/SCHEDULER_/' "$ADS_SCHEDULER_STATUS"
[ -r "$ADS_STATE/jobs/current.status" ] && sed 's/^/JOB_CURRENT_/' "$ADS_STATE/jobs/current.status" || true; [ -r "$ADS_STATE/jobs/last.status" ] && sed 's/^/JOB_LAST_/' "$ADS_STATE/jobs/last.status" || true
VERDICTS="$ADS_STATE/verdicts.tsv"; if [ -r "$VERDICTS" ]; then echo "BLOCKED=$(awk -F'|' '$3=="BLOCK"{n++}END{print n+0}' "$VERDICTS")"; echo "REVIEW=$(awk -F'|' '$2=="SUSPECT"{n++}END{print n+0}' "$VERDICTS")"; echo "ALLOW=$(awk -F'|' '$2=="ALLOW"{n++}END{print n+0}' "$VERDICTS")"; echo "TRUST=$(awk -F'|' '$2=="TRUST"{n++}END{print n+0}' "$VERDICTS")"; else echo "VERDICT_STATE=NOT_INITIALIZED"; fi
[ -r "$ADS_STATE/last-run.status" ] || { echo "LAST_RUN=NOT_INITIALIZED"; WARN=$((WARN+1)); }
[ -r "$ADS_STATE/sources.status" ] || { echo "LAST_SOURCE_UPDATE=NOT_INITIALIZED"; WARN=$((WARN+1)); }
HTTPSCTL="${VWARD_ADS_HTTPS_CTL:-/opt/bin/vward-ads-privacy-https.sh}"; [ -x "$HTTPSCTL" ] || HTTPSCTL="$SELF_DIR/vward-ads-privacy-https.sh"
if [ -x "$HTTPSCTL" ] && [ -r "$ADS_ETC/https/https-content-guard.conf" ]; then
  HTTPS_OUT="${TMPDIR:-/tmp}/vward-ads-health-https.$$"
  if "$HTTPSCTL" status >"$HTTPS_OUT" 2>/dev/null; then
    sed 's/^/HTTPS_/' "$HTTPS_OUT"
    HEN="$(awk -F= '$1=="ENABLED"{print $2;exit}' "$HTTPS_OUT")"; HRUN="$(awk -F= '$1=="RUNNING"{print $2;exit}' "$HTTPS_OUT")"; HREADY="$(awk -F= '$1=="PROVIDER_READY"{print $2;exit}' "$HTTPS_OUT")"
    if [ "$HEN" = 1 ] && { [ "$HREADY" != 1 ] || [ "$HRUN" != 1 ]; }; then WARN=$((WARN+1)); fi
  else echo "HTTPS_STATUS=WARNING"; WARN=$((WARN+1)); fi
  rm -f "$HTTPS_OUT"
else echo "HTTPS_GUARD=NOT_CONFIGURED"; fi
if [ "$FAIL" -gt 0 ]; then echo "HEALTH=FAIL"; echo "FAILURES=$FAIL"; echo "WARNINGS=$WARN"; exit 1; fi
if [ "$WARN" -gt 0 ]; then echo "HEALTH=WARNING"; echo "FAILURES=0"; echo "WARNINGS=$WARN"; exit 0; fi
echo "HEALTH=PASS"; echo "FAILURES=0"; echo "WARNINGS=0"
