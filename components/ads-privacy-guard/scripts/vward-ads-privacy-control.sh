#!/bin/sh
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "FAIL: common library not found" >&2; exit 1; }
. "$LIB"
ads_mkdirs || ads_die "cannot create component directories"
[ -r "$ADS_CONFIG" ] && ads_load_config

pause_state(){ p=0; [ -r "$ADS_CONTROL_STATE" ] && p="$(awk -F= '$1=="paused"{print $2; exit}' "$ADS_CONTROL_STATE")"; case "$p" in 1) echo 1 ;; *) echo 0 ;; esac; }
write_pause_state(){ p="$1"; t="$ADS_STATE/work/control-state.$$"; { echo "paused=$p"; echo "changed=$(ads_now)"; } > "$t" || return 1; ads_atomic_copy "$t" "$ADS_CONTROL_STATE" 0600; rm -f "$t"; }

OP="${1:-}"
case "$OP" in
  pause) write_pause_state 1 || ads_die "cannot persist pause state"; ads_log "CONTROL|pause"; echo "CONTROL=PASS"; echo "ACTION=PAUSE"; echo "PAUSED=1"; exit 0 ;;
  resume) write_pause_state 0 || ads_die "cannot persist pause state"; ads_log "CONTROL|resume"; echo "CONTROL=PASS"; echo "ACTION=RESUME"; echo "PAUSED=0"; exit 0 ;;
  status) echo "CONTROL=PASS"; echo "PAUSED=$(pause_state)"; echo "ENABLED=${ENABLED:-1}"; echo "RUN_MODE=${RUN_MODE:-scheduled}"; [ -r "$ADS_RUNTIME_STATUS" ] && sed 's/^/RUNTIME_/' "$ADS_RUNTIME_STATUS"; [ -r "$ADS_SCHEDULER_STATUS" ] && sed 's/^/SCHEDULER_/' "$ADS_SCHEDULER_STATUS"; exit 0 ;;
  allow|block|remove|show) ;;
  *) echo "Usage: $0 {pause|resume|status|allow|block|remove|show} [domain] [exact|suffix]" >&2; exit 2 ;;
esac
DOMAIN="$(ads_normalize_domain "${2:-}")"; SCOPE="${3:-exact}"
case "$SCOPE" in exact|suffix) ;; *) ads_die "scope must be exact or suffix" ;; esac
ads_valid_domain "$DOMAIN" || ads_die "invalid domain"
if [ "$OP" = show ]; then
  echo "DOMAIN=$DOMAIN"; echo "ALLOWLIST=$(ads_trust_match_file "$DOMAIN" "$ADS_ALLOWLIST")"; echo "DENYLIST=$(ads_trust_match_file "$DOMAIN" "$ADS_DENYLIST")"; echo "TRUST=$(ads_trust_match_file "$DOMAIN" "$ADS_TRUST_BUILTIN")"; awk -F'|' -v d="$DOMAIN" '$1==d {print; exit}' "$ADS_STATE/verdicts.tsv" 2>/dev/null || true; exit 0
fi

