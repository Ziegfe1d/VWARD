#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "FAIL: common library not found" >&2; exit 1; }
. "$LIB"
ads_admission_enter ads-guard

MODE="${1:-scan}"
case "$MODE" in
    scan|--dry-run|rebuild) ;;
    *) echo "Usage: $0 [scan|--dry-run|rebuild]" >&2; exit 2 ;;
esac

ads_mkdirs || ads_die "cannot create component directories"
ads_require "$ADS_JQ"
ads_load_config

ENABLED="${ENABLED:-1}"
ads_bool "$ENABLED" || { echo "ADS_PRIVACY_GUARD=DISABLED"; exit 0; }

SCAN_TAIL_LINES="$(ads_num "${SCAN_TAIL_LINES:-20000}" 20000)"
MAX_CANDIDATES_PER_RUN="$(ads_num "${MAX_CANDIDATES_PER_RUN:-500}" 500)"
BLOCK_SCORE="$(ads_num "${BLOCK_SCORE:-150}" 150)"
REVIEW_SCORE="$(ads_num "${REVIEW_SCORE:-60}" 60)"
MIN_INDEPENDENT_GROUPS="$(ads_num "${MIN_INDEPENDENT_GROUPS:-2}" 2)"
ALLOW_TTL_DAYS="$(ads_num "${ALLOW_TTL_DAYS:-30}" 30)"
TRUST_TTL_DAYS="$(ads_num "${TRUST_TTL_DAYS:-180}" 180)"
SUSPECT_TTL_HOURS="$(ads_num "${SUSPECT_TTL_HOURS:-24}" 24)"
BLOCK_RECHECK_DAYS="$(ads_num "${BLOCK_RECHECK_DAYS:-30}" 30)"
MIN_SOURCE_INDEXES="$(ads_num "${MIN_SOURCE_INDEXES:-3}" 3)"
HEURISTIC_REVIEW_SCORE="$(ads_num "${HEURISTIC_REVIEW_SCORE:-20}" 20)"
PUBLISH_MODE="${PUBLISH_MODE:-staged}"
AUTO_PUBLISH="${AUTO_PUBLISH:-0}"
QUERY_SOURCE="${QUERY_SOURCE:-auto}"
AUTO_RULE_SCOPE="${AUTO_RULE_SCOPE:-exact}"
case "$AUTO_RULE_SCOPE" in exact|suffix) ;; *) ads_die "AUTO_RULE_SCOPE must be exact or suffix" ;; esac

# Scheduler can request a smaller low-load window without rewriting local config.
if [ -n "${VWARD_ADS_SCAN_TAIL_OVERRIDE:-}" ]; then
    SCAN_TAIL_LINES="$(ads_num "$VWARD_ADS_SCAN_TAIL_OVERRIDE" "$SCAN_TAIL_LINES")"
fi
if [ -n "${VWARD_ADS_MAX_CANDIDATES_OVERRIDE:-}" ]; then
    MAX_CANDIDATES_PER_RUN="$(ads_num "$VWARD_ADS_MAX_CANDIDATES_OVERRIDE" "$MAX_CANDIDATES_PER_RUN")"
fi

VERDICTS="$ADS_STATE/verdicts.tsv"
GENERATED="$ADS_STATE/generated/vward-ads-privacy-guard.rules"
REVIEW_QUEUE="$ADS_STATE/review.tsv"
LAST_RUN="$ADS_STATE/last-run.status"
LOCK="$ADS_STATE/scan.lock"
RUNTIME_STATUS="$ADS_RUNTIME_STATUS"

runtime_status()
{
    PHASE="$1" DOMAIN="${2:-}" CURRENT="${3:-0}" TOTAL="${4:-0}"
    TMP="/tmp/vward-ads-runtime.$$"
    {
        echo "ts=$(ads_now)"
        echo "phase=$PHASE"
        echo "mode=$MODE"
        echo "domain=$DOMAIN"
        echo "current=$CURRENT"
        echo "total=$TOTAL"
    } > "$TMP"
    mv "$TMP" "$RUNTIME_STATUS" 2>/dev/null || true
}

