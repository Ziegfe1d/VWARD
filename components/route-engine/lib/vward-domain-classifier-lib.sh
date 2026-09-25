#!/bin/sh
VWARD_CLASSIFIER_VERSION="0.2.0-rc.1.fix.12"
VWARD_ROUTE_ETC="${VWARD_ROUTE_ETC:-/opt/etc/vward/route-engine}"
VWARD_ROUTE_STATE="${VWARD_ROUTE_STATE:-/opt/var/lib/vward/route-engine}"
VWARD_CLASSIFIER_CONFIG="${VWARD_CLASSIFIER_CONFIG:-$VWARD_ROUTE_ETC/domain-classifier.conf}"
VWARD_CATEGORY_REGISTRY="${VWARD_CATEGORY_REGISTRY:-$VWARD_ROUTE_ETC/categories.tsv}"
VWARD_CATEGORY_CATALOG_DIR="${VWARD_CATEGORY_CATALOG_DIR:-$VWARD_ROUTE_ETC/catalogs}"
VWARD_AUTO_CLASSIFY_THRESHOLD="${VWARD_AUTO_CLASSIFY_THRESHOLD:-90}"
VWARD_CLASSIFIER_BATCH_SIZE="${VWARD_CLASSIFIER_BATCH_SIZE:-25}"
VWARD_CLASSIFIER_ENABLED="${VWARD_CLASSIFIER_ENABLED:-1}"
VWARD_CLASSIFIER_LOCK="${VWARD_CLASSIFIER_LOCK:-$VWARD_ROUTE_STATE/classifier.lock}"
VWARD_CLASSIFIER_LOCK_STALE_SEC="${VWARD_CLASSIFIER_LOCK_STALE_SEC:-900}"

