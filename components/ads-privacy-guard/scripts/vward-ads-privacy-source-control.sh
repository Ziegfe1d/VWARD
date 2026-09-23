#!/bin/sh
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "FAIL: common library not found" >&2; exit 1; }
. "$LIB"
ads_admission_enter ads-source-control
trap ads_admission_leave EXIT
trap 'exit 1' HUP INT TERM
ads_mkdirs || ads_die "cannot create component directories"
ads_require "$ADS_JQ"
[ -r "$ADS_CONFIG" ] && ads_load_config
[ -r "$ADS_SOURCE_REGISTRY" ] || ads_die "source registry unavailable"

# Writes a file through a verified temporary copy; restores the backup on failure.
install_file() {
    tf="$1"; target="$2"
    chmod 0600 "$tf" || return 1
    mv "$tf" "$target"
}

set_override() {
    # set_override ID MODE: one override line per source.
    [ -e "$ADS_SOURCE_OVERRIDES" ] || : > "$ADS_SOURCE_OVERRIDES"
    so_tmp="$ADS_STATE/work/source-overrides.$$"
    awk -F'|' -v id="$1" '$1!=id {print}' "$ADS_SOURCE_OVERRIDES" > "$so_tmp" || return 1
    [ "$2" = "" ] || printf '%s|%s|console/manual override\n' "$1" "$2" >> "$so_tmp"
    sort -u "$so_tmp" -o "$so_tmp" && install_file "$so_tmp" "$ADS_SOURCE_OVERRIDES"
}

custom_op() {
    mkdir -p "$ADS_ETC" "$ADS_STATE/work" || ads_die "cannot create directories"
    STAMP="$(date '+%Y%m%d-%H%M%S')"; BACKUP_DIR="$ADS_BACKUP_ROOT/source-settings/$STAMP"
    mkdir -p "$BACKUP_DIR" && chmod 0700 "$BACKUP_DIR" || ads_die "cannot create backup directory"
    for f in "$ADS_SOURCE_OVERRIDES" "$ADS_CUSTOM_SOURCES"; do [ ! -e "$f" ] || cp -p "$f" "$BACKUP_DIR/" || ads_die "backup failed"; done
    [ -s "$ADS_CUSTOM_SOURCES" ] || printf '{"schema":1,"sources":[]}\n' > "$ADS_CUSTOM_SOURCES"
    CT="$ADS_STATE/work/custom-sources.$$"
    case "$1" in
      add)
        URL="${2:-}"; FORMAT="${3:-}"
        printf '%s\n' "$URL" | grep -Eq '^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?/[A-Za-z0-9._~/%+=&?-]*$' && [ "${#URL}" -le 300 ] || ads_die "invalid source url"
        case "$FORMAT" in adblock|hosts|domains) ;; *) ads_die "format must be adblock, hosts or domains" ;; esac
        SID="custom-$(printf '%s' "$URL" | sha256sum | cut -c1-10)"
        "$ADS_JQ" -e --arg id "$SID" 'any(.sources[]?; .id == $id)' "$ADS_CUSTOM_SOURCES" >/dev/null 2>&1 && ads_die "source already added"
        [ "$("$ADS_JQ" '.sources | length' "$ADS_CUSTOM_SOURCES" 2>/dev/null || echo 99)" -lt 10 ] || ads_die "at most 10 custom sources"
        "$ADS_JQ" --arg id "$SID" --arg url "$URL" --arg format "$FORMAT" '.sources += [{id:$id,url:$url,format:$format}]' "$ADS_CUSTOM_SOURCES" > "$CT" || ads_die "cannot build custom sources"
        install_file "$CT" "$ADS_CUSTOM_SOURCES" || ads_die "custom source install failed"
        # New sources start in "check" mode: they are evaluated but block nothing.
        set_override "$SID" check || { cp -p "$BACKUP_DIR/$(basename "$ADS_CUSTOM_SOURCES")" "$ADS_CUSTOM_SOURCES" 2>/dev/null; ads_die "override failed; rolled back"; }
        ads_log "SOURCE_ADD|id=$SID|format=$FORMAT|backup=$BACKUP_DIR"
        echo "SOURCE_CONTROL=PASS"; echo "SOURCE_ID=$SID"; echo "MODE=check"
        ;;
      delete)
        SID="${2:-}"
        case "$SID" in custom-*) ;; *) ads_die "only custom sources can be deleted" ;; esac
        "$ADS_JQ" -e --arg id "$SID" 'any(.sources[]?; .id == $id)' "$ADS_CUSTOM_SOURCES" >/dev/null 2>&1 || ads_die "unknown custom source"
        "$ADS_JQ" --arg id "$SID" '.sources |= map(select(.id != $id))' "$ADS_CUSTOM_SOURCES" > "$CT" || ads_die "cannot build custom sources"
        install_file "$CT" "$ADS_CUSTOM_SOURCES" || ads_die "custom source removal failed"
        set_override "$SID" "" || ads_die "override cleanup failed"
        rm -f "$ADS_STATE/sources/$SID".* 2>/dev/null
        ads_log "SOURCE_DELETE|id=$SID|backup=$BACKUP_DIR"
        echo "SOURCE_CONTROL=PASS"; echo "SOURCE_ID=$SID"
        ;;
      category)
        PURPOSE="${2:-}"; STATE_ON="${3:-}"
        case "$PURPOSE" in ''|*[!a-z-]*) ads_die "invalid category" ;; esac
        case "$STATE_ON" in on|off) ;; *) ads_die "category state must be on or off" ;; esac
        IDS="$("$ADS_JQ" -r --arg p "$PURPOSE" '.sources[] | select(.purpose == $p) | .id + "|" + (.default_mode // "check")' "$ADS_SOURCE_REGISTRY")"
        [ -n "$IDS" ] || ads_die "unknown category"
        for row in $IDS; do
            sid="${row%%|*}"; def="${row#*|}"
            # "on" restores each source's default mode, "off" switches it off.
            if [ "$STATE_ON" = on ]; then set_override "$sid" "$def"; else set_override "$sid" off; fi ||
                { cp -p "$BACKUP_DIR/$(basename "$ADS_SOURCE_OVERRIDES")" "$ADS_SOURCE_OVERRIDES" 2>/dev/null; ads_die "category change failed; rolled back"; }
        done
        ads_log "SOURCE_CATEGORY|purpose=$PURPOSE|state=$STATE_ON|backup=$BACKUP_DIR"
        echo "SOURCE_CONTROL=PASS"; echo "CATEGORY=$PURPOSE"; echo "STATE=$STATE_ON"
        ;;
    esac
}