runtime_status preparing "" 0 0

if ! ads_lock_acquire "$LOCK"; then
    echo "ADS_SCAN=ALREADY_RUNNING"
    exit 0
fi

WORK="$(ads_scratch_dir scan)"
mkdir -m 700 "$WORK" || ads_die "cannot create work directory"
cleanup()
{
    rm -rf "${WORK:?}"
    ads_lock_release "$LOCK"
    runtime_status idle "" 0 0
    ads_admission_leave
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

RAW="$WORK/query.tsv"
STATS="$WORK/candidates.tsv"
LIMITED="$WORK/candidates-limited.tsv"
PENDING="$WORK/pending.tsv"
DECISIONS="$WORK/decisions.tsv"
LOOKUP="$WORK/lookup.tsv"
LOOKUP_KEYS="$WORK/lookup.keys"
MATCHES="$WORK/matches.tsv"
NEW_STATE="$WORK/verdicts.tsv"
NEW_RULES="$WORK/vward-ads-privacy-guard.rules"
NEW_REVIEW="$WORK/review.tsv"

: > "$RAW"
: > "$PENDING"
: > "$DECISIONS"
: > "$MATCHES"

QUERY_READER="${VWARD_ADS_QUERY_READER:-/opt/bin/vward-ads-privacy-query-read.sh}"
[ -x "$QUERY_READER" ] || QUERY_READER="$SELF_DIR/vward-ads-privacy-query-read.sh"
[ -x "$QUERY_READER" ] || ads_die "query reader missing"
QUERY_SOURCE="$QUERY_SOURCE" "$QUERY_READER" "$SCAN_TAIL_LINES" window > "$RAW" || ads_die "cannot read allowed AdGuard Home queries"

# Normalize and reject reverse/local/invalid names before aggregation.
awk -F'\t' '
{
    d=tolower($1)
    sub(/^\./,"",d); sub(/\.$/,"",d)
    if (d=="" || d !~ /^[a-z0-9_][a-z0-9_.-]*[a-z0-9_]$/ || index(d,".")==0) next
    if (d ~ /\.in-addr\.arpa$/ || d ~ /\.ip6\.arpa$/ || d ~ /\.local$/ || d ~ /\.lan$/ || d ~ /\.home\.arpa$/) next
    print d "|" $2 "|" $3
}' "$RAW" | sort -t'|' -k1,1 -k3,3 > "$WORK/query.normalized"

awk -F'|' '
{
    d=$1; c=$2; t=$3
    count[d]++
    if (!((d SUBSEP c) in client_seen)) { client_seen[d SUBSEP c]=1; clients[d]++ }
    if (!(d in first) || t < first[d]) first[d]=t
    if (!(d in last) || t > last[d]) last[d]=t
}
END {
    for (d in count)
        print d "|" count[d] "|" clients[d] "|" first[d] "|" last[d]
}' "$WORK/query.normalized" |
sort -t'|' -k2,2nr -k1,1 > "$STATS"

NOW="$(ads_epoch)"
# Previously blocked VWARD domains may disappear from the allowed AGH log after
# enforcement. Reinsert only BLOCK entries whose recheck TTL is due so they are
# periodically revalidated without waiting for a new allowed query.
if [ -r "$VERDICTS" ]; then
    awk -F'|' -v now="$NOW" '$3=="BLOCK" && ($7+0)<=now {print $1 "|0|0|" $5 "|" $6}' "$VERDICTS" >> "$STATS"
    sort -t'|' -k1,1 -k2,2nr "$STATS" | awk -F'|' '!seen[$1]++' > "$WORK/stats.dedup"
    mv "$WORK/stats.dedup" "$STATS"
fi

# Do not limit before trust/cache checks: hot known domains must not starve new
# unknown domains. The cap is applied to the expensive PENDING queue later.
cp "$STATS" "$LIMITED"
TOTAL_ALLOWED="$(wc -l < "$WORK/query.normalized" 2>/dev/null | tr -d ' ')"
UNIQUE_ALLOWED="$(wc -l < "$STATS" 2>/dev/null | tr -d ' ')"
TOTAL_ALLOWED="$(ads_num "$TOTAL_ALLOWED" 0)"
UNIQUE_ALLOWED="$(ads_num "$UNIQUE_ALLOWED" 0)"
TRUST_NEXT=$((NOW + TRUST_TTL_DAYS * 86400))
ALLOW_NEXT=$((NOW + ALLOW_TTL_DAYS * 86400))
SUSPECT_NEXT=$((NOW + SUSPECT_TTL_HOURS * 3600))
BLOCK_NEXT=$((NOW + BLOCK_RECHECK_DAYS * 86400))

# Existing state may not exist on first run.
[ -r "$VERDICTS" ] || : > "$VERDICTS"

sanitize_field()
{
    printf '%s' "$1" | tr '|\t\r\n' '    ' | sed 's/[[:space:]][[:space:]]*/ /g'
}

state_line_for()
{
    D="$1"
    awk -F'|' -v d="$D" '$1==d {print; exit}' "$VERDICTS" 2>/dev/null
}

write_decision()
{
    D="$1" V="$2" A="$3" C="$4" FIRST="$5" LAST="$6" NEXT="$7" REASON="$8" EVIDENCE="$9"
    REASON="$(sanitize_field "$REASON")"
    EVIDENCE="$(sanitize_field "$EVIDENCE")"
    printf '%s|%s|%s|%s|%s|%s|%s|%s|%s\n' \
        "$D" "$V" "$A" "$C" "$FIRST" "$LAST" "$NEXT" "$REASON" "$EVIDENCE" >> "$DECISIONS"
}

while IFS='|' read -r DOMAIN COUNT CLIENTS FIRST_SEEN LAST_SEEN; do
    [ -n "$DOMAIN" ] || continue

    if ads_denylist_match "$DOMAIN"; then
        write_decision "$DOMAIN" BLOCK BLOCK VERY_HIGH "$FIRST_SEEN" "$LAST_SEEN" "$BLOCK_NEXT" \
            "manual_denylist" "local denylist"
        continue
    fi

    if ads_allowlist_match "$DOMAIN"; then
        write_decision "$DOMAIN" ALLOW NONE VERY_HIGH "$FIRST_SEEN" "$LAST_SEEN" "$TRUST_NEXT" \
            "manual_allowlist" "local allowlist; never auto block"
        continue
    fi

    if ads_builtin_trust_match "$DOMAIN"; then
        write_decision "$DOMAIN" TRUST NONE HIGH "$FIRST_SEEN" "$LAST_SEEN" "$TRUST_NEXT" \
            "trusted_registry" "built-in exact/suffix trust registry"
        continue
    fi

    OLD="$(state_line_for "$DOMAIN")"
    if [ -n "$OLD" ] && [ "$MODE" != rebuild ]; then
        OLD_NEXT="$(printf '%s\n' "$OLD" | cut -d'|' -f7)"
        OLD_NEXT="$(ads_num "$OLD_NEXT" 0)"
        if [ "$OLD_NEXT" -gt "$NOW" ]; then
            # Keep the verdict but refresh last_seen. This avoids expensive rechecks.
            OLD_V="$(printf '%s\n' "$OLD" | cut -d'|' -f2)"
            OLD_A="$(printf '%s\n' "$OLD" | cut -d'|' -f3)"
            OLD_C="$(printf '%s\n' "$OLD" | cut -d'|' -f4)"
            OLD_FIRST="$(printf '%s\n' "$OLD" | cut -d'|' -f5)"
            OLD_REASON="$(printf '%s\n' "$OLD" | cut -d'|' -f8)"
            OLD_EVID="$(printf '%s\n' "$OLD" | cut -d'|' -f9-)"
            [ -n "$OLD_FIRST" ] || OLD_FIRST="$FIRST_SEEN"
            write_decision "$DOMAIN" "$OLD_V" "$OLD_A" "$OLD_C" "$OLD_FIRST" "$LAST_SEEN" "$OLD_NEXT" "$OLD_REASON" "$OLD_EVID"
            continue
        fi
    fi

    printf '%s|%s|%s|%s|%s\n' "$DOMAIN" "$COUNT" "$CLIENTS" "$FIRST_SEEN" "$LAST_SEEN" >> "$PENDING"
done < "$LIMITED"

# Expensive evidence lookup is capped only after cheap trust/manual/cache paths.
cp "$PENDING" "$WORK/pending.all"
head -n "$MAX_CANDIDATES_PER_RUN" "$WORK/pending.all" > "$PENDING"
CANDIDATE_COUNT="$(wc -l < "$PENDING" 2>/dev/null | tr -d ' ')"
CANDIDATE_COUNT="$(ads_num "$CANDIDATE_COUNT" 0)"
PENDING_COUNT="$CANDIDATE_COUNT"
runtime_status indexing "" 0 "$PENDING_COUNT"

# Build suffix lookup keys so ||example.com^ can match sub.example.com.
while IFS='|' read -r DOMAIN COUNT CLIENTS FIRST_SEEN LAST_SEEN; do
    [ -n "$DOMAIN" ] || continue
    KEY="$DOMAIN"
    N=0
    while [ "$N" -lt 8 ]; do
        case "$KEY" in
            *.*)
                printf '%s|%s\n' "$KEY" "$DOMAIN" >> "$LOOKUP"
                KEY="${KEY#*.}"
                ;;
            *) break ;;
        esac
        N=$((N + 1))
    done
