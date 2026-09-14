#!/bin/sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
TMP="${TMPDIR:-/tmp}/vward-domain-tests.$$"; trap 'rm -rf "$TMP"' EXIT INT TERM
mkdir -p "$TMP/etc/catalogs" "$TMP/state"
LIB="$ROOT/components/route-engine/lib/vward-domain-classifier-lib.sh"
CLI="$ROOT/components/route-engine/scripts/vward-domain-classifier.sh"
DRY="$ROOT/components/route-engine/scripts/vward-domain-migrate-dry-run.sh"
fail(){ echo "FAIL: $*" >&2; exit 1; }; pass(){ echo "PASS: $*"; }

cp "$ROOT/config/route-engine/categories.tsv.example" "$TMP/etc/categories.tsv"
for f in "$ROOT"/components/route-engine/data/catalogs/*.domains; do cp "$f" "$TMP/etc/catalogs/$(basename "$f")"; done
# CI runners are intentionally unprivileged; production keeps this check enabled.
ENV="VWARD_REQUIRE_SECURE_CONFIG=0 VWARD_DOMAIN_CLASSIFIER_LIB=$LIB VWARD_ROUTE_ETC=$TMP/etc VWARD_ROUTE_STATE=$TMP/state VWARD_CATEGORY_REGISTRY=$TMP/etc/categories.tsv VWARD_CATEGORY_CATALOG_DIR=$TMP/etc/catalogs"

cat > "$TMP/etc/domain-classifier.conf" <<'EOF2'
AUTO_CLASSIFY_THRESHOLD=96
CLASSIFIER_BATCH_SIZE=2
MIGRATION_MODE=dry-run
EOF2
chmod 0600 "$TMP/etc/domain-classifier.conf"
ENV="$ENV VWARD_CLASSIFIER_CONFIG=$TMP/etc/domain-classifier.conf"

out="$(env $ENV busybox sh "$CLI" classify steampowered.com)" || fail exact_steam
printf '%s\n' "$out" | grep -q '^CATEGORY=steam$' || fail exact_category
printf '%s\n' "$out" | grep -q '^CONFIDENCE=100$' || fail exact_confidence
pass "T01 exact Steam"

out="$(env $ENV busybox sh "$CLI" classify images.cdn.steamstatic.com)" || fail child_steam
printf '%s\n' "$out" | grep -q '^CONFIDENCE=95$' || fail child_confidence
printf '%s\n' "$out" | grep -q '^REASON=parent_domain:steamstatic.com$' || fail child_reason
pass "T02 parent to child inheritance"

if env $ENV busybox sh "$CLI" classify unknown.example > "$TMP/unknown"; then fail unknown_rc; fi
grep -q '^CATEGORY=UNKNOWN$' "$TMP/unknown" || fail unknown_category
pass "T08 unknown retained"

printf '%s\n' shared.example >> "$TMP/etc/catalogs/steam.domains"
printf '%s\n' shared.example >> "$TMP/etc/catalogs/epic-games.domains"
if env $ENV busybox sh "$CLI" classify cdn.shared.example > "$TMP/conflict"; then fail conflict_rc; fi
grep -q '^CATEGORY=CONFLICT$' "$TMP/conflict" || fail conflict_category
pass "T09 equal-confidence conflict"

if env $ENV busybox sh "$CLI" catalog-add steam new.steam.test 95 > "$TMP/low"; then fail low_threshold_rc; fi
grep -q '^CATALOG_ADD=SKIPPED$' "$TMP/low" || fail low_threshold
! grep -q '^new.steam.test$' "$TMP/etc/catalogs/steam.domains" || fail low_written
env $ENV busybox sh "$CLI" catalog-add steam new.steam.test 96 | grep -q '^CATALOG_ADD=PASS$' || fail catalog_add
[ "$(grep -c '^new.steam.test$' "$TMP/etc/catalogs/steam.domains")" -eq 1 ] || fail catalog_duplicate
env $ENV busybox sh "$CLI" catalog-add steam new.steam.test 100 >/dev/null || fail catalog_idempotent
[ "$(grep -c '^new.steam.test$' "$TMP/etc/catalogs/steam.domains")" -eq 1 ] || fail catalog_idempotence
pass "T16 atomic catalog deduplication"

mkdir "$TMP/state/classifier.lock"; echo $$ > "$TMP/state/classifier.lock/pid"; date +%s > "$TMP/state/classifier.lock/started"
if env $ENV busybox sh "$CLI" catalog-add steam locked.steam.test 100 > "$TMP/locked"; then fail live_lock_ignored; fi
! grep -q '^locked.steam.test$' "$TMP/etc/catalogs/steam.domains" || fail lock_write
rm -rf "$TMP/state/classifier.lock"
pass "T22 live classifier lock blocks mutation"

if env $ENV busybox sh "$CLI" catalog-add steam _service.steam.test 100 > "$TMP/unsafe"; then fail unsafe_route_name; fi
! grep -q '^_service.steam.test$' "$TMP/etc/catalogs/steam.domains" || fail unsafe_route_written
pass "strict route FQDN validation"

printf 'steampowered.com\nepicgames.com\nx.com\n' | env $ENV busybox sh "$CLI" batch > "$TMP/batch"
[ "$(wc -l < "$TMP/batch")" -eq 2 ] || fail configured_batch_limit
pass "validated config and bounded batch"

if env $ENV busybox sh "$CLI" classify steam.test > "$TMP/upward"; then fail child_to_parent; fi
grep -q '^CATEGORY=UNKNOWN$' "$TMP/upward" || fail upward_unknown
pass "T30 child to parent escalation forbidden"

env $ENV busybox sh "$DRY" steampowered.com > "$TMP/dry" || fail dry_run
grep -q '^MIGRATION=CATALOG_ONLY$' "$TMP/dry" || fail missing_target_catalog_only
grep -q '^ADAPTIVEAUTO=RETAIN$' "$TMP/dry" || fail adaptive_retain
pass "T17 unresolved target is non-destructive"

echo DOMAIN_CLASSIFIER_SIMULATIONS=PASS