mkdir -p "$ADS_ETC" "$ADS_BACKUP_ROOT/manual" || ads_die "cannot create control directories"
[ -e "$ADS_ALLOWLIST" ] || : > "$ADS_ALLOWLIST"; [ -e "$ADS_DENYLIST" ] || : > "$ADS_DENYLIST"
chmod 0600 "$ADS_ALLOWLIST" "$ADS_DENYLIST" 2>/dev/null || ads_die "cannot protect local rule files"
STAMP="$(date '+%Y%m%d-%H%M%S')"; BACKUP_DIR="$ADS_BACKUP_ROOT/manual/$STAMP"; mkdir -p "$BACKUP_DIR" || ads_die "cannot create control backup"; chmod 0700 "$BACKUP_DIR"
cp -p "$ADS_ALLOWLIST" "$BACKUP_DIR/allowlist.tsv.before" || ads_die "allowlist backup failed"; cp -p "$ADS_DENYLIST" "$BACKUP_DIR/denylist.tsv.before" || ads_die "denylist backup failed"
ALLOW_TMP="${ADS_ALLOWLIST}.new.$$"; DENY_TMP="${ADS_DENYLIST}.new.$$"
trap 'rm -f "$ALLOW_TMP" "$DENY_TMP" "$ALLOW_TMP.sorted" "$DENY_TMP.sorted"' EXIT
trap 'exit 1' HUP INT TERM
awk -F'|' -v d="$DOMAIN" '$1!=d {print}' "$ADS_ALLOWLIST" > "$ALLOW_TMP" || ads_die "allowlist build failed"; awk -F'|' -v d="$DOMAIN" '$1!=d {print}' "$ADS_DENYLIST" > "$DENY_TMP" || ads_die "denylist build failed"
case "$OP" in allow) printf '%s|%s|manual allow; never auto block\n' "$DOMAIN" "$SCOPE" >> "$ALLOW_TMP" ;; block) printf '%s|%s|manual confirmed block\n' "$DOMAIN" "$SCOPE" >> "$DENY_TMP" ;; remove) ;; esac
sort -u "$ALLOW_TMP" > "$ALLOW_TMP.sorted" || ads_die "allowlist sort failed"; sort -u "$DENY_TMP" > "$DENY_TMP.sorted" || ads_die "denylist sort failed"; mv "$ALLOW_TMP.sorted" "$ALLOW_TMP"; mv "$DENY_TMP.sorted" "$DENY_TMP"; chmod 0600 "$ALLOW_TMP" "$DENY_TMP"
mv "$ALLOW_TMP" "$ADS_ALLOWLIST" || ads_die "allowlist install failed"
if ! mv "$DENY_TMP" "$ADS_DENYLIST"; then cp -p "$BACKUP_DIR/allowlist.tsv.before" "$ADS_ALLOWLIST" 2>/dev/null || true; cp -p "$BACKUP_DIR/denylist.tsv.before" "$ADS_DENYLIST" 2>/dev/null || true; ads_die "denylist install failed; rollback attempted"; fi

REBUILD="${VWARD_ADS_RULES_REBUILD:-/opt/bin/vward-ads-privacy-rules-rebuild.sh}"; [ -x "$REBUILD" ] || REBUILD="$SELF_DIR/vward-ads-privacy-rules-rebuild.sh"
if ! "$REBUILD" >/dev/null 2>&1; then cp -p "$BACKUP_DIR/allowlist.tsv.before" "$ADS_ALLOWLIST" 2>/dev/null || true; cp -p "$BACKUP_DIR/denylist.tsv.before" "$ADS_DENYLIST" 2>/dev/null || true; "$REBUILD" >/dev/null 2>&1 || true; ads_die "rule rebuild failed; manual rule files rolled back"; fi

PUBLISHED=NO
if ads_bool "${AUTO_PUBLISH:-0}" && [ "${PUBLISH_MODE:-staged}" = user_rules_api ]; then
  PUB="${VWARD_ADS_PUBLISHER:-/opt/bin/vward-ads-privacy-publish.sh}"; [ -x "$PUB" ] || PUB="$SELF_DIR/vward-ads-privacy-publish.sh"
  if "$PUB" apply --confirm >/dev/null 2>&1; then PUBLISHED=YES; else ads_log "CONTROL|publish_failed|op=$OP|domain=$DOMAIN"; PUBLISHED=FAILED; fi
fi
case "$OP" in allow) ACTION=ALLOW ;; block) ACTION=BLOCK ;; remove) ACTION=REMOVE_OVERRIDE ;; esac
echo "CONTROL=PASS"; echo "ACTION=$ACTION"; echo "DOMAIN=$DOMAIN"; echo "SCOPE=$SCOPE"; echo "PUBLISHED=$PUBLISHED"; echo "BACKUP_DIR=$BACKUP_DIR"; ads_log "CONTROL|op=$OP|domain=$DOMAIN|scope=$SCOPE|publish=$PUBLISHED|backup=$BACKUP_DIR"