done < "$PENDING"
sort -u "$LOOKUP" -o "$LOOKUP" 2>/dev/null || true
cut -d'|' -f1 "$LOOKUP" 2>/dev/null | sort -u > "$LOOKUP_KEYS"

HEALTHY_INDEXES=0
if [ -r "$ADS_SOURCE_REGISTRY" ] && [ -s "$LOOKUP_KEYS" ]; then
    for SID in $("$ADS_JQ" -r '.sources[].id' "$ADS_SOURCE_REGISTRY" 2>/dev/null); do
        SOURCE_MODE="$(ads_source_mode "$SID")"
        [ "$SOURCE_MODE" != off ] || continue
        SRC="$ADS_STATE/sources/$SID.domains"
        [ -s "$SRC" ] || continue
        HEALTHY_INDEXES=$((HEALTHY_INDEXES + 1))

        GROUP="$("$ADS_JQ" -r --arg id "$SID" '.sources[] | select(.id==$id) | (.independence_group // .vendor)' "$ADS_SOURCE_REGISTRY")"
        WEIGHT="$("$ADS_JQ" -r --arg id "$SID" '.sources[] | select(.id==$id) | (.weight // 0)' "$ADS_SOURCE_REGISTRY")"
        SINGLE="$("$ADS_JQ" -r --arg id "$SID" '.sources[] | select(.id==$id) | (.single_source_block // false)' "$ADS_SOURCE_REGISTRY")"
        PURPOSE="$("$ADS_JQ" -r --arg id "$SID" '.sources[] | select(.id==$id) | .purpose' "$ADS_SOURCE_REGISTRY")"

        comm -12 "$LOOKUP_KEYS" "$SRC" > "$WORK/$SID.hitkeys"
        [ -s "$WORK/$SID.hitkeys" ] || continue

        # Respect domain-anchored exception rules from the same source.  A child
        # exception suppresses evidence inherited from a blocked parent domain.
        : > "$WORK/$SID.excluded"
        EXC="$ADS_STATE/sources/$SID.exceptions"
        if [ -s "$EXC" ]; then
            comm -12 "$LOOKUP_KEYS" "$EXC" > "$WORK/$SID.exceptkeys"
            if [ -s "$WORK/$SID.exceptkeys" ]; then
                awk -F'|' '
                    NR==FNR {exc[$1]=1; next}
                    exc[$1] {print $2}
                ' "$WORK/$SID.exceptkeys" "$LOOKUP" | sort -u > "$WORK/$SID.excluded"
            fi
        fi

        awk -F'|' '
            NR==FNR {hit[$1]=1; next}
            hit[$1] && !seen[$2]++ {print $2 "|" $1}
        ' "$WORK/$SID.hitkeys" "$LOOKUP" > "$WORK/$SID.pairs"

        awk -F'|' -v sid="$SID" -v group="$GROUP" -v weight="$WEIGHT" -v single="$SINGLE" -v purpose="$PURPOSE" -v smode="$SOURCE_MODE" '
            FILENAME==ARGV[1] {excluded[$1]=1; next}
            !($1 in excluded) {print $1 "|" $2 "|" sid "|" group "|" weight "|" single "|" purpose "|" smode}
        ' "$WORK/$SID.excluded" "$WORK/$SID.pairs" >> "$MATCHES"
    done
