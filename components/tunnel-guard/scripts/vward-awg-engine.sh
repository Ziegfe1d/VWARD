#!/bin/sh
# VWARD tunnel engine («Контур AmneziaWG»): holds tunnels whose format the
# firmware cannot (AmneziaWG 3.x on KeeneticOS 5.1).  Each tunnel runs
# wireproxy-awg (amneziawg-go, userspace, no kernel modules) with a SOCKS5
# port on 127.0.0.1, and Keenetic gets a «Прокси» connection (ProxyN) to it,
# so lists and subnets are routed to it like to any Keenetic tunnel.
#
# The program is downloaded only when the first such tunnel is added, from
# the release pinned below, and checked against its SHA-256.  Tunnel files
# hold private keys: root-only, never printed, never in a process's arguments.
#
# vward-awg-engine.sh install | add DESCRIPTION FILE | remove PROXY |
#                     supervise | stop | status
# Output: "result=..." / "info.key=value" lines, or "error=<code>".
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

ENGINE_ETC=${VWARD_AWG_ETC:-/opt/etc/vward/awg-engine}
ENGINE_SHARE=${VWARD_AWG_SHARE:-/opt/share/vward/awg-engine}
ENGINE_RUN=${VWARD_AWG_RUN:-/opt/var/run/vward/awg-engine}
ENGINE_LOG=${VWARD_AWG_LOG:-/opt/var/log/vward-awg-engine.log}
TUNNELS="$ENGINE_ETC/tunnels.tsv"
BIN="$ENGINE_SHARE/wireproxy"
RCI=${VWARD_RCI_BASE:-http://127.0.0.1:79/rci}
CURL=${VWARD_CURL_BIN:-curl}
JQ=${JQ:-jq}
HANDSHAKE_WAIT=${VWARD_AWG_HANDSHAKE_WAIT:-30}
MAX_TUNNELS=5
PORT_BASE=25400
PROXY_BASE=40

WP_VERSION=v1.0.18
WP_URL=${VWARD_AWG_URL:-https://github.com/artem-russkikh/wireproxy-awg/releases/download/$WP_VERSION}
# SHA-256 of wireproxy_linux_<arch>.tar.gz of that release.
wp_sum() {
    case "$1" in
        mipsle) echo c6578570d2926d2743a15b6dbde3121423ba13adc99a6c34f60f7d1fa094f5bd ;;
        mips) echo 34d8c23a7d9f297fc5466a52923d90059013f1c03b1d17ea079a526dc5fb4d01 ;;
        arm64) echo ee05ae8426b78947832c95c39596d5e778f4d485e8208683264c08064f82e7a3 ;;
        arm) echo 1830acaddd9dc0f82327444e43149d9c5c1942f3bad086255e36d54431817635 ;;
        *) return 1 ;;
    esac
}

