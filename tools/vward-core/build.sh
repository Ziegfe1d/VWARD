#!/bin/sh
# Reproducible static build of vward-core (only selftest --yes writes, its own test group) for the
# routers' processors, the way tools/vward-awg is built: the same Go release gives the same
# bytes; `build.sh OUT --check` fails on any difference from SHA256SUMS.
set -eu
OUT=${1:?usage: build.sh OUT [--check]}
HERE=$(cd "$(dirname "$0")" && pwd)
export GOTOOLCHAIN=go1.25.1 CGO_ENABLED=0 GOOS=linux GOFLAGS=-mod=readonly
mkdir -p "$OUT"
cd "$HERE"
for arch in mipsle mips arm64; do
    case "$arch" in mips*) extra="GOMIPS=softfloat" ;; *) extra= ;; esac
    env GOARCH="$arch" $extra go build -trimpath -buildvcs=false -ldflags "-s -w -buildid=" -o "$OUT/vward-core-linux-$arch" .
done
cd "$OUT"
sha256sum vward-core-linux-mipsle vward-core-linux-mips vward-core-linux-arm64 > SHA256SUMS
if [ "${2:-}" = --check ]; then
    diff -u "$HERE/SHA256SUMS" SHA256SUMS
fi
for f in vward-core-linux-*; do case "$f" in *.gz) ;; *) gzip -9nf "$f" ;; esac; done