vdc_num(){ case "${1:-}" in ''|*[!0-9]*) printf '%s\n' "$2";; *) printf '%s\n' "$1";; esac; }
vdc_secure_file_ok(){
  [ -r "$1" ] || return 1
  # Keenetic's BusyBox stat has no -c, so owner and mode come from ls.
  vdc_meta="$(ls -ln "$1" 2>/dev/null | awk '{sub(/[.+]$/, "", $1); print $3, $1}')"
  case "$vdc_meta" in '0 -rw-------'|'0 -r--------') return 0;; *) return 1;; esac
}
vdc_load_config(){
  [ -r "$VWARD_CLASSIFIER_CONFIG" ] || return 0
  if [ "${VWARD_REQUIRE_SECURE_CONFIG:-1}" = 1 ] && ! vdc_secure_file_ok "$VWARD_CLASSIFIER_CONFIG"; then
    echo "classifier config must be root-owned and mode 0600 or 0400" >&2; return 1
  fi
  . "$VWARD_CLASSIFIER_CONFIG"
  VWARD_AUTO_CLASSIFY_THRESHOLD="$(vdc_num "${AUTO_CLASSIFY_THRESHOLD:-$VWARD_AUTO_CLASSIFY_THRESHOLD}" 90)"
  VWARD_CLASSIFIER_BATCH_SIZE="$(vdc_num "${CLASSIFIER_BATCH_SIZE:-$VWARD_CLASSIFIER_BATCH_SIZE}" 25)"
  [ "$VWARD_AUTO_CLASSIFY_THRESHOLD" -ge 70 ] && [ "$VWARD_AUTO_CLASSIFY_THRESHOLD" -le 100 ] || { echo "AUTO_CLASSIFY_THRESHOLD out of range" >&2; return 1; }
  [ "$VWARD_CLASSIFIER_BATCH_SIZE" -ge 1 ] && [ "$VWARD_CLASSIFIER_BATCH_SIZE" -le 100 ] || { echo "CLASSIFIER_BATCH_SIZE out of range" >&2; return 1; }
  case "${MIGRATION_MODE:-dry-run}" in off|dry-run) ;; *) echo "MIGRATION_MODE must be off or dry-run" >&2; return 1;; esac
  case "${CLASSIFIER_ENABLED:-1}" in 0|1) VWARD_CLASSIFIER_ENABLED="${CLASSIFIER_ENABLED:-1}" ;; *) echo "CLASSIFIER_ENABLED must be 0 or 1" >&2; return 1;; esac
}
vdc_lock_acquire(){
  vdc_la_now="$(date +%s)"; mkdir -p "$VWARD_ROUTE_STATE" || return 1
  if mkdir "$VWARD_CLASSIFIER_LOCK" 2>/dev/null; then printf '%s\n' "$$" > "$VWARD_CLASSIFIER_LOCK/pid"; printf '%s\n' "$vdc_la_now" > "$VWARD_CLASSIFIER_LOCK/started"; return 0; fi
  vdc_la_pid="$(cat "$VWARD_CLASSIFIER_LOCK/pid" 2>/dev/null)"; case "$vdc_la_pid" in ''|*[!0-9]*) vdc_la_pid=0;; esac
  [ "$vdc_la_pid" -gt 0 ] && kill -0 "$vdc_la_pid" 2>/dev/null && return 1
  vdc_la_started="$(vdc_num "$(cat "$VWARD_CLASSIFIER_LOCK/started" 2>/dev/null)" 0)"
  [ "$vdc_la_started" -eq 0 ] || [ $((vdc_la_now-vdc_la_started)) -ge "$(vdc_num "$VWARD_CLASSIFIER_LOCK_STALE_SEC" 900)" ] || return 1
  rm -rf "$VWARD_CLASSIFIER_LOCK" 2>/dev/null || return 1
  mkdir "$VWARD_CLASSIFIER_LOCK" 2>/dev/null || return 1
  printf '%s\n' "$$" > "$VWARD_CLASSIFIER_LOCK/pid"; printf '%s\n' "$vdc_la_now" > "$VWARD_CLASSIFIER_LOCK/started"
}
vdc_lock_release(){ [ -n "${VWARD_CLASSIFIER_LOCK:-}" ] && rm -rf "$VWARD_CLASSIFIER_LOCK" 2>/dev/null || true; }

