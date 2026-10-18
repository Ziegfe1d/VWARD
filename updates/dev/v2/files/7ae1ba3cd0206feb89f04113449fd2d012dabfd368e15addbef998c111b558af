#!/bin/sh
# VWARD VLESS engine: a VLESS or Trojan server (a vless:// or trojan:// link, or one server
# of a subscription)
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
# vward-vless-engine.sh servers FILE | add DESCRIPTION FILE | remove NAME | restart NAME | start NAME |
#                       kick NAME | failover NAME | disable NAME | enable NAME | supervise |
#                       stop | status | install
# FILE: vless:// or trojan:// links, one a line, or the address of a subscription (https://...); a line
# "#server=N" chooses the N-th server (1 by default).
# Output: "result=..." / "info.key=value" lines, or "error=<code>".
PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
# Xray (Go) looks for the list of certificate authorities only in /etc/ssl, which KeeneticOS
# does not have: every TLS server (xHTTP, gRPC, WebSocket, Trojan) failed with «certificate
# signed by unknown authority» (Viva 2026-10-04; REALITY needs no list and worked). The list
# is Entware's ca-bundle, which VWARD's installer puts in.
if [ -z "${SSL_CERT_FILE:-}" ]; then
    for ca in ${VWARD_CA_BUNDLE:-/opt/etc/ssl/certs/ca-certificates.crt /opt/etc/ssl/cert.pem}; do
        [ -s "$ca" ] && { SSL_CERT_FILE=$ca; export SSL_CERT_FILE; break; }
    done
