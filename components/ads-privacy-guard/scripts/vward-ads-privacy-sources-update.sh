#!/bin/sh
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "FAIL: common library not found" >&2; exit 1; }
. "$LIB"

ads_mkdirs || ads_die "cannot create component directories"
ads_require "$ADS_JQ"; ads_require "$ADS_CURL"; ads_load_config
[ -r "$ADS_SOURCE_REGISTRY" ] || ads_die "source registry not readable"
LOCK="$ADS_STATE/sources-update.lock"
ads_lock_acquire "$LOCK" "${SOURCE_LOCK_STALE_SEC:-900}" || { echo "SOURCES_UPDATE=ALREADY_RUNNING"; exit 0; }
WORK="$ADS_STATE/work/sources-update.$$"; mkdir -p "$WORK" || ads_die "cannot create work directory"
cleanup(){ rm -rf "$WORK"; ads_lock_release "$LOCK"; }
trap cleanup EXIT INT TERM

SOURCE_TOTAL=0; SOURCE_OK=0; SOURCE_FAILED=0; UPDATED=0; ACTIVE_OK=0; CHECK_OK=0; OFF_COUNT=0

fetch_source() (
    fs_sid="$1"; fs_raw="$2"; fs_max="$3"; shift 3
    for fs_url in "$@"; do
        [ -n "$fs_url" ] || continue
        rm -f "$fs_raw.tmp"
        if "$ADS_CURL" -4 -f -L --connect-timeout "${SOURCE_CONNECT_TIMEOUT:-10}" \
           --max-time "${SOURCE_MAX_TIME:-120}" --max-filesize "$fs_max" -sS \
           "$fs_url" -o "$fs_raw.tmp"; then
            fs_bytes="$(wc -c < "$fs_raw.tmp" 2>/dev/null | tr -d ' ')"; fs_bytes="$(ads_num "$fs_bytes" 0)"
            [ "$fs_bytes" -le "$fs_max" ] || { rm -f "$fs_raw.tmp"; continue; }
            mv "$fs_raw.tmp" "$fs_raw" || return 1
            printf '%s\n' "$fs_url" > "$fs_raw.url"
            return 0
        fi
    done
    return 1
)