vdc_normalize_host(){ printf '%s\n' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//;s/^\.//;s/\.$//'; }
vdc_valid_host(){ printf '%s\n' "$1" | awk 'length($0)<1||length($0)>253||$0~/\.\./||$0!~/^[a-z0-9_][a-z0-9_.-]*[a-z0-9_]$/||index($0,".")==0{exit 1}{exit 0}'; }
vdc_valid_route_fqdn(){ printf '%s\n' "$1" | awk 'length($0)<1||length($0)>253||index($0,".")==0{exit 1}{n=split($0,a,".");for(i=1;i<=n;i++)if(length(a[i])<1||length(a[i])>63||a[i]!~/^[a-z0-9][a-z0-9-]*[a-z0-9]$/&&a[i]!~/^[a-z0-9]$/)exit 1;exit 0}'; }
vdc_registry_rows(){ [ -r "$VWARD_CATEGORY_REGISTRY" ] || return 1; awk -F'|' 'NF>=5&&$1!~/^[[:space:]]*#/&&$5==1{print}' "$VWARD_CATEGORY_REGISTRY"; }
vdc_catalog_path(){ vdc_registry_rows | awk -F'|' -v c="$1" '$1==c{print $4;exit}' | sed "s#^@catalogs/#$VWARD_CATEGORY_CATALOG_DIR/#"; }
vdc_best_in_file(){
  vdc_bf_host="$1"; vdc_bf_file="$2"; [ -r "$vdc_bf_file" ] || return 1
  awk -v h="$vdc_bf_host" '/^[[:space:]]*#/||/^[[:space:]]*$/{next}{d=tolower($1);sub(/^\*\./,"",d);sub(/^\./,"",d);sub(/\.$/,"",d);if(h==d){print "100|exact_catalog_match:" d;exit}if(length(h)>length(d)&&substr(h,length(h)-length(d))=="." d&&length(d)>best){best=length(d);reason=d}}END{if(best>0)print "95|parent_domain:" reason}' "$vdc_bf_file" | head -n1
}
vdc_classify(){
  vdc_host="$(vdc_normalize_host "$1")"
  if ! vdc_valid_host "$vdc_host"; then printf 'UNKNOWN|0|invalid_host|none\n'; return 2; fi
  vdc_hits="${TMPDIR:-/tmp}/vward-classify-hits.$$"; : > "$vdc_hits" || return 3
  vdc_registry_rows | while IFS='|' read -r vdc_cat vdc_title vdc_target vdc_catalog vdc_enabled; do
    vdc_file="$(printf '%s\n' "$vdc_catalog" | sed "s#^@catalogs/#$VWARD_CATEGORY_CATALOG_DIR/#")"
    vdc_match="$(vdc_best_in_file "$vdc_host" "$vdc_file" 2>/dev/null || true)"
    [ -n "$vdc_match" ] && printf '%s|%s|local_catalog\n' "$vdc_cat" "$vdc_match" >> "$vdc_hits"
  done
  vdc_max="$(awk -F'|' 'BEGIN{m=0}$2>m{m=$2}END{print m}' "$vdc_hits")"
  vdc_count="$(awk -F'|' -v m="$vdc_max" '$2==m{n++}END{print n+0}' "$vdc_hits")"
  if [ "$vdc_count" -gt 1 ]; then vdc_categories="$(awk -F'|' -v m="$vdc_max" '$2==m{printf "%s%s",s,$1;s=","}' "$vdc_hits")"; rm -f "$vdc_hits"; printf 'CONFLICT|%s|category_conflict:%s|local_catalog\n' "$vdc_max" "$vdc_categories"; return 4; fi
  if [ "$vdc_count" -eq 1 ]; then vdc_result="$(awk -F'|' -v m="$vdc_max" '$2==m{print $1"|"$2"|"$3"|"$4;exit}' "$vdc_hits")"; rm -f "$vdc_hits"; printf '%s\n' "$vdc_result"; return 0; fi
  rm -f "$vdc_hits"; printf 'UNKNOWN|0|no_category_evidence|none\n'; return 1
}
vdc_target_group(){ vdc_registry_rows | awk -F'|' -v c="$1" '$1==c{print $3;exit}'; }
vdc_catalog_add() (
  vdc_ca_category="$1"; vdc_ca_host="$(vdc_normalize_host "$2")"; vdc_valid_route_fqdn "$vdc_ca_host" || return 2
  vdc_ca_file="$(vdc_catalog_path "$vdc_ca_category")"; [ -n "$vdc_ca_file" ] || return 3
  mkdir -p "$(dirname "$vdc_ca_file")" || return 4
  vdc_lock_acquire || return 7
  trap 'vdc_lock_release; command -v vward_admission_leave >/dev/null 2>&1 && vward_admission_leave 2>/dev/null || true' EXIT
  trap 'exit 1' HUP INT TERM
  if [ -r "$vdc_ca_file" ] && awk -v d="$vdc_ca_host" '$1==d{f=1}END{exit !f}' "$vdc_ca_file"; then return 0; fi
  vdc_ca_tmp="${vdc_ca_file}.new.$$"; { [ -r "$vdc_ca_file" ] && cat "$vdc_ca_file"; printf '%s\n' "$vdc_ca_host"; } | awk 'NF&&$1!~/^#/' | sort -u > "$vdc_ca_tmp" || { rm -f "$vdc_ca_tmp"; return 5; }
  chmod 0600 "$vdc_ca_tmp" || { rm -f "$vdc_ca_tmp"; return 6; }; mv "$vdc_ca_tmp" "$vdc_ca_file"
)