fi

sort -u "$MATCHES" -o "$MATCHES" 2>/dev/null || true

suspicious_tld_score()
{
    case "$1" in
        *.xyz|*.click|*.top|*.icu|*.monster|*.buzz|*.cam|*.cfd|*.quest|*.sbs|*.rest|*.life)
            echo 10 ;;
        *) echo 0 ;;
    esac
}

keyword_score()
{
    printf '%s\n' "$1" |
    grep -Eqi '(^|[.-])(ads?|advert|banner|popup|popunder|redirect|click|track|tracker|tracking|analytics|metric|pixel|telemetry|affiliate|sponsor|beacon|promo)([.-]|$)' && echo 15 || echo 0
}

external_verdict()
{
    DOMAIN="$1"
    CMD="${EXTERNAL_VERIFIER_COMMAND:-}"
    [ -n "$CMD" ] && [ -x "$CMD" ] || return 1
    "$CMD" "$DOMAIN" 2>/dev/null | head -n 1
}

PROCESSED=0
runtime_status analysing "" 0 "$PENDING_COUNT"
while IFS='|' read -r DOMAIN COUNT CLIENTS FIRST_SEEN LAST_SEEN; do
    [ -n "$DOMAIN" ] || continue
    PROCESSED=$((PROCESSED + 1))
    runtime_status analysing "$DOMAIN" "$PROCESSED" "$PENDING_COUNT"

    SUMMARY="$(awk -F'|' -v d="$DOMAIN" '
        $1==d {
            sid=$3; group=$4; weight=$5+0; single=$6; purpose=$7; smode=$8
            if (smode=="active") {
                if (!(group in gmax) || weight>gmax[group]) gmax[group]=weight
                if (!gseen[group]++) groups++
                if (single=="true") single_block=1
            }
            if (!sseen[sid]++) {
                if (sources!="") sources=sources ","
                sources=sources sid "(" smode ")"
            }
            if (!pseen[purpose]++) {
                if (purposes!="") purposes=purposes ","
                purposes=purposes purpose
            }
        }
        END {
            score=0
            for (g in gmax) score+=gmax[g]
            printf "%d|%d|%d|%s|%s", score+0,groups+0,single_block+0,sources,purposes
        }
    ' "$MATCHES")"

    SCORE="$(printf '%s' "$SUMMARY" | cut -d'|' -f1)"
    GROUPS="$(printf '%s' "$SUMMARY" | cut -d'|' -f2)"
    SINGLE_BLOCK="$(printf '%s' "$SUMMARY" | cut -d'|' -f3)"
    SOURCES="$(printf '%s' "$SUMMARY" | cut -d'|' -f4)"
    PURPOSES="$(printf '%s' "$SUMMARY" | cut -d'|' -f5)"
    SCORE="$(ads_num "$SCORE" 0)"
    GROUPS="$(ads_num "$GROUPS" 0)"
    SINGLE_BLOCK="$(ads_num "$SINGLE_BLOCK" 0)"

    OLD="$(state_line_for "$DOMAIN")"
    OLD_ACTION="$(printf '%s\n' "$OLD" | cut -d'|' -f3)"
    OLD_FIRST="$(printf '%s\n' "$OLD" | cut -d'|' -f5)"
    [ -n "$OLD_FIRST" ] || OLD_FIRST="$FIRST_SEEN"

    if [ "$SINGLE_BLOCK" -eq 1 ]; then
        write_decision "$DOMAIN" BLOCK BLOCK VERY_HIGH "$OLD_FIRST" "$LAST_SEEN" "$BLOCK_NEXT" \
            "dedicated_block_feed" "score=$SCORE groups=$GROUPS sources=$SOURCES purpose=$PURPOSES"
        continue
    fi

    if [ "$GROUPS" -ge "$MIN_INDEPENDENT_GROUPS" ] && [ "$SCORE" -ge "$BLOCK_SCORE" ]; then
        write_decision "$DOMAIN" BLOCK BLOCK HIGH "$OLD_FIRST" "$LAST_SEEN" "$BLOCK_NEXT" \
            "multi_source_consensus" "score=$SCORE groups=$GROUPS sources=$SOURCES purpose=$PURPOSES"
        continue
    fi

    EXT="$(external_verdict "$DOMAIN")"
    if [ -n "$EXT" ]; then
        EXT_V="$(printf '%s' "$EXT" | cut -d'|' -f1)"
        EXT_C="$(printf '%s' "$EXT" | cut -d'|' -f2)"
        EXT_R="$(printf '%s' "$EXT" | cut -d'|' -f3-)"
        case "$EXT_V" in
            BLOCK)
                write_decision "$DOMAIN" BLOCK BLOCK "${EXT_C:-HIGH}" "$OLD_FIRST" "$LAST_SEEN" "$BLOCK_NEXT" \
                    "external_verifier" "$EXT_R"
                continue
                ;;
            ALLOW|TRUST)
                write_decision "$DOMAIN" ALLOW NONE "${EXT_C:-HIGH}" "$OLD_FIRST" "$LAST_SEEN" "$ALLOW_NEXT" \
                    "external_verifier" "$EXT_R"
                continue
                ;;
            SUSPECT|REVIEW)
                write_decision "$DOMAIN" SUSPECT NONE "${EXT_C:-MEDIUM}" "$OLD_FIRST" "$LAST_SEEN" "$SUSPECT_NEXT" \
                    "external_verifier" "$EXT_R"
                continue
                ;;
        esac
    fi

    # Never cache a new domain as safe while the evidence catalog is degraded.
    # External verifier gets a chance first; otherwise queue a short recheck.
    if [ "$HEALTHY_INDEXES" -lt "$MIN_SOURCE_INDEXES" ] && [ "$SCORE" -eq 0 ]; then
        ACTION=NONE
        [ "$OLD_ACTION" = BLOCK ] && ACTION=BLOCK
        write_decision "$DOMAIN" SUSPECT "$ACTION" LOW "$OLD_FIRST" "$LAST_SEEN" "$SUSPECT_NEXT" \
            "source_catalog_degraded" "healthy_indexes=$HEALTHY_INDEXES required=$MIN_SOURCE_INDEXES"
        continue
    fi

    HEUR=0
    TLD_SCORE="$(suspicious_tld_score "$DOMAIN")"
    KEY_SCORE="$(keyword_score "$DOMAIN")"
    HEUR=$((HEUR + TLD_SCORE + KEY_SCORE))
    [ "$COUNT" -ge 10 ] && HEUR=$((HEUR + 5))
    [ "$COUNT" -ge 30 ] && HEUR=$((HEUR + 5))
    [ "$CLIENTS" -eq 1 ] && [ "$COUNT" -ge 5 ] && HEUR=$((HEUR + 5))

    if [ "$SCORE" -ge "$REVIEW_SCORE" ] || [ "$HEUR" -ge "$HEURISTIC_REVIEW_SCORE" ]; then
        ACTION=NONE
        REASON="review_required"
        # Safety invariant: an automatically blocked domain is never silently
        # unblocked merely because a remote list changed. Hold it blocked until
        # the review/allowlist path resolves the regression.
        if [ "$OLD_ACTION" = BLOCK ]; then
            ACTION=BLOCK
            REASON="block_revalidation_pending"
        fi
        write_decision "$DOMAIN" SUSPECT "$ACTION" MEDIUM "$OLD_FIRST" "$LAST_SEEN" "$SUSPECT_NEXT" \
            "$REASON" "source_score=$SCORE groups=$GROUPS sources=$SOURCES heuristic=$HEUR queries=$COUNT clients=$CLIENTS"
    else
        if [ "$OLD_ACTION" = BLOCK ]; then
            write_decision "$DOMAIN" SUSPECT BLOCK MEDIUM "$OLD_FIRST" "$LAST_SEEN" "$SUSPECT_NEXT" \
                "block_evidence_disappeared_review" "previous block held; source_score=$SCORE heuristic=$HEUR"
        else
            write_decision "$DOMAIN" ALLOW NONE MEDIUM "$OLD_FIRST" "$LAST_SEEN" "$ALLOW_NEXT" \
                "no_block_evidence" "source_score=$SCORE groups=$GROUPS heuristic=$HEUR queries=$COUNT clients=$CLIENTS"
        fi
    fi
