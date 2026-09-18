#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "FAIL: common library not found" >&2; exit 1; }
. "$LIB"

DOMAIN="$(ads_normalize_domain "${1:-}")"
[ -n "$DOMAIN" ] || { echo "Usage: $0 domain" >&2; exit 2; }
ads_valid_domain "$DOMAIN" || ads_die "invalid domain"

ads_mkdirs || ads_die "cannot create component directories"
[ -r "$ADS_CONFIG" ] && ads_load_config

VERDICTS="$ADS_STATE/verdicts.tsv"
WORK="/tmp/vward-ads-probe.$$"
mkdir -p "$WORK" || ads_die "cannot create work directory"
trap 'rm -rf "$WORK"' EXIT
trap 'exit 1' HUP INT TERM

echo "============================================================"
echo " VWARD ADS & PRIVACY GUARD DOMAIN PROBE"
echo " DOMAIN=$DOMAIN"
echo " DATE=$(ads_now)"
echo "============================================================"

echo
echo "=== 1. LOCAL OVERRIDES / TRUST ==="
if ads_allowlist_match "$DOMAIN"; then echo "ALLOWLIST=MATCH"; else echo "ALLOWLIST=NO_MATCH"; fi
if ads_denylist_match "$DOMAIN"; then echo "DENYLIST=MATCH"; else echo "DENYLIST=NO_MATCH"; fi
TRUST_HIT="$(ads_trust_match_file "$DOMAIN" "$ADS_TRUST_BUILTIN")"
if [ -n "$TRUST_HIT" ]; then
    echo "TRUST=MATCH"
    echo "TRUST_RECORD=$TRUST_HIT"
else
    echo "TRUST=NO_MATCH"
fi

echo
echo "=== 2. CURRENT VERDICT ==="
STATE_LINE="$(awk -F'|' -v d="$DOMAIN" '$1==d {print; exit}' "$VERDICTS" 2>/dev/null)"
if [ -n "$STATE_LINE" ]; then
    echo "$STATE_LINE"
else
    echo "VERDICT=NOT_CLASSIFIED"
fi

echo
echo "=== 3. EVIDENCE SOURCE MATCHES ==="
KEY="$DOMAIN"
: > "$WORK/keys"
N=0
while [ "$N" -lt 8 ]; do
    case "$KEY" in
        *.*)
            echo "$KEY" >> "$WORK/keys"
            KEY="${KEY#*.}"
            ;;
        *) break ;;
    esac
    N=$((N + 1))
done
sort -u "$WORK/keys" -o "$WORK/keys"

MATCH_COUNT=0
if [ -r "$ADS_SOURCE_REGISTRY" ] && [ -x "$ADS_JQ" ]; then
    for SID in $("$ADS_JQ" -r '.sources[].id' "$ADS_SOURCE_REGISTRY" 2>/dev/null); do
        MODE="$(ads_source_mode "$SID")"
        [ "$MODE" != off ] || continue
        SRC="$ADS_STATE/sources/$SID.domains"
        [ -s "$SRC" ] || continue
        HIT="$(comm -12 "$WORK/keys" "$SRC" | head -n 1)"
        [ -n "$HIT" ] || continue
        EXC="$ADS_STATE/sources/$SID.exceptions"
        EXC_HIT=""
        [ -s "$EXC" ] && EXC_HIT="$(comm -12 "$WORK/keys" "$EXC" | head -n 1)"
        if [ -n "$EXC_HIT" ]; then
            echo "$SID|mode=$MODE|blocked_match=$HIT|exception=$EXC_HIT|effective=NO_MATCH"
            continue
        fi
        NAME="$("$ADS_JQ" -r --arg id "$SID" '.sources[] | select(.id==$id) | .name' "$ADS_SOURCE_REGISTRY")"
        GROUP="$("$ADS_JQ" -r --arg id "$SID" '.sources[] | select(.id==$id) | (.independence_group // .vendor)' "$ADS_SOURCE_REGISTRY")"
        WEIGHT="$("$ADS_JQ" -r --arg id "$SID" '.sources[] | select(.id==$id) | (.weight // 0)' "$ADS_SOURCE_REGISTRY")"
        PURPOSE="$("$ADS_JQ" -r --arg id "$SID" '.sources[] | select(.id==$id) | .purpose' "$ADS_SOURCE_REGISTRY")"
        SINGLE="$("$ADS_JQ" -r --arg id "$SID" '.sources[] | select(.id==$id) | (.single_source_block // false)' "$ADS_SOURCE_REGISTRY")"
        echo "$SID|mode=$MODE|match=$HIT|group=$GROUP|weight=$WEIGHT|single=$SINGLE|purpose=$PURPOSE|name=$NAME"
        MATCH_COUNT=$((MATCH_COUNT + 1))
    done
fi
echo "SOURCE_MATCH_COUNT=$MATCH_COUNT"

