#!/bin/sh
# Release rehearsal: builds the real candidate from this tree, signs it through
# scripts/prepare-dev-release.sh with a throwaway key, applies it over a root that
# models an installed 0.1.9-beta router, checks the full health profile and rolls
# it back. When origin/beta is available the root is seeded with the files of the
# real signed beta packages; otherwise with a beta VERSION only.

set -eu

REPO=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
UPDATER=$REPO/components/update-engine
WORK=$(mktemp -d "${TMPDIR:-/tmp}/vward-release-rehearsal.XXXXXX")
trap 'rm -rf "$WORK"' EXIT HUP INT TERM

BETA_VERSION=0.1.9-beta
BETA_SEQUENCE=2026091701
SEQUENCE=$((BETA_SEQUENCE + 1))
VERSION=$(sed -n '1p' "$REPO/VERSION")

passed=0
failed=0
n=0
pass() { passed=$((passed + 1)); n=$((n + 1)); printf 'ok %s - %s\n' "$n" "$1"; }
fail() { failed=$((failed + 1)); n=$((n + 1)); printf 'not ok %s - %s\n' "$n" "$1"; }
check() { name=$1; shift; if "$@"; then pass "$name"; else fail "$name"; fi; }

openssl genpkey -algorithm ED25519 -out "$WORK/private.pem" >/dev/null 2>&1
openssl pkey -in "$WORK/private.pem" -pubout -out "$WORK/public.pem" >/dev/null 2>&1

# A rehearsal key must never reach the feed.
feed_before=$(sha256sum "$REPO/updates/dev/update-manifest.json" | awk '{print $1}')
set +e
VWARD_SIGNING_KEY_FILE=$WORK/private.pem VWARD_REHEARSAL_PUBLIC_KEY=$WORK/public.pem \
    "$REPO/scripts/prepare-dev-release.sh" "$WORK/refused" "$SEQUENCE" "$BETA_VERSION" --stage >/dev/null 2>&1
code=$?
set -e
feed_after=$(sha256sum "$REPO/updates/dev/update-manifest.json" | awk '{print $1}')
check 'rehearsal key cannot be staged' test "$code" -ne 0 -a "$feed_before" = "$feed_after" -a ! -e "$WORK/refused"

VWARD_SIGNING_KEY_FILE=$WORK/private.pem VWARD_REHEARSAL_PUBLIC_KEY=$WORK/public.pem \
    "$REPO/scripts/prepare-dev-release.sh" "$WORK/release" "$SEQUENCE" "$BETA_VERSION" > "$WORK/release.out"
MANIFEST=$WORK/release/update-manifest.json
PACKAGE=$WORK/release/candidate/vward-$VERSION.tar.gz
check 'release script signs the real candidate' grep -qx 'PUBLISH_READY=YES' "$WORK/release.out"
manifest_ok() { jq -e --arg v "$VERSION" --argjson s "$SEQUENCE" '.signed.version == $v and .signed.sequence == $s and .signed.health_profile == "full"' "$MANIFEST" >/dev/null; }
check 'manifest names this VERSION and sequence' manifest_ok
check 'manifest package digest matches the candidate' \
    test "$(jq -r '.signed.package.sha256' "$MANIFEST")" = "$(sha256sum "$PACKAGE" | awk '{print $1}')"

ROOT=$WORK/root
mkdir -p "$ROOT/opt/etc/vward" "$ROOT/opt/share/vward" "$ROOT/opt/var/lib/vward/updater"
seed=minimal
if git -C "$REPO" rev-parse --verify -q origin/beta >/dev/null 2>&1; then
    seed=beta-packages
    for v in $(git -C "$REPO" ls-tree --name-only origin/beta updates/dev/packages/ | sed -n 's|.*/vward-\(.*\)\.tar\.gz$|\1|p' | sort -V); do
        old=$WORK/beta-$v
        mkdir -p "$old"
        git -C "$REPO" show "origin/beta:updates/dev/packages/vward-$v.tar.gz" > "$old.tar.gz"
        tar -xzf "$old.tar.gz" -C "$old" 2>/dev/null || continue
        [ -r "$old/package-manifest.json" ] || continue
        jq -r '.files[] | [.source, .target] | @tsv' "$old/package-manifest.json" |
        while IFS="$(printf '\t')" read -r source target; do
            mkdir -p "$ROOT$(dirname "$target")"
            cp "$old/$source" "$ROOT$target"
        done
    done
fi
printf '%s\n' "$BETA_VERSION" > "$ROOT/opt/share/vward/VERSION"
printf 'installed_version=%s\ninstalled_update_id=vward-%s\nlast_sequence=%s\nmanifest_hash=beta\nlast_health_check=beta\n' \
    "$BETA_VERSION" "$BETA_VERSION" "$BETA_SEQUENCE" > "$ROOT/opt/var/lib/vward/updater/committed.state"
