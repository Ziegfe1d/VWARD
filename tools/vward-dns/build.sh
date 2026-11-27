#!/bin/sh
# Reproducible pilot binaries. This creates a test bundle, not a signed VWARD release.
set -eu
OUT=${1:?usage: build.sh OUTPUT_DIRECTORY}
mkdir -p "$OUT"
OUT=$(CDPATH='' cd "$OUT" && pwd)
cd "$(dirname "$0")"
export GOTOOLCHAIN=go1.25.1 CGO_ENABLED=0 GOOS=linux GOMIPS=softfloat
for arch in mipsle mips arm64 amd64; do
    dir="$OUT/vward-dns-$arch"
    mkdir -p "$dir"
    GOARCH="$arch" go build -mod=readonly -trimpath -buildvcs=false -ldflags '-s -w -buildid=' -o "$dir/vward-dns" .
    cp pilot.sh "$dir/"
    (cd "$dir" && sha256sum vward-dns pilot.sh > SHA256SUMS)
done
