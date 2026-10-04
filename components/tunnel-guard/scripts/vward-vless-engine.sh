#!/bin/sh
# VWARD VLESS engine: a VLESS server (a vless:// link, or one server of a subscription)
# as a Keenetic tunnel. Keenetic makes an «OpkgTun» connection with its own TUN adapter
# (opkgtunN), and Xray (its TUN inbound, since Xray 26.1.23) attaches to that adapter and
# carries the packets to the server; Keenetic keeps the address and the routes, so lists
# and subnets go to it like to any Keenetic tunnel. Off by default: nothing is downloaded
# until the first VLESS tunnel is added.
#
# Xray is the official build of XTLS/Xray-core, downloaded once and checked against the
# SHA-256 pinned below. A link holds the user's id (a key): the files are root-only and it
# is never printed, logged or put in a process's arguments.
#
# vward-vless-engine.sh servers FILE | add DESCRIPTION FILE | remove NAME | restart NAME |
#                       disable NAME | enable NAME | supervise | stop | status | install
# FILE: vless:// links, one a line, or the address of a subscription (https://...); a line
# "#server=N" chooses the N-th server (1 by default).
# Output: "result=..." / "info.key=value" lines, or "error=<code>".
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

ENGINE_ETC=${VWARD_VLESS_ETC:-/opt/etc/vward/vless-engine}
ENGINE_SHARE=${VWARD_VLESS_SHARE:-/opt/share/vward/vless-engine}
ENGINE_RUN=${VWARD_VLESS_RUN:-/opt/var/run/vward/vless-engine}
ENGINE_LOG=${VWARD_VLESS_LOG:-/opt/var/log/vward-vless-engine.log}
TUNNELS="$ENGINE_ETC/tunnels.tsv"
BIN="$ENGINE_SHARE/xray"
CURL=${VWARD_CURL_BIN:-curl}
NDMC=${VWARD_NDMC:-ndmc}
JQ=${JQ:-jq}
CONNECT_WAIT=${VWARD_VLESS_CONNECT_WAIT:-30}
MAX_TUNNELS=5
OPKGTUN_MAX=9
CHECK_URL=${VWARD_VLESS_CHECK_URL:-https://1.1.1.1/cdn-cgi/trace}

XRAY_VERSION=26.9.9
XRAY_URL=${VWARD_XRAY_URL:-https://github.com/XTLS/Xray-core/releases/download/v$XRAY_VERSION}
# SHA-256 of the release archives (the .dgst files of the release).
xray_zip() {
    case "$1" in
        mipsle) echo "Xray-linux-mips32le.zip e572d2cdd819318383460443140898e6117e8e0da5f0c359b25f6c890b8d81a2 xray_softfloat" ;;
        mips) echo "Xray-linux-mips32.zip 4b9838c570f283d7104e0c775df3562a4f12f33c06e6c77ddcf2319845bf47ba xray_softfloat" ;;
        arm64) echo "Xray-linux-arm64-v8a.zip 3e38d72dfc5eb65c91df0e5583e9b6676c32232041da47de6ae73946b526d66c xray" ;;
        arm) echo "Xray-linux-arm32-v7a.zip 5b2a9e2767c0197f7bd41c2db133f91440e845771e621178e0fd2b8520228e5f xray" ;;
        *) return 1 ;;
    esac
}

