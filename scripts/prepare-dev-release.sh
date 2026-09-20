#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)"
BUILD="$ROOT/scripts/build-update-candidate.sh"
REFRESH="$ROOT/scripts/refresh-sha256sums.sh"
PUBKEY="$ROOT/config/updater/update-public.pem"
KEY=${VWARD_SIGNING_KEY_FILE:-}

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

[ "$#" -ge 3 ] && [ "$#" -le 4 ] || fail "usage: $0 OUTPUT_DIRECTORY SEQUENCE MIN_VWARD [--stage]"
OUT=$1
SEQUENCE=$2
MIN_VWARD=$3
STAGE=0
[ "${4:-}" = "" ] || [ "${4:-}" = "--stage" ] || fail "unknown option: ${4:-}"
[ "${4:-}" != "--stage" ] || STAGE=1

case "$SEQUENCE" in ''|*[!0-9]*) fail "sequence must be a positive integer" ;; esac
[ "$SEQUENCE" -gt 0 ] || fail "sequence must be a positive integer"
case "$MIN_VWARD" in ''|*[!0-9A-Za-z.-]*) fail "invalid MIN_VWARD" ;; esac
[ -n "$KEY" ] && [ -r "$KEY" ] || fail "VWARD_SIGNING_KEY_FILE is required and must be readable"
[ -r "$PUBKEY" ] || fail "trusted public key is missing"
[ ! -e "$OUT" ] || fail "output path already exists: $OUT"

private_pub="$(openssl pkey -in "$KEY" -pubout -outform DER | sha256sum | awk '{print $1}')"
trusted_pub="$(openssl pkey -pubin -in "$PUBKEY" -outform DER | sha256sum | awk '{print $1}')"
[ "$private_pub" = "$trusted_pub" ] || fail "signing key does not match trusted public key"

mkdir -p "$OUT"
"$BUILD" "$OUT/candidate"

VERSION="$(sed -n '1p' "$ROOT/VERSION")"
PACKAGE="$OUT/candidate/vward-$VERSION.tar.gz"
PACKAGE_SHA="$(jq -r '.package_sha256' "$OUT/candidate/candidate-metadata.json")"
PACKAGE_SIZE="$(jq -r '.package_size' "$OUT/candidate/candidate-metadata.json")"
UNPACKED_SIZE="$(jq -r '.unpacked_size' "$OUT/candidate/candidate-metadata.json")"
COMPONENTS="$(awk -F '\t' '!/^#/ && NF {print $1}' "$ROOT/config/components/package-map.tsv" | LC_ALL=C sort -u | jq -R . | jq -s .)"
PUBLISHED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
URL="https://raw.githubusercontent.com/Ziegfe1d/VWARD/dev/updates/dev/packages/vward-$VERSION.tar.gz"

jq -n --arg version "$VERSION" --arg update_id "vward-$VERSION" --argjson sequence "$SEQUENCE" \
    --arg published_at "$PUBLISHED_AT" --arg url "$URL" --arg sha256 "$PACKAGE_SHA" \
    --argjson size "$PACKAGE_SIZE" --argjson unpacked_size "$UNPACKED_SIZE" \
    --arg min_vward "$MIN_VWARD" --argjson components "$COMPONENTS" \
    '{schema:1,update_id:$update_id,sequence:$sequence,version:$version,channel:"dev",priority:"ROUTINE",published_at:$published_at,min_updater_version:"1.2.0",package:{url:$url,sha256:$sha256,size:$size,unpacked_size:$unpacked_size},compatibility:{min_vward:$min_vward,max_vward:$version},affected_components:$components,affected_services:[],health_profile:"full",requires_reboot:false,rollback_policy:"automatic",signature:{algorithm:"Ed25519",key_id:"vward-prod-2026-01"}}' > "$OUT/signed.json"

jq -cS . "$OUT/signed.json" > "$OUT/signed.canonical.json"
openssl pkeyutl -sign -inkey "$KEY" -rawin -in "$OUT/signed.canonical.json" -out "$OUT/signature.bin"
SIGNATURE="$(openssl base64 -A -in "$OUT/signature.bin")"
jq -n --slurpfile signed "$OUT/signed.json" --arg signature "$SIGNATURE" '{signed:$signed[0],signature:$signature}' > "$OUT/update-manifest.json"
jq -cS '.signed' "$OUT/update-manifest.json" > "$OUT/verify.canonical.json"
jq -r '.signature' "$OUT/update-manifest.json" | openssl base64 -d -A > "$OUT/verify.signature.bin"
openssl pkeyutl -verify -pubin -inkey "$PUBKEY" -rawin -in "$OUT/verify.canonical.json" -sigfile "$OUT/verify.signature.bin" >/dev/null

if [ "$STAGE" -eq 1 ]; then
    target="$ROOT/updates/dev/packages/vward-$VERSION.tar.gz"
    manifest="$ROOT/updates/dev/update-manifest.json"
    mkdir -p "$(dirname "$target")"
    if [ -e "$target" ]; then
        [ "$(sha256sum "$target" | awk '{print $1}')" = "$PACKAGE_SHA" ] || fail "refusing to overwrite a different existing package"
    else
        cp "$PACKAGE" "$target"
    fi
    cp "$OUT/update-manifest.json" "$manifest"
    "$REFRESH" --include "updates/dev/packages/vward-$VERSION.tar.gz"
    printf 'PUBLISH_READY=STAGED\nPACKAGE=%s\nMANIFEST=%s\n' "$target" "$manifest"
else
    printf 'SIGNING_REQUIRED=NO\nPUBLISH_READY=YES\nPACKAGE=%s\nMANIFEST=%s\n' "$PACKAGE" "$OUT/update-manifest.json"
fi
