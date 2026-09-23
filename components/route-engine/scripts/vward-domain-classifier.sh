#!/bin/sh
set -u
LIB="${VWARD_DOMAIN_CLASSIFIER_LIB:-/opt/lib/vward/vward-domain-classifier-lib.sh}"
[ -r "$LIB" ] || { echo CLASSIFIER=FAIL; echo REASON=library_missing; exit 2; }; . "$LIB"
vdc_load_config || { echo CLASSIFIER=FAIL; echo REASON=config_invalid; exit 2; }
case "${1:-classify}" in
 classify) host="${2:-}"; result="$(vdc_classify "$host")"; rc=$?; IFS='|' read -r category confidence reason source <<EOF
$result
EOF
 printf 'HOST=%s\nCATEGORY=%s\nCONFIDENCE=%s\nREASON=%s\nSOURCE=%s\n' "$(vdc_normalize_host "$host")" "$category" "$confidence" "$reason" "$source"; exit "$rc";;
 batch) limit="$VWARD_CLASSIFIER_BATCH_SIZE"; n=0; while IFS= read -r host && [ "$n" -lt "$limit" ]; do [ -n "$host" ] || continue; result="$(vdc_classify "$host")" || true; printf '%s|%s\n' "$(vdc_normalize_host "$host")" "$result"; n=$((n+1)); done;;
 catalog-add)
  # Automatic categorisation of new domains switched off in the Console.
  [ "$VWARD_CLASSIFIER_ENABLED" = 1 ] || { echo CATALOG_ADD=SKIPPED; echo REASON=classifier_disabled; exit 0; }
  VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
  [ -r "$VWARD_ADMISSION_LIB" ] || VWARD_ADMISSION_LIB="$(CDPATH= cd -- "$(dirname -- "$0")/../../runtime/lib" 2>/dev/null && pwd)/vward-runtime-admission.sh"
  [ -r "$VWARD_ADMISSION_LIB" ] || { echo CATALOG_ADD=FAIL; echo REASON=admission_library_missing; exit 2; }
  . "$VWARD_ADMISSION_LIB"
  vward_admission_enter domain-classifier || exit $?
  trap vward_admission_leave EXIT
  trap 'exit 1' HUP INT TERM
  category="${2:-}"; host="${3:-}"; confidence="${4:-0}"
  case "$confidence" in ''|*[!0-9]*) echo CATALOG_ADD=FAIL; exit 2;; esac
  [ "$confidence" -ge "$VWARD_AUTO_CLASSIFY_THRESHOLD" ] || { echo CATALOG_ADD=SKIPPED; echo REASON=below_threshold; exit 1; }
  vdc_catalog_add "$category" "$host" || { echo CATALOG_ADD=FAIL; exit 3; }
  echo CATALOG_ADD=PASS
  ;;
 *) echo "Usage: $0 classify HOST | batch | catalog-add CATEGORY HOST CONFIDENCE" >&2; exit 64;;
esac
