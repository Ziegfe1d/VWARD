#!/bin/sh
# vward-sentinel.sh: VWARD's real-time watcher (tools/vward-sentinel, a small C program).
#   vward-sentinel.sh install   the program for this router's processor, from the sentinel
#                               branch, checked against the SHA-256 pinned below
#   vward-sentinel.sh start     configure (what to watch) and start it, when installed
#   vward-sentinel.sh stop | status | config
#   vward-sentinel.sh install-dnscap   only vward-dnscap (tools/vward-dnscap), the route
#                               engine's DNS capture without libpcap; «install» does it too
# Without the program everything works as before: the cron supervisor and the jobs.

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

SHARE=${VWARD_SENTINEL_SHARE:-/opt/share/vward/sentinel}
BIN="$SHARE/vward-sentinel"
STATE_DIR=${VWARD_SENTINEL_STATE:-/tmp/vward-sentinel}
CONF="$STATE_DIR/sentinel.conf"
PIDFILE=${VWARD_SENTINEL_PIDFILE:-/opt/var/run/vward/sentinel.pid}
RUN_DIR=${VWARD_RUN_DIR:-/opt/var/run/vward}
ACT=${VWARD_SENTINEL_ACT:-/opt/bin/vward-sentinel-act.sh}
LOG=${VWARD_SENTINEL_LOG:-/opt/var/log/vward-sentinel.log}
CURL=${VWARD_CURL_BIN:-curl}
URL=${VWARD_SENTINEL_URL:-https://raw.githubusercontent.com/Ziegfe1d/VWARD/sentinel}
VERSION=2
DNSCAP_SHARE=${VWARD_DNSCAP_SHARE:-/opt/share/vward/dnscap}
DNSCAP_VERSION=1
VWARD_PROFILE_LIB=${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}

# SHA-256 of the program (tools/vward-sentinel/SHA256SUMS, a reproducible build).
sentinel_sum() {
    case "$1" in
        mipsle) echo 5eb1ef825f8711b1b8049cba350dd7a7c8c535a23f0ef3849883bfb45fbeb988 ;;
        mips) echo 07ac16328fba1a6178c668e4e669955a0b46b3ddb4d8d9c3e4df0a391167959f ;;
        arm64) echo 1c02a4df4f1c1ad25cff5132d7b86307012c3138058ea976d191c273ae3cf968 ;;
        arm) echo 75298e42c2963c4e4abb93669814b0ad03e32edffce5f70129ecaec08a3acd1d ;;
        *) return 1 ;;
    esac
}

# SHA-256 of vward-dnscap (tools/vward-dnscap/SHA256SUMS).
dnscap_sum() {
    case "$1" in
        mipsle) echo a8265f331d0eca2821d78c9584cdab072969ce534f7a298ebc5902b75cbbc567 ;;
        mips) echo f2e41e6c65477b740f5b6597468d3a98080d14f00ac5be56eb59fb05dfb190b4 ;;
        arm64) echo 11f8a14d2bc24a37d836def8a46c3f6266cafb187e1ea93651797088dbc1073b ;;
        arm) echo e3f15fe14961c57cee8fd21052728c1e876e40606581b5c4d46e39892c8e0ad1 ;;
        *) return 1 ;;
    esac
}

die() { printf 'error=%s\n' "$1"; exit "${2:-1}"; }
log() { mkdir -p "${LOG%/*}" 2>/dev/null; printf '%s|SENTINEL|%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG" 2>/dev/null; }

# Keenetic MIPS is little-endian (MT7621, MT7628) or big-endian (EN75xx): uname says
# "mips" for both, the ELF header of the router's own shell tells.
sentinel_arch() {
    [ -z "${VWARD_SENTINEL_ARCH:-}" ] || { echo "$VWARD_SENTINEL_ARCH"; return 0; }
    case "$(uname -m)" in
        aarch64|arm64) echo arm64 ;;
        armv7*|armv6*|arm*) echo arm ;;
        mips*)
            e=$(dd if=/bin/sh bs=1 skip=5 count=1 2>/dev/null | od -An -tu1 | tr -d ' ')
            if [ "$e" = 2 ]; then echo mips; else echo mipsle; fi ;;
        *) return 1 ;;
    esac
}

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
    else openssl dgst -sha256 "$1" 2>/dev/null | awk '{print $NF}'; fi
}