done < "$PENDING"

runtime_status finalizing "" "$PENDING_COUNT" "$PENDING_COUNT"

# Merge decisions into persistent state atomically. State entries not touched by
# this scan remain intact.
awk -F'|' '
    NR==FNR {new[$1]=$0; order[++n]=$1; next}
    {
        if ($1 in new) {print new[$1]; used[$1]=1}
        else print
    }
    END {
        for (i=1;i<=n;i++) if (!(order[i] in used)) print new[order[i]]
    }
' "$DECISIONS" "$VERDICTS" | sort -t'|' -k1,1 > "$NEW_STATE"

# Build managed block rules from action=BLOCK. User denylist is included as an
# explicit override. The generated file is the authoritative VWARD output.
{
    echo "! VWARD Ads & Privacy Guard"
    echo "! generated: $(ads_now)"
    echo "! source: allowed AdGuard Home DNS requests + evidence registry"
    echo "! do not edit; use VWARD allowlist/denylist"
    # Automatic VWARD decisions use the configured safe scope (exact by default).
    awk -F'|' '$3=="BLOCK" && $8!="manual_denylist" {print $1}' "$NEW_STATE" | while IFS= read -r d; do
        [ -n "$d" ] && ads_rule_for "$d" "$AUTO_RULE_SCOPE"
    done
    # Manual blocks retain the user-selected exact/suffix scope.
    if [ -r "$ADS_DENYLIST" ]; then
        awk -F'|' '/^[[:space:]]*#/ || NF<2 {next} {print tolower($1) "|" tolower($2)}' "$ADS_DENYLIST" | while IFS='|' read -r d scope; do
            [ -n "$d" ] && ads_rule_for "$d" "$scope"
        done
    fi
} | sort -u > "$NEW_RULES"

