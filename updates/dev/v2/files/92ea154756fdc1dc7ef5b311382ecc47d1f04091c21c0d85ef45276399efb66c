#!/bin/sh
# Read-only views of VWARD Ads & Privacy Guard for the Console. Prints JSON.
#   querylog all|blocked|allowed|review [SEARCH] [LIMIT]  AdGuard Home query log
#   stats                                                  AdGuard Home counters for the day
#   list review|blocked [SEARCH]                           domains from the verdict state
#   publish-status                                         rules not yet published
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo '{"ok":false,"error":"ads_library_unavailable"}'; exit 1; }
. "$LIB"
[ -x "$ADS_JQ" ] || { echo '{"ok":false,"error":"jq_unavailable"}'; exit 1; }
[ -r "$ADS_CONFIG" ] && ads_load_config

VERDICTS="$ADS_STATE/verdicts.tsv"
RULES="$ADS_STATE/generated/vward-ads-privacy-guard.rules"
PUBLISHED="$ADS_STATE/published.rules"
TMP=""
cleanup() { [ -z "$TMP" ] || rm -f "$TMP" "$TMP.v"; }
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

fail() { printf '{"ok":false,"error":"%s"}\n' "$1"; exit 0; }
search_ok() { case "$1" in *[!a-z0-9.-]*) return 1 ;; esac; [ "${#1}" -le 100 ]; }

# Why AdGuard Home did not answer: no address in the profile, a login is needed, or it is down.
agh_fail() {
    [ "$1" = 2 ] && fail adguard_not_configured
    if [ "$1" = 22 ]; then
        code=$("$ADS_CURL" -s -o /dev/null -w '%{http_code}' --connect-timeout 3 --max-time 5 "$(ads_agh_api_base)/status" 2>/dev/null)
        case "$code" in 401|403) fail adguard_auth_required ;; esac
    fi
    fail adguard_unavailable
}

new_tmp() { TMP=$(mktemp "${TMPDIR:-/tmp}/vward-ads-view.XXXXXX" 2>/dev/null) || fail temporary_file_unavailable; }

# Verdict map for the query log: domain -> verdict/action.
verdict_json() {
    if [ -r "$VERDICTS" ]; then
        awk -F'|' 'NF>=3 {print $1 "\t" $2 "\t" $3}' "$VERDICTS" |
            "$ADS_JQ" -Rn '[inputs | split("\t") | {(.[0]): {verdict: .[1], action: .[2]}}] | add // {}'
    else
        echo '{}'
    fi
}

