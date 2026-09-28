#!/bin/sh
# prepare.sh: .build/xcrypto = golang.org/x/crypto (the version in go.mod) with
# the MIPS files of this directory, and .build/go.mod pointing at it.  The
# replacement is a relative path, so the build stays reproducible anywhere.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
cd "$ROOT"
XC=$(go list -m -f '{{.Dir}}' golang.org/x/crypto)
[ -n "$XC" ] && [ -d "$XC" ] || { go mod download golang.org/x/crypto; XC=$(go list -m -f '{{.Dir}}' golang.org/x/crypto); }
rm -rf "${ROOT:?}/.build"
mkdir -p .build
cp -R "$XC" .build/xcrypto
chmod -R u+w .build/xcrypto
cp mips/chacha_noasm.go mips/chacha_mipsx.go .build/xcrypto/chacha20/
cp mips/mac_noasm.go mips/sum_mipsx.go mips/sum_mipsx_test.go .build/xcrypto/internal/poly1305/
cp go.mod .build/go.mod
cp go.sum .build/go.sum
echo 'replace golang.org/x/crypto => ./.build/xcrypto' >> .build/go.mod
