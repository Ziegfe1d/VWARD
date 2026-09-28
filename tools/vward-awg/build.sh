#!/bin/sh
# Reproducible build of vward-awg for the routers' processors.  The same Go
# release and module versions give the same bytes, so SHA256SUMS (checked in)
# pins what routers accept; `build.sh OUT --check` fails on any difference.
set -eu
OUT=${1:?usage: build.sh OUT [--check]}
HERE=$(cd "$(dirname "$0")" && pwd)
GO_VERSION=go1.25.1
export GOTOOLCHAIN=$GO_VERSION CGO_ENABLED=0 GOOS=linux GOFLAGS=-mod=readonly
mkdir -p "$OUT"
cd "$HERE"
# golang.org/x/crypto with the MIPS ChaCha20 and Poly1305 of _mips/ (see _mips/prepare.sh).
sh _mips/prepare.sh
for arch in mipsle mips arm64 arm; do
    case "$arch" in mips*) extra="GOMIPS=softfloat" ;; arm) extra="GOARM=7" ;; *) extra= ;; esac
    env GOARCH="$arch" $extra go build -modfile=.build/go.mod -trimpath -buildvcs=false -ldflags "-s -w -buildid=" -o "$OUT/vward-awg-linux-$arch" .
done
cd "$OUT"
sha256sum vward-awg-linux-mipsle vward-awg-linux-mips vward-awg-linux-arm64 vward-awg-linux-arm > SHA256SUMS
if [ "${2:-}" = --check ]; then
    diff -u "$HERE/SHA256SUMS" SHA256SUMS
fi
for f in vward-awg-linux-*; do case "$f" in *.gz) ;; *) gzip -9nf "$f" ;; esac; done
