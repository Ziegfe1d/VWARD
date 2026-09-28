#!/bin/sh
# test.sh: golang.org/x/crypto's own tests for ChaCha20, Poly1305 and
# ChaCha20-Poly1305, plus ours, and amneziawg-go's device tests, on little- and
# big-endian MIPS under qemu-user, with the files of this directory in place.
# (TwoDevicePing, AWGDevicePing and ConcurrencySafety are skipped: they fail the
# same way without these files where loopback UDP is restricted.)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE/.."
[ -f .build/go.mod ] || sh _mips/prepare.sh
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
for arch in mipsle mips; do
    q=qemu-mipsel-static; [ "$arch" = mips ] && q=qemu-mips-static
    for p in chacha20 internal/poly1305 chacha20poly1305; do
        GOARCH=$arch GOMIPS=softfloat go test -modfile=.build/go.mod -c -o "$T/t" "golang.org/x/crypto/$p"
        "$q" "$T/t" -test.short >/dev/null || { echo "FAIL: $arch $p"; exit 1; }
        echo "PASS: $arch $p"
    done
    GOARCH=$arch GOMIPS=softfloat go test -modfile=.build/go.mod -c -o "$T/d" github.com/amnezia-vpn/amneziawg-go/v3/device
    (cd .build/awg/device && "$q" "$T/d" -test.short -test.skip 'TestTwoDevicePing|TestAWGDevicePing|TestConcurrencySafety' >/dev/null) ||
        { echo "FAIL: $arch amneziawg-go device"; exit 1; }
    echo "PASS: $arch amneziawg-go device"
done
