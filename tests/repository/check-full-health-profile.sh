#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
MAP=$ROOT/config/components/package-map.tsv
HEALTH=$ROOT/components/update-engine/vward-update-health.sh
TMP=${TMPDIR:-/tmp}/vward-full-health-test.$$
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP"

while IFS="$(printf '\t')" read -r component source target mode extra
do
    case "$component" in ''|'#'*) continue ;; esac
    destination=$TMP$target
    mkdir -p "$(dirname "$destination")"
    cp "$ROOT/$source" "$destination"
    chmod "$mode" "$destination"
done < "$MAP"

VWARD_ROOT_PREFIX="$TMP" "$HEALTH" full >/dev/null

printf '%s\n' "broken='" >> "$TMP/opt/bin/vward-route.sh"
if VWARD_ROOT_PREFIX="$TMP" "$HEALTH" full >/dev/null 2>&1; then
    echo "FAIL: full health accepted broken shell syntax" >&2
    exit 1
fi

cp "$ROOT/components/route-tools/scripts/vward-route.sh" "$TMP/opt/bin/vward-route.sh"
chmod 0755 "$TMP/opt/bin/vward-route.sh"
printf '%s\n' '{broken' > "$TMP/opt/share/vward/settings-registry.json"
if VWARD_ROOT_PREFIX="$TMP" "$HEALTH" full >/dev/null 2>&1; then
    echo "FAIL: full health accepted invalid JSON" >&2
    exit 1
fi

echo "FULL_HEALTH_PROFILE=PASS"