awk -F'|' '$2=="SUSPECT" {print}' "$NEW_STATE" > "$NEW_REVIEW"

if [ "$MODE" = "--dry-run" ]; then
    echo "ADS_SCAN=DRY_RUN"
    echo "ALLOWED_RECORDS=$TOTAL_ALLOWED"
    echo "UNIQUE_ALLOWED_DOMAINS=$UNIQUE_ALLOWED"
    echo "CANDIDATES_CONSIDERED=$CANDIDATE_COUNT"
    echo "PENDING_RECHECK=$PENDING_COUNT"
    echo "SOURCE_INDEXES=$HEALTHY_INDEXES"
    echo "DECISIONS=$(wc -l < "$DECISIONS" 2>/dev/null | tr -d ' ')"
    echo "WOULD_BLOCK=$(awk -F'|' '$3=="BLOCK"{n++}END{print n+0}' "$NEW_STATE")"
    echo "WOULD_REVIEW=$(awk -F'|' '$2=="SUSPECT"{n++}END{print n+0}' "$NEW_STATE")"
    exit 0
fi

# If no source catalog is healthy, do not accept new feed-based classifications.
# Trust/cache decisions are still safe, but the contour is considered degraded.
if [ "$HEALTHY_INDEXES" -lt "$MIN_SOURCE_INDEXES" ] && [ "$PENDING_COUNT" -gt 0 ]; then
    ads_log "SCAN_DEGRADED|healthy_indexes=$HEALTHY_INDEXES|min=$MIN_SOURCE_INDEXES"