fi

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
# Through HTTP: whether pages pass needs no TLS, and Entware's OpenSSL 3.5.5 crashes on some
# routers («Illegal instruction», a Viva, 2026-10-11): every check through it said «dead».
CHECK_URL=${VWARD_VLESS_CHECK_URL:-http://1.1.1.1/cdn-cgi/trace}

XRAY_VERSION=26.9.9
XRAY_URL=${VWARD_XRAY_URL:-https://github.com/XTLS/Xray-core/releases/download/v$XRAY_VERSION}

# get CURL-ARGUMENTS: a download through vward_fetch of the device profile: when curl crashes on
# HTTPS (Entware's OpenSSL 3.5.5 on some MIPS routers), uclient-fetch with mbedTLS downloads.
get() {
    command -v vward_fetch >/dev/null 2>&1 ||
        { [ ! -r "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}" ] || . "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}"; } 2>/dev/null
    if command -v vward_fetch >/dev/null 2>&1; then VWARD_CURL_BIN=$CURL; vward_fetch "$@"; else "$CURL" "$@"; fi
}

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

die() { [ "$1" != router_rejected ] || [ -z "${NDM_REASON:-}" ] || printf 'reason=%s\n' "$NDM_REASON"; printf 'error=%s\n' "$1"; exit "${2:-1}"; }
# Every line says who asked (VWARD_ACTOR: an agent, the Panel - the owner, or the shell).
log() { mkdir -p "${ENGINE_LOG%/*}" 2>/dev/null; printf '%s|VLESS_ENGINE|%s|by=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" "${VWARD_ACTOR:-shell}" >> "$ENGINE_LOG" 2>/dev/null; }

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
    get -fsSL --connect-timeout 15 --max-time 600 --max-filesize 67108864 \
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

# stubs_drop FILE: the provider's notes dressed as servers left out: a subscription that ran out
# sends «⌛ Subscription expired», «Contact support» at 0.0.0.0 (Viva 2026-10-16), some send such
# notes among the servers. A link to no address (0.0.0.0, 127.0.0.1, ::, none) or named «expired».
stubs_drop() {
    awk '{ s = $0; nm = ""; i = index(s, "#"); if (i) { nm = tolower(substr(s, i + 1)); s = substr(s, 1, i - 1) }
           i = index(s, "@"); hp = i ? substr(s, i + 1) : ""
           if (substr(hp, 1, 1) == "[") h = substr(hp, 2, index(hp, "]") - 2); else { j = index(hp, ":"); h = j ? substr(hp, 1, j - 1) : hp }
           if (h == "" || h == "0.0.0.0" || h == "127.0.0.1" || h == "::" || h == "::1" || nm ~ /expired/) next
           print }' "$1" > "$1.real" && mv -f "$1.real" "$1"
}

# links FILE OUT: the vless:// and trojan:// links of FILE, or of the subscription it names
# (base64 or plain), the provider's notes left out (stubs_drop). 4: the subscription ran out -
# only notes came, or its own «subscription-userinfo» says the date is past.
links() {
    lk_exp= lk_title=
    src=$(tr -d '\r' < "$1" | grep -v '^#' | awk 'NF {sub(/^[ \t]+/, ""); sub(/[ \t]+$/, ""); print; exit}')
    case "$src" in
        vless://*|trojan://*) tr -d '\r' < "$1" | awk '/^(vless|trojan):\/\// {print $1}' > "$2" ;;
        https://*|http://*)
            printf '%s\n' "$src" | grep -Eq '^https?://[A-Za-z0-9._~:/?#@!$&()*+,;=%-]+$' || return 2
            rm -f "$2.hdr"
            get -fsSL --connect-timeout 10 --max-time 30 --max-filesize 1048576 -A "VWARD" \
                -D "$2.hdr" -o "$2.raw" "$src" 2>/dev/null || { rm -f "$2.hdr"; return 3; }
            lk_exp=$(tr -d '\r' < "$2.hdr" 2>/dev/null | awk 'tolower($1) == "subscription-userinfo:" {
                n = split($0, a, ";"); for (i = 1; i <= n; i++) if (a[i] ~ /expire=[0-9]+/) { sub(/.*expire=/, "", a[i]); e = a[i] + 0 } }
                END { if (e) print e }')
            # The subscription's own name («profile-title», plain or «base64:…»): the tunnel's
            # name in Keenetic, not the first server's (owner 2026-10-18).
            lk_title=$(tr -d '\r' < "$2.hdr" 2>/dev/null | awk 'tolower($1) == "profile-title:" {sub(/^[^:]*:[ \t]*/, ""); print; exit}')
            case "$lk_title" in base64:*) lk_title=$(printf '%s' "${lk_title#base64:}" | { base64 -d 2>/dev/null || openssl base64 -d -A 2>/dev/null; }) ;; esac
            lk_title=$(printf '%s' "$lk_title" | tr -d '|"\\\000-\037' | cut -c1-48)
            rm -f "$2.hdr"
            if grep -Eq '(vless|trojan)://' "$2.raw"; then tr -d '\r' < "$2.raw"
            else tr -d '\r\n ' < "$2.raw" | { base64 -d 2>/dev/null || openssl base64 -d -A 2>/dev/null; } | tr -d '\r'; fi |
                awk '/^(vless|trojan):\/\// {print $1}' > "$2"
            rm -f "$2.raw" ;;
        *) return 2 ;;
    esac
    [ -s "$2" ] || return 1
    lk_n=$(grep -c . "$2")
    stubs_drop "$2"
    # Only notes, or the date past: the subscription ran out (a date of 0 is «no end»).
    [ -s "$2" ] || return 4
    case "${lk_exp:-}" in ''|0|*[!0-9]*) ;; *) [ "$lk_exp" -gt "$(date +%s)" ] || return 4 ;; esac
    lk_exp=
    [ "$lk_n" -gt 0 ]
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
            i = index($0, "://"); if (!i) exit 1
            print "proto\t" substr($0, 1, i - 1); s = substr($0, i + 3); frag = ""; q = ""
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
    # VLESS: a UUID, or Xray's short form (up to 30 characters); Trojan: a password without
    # spaces or control characters. Entware's jq has no regex.
    if grep -qx 'proto	trojan' "$3.kv"; then cf_id='[^[:space:][:cntrl:]]{1,128}'
    else cf_id='([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[A-Za-z0-9_-]{1,30})'; fi
    awk -F '\t' '$1 == "id" {print substr($0, 4); exit}' "$3.kv" | grep -Eq "^$cf_id\$" || { rm -f "$3.kv"; return 2; }
    "$JQ" -Rn --arg tun "$2" '
        [inputs | split("\t") | {key: .[0], value: (.[1:] | join("\t"))}] | from_entries as $l |
        def q($k): $l["q." + $k] // "";
        (q("type") | if . == "" then "tcp" elif . == "raw" then "tcp" else . end) as $net |
        ($l.proto == "trojan") as $trojan |
        # A Trojan link without «security» means TLS (its scheme has no plain mode).
        (q("security") | if . == "" then (if $trojan then "tls" else "none" end) else . end) as $sec |
        # xHTTP «extra» (padding obfuscation, xmux, upload method...): the server expects
        # its requests shaped so; without it the connection is cut (Viva 2026-10-04).
        (q("extra") | if . == "" then null else (try fromjson catch null) end) as $extra |
        if (($l.port | tonumber? // 0) | . < 1 or . > 65535) or ($l.host == "") or
           ([$net] | inside(["tcp", "ws", "grpc", "xhttp", "httpupgrade"]) | not) or ([$sec] | inside(["none", "tls", "reality"]) | not)
        then error("unsupported") else . end |
        {log: {loglevel: "warning"},
         inbounds: [{tag: "tun", port: 0, protocol: "tun", settings: {name: $tun, mtu: 1400}}],
         outbounds: [{tag: "vless", protocol: (if $trojan then "trojan" else "vless" end),
           settings: (if $trojan then {servers: [{address: $l.host, port: ($l.port | tonumber), password: $l.id}]}
             else {vnext: [{address: $l.host, port: ($l.port | tonumber),
               users: [{id: $l.id, encryption: (q("encryption") | if . == "" then "none" else . end)} + (if q("flow") != "" then {flow: q("flow")} else {} end)]}]} end),
           streamSettings: ({network: $net, security: $sec}
             + (if $sec == "reality" then {realitySettings: {serverName: q("sni"), fingerprint: (q("fp") | if . == "" then "chrome" else . end),
                   publicKey: q("pbk"), shortId: q("sid"), spiderX: q("spx")}}
                elif $sec == "tls" then {tlsSettings: ({serverName: (q("sni") | if . == "" then $l.host else . end)}
                   + (if q("fp") != "" then {fingerprint: q("fp")} else {} end)
                   + (if q("alpn") != "" then {alpn: (q("alpn") | split(","))} else {} end))}
                else {} end)
             + (if $net == "ws" then {wsSettings: {path: (q("path") | if . == "" then "/" else . end), host: q("host")}}
                elif $net == "grpc" then {grpcSettings: ({serviceName: q("serviceName")}
                   + (if q("mode") == "multi" then {multiMode: true} else {} end)
                   + (if q("authority") != "" then {authority: q("authority")} else {} end))}
                elif $net == "xhttp" then {xhttpSettings: ({path: (q("path") | if . == "" then "/" else . end), host: q("host"), mode: (q("mode") | if . == "" then "auto" else . end)}
                   + (if ($extra | type) == "object" then {extra: $extra} else {} end))}
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
    case "$rc" in 0) ;; 2) die vless_syntax 64 ;; 3) die subscription_unavailable ;; 4) die subscription_expired ;; *) die vless_no_servers 64 ;; esac
    i=0
    while IFS= read -r l; do
        i=$((i + 1))
        [ "$i" -le 50 ] || break
        parse "$l" > "$TMPD/kv" 2>/dev/null || continue
        v() { awk -F '\t' -v k="$1" '$1 == k {print substr($0, length(k) + 2); exit}' "$TMPD/kv" | tr -d '|"\\' | cut -c1-64; }
        printf 'info.server.%s=%s|%s|%s|%s|%s\n' "$i" "$(v name)" "$(v host)" "$(v port)" "$(v q.security)" "$(v q.type)"
    done < "$TMPD/links"
    printf 'info.kind=vless\ninfo.servers=%s\n' "$i"
    [ -z "${lk_title:-}" ] || printf 'info.title=%s\n' "$lk_title"
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
    # ndm COMMAND: one Keenetic command (never a key); on refusal the command and Keenetic's own
    # words go to the log and to the caller (reason=).
    ndm_out=$("$NDMC" -c "$1" 2>&1) || { ndm_refused "$1"; return 1; }
    printf '%s\n' "$ndm_out" | grep -Eqi '(^|[^a-z])(error|failed|invalid|unknown command|not found|no such)' || return 0
    ndm_refused "$1"
    return 1
}
ndm_refused() {
    NDM_REASON="$(printf '%s' "$1" | tr -d '"\\' | cut -c1-120): $(printf '%s' "$ndm_out" | tr -cs 'A-Za-z0-9 ._:,()/[]-' ' ' | cut -c1-160)"
    log "refused: $NDM_REASON"
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

# procs_of SLOT: every running program started with the slot's configuration, whatever the
# pid file says. A stale pid file left an old program holding the adapter while a «restart»
# started a second one beside it (Viva 2026-10-04: the broken Xray lived on for hours).
procs_of() {
    grep -l -F -- "$ENGINE_ETC/v$1.json" "${VWARD_PROC:-/proc}"/[0-9]*/cmdline 2>/dev/null | while IFS= read -r f; do
        d=${f%/cmdline}
        [ "$(cat "$d/comm" 2>/dev/null)" = "${VWARD_ENGINE_COMM:-xray}" ] && echo "${d##*/}"
    done
}

# pid_of SLOT: the tunnel's program while it runs (a zombie left by a kill is not running);
# found by its configuration when the pid file is stale.
pid_of() {
    p=$(cat "$ENGINE_RUN/v$1.pid" 2>/dev/null)
    case "$p" in ''|*[!0-9]*) p= ;; esac
    if [ -n "$p" ]; then
        s=$(cat "${VWARD_PROC:-/proc}/$p/stat" 2>/dev/null) || p=
        s=${s##*) }
        case "$s" in Z*|X*) p= ;; esac
    fi
    [ -n "$p" ] || p=$(procs_of "$1" | head -n 1)
    [ -n "$p" ] || return 1
    echo "$p" > "$ENGINE_RUN/v$1.pid" 2>/dev/null
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
    st_now=$(date +%s)
    echo "$st_now" > "$ENGINE_RUN/v$1.started"
    mkdir -p "$STARTS_DIR" 2>/dev/null
    { [ ! -r "$STARTS_DIR/v$1" ] || tail -n 20 "$STARTS_DIR/v$1"; echo "$st_now"; } > "$STARTS_DIR/v$1.new" 2>/dev/null &&
        mv -f "$STARTS_DIR/v$1.new" "$STARTS_DIR/v$1"
}

# The starts VWARD made, in RAM: a reboot starts every tunnel afresh.
STARTS_DIR=${VWARD_ENGINE_STARTS_DIR:-/tmp/vward-engine-starts}

# restart_due SLOT NAME: the program may be started again by VWARD itself now. A tunnel whose
# program kept stopping, or whose server stayed silent, was started again every minute, 185
# times a day, each start dropping the channel again (Viva 2026-10-16): after a start the
# pauses grow 1, 2, 4, 8 minutes, and after 6 starts within the hour the tunnel is left as it
# is (one notification) until the hour has passed or the owner restarts it. A start 15 minutes
# back or more: a new trouble, counted afresh.
restart_due() {
    rd_now=$(date +%s) rd_c=0 rd_last=0
    if [ -r "$STARTS_DIR/v$1" ]; then
        rd_c=$(awk -v n="$rd_now" '$1 + 3600 > n' "$STARTS_DIR/v$1" | wc -l)
        rd_last=$(tail -n 1 "$STARTS_DIR/v$1")
    fi
    case "$rd_last" in ''|*[!0-9]*) rd_last=0 ;; esac
    if [ $((rd_now - rd_last)) -ge 900 ]; then
        [ ! -e "$STARTS_DIR/v$1.gaveup" ] || rm -f "$STARTS_DIR/v$1.gaveup"
        return 0
    fi
    if [ "$rd_c" -ge "${VWARD_ENGINE_STARTS_MAX:-6}" ]; then
        [ ! -e "$STARTS_DIR/v$1.gaveup" ] || return 1
        : > "$STARTS_DIR/v$1.gaveup"
        log "$2: started $rd_c times within the hour, not started again until the hour has passed"
        bell warn "«{t}» перезапускался $rd_c раз за час" \
            "Туннель не работает после перезапусков: программа останавливается или сервер не отвечает. VWARD не перезапускает его до конца часа, чтобы не ронять канал снова и снова. Проверьте сервер или подписку; кнопка «Перезапустить» работает и сейчас." \
            "$2"
        return 1
    fi
    [ ! -e "$STARTS_DIR/v$1.gaveup" ] || rm -f "$STARTS_DIR/v$1.gaveup"
    rd_wait=${VWARD_ENGINE_BACKOFF:-60} rd_i=1
    while [ "$rd_i" -lt "$rd_c" ] && [ "$rd_wait" -lt 480 ]; do rd_wait=$((rd_wait * 2)) rd_i=$((rd_i + 1)); done
    [ $((rd_now - rd_last)) -ge "$rd_wait" ]
}

