#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)"
BUILD="$ROOT/scripts/build-update-candidate.sh"
REFRESH="$ROOT/scripts/refresh-sha256sums.sh"
PUBKEY="$ROOT/config/updater/update-public.pem"
KEY=${VWARD_SIGNING_KEY_FILE:-}
# Rehearsals sign with a throwaway key; such output is never staged into the feed.
REHEARSAL_PUBKEY=${VWARD_REHEARSAL_PUBLIC_KEY:-}

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

[ "$#" -ge 3 ] && [ "$#" -le 4 ] || fail "usage: $0 OUTPUT_DIRECTORY SEQUENCE MIN_VWARD [--stage]"
OUT=$1
SEQUENCE=$2
MIN_VWARD=$3
STAGE=0
[ "${4:-}" = "" ] || [ "${4:-}" = "--stage" ] || fail "unknown option: ${4:-}"
[ "${4:-}" != "--stage" ] || STAGE=1
if [ -n "$REHEARSAL_PUBKEY" ]; then
    [ "$STAGE" -eq 0 ] || fail "a rehearsal key cannot be staged into the feed"
    PUBKEY=$REHEARSAL_PUBKEY
fi

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

# sign_manifest SIGNED OUTPUT: the canonical signed part, signed and verified.
sign_manifest() {
    jq -cS . "$1" > "$1.canonical"
    openssl pkeyutl -sign -inkey "$KEY" -rawin -in "$1.canonical" -out "$1.sig"
    jq -n --slurpfile signed "$1" --arg signature "$(openssl base64 -A -in "$1.sig")" '{signed:$signed[0],signature:$signature}' > "$2"
    jq -cS '.signed' "$2" > "$2.verify"
    jq -r '.signature' "$2" | openssl base64 -d -A > "$2.verify.sig"
    openssl pkeyutl -verify -pubin -inkey "$PUBKEY" -rawin -in "$2.verify" -sigfile "$2.verify.sig" >/dev/null
    rm -f "$1.canonical" "$1.sig" "$2.verify" "$2.verify.sig"
}
sign_manifest "$OUT/signed.json" "$OUT/update-manifest.json"

# ---------- Per-file feed (schema 2, Update Engine 2) ----------
# Every program file and every engine file once, named by its sha256; the signed
# manifest lists the whole release, so a router fetches only what differs.
V2="$OUT/v2"
mkdir -p "$V2/files"
V2_BASE="https://raw.githubusercontent.com/Ziegfe1d/VWARD/dev/updates/dev/v2/files/"
ENGINE_VERSION="$(sed -n 's/^VU_ENGINE_VERSION=//p' "$ROOT/components/update-engine/vward-update-common-base.sh")"
[ -n "$ENGINE_VERSION" ] || fail "engine version missing"
file_row() {
    # file_row SOURCE MODE: sha size mode, the file stored under its sha256.
    digest="$(sha256sum "$ROOT/$1" | awk '{print $1}')"
    cp "$ROOT/$1" "$V2/files/$digest"
    printf '%s\t%s\t%s' "$digest" "$(wc -c < "$ROOT/$1" | tr -d ' ')" "$2"
}
: > "$V2/files.tsv"
while IFS="$(printf '\t')" read -r component source target mode; do
    case "$component" in ''|'#'*) continue ;; esac
    printf '%s\t%s\t%s\n' "$target" "$(file_row "$source" "$mode")" "$component" >> "$V2/files.tsv"
done < "$ROOT/config/components/package-map.tsv"
: > "$V2/engine.tsv"
for source in components/update-engine/vward-update-bootstrap.sh components/update-engine/vward-update-common-base.sh \
    components/update-engine/vward-update-common.sh components/update-engine/vward-update-delta.sh \
    components/update-engine/vward-update-hardening.sh components/update-engine/vward-update-health.sh \
    components/update-engine/vward-update-rollback.sh components/update-engine/vward-update-watch.sh \
    components/update-engine/vward-update.sh config/components/component-registry.json; do
    case "$source" in *.sh) mode=0755 ;; *) mode=0644 ;; esac
    printf '%s\t%s\n' "${source##*/}" "$(file_row "$source" "$mode")" >> "$V2/engine.tsv"
done
jq -n --arg version "$VERSION" --arg update_id "vward-$VERSION" --argjson sequence "$SEQUENCE" \
    --arg published_at "$PUBLISHED_AT" --arg base "$V2_BASE" --arg min_vward "$MIN_VWARD" --arg engine "$ENGINE_VERSION" \
    --rawfile files "$V2/files.tsv" --rawfile engine_files "$V2/engine.tsv" \
    '($files | split("\n") | map(select(length > 0) | split("\t")
        | {target: .[0], sha256: .[1], size: (.[2] | tonumber), mode: .[3], component: .[4]})) as $f
     | ($engine_files | split("\n") | map(select(length > 0) | split("\t")
        | {name: .[0], sha256: .[1], size: (.[2] | tonumber), mode: .[3]})) as $e
     | {schema:2,update_id:$update_id,sequence:$sequence,version:$version,channel:"dev",priority:"ROUTINE",
        published_at:$published_at,min_updater_version:"2.0.0",files_base:$base,files:$f,
        engine:{version:$engine,files:$e},compatibility:{min_vward:$min_vward,max_vward:$version},
        affected_components:($f | map(.component) | unique),affected_services:[],health_profile:"full",
        requires_reboot:false,rollback_policy:"automatic",signature:{algorithm:"Ed25519",key_id:"vward-prod-2026-01"}}' > "$V2/signed.json"
sign_manifest "$V2/signed.json" "$V2/manifest.json"

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
    feed_v2="$ROOT/updates/dev/v2"
    mkdir -p "$feed_v2/files"
    for blob in "$V2/files"/*; do
        [ -e "$feed_v2/files/${blob##*/}" ] || cp "$blob" "$feed_v2/files/${blob##*/}"
    done
    cp "$V2/manifest.json" "$feed_v2/manifest.json"
    set -- --include "updates/dev/packages/vward-$VERSION.tar.gz" --include updates/dev/v2/manifest.json
    for blob in "$feed_v2/files"/*; do set -- "$@" --include "updates/dev/v2/files/${blob##*/}"; done
    "$REFRESH" "$@"
    printf 'PUBLISH_READY=STAGED\nPACKAGE=%s\nMANIFEST=%s\n' "$target" "$manifest"
else
    printf 'SIGNING_REQUIRED=NO\nPUBLISH_READY=YES\nPACKAGE=%s\nMANIFEST=%s\n' "$PACKAGE" "$OUT/update-manifest.json"
fi