fi

ads_install_if_changed "$NEW_STATE" "$VERDICTS" 0644 || ads_die "cannot install verdict state"
ads_install_if_changed "$NEW_RULES" "$GENERATED" 0644 || ads_die "cannot install generated rules"
ads_install_if_changed "$NEW_REVIEW" "$REVIEW_QUEUE" 0644 || ads_die "cannot install review queue"

BLOCKED_COUNT="$(awk -F'|' '$3=="BLOCK"{n++}END{print n+0}' "$VERDICTS")"
REVIEW_COUNT="$(awk -F'|' '$2=="SUSPECT"{n++}END{print n+0}' "$VERDICTS")"
ALLOW_COUNT="$(awk -F'|' '$2=="ALLOW"{n++}END{print n+0}' "$VERDICTS")"
TRUST_COUNT="$(awk -F'|' '$2=="TRUST"{n++}END{print n+0}' "$VERDICTS")"

{
    echo "last_run=$(ads_now)"
    echo "allowed_records=$TOTAL_ALLOWED"
    echo "unique_allowed=$UNIQUE_ALLOWED"
    echo "candidates=$CANDIDATE_COUNT"
    echo "pending_recheck=$PENDING_COUNT"
    echo "source_indexes=$HEALTHY_INDEXES"
    echo "blocked=$BLOCKED_COUNT"
    echo "review=$REVIEW_COUNT"
    echo "allow=$ALLOW_COUNT"
    echo "trust=$TRUST_COUNT"
    echo "publish_mode=$PUBLISH_MODE"
    echo "auto_publish=$AUTO_PUBLISH"
} > "$WORK/last-run.status"
ads_atomic_copy "$WORK/last-run.status" "$LAST_RUN" 0644 || true

