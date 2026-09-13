#!/bin/sh
set -u
LIB="${VWARD_DOMAIN_CLASSIFIER_LIB:-/opt/lib/vward/vward-domain-classifier-lib.sh}"
[ -r "$LIB" ] || { echo MIGRATION=FAIL; echo REASON=library_missing; exit 2; }; . "$LIB"
vdc_load_config || { echo MIGRATION=FAIL; echo REASON=config_invalid; exit 2; }
case "${MIGRATION_MODE:-dry-run}" in off) echo MIGRATION=OFF; exit 0;; dry-run) ;; esac
host="$(vdc_normalize_host "${1:-}")"; result="$(vdc_classify "$host")" || true
IFS='|' read -r category confidence reason source <<EOF
$result
EOF
case "$confidence" in ''|*[!0-9]*) confidence=0;; esac
if [ "$category" = UNKNOWN ] || [ "$category" = CONFLICT ] || [ "$confidence" -lt "$VWARD_AUTO_CLASSIFY_THRESHOLD" ]; then printf 'MIGRATION=HOLD\nHOST=%s\nCATEGORY=%s\nCONFIDENCE=%s\nREASON=%s\nADAPTIVEAUTO=RETAIN\n' "$host" "$category" "$confidence" "$reason"; exit 1; fi
target="$(vdc_target_group "$category")"
if [ -z "$target" ] || [ "$target" = AUTO ]; then printf 'MIGRATION=CATALOG_ONLY\nHOST=%s\nCATEGORY=%s\nCONFIDENCE=%s\nREASON=target_group_unresolved\nADAPTIVEAUTO=RETAIN\n' "$host" "$category" "$confidence"; exit 0; fi
printf 'MIGRATION=DRY_RUN\nHOST=%s\nCATEGORY=%s\nCONFIDENCE=%s\nREASON=%s\nTARGET_GROUP=%s\nWOULD_ADD_TARGET_FIRST=YES\nWOULD_VERIFY_TARGET=YES\nWOULD_REMOVE_ADAPTIVEAUTO_LAST=YES\n' "$host" "$category" "$confidence" "$reason" "$target"
