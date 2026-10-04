#!/bin/sh
# Builds vward-dnscap (the DNS queries of the LAN, without libpcap) for the routers' processors.
#   sh build.sh OUT [--check]
# zig (a C compiler with musl for every target) comes pinned from PyPI; --check compares
# the result with SHA256SUMS here, the sums the runtime pins.  The build is reproducible.
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

# Router processors: MT7621 and older MIPS (little and big endian, no FPU: soft float),
# newer Keenetic on ARM.
for pair in mipsle:mipsel-linux-musl mips:mips-linux-musl arm64:aarch64-linux-musl arm:arm-linux-musleabihf; do
    arch=${pair%%:*}
    target=${pair#*:}
    case "$arch" in mips*) float=-msoft-float ;; *) float= ;; esac
    ZIG_GLOBAL_CACHE_DIR="$OUT/.cache" ZIG_LOCAL_CACHE_DIR="$OUT/.cache" \
        "$ZIG" cc -target "$target" $float -Os -static -s -fno-ident -ffile-prefix-map="$HERE"=. \
        -Wall -Wextra -Werror -o "$OUT/vward-dnscap-linux-$arch" "$HERE/dnscap.c"
done
cd "$OUT"
sha256sum vward-dnscap-linux-mipsle vward-dnscap-linux-mips vward-dnscap-linux-arm64 vward-dnscap-linux-arm > SHA256SUMS
if [ "$CHECK" = --check ]; then
    diff -u "$HERE/SHA256SUMS" SHA256SUMS
    echo "DNSCAP_BUILD=REPRODUCED"
fi
