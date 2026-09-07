#!/bin/sh

set -u

SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SELF_DIR/vward-update-common.sh"
vu_load_config

[ "$update_enabled" = 1 ] || exit "$VU_OK"

case "${1:-}" in
    --once) watch_once=1 ;;
    '') watch_once=0 ;;
    *) vu_die "$VU_CONFIG_ERROR" "Usage: vward-update-watch.sh [--once]" ;;
esac

run_once() {
    [ -n "$manifest_url" ] || return "$VU_CONFIG_ERROR"
    mkdir -p "$VU_STAGING_DIR" || return "$VU_INSTALL_ERROR"
    local_manifest=$VU_STAGING_DIR/watcher-manifest.json
    headers=$VU_STAGING_DIR/watcher-headers.$$
    body=$local_manifest.part.$$
    etag=$(vu_state_get manifest_etag "$VU_STATE_DIR/watcher.state" 2>/dev/null || :)
    if [ -n "$VU_ROOT_PREFIX" ] && [ -n "${VWARD_TEST_HTTP_STATUS:-}" ]; then
        status=$VWARD_TEST_HTTP_STATUS
        : > "$headers"
        if [ "$status" = 200 ]; then
            cp "$VWARD_TEST_WATCH_MANIFEST" "$body" || return "$VU_VERIFY_ERROR"
        else
            : > "$body"
        fi
    elif [ -n "$etag" ]; then
        status=$(curl --silent --show-error --location --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 60 \
            --dump-header "$headers" --output "$body" --write-out '%{http_code}' --header "If-None-Match: $etag" "$manifest_url") || return "$VU_VERIFY_ERROR"
    else
        status=$(curl --silent --show-error --location --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 60 \
            --dump-header "$headers" --output "$body" --write-out '%{http_code}' "$manifest_url") || return "$VU_VERIFY_ERROR"
    fi
    case "$status" in
        304)
            rm -f "$headers" "$body"
            vu_log INFO "Manifest unchanged; reevaluating pending update"
            process_pending
            pending_result=$?
            case "$pending_result" in
                "$VU_NO_UPDATE"|"$VU_VERIFY_ERROR"|"$VU_COMPAT_ERROR")
                    rm -f "$VU_STATE_DIR/watcher.state"
                    vu_log WARN "Pending cache is unavailable or invalid; ETag cleared for refetch"
                    return "$VU_VERIFY_ERROR"
                    ;;
                *) return "$pending_result" ;;
            esac
            ;;
        200) ;;
        *) rm -f "$headers" "$body"; vu_log WARN "Manifest HTTP status: $status"; return "$VU_VERIFY_ERROR" ;;
    esac
    mv -f "$body" "$local_manifest" || return "$VU_INSTALL_ERROR"
    new_etag=$(sed -n 's/^[Ee][Tt][Aa][Gg]:[[:space:]]*//p' "$headers" | tr -d '\r' | tail -n 1)
    rm -f "$headers"
    VWARD_LOCAL_MANIFEST=$local_manifest "$SELF_DIR/vward-update.sh" --check || return $?
    [ -z "$new_etag" ] || vu_state_set manifest_etag "$new_etag" "$VU_STATE_DIR/watcher.state" || return "$VU_INSTALL_ERROR"
    rm -f "$local_manifest"
    process_pending
}

process_pending() {
    [ -r "$VU_PENDING_DIR/pending.state" ] && [ -r "$VU_PENDING_DIR/manifest.json" ] || return "$VU_NO_UPDATE"
    priority=$(vu_pending_get priority 2>/dev/null || return "$VU_VERIFY_ERROR")
    first_seen=$(vu_pending_get first_seen_at 2>/dev/null || return "$VU_VERIFY_ERROR")
    vu_auto_allowed "$priority" || { vu_log INFO "Pending $priority update is not enabled for automatic apply"; return "$VU_OK"; }
    [ "$barrier_integration_ready" = 1 ] || { vu_log WARN "Automatic apply blocked: barrier integration is not ready"; return "$VU_DEFERRED"; }
    vu_schedule_ready "$priority" "$first_seen" || { vu_log INFO "Pending $priority update is waiting for its window"; return "$VU_DEFERRED"; }
    "$SELF_DIR/vward-update.sh" --apply-pending
}

while :; do
    attempt=0
    delay=1
    result=$VU_OK
    while [ "$attempt" -lt 4 ]; do
        run_once
        result=$?
        if [ "$result" -eq "$VU_OK" ]; then
            break
        fi
        attempt=$((attempt + 1))
        [ "$attempt" -ge 4 ] && break
        sleep "$delay"
        delay=$((delay * 2))
    done
    [ "$watch_once" = 1 ] && exit "$result"
    sleep "$check_interval_seconds"
done