OP="${1:-list}"
case "$OP" in
  list)
    "$ADS_JQ" -r '.sources[].id' "$ADS_SOURCE_REGISTRY" | while IFS= read -r sid; do
      [ -n "$sid" ] || continue
      name="$($ADS_JQ -r --arg id "$sid" '.sources[]|select(.id==$id)|.name' "$ADS_SOURCE_REGISTRY")"
      purpose="$($ADS_JQ -r --arg id "$sid" '.sources[]|select(.id==$id)|.purpose' "$ADS_SOURCE_REGISTRY")"
      cached=0; [ -s "$ADS_STATE/sources/$sid.domains" ] && cached=1
      custom=0; case "$sid" in custom-*) custom=1 ;; esac
      printf '%s|%s|%s|%s|%s|%s\n' "$sid" "$(ads_source_mode "$sid")" "$name" "$cached" "$purpose" "$custom"
    done
    exit 0
    ;;
  set) ;;
  add|delete|category) custom_op "$@"; exit $? ;;
  *) echo "Usage: $0 {list|set SOURCE_ID active|check|off|add URL FORMAT|delete SOURCE_ID|category PURPOSE on|off}" >&2; exit 2 ;;
esac

SID="${2:-}"; MODE="${3:-}"
case "$SID" in ''|*[!a-z0-9-]*) ads_die "invalid source id" ;; esac
case "$MODE" in active|check|off) ;; *) ads_die "mode must be active, check or off" ;; esac
"$ADS_JQ" -e --arg id "$SID" '.sources[] | select(.id==$id)' "$ADS_SOURCE_REGISTRY" >/dev/null 2>&1 || ads_die "unknown source id: $SID"

[ -e "$ADS_SOURCE_OVERRIDES" ] || : > "$ADS_SOURCE_OVERRIDES"
STAMP="$(date '+%Y%m%d-%H%M%S')"
BACKUP_DIR="$ADS_BACKUP_ROOT/source-settings/$STAMP"
mkdir -p "$BACKUP_DIR" || ads_die "cannot create backup directory"
chmod 0700 "$BACKUP_DIR" || ads_die "cannot protect backup directory"
cp -p "$ADS_SOURCE_OVERRIDES" "$BACKUP_DIR/source-overrides.tsv.before" || ads_die "backup failed"

TMP="$ADS_STATE/work/source-overrides.$$"
awk -F'|' -v id="$SID" '$1!=id {print}' "$ADS_SOURCE_OVERRIDES" > "$TMP" || ads_die "cannot build overrides"
printf '%s|%s|console/manual override\n' "$SID" "$MODE" >> "$TMP"
sort -u "$TMP" -o "$TMP" || ads_die "cannot sort overrides"
chmod 0600 "$TMP" || ads_die "cannot protect override temp"
if ! mv "$TMP" "$ADS_SOURCE_OVERRIDES"; then
  cp -p "$BACKUP_DIR/source-overrides.tsv.before" "$ADS_SOURCE_OVERRIDES" 2>/dev/null || true
  ads_die "override install failed"
fi

[ "$(ads_source_mode "$SID")" = "$MODE" ] || {
  cp -p "$BACKUP_DIR/source-overrides.tsv.before" "$ADS_SOURCE_OVERRIDES" 2>/dev/null || true
  ads_die "override verification failed; rolled back"
}
ads_log "SOURCE_MODE|id=$SID|mode=$MODE|backup=$BACKUP_DIR"
echo "SOURCE_CONTROL=PASS"
echo "SOURCE=$SID"
echo "MODE=$MODE"
echo "BACKUP_DIR=$BACKUP_DIR"
