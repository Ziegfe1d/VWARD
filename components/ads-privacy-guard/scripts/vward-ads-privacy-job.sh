#!/bin/sh
# Durable single-worker queue for long VWARD Ads & Privacy Guard actions.
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "FAIL: common library not found" >&2; exit 1; }
. "$LIB"
ads_mkdirs || ads_die "cannot create component directories"
[ -r "$ADS_CONFIG" ] && ads_load_config

JOBS="$ADS_STATE/jobs"
QUEUED="$JOBS/queued"
RUNNING="$JOBS/running"
LEGACY_QUEUE="$JOBS/queue"
CURRENT="$JOBS/current.status"
LAST="$JOBS/last.status"
LOCK="$JOBS/worker.lock"
mkdir -p "$QUEUED" "$RUNNING" || ads_die "cannot create jobs directories"
chmod 0700 "$JOBS" "$QUEUED" "$RUNNING" 2>/dev/null || true

job_valid_domain() { jvd="$(ads_normalize_domain "${1:-}")"; ads_valid_domain "$jvd" || return 1; printf '%s\n' "$jvd"; }

status_write()
{
    js_file="$1"; shift
    js_tmp="$ADS_STATE/work/job-status.$$"
    { echo "ts=$(ads_now)"; printf '%s\n' "$@"; } > "$js_tmp" || return 1
    ads_atomic_copy "$js_tmp" "$js_file" 0600
    js_rc=$?; rm -f "$js_tmp"; return "$js_rc"
}

spool_line()
{
    js_line="$1"
    IFS='|' read -r js_id js_type js_arg js_created <<EOJ
$js_line
EOJ
    [ -n "$js_id" ] && [ -n "$js_type" ] && [ -n "$js_created" ] || return 1
    js_dest="$QUEUED/$js_id.job"; js_n=0
    while [ -e "$js_dest" ] || [ -e "$RUNNING/$(basename "$js_dest")" ]; do js_n=$((js_n + 1)); js_dest="$QUEUED/$js_id-$js_n.job"; done
    js_tmp="$ADS_STATE/work/job-spool.$$.$js_n"
    printf '%s\n' "$js_line" > "$js_tmp" || return 1
    chmod 0600 "$js_tmp" 2>/dev/null || true
    mv "$js_tmp" "$js_dest"
}

enqueue()
{
    je_type="$1"; je_arg="${2:-}"
    case "$je_type" in
        scan|sources-update|publish|rules-rebuild) [ -z "$je_arg" ] || ads_die "unexpected job argument" ;;
        probe) je_arg="$(job_valid_domain "$je_arg")" || ads_die "invalid probe domain" ;;
        *) ads_die "unsupported job type: $je_type" ;;
    esac
    je_id="$(date '+%Y%m%d%H%M%S')-$$"
    spool_line "$je_id|$je_type|$je_arg|$(ads_epoch)" || ads_die "cannot persist queued job"
    ads_log "JOB_ENQUEUE|id=$je_id|type=$je_type|arg=$je_arg"
    echo "JOB=QUEUED"; echo "JOB_ID=$je_id"; echo "JOB_TYPE=$je_type"
    [ -n "$je_arg" ] && echo "JOB_ARG=$je_arg"
    return 0
}