die() { printf 'error=%s\n' "$1"; exit "${2:-1}"; }
log() { mkdir -p "${ENGINE_LOG%/*}" 2>/dev/null; printf '%s|VLESS_ENGINE|%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$ENGINE_LOG" 2>/dev/null; }

TMPD=
cleanup() { [ -z "$TMPD" ] || rm -rf "${TMPD:?}"; }
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

# The same processor names as the tunnel engine: MIPS endianness from the router's own shell.
engine_arch() {
    [ -z "${VWARD_VLESS_ARCH:-}" ] || { echo "$VWARD_VLESS_ARCH"; return 0; }
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

# unzip_one ZIP MEMBER OUT: BusyBox or Entware unzip; Entware's is installed when neither is.
unzip_one() {
    if command -v unzip >/dev/null 2>&1; then unzip -p "$1" "$2" > "$3" 2>/dev/null && [ -s "$3" ] && return 0; fi
    if command -v busybox >/dev/null 2>&1; then busybox unzip -p "$1" "$2" > "$3" 2>/dev/null && [ -s "$3" ] && return 0; fi
    command -v opkg >/dev/null 2>&1 && opkg install unzip >/dev/null 2>&1 && unzip -p "$1" "$2" > "$3" 2>/dev/null && [ -s "$3" ]
}

op_install() {
    [ ! -x "$BIN" ] || [ "$(cat "$ENGINE_SHARE/version" 2>/dev/null)" != "$XRAY_VERSION" ] || { echo "result=unchanged"; return 0; }
    a=$(engine_arch) || die arch_unsupported
    set -- $(xray_zip "$a") || die arch_unsupported
    [ "$#" -eq 3 ] || die arch_unsupported
    mkdir -p "$ENGINE_SHARE" || die write_failed
    TMPD=$(mktemp -d "$ENGINE_SHARE/.install.XXXXXX" 2>/dev/null) || die write_failed
    "$CURL" -fsSL --connect-timeout 15 --max-time 600 --max-filesize 67108864 \
        -o "$TMPD/x.zip" "$XRAY_URL/$1" 2>/dev/null || die download_failed
    [ "$(sha256_of "$TMPD/x.zip")" = "$2" ] || die checksum_mismatch
    unzip_one "$TMPD/x.zip" "$3" "$TMPD/xray" || die package_damaged
    rm -f "$TMPD/x.zip"
    chmod 0755 "$TMPD/xray" || die write_failed
    "$TMPD/xray" version >/dev/null 2>&1 || die binary_not_runnable
    mv -f "$TMPD/xray" "$BIN" || die write_failed
    echo "$XRAY_VERSION" > "$ENGINE_SHARE/version"
    log "installed xray $XRAY_VERSION arch=$a"
    echo "result=changed"
}

# links FILE OUT: the vless:// links of FILE, or of the subscription it names (base64 or plain).
links() {
    src=$(tr -d '\r' < "$1" | grep -v '^#' | awk 'NF {sub(/^[ \t]+/, ""); sub(/[ \t]+$/, ""); print; exit}')
    case "$src" in
        vless://*) tr -d '\r' < "$1" | awk '/^vless:\/\// {print $1}' > "$2" ;;
        https://*|http://*)
            printf '%s\n' "$src" | grep -Eq '^https?://[A-Za-z0-9._~:/?#@!$&()*+,;=%-]+$' || return 2
            "$CURL" -fsSL --connect-timeout 10 --max-time 30 --max-filesize 1048576 -A "VWARD" \
                -o "$2.raw" "$src" 2>/dev/null || return 3
            if grep -q 'vless://' "$2.raw"; then tr -d '\r' < "$2.raw"
            else tr -d '\r\n ' < "$2.raw" | { base64 -d 2>/dev/null || openssl base64 -d -A 2>/dev/null; } | tr -d '\r'; fi |
                awk '/^vless:\/\// {print $1}' > "$2"
            rm -f "$2.raw" ;;
        *) return 2 ;;
    esac
    [ -s "$2" ]
}

# parse LINK: the link's parts as KEY<TAB>VALUE lines (percent-decoded), for jq.
parse() {
    # Bytes, not characters: a percent-encoded UTF-8 name comes out as it was.
    printf '%s\n' "$1" | LC_ALL=C awk '
        function dec(s,   o, i, c, h) {
            o = ""
            for (i = 1; i <= length(s); i++) {
                c = substr(s, i, 1)
                if (c == "%" && i + 2 <= length(s)) { h = toupper(substr(s, i + 1, 2)); o = o sprintf("%c", index("0123456789ABCDEF", substr(h, 1, 1)) * 16 + index("0123456789ABCDEF", substr(h, 2, 1)) - 17); i += 2 }
                else if (c == "+") o = o " "
                else o = o c
            }
            return o
        }
        {
            s = substr($0, 9); frag = ""; q = ""
            i = index(s, "#"); if (i) { frag = substr(s, i + 1); s = substr(s, 1, i - 1) }
            i = index(s, "?"); if (i) { q = substr(s, i + 1); s = substr(s, 1, i - 1) }
            sub(/\/$/, "", s)
            i = index(s, "@"); if (!i) exit 1
            print "id\t" dec(substr(s, 1, i - 1)); hp = substr(s, i + 1)
            if (substr(hp, 1, 1) == "[") { i = index(hp, "]"); host = substr(hp, 2, i - 2); port = substr(hp, i + 2) }
            else { i = index(hp, ":"); if (!i) exit 1; host = substr(hp, 1, i - 1); port = substr(hp, i + 1) }
            print "host\t" host; print "port\t" port; print "name\t" dec(frag)
            n = split(q, kv, "&")
            for (j = 1; j <= n; j++) { i = index(kv[j], "="); if (i) print "q." substr(kv[j], 1, i - 1) "\t" dec(substr(kv[j], i + 1)) }
        }'
}

# config LINK TUN OUT: the Xray configuration of the link on Keenetic's adapter TUN.
config() {
    parse "$1" > "$3.kv" || return 2
    # A UUID, or Xray's short form (up to 30 characters); Entware's jq has no regex.
    awk -F '\t' '$1 == "id" {print substr($0, 4); exit}' "$3.kv" |
        grep -Eq '^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[A-Za-z0-9_-]{1,30})$' || { rm -f "$3.kv"; return 2; }
    "$JQ" -Rn --arg tun "$2" '
        [inputs | split("\t") | {key: .[0], value: (.[1:] | join("\t"))}] | from_entries as $l |
        def q($k): $l["q." + $k] // "";
        (q("type") | if . == "" then "tcp" elif . == "raw" then "tcp" else . end) as $net |
        (q("security") | if . == "" then "none" else . end) as $sec |
        if (($l.port | tonumber? // 0) | . < 1 or . > 65535) or ($l.host == "") or
           ([$net] | inside(["tcp", "ws", "grpc", "xhttp", "httpupgrade"]) | not) or ([$sec] | inside(["none", "tls", "reality"]) | not)
        then error("unsupported") else . end |
        {log: {loglevel: "warning"},
         inbounds: [{tag: "tun", port: 0, protocol: "tun", settings: {name: $tun, mtu: 1400}}],
         outbounds: [{tag: "vless", protocol: "vless",
           settings: {vnext: [{address: $l.host, port: ($l.port | tonumber),
             users: [{id: $l.id, encryption: (q("encryption") | if . == "" then "none" else . end)} + (if q("flow") != "" then {flow: q("flow")} else {} end)]}]},
           streamSettings: ({network: $net, security: $sec}
             + (if $sec == "reality" then {realitySettings: {serverName: q("sni"), fingerprint: (q("fp") | if . == "" then "chrome" else . end),
                   publicKey: q("pbk"), shortId: q("sid"), spiderX: q("spx")}}
                elif $sec == "tls" then {tlsSettings: ({serverName: (q("sni") | if . == "" then $l.host else . end)}
                   + (if q("fp") != "" then {fingerprint: q("fp")} else {} end)
                   + (if q("alpn") != "" then {alpn: (q("alpn") | split(","))} else {} end))}
                else {} end)
             + (if $net == "ws" then {wsSettings: {path: (q("path") | if . == "" then "/" else . end), host: q("host")}}
                elif $net == "grpc" then {grpcSettings: {serviceName: q("serviceName")}}
                elif $net == "xhttp" then {xhttpSettings: {path: (q("path") | if . == "" then "/" else . end), host: q("host"), mode: (q("mode") | if . == "" then "auto" else . end)}}
                elif $net == "httpupgrade" then {httpupgradeSettings: {path: (q("path") | if . == "" then "/" else . end), host: q("host")}}
                elif q("headerType") == "http" then {tcpSettings: {header: {type: "http"}}}
                else {} end))},
           {tag: "direct", protocol: "freedom"}]}' < "$3.kv" > "$3" 2>/dev/null
    rc=$?; rm -f "$3.kv"; [ "$rc" = 0 ] || return 2
}

# chosen FILE LINKS: the N-th link ("#server=N" in FILE, 1 by default).
chosen() {
    k=$(tr -d '\r' < "$1" | sed -n 's/^#server=\([0-9][0-9]*\)$/\1/p' | head -n 1)
    sed -n "${k:-1}p" "$2"
}

# servers FILE: the servers for the Panel's choice, never the ids.
op_servers() {
    TMPD=$(mktemp -d /tmp/vward-vless.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    links "$1" "$TMPD/links"; rc=$?
    case "$rc" in 0) ;; 2) die vless_syntax 64 ;; 3) die subscription_unavailable ;; *) die vless_no_servers 64 ;; esac
    i=0
    while IFS= read -r l; do
        i=$((i + 1))
        [ "$i" -le 50 ] || break
        parse "$l" > "$TMPD/kv" 2>/dev/null || continue
        v() { awk -F '\t' -v k="$1" '$1 == k {print substr($0, length(k) + 2); exit}' "$TMPD/kv" | tr -d '|"\\' | cut -c1-64; }
        printf 'info.server.%s=%s|%s|%s|%s|%s\n' "$i" "$(v name)" "$(v host)" "$(v port)" "$(v q.security)" "$(v q.type)"
    done < "$TMPD/links"
    printf 'info.kind=vless\ninfo.servers=%s\n' "$i"
    echo "result=checked"
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
    ndm_out=$("$NDMC" -c "$1" 2>&1) || { log "refused: $1"; return 1; }
    printf '%s\n' "$ndm_out" | grep -Eqi '(^|[^a-z])(error|failed|invalid|unknown command|not found|no such)' || return 0
    log "refused: $1"
    return 1
}

