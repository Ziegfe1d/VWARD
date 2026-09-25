#!/bin/sh
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "FAIL: common library not found" >&2; exit 1; }
. "$LIB"
ads_admission_enter ads-control
trap ads_admission_leave EXIT
trap 'exit 1' HUP INT TERM
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
  agh) ;;
  *) echo "Usage: $0 {pause|resume|status|allow|block|remove|show|agh} [domain] [exact|suffix]" >&2; exit 2 ;;
esac

# agh SETTING ARGS: AdGuard Home's own ad settings, each change read back.
#   protection|filtering|safebrowsing|parental|safesearch 0|1
#   interval HOURS (0 1 12 24 72 168)      filters-refresh
#   filter-enable URL 0|1   filter-add URL NAME   filter-remove URL
#   service ID 0|1
if [ "$OP" = agh ]; then
  W="$(mktemp -d "${TMPDIR:-/tmp}/vward-ads-agh.XXXXXX" 2>/dev/null)" || ads_die "cannot create a work directory"
  trap 'rm -rf "$W"; ads_admission_leave' EXIT
  AG_SET="${2:-}" A1="${3:-}" A2="${4:-}"
  agfail() { echo "CONTROL=FAIL"; echo "ERROR=$1"; ads_log "CONTROL|agh|$AG_SET|error=$1"; exit 1; }
  bool() { case "$1" in 1) echo true ;; 0) echo false ;; *) agfail invalid_value ;; esac; }
  jpost() { printf '%s' "$2" > "$W/body.json"; ads_agh_api_post "$1" "$W/body.json" "$W/out" >/dev/null 2>&1; }
  jput() { printf '%s' "$2" > "$W/body.json"; ads_agh_api_put "$1" "$W/body.json" "$W/out" >/dev/null 2>&1; }
  aget() { ads_agh_api_get "$1" "$W/$2" >/dev/null 2>&1; }
  valid_url() { printf '%s\n' "$1" | grep -Eq '^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?/[A-Za-z0-9._~/%+=&?-]*$' && [ "${#1}" -le 300 ]; }
  aget status status.json || agfail adguard_unavailable
  case "$AG_SET" in
    protection)
      B=$(bool "$A1")
      jpost protection "{\"enabled\":$B}" || jpost dns_config "{\"protection_enabled\":$B}" || agfail adguard_rejected
      aget status status.json && "$ADS_JQ" -e --argjson b "$B" '.protection_enabled == $b' "$W/status.json" >/dev/null || agfail verification_failed ;;
    filtering|interval)
      aget filtering/status filtering.json || agfail adguard_unavailable
      if [ "$AG_SET" = filtering ]; then B=$(bool "$A1"); I=$("$ADS_JQ" -r '.interval // 24' "$W/filtering.json")
      else case "$A1" in 0|1|12|24|72|168) I=$A1 ;; *) agfail invalid_value ;; esac; B=$("$ADS_JQ" -r '.enabled == true' "$W/filtering.json"); fi
      jpost filtering/config "{\"enabled\":$B,\"interval\":$I}" || agfail adguard_rejected
      aget filtering/status filtering.json && "$ADS_JQ" -e --argjson b "$B" --argjson i "$I" '.enabled == $b and .interval == $i' "$W/filtering.json" >/dev/null || agfail verification_failed ;;
    safebrowsing|parental)
      B=$(bool "$A1"); E=disable; [ "$B" = true ] && E=enable
      jpost "$AG_SET/$E" "" || agfail adguard_rejected
      aget "$AG_SET/status" x.json && "$ADS_JQ" -e --argjson b "$B" '.enabled == $b' "$W/x.json" >/dev/null || agfail verification_failed ;;
    safesearch)
      B=$(bool "$A1")
      if aget safesearch/status ss.json && "$ADS_JQ" -e 'has("bing")' "$W/ss.json" >/dev/null 2>&1; then
        jput safesearch/settings "$("$ADS_JQ" -c --argjson b "$B" '.enabled = $b' "$W/ss.json")" || agfail adguard_rejected
      else
        E=disable; [ "$B" = true ] && E=enable; jpost "safesearch/$E" "" || agfail adguard_rejected
      fi
      aget safesearch/status ss.json && "$ADS_JQ" -e --argjson b "$B" '.enabled == $b' "$W/ss.json" >/dev/null || agfail verification_failed ;;
    filters-refresh)
      jpost filtering/refresh '{"whitelist":false}' || agfail adguard_rejected ;;
    filter-enable)
      valid_url "$A1" || agfail invalid_url; B=$(bool "$A2")
      aget filtering/status filtering.json || agfail adguard_unavailable
      NAME=$("$ADS_JQ" -r --arg u "$A1" '[.filters[]? | select(.url == $u)][0].name // empty' "$W/filtering.json")
      [ -n "$NAME" ] || agfail unknown_filter
      jpost filtering/set_url "$("$ADS_JQ" -cn --arg u "$A1" --arg n "$NAME" --argjson b "$B" '{url: $u, whitelist: false, data: {name: $n, url: $u, enabled: $b}}')" || agfail adguard_rejected
      aget filtering/status filtering.json && "$ADS_JQ" -e --arg u "$A1" --argjson b "$B" 'any(.filters[]?; .url == $u and .enabled == $b)' "$W/filtering.json" >/dev/null || agfail verification_failed ;;
    filter-add)
      valid_url "$A1" || agfail invalid_url
      case "$A2" in ''|*[!A-Za-z0-9\ ._-]*) agfail invalid_name ;; esac; [ "${#A2}" -le 64 ] || agfail invalid_name
      jpost filtering/add_url "$("$ADS_JQ" -cn --arg u "$A1" --arg n "$A2" '{name: $n, url: $u, whitelist: false}')" || agfail adguard_rejected
      aget filtering/status filtering.json && "$ADS_JQ" -e --arg u "$A1" 'any(.filters[]?; .url == $u)' "$W/filtering.json" >/dev/null || agfail verification_failed ;;
    filter-remove)
      valid_url "$A1" || agfail invalid_url
      jpost filtering/remove_url "$("$ADS_JQ" -cn --arg u "$A1" '{url: $u, whitelist: false}')" || agfail adguard_rejected
      aget filtering/status filtering.json && ! "$ADS_JQ" -e --arg u "$A1" 'any(.filters[]?; .url == $u)' "$W/filtering.json" >/dev/null || agfail verification_failed ;;
    service)
      case "$A1" in ''|*[!a-z0-9_]*) agfail invalid_service ;; esac; B=$(bool "$A2")
      if aget blocked_services/get sg.json; then
        NEW=$("$ADS_JQ" -c --arg s "$A1" --argjson b "$B" '.ids = (((.ids // []) - [$s]) + (if $b then [$s] else [] end))' "$W/sg.json")
        jput blocked_services/update "$NEW" || agfail adguard_rejected
        aget blocked_services/get sg.json && "$ADS_JQ" -e --arg s "$A1" --argjson b "$B" '((.ids // []) | index($s) != null) == $b' "$W/sg.json" >/dev/null || agfail verification_failed
      elif aget blocked_services/list sl.json; then
        NEW=$("$ADS_JQ" -c --arg s "$A1" --argjson b "$B" '((. // []) - [$s]) + (if $b then [$s] else [] end)' "$W/sl.json")
        jpost blocked_services/set "$NEW" || agfail adguard_rejected
        aget blocked_services/list sl.json && "$ADS_JQ" -e --arg s "$A1" --argjson b "$B" '((. // []) | index($s) != null) == $b' "$W/sl.json" >/dev/null || agfail verification_failed
      else agfail adguard_unavailable; fi ;;
    *) agfail invalid_setting ;;
  esac
  ads_log "CONTROL|agh|$AG_SET|$A1|$A2|ok"
  echo "CONTROL=PASS"; echo "ACTION=AGH_$(printf '%s' "$AG_SET" | tr 'a-z-' 'A-Z_')"
  exit 0
fi
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
trap 'rm -f "$ALLOW_TMP" "$DENY_TMP" "$ALLOW_TMP.sorted" "$DENY_TMP.sorted"; ads_admission_leave' EXIT
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