for SID in $("$ADS_JQ" -r '.sources[].id' "$ADS_SOURCE_REGISTRY" 2>/dev/null); do
    SOURCE_TOTAL=$((SOURCE_TOTAL + 1))
    MODE="$(ads_source_mode "$SID")"
    if [ "$MODE" = off ]; then
        OFF_COUNT=$((OFF_COUNT + 1)); echo "SOURCE=$SID"; echo "SOURCE_MODE=off"; echo "SOURCE_STATUS=SKIPPED"; echo; continue
    fi
    NAME="$("$ADS_JQ" -r --arg id "$SID" '.sources[]|select(.id==$id)|.name' "$ADS_SOURCE_REGISTRY")"
    VENDOR="$("$ADS_JQ" -r --arg id "$SID" '.sources[]|select(.id==$id)|.vendor' "$ADS_SOURCE_REGISTRY")"
    PURPOSE="$("$ADS_JQ" -r --arg id "$SID" '.sources[]|select(.id==$id)|.purpose' "$ADS_SOURCE_REGISTRY")"
    FORMAT="$("$ADS_JQ" -r --arg id "$SID" '.sources[]|select(.id==$id)|.format' "$ADS_SOURCE_REGISTRY")"
    MIN_ENTRIES="$("$ADS_JQ" -r --arg id "$SID" '.sources[]|select(.id==$id)|(.min_entries//1)' "$ADS_SOURCE_REGISTRY")"; MIN_ENTRIES="$(ads_num "$MIN_ENTRIES" 1)"
    MAX_BYTES="$("$ADS_JQ" -r --arg id "$SID" '.sources[]|select(.id==$id)|(.max_bytes//33554432)' "$ADS_SOURCE_REGISTRY")"; MAX_BYTES="$(ads_num "$MAX_BYTES" 33554432)"
    RAW="$WORK/$SID.raw"; NORMAL="$WORK/$SID.domains"; EXCEPT="$WORK/$SID.exceptions"
    echo "SOURCE=$SID"; echo "SOURCE_MODE=$MODE"; echo "NAME=$NAME"; echo "VENDOR=$VENDOR"; echo "PURPOSE=$PURPOSE"
    set -- $("$ADS_JQ" -r --arg id "$SID" '.sources[]|select(.id==$id)|.urls[]' "$ADS_SOURCE_REGISTRY")
    if ! fetch_source "$SID" "$RAW" "$MAX_BYTES" "$@"; then
        SOURCE_FAILED=$((SOURCE_FAILED + 1)); echo "SOURCE_STATUS=UNAVAILABLE_LKG_KEPT"; ads_log "SOURCE_FAIL|id=$SID|mode=$MODE|reason=download"; echo; continue
    fi
    BYTES="$(wc -c < "$RAW" 2>/dev/null | tr -d ' ')"; BYTES="$(ads_num "$BYTES" 0)"
    case "$FORMAT" in adblock|hosts|domains) ads_source_domain_normalize < "$RAW" > "$NORMAL"; ads_source_exception_normalize < "$RAW" > "$EXCEPT" ;; *) SOURCE_FAILED=$((SOURCE_FAILED+1)); echo "SOURCE_STATUS=UNSUPPORTED_FORMAT"; echo; continue ;; esac
    COUNT="$(wc -l < "$NORMAL" 2>/dev/null | tr -d ' ')"; COUNT="$(ads_num "$COUNT" 0)"
    if [ "$COUNT" -lt "$MIN_ENTRIES" ]; then SOURCE_FAILED=$((SOURCE_FAILED+1)); echo "SOURCE_STATUS=REJECTED_COUNT_LKG_KEPT"; echo "ENTRIES=$COUNT"; ads_log "SOURCE_FAIL|id=$SID|reason=count|count=$COUNT|min=$MIN_ENTRIES"; echo; continue; fi
    DEST="$ADS_STATE/sources/$SID.domains"; EXDEST="$ADS_STATE/sources/$SID.exceptions"; META="$ADS_STATE/sources/$SID.meta"
    OLD_SHA="$(ads_file_sha256 "$DEST" 2>/dev/null)"; NEW_SHA="$(ads_file_sha256 "$NORMAL")"
    # Install domains + exceptions as one logical last-known-good pair.  A
    # partial pair can invert an exception decision, so roll back both files if
    # either replacement fails.
    HAD_DEST=0; HAD_EXDEST=0
    [ -e "$DEST" ] && { cp -p "$DEST" "$WORK/$SID.domains.before" || { SOURCE_FAILED=$((SOURCE_FAILED+1)); echo "SOURCE_STATUS=BACKUP_FAILED"; continue; }; HAD_DEST=1; }
    [ -e "$EXDEST" ] && { cp -p "$EXDEST" "$WORK/$SID.exceptions.before" || { SOURCE_FAILED=$((SOURCE_FAILED+1)); echo "SOURCE_STATUS=BACKUP_FAILED"; continue; }; HAD_EXDEST=1; }
    if ! ads_atomic_copy "$NORMAL" "$DEST" 0644; then
        SOURCE_FAILED=$((SOURCE_FAILED+1)); echo "SOURCE_STATUS=INSTALL_FAILED"; continue
    fi
    if ! ads_atomic_copy "$EXCEPT" "$EXDEST" 0644; then
        [ "$HAD_DEST" -eq 1 ] && cp -p "$WORK/$SID.domains.before" "$DEST" 2>/dev/null || rm -f "$DEST"
        [ "$HAD_EXDEST" -eq 1 ] && cp -p "$WORK/$SID.exceptions.before" "$EXDEST" 2>/dev/null || rm -f "$EXDEST"
        SOURCE_FAILED=$((SOURCE_FAILED+1)); echo "SOURCE_STATUS=PAIR_ROLLBACK"; ads_log "SOURCE_FAIL|id=$SID|reason=pair_install"; continue
    fi
    EXCOUNT="$(wc -l < "$EXCEPT" 2>/dev/null | tr -d ' ')"; EXCOUNT="$(ads_num "$EXCOUNT" 0)"
    USED_URL="$(cat "$RAW.url" 2>/dev/null)"
    { echo "id=$SID"; echo "mode=$MODE"; echo "name=$NAME"; echo "vendor=$VENDOR"; echo "purpose=$PURPOSE"; echo "format=$FORMAT"; echo "entries=$COUNT"; echo "exceptions=$EXCOUNT"; echo "bytes=$BYTES"; echo "sha256=$NEW_SHA"; echo "fetched_at=$(ads_now)"; echo "url=$USED_URL"; } > "$WORK/$SID.meta"
    ads_atomic_copy "$WORK/$SID.meta" "$META" 0644 || true
    SOURCE_OK=$((SOURCE_OK+1)); [ "$MODE" = active ] && ACTIVE_OK=$((ACTIVE_OK+1)); [ "$MODE" = check ] && CHECK_OK=$((CHECK_OK+1)); [ "$OLD_SHA" = "$NEW_SHA" ] || UPDATED=$((UPDATED+1))
    echo "SOURCE_STATUS=OK"; echo "ENTRIES=$COUNT"; echo "EXCEPTIONS=$EXCOUNT"; echo "SHA256=$NEW_SHA"; echo
    ads_log "SOURCE_OK|id=$SID|mode=$MODE|entries=$COUNT|sha256=$NEW_SHA"
done

HEALTHY_INDEXES="$SOURCE_OK"
{ echo "last_run=$(ads_now)"; echo "source_total=$SOURCE_TOTAL"; echo "source_ok=$SOURCE_OK"; echo "source_failed=$SOURCE_FAILED"; echo "source_updated=$UPDATED"; echo "active_ok=$ACTIVE_OK"; echo "check_ok=$CHECK_OK"; echo "off=$OFF_COUNT"; echo "healthy_indexes=$HEALTHY_INDEXES"; } > "$WORK/sources.status"
ads_atomic_copy "$WORK/sources.status" "$ADS_STATE/sources.status" 0644 || true

echo "SOURCES_TOTAL=$SOURCE_TOTAL"; echo "SOURCES_OK=$SOURCE_OK"; echo "SOURCES_FAILED=$SOURCE_FAILED"; echo "SOURCES_UPDATED=$UPDATED"; echo "ACTIVE_OK=$ACTIVE_OK"; echo "CHECK_OK=$CHECK_OK"; echo "OFF=$OFF_COUNT"
MIN_HEALTHY_SOURCES="$(ads_num "${MIN_HEALTHY_SOURCES:-3}" 3)"
if [ "$HEALTHY_INDEXES" -lt "$MIN_HEALTHY_SOURCES" ] || [ "$ACTIVE_OK" -lt 1 ]; then echo "SOURCES_UPDATE=FAIL"; ads_log "SOURCES_UPDATE_FAIL|healthy=$HEALTHY_INDEXES|active=$ACTIVE_OK"; exit 4; fi
echo "SOURCES_UPDATE=PASS"; ads_log "SOURCES_UPDATE_OK|healthy=$HEALTHY_INDEXES|active=$ACTIVE_OK|updated=$UPDATED|failed=$SOURCE_FAILED"
