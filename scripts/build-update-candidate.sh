#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)"
MAP="$ROOT/config/components/package-map.tsv"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

[ "$#" -eq 1 ] || fail "usage: $0 OUTPUT_DIRECTORY"
OUT="$1"
[ -r "$MAP" ] || fail "package map is not readable"
[ ! -e "$OUT" ] || fail "output path already exists: $OUT"
VERSION="$(sed -n '1p' "$ROOT/VERSION")"
case "$VERSION" in ''|*[!0-9A-Za-z.-]*) fail "invalid VERSION" ;; esac

PKGDIR="$OUT/package"
JSONL="$OUT/package-files.jsonl"
ARTIFACT="$OUT/vward-$VERSION.tar.gz"
mkdir -p "$PKGDIR"
: > "$JSONL"

while IFS="$(printf '\t')" read -r component source target mode extra
do
  case "$component" in ''|'#'*) continue ;; esac
  [ -z "${extra:-}" ] || fail "too many package map fields for $source"
  case "$component" in *[!a-z0-9-]*|'') fail "invalid component: $component" ;; esac
  case "$source" in /*|*'..'*) fail "unsafe source: $source" ;; esac
  case "$target" in /opt/*) ;; *) fail "unsafe target: $target" ;; esac
  case "$mode" in 0644|0755) ;; *) fail "invalid mode: $mode" ;; esac
  src="$ROOT/$source"
  dst="$PKGDIR/files$target"
  [ -f "$src" ] || fail "missing source: $source"
  [ ! -L "$src" ] || fail "symlink source forbidden: $source"
  mkdir -p "$(dirname "$dst")"
  cp "$src" "$dst"
  chmod "$mode" "$dst"
  digest="$(sha256sum "$dst" | awk '{print $1}')"
  jq -nc --arg source "files$target" --arg target "$target" --arg mode "$mode" \
    --arg sha256 "$digest" --arg component "$component" \
    '{source:$source,target:$target,mode:$mode,sha256:$sha256,component:$component,restart_policy:"none",config_policy:"program-only"}' >> "$JSONL"
done < "$MAP"

jq -s '{schema:1,files:.}' "$JSONL" > "$PKGDIR/package-manifest.json"
expected="$(awk -F '\t' '!/^#/ && NF {n++} END {print n+0}' "$MAP")"
actual="$(jq '.files | length' "$PKGDIR/package-manifest.json")"
[ "$actual" = "$expected" ] || fail "package target count mismatch: $actual/$expected"
unpacked_size="$(find "$PKGDIR" -type f -exec wc -c {} \; | awk '{sum+=$1} END{print sum+0}')"
tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner -czf "$ARTIFACT" -C "$PKGDIR" .
declared_size="$(tar -tvzf "$ARTIFACT" | awk '$1 ~ /^-/ {sum+=$3} END{print sum+0}')"
[ "$declared_size" = "$unpacked_size" ] || fail "unpacked size mismatch"
package_sha="$(sha256sum "$ARTIFACT" | awk '{print $1}')"
package_size="$(wc -c < "$ARTIFACT" | tr -d ' ')"
jq -n --arg version "$VERSION" --arg package_file "$(basename "$ARTIFACT")" --arg sha256 "$package_sha" \
  --argjson size "$package_size" --argjson unpacked_size "$unpacked_size" --argjson files "$actual" \
  '{candidate:true,signed:false,publication_state:"SIGNING_REQUIRED",version:$version,package_file:$package_file,package_sha256:$sha256,package_size:$size,unpacked_size:$unpacked_size,file_count:$files}' > "$OUT/candidate-metadata.json"
cp "$PKGDIR/package-manifest.json" "$OUT/package-manifest.json"
printf 'CANDIDATE=BUILT\nVERSION=%s\nFILES=%s\nPACKAGE=%s\nSHA256=%s\n' "$VERSION" "$actual" "$ARTIFACT" "$package_sha"