case "${1:-}" in
    querylog)
        FILTER=${2:-all}; SEARCH=$(printf '%s' "${3:-}" | tr 'A-Z' 'a-z'); LIMIT=$(ads_num "${4:-}" 100)
        case "$FILTER" in all) STATUS=all ;; blocked) STATUS=blocked ;; allowed) STATUS=processed ;; review) STATUS=all ;; *) fail invalid_filter ;; esac
        search_ok "$SEARCH" || fail invalid_search
        [ "$LIMIT" -ge 1 ] && [ "$LIMIT" -le 500 ] || LIMIT=100
        new_tmp
        QUERY="querylog?limit=$LIMIT&response_status=$STATUS"
        [ -z "$SEARCH" ] || QUERY="$QUERY&search=$SEARCH"
        ads_agh_api_get "$QUERY" "$TMP" >/dev/null 2>&1 || agh_fail $?
        "$ADS_JQ" -e '.data | type == "array"' "$TMP" >/dev/null 2>&1 || fail adguard_unavailable
        # The verdicts go as a file: with a few thousand domains they pass the
        # 128 KB a single argument may hold, and jq would not start at all.
        verdict_json > "$TMP.v" || fail temporary_file_unavailable
        "$ADS_JQ" -c --slurpfile vs "$TMP.v" --arg filter "$FILTER" '
            $vs[0] as $v |
            [.data[]? | {
                time: (.time // ""), client: (.client // ""),
                domain: ((.question.name // "") | ascii_downcase | rtrimstr(".")),
                blocked: ((.reason // "") | IN("FilteredBlackList", "FilteredSafeBrowsing", "FilteredParental", "FilteredBlockedService", "FilteredInvalid")),
                reason: (.reason // "")
              } | . + {verdict: ($v[.domain].verdict // ""), vward_block: (($v[.domain].action // "") == "BLOCK")}
              | select($filter != "review" or .verdict == "SUSPECT")]
            | {ok: true, filter: $filter, entries: .}' "$TMP"
        ;;
    stats)
        new_tmp
        ads_agh_api_get "stats" "$TMP" >/dev/null 2>&1 || agh_fail $?
        "$ADS_JQ" -c '{ok: true,
            queries: (.num_dns_queries // 0), blocked: (.num_blocked_filtering // 0),
            avg_ms: (((.avg_processing_time // 0) * 1000) | floor),
            top_blocked: [(.top_blocked_domains // [])[:5][] | to_entries[0] | {domain: .key, count: .value}]}' "$TMP" 2>/dev/null ||
            fail adguard_unavailable
        ;;
    list)
        KIND=${2:-}; SEARCH=$(printf '%s' "${3:-}" | tr 'A-Z' 'a-z')
        case "$KIND" in review|blocked) ;; *) fail invalid_list ;; esac
        search_ok "$SEARCH" || fail invalid_search
        [ -r "$VERDICTS" ] || { printf '{"ok":true,"kind":"%s","total":0,"entries":[]}\n' "$KIND"; exit 0; }
        awk -F'|' -v k="$KIND" -v s="$SEARCH" '
            (k == "review" && $2 == "SUSPECT") || (k == "blocked" && $3 == "BLOCK") {
                if (s != "" && index($1, s) == 0) next
                print $1 "\t" $2 "\t" $3 "\t" $4 "\t" $6 "\t" $8
            }' "$VERDICTS" |
        "$ADS_JQ" -Rnc --arg kind "$KIND" '[inputs | split("\t") | {domain: .[0], verdict: .[1], action: .[2], confidence: .[3], last_seen: .[4], reason: .[5]}]
            | {ok: true, kind: $kind, total: length, entries: (sort_by(.last_seen) | reverse | .[:200])}'
        ;;
    publish-status)
        rules() { [ ! -r "$1" ] || awk 'NF && $0 !~ /^[!#]/' "$1"; }
        # One stream: "P rule" for published, "G rule" for generated.
        COUNTS=$({ rules "$PUBLISHED" | sed 's/^/P /'; rules "$RULES" | sed 's/^/G /'; } |
            awk '{r = substr($0, 3)} $1 == "P" {p[r] = 1} $1 == "G" {g[r] = 1}
                 END {for (r in g) if (!(r in p)) a++; for (r in p) if (!(r in g)) d++; print a+0, d+0}')
        ADDED=${COUNTS% *}; REMOVED=${COUNTS#* }
        printf '{"ok":true,"published":%s,"added":%s,"removed":%s,"mode":"%s","auto_publish":%s}\n' \
            "$([ -r "$PUBLISHED" ] && echo true || echo false)" "$ADDED" "$REMOVED" \
            "$(printf '%s' "${PUBLISH_MODE:-staged}" | tr -cd 'a-z_')" "$(ads_bool "${AUTO_PUBLISH:-0}" && echo true || echo false)"
        ;;
    agh)
        # Everything AdGuard Home does about ads, for the Ads page. Optional parts
        # (older or newer API) are null when the endpoint does not exist.
        D=$(mktemp -d "${TMPDIR:-/tmp}/vward-ads-agh.XXXXXX" 2>/dev/null) || fail temporary_file_unavailable
        TMP=$D/x
        get() { ads_agh_api_get "$1" "$D/$2" >/dev/null 2>&1 || { rm -f "$D/$2"; return 1; }; }
        get status status.json; rc=$?
        [ "$rc" = 0 ] || { ads_agh_api_get status "$D/x" >/dev/null 2>&1; r=$?; rm -rf "${D:?}"; agh_fail "$r"; }
        get filtering/status filtering.json
        get blocked_services/all services-all.json || get blocked_services/services services-old.json
        get blocked_services/get services-get.json || get blocked_services/list services-list.json
        get safebrowsing/status safebrowsing.json
        get parental/status parental.json
        get safesearch/status safesearch.json
        # Answers go to jq as files: the service list carries icons and the
        # filter status the user rules, far beyond the 128 KB one argument may hold.
        for f in status filtering services-all services-old services-get services-list safebrowsing parental safesearch; do
            [ -s "$D/$f.json" ] || echo null > "$D/$f.json"
        done
        "$ADS_JQ" -cn --slurpfile st "$D/status.json" --slurpfile fl "$D/filtering.json" \
            --slurpfile sall "$D/services-all.json" --slurpfile sold "$D/services-old.json" \
            --slurpfile sget "$D/services-get.json" --slurpfile slist "$D/services-list.json" \
            --slurpfile sb "$D/safebrowsing.json" --slurpfile pc "$D/parental.json" --slurpfile ss "$D/safesearch.json" '
            $st[0] as $st | $fl[0] as $fl | $sall[0] as $sall | $sold[0] as $sold | $sget[0] as $sget |
            $slist[0] as $slist | $sb[0] as $sb | $pc[0] as $pc | $ss[0] as $ss |
            def filters($f): [($f // [])[] | {id, name: (.name // ""), url: (.url // ""), enabled: (.enabled == true),
                rules: (.rules_count // 0), updated: (.last_updated // "")}];
            {ok: true, version: ($st.version // ""), protection: ($st.protection_enabled == true),
             filtering: (if $fl == null then null else {enabled: ($fl.enabled == true), interval: ($fl.interval // 24),
                 filters: filters($fl.filters), allow_filters: filters($fl.whitelist_filters), user_rules: (($fl.user_rules // []) | length)} end),
             services: (if $sall == null and $sold == null then null else
                 {available: [(($sall.blocked_services // $sold // [])[]) | {id, name: (.name // .id)}] | sort_by(.name | ascii_downcase),
                  blocked: (if $sget != null then ($sget.ids // []) else ($slist // []) end)} end),
             safebrowsing: (if $sb == null then null else ($sb.enabled == true) end),
             parental: (if $pc == null then null else ($pc.enabled == true) end),
             safesearch: (if $ss == null then null else ($ss.enabled == true) end)}' 2>/dev/null || { rm -rf "${D:?}"; fail adguard_unavailable; }
        rm -rf "${D:?}"
        ;;
    *)
        fail invalid_view
        ;;
esac