# recent SLOT: the program was (re)started within the cooldown (180 s). The guard, the
# minute check and a restart from the Panel do not restart it again on top of each other
# (Viva 2026-10-04: four restarts in a minute, the tunnel never settled), and a tunnel that
# has just started gets the time to settle before it is judged silent.
recent() {
    rs=$(cat "$ENGINE_RUN/v$1.started" 2>/dev/null)
    case "$rs" in ''|*[!0-9]*) return 1 ;; esac
    [ $(( $(date +%s) - rs )) -lt "${VWARD_ENGINE_COOLDOWN:-180}" ]
}

stop_one() {
    # The pid file's program and any other copy on the same configuration.
    pf=$(cat "$ENGINE_RUN/v$1.pid" 2>/dev/null)
    case "$pf" in ''|*[!0-9]*) pf= ;; esac
    # A pid from the file only when it still is the tunnel's program (pids are reused).
    [ -z "$pf" ] || [ "$(cat "${VWARD_PROC:-/proc}/$pf/comm" 2>/dev/null)" = "${VWARD_ENGINE_COMM:-xray}" ] || pf=
    ps_=$( { [ -z "$pf" ] || echo "$pf"; procs_of "$1"; } | sort -u | tr '\n' ' ')
    [ -z "$ps_" ] || { kill $ps_ 2>/dev/null; sleep 1; kill -9 $ps_ 2>/dev/null; }
    rm -f "$ENGINE_RUN/v$1.pid"
}