ads_log "SCAN_OK|allowed=$TOTAL_ALLOWED|unique=$UNIQUE_ALLOWED|blocked=$BLOCKED_COUNT|review=$REVIEW_COUNT|sources=$HEALTHY_INDEXES"

echo "ADS_SCAN=PASS"
echo "ALLOWED_RECORDS=$TOTAL_ALLOWED"
echo "UNIQUE_ALLOWED_DOMAINS=$UNIQUE_ALLOWED"
echo "CANDIDATES_CONSIDERED=$CANDIDATE_COUNT"
echo "PENDING_RECHECK=$PENDING_COUNT"
echo "SOURCE_INDEXES=$HEALTHY_INDEXES"
echo "BLOCKED_STATE=$BLOCKED_COUNT"
echo "REVIEW_STATE=$REVIEW_COUNT"
echo "ALLOW_STATE=$ALLOW_COUNT"
echo "TRUST_STATE=$TRUST_COUNT"
echo "GENERATED_RULES=$GENERATED"
echo "PUBLISH_MODE=$PUBLISH_MODE"
echo "AUTO_PUBLISH=$AUTO_PUBLISH"

if ! ads_bool "$AUTO_PUBLISH"; then
    echo "PUBLISH_STATUS=STAGED_AUTO_DISABLED"
    exit 0
fi

if [ "$PUBLISH_MODE" = "user_rules_api" ]; then
    PUBLISHER="${VWARD_ADS_PUBLISHER:-/opt/bin/vward-ads-privacy-publish.sh}"
    [ -x "$PUBLISHER" ] || PUBLISHER="$SELF_DIR/vward-ads-privacy-publish.sh"
    if [ -x "$PUBLISHER" ]; then
        "$PUBLISHER" apply
        exit $?
    fi
    echo "PUBLISH_STATUS=SKIPPED_PUBLISHER_MISSING"
else
    echo "PUBLISH_STATUS=STAGED_ONLY"
fi

exit 0
