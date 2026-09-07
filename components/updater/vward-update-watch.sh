#!/bin/sh

set -u

SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SELF_DIR/vward-update-common.sh"
vu_load_config

[ "$update_enabled" = 1 ] || exit "$VU_OK"

case "${1:-}" in --once) watch_once=1 ;; '') watch_once=0 ;; *) vu_die "$VU_CONFIG_ERROR" "Usage: vward-update-watch.sh [--once]" ;; esac

process_pending() {
    [ -r "$VU_PENDING_DIR/pending.state" ] && [ -r "$VU_PENDING_DIR/manifest.json" ] || return "$VU_NO_UPDATE"
    manifest=$VU_PENDING_DIR/manifest.json
    if vu_quarantine_matches "$manifest"; then
        vu_log WARN "Pending update is quarantined; unattended retry suppressed"
        return "$VU_QUARANTINED"
    fi
    priority=$(vu_pending_get priority 2>/dev/null || return "$VU_VERIFY_ERROR")
    first_seen=$(vu_pending_get first_seen_at 2>/dev/null || return "$VU_VERIFY_ERROR")
    vu_auto_allowed "$priority" || { vu_log INFO "Pending $priority update is not enabled for automatic apply"; return "$VU_OK"; }
    [ "$barrier_integration_ready" = 1 ] || { vu_log INFO "Automatic apply blocked: barrier integration is not ready"; return "$VU_DEFERRED"; }
    vu_schedule_ready "$priority" "$first_seen" || { vu_log INFO "Pending $priority update is waiting for its window"; return "$VU_DEFERRED"; }
    "$SELF_DIR/vward-update.sh" --apply-pending
}

http_fetch_manifest() {
    headers=$1; body=$2; etag=$3
    if [ -n "$VU_ROOT_PREFIX" ] && [ -n "${VWARD_TEST_HTTP_STATUS:-}" ]; then
        if [ -n "${VWARD_TEST_WATCH_COUNTER:-}" ]; then
            n=$(sed -n '1p' "$VWARD_TEST_WATCH_COUNTER" 2>/dev/null || printf 0)
            printf '%s\n' "$((n+1))" > "$VWARD_TEST_WATCH_COUNTER"
        fi
        status=$VWARD_TEST_HTTP_STATUS
        : > "$headers"
        if [ -n "${VWARD_TEST_ETAG:-}" ]; then printf 'ETag: %s\r\n' "$VWARD_TEST_ETAG" > "$headers"; fi
        if [ "$status" = 200 ]; then
            cp "$VWARD_TEST_WATCH_MANIFEST" "$body" || return "$VU_VERIFY_ERROR"
            size=$(wc -c < "$body" | tr -d ' ')
            [ "$size" -le "$max_manifest_size" ] || return "$VU_VERIFY_ERROR"
        else
            : > "$body"
        fi
        printf '%s\n' "$status"
        return 0
    fi
    if [ -n "$etag" ]; then
        status=$(curl --silent --show-error --location --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 60 --max-filesize "$max_manifest_size" \
            --dump-header "$headers" --output "$body" --write-out '%{http_code}' --header "If-None-Match: $etag" "$manifest_url") || return "$VU_NETWORK_ERROR"
    else
        status=$(curl --silent --show-error --location --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 60 --max-filesize "$max_manifest_size" \
            --dump-header "$headers" --output "$body" --write-out '%{http_code}' "$manifest_url") || return "$VU_NETWORK_ERROR"
    fi
    if [ -f "$body" ]; then size=$(wc -c < "$body" | tr -d ' '); [ "$size" -le "$max_manifest_size" ] || return "$VU_VERIFY_ERROR"; fi
    printf '%s\n' "$status"
}

run_once() {
    [ -n "$manifest_url" ] || return "$VU_CONFIG_ERROR"
    mkdir -p "$VU_STAGING_DIR" || return "$VU_INSTALL_ERROR"
    local_manifest=$VU_STAGING_DIR/watcher-manifest.json
    headers=$VU_STAGING_DIR/watcher-headers.$$
    body=$local_manifest.part.$$
    etag=$(vu_state_get manifest_etag "$VU_STATE_DIR/watcher.state" 2>/dev/null || :)
    status=$(http_fetch_manifest "$headers" "$body" "$etag")
    fetch_code=$?
    [ "$fetch_code" -eq 0 ] || { rm -f "$headers" "$body"; return "$fetch_code"; }
    case "$status" in
        304)
            rm -f "$headers" "$body"
            process_pending
            pending_result=$?
            case "$pending_result" in
                "$VU_OK"|"$VU_NO_UPDATE")
                    vu_log INFO "Manifest unchanged; no actionable pending update"
                    return "$VU_OK" ;;
                "$VU_DEFERRED"|"$VU_QUARANTINED"|"$VU_VERIFY_ERROR"|"$VU_COMPAT_ERROR"|"$VU_SAFETY_ERROR"|"$VU_INSTALL_ERROR"|"$VU_HEALTH_ERROR"|"$VU_ROLLBACK_ERROR") return "$pending_result" ;;
                *) return "$pending_result" ;;
            esac ;;
        200) ;;
        408|425|429|500|502|503|504) rm -f "$headers" "$body"; return "$VU_NETWORK_ERROR" ;;
        *) rm -f "$headers" "$body"; vu_log WARN "Manifest HTTP status: $status"; return "$VU_VERIFY_ERROR" ;;
    esac
    mv -f "$body" "$local_manifest" || return "$VU_INSTALL_ERROR"
    new_etag=$(sed -n 's/^[Ee][Tt][Aa][Gg]:[[:space:]]*//p' "$headers" | tr -d '\r' | tail -n 1)
    rm -f "$headers"
    VWARD_LOCAL_MANIFEST=$local_manifest "$SELF_DIR/vward-update.sh" --check
    check_result=$?
    case "$check_result" in
        "$VU_OK")
            [ -z "$new_etag" ] || vu_state_set manifest_etag "$new_etag" "$VU_STATE_DIR/watcher.state" || return "$VU_INSTALL_ERROR"
            rm -f "$local_manifest"
            process_pending
            return $? ;;
        "$VU_NO_UPDATE")
            [ -z "$new_etag" ] || vu_state_set manifest_etag "$new_etag" "$VU_STATE_DIR/watcher.state" || return "$VU_INSTALL_ERROR"
            rm -f "$local_manifest"
            vu_log INFO "Feed points to the already installed update"
            return "$VU_OK" ;;
        *) rm -f "$local_manifest"; return "$check_result" ;;
    esac
}

while :; do
    attempt=0; result=$VU_OK
    while :; do
        run_once; result=$?
        [ "$result" -eq "$VU_NETWORK_ERROR" ] || break
        attempt=$((attempt+1))
        [ "$attempt" -ge 4 ] && break
        delay=$((1 << (attempt-1)))
        sleep "$delay"
    done
    [ "$watch_once" = 1 ] && exit "$result"
    sleep "$check_interval_seconds"
done
