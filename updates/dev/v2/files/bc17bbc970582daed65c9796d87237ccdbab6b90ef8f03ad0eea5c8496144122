#!/bin/sh
# VWARD tunnel engine («Контур AmneziaWG»): holds tunnels whose format the
# firmware cannot (AmneziaWG 3.x on KeeneticOS 5.1).  Keenetic makes an
# «OpkgTun» connection with its own TUN adapter (opkgtunN), and vward-awg
# (tools/vward-awg: amneziawg-go as a library, userspace, no kernel modules)
# attaches to that adapter and carries its packets to the server.  Keenetic
# keeps the address and routes, so lists and subnets go to it like to any
# Keenetic tunnel.  (A «Прокси» connection needed Keenetic's proxy client
# component, which some models do not have.)
#
# The program is downloaded only when the first such tunnel is added, from the
# awg-engine branch, and checked against the SHA-256 pinned below.  Tunnel
# files hold private keys: root-only, never printed, never in a process's
# arguments.
#
# vward-awg-engine.sh install | add DESCRIPTION FILE | remove NAME |
#                     restart NAME | disable NAME | enable NAME | supervise | stop | status
# Output: "result=..." / "info.key=value" lines, or "error=<code>".
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

ENGINE_ETC=${VWARD_AWG_ETC:-/opt/etc/vward/awg-engine}
ENGINE_SHARE=${VWARD_AWG_SHARE:-/opt/share/vward/awg-engine}
ENGINE_RUN=${VWARD_AWG_RUN:-/opt/var/run/vward/awg-engine}
ENGINE_LOG=${VWARD_AWG_LOG:-/opt/var/log/vward-awg-engine.log}
TUNNELS="$ENGINE_ETC/tunnels.tsv"
BIN="$ENGINE_SHARE/vward-awg"
CURL=${VWARD_CURL_BIN:-curl}
NDMC=${VWARD_NDMC:-ndmc}
HANDSHAKE_WAIT=${VWARD_AWG_HANDSHAKE_WAIT:-30}
MAX_TUNNELS=5
# Keenetic numbers OpkgTun connections 0-9; other programs may hold some.
OPKGTUN_MAX=9

AWG_VERSION=1.2.1
AWG_URL=${VWARD_AWG_URL:-https://raw.githubusercontent.com/Ziegfe1d/VWARD/awg-engine}
# SHA-256 of the unpacked program (tools/vward-awg/SHA256SUMS, a reproducible build).
awg_sum() {
    case "$1" in
        mipsle) echo 8b25dc552a32a167d14c311af26f518df28a862003c7d9875d1493010f3055c8 ;;
        mips) echo 3c176960b18e981b04d5fb7d2516664cb7b37ef4b7c9bbdd47875827b6873ebb ;;
        arm64) echo d24686806f754302b5abb18ce50cdd3b2008e1877180d90108a69fe74517fe03 ;;
        arm) echo 0ff2dd832ae71c8097aa9ea7888e355d98ad00c314cc7e558414865a756da023 ;;
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
    [ ! -x "$BIN" ] || [ "$(cat "$ENGINE_SHARE/version" 2>/dev/null)" != "$AWG_VERSION" ] || { echo "result=unchanged"; return 0; }
    a=$(engine_arch) || die arch_unsupported
    want=$(awg_sum "$a") || die arch_unsupported
    mkdir -p "$ENGINE_SHARE" || die write_failed
    TMPD=$(mktemp -d "$ENGINE_SHARE/.install.XXXXXX" 2>/dev/null) || die write_failed
    "$CURL" -fsSL --connect-timeout 15 --max-time 300 --max-filesize 8388608 \
        -o "$TMPD/p.gz" "$AWG_URL/vward-awg-linux-$a.gz" 2>/dev/null || die download_failed
    gunzip -c "$TMPD/p.gz" > "$TMPD/vward-awg" 2>/dev/null || die package_damaged
    [ "$(sha256_of "$TMPD/vward-awg")" = "$want" ] || die checksum_mismatch
    chmod 0755 "$TMPD/vward-awg" || die write_failed
    "$TMPD/vward-awg" -v >/dev/null 2>&1 || die binary_not_runnable
    mv -f "$TMPD/vward-awg" "$BIN" || die write_failed
    echo "$AWG_VERSION" > "$ENGINE_SHARE/version"
    # The SOCKS program of earlier builds is no longer used.
    rm -f "$ENGINE_SHARE/wireproxy"
    log "installed vward-awg $AWG_VERSION arch=$a"
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