running() {
    P=
    [ -r "$PIDFILE" ] && read -r P 2>/dev/null < "$PIDFILE"
    case "$P" in ''|*[!0-9]*) return 1 ;; esac
    kill -0 "$P" 2>/dev/null || return 1
    # Our program, not a process that took its id after a reboot.
    [ -r "/proc/$P/cmdline" ] && case "$(tr '\000' ' ' 2>/dev/null < "/proc/$P/cmdline")" in *vward-sentinel*) return 0 ;; esac
    return 1
}

op_install() {
    [ ! -x "$BIN" ] || [ "$(cat "$SHARE/version" 2>/dev/null)" != "$VERSION" ] || { echo "result=unchanged"; return 0; }
    a=$(sentinel_arch) || die arch_unsupported
    want=$(sentinel_sum "$a") || die arch_unsupported
    mkdir -p "$SHARE" || die write_failed
    TMPD=$(mktemp -d "$SHARE/.install.XXXXXX" 2>/dev/null) || die write_failed
    trap 'rm -rf "${TMPD:?}"' EXIT
    "$CURL" -fsSL --connect-timeout 15 --max-time 120 --max-filesize 2097152 \
        -o "$TMPD/p.gz" "$URL/vward-sentinel-linux-$a.gz" 2>/dev/null || die download_failed
    gunzip -c "$TMPD/p.gz" > "$TMPD/vward-sentinel" 2>/dev/null || die package_damaged
    [ "$(sha256_of "$TMPD/vward-sentinel")" = "$want" ] || die checksum_mismatch
    chmod 0755 "$TMPD/vward-sentinel" || die write_failed
    "$TMPD/vward-sentinel" --version >/dev/null 2>&1 || die binary_not_runnable
    running && op_stop >/dev/null
    mv -f "$TMPD/vward-sentinel" "$BIN" || die write_failed
    echo "$VERSION" > "$SHARE/version"
    log "installed $VERSION arch=$a"
    echo "result=changed"
}

# The route engine picks vward-dnscap up at its next capture start (tcpdump stays the
# second choice).  A broken download never replaces a working program.
op_install_dnscap() {
    D="$DNSCAP_SHARE/vward-dnscap"
    [ ! -x "$D" ] || [ "$(cat "$DNSCAP_SHARE/version" 2>/dev/null)" != "$DNSCAP_VERSION" ] || { echo "result=unchanged"; return 0; }
    a=$(sentinel_arch) || die arch_unsupported
    want=$(dnscap_sum "$a") || die arch_unsupported
    mkdir -p "$DNSCAP_SHARE" || die write_failed
    TMPC=$(mktemp -d "$DNSCAP_SHARE/.install.XXXXXX" 2>/dev/null) || die write_failed
    trap 'rm -rf "${TMPC:?}"' EXIT
    "$CURL" -fsSL --connect-timeout 15 --max-time 120 --max-filesize 1048576 \
        -o "$TMPC/p.gz" "$URL/vward-dnscap-linux-$a.gz" 2>/dev/null || die download_failed
    gunzip -c "$TMPC/p.gz" > "$TMPC/vward-dnscap" 2>/dev/null || die package_damaged
    [ "$(sha256_of "$TMPC/vward-dnscap")" = "$want" ] || die checksum_mismatch
    chmod 0755 "$TMPC/vward-dnscap" || die write_failed
    "$TMPC/vward-dnscap" --version >/dev/null 2>&1 || die binary_not_runnable
    mv -f "$TMPC/vward-dnscap" "$D" || die write_failed
    echo "$DNSCAP_VERSION" > "$DNSCAP_SHARE/version"
    rm -rf "${TMPC:?}"
    log "dnscap installed $DNSCAP_VERSION arch=$a"
    echo "result=changed"
}

