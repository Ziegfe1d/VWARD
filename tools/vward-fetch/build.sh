#!/bin/sh
# Builds vward-fetch (VWARD's own download program, Zig's std.crypto TLS) for the routers'
# processors: static, musl, no FPU on MIPS. --check compares with SHA256SUMS here, the sums a
# router pins before it trusts the program. The build is reproducible.
#   sh build.sh OUT [--check]
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OUT=${1:?usage: build.sh OUT [--check]}
CHECK=${2:-}
# 0.14: TLS 1.2 next to 1.3 in std.crypto.tls (0.13, the other tools' zig, has 1.3 only).
ZIG_VERSION=0.14.1
ZIG_WHEEL=ziglang-0.14.1-py3-none-manylinux_2_12_x86_64.manylinux2010_x86_64.musllinux_1_1_x86_64.whl
ZIG_SHA256=6eb9d4d759b292c83810dbee2e9e8e3fbfbf01d864e6e9811bae711fd74e1c2f

mkdir -p "$OUT"
OUT=$(CDPATH= cd -- "$OUT" && pwd)
ZIG=${ZIG_FETCH:-}
if [ -z "$ZIG" ]; then
    Z="$OUT/.zig-0.14"
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
         arm64:aarch64-linux-musl:baseline arm:arm-linux-musleabihf:baseline x86_64:x86_64-linux-musl:baseline; do
    arch=${t%%:*}; rest=${t#*:}; target=${rest%%:*}; cpu=${rest#*:}
    ZIG_GLOBAL_CACHE_DIR="$OUT/.cache" ZIG_LOCAL_CACHE_DIR="$OUT/.cache" \
        "$ZIG" build-exe "$HERE/main.zig" -O ReleaseSmall -target "$target" -mcpu "$cpu" -fstrip \
        --name "vward-fetch-linux-$arch"
    rm -f "vward-fetch-linux-$arch.o"
done
sha256sum vward-fetch-linux-mipsle vward-fetch-linux-mips vward-fetch-linux-arm64 vward-fetch-linux-arm > SHA256SUMS.fetch
if [ "$CHECK" = --check ]; then
    diff -u "$HERE/SHA256SUMS" SHA256SUMS.fetch
    echo "FETCH_BUILD=REPRODUCED"
fi