free_opkgtun() {
    rc=$("$NDMC" -c "show running-config" 2>/dev/null) || return 1
    k=0
    while [ "$k" -le "$OPKGTUN_MAX" ]; do
        printf '%s\n' "$rc" | grep -qx "interface OpkgTun$k" || { echo "$k"; return 0; }
        k=$((k + 1))
    done
    return 1
}

adapter_of() { printf 'opkgtun%s\n' "${1#OpkgTun}"; }

pid_of() {
    p=$(cat "$ENGINE_RUN/v$1.pid" 2>/dev/null)
    case "$p" in ''|*[!0-9]*) return 1 ;; esac
    s=$(cat "/proc/$p/stat" 2>/dev/null) || return 1
    s=${s##*) }
    case "$s" in Z*|X*) return 1 ;; esac
    echo "$p"
}

start_one() {
    mkdir -p "$ENGINE_RUN" || return 1
    [ -z "$(pid_of "$1")" ] || return 0
    rm -f "$ENGINE_RUN/v$1.down"
    (
        # Two threads, as the tunnel engine: the router keeps the rest.
        GOMAXPROCS=${VWARD_VLESS_THREADS:-2} GOGC=50 GODEBUG=madvdontneed=1
        export GOMAXPROCS GOGC GODEBUG
        # Started from a background job (lowest priority): the tunnel carries the owner's
        # traffic and takes the normal priority back.
        VWARD_TUNNEL_NICE=
        [ "${VWARD_BACKGROUND:-0}" != 1 ] || VWARD_TUNNEL_NICE="nice -n -19"
        exec $VWARD_TUNNEL_NICE "$BIN" run -c "$ENGINE_ETC/v$1.json" </dev/null >/dev/null 2>"$ENGINE_RUN/v$1.err" 3>&-
    ) &
    echo $! > "$ENGINE_RUN/v$1.pid"
}

