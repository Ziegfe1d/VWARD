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
AUTO_RULE_SCOPE="${AUTO_RULE_SCOPE:-exact}"
case "$AUTO_RULE_SCOPE" in exact|suffix) ;; *) ads_die "invalid AUTO_RULE_SCOPE" ;; esac
VERDICTS="$ADS_STATE/verdicts.tsv"; OUT="$ADS_STATE/generated/vward-ads-privacy-guard.rules"; TMP="$ADS_STATE/work/rules-rebuild.$$"
{
  echo "! VWARD Ads & Privacy Guard"
  echo "! generated: $(ads_now)"
  echo "! ownership: VWARD managed rules only"
  if [ -r "$VERDICTS" ]; then
    awk -F'|' '$3=="BLOCK" && $8!="manual_denylist" {print $1}' "$VERDICTS" | while IFS= read -r d; do
      [ -n "$d" ] || continue
      ads_allowlist_match "$d" && continue
      ads_rule_for "$d" "$AUTO_RULE_SCOPE"
    done
  fi
  if [ -r "$ADS_DENYLIST" ]; then
    awk -F'|' '/^[[:space:]]*#/ || NF<2 {next} {print tolower($1) "|" tolower($2)}' "$ADS_DENYLIST" | while IFS='|' read -r d scope; do
      [ -n "$d" ] || continue
      ads_rule_for "$d" "$scope"
    done
  fi
} | awk '!seen[$0]++' > "$TMP" || ads_die "cannot build rules"
ads_atomic_copy "$TMP" "$OUT" 0644 || ads_die "cannot install generated rules"
rm -f "$TMP"
echo "RULES_REBUILD=PASS"
echo "RULES_FILE=$OUT"
echo "RULE_COUNT=$(awk 'NF && $0 !~ /^[!#]/ {n++} END{print n+0}' "$OUT")"
