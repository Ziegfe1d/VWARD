#!/bin/sh
# Emits allowed, ordinary AdGuard Home queries as: domain<TAB>client<TAB>time
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
QUERY_SOURCE="${QUERY_SOURCE:-auto}"
case "$QUERY_SOURCE" in auto|api|file) ;; *) ads_die "QUERY_SOURCE must be auto, api or file" ;; esac

read_api() (
    qr_tmp="${TMPDIR:-/tmp}/vward-ads-query-api.$$"
    trap 'rm -f "$qr_tmp"' EXIT INT TERM
    ads_agh_api_get "querylog?limit=$LINES&response_status=all" "$qr_tmp" || return 1
    "$ADS_JQ" -e '.data | type=="array"' "$qr_tmp" >/dev/null 2>&1 || return 1
    "$ADS_JQ" -r '
      .data[]? |
      select((.reason // "") == "NotFilteredNotFound") |
      [(.question.name // ""), (.client // "UNKNOWN"), (.time // "UNKNOWN")] | @tsv
    ' "$qr_tmp" 2>/dev/null
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

if [ "$QUERY_SOURCE" != file ]; then
    if read_api; then
        exit 0
    fi
    [ "$QUERY_SOURCE" = auto ] || exit 3
fi
HALF=$((LINES / 2)); [ "$HALF" -gt 0 ] || HALF=1
read_file_one "$ADS_QUERYLOG_OLD" "$HALF"
read_file_one "$ADS_QUERYLOG" "$HALF"