cp "$WORK/public.pem" "$ROOT/opt/etc/vward/update-public.pem"
CONFIG=$ROOT/opt/etc/vward/update.conf
{
    printf '%s\n' 'update_enabled=1' 'auto_apply=0' 'channel=dev'
    printf 'public_key_file=%s\n' "$ROOT/opt/etc/vward/update-public.pem"
    printf 'current_version_file=%s\n' "$ROOT/opt/share/vward/VERSION"
    printf '%s\n' 'minimum_free_kb=1' 'barrier_integration_ready=1' 'apply_window=any'
} > "$CONFIG"
printf '# seed=%s\n' "$seed"

# Snapshot of the beta root: every file with its digest.
snapshot() { (cd "$ROOT/opt" && find . -type f ! -path './var/*' ! -path './etc/vward/update.conf' -exec sha256sum {} + | LC_ALL=C sort -k2); }
snapshot > "$WORK/before.sums"

run_update() {
    VWARD_ROOT_PREFIX=$ROOT VWARD_UPDATE_CONFIG=$CONFIG VWARD_TEST_MANIFEST=$MANIFEST VWARD_TEST_PACKAGE=$PACKAGE \
        "$UPDATER/vward-update.sh" "$@"
}

set +e
run_update --apply > "$WORK/apply.out" 2>&1
code=$?
set -e
[ "$code" -eq 0 ] || sed 's/^/  # /' "$WORK/apply.out"
check "beta $BETA_VERSION upgrades to $VERSION" test "$code" -eq 0
check 'installed VERSION is the candidate' test "$(cat "$ROOT/opt/share/vward/VERSION")" = "$VERSION"

mismatch=0
tar -xzOf "$PACKAGE" ./package-manifest.json | jq -r '.files[] | [.target, .sha256, .mode] | @tsv' > "$WORK/targets.tsv"
while IFS="$(printf '\t')" read -r target sha mode; do
    [ "$(sha256sum "$ROOT$target" 2>/dev/null | awk '{print $1}')" = "$sha" ] || { printf '  # digest %s\n' "$target"; mismatch=1; }
    [ "$mode" != 0755 ] || [ -x "$ROOT$target" ] || { printf '  # mode %s\n' "$target"; mismatch=1; }
done < "$WORK/targets.tsv"
check 'every package target matches its signed digest and mode' test "$mismatch" -eq 0

health_ok() { VWARD_ROOT_PREFIX=$ROOT VWARD_UPDATE_CONFIG=$CONFIG "$UPDATER/vward-update-health.sh" full >/dev/null 2>&1; }
check 'full health profile passes on the upgraded root' health_ok

# Files the candidate does not own stay as they were on the beta router.
untouched=0
cut -f1 "$WORK/targets.tsv" | sed 's|^/opt|.|' | LC_ALL=C sort > "$WORK/owned"
awk 'NR==FNR {owned[$1]=1; next} !($2 in owned)' "$WORK/owned" "$WORK/before.sums" > "$WORK/foreign.before"
snapshot | awk 'NR==FNR {owned[$1]=1; next} !($2 in owned)' "$WORK/owned" - > "$WORK/foreign.after"
cmp -s "$WORK/foreign.before" "$WORK/foreign.after" || untouched=1
check 'files outside the package are untouched' test "$untouched" -eq 0

set +e
run_update --apply > "$WORK/replay.out" 2>&1
code=$?
set -e
check 'the same manifest is not applied twice' test "$code" -ne 0 -a "$code" -ne 40 -a "$code" -ne 41

set +e
env VWARD_ROOT_PREFIX="$ROOT" VWARD_UPDATE_CONFIG="$CONFIG" "$UPDATER/vward-update-rollback.sh" > "$WORK/rollback.out" 2>&1
code=$?
set -e
[ "$code" -eq 0 ] || sed 's/^/  # /' "$WORK/rollback.out"
check 'rollback returns to beta' test "$code" -eq 0
snapshot > "$WORK/after.sums"
if cmp -s "$WORK/before.sums" "$WORK/after.sums"; then
    pass 'rollback restores every beta file and removes new ones'
else
    diff "$WORK/before.sums" "$WORK/after.sums" | sed -n '1,20s/^/  # /p'
    fail 'rollback restores every beta file and removes new ones'
fi
check 'VERSION after rollback is beta' test "$(cat "$ROOT/opt/share/vward/VERSION")" = "$BETA_VERSION"

printf '1..%s\n' "$((passed + failed))"
[ "$failed" -eq 0 ]
