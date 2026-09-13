#!/bin/sh
# Lightweight single-worker queue for long VWARD Ads & Privacy Guard actions.
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "FAIL: common library not found" >&2; exit 1; }
. "$LIB"
ads_mkdirs || ads_die "cannot create component directories"
[ -r "$ADS_CONFIG" ] && ads_load_config

QUEUE="$ADS_STATE/jobs/queue"
CURRENT="$ADS_STATE/jobs/current.status"
LAST="$ADS_STATE/jobs/last.status"
LOCK="$ADS_STATE/jobs/worker.lock"
mkdir -p "$ADS_STATE/jobs" || ads_die "cannot create jobs directory"
[ -e "$QUEUE" ] || : > "$QUEUE"
chmod 0600 "$QUEUE" 2>/dev/null || true

job_valid_domain()
{
    jvd="$(ads_normalize_domain "${1:-}")"
    ads_valid_domain "$jvd" || return 1
    printf '%s\n' "$jvd"
}

status_write()
{
    js_file="$1"; shift
    js_tmp="$ADS_STATE/work/job-status.$$"
    {
        echo "ts=$(ads_now)"
        printf '%s\n' "$@"
    } > "$js_tmp" || return 1
    ads_atomic_copy "$js_tmp" "$js_file" 0600
    rm -f "$js_tmp"
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
    je_tmp="$ADS_STATE/work/jobs-queue.$$"
    cp "$QUEUE" "$je_tmp" || return 1
    printf '%s|%s|%s|%s\n' "$je_id" "$je_type" "$je_arg" "$(ads_epoch)" >> "$je_tmp" || return 1
    ads_atomic_copy "$je_tmp" "$QUEUE" 0600 || return 1
    rm -f "$je_tmp"
    ads_log "JOB_ENQUEUE|id=$je_id|type=$je_type|arg=$je_arg"
    echo "JOB=QUEUED"
    echo "JOB_ID=$je_id"
    echo "JOB_TYPE=$je_type"
    [ -n "$je_arg" ] && echo "JOB_ARG=$je_arg"
    return 0
}

run_one()
{
    [ -s "$QUEUE" ] || { echo "JOB_WORKER=IDLE"; return 0; }
    ads_lock_acquire "$LOCK" "${JOB_LOCK_STALE_SEC:-1800}" || { echo "JOB_WORKER=BUSY"; return 0; }
    trap 'ads_lock_release "$LOCK"' EXIT INT TERM

    jw_line="$(head -n 1 "$QUEUE")"
    jw_rest="$ADS_STATE/work/jobs-rest.$$"
    tail -n +2 "$QUEUE" > "$jw_rest" 2>/dev/null || : > "$jw_rest"
    ads_atomic_copy "$jw_rest" "$QUEUE" 0600 || ads_die "cannot advance job queue"
    rm -f "$jw_rest"
    IFS='|' read -r jw_id jw_type jw_arg jw_created <<EOJ
$jw_line
EOJ
    status_write "$CURRENT" "id=$jw_id" "type=$jw_type" "arg=$jw_arg" "state=RUNNING" "created_epoch=$jw_created" || true

    jw_rc=0
    jw_out="$ADS_STATE/jobs/$jw_id.out"
    case "$jw_type" in
        scan)
            jw_cmd="${VWARD_ADS_SCANNER:-/opt/bin/vward-ads-privacy-guard.sh}"; [ -x "$jw_cmd" ] || jw_cmd="$SELF_DIR/vward-ads-privacy-guard.sh"
            "$jw_cmd" scan > "$jw_out" 2>&1 || jw_rc=$? ;;
        sources-update)
            jw_cmd="${VWARD_ADS_SOURCES_UPDATER:-/opt/bin/vward-ads-privacy-sources-update.sh}"; [ -x "$jw_cmd" ] || jw_cmd="$SELF_DIR/vward-ads-privacy-sources-update.sh"
            "$jw_cmd" > "$jw_out" 2>&1 || jw_rc=$? ;;
        publish)
            jw_cmd="${VWARD_ADS_PUBLISHER:-/opt/bin/vward-ads-privacy-publish.sh}"; [ -x "$jw_cmd" ] || jw_cmd="$SELF_DIR/vward-ads-privacy-publish.sh"
            "$jw_cmd" apply --confirm > "$jw_out" 2>&1 || jw_rc=$? ;;
        rules-rebuild)
            jw_cmd="${VWARD_ADS_RULES_REBUILD:-/opt/bin/vward-ads-privacy-rules-rebuild.sh}"; [ -x "$jw_cmd" ] || jw_cmd="$SELF_DIR/vward-ads-privacy-rules-rebuild.sh"
            "$jw_cmd" > "$jw_out" 2>&1 || jw_rc=$? ;;
        probe)
            jw_cmd="${VWARD_ADS_PROBE:-/opt/bin/vward-ads-privacy-probe.sh}"; [ -x "$jw_cmd" ] || jw_cmd="$SELF_DIR/vward-ads-privacy-probe.sh"
            "$jw_cmd" "$jw_arg" > "$jw_out" 2>&1 || jw_rc=$? ;;
        *) jw_rc=2; printf 'unsupported job type: %s\n' "$jw_type" > "$jw_out" ;;
    esac
    chmod 0600 "$jw_out" 2>/dev/null || true
    if [ "$jw_rc" -eq 0 ]; then jw_state=DONE; else jw_state=FAILED; fi
    status_write "$LAST" "id=$jw_id" "type=$jw_type" "arg=$jw_arg" "state=$jw_state" "rc=$jw_rc" "output=$jw_out" || true
    rm -f "$CURRENT"
    ads_log "JOB_DONE|id=$jw_id|type=$jw_type|state=$jw_state|rc=$jw_rc"
    echo "JOB_WORKER=$jw_state"
    echo "JOB_ID=$jw_id"
    echo "JOB_RC=$jw_rc"
    return "$jw_rc"
}

case "${1:-status}" in
    enqueue) [ -n "${2:-}" ] || ads_die "job type required"; enqueue "$2" "${3:-}" ;;
    worker) run_one ;;
    status)
        echo "JOB_QUEUE=$(wc -l < "$QUEUE" 2>/dev/null | tr -d ' ')"
        [ -r "$CURRENT" ] && sed 's/^/CURRENT_/' "$CURRENT" || echo "CURRENT_state=IDLE"
        [ -r "$LAST" ] && sed 's/^/LAST_/' "$LAST" || echo "LAST_state=NONE"
        ;;
    *) echo "Usage: $0 {enqueue TYPE [ARG]|worker|status}" >&2; exit 2 ;;
esac