stop_one() {
    p=$(pid_of "$1") || :
    [ -z "$p" ] || { kill "$p" 2>/dev/null; sleep 1; kill -9 "$p" 2>/dev/null; }
    rm -f "$ENGINE_RUN/v$1.pid"
}

# connected NAME: a page opened through the tunnel's adapter (VLESS has no handshake to read).
connected() {
    "$CURL" -4 -s -o /dev/null --noproxy '*' --interface "$(adapter_of "$1")" --connect-timeout 5 --max-time 8 "$CHECK_URL" </dev/null 2>/dev/null
}

step() { { printf 'step=%s\n' "$1" >&3; } 2>/dev/null || :; }

op_add() {
    desc=$1 file=$2 keep=${3:-}
    [ -f "$file" ] && [ ! -L "$file" ] || die vless_syntax 64
    TMPD=$(mktemp -d /tmp/vward-vless.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    links "$file" "$TMPD/links"; rc=$?
    case "$rc" in 0) ;; 2) die vless_syntax 64 ;; 3) die subscription_unavailable ;; *) die vless_no_servers 64 ;; esac
    link=$(chosen "$file" "$TMPD/links")
    [ -n "$link" ] || die vless_no_servers 64
    if [ -z "$desc" ]; then desc=$(parse "$link" | awk -F '\t' '$1 == "name" {print substr($0, 6); exit}' | tr -d '"\\' | cut -c1-64); fi
    [ -n "$desc" ] || desc=VLESS
    case "$desc" in *'"'*|*"$(printf '\134')"*) die invalid_description 64 ;; esac
    [ -x "$BIN" ] && [ "$(cat "$ENGINE_SHARE/version" 2>/dev/null)" = "$XRAY_VERSION" ] ||
        { step download; ( TMPD=; trap cleanup EXIT; op_install ) >/dev/null; } || die engine_install_failed
    mkdir -p "$ENGINE_ETC" && chmod 0700 "$ENGINE_ETC" || die write_failed
    n=$(free_slot) || die engine_full
    k=$(free_opkgtun) || die no_free_tunnel
    name="OpkgTun$k"
    (umask 077; config "$link" "$(adapter_of "$name")" "$ENGINE_ETC/v$n.json") || { rm -f "$ENGINE_ETC/v$n.json"; die vless_unsupported 64; }
    "$BIN" run -test -c "$ENGINE_ETC/v$n.json" >/dev/null 2>&1 || { rm -f "$ENGINE_ETC/v$n.json"; die conf_rejected; }
    host=$(parse "$link" | awk -F '\t' '$1 == "host" {print $2; exit}')
    port=$(parse "$link" | awk -F '\t' '$1 == "port" {print $2; exit}')
    undo() { stop_one "$n"; ndm "no interface $name" >/dev/null 2>&1; rm -f "$ENGINE_ETC/v$n.json" "$ENGINE_RUN/v$n.err"; }
    # A private address no home network uses (the benchmarking range), one /30 a tunnel.
    step router
    for c in "interface $name" "interface $name description \"$desc\"" "interface $name ip address 198.18.$k.1 255.255.255.252" \
             "interface $name security-level public" "interface $name ip tcp adjust-mss pmtu" "interface $name up"; do
        ndm "$c" || { undo; die router_rejected; }
    done
    step program
    start_one "$n" || { undo; die engine_start_failed; }
    step handshake
    w=0 cw=$CONNECT_WAIT nohs=0
    [ "$keep" != keep ] || [ "$cw" -le 10 ] || cw=10
    until connected "$name"; do
        w=$((w + 5))
        [ -n "$(pid_of "$n")" ] || { undo; die tunnel_no_handshake; }
        if [ "$w" -gt "$cw" ]; then
            # «keep»: the owner chose to keep the tunnel though the server stayed silent.
            [ "$keep" = keep ] || { undo; die tunnel_no_handshake; }
            nohs=1; break
        fi
        sleep 2
    done
    step save
    ndm "system configuration save" || { undo; die config_save_failed; }
    printf '%s\t%s\t%s:%s\t%s\n' "$n" "$name" "$host" "$port" "$desc" >> "$TUNNELS"
    log "added $name slot=$n server=$host:$port"
    printf 'info.name=%s\n' "$name"
    [ "$nohs" = 0 ] || printf 'info.handshake=none\n'
    echo "result=changed"
}