# What to watch: VWARD's long-running programs with their memory limits, the provider's
# and the tunnels' interfaces, the router's DNS.
op_config() {
    mkdir -p "$STATE_DIR" || die write_failed
    {
        echo "STATE_DIR=$STATE_DIR"
        echo "ACT=$ACT"
        echo "HOURS_FILE=${VWARD_SENTINEL_HOURS:-/opt/var/lib/vward/sentinel/hours.tsv}"
        echo "SAMPLE_MS=2000"
        echo "DNS=127.0.0.1:53"
        echo "DNS_NAME=vward-probe.invalid"
        echo "DNS_EVERY=30"
        echo "WATCH=route-engine:$RUN_DIR/route-engine.pid:16384"
        echo "WATCH=panel:/opt/var/run/vward-console-lighttpd.pid:24576"
        for f in "$RUN_DIR"/awg-engine/t*.pid; do [ -e "$f" ] && { n=${f##*/}; echo "WATCH=awg-${n%.pid}:$f:65536"; }; done
        for f in "$RUN_DIR"/vless-engine/v*.pid; do [ -e "$f" ] && { n=${f##*/}; echo "WATCH=xray-${n%.pid}:$f:98304"; }; done
        if [ -r "$VWARD_PROFILE_LIB" ] && . "$VWARD_PROFILE_LIB" && vward_profile_load >/dev/null 2>&1; then
            [ -z "${VWARD_WAN_DEVICE:-}" ] || echo "IFACE=$VWARD_WAN_DEVICE"
            # AdGuard Home in the DNS chain, asked every 5 s (unless the owner keeps the chain: CHAIN=0).
            y=${VWARD_ADGUARD_CONFIG:-}
            if [ -n "$y" ] && [ -r "$y" ] && [ "$(sed -n 's/^CHAIN=//p' "${VWARD_DNS_GUARD_CONF:-/opt/etc/vward/ads-privacy-guard/dns-guard.conf}" 2>/dev/null)" != 0 ]; then
                cp=$(awk '/^[^ #]/ {d = ($1 == "dns:")} d && $1 == "port:" {print $2; exit}' "$y" 2>/dev/null)
                ch=$(awk '/^[^ #]/ {d = ($1 == "dns:"); b = 0; next} d && /^  bind_hosts:/ {b = 1; next} d && /^  [a-z_]+:/ {b = 0}
                    b && $1 == "-" {gsub(/["\047]/, "", $2); print $2}' "$y" 2>/dev/null | grep -E '^[0-9]+(\.[0-9]+){3}$' | grep -v '^0\.0\.0\.0$' | head -n 1)
                case "$cp" in ''|*[!0-9]*|53) ;; *) echo "CHAIN=${ch:-${VWARD_LAN_ADDRESS:-127.0.0.1}}:$cp"; echo "CHAIN_EVERY=5"; echo "CHAIN_MISS=3" ;; esac
            fi
            vward_map_vpns "$(vward_device_map 2>/dev/null)" "${VWARD_WAN_DEVICE:-}" 2>/dev/null |
                while read -r _ dev; do [ -n "$dev" ] && echo "IFACE=$dev"; done
        fi
    } > "$CONF.tmp" && mv -f "$CONF.tmp" "$CONF" || die write_failed
    echo "result=changed"
}

op_start() {
    [ -x "$BIN" ] || { echo "result=not_installed"; return 0; }
    running && { echo "result=unchanged"; return 0; }
    op_config >/dev/null
    mkdir -p "${PIDFILE%/*}" || die write_failed
    # Normal priority: it reacts at once and costs a fraction of a percent.
    "$BIN" "$CONF" </dev/null >/dev/null 2>&1 &
    echo $! > "$PIDFILE"
    log "started pid=$!"
    echo "result=changed"
}

op_stop() {
    running || { rm -f "$PIDFILE"; echo "result=unchanged"; return 0; }
    kill "$P" 2>/dev/null
    n=0
    while kill -0 "$P" 2>/dev/null && [ "$n" -lt 5 ]; do sleep 1; n=$((n + 1)); done
    kill -9 "$P" 2>/dev/null
    rm -f "$PIDFILE"
    log "stopped"
    echo "result=changed"
}

case "${1:-}" in
    # The capture program first: the engine needs it more than the watcher.
    install) ( op_install_dnscap ) >/dev/null 2>&1; op_install ;;
    install-dnscap) op_install_dnscap ;;
    config) op_config ;;
    start) op_start ;;
    stop) op_stop ;;
    restart) op_stop >/dev/null; op_start ;;
    # The tunnels changed: the watcher learns their programs and interfaces (SIGHUP).
    reload) op_config >/dev/null; running && kill -HUP "$P" 2>/dev/null; echo "result=changed" ;;
    status)
        if running; then echo "status=running"; echo "pid=$P"; elif [ -x "$BIN" ]; then echo "status=stopped"; else echo "status=not_installed"; fi ;;
    *) echo "usage: vward-sentinel.sh install|install-dnscap|start|stop|restart|reload|status|config" >&2; exit 64 ;;
esac