# connected NAME: a page opened through the tunnel's adapter (VLESS has no handshake to read).
connected() {
    "$CURL" --http1.1 -4 -s -o /dev/null --noproxy '*' --interface "$(adapter_of "$1")" --connect-timeout 5 --max-time 8 "$CHECK_URL" </dev/null 2>/dev/null
}

step() { { printf 'step=%s\n' "$1" >&3; } 2>/dev/null || :; }

op_add() {
    desc=$1 file=$2 keep=${3:-}
    [ -f "$file" ] && [ ! -L "$file" ] || die vless_syntax 64
    TMPD=$(mktemp -d /tmp/vward-vless.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    links "$file" "$TMPD/links"; rc=$?
    case "$rc" in 0) ;; 2) die vless_syntax 64 ;; 3) die subscription_unavailable ;; 4) die subscription_expired ;; *) die vless_no_servers 64 ;; esac
    link=$(chosen "$file" "$TMPD/links")
    [ -n "$link" ] || die vless_no_servers 64
    idx=$(tr -d '\r' < "$file" | sed -n 's/^#server=\([0-9][0-9]*\)$/\1/p' | head -n 1)
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
    # Where the server came from (the subscription's address or the links) and which one it
    # is: when it stops answering, failover moves the tunnel to another server of it.
    (umask 077; grep -v '^#server=' "$file" > "$ENGINE_ETC/v$n.src" && cp "$TMPD/links" "$ENGINE_ETC/v$n.links" &&
        echo "${idx:-1}" > "$ENGINE_ETC/v$n.idx") 2>/dev/null || rm -f "$ENGINE_ETC/v$n.src"
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
    rm -f "$ENGINE_ETC/v$n.json" "$ENGINE_ETC/v$n.off" "$ENGINE_RUN/v$n.err" "$ENGINE_ETC/v$n.src" "$ENGINE_ETC/v$n.links" \
        "$ENGINE_ETC/v$n.idx" "$ENGINE_ETC/v$n.countries" "$ENGINE_RUN/v$n.fails" "$ENGINE_RUN/v$n.failover.at"
    awk -F'\t' -v p="$1" '$2 != p' "$TUNNELS" > "$TUNNELS.new" && mv -f "$TUNNELS.new" "$TUNNELS"
    log "removed $1"
    echo "result=changed"
}

# stop_orphans: a program whose slot no tunnel has any more (a removal that did not stop
# it, seen on Viva 2026-10-04) holds an adapter and memory for nothing: it is stopped.
stop_orphans() {
    grep -l -F -- "$ENGINE_ETC/v" "${VWARD_PROC:-/proc}"/[0-9]*/cmdline 2>/dev/null | while IFS= read -r f; do
        d=${f%/cmdline}
        [ "$(cat "$d/comm" 2>/dev/null)" = "${VWARD_ENGINE_COMM:-xray}" ] || continue
        c=$(tr '\000' '\n' 2>/dev/null < "$f" | grep -F -- "$ENGINE_ETC/v" | head -n 1)
        k=${c##*/v}; k=${k%.json}
        case "$k" in ''|*[!0-9]*) continue ;; esac
        awk -F '\t' -v n="$k" '$1 == n {f = 1} END {exit !f}' "$TUNNELS" 2>/dev/null && continue
        kill "${d##*/}" 2>/dev/null && log "stopped the program of a removed tunnel (slot $k)"
    done
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
    stop_orphans
    [ -s "$TUNNELS" ] && [ -x "$BIN" ] || { echo "result=unchanged"; return 0; }
    started=0
    while IFS="$(printf '\t')" read -r n name server desc; do
        case "$name" in OpkgTun[0-9]) ;; *) continue ;; esac
        [ ! -e "$ENGINE_ETC/v$n.off" ] || continue
        # A failover at work starts and stops the program itself.
        ! failover_busy "$n" || continue
        if [ -z "$(pid_of "$n")" ]; then
            restart_due "$n" "$name" || continue
            start_one "$n" && started=$((started + 1)) && log "restarted $name"
            continue
        fi
        link_up "$(adapter_of "$name")"
        case $? in
            1) : > "$ENGINE_RUN/v$n.down"; continue ;;
            2) continue ;;
        esac
        if recent "$n"; then rm -f "$ENGINE_RUN/v$n.down" "$ENGINE_RUN/v$n.miss"; continue; fi
        if [ ! -e "$ENGINE_RUN/v$n.down" ]; then
            connected "$name" </dev/null && { rm -f "$ENGINE_RUN/v$n.miss" "$ENGINE_RUN/v$n.fails"; continue; }
            # Not this module's decision (one decision, one agent): VWARD's tunnel for routes
            # under the tunnel guard (it restarts, changes the server, takes the reserve
            # channel), or no internet at the provider (a restart or another server would not
            # help and could leave a working server).
            if guard_owns "$name" || ! wan_alive; then rm -f "$ENGINE_RUN/v$n.miss" "$ENGINE_RUN/v$n.fails"; continue; fi
            # One silent minute may be the server or the line: Xray starts afresh on the second.
            [ -e "$ENGINE_RUN/v$n.miss" ] || { : > "$ENGINE_RUN/v$n.miss"; continue; }
        fi
        rm -f "$ENGINE_RUN/v$n.miss"
        # The subscription ran out: no restart and no other server helps until it is renewed.
        if expired_wait "$n" "$name"; then continue; fi
        # Two restarts in a row did not bring the server back: another server of the same
        # subscription, in the background (it tries them one by one).
        fails=$(cat "$ENGINE_RUN/v$n.fails" 2>/dev/null); case "$fails" in ''|*[!0-9]*) fails=0 ;; esac
        if [ "$fails" -ge 2 ] && [ -s "$ENGINE_ETC/v$n.src" ] && failover_due "$n"; then
            rm -f "$ENGINE_RUN/v$n.fails"
            "${VWARD_VLESS_SELF:-$0}" failover "$name" </dev/null >/dev/null 2>&1 &
            log "$name: no answer after two restarts, looking for another server"
            continue
        fi
        restart_due "$n" "$name" || continue
        echo $((fails + 1)) > "$ENGINE_RUN/v$n.fails"
        stop_one "$n"
        start_one "$n" && started=$((started + 1)) && log "restarted $name on its adapter"
    done < "$TUNNELS"
    [ "$started" = 0 ] && echo "result=unchanged" || echo "result=changed"
}