ndm() {
    # ndm COMMAND: one Keenetic command (never a key); its own words go to the log on refusal.
    ndm_out=$("$NDMC" -c "$1" 2>&1) || { log "refused: $1: $(ndm_why)"; return 1; }
    printf '%s\n' "$ndm_out" | grep -Eqi '(^|[^a-z])(error|failed|invalid|unknown command|not found|no such)' || return 0
    log "refused: $1: $(ndm_why)"
    return 1
}
ndm_why() { printf '%s' "$ndm_out" | tr -cs 'A-Za-z0-9 ._:,()"/[]-' ' ' | cut -c1-200; }

# free_opkgtun: the first OpkgTun number no connection in Keenetic uses.
free_opkgtun() {
    rc=$("$NDMC" -c "show running-config" 2>/dev/null) || return 1
    k=0
    while [ "$k" -le "$OPKGTUN_MAX" ]; do
        printf '%s\n' "$rc" | grep -qx "interface OpkgTun$k" || { echo "$k"; return 0; }
        k=$((k + 1))
    done
    return 1
}

# conf_address FILE: the tunnel's IPv4 address as "ADDRESS MASK" for Keenetic.
conf_address() {
    tr -d '\r' < "$1" | awk -F'=' 'tolower($1) ~ /^[ \t]*address[ \t]*$/ {
        n = split($2, a, ",")
        for (i = 1; i <= n; i++) {
            v = a[i]; gsub(/[ \t]/, "", v)
            if (v !~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(\/[0-9]+)?$/) continue
            p = 32; if (split(v, b, "/") == 2) {v = b[1]; p = b[2] + 0}
            if (p < 1 || p > 32) continue
            m = ""; for (j = 0; j < 4; j++) {bits = p - 8 * j; if (bits > 8) bits = 8; if (bits < 0) bits = 0
                m = m (j ? "." : "") (256 - 2 ^ (8 - bits)) % 256}
            print v " " m; exit
        }
    }'
}

adapter_of() { printf 'opkgtun%s\n' "${1#OpkgTun}"; }

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
    # start_one SLOT NAME: the tunnel's program in the background on Keenetic's adapter.
    mkdir -p "$ENGINE_RUN" || return 1
    [ -z "$(pid_of "$1")" ] || return 0
    # Measured on Viva (MT7621, 4 threads): two threads move as much as four (13-22 Mbit/s
    # either way, the channel varies more) at 27% of the CPU instead of 37-48%, and leave the
    # other two to the router. A memory limit (24 MiB, GOGC=50) cut the speed to 3 Mbit/s.
    (
        GOMAXPROCS=${VWARD_AWG_THREADS:-2} GOGC=100 GODEBUG=madvdontneed=1
        export GOMAXPROCS GOGC GODEBUG
        # Started from a background job (lowest priority): the tunnel carries the owner's
        # traffic and takes the normal priority back.
        VWARD_TUNNEL_NICE=
        [ "${VWARD_BACKGROUND:-0}" != 1 ] || VWARD_TUNNEL_NICE="nice -n -19"
        # fd 3 (an add's step channel) is not the tunnel's to keep open.
        exec $VWARD_TUNNEL_NICE "$BIN" -i "$(adapter_of "$2")" -c "$ENGINE_ETC/t$1.conf" -s "$ENGINE_RUN/t$1.state" </dev/null >/dev/null 2>"$ENGINE_RUN/t$1.err" 3>&-
    ) &
    echo $! > "$ENGINE_RUN/t$1.pid"
}

stop_one() {
    p=$(pid_of "$1") || :
    [ -z "$p" ] || { kill "$p" 2>/dev/null; sleep 1; kill -9 "$p" 2>/dev/null; }
    rm -f "$ENGINE_RUN/t$1.pid" "$ENGINE_RUN/t$1.state"
}

# The program writes the last handshake time to its state file (never a key).
handshake_age() {
    h=$(sed -n 's/^handshake=//p' "$ENGINE_RUN/t$1.state" 2>/dev/null)
    case "$h" in ''|*[!0-9]*|0) return 1 ;; esac
    echo $(( $(date +%s) - h ))
}

