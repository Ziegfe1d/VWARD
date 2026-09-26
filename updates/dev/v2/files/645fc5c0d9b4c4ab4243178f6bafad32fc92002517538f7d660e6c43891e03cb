#!/bin/sh
# Emits allowed, ordinary AdGuard Home queries as: domain<TAB>client<TAB>time
# Usage: vward-ads-privacy-query-read.sh [LINES] [window]
# "window" keeps the last LINES queries in RAM and asks AdGuard Home only for
# the ones newer than the previous call, so a scan does not make AdGuard Home
# decode its whole query log every time.
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "FAIL: common library not found" >&2; exit 1; }
. "$LIB"
ads_require "$ADS_JQ"
[ -r "$ADS_CONFIG" ] && ads_load_config
LINES="$(ads_num "${1:-${SCAN_TAIL_LINES:-20000}}" 20000)"
MODE="${2:-}"
QUERY_SOURCE="${QUERY_SOURCE:-auto}"
case "$QUERY_SOURCE" in auto|api|file) ;; *) ads_die "QUERY_SOURCE must be auto, api or file" ;; esac

read_api() (
    qr_tmp="${TMPDIR:-/tmp}/vward-ads-query-api.$$"
    trap 'rm -f "$qr_tmp"' EXIT
    trap 'exit 1' HUP INT TERM
    ads_agh_api_get "querylog?limit=$LINES&response_status=all" "$qr_tmp" || return 1
    "$ADS_JQ" -e '.data | type=="array"' "$qr_tmp" >/dev/null 2>&1 || return 1
    "$ADS_JQ" -r '
      .data[]? |
      select((.reason // "") == "NotFilteredNotFound") |
      [(.question.name // ""), (.client // "UNKNOWN"), (.time // "UNKNOWN")] | @tsv
    ' "$qr_tmp" 2>/dev/null
)

# Pages newest first until the newest query of the previous call; the window
# holds domain, client, time and 1 for an allowed query, oldest first.
read_api_window() (
    qw_dir="${VWARD_ADS_QUERY_WINDOW_DIR:-${TMPDIR:-/tmp}/vward-ads-query-window}"
    umask 077
    [ ! -L "$qw_dir" ] && mkdir -p "$qw_dir" 2>/dev/null && chmod 700 "$qw_dir" || return 1
    qw_page="$(ads_num "${VWARD_ADS_QUERY_PAGE:-500}" 500)"
    [ "$qw_page" -gt 0 ] || qw_page=500
    qw_tmp="$qw_dir/page.$$"; qw_new="$qw_dir/new.$$"
    trap 'rm -f "$qw_tmp" "$qw_new" "$qw_dir/window.$$"' EXIT
    trap 'exit 1' HUP INT TERM
    qw_cursor=""
    [ -s "$qw_dir/window.tsv" ] && qw_cursor="$(sed -n '1p' "$qw_dir/cursor" 2>/dev/null)"
    : > "$qw_new"
    qw_older=""; qw_newest=""; qw_found=0; qw_seen=0; qw_calls=0
    while [ "$qw_seen" -lt "$LINES" ] && [ "$qw_calls" -lt $((LINES / qw_page + 2)) ]; do
        qw_q="querylog?limit=$qw_page&response_status=all"
        [ -z "$qw_older" ] || qw_q="$qw_q&older_than=$(printf '%s' "$qw_older" | sed 's/+/%2B/g')"
        ads_agh_api_get "$qw_q" "$qw_tmp" || return 1
        qw_calls=$((qw_calls + 1))
        # count|cursor position on this page (-1: not here)|oldest|first time
        qw_meta="$("$ADS_JQ" -r --arg cur "$qw_cursor" '
          select(.data | type=="array") |
          [(.data | length),
           (if $cur == "" then -1 else ((.data | map(.time // "") | index($cur)) // -1) end),
           (.oldest // ""), (.data[0].time // "")] | map(tostring) | join("|")' "$qw_tmp" 2>/dev/null)" || return 1
        [ -n "$qw_meta" ] || return 1
        IFS='|' read -r qw_count qw_at qw_oldest qw_first <<EOF_META
$qw_meta
EOF_META
        [ -n "$qw_newest" ] || qw_newest="$qw_first"
        "$ADS_JQ" -r --argjson at "$qw_at" '
          (if $at >= 0 then .data[:$at] else .data end)[] |
          [(.question.name // ""), (.client // "UNKNOWN"), (.time // "UNKNOWN"),
           (if (.reason // "") == "NotFilteredNotFound" then 1 else 0 end)] | @tsv
        ' "$qw_tmp" >> "$qw_new" 2>/dev/null || return 1
        if [ "$qw_at" -ge 0 ]; then qw_found=1; break; fi
        qw_seen=$((qw_seen + qw_count))
        [ "$qw_count" -gt 0 ] && [ -n "$qw_oldest" ] && [ "$qw_oldest" != "$qw_older" ] || break
        qw_older="$qw_oldest"
    done
    {
        [ "$qw_found" = 1 ] && cat "$qw_dir/window.tsv"
        awk '{ l[NR] = $0 } END { for (i = NR; i > 0; i--) print l[i] }' "$qw_new"
    } | tail -n "$LINES" > "$qw_dir/window.$$" || return 1
    mv -f "$qw_dir/window.$$" "$qw_dir/window.tsv" || return 1
    [ -z "$qw_newest" ] || printf '%s\n' "$qw_newest" > "$qw_dir/cursor"
    awk -F'\t' '$4 == 1 { print $1 "\t" $2 "\t" $3 }' "$qw_dir/window.tsv"
)

read_file_one() (
    qr_file="$1"; qr_lines="$2"
    [ -r "$qr_file" ] || return 0
    tail -n "$qr_lines" "$qr_file" 2>/dev/null |
    "$ADS_JQ" -r '
      select(.Result.IsFiltered != true) |
      select(((.Result.Reason // .Reason // "NotFilteredNotFound") == "NotFilteredNotFound")) |
      [(.QH // ""), (.IP // "UNKNOWN"), (.T // "UNKNOWN")] | @tsv
    ' 2>/dev/null
)

if [ "$QUERY_SOURCE" != file ] && [ "$MODE" = window ]; then
    if read_api_window; then
        exit 0
    fi
    # A failed page leaves the saved window as it was; fall through to a full read.
fi
if [ "$QUERY_SOURCE" != file ]; then
    if read_api; then
        exit 0
    fi
    [ "$QUERY_SOURCE" = auto ] || exit 3
fi
HALF=$((LINES / 2)); [ "$HALF" -gt 0 ] || HALF=1
read_file_one "$ADS_QUERYLOG_OLD" "$HALF"
read_file_one "$ADS_QUERYLOG" "$HALF"