# profile: the device profile, once a run and only when a tunnel is silent (VWARD's tunnel for
# routes, the provider's device). Without it the module decides as before.
profile() {
    [ -z "${PROFILED:-}" ] || return 0
    PROFILED=1
    pl=${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}
    { [ -r "$pl" ] && . "$pl" && vward_profile_load; } >/dev/null 2>&1 || :
}

# guard_owns NAME: NAME is VWARD's tunnel for routes and the tunnel guard (network agent) is on.
guard_owns() {
    profile
    [ -n "${VWARD_TUNNEL_INTERFACE:-}" ] && [ "$1" = "$VWARD_TUNNEL_INTERFACE" ] || return 1
    go_st=${VWARD_COMPONENT_STATE:-/opt/etc/vward/components}
    [ ! -e "$go_st/vward.off" ] && [ ! -e "$go_st/tunnel-guard.disabled" ] &&
        [ ! -e "${VWARD_ETC:-/opt/etc/vward}/tunnel-guard.disabled" ]
}

# wan_alive: a page opens through the provider's device (unknown device: yes, as before).
wan_alive() {
    profile
    vward_valid_ifname "${VWARD_WAN_DEVICE:-}" 2>/dev/null || return 0
    for wu in "$CHECK_URL" http://1.0.0.1/cdn-cgi/trace; do
        "$CURL" --http1.1 -4 -s -o /dev/null --noproxy '*' --interface "$VWARD_WAN_DEVICE" --connect-timeout 5 --max-time 8 "$wu" </dev/null 2>/dev/null && return 0
    done
    return 1
}

# kick NAME: a restart unless the program has just been (re)started (the guard's own
# attempt when the server stops answering).
op_kick() {
    row=$(row_of "$1")
    [ -n "$row" ] || die unknown_tunnel 64
    n=$(printf '%s' "$row" | cut -f1)
    ! recent "$n" || { echo "result=unchanged"; return 0; }
    ! failover_busy "$n" || { echo "result=unchanged"; return 0; }
    restart_due "$n" "$1" || { echo "result=unchanged"; return 0; }
    ( op_restart "$1" ) 3>&- >/dev/null && { echo "result=changed"; return 0; }
    [ -s "$ENGINE_ETC/v$n.src" ] && failover_due "$n" || die tunnel_no_handshake
    op_failover "$1"
}

# failover_busy SLOT: a failover is moving the tunnel right now (its lock, with a live pid).
failover_busy() {
    fp=$(cat "$ENGINE_RUN/v$1.failover/pid" 2>/dev/null)
    case "$fp" in ''|*[!0-9]*) [ -d "$ENGINE_RUN/v$1.failover" ] && rm -rf "${ENGINE_RUN:?}/v$1.failover"; return 1 ;; esac
    kill -0 "$fp" 2>/dev/null && return 0
    rm -rf "${ENGINE_RUN:?}/v$1.failover"
    return 1
}

# failover_due SLOT: no failover found nothing within the last 30 minutes (every server
# silent: the line, not the server; trying them all again each minute helps nobody).
failover_due() {
    fa=$(cat "$ENGINE_RUN/v$1.failover.at" 2>/dev/null)
    case "$fa" in ''|*[!0-9]*) return 0 ;; esac
    [ $(( $(date +%s) - fa )) -ge "${VWARD_VLESS_FAILOVER_PAUSE:-1800}" ]
}

# failover NAME: the tunnel's server does not answer; the other servers of its subscription
# (read again, or the copy kept when the address does not answer) are tried on the tunnel's
# own adapter, servers of the same country first (the flag at the start of the name), at
# most 8. The first that opens a page stays; none: the old server goes back.
# try_server SLOT NAME I: server I of $TMPD/links on the tunnel; 0 = a page opens through it
# (it stays, the tunnel's row and server number follow), else the tunnel keeps its config file
# as it was before the call only when the caller puts it back.
try_server() {
    ts_l=$(sed -n "${3}p" "$TMPD/links")
    [ -n "$ts_l" ] || return 1
    config "$ts_l" "$(adapter_of "$2")" "$TMPD/c.json" 2>/dev/null || return 1
    "$BIN" run -test -c "$TMPD/c.json" >/dev/null 2>&1 || return 1
    (umask 077; cp "$TMPD/c.json" "$ENGINE_ETC/v$1.json") || return 1
    stop_one "$1"
    start_one "$1" || return 1
    ts_w=0 ts_ok=0
    while [ "$ts_w" -le "${VWARD_VLESS_FAILOVER_WAIT:-16}" ]; do
        connected "$2" && { ts_ok=1; break; }
        sleep 2
        ts_w=$((ts_w + 4))
    done
    [ "$ts_ok" = 1 ] || return 1
    TS_HOST=$(parse "$ts_l" | awk -F '\t' '$1 == "host" {print $2; exit}')
    TS_PORT=$(parse "$ts_l" | awk -F '\t' '$1 == "port" {print $2; exit}')
    echo "$3" > "$ENGINE_ETC/v$1.idx"
    awk -F '\t' -v OFS='\t' -v p="$2" -v s="$TS_HOST:$TS_PORT" '$2 == p {$3 = s} {print}' "$TUNNELS" > "$TUNNELS.new" && mv -f "$TUNNELS.new" "$TUNNELS"
    rm -f "$ENGINE_RUN/v$1.fails" "$ENGINE_RUN/v$1.miss" "$ENGINE_RUN/v$1.failover.at"
    return 0
}