# step NAME: where an add stands, for the Panel's progress window (fd 3 when the caller
# opened it; nothing otherwise).
step() { { printf 'step=%s\n' "$1" >&3; } 2>/dev/null || :; }

op_add() {
    desc=$1 conf=$2
    case "$desc" in ''|*'"'*|*"$(printf '\134')"*) die invalid_description 64 ;; esac
    [ "${#desc}" -le 64 ] || die invalid_description 64
    [ -f "$conf" ] && [ ! -L "$conf" ] && grep -qi '^\[Interface\]' "$conf" && grep -qi '^\[Peer\]' "$conf" || die conf_syntax 64
    addr=$(conf_address "$conf"); [ -n "$addr" ] || die conf_no_address 64
    [ -x "$BIN" ] && [ "$(cat "$ENGINE_SHARE/version" 2>/dev/null)" = "$AWG_VERSION" ] ||
        { step download; ( trap cleanup EXIT; op_install ) >/dev/null; } || die engine_install_failed
    mkdir -p "$ENGINE_ETC" && chmod 0700 "$ENGINE_ETC" || die write_failed
    n=$(free_slot) || die engine_full
    k=$(free_opkgtun) || die no_free_tunnel
    name="OpkgTun$k"
    (umask 077; tr -d '\r' < "$conf" > "$ENGINE_ETC/t$n.conf") || die write_failed
    "$BIN" -n -c "$ENGINE_ETC/t$n.conf" >/dev/null 2>&1 || { rm -f "$ENGINE_ETC/t$n.conf"; die conf_rejected; }
    # Keenetic makes the connection and its adapter first; the program attaches to it.
    undo() { stop_one "$n"; ndm "no interface $name" >/dev/null 2>&1; rm -f "$ENGINE_ETC/t$n.conf" "$ENGINE_RUN/t$n.err"; }
    step router
    for c in "interface $name" "interface $name description \"$desc\"" "interface $name ip address $addr" \
             "interface $name security-level public" "interface $name ip tcp adjust-mss pmtu" "interface $name up"; do
        ndm "$c" || { undo; die router_rejected; }
    done
    step program
    start_one "$n" "$name" || { undo; die engine_start_failed; }
    step handshake
    w=0
    until handshake_age "$n" >/dev/null; do
        w=$((w + 2))
        [ "$w" -le "$HANDSHAKE_WAIT" ] || { undo; die tunnel_no_handshake; }
        sleep 2
    done
    step save
    ndm "system configuration save" || { undo; die config_save_failed; }
    printf '%s\t%s\t-\t%s\n' "$n" "$name" "$desc" >> "$TUNNELS"
    log "added $name slot=$n"
    printf 'info.name=%s\n' "$name"
    echo "result=changed"
}

op_remove() {
    row=$(row_of "$1")
    [ -n "$row" ] || die unknown_tunnel 64
    n=$(printf '%s' "$row" | cut -f1)
    stop_one "$n"
    ndm "no interface $1" && ndm "system configuration save" || die router_rejected
    rm -f "$ENGINE_ETC/t$n.conf" "$ENGINE_ETC/t$n.wp" "$ENGINE_ETC/t$n.off" "$ENGINE_RUN/t$n.err"
    awk -F'\t' -v p="$1" '$2 != p' "$TUNNELS" > "$TUNNELS.new" && mv -f "$TUNNELS.new" "$TUNNELS"
    log "removed $1"
    echo "result=changed"
}

# supervise: every minute (from the tunnel health check): a tunnel whose program
# stopped is started again.  Nothing to do - nothing runs.
op_supervise() {
    [ -s "$TUNNELS" ] && [ -x "$BIN" ] || { echo "result=unchanged"; return 0; }
    started=0
    while IFS="$(printf '\t')" read -r n name port desc; do
        case "$name" in OpkgTun[0-9]) ;; *) continue ;; esac
        [ ! -e "$ENGINE_ETC/t$n.off" ] || continue
        [ -n "$(pid_of "$n")" ] && continue
        start_one "$n" "$name" && started=$((started + 1)) && log "restarted $name"
    done < "$TUNNELS"
    [ "$started" = 0 ] && echo "result=unchanged" || echo "result=changed"
}

