#!/bin/sh
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "FAIL: common library not found" >&2; exit 1; }
. "$LIB"
ads_mkdirs || ads_die "cannot create component directories"
ads_require "$ADS_JQ"
[ -r "$ADS_CONFIG" ] && ads_load_config
[ -r "$ADS_SOURCE_REGISTRY" ] || ads_die "source registry unavailable"

OP="${1:-list}"
case "$OP" in
  list)
    "$ADS_JQ" -r '.sources[].id' "$ADS_SOURCE_REGISTRY" | while IFS= read -r sid; do
      [ -n "$sid" ] || continue
      name="$($ADS_JQ -r --arg id "$sid" '.sources[]|select(.id==$id)|.name' "$ADS_SOURCE_REGISTRY")"
      purpose="$($ADS_JQ -r --arg id "$sid" '.sources[]|select(.id==$id)|.purpose' "$ADS_SOURCE_REGISTRY")"
      cached=0; [ -s "$ADS_STATE/sources/$sid.domains" ] && cached=1
      printf '%s|%s|%s|%s|%s\n' "$sid" "$(ads_source_mode "$sid")" "$name" "$cached" "$purpose"
    done
    exit 0
    ;;
  set) ;;
  *) echo "Usage: $0 {list|set SOURCE_ID active|check|off}" >&2; exit 2 ;;
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