# bell SEV TITLE TEXT NAME: a notification in the Panel's bell (the device profile's vward_note).
bell() {
    command -v vward_note >/dev/null 2>&1 ||
        { [ ! -r "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}" ] || . "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}"; } 2>/dev/null
    ! command -v vward_note >/dev/null 2>&1 || vward_note "$1" "$2" "$3" "t-$4"
}

# sub_state SLOT NAME RC: what the subscription said (RC of links). 4, it ran out: noted once
# ($ENGINE_RUN/vSLOT.expired), the servers kept stay; it answers with servers again: the
# note goes, the owner is told it works again. Other answers (no connection) change nothing.
sub_state() {
    case "$3" in
        4) [ -e "$ENGINE_RUN/v$1.expired" ] && return 0
           mkdir -p "$ENGINE_RUN" && : > "$ENGINE_RUN/v$1.expired"
           log "$2: the subscription ran out (the provider sends notes instead of servers), the servers kept stay"
           bell warn "Подписка VLESS истекла" \
               "Провайдер присылает вместо серверов заглушки («Subscription expired»). VWARD оставил прежний список серверов и не перезапускает туннель «{t}» впустую; продлите подписку у провайдера. VWARD проверяет её раз в 30 минут и вернёт туннель сам." "$2" ;;
        0) [ -e "$ENGINE_RUN/v$1.expired" ] || return 0
           rm -f "$ENGINE_RUN/v$1.expired" "$ENGINE_RUN/v$1.failover.at"
           log "$2: the subscription answers with servers again"
           bell ok "Подписка VLESS снова действует" "Провайдер снова присылает серверы: туннель «{t}» работает как обычно." "$2" ;;
    esac
}

# expired_wait SLOT NAME: the tunnel's subscription ran out: 0 while it still has (looked at again
# every 30 minutes; nothing restarts the tunnel meanwhile, no server helps), 1 when it was renewed.
expired_wait() {
    [ -e "$ENGINE_RUN/v$1.expired" ] || return 1
    [ -n "$(find "$ENGINE_RUN/v$1.expired" -mmin +"${VWARD_VLESS_EXPIRED_EVERY:-30}" 2>/dev/null)" ] || return 0
    ew_t=$(mktemp -d /tmp/vward-vless.XXXXXX 2>/dev/null) || return 0
    links "$ENGINE_ETC/v$1.src" "$ew_t/links"; ew_rc=$?
    case "$ew_rc" in
        0) (umask 077; cp "$ew_t/links" "$ENGINE_ETC/v$1.links"); rm -rf "${ew_t:?}"; sub_state "$1" "$2" 0; return 1 ;;
        *) : > "$ENGINE_RUN/v$1.expired"; rm -rf "${ew_t:?}"; return 0 ;;
    esac
}

# tunnel_links NAME: the tunnel's slot in $n and its subscription's servers in $TMPD/links (read
# again when its address answers, else the copy kept from the last time).
tunnel_links() {
    row=$(row_of "$1")
    [ -n "$row" ] || die unknown_tunnel 64
    n=$(printf '%s' "$row" | cut -f1)
    [ -s "$ENGINE_ETC/v$n.src" ] || [ -s "$ENGINE_ETC/v$n.links" ] || die no_source 64
    TMPD=$(mktemp -d /tmp/vward-vless.XXXXXX 2>/dev/null) || die temporary_file_unavailable
    tl_rc=1
    [ ! -s "$ENGINE_ETC/v$n.src" ] || { links "$ENGINE_ETC/v$n.src" "$TMPD/links"; tl_rc=$?; }
    sub_state "$n" "$1" "$tl_rc"
    if [ "$tl_rc" = 0 ]; then (umask 077; cp "$TMPD/links" "$ENGINE_ETC/v$n.links")
    else cp "$ENGINE_ETC/v$n.links" "$TMPD/links" 2>/dev/null || die subscription_unavailable; stubs_drop "$TMPD/links"; fi
}

