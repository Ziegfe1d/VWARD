#!/bin/sh
# prepare.sh: .build/xcrypto = golang.org/x/crypto (the version in go.mod) with
# the MIPS ChaCha20 and Poly1305 of this directory, .build/awg = amneziawg-go
# with the MIPS counters and pools of awg/, and .build/go.mod pointing at both.
# The replacements are relative paths, so the build stays reproducible anywhere.
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
cp _mips/chacha_noasm.go _mips/chacha_mipsx.go .build/xcrypto/chacha20/
cp _mips/mac_noasm.go _mips/sum_mipsx.go _mips/sum_mipsx_test.go .build/xcrypto/internal/poly1305/
AWG=$(go list -m -f '{{.Dir}}' github.com/amnezia-vpn/amneziawg-go/v3)
cp -R "$AWG" .build/awg
chmod -R u+w .build/awg
# 64-bit atomics and sync.Pool in the packet path become the types of awg/vw_*.go
# (the standard ones everywhere but MIPS).
for f in .build/awg/device/*.go .build/awg/conn/*.go; do
    case "$f" in *_test.go|*windows*) continue ;; esac
    sed -i -e 's/atomic\.Uint64/u64/g' -e 's/atomic\.Int64/i64/g' -e 's/sync\.Pool/vwPool/g' "$f"
    # An import left without use is a compile error.
    grep -q 'atomic\.' "$f" || sed -i '/^[[:space:]]*"sync\/atomic"$/d' "$f"
    grep -q 'sync\.' "$f" || sed -i '/^[[:space:]]*"sync"$/d' "$f"
done
cp _mips/awg/vw_mipsx.go _mips/awg/vw_other.go .build/awg/device/
cp _mips/awg/conn_vw_mipsx.go .build/awg/conn/vw_mipsx.go
cp _mips/awg/conn_vw_other.go .build/awg/conn/vw_other.go
cp go.mod .build/go.mod
cp go.sum .build/go.sum
echo 'replace golang.org/x/crypto => ./.build/xcrypto' >> .build/go.mod
echo 'replace github.com/amnezia-vpn/amneziawg-go/v3 => ./.build/awg' >> .build/go.mod