op_remove() {
    row=$(row_of "$1")
    [ -n "$row" ] || die unknown_tunnel 64
    n=$(printf '%s' "$row" | cut -f1)
    stop_one "$n"
    ndm "no interface $1" && ndm "system configuration save" || die router_rejected
    rm -f "$ENGINE_ETC/v$n.json" "$ENGINE_ETC/v$n.off" "$ENGINE_RUN/v$n.err"
    awk -F'\t' -v p="$1" '$2 != p' "$TUNNELS" > "$TUNNELS.new" && mv -f "$TUNNELS.new" "$TUNNELS"
    log "removed $1"
    echo "result=changed"
}

# link_up ADAPTER: 0 when the adapter is switched on, 1 when off, 2 when there is no such
# adapter (nothing to say).
link_up() {
    f=$(cat "${VWARD_SYSFS_NET:-/sys/class/net}/$1/flags" 2>/dev/null) || return 2
    [ -n "$f" ] || return 2
    [ $((f & 1)) = 1 ]
}

# A stopped program starts again. Keenetic switching the interface off and on again (the
# guard does when the server is silent) leaves Xray on an adapter that no longer carries
# anything (seen on Viva 2026-10-04: no page opened until Xray restarted): after an «off»
# seen here, or when no page opens through a switched-on adapter, Xray starts afresh.
op_supervise() {
    [ -s "$TUNNELS" ] && [ -x "$BIN" ] || { echo "result=unchanged"; return 0; }
    started=0
    while IFS="$(printf '\t')" read -r n name server desc; do
        case "$name" in OpkgTun[0-9]) ;; *) continue ;; esac
        [ ! -e "$ENGINE_ETC/v$n.off" ] || continue
        if [ -z "$(pid_of "$n")" ]; then
            start_one "$n" && started=$((started + 1)) && log "restarted $name"
            continue
        fi
        link_up "$(adapter_of "$name")"
        case $? in
            1) : > "$ENGINE_RUN/v$n.down"; continue ;;
            2) continue ;;
        esac
        [ -e "$ENGINE_RUN/v$n.down" ] || ! connected "$name" </dev/null || continue
        stop_one "$n"
        start_one "$n" && started=$((started + 1)) && log "restarted $name on its adapter"
    done < "$TUNNELS"
    [ "$started" = 0 ] && echo "result=unchanged" || echo "result=changed"
}