# list NAME: the servers of the tunnel's subscription as the VPN apps show them: name (with the
# country flag), address, the time a TCP connection to it takes from the router (empty: it does
# not answer), and which one the tunnel uses now. Never the ids or the subscription's address.
op_list() {
    tunnel_links "$1"
    cur=$(cat "$ENGINE_ETC/v$n.idx" 2>/dev/null); case "$cur" in ''|*[!0-9]*) cur=1 ;; esac
    i=0
    while IFS= read -r l; do
        i=$((i + 1))
        [ "$i" -le 50 ] || break
        parse "$l" > "$TMPD/kv.$i" 2>/dev/null || continue
        h=$(awk -F '\t' '$1 == "host" {print $2; exit}' "$TMPD/kv.$i")
        pt=$(awk -F '\t' '$1 == "port" {print $2; exit}' "$TMPD/kv.$i")
        case "$h:$pt" in *[!A-Za-z0-9.:_-]*|:*|*:) continue ;; esac
        # Ten at a time: a TCP connection each, at most 2 s. A plain HTTP request: Entware's curl
        # has no telnet:// (every server was «not answering», Viva 2026-10-11); the connection
        # time is written also when the server does not speak HTTP (0 = no connection).
        case "$h" in *:*) hp="[$h]" ;; *) hp=$h ;; esac
        # Its exit code says why one did not answer: 6 name not found, 7 refused, 28 no answer in time.
        ( "$CURL" -s -o /dev/null --noproxy '*' --connect-timeout 2 --max-time 2 -w '%{time_connect}' "http://$hp:$pt/" </dev/null > "$TMPD/ms.$i" 2>/dev/null
          echo "$?" > "$TMPD/rc.$i" ) &
        [ $((i % 10)) != 0 ] || wait
    done < "$TMPD/links"
    wait
    j=0
    while [ "$j" -lt "$i" ]; do
        j=$((j + 1))
        [ -s "$TMPD/kv.$j" ] || continue
        v() { awk -F '\t' -v k="$1" '$1 == k {print substr($0, length(k) + 2); exit}' "$TMPD/kv.$j" | tr -d '|"\\' | cut -c1-64; }
        ms=$(awk '{t = $1 * 1000; if (t > 0) printf "%d", t + 0.5}' "$TMPD/ms.$j" 2>/dev/null)
        why=; [ -n "$ms" ] || case "$(cat "$TMPD/rc.$j" 2>/dev/null)" in 6) why=dns ;; 7) why=refused ;; *) why=timeout ;; esac
        printf 'info.server.%s=%s|%s|%s|%s|%s|%s\n' "$j" "$(v name)" "$(v host)" "$(v port)" "$ms" "$([ "$j" = "$cur" ] && echo 1 || echo 0)" "$why"
    done
    co_cross=$(countries_get "$n" cross)
    printf 'info.current=%s\ninfo.servers=%s\ninfo.countries.off=%s\ninfo.countries.cross=%s\n' "$cur" "$i" "$(countries_get "$n" off)" "${co_cross:-1}"
    echo "result=checked"
}

# select NAME I: the tunnel moves to server I of its subscription when a page opens through it;
# otherwise it stays on its server.
op_select() {
    case "$2" in ''|*[!0-9]*) die invalid_value 64 ;; esac
    tunnel_links "$1"
    [ "$2" -ge 1 ] && [ -n "$(sed -n "${2}p" "$TMPD/links")" ] || die invalid_value 64
    cur=$(cat "$ENGINE_ETC/v$n.idx" 2>/dev/null); case "$cur" in ''|*[!0-9]*) cur=1 ;; esac
    failover_busy "$n" && die engine_busy 75
    mkdir -p "$ENGINE_RUN" && mkdir "$ENGINE_RUN/v$n.failover" 2>/dev/null || die engine_busy 75
    echo $$ > "$ENGINE_RUN/v$n.failover/pid"
    trap 'rm -rf "${ENGINE_RUN:?}/v$n.failover"; cleanup' EXIT
    cp "$ENGINE_ETC/v$n.json" "$TMPD/old.json" || die write_failed
    if try_server "$n" "$1" "$2"; then
        log "server $1: server $cur -> server $2 $TS_HOST:$TS_PORT (chosen in the Panel)"
        printf 'info.server=%s\ninfo.host=%s:%s\n' "$2" "$TS_HOST" "$TS_PORT"
        echo "result=changed"
        return 0
    fi
    (umask 077; cp "$TMPD/old.json" "$ENGINE_ETC/v$n.json")
    stop_one "$n"
    start_one "$n"
    log "server $1: server $2 did not answer, server $cur kept"
    die server_unreachable
}

# Countries of a tunnel's servers (fix.28.2): the owner switches countries off and decides whether
# a failover may move to another country. $ENGINE_ETC/vSLOT.countries: «off=DE NL» (two-letter
# codes from the flag at the start of a server's name; «--» for servers without a flag) and
# «cross=0|1» (1 by default: any country that is on).
# cc NAME: the country code of a server's name.
cc() {
    printf '%s' "$1" | LC_ALL=C od -An -tu1 -N8 | awk '{for (i = 1; i <= NF; i++) b[i] = $i}
        END {if (b[1] == 240 && b[2] == 159 && b[3] == 135 && b[4] >= 166 && b[4] <= 191 && b[5] == 240 && b[8] >= 166 && b[8] <= 191)
                 printf "%c%c\n", b[4] - 101, b[8] - 101; else print "--"}'
}
countries_get() { sed -n "s/^$2=//p" "$ENGINE_ETC/v$1.countries" 2>/dev/null | tail -n 1; }

# countries NAME [CODE 0|1 | cross 0|1]: the settings, or one change.
op_countries() {
    row=$(row_of "$1")
    [ -n "$row" ] || die unknown_tunnel 64
    n=$(printf '%s' "$row" | cut -f1)
    if [ -n "${2:-}" ]; then
        case "$3" in 0|1) ;; *) die invalid_value 64 ;; esac
        co_off=$(countries_get "$n" off) co_cross=$(countries_get "$n" cross)
        case "$2" in
            cross) co_cross=$3 ;;
            --|[A-Z][A-Z])
                co_off=$(printf '%s\n' $co_off | grep -vx -- "$2" | tr '\n' ' ')
                [ "$3" = 1 ] || co_off="$co_off $2" ;;
            *) die invalid_value 64 ;;
        esac
        co_off=$(printf '%s\n' $co_off | grep -E '^(--|[A-Z][A-Z])$' | sort -u | tr '\n' ' ' | sed 's/ $//')
        (umask 077; printf 'off=%s\ncross=%s\n' "$co_off" "${co_cross:-1}" > "$ENGINE_ETC/v$n.countries") || die write_failed
        log "countries $1: off=${co_off:-none} cross=${co_cross:-1}"
    fi
    co_cross=$(countries_get "$n" cross)
    printf 'info.countries.off=%s\ninfo.countries.cross=%s\n' "$(countries_get "$n" off)" "${co_cross:-1}"
    echo "result=${2:+changed}${2:-checked}"
}