die() { printf 'error=%s\n' "$1"; exit "${2:-1}"; }
log() { mkdir -p "${ENGINE_LOG%/*}" 2>/dev/null; printf '%s|AWG_ENGINE|%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$ENGINE_LOG" 2>/dev/null; }

TMPD=
cleanup() { [ -z "$TMPD" ] || rm -rf "${TMPD:?}"; }
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

# Keenetic MIPS is little-endian (MT7621, MT7628) or big-endian (EN75xx):
# uname says "mips" for both, the ELF header of the router's own shell tells.
engine_arch() {
    [ -z "${VWARD_AWG_ARCH:-}" ] || { echo "$VWARD_AWG_ARCH"; return 0; }
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

op_install() {
    [ ! -x "$BIN" ] || [ "$(cat "$ENGINE_SHARE/version" 2>/dev/null)" != "$WP_VERSION" ] || { echo "result=unchanged"; return 0; }
    a=$(engine_arch) || die arch_unsupported
    want=$(wp_sum "$a") || die arch_unsupported
    mkdir -p "$ENGINE_SHARE" || die write_failed
    TMPD=$(mktemp -d "$ENGINE_SHARE/.install.XXXXXX" 2>/dev/null) || die write_failed
    "$CURL" -fsSL --connect-timeout 15 --max-time 300 --max-filesize 16777216 \
        -o "$TMPD/wp.tgz" "$WP_URL/wireproxy_linux_$a.tar.gz" 2>/dev/null || die download_failed
    [ "$(sha256_of "$TMPD/wp.tgz")" = "$want" ] || die checksum_mismatch
    tar xzf "$TMPD/wp.tgz" -C "$TMPD" wireproxy 2>/dev/null && [ -s "$TMPD/wireproxy" ] || die package_damaged
    chmod 0755 "$TMPD/wireproxy" || die write_failed
    "$TMPD/wireproxy" -v >/dev/null 2>&1 || die binary_not_runnable
    mv -f "$TMPD/wireproxy" "$BIN" || die write_failed
    echo "$WP_VERSION" > "$ENGINE_SHARE/version"
    log "installed $WP_VERSION arch=$a"
    echo "result=changed"
}

row_of() { [ -f "$TUNNELS" ] && awk -F'\t' -v p="$1" '$2 == p {print; exit}' "$TUNNELS"; }

free_slot() {
    n=0
    while [ "$n" -lt "$MAX_TUNNELS" ]; do
        awk -F'\t' -v n="$n" '$1 == n {f=1} END{exit f ? 0 : 1}' "$TUNNELS" 2>/dev/null || { echo "$n"; return 0; }
        n=$((n + 1))
    done
    return 1
}

rci() {
    # rci JSON: one RCI request; Keenetic answers 200 either way, errors say "error".
    r_out=$("$CURL" -fsS --max-time 15 -H 'Content-Type: application/json' -d "$1" "$RCI/" 2>/dev/null) || return 1
    printf '%s\n' "$r_out" | "$JQ" -e '[.. | objects | select(.status? == "error")] | length == 0' >/dev/null 2>&1
}

# Keenetic's own words for the last refused request (no keys go to RCI here).
rci_why() {
    w=$(printf '%s\n' "$r_out" | "$JQ" -r '[.. | objects | select(.status? == "error") | .message? // empty] | first // empty' 2>/dev/null |
        tr -cs 'A-Za-z0-9 ._:,()/-' ' ' | cut -c1-200)
    echo "${w:-no answer}"
}

# pid_of SLOT: the tunnel's program while it runs (a zombie left by a kill is not running).
pid_of() {
    p=$(cat "$ENGINE_RUN/t$1.pid" 2>/dev/null)
    case "$p" in ''|*[!0-9]*) return 1 ;; esac
    s=$(cat "/proc/$p/stat" 2>/dev/null) || return 1
    s=${s##*) }
    case "$s" in Z*|X*) return 1 ;; esac
    echo "$p"
}

start_one() {
    # start_one SLOT: the tunnel's wireproxy in the background, memory kept small.
    mkdir -p "$ENGINE_RUN" || return 1
    [ -z "$(pid_of "$1")" ] || return 0
    (
        GOMAXPROCS=2 GOMEMLIMIT=24MiB GOGC=50 GODEBUG=madvdontneed=1
        export GOMAXPROCS GOMEMLIMIT GOGC GODEBUG
        exec "$BIN" -s -c "$ENGINE_ETC/t$1.wp" -i "127.0.0.1:$((PORT_BASE + 100 + $1))" </dev/null >/dev/null 2>&1
    ) &
    echo $! > "$ENGINE_RUN/t$1.pid"
}

stop_one() {
    p=$(pid_of "$1") || :
    [ -z "$p" ] || { kill "$p" 2>/dev/null; sleep 1; kill -9 "$p" 2>/dev/null; }
    rm -f "$ENGINE_RUN/t$1.pid"
}

# The health page also carries the private key: only the handshake time is read.
handshake_age() {
    h=$("$CURL" -fs --max-time 4 "http://127.0.0.1:$((PORT_BASE + 100 + $1))/metrics" 2>/dev/null |
        sed -n 's/^last_handshake_time_sec=//p' | sort -n | tail -n 1)
    case "$h" in ''|*[!0-9]*|0) return 1 ;; esac
    echo $(( $(date +%s) - h ))
}