op_restart() {
    row=$(row_of "$1")
    [ -n "$row" ] || die unknown_tunnel 64
    n=$(printf '%s' "$row" | cut -f1)
    stop_one "$n"
    step program
    start_one "$n" || die engine_start_failed
    step handshake
    w=0
    until connected "$1"; do
        w=$((w + 5))
        [ "$w" -le "$CONNECT_WAIT" ] || die tunnel_no_handshake
        sleep 2
    done
    log "restarted $1 by request"
    echo "result=changed"
}

op_stop() {
    [ -f "$TUNNELS" ] || { echo "result=unchanged"; return 0; }
    while IFS="$(printf '\t')" read -r n name server desc; do stop_one "$n"; done < "$TUNNELS"
    echo "result=changed"
}

# status: plain facts for the Panel, never the ids.
op_status() {
    printf 'info.installed=%s\n' "$([ -x "$BIN" ] && echo 1 || echo 0)"
    printf 'info.version=%s\n' "$(cat "$ENGINE_SHARE/version" 2>/dev/null)"
    printf 'info.arch=%s\n' "$(engine_arch 2>/dev/null)"
    [ -f "$TUNNELS" ] && while IFS="$(printf '\t')" read -r n name server desc; do
        p=$(pid_of "$n") || :
        rss=; [ -z "$p" ] || rss=$(awk '/^VmRSS:/ {print $2}' "/proc/$p/status" 2>/dev/null)
        printf 'tunnel=%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$([ -n "$p" ] && echo 1 || echo 0)" "$rss" "$server" "$desc" "$([ -e "$ENGINE_ETC/v$n.off" ] && echo 1 || echo 0)"
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
    : > "$ENGINE_ETC/v$n.off" || die write_failed
    log "disabled $1"
    echo "result=changed"
}

op_enable() {
    row=$(row_of "$1")
    [ -n "$row" ] || die unknown_tunnel 64
    n=$(printf '%s' "$row" | cut -f1)
    [ -e "$ENGINE_ETC/v$n.off" ] || { echo "result=unchanged"; return 0; }
    rm -f "$ENGINE_ETC/v$n.off" || die write_failed
    log "enabled $1"
    echo "result=changed"
}

# The real-time watcher learns the tunnels' programs and interfaces.
sentinel_reload() { [ ! -x /opt/bin/vward-sentinel.sh ] || /opt/bin/vward-sentinel.sh reload </dev/null >/dev/null 2>&1 || :; }

case "${1:-}" in
    install) op_install ;;
    servers) [ "$#" -eq 2 ] || die usage 64; op_servers "$2" ;;
    add) [ "$#" -eq 3 ] || [ "$#" -eq 4 ] || die usage 64; op_add "$2" "$3" "${4:-}"; sentinel_reload ;;
    remove) [ "$#" -eq 2 ] || die usage 64; op_remove "$2"; sentinel_reload ;;
    restart) [ "$#" -eq 2 ] || die usage 64; op_restart "$2" ;;
    disable) [ "$#" -eq 2 ] || die usage 64; op_disable "$2" ;;
    enable) [ "$#" -eq 2 ] || die usage 64; op_enable "$2" ;;
    supervise) op_supervise ;;
    stop) op_stop ;;
    status) op_status ;;
    *) die usage 64 ;;
esac
