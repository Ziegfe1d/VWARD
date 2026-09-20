#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)"
OUT="$ROOT/SHA256SUMS"
declare -a include=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --include)
            [ "$#" -ge 2 ] || { echo "usage: $0 [--include REPOSITORY_PATH]" >&2; exit 2; }
            include+=("$2")
            shift 2
            ;;
        *)
            echo "usage: $0 [--include REPOSITORY_PATH]" >&2
            exit 2
            ;;
    esac
done

cd "$ROOT"
tmp="$OUT.new.$$"
trap 'rm -f "$tmp"' EXIT

{
    git ls-files
    for path in "${include[@]}"; do
        case "$path" in
            ''|/*|*'..'*) echo "unsafe include path: $path" >&2; exit 2 ;;
        esac
        [ -f "$path" ] || { echo "missing include path: $path" >&2; exit 2; }
        printf '%s\n' "$path"
    done
} | grep -vx 'SHA256SUMS' | LC_ALL=C sort -u | while IFS= read -r path; do
    sha256sum "$path"
done > "$tmp"

mv -f "$tmp" "$OUT"
trap - EXIT
printf 'SHA256SUMS=REFRESHED\n'
