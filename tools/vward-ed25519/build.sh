#!/bin/sh
# Builds vward-ed25519 (an Ed25519 signature check, Zig's std.crypto) for the routers'
# processors: static, musl, no FPU on MIPS. --check compares with SHA256SUMS here, the
# sums a router pins before it trusts the program. The build is reproducible.
#   sh build.sh OUT [--check]
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OUT=${1:?usage: build.sh OUT [--check]}
CHECK=${2:-}
ZIG_VERSION=0.13.0
ZIG_WHEEL=ziglang-0.13.0-py3-none-manylinux_2_12_x86_64.manylinux2010_x86_64.musllinux_1_1_x86_64.whl
ZIG_SHA256=3ce0c9f16547e5d61b32e0d226926e9a2552ef4b91fccf7ab5ea1a623a77824b

mkdir -p "$OUT"
OUT=$(CDPATH= cd -- "$OUT" && pwd)
ZIG=${ZIG:-}
if [ -z "$ZIG" ]; then
    Z="$OUT/.zig"
    if [ ! -x "$Z/ziglang/zig" ]; then
        mkdir -p "$Z"
        python3 -m pip download "ziglang==$ZIG_VERSION" --no-deps --only-binary=:all: -d "$Z" -q
        echo "$ZIG_SHA256  $Z/$ZIG_WHEEL" | sha256sum -c - >/dev/null
        python3 -m zipfile -e "$Z/$ZIG_WHEEL" "$Z"
        chmod +x "$Z/ziglang/zig"
    fi
    ZIG="$Z/ziglang/zig"
fi
"$ZIG" version | grep -qx "$ZIG_VERSION" || { echo "zig $ZIG_VERSION is needed" >&2; exit 1; }

cd "$OUT"
for t in mipsle:mipsel-linux-musl:mips32r2+soft_float mips:mips-linux-musl:mips32r2+soft_float \
         arm64:aarch64-linux-musl:baseline arm:arm-linux-musleabihf:baseline; do
    arch=${t%%:*}; rest=${t#*:}; target=${rest%%:*}; cpu=${rest#*:}
    ZIG_GLOBAL_CACHE_DIR="$OUT/.cache" ZIG_LOCAL_CACHE_DIR="$OUT/.cache" \
        "$ZIG" build-exe "$HERE/main.zig" -O ReleaseSmall -target "$target" -mcpu "$cpu" -fstrip \
        --name "vward-ed25519-linux-$arch"
    rm -f "vward-ed25519-linux-$arch.o"
done
sha256sum vward-ed25519-linux-mipsle vward-ed25519-linux-mips vward-ed25519-linux-arm64 vward-ed25519-linux-arm > SHA256SUMS.ed25519
if [ "$CHECK" = --check ]; then
    diff -u "$HERE/SHA256SUMS" SHA256SUMS.ed25519
    echo "ED25519_BUILD=REPRODUCED"
fi