# restart NAME: the tunnel's program again (the Panel's «Перезапустить»), then its handshake.
op_restart() {
    row=$(row_of "$1")
    [ -n "$row" ] || die unknown_tunnel 64
    n=$(printf '%s' "$row" | cut -f1)
    stop_one "$n"
    step program
    start_one "$n" "$1" || die engine_start_failed
    step handshake
    w=0
    until handshake_age "$n" >/dev/null; do
        w=$((w + 2))
        [ "$w" -le "$HANDSHAKE_WAIT" ] || die tunnel_no_handshake
        sleep 2
    done
    log "restarted $1 by request"
    echo "result=changed"
}

op_stop() {
    [ -f "$TUNNELS" ] || { echo "result=unchanged"; return 0; }
    while IFS="$(printf '\t')" read -r n name port desc; do stop_one "$n"; done < "$TUNNELS"
    echo "result=changed"
}

# status: plain facts for the Panel, never the keys.
op_status() {
    printf 'info.installed=%s\n' "$([ -x "$BIN" ] && echo 1 || echo 0)"
    printf 'info.version=%s\n' "$(cat "$ENGINE_SHARE/version" 2>/dev/null)"
    printf 'info.arch=%s\n' "$(engine_arch 2>/dev/null)"
    [ -f "$TUNNELS" ] && while IFS="$(printf '\t')" read -r n name port desc; do
        p=$(pid_of "$n") || :
        age=$(handshake_age "$n" 2>/dev/null) || age=
        rss=; [ -z "$p" ] || rss=$(awk '/^VmRSS:/ {print $2}' "/proc/$p/status" 2>/dev/null)
        ep=$(sed -n 's/^[Ee]ndpoint *= *//p' "$ENGINE_ETC/t$n.conf" 2>/dev/null | head -n 1)
        # Traffic from the program's own state (Keenetic does not see the peer of an OpkgTun).
        rx=; tx=; [ -z "$p" ] || { rx=$(sed -n 's/^rx=//p' "$ENGINE_RUN/t$n.state" 2>/dev/null); tx=$(sed -n 's/^tx=//p' "$ENGINE_RUN/t$n.state" 2>/dev/null); }
        printf 'tunnel=%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$([ -n "$p" ] && echo 1 || echo 0)" "$age" "$rss" "$ep" "$desc" "$rx" "$tx" "$([ -e "$ENGINE_ETC/t$n.off" ] && echo 1 || echo 0)"
    done < "$TUNNELS"
    echo "result=status"
}

# disable NAME / enable NAME: the owner switched the tunnel off in the Panel. Its program
# stops and supervise leaves it alone until it is switched on again (a flag file, so the
# choice outlives a reboot).
op_disable() {
    row=$(row_of "$1")
    [ -n "$row" ] || die unknown_tunnel 64
    n=$(printf '%s' "$row" | cut -f1)
    stop_one "$n"
    : > "$ENGINE_ETC/t$n.off" || die write_failed
    log "disabled $1"
    echo "result=changed"
}

op_enable() {
    row=$(row_of "$1")
    [ -n "$row" ] || die unknown_tunnel 64
    n=$(printf '%s' "$row" | cut -f1)
    [ -e "$ENGINE_ETC/t$n.off" ] || { echo "result=unchanged"; return 0; }
    rm -f "$ENGINE_ETC/t$n.off" || die write_failed
    log "enabled $1"
    echo "result=changed"
}

# The real-time watcher learns the tunnels' programs and interfaces.
sentinel_reload() { [ ! -x /opt/bin/vward-sentinel.sh ] || /opt/bin/vward-sentinel.sh reload </dev/null >/dev/null 2>&1 || :; }

case "${1:-}" in
    install) op_install ;;
    add) [ "$#" -eq 3 ] || die usage 64; op_add "$2" "$3"; sentinel_reload ;;
    remove) [ "$#" -eq 2 ] || die usage 64; op_remove "$2"; sentinel_reload ;;
    restart) [ "$#" -eq 2 ] || die usage 64; op_restart "$2" ;;
    disable) [ "$#" -eq 2 ] || die usage 64; op_disable "$2" ;;
    enable) [ "$#" -eq 2 ] || die usage 64; op_enable "$2" ;;
    supervise) op_supervise ;;
    stop) op_stop ;;
    status) op_status ;;
    *) die usage 64 ;;
esac