op_failover() {
    row=$(row_of "$1")
    [ -n "$row" ] || die unknown_tunnel 64
    n=$(printf '%s' "$row" | cut -f1)
    [ -s "$ENGINE_ETC/v$n.src" ] || { echo "info.failover=no_source"; echo "result=unchanged"; return 0; }
    mkdir -p "$ENGINE_RUN" || die write_failed
    failover_busy "$n" && { echo "result=unchanged"; return 0; }
    mkdir "$ENGINE_RUN/v$n.failover" 2>/dev/null || { echo "result=unchanged"; return 0; }
    echo $$ > "$ENGINE_RUN/v$n.failover/pid"
    TMPD=$(mktemp -d /tmp/vward-vless.XXXXXX 2>/dev/null) || { rm -rf "${ENGINE_RUN:?}/v$n.failover"; die temporary_file_unavailable; }
    trap 'rm -rf "${ENGINE_RUN:?}/v$n.failover"; cleanup' EXIT
    links "$ENGINE_ETC/v$n.src" "$TMPD/links"; fo_rc=$?
    sub_state "$n" "$1" "$fo_rc"
    if [ "$fo_rc" = 4 ]; then
        # Every server refuses an expired subscription: none is tried, the tunnel stays as it is.
        date +%s > "$ENGINE_RUN/v$n.failover.at"
        echo "info.failover=expired"
        echo "result=unchanged"
        return 0
    fi
    if [ "$fo_rc" = 0 ]; then (umask 077; cp "$TMPD/links" "$ENGINE_ETC/v$n.links")
    else cp "$ENGINE_ETC/v$n.links" "$TMPD/links" 2>/dev/null || die subscription_unavailable; stubs_drop "$TMPD/links"; fi
    cur=$(cat "$ENGINE_ETC/v$n.idx" 2>/dev/null); case "$cur" in ''|*[!0-9]*) cur=1 ;; esac
    # The flag: two regional indicator symbols, 8 bytes of UTF-8 (F0 9F 87 ..).
    nm() { parse "$1" 2>/dev/null | awk -F '\t' '$1 == "name" {print substr($0, 6); exit}'; }
    flag=$(nm "$(sed -n "${cur}p" "$TMPD/links")" | LC_ALL=C cut -b1-8)
    case "$flag" in "$(printf '\360\237\207')"*) ;; *) flag= ;; esac
    # Countries switched off are never tried; without «cross» only the same country.
    fo_off=" $(countries_get "$n" off) " fo_cross=$(countries_get "$n" cross)
    i=0
    while IFS= read -r l; do
        i=$((i + 1))
        [ "$i" != "$cur" ] || continue
        case "$fo_off" in "  ") ;; *) case "$fo_off" in *" $(cc "$(nm "$l")") "*) continue ;; esac ;; esac
        if [ -n "$flag" ] && [ "$(nm "$l" | LC_ALL=C cut -b1-8)" = "$flag" ]; then echo "$i" >> "$TMPD/same"
        elif [ "${fo_cross:-1}" != 0 ]; then echo "$i" >> "$TMPD/other"; fi
    done < "$TMPD/links"
    cat "$TMPD/same" "$TMPD/other" 2>/dev/null | head -n "${VWARD_VLESS_FAILOVER_MAX:-8}" > "$TMPD/try"
    cp "$ENGINE_ETC/v$n.json" "$TMPD/old.json" || die write_failed
    while IFS= read -r i; do
        try_server "$n" "$1" "$i" || continue
        log "failover $1: server $cur did not answer, now server $i $TS_HOST:$TS_PORT"
        printf 'info.server=%s\ninfo.host=%s:%s\n' "$i" "$TS_HOST" "$TS_PORT"
        echo "result=changed"
        return 0
    done < "$TMPD/try"
    (umask 077; cp "$TMPD/old.json" "$ENGINE_ETC/v$n.json")
    stop_one "$n"
    start_one "$n"
    date +%s > "$ENGINE_RUN/v$n.failover.at"
    log "failover $1: no other server of the subscription answers, server $cur kept"
    echo "info.failover=none"
    echo "result=unchanged"
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

# start NAME: the program (re)started without waiting for the server - the Panel's switch
# (Keenetic switches a tunnel at once; the answer of the server shows in the tunnel's status).
op_start() {
    row=$(row_of "$1")
    [ -n "$row" ] || die unknown_tunnel 64
    n=$(printf '%s' "$row" | cut -f1)
    stop_one "$n"
    start_one "$n" || die engine_start_failed
    log "started $1 by request"
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
        # The current server's own name in the subscription («Norway-14s(ws)»), for the Panel.
        ci=$(cat "$ENGINE_ETC/v$n.idx" 2>/dev/null); case "$ci" in ''|*[!0-9]*) ci=1 ;; esac
        sname=$(sed -n "${ci}p" "$ENGINE_ETC/v$n.links" 2>/dev/null | head -n 1)
        [ -z "$sname" ] || sname=$(parse "$sname" 2>/dev/null | awk -F '\t' '$1 == "name" {print substr($0, 6); exit}' | tr -d '\t|"\\' | cut -c1-64)
        printf 'tunnel=%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$([ -n "$p" ] && echo 1 || echo 0)" "$rss" "$server" "$desc" "$([ -e "$ENGINE_ETC/v$n.off" ] && echo 1 || echo 0)" "$sname"
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
    kick) [ "$#" -eq 2 ] || die usage 64; op_kick "$2" ;;
    start) [ "$#" -eq 2 ] || die usage 64; op_start "$2" ;;
    failover) [ "$#" -eq 2 ] || die usage 64; op_failover "$2" ;;
    list) [ "$#" -eq 2 ] || die usage 64; op_list "$2" ;;
    select) [ "$#" -eq 3 ] || die usage 64; op_select "$2" "$3" ;;
    countries) [ "$#" -eq 2 ] || [ "$#" -eq 4 ] || die usage 64; op_countries "$2" "${3:-}" "${4:-}" ;;
    disable) [ "$#" -eq 2 ] || die usage 64; op_disable "$2"; sentinel_reload ;;
    enable) [ "$#" -eq 2 ] || die usage 64; op_enable "$2"; sentinel_reload ;;
    supervise) op_supervise ;;
    stop) op_stop ;;
    status) op_status ;;
    *) die usage 64 ;;
esac