echo
echo "=== 4. ADGUARD HOME ALLOWED HISTORY ==="
: > "$WORK/history"
QUERY_READER="${VWARD_ADS_QUERY_READER:-/opt/bin/vward-ads-privacy-query-read.sh}"
[ -x "$QUERY_READER" ] || QUERY_READER="$SELF_DIR/vward-ads-privacy-query-read.sh"
if [ -x "$QUERY_READER" ]; then
    QUERY_SOURCE="${QUERY_SOURCE:-auto}" "$QUERY_READER" "${PROBE_TAIL_LINES:-20000}" 2>/dev/null |
      awk -F'\t' -v d="$DOMAIN" 'tolower($1)==d {print $3 "\t" $2 "\tALLOWED"}' >> "$WORK/history"
fi
HISTORY_COUNT="$(wc -l < "$WORK/history" 2>/dev/null | tr -d ' ')"; HISTORY_COUNT="$(ads_num "$HISTORY_COUNT" 0)"
echo "QUERY_COUNT=$HISTORY_COUNT"
if [ "$HISTORY_COUNT" -gt 0 ]; then
    echo "UNIQUE_CLIENTS=$(cut -f2 "$WORK/history" | sort -u | wc -l | tr -d ' ')"
    echo "FIRST=$(head -n 1 "$WORK/history" | cut -f1)"
    echo "LAST=$(tail -n 1 "$WORK/history" | cut -f1)"
    echo "CLIENTS:"; cut -f2 "$WORK/history" | sort | uniq -c | sort -nr | head -n 20
fi

echo
echo "=== 5. DNS RESOLUTION ==="
if command -v nslookup >/dev/null 2>&1; then
    if [ -n "${DNS_PROBE_SERVER:-}" ]; then
        nslookup "$DOMAIN" "$DNS_PROBE_SERVER" 2>&1 | head -n 30
    else
        nslookup "$DOMAIN" 2>&1 | head -n 30
    fi
else
    echo "DNS_PROBE=UNAVAILABLE"
fi

echo
echo "=== 6. OPTIONAL RDAP ==="
if ads_bool "${RDAP_ENABLED:-0}" && [ -x "$ADS_CURL" ] && [ -x "$ADS_JQ" ]; then
    "$ADS_CURL" -4 -f -L --connect-timeout 5 --max-time 12 -sS \
        "https://rdap.org/domain/$DOMAIN" -o "$WORK/rdap.json" 2>/dev/null
    RDAP_RC=$?
    echo "RDAP_RC=$RDAP_RC"
    if [ "$RDAP_RC" -eq 0 ]; then
        "$ADS_JQ" -r '
          "HANDLE=" + (.handle // ""),
          "STATUS=" + ((.status // []) | join(",")),
          (.events[]? | select(.eventAction=="registration" or .eventAction=="last changed") | "EVENT=" + .eventAction + "|" + (.eventDate // ""))
        ' "$WORK/rdap.json" 2>/dev/null | head -n 20
    fi
else
    echo "RDAP=DISABLED"
fi

echo
echo "=== 7. OPTIONAL EXTERNAL VERIFIER ==="
if [ -n "${EXTERNAL_VERIFIER_COMMAND:-}" ] && [ -x "$EXTERNAL_VERIFIER_COMMAND" ]; then
    "$EXTERNAL_VERIFIER_COMMAND" "$DOMAIN" 2>&1 | head -n 40
else
    echo "EXTERNAL_VERIFIER=NOT_CONFIGURED"
fi

echo
echo "=== 8. HEURISTIC SIGNALS ==="
HEUR=0
case "$DOMAIN" in
    *.xyz|*.click|*.top|*.icu|*.monster|*.buzz|*.cam|*.cfd|*.quest|*.sbs|*.rest|*.life)
        echo "SUSPICIOUS_TLD=YES"
        HEUR=$((HEUR + 10))
        ;;
    *) echo "SUSPICIOUS_TLD=NO" ;;
esac
if printf '%s\n' "$DOMAIN" | grep -Eqi '(^|[.-])(ads?|advert|banner|popup|popunder|redirect|click|track|tracker|tracking|analytics|metric|pixel|telemetry|affiliate|sponsor|beacon|promo)([.-]|$)'; then
    echo "SUSPICIOUS_KEYWORD=YES"
    HEUR=$((HEUR + 15))
else
    echo "SUSPICIOUS_KEYWORD=NO"
fi
[ "$HISTORY_COUNT" -ge 10 ] && HEUR=$((HEUR + 5))
[ "$HISTORY_COUNT" -ge 30 ] && HEUR=$((HEUR + 5))
echo "HEURISTIC_SCORE=$HEUR"
echo "NOTE=Heuristics alone never authorize automatic blocking"

echo
echo "============================================================"
echo " END"
echo "============================================================"