recover_jobs()
{
    for jr_result in "$RUNNING"/*.result; do
        [ -f "$jr_result" ] || continue
        jr_job="${jr_result%.result}.job"
        [ -r "$jr_job" ] || { rm -f "$jr_result"; continue; }
        IFS='|' read -r jr_id jr_type jr_arg jr_created < "$jr_job"
        jr_rc="$(cat "$jr_result" 2>/dev/null)"; case "$jr_rc" in ''|*[!0-9]*) jr_rc=2 ;; esac
        [ "$jr_rc" -eq 0 ] && jr_state=DONE || jr_state=FAILED
        status_write "$LAST" "id=$jr_id" "type=$jr_type" "arg=$jr_arg" "state=$jr_state" "rc=$jr_rc" "output=$JOBS/$jr_id.out" || return 1
        rm -f "$jr_job" "$jr_result"
        ads_log "JOB_RECOVER_RESULT|id=$jr_id|state=$jr_state|rc=$jr_rc"
    done
    for jr_job in "$RUNNING"/*.job; do
        [ -f "$jr_job" ] || continue
        jr_base="$(basename "$jr_job")"; [ -e "${jr_job%.job}.result" ] && continue
        mv "$jr_job" "$QUEUED/$jr_base" || return 1
        ads_log "JOB_RECOVER_REQUEUE|job=$jr_base"
    done
    rm -f "$CURRENT"
    if [ -s "$LEGACY_QUEUE" ]; then
        while IFS= read -r jr_line; do [ -n "$jr_line" ] && spool_line "$jr_line" || true; done < "$LEGACY_QUEUE"
        : > "$LEGACY_QUEUE" || return 1
        chmod 0600 "$LEGACY_QUEUE" 2>/dev/null || true
        ads_log "JOB_MIGRATE_LEGACY_QUEUE"
    fi
}

run_one()
{
    ads_lock_acquire "$LOCK" "${JOB_LOCK_STALE_SEC:-1800}" || { echo "JOB_WORKER=BUSY"; return 0; }
    trap 'ads_lock_release "$LOCK"' EXIT INT TERM
    recover_jobs || ads_die "cannot recover job spool"
    jw_job="$(find "$QUEUED" -type f -name '*.job' 2>/dev/null | sort | sed -n '1p')"
    [ -n "$jw_job" ] || { echo "JOB_WORKER=IDLE"; return 0; }
    jw_base="$(basename "$jw_job")"; jw_running="$RUNNING/$jw_base"
    mv "$jw_job" "$jw_running" || ads_die "cannot claim queued job"
    IFS='|' read -r jw_id jw_type jw_arg jw_created < "$jw_running"
    status_write "$CURRENT" "id=$jw_id" "type=$jw_type" "arg=$jw_arg" "state=RUNNING" "created_epoch=$jw_created" || ads_die "cannot persist running status"
    jw_rc=0; jw_out="$JOBS/$jw_id.out"
    case "$jw_type" in
        scan) jw_cmd="${VWARD_ADS_SCANNER:-/opt/bin/vward-ads-privacy-guard.sh}"; [ -x "$jw_cmd" ] || jw_cmd="$SELF_DIR/vward-ads-privacy-guard.sh"; "$jw_cmd" scan > "$jw_out" 2>&1 || jw_rc=$? ;;
        sources-update) jw_cmd="${VWARD_ADS_SOURCES_UPDATER:-/opt/bin/vward-ads-privacy-sources-update.sh}"; [ -x "$jw_cmd" ] || jw_cmd="$SELF_DIR/vward-ads-privacy-sources-update.sh"; "$jw_cmd" > "$jw_out" 2>&1 || jw_rc=$? ;;
        publish) jw_cmd="${VWARD_ADS_PUBLISHER:-/opt/bin/vward-ads-privacy-publish.sh}"; [ -x "$jw_cmd" ] || jw_cmd="$SELF_DIR/vward-ads-privacy-publish.sh"; "$jw_cmd" apply --confirm > "$jw_out" 2>&1 || jw_rc=$? ;;
        rules-rebuild) jw_cmd="${VWARD_ADS_RULES_REBUILD:-/opt/bin/vward-ads-privacy-rules-rebuild.sh}"; [ -x "$jw_cmd" ] || jw_cmd="$SELF_DIR/vward-ads-privacy-rules-rebuild.sh"; "$jw_cmd" > "$jw_out" 2>&1 || jw_rc=$? ;;
        probe) jw_cmd="${VWARD_ADS_PROBE:-/opt/bin/vward-ads-privacy-probe.sh}"; [ -x "$jw_cmd" ] || jw_cmd="$SELF_DIR/vward-ads-privacy-probe.sh"; "$jw_cmd" "$jw_arg" > "$jw_out" 2>&1 || jw_rc=$? ;;
        *) jw_rc=2; printf 'unsupported job type: %s\n' "$jw_type" > "$jw_out" ;;
    esac
    chmod 0600 "$jw_out" 2>/dev/null || true
    jw_result="$RUNNING/${jw_base%.job}.result"
    printf '%s\n' "$jw_rc" > "$jw_result" || ads_die "cannot persist job result"
    chmod 0600 "$jw_result" 2>/dev/null || true
    [ "$jw_rc" -eq 0 ] && jw_state=DONE || jw_state=FAILED
    status_write "$LAST" "id=$jw_id" "type=$jw_type" "arg=$jw_arg" "state=$jw_state" "rc=$jw_rc" "output=$jw_out" || ads_die "cannot persist completed status"
    rm -f "$CURRENT" "$jw_running" "$jw_result"
    ads_log "JOB_DONE|id=$jw_id|type=$jw_type|state=$jw_state|rc=$jw_rc"
    echo "JOB_WORKER=$jw_state"; echo "JOB_ID=$jw_id"; echo "JOB_RC=$jw_rc"
    return "$jw_rc"
}

case "${1:-status}" in
    enqueue) [ -n "${2:-}" ] || ads_die "job type required"; enqueue "$2" "${3:-}" ;;
    worker) run_one ;;
    status)
        echo "JOB_QUEUE=$(find "$QUEUED" -type f -name '*.job' 2>/dev/null | wc -l | tr -d ' ')"
        [ -r "$CURRENT" ] && sed 's/^/CURRENT_/' "$CURRENT" || echo "CURRENT_state=IDLE"
        [ -r "$LAST" ] && sed 's/^/LAST_/' "$LAST" || echo "LAST_state=NONE" ;;
    *) echo "Usage: $0 {enqueue TYPE [ARG]|worker|status}" >&2; exit 2 ;;
esac