op_add() {
    desc=$1 conf=$2
    case "$desc" in ''|*'"'*|*"$(printf '\134')"*) die invalid_description 64 ;; esac
    [ "${#desc}" -le 64 ] || die invalid_description 64
    [ -f "$conf" ] && [ ! -L "$conf" ] && grep -qi '^\[Interface\]' "$conf" && grep -qi '^\[Peer\]' "$conf" || die conf_syntax 64
    [ -x "$BIN" ] || ( trap cleanup EXIT; op_install ) >/dev/null || die engine_install_failed
    mkdir -p "$ENGINE_ETC" && chmod 0700 "$ENGINE_ETC" || die write_failed
    n=$(free_slot) || die engine_full
    proxy="Proxy$((PROXY_BASE + n))" port=$((PORT_BASE + n))
    (umask 077
     # The tunnel's own .conf without any proxy sections it may carry, then ours.
     tr -d '\r' < "$conf" | awk 'tolower($0) ~ /^\[(socks5|http|tcpclienttunnel|tcpservertunnel|stdiotunnel)\]/ {skip=1; next}
        skip && /^\[/ {skip=0} !skip' > "$ENGINE_ETC/t$n.conf" &&
     printf 'WGConfig = %s\n\n[Socks5]\nBindAddress = 127.0.0.1:%s\n' "$ENGINE_ETC/t$n.conf" "$port" > "$ENGINE_ETC/t$n.wp") || die write_failed
    "$BIN" -n -c "$ENGINE_ETC/t$n.wp" >/dev/null 2>&1 || { rm -f "$ENGINE_ETC/t$n.conf" "$ENGINE_ETC/t$n.wp"; die conf_rejected; }
    start_one "$n" || die engine_start_failed
    w=0
    until handshake_age "$n" >/dev/null; do
        w=$((w + 2))
        [ "$w" -le "$HANDSHAKE_WAIT" ] || { stop_one "$n"; rm -f "$ENGINE_ETC/t$n.conf" "$ENGINE_ETC/t$n.wp"; die tunnel_no_handshake; }
        sleep 2
    done
    # Keenetic's «Прокси» connection to the local port; UDP goes through as well.
    rci "[{\"interface\":{\"name\":\"$proxy\",\"description\":\"$desc\",\"proxy\":{\"protocol\":{\"proto\":\"socks5\"},\"upstream\":{\"host\":\"127.0.0.1\",\"port\":\"$port\"},\"socks5-udp\":true}}}]" &&
        rci "[{\"interface\":{\"name\":\"$proxy\",\"up\":true}},{\"system\":{\"configuration\":{\"save\":true}}}]" || {
        log "router_rejected $proxy: $(rci_why)"
        rci "[{\"interface\":{\"name\":\"$proxy\",\"no\":true}}]"
        stop_one "$n"; rm -f "$ENGINE_ETC/t$n.conf" "$ENGINE_ETC/t$n.wp"; die router_rejected; }
    printf '%s\t%s\t%s\t%s\n' "$n" "$proxy" "$port" "$desc" >> "$TUNNELS"
    log "added $proxy slot=$n"
    printf 'info.name=%s\n' "$proxy"
    echo "result=changed"
}

op_remove() {
    row=$(row_of "$1")
    [ -n "$row" ] || die unknown_tunnel 64
    n=$(printf '%s' "$row" | cut -f1)
    rci "[{\"interface\":{\"name\":\"$1\",\"no\":true}},{\"system\":{\"configuration\":{\"save\":true}}}]" || die router_rejected
    stop_one "$n"
    rm -f "$ENGINE_ETC/t$n.conf" "$ENGINE_ETC/t$n.wp"
    awk -F'\t' -v p="$1" '$2 != p' "$TUNNELS" > "$TUNNELS.new" && mv -f "$TUNNELS.new" "$TUNNELS"
    log "removed $1"
    echo "result=changed"
}

# supervise: every minute (from the tunnel health check): a tunnel whose program
# stopped is started again.  Nothing to do - nothing runs.
op_supervise() {
    [ -s "$TUNNELS" ] && [ -x "$BIN" ] || { echo "result=unchanged"; return 0; }
    started=0
    while IFS="$(printf '\t')" read -r n proxy port desc; do
        [ -n "$(pid_of "$n")" ] && continue
        start_one "$n" && started=$((started + 1)) && log "restarted $proxy"
    done < "$TUNNELS"
    [ "$started" = 0 ] && echo "result=unchanged" || echo "result=changed"
}

op_stop() {
    [ -f "$TUNNELS" ] || { echo "result=unchanged"; return 0; }
    while IFS="$(printf '\t')" read -r n proxy port desc; do stop_one "$n"; done < "$TUNNELS"
    echo "result=changed"
}

# status: plain facts for the Panel, never the keys.
op_status() {
    printf 'info.installed=%s\n' "$([ -x "$BIN" ] && echo 1 || echo 0)"
    printf 'info.version=%s\n' "$(cat "$ENGINE_SHARE/version" 2>/dev/null)"
    printf 'info.arch=%s\n' "$(engine_arch 2>/dev/null)"
    [ -f "$TUNNELS" ] && while IFS="$(printf '\t')" read -r n proxy port desc; do
        p=$(pid_of "$n") || :
        age=$(handshake_age "$n" 2>/dev/null) || age=
        rss=; [ -z "$p" ] || rss=$(awk '/^VmRSS:/ {print $2}' "/proc/$p/status" 2>/dev/null)
        ep=$(sed -n 's/^[Ee]ndpoint *= *//p' "$ENGINE_ETC/t$n.conf" 2>/dev/null | head -n 1)
        printf 'tunnel=%s\t%s\t%s\t%s\t%s\t%s\n' "$proxy" "$([ -n "$p" ] && echo 1 || echo 0)" "$age" "$rss" "$ep" "$desc"
    done < "$TUNNELS"
    echo "result=status"
}

case "${1:-}" in
    install) op_install ;;
    add) [ "$#" -eq 3 ] || die usage 64; op_add "$2" "$3" ;;
    remove) [ "$#" -eq 2 ] || die usage 64; op_remove "$2" ;;
    supervise) op_supervise ;;
    stop) op_stop ;;
    status) op_status ;;
    *) die usage 64 ;;
esac
