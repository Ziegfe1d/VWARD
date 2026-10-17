#!/opt/bin/sh

# Keenetic can start Entware's scripts with a library path of its own: an Entware program
# (curl) then loads the firmware's libraries and crashes in the loader (seen on a router right
# after boot). Entware's programs and the firmware's each find their own libraries without it.
unset LD_LIBRARY_PATH

VWARD_DEVICE_CONFIG=${VWARD_DEVICE_CONFIG:-/opt/etc/vward/device.conf}
VWARD_DEVICE_MAP_CACHE=${VWARD_DEVICE_MAP_CACHE:-/tmp/vward-device-map.tsv}
VWARD_DEVICE_MAP_TTL=${VWARD_DEVICE_MAP_TTL:-300}
VWARD_ADGUARD_CONFIG=${VWARD_ADGUARD_CONFIG:-/opt/etc/AdGuardHome/AdGuardHome.yaml}
VWARD_SYSFS_NET=${VWARD_SYSFS_NET:-/sys/class/net}
VWARD_OWNED_GROUPS=${VWARD_OWNED_GROUPS:-AdaptiveAuto}

vward_profile_error()
{
    echo "VWARD device profile: $*" >&2
    return 1
}

vward_valid_ifname()
{
    case "$1" in ''|*[!A-Za-z0-9_.:-]*) return 1 ;; *) return 0 ;; esac
}

vward_valid_ndm_name()
{
    case "$1" in ''|*[!A-Za-z0-9_./:-]*) return 1 ;; *) return 0 ;; esac
}

vward_valid_ipv4()
{
    # In the shell, without awk: every minute job checks several addresses.
    case "$1" in ''|*[!0-9.]*|.*|*.|*..*) return 1 ;; esac
    vvi_rest=$1 vvi_n=0
    while [ -n "$vvi_rest" ]; do
        vvi_o=${vvi_rest%%.*}
        case "$vvi_rest" in *.*) vvi_rest=${vvi_rest#*.} ;; *) vvi_rest= ;; esac
        vvi_n=$((vvi_n + 1))
        [ "$vvi_n" -le 4 ] && [ "${#vvi_o}" -le 3 ] && [ "$vvi_o" -le 255 ] || return 1
    done
    [ "$vvi_n" -eq 4 ]
}

vward_tool()
{
    command -v "$1" 2>/dev/null && return 0
    [ -x "/opt/bin/$1" ] && printf '%s\n' "/opt/bin/$1"
}

vward_unique()
{
    awk 'NF && !seen[$0]++ {n++; line=$0} END{if(n==1) print line}'
}

vward_is_wireguard_sysfs()
{
    grep -qx 'DEVTYPE=wireguard' "$VWARD_SYSFS_NET/$1/uevent" 2>/dev/null
}

vward_rci_note()
{
    _vrn=${VWARD_RCI_FAIL_LOG:-/tmp/vward-rci-fail.log}
    printf '%s\t%s\n' "$(date +%s)" "$1" >> "$_vrn" 2>/dev/null || return 0
    [ "$(wc -c < "$_vrn" 2>/dev/null || echo 0)" -lt 4096 ] ||
        { tail -n 100 "$_vrn" > "$_vrn.$$" && mv -f "$_vrn.$$" "$_vrn"; } 2>/dev/null || rm -f "$_vrn.$$"
}

# vward_note SEV TITLE [TEXT] [TO]: an event for the bell's history in the Panel (fix.26), written
# by the agent that did it, so it is there even when no Panel was open. SEV: ok, info, warn, err;
# TO: the Panel page it is about («t-NAME»: «{t}» in TITLE becomes the tunnel's name there).
# The same line as the Panel's action=notes writes; the last 200 kept.
vward_note()
{
    _vn_d=${VWARD_CONSOLE_NOTES:-/opt/var/lib/vward/console} _vn_now=$(date +%s)
    (umask 077; mkdir -p "$_vn_d" && printf '%s-%s\t%s\t%s\t\t%s\t%s\t%s\n' "$_vn_now" "$$" "$_vn_now" "$1" "${4:-}" \
        "$(printf '%s' "$2" | tr '\000-\037\177' ' ')" "$(printf '%s' "${3:-}" | tr '\000-\037\177' ' ')" >> "$_vn_d/notes.tsv") 2>/dev/null || return 0
    [ "$(wc -l < "$_vn_d/notes.tsv")" -le 220 ] ||
        { tail -n 200 "$_vn_d/notes.tsv" > "$_vn_d/notes.tsv.$$" && mv -f "$_vn_d/notes.tsv.$$" "$_vn_d/notes.tsv"; } 2>/dev/null || rm -f "$_vn_d/notes.tsv.$$"
    return 0
}

# One answer of Keenetic's RCI (PATH under /rci, seconds): curl, then BusyBox wget.  Plain
# HTTP to the router itself needs no TLS: when Entware's curl cannot start (a broken OpenSSL
# library, seen on a router), VWARD still learns the router's interfaces and configuration.
vward_rci_get()
{
    _vrg_url="${VWARD_RCI_BASE:-http://127.0.0.1:79/rci}/$1" _vrg_t=${2:-5}
    _vrg_curl=${VWARD_CURL_BIN:-$(vward_tool curl)}
    if [ -n "$_vrg_curl" ]; then
        _vrg_out=$("$_vrg_curl" --fail --silent --connect-timeout 2 --max-time "$_vrg_t" "$_vrg_url" 2>/dev/null)
        _vrg_rc=$?
        [ "$_vrg_rc" = 0 ] && [ -n "$_vrg_out" ] && { printf '%s\n' "$_vrg_out"; _vrg_out=; return 0; }
        # curl ran and Keenetic answered no (an error, a timeout): wget would hear the same.
        # Only a curl that cannot start (126 and up: not runnable, killed) is replaced; Entware's
        # BusyBox wget itself crashed 70 times in a router's log when asked every time.
        _vrg_out=
        # No answer in time (28) or no connection (7): noted for «Стабильность» in the Panel
        # (RAM, the last 100). An error answer is an answer.
        case "$_vrg_rc" in 7|28) vward_rci_note "$_vrg_rc" ;; esac
        [ "$_vrg_rc" -ge 126 ] || return 1
    fi
    # A wget that crashed once is not asked again until the router restarts (BusyBox 1.37 of
    # Entware crashes on every request at the same place: 680 crash lines in the router's log in
    # 5 hours, Viva 2026-10-11).
    _vrg_bad=${VWARD_WGET_BROKEN_DIR:-/tmp/vward-wget-broken}
    for _vrg_w in ${VWARD_RCI_WGET:-/opt/bin/busybox:wget /bin/busybox:wget wget}; do
        _vrg_k=$(printf '%s' "$_vrg_w" | tr '/:' '__')
        [ ! -e "$_vrg_bad/$_vrg_k" ] || continue
        case "$_vrg_w" in
            *:wget) [ -x "${_vrg_w%:wget}" ] || continue
                    _vrg_out=$("${_vrg_w%:wget}" wget -q -T "$_vrg_t" -O - "$_vrg_url" 2>/dev/null) ;;
            *) command -v "$_vrg_w" >/dev/null 2>&1 || continue
               _vrg_out=$("$_vrg_w" -q -T "$_vrg_t" -O - "$_vrg_url" 2>/dev/null) ;;
        esac
        _vrg_rc=$?
        [ "$_vrg_rc" = 0 ] && [ -n "$_vrg_out" ] && { printf '%s\n' "$_vrg_out"; _vrg_out=; return 0; }
        [ "$_vrg_rc" -lt 128 ] || { mkdir -p "$_vrg_bad" 2>/dev/null; : > "$_vrg_bad/$_vrg_k" 2>/dev/null; }
    done
    _vrg_out=
    return 1
}

# vward_tls_take: curl may be run on HTTPS now (it did not crash within the hour). Not known to
# work within the hour either: one caller tries first and the others wait for its result (up to
# 20 s), so a broken curl crashes once, not once per agent starting in the same minute (chaos
# run: 3 crashes at once). vward_tls_done RC: the result noted (a crash: broken for an hour; an
# answer: works for an hour), the turn given back. A crash is a signal of curl's own fault (132
# illegal instruction, 134 abort, 135 bus error, 136 arithmetic, 139 memory); a stop from outside
# (137, 143: a time limit) or a closed pipe (141) is none (each marked a working curl broken for
# an hour, Viva 2026-10-17).
vward_tls_take()
{
    _vt_flag=${VWARD_TLS_BROKEN_FLAG:-/tmp/vward-curl-tls.broken}
    _vt_ok=${_vt_flag%.broken}.ok _vt_lock=${_vt_flag%.broken}.probe _vt_mine=0 _vt_w=0
    [ -z "$(find "$_vt_flag" -mmin -60 2>/dev/null)" ] || return 1
    [ -z "$(find "$_vt_ok" -mmin -60 2>/dev/null)" ] || return 0
    [ -z "$(find "$_vt_lock" -maxdepth 0 -mmin +1 2>/dev/null)" ] || rmdir "$_vt_lock" 2>/dev/null
    until mkdir "$_vt_lock" 2>/dev/null; do
        [ -z "$(find "$_vt_flag" -mmin -60 2>/dev/null)" ] || return 1
        [ -z "$(find "$_vt_ok" -mmin -60 2>/dev/null)" ] || return 0
        [ "$_vt_w" -lt 20 ] || return 0
        sleep 1; _vt_w=$((_vt_w + 1))
    done
    _vt_mine=1
    return 0
}

vward_tls_done()
{
    _vt_flag=${VWARD_TLS_BROKEN_FLAG:-/tmp/vward-curl-tls.broken}
    case "$1" in
        132|134|135|136|139) : > "$_vt_flag" 2>/dev/null; rm -f "${_vt_flag%.broken}.ok" ;;
        *) [ "$1" -ge 126 ] 2>/dev/null || : > "${_vt_flag%.broken}.ok" 2>/dev/null ;;
    esac
    [ "${_vt_mine:-0}" = 0 ] || rmdir "${_vt_flag%.broken}.probe" 2>/dev/null
    _vt_mine=0
    return 0
}

# vward_fetch CURL-ARGUMENTS: a download (HTTPS) that does not need Entware's OpenSSL. curl
# first; when curl crashes (126 and up: Entware's OpenSSL 3.5.5 dies on the TLS handshake on
# some MIPS routers, «Illegal instruction», a Viva 2026-10-11), the same request goes through
# uclient-fetch with mbedTLS, and curl is not asked again for an hour. Of curl's options:
# -o, -w (%{http_code}, %{time_total}, %{redirect_url}), -D (left empty), -f, --max-filesize,
# --retry, -m, --connect-timeout, -A, -4, -k; TLS versions, headers, --interface and the
# quiet/redirect options are uclient-fetch's defaults or skipped. --resolve and a request
# body: 2, curl's «not supported» (the caller says it could not check).
vward_fetch()
{
    _vf_curl=${VWARD_CURL_BIN:-$(vward_tool curl)} _vf_rc=127
    _vf_flag=${VWARD_TLS_BROKEN_FLAG:-/tmp/vward-curl-tls.broken}
    if [ -n "$_vf_curl" ] && vward_tls_take; then
        # HTTP/1.1: Entware's curl crashed in libnghttp2 (HTTP/2) on HTTPS, 81 times in two hours
        # (Viva 2026-10-12, «SIGSEGV ... in libnghttp2.so»); small downloads gain nothing from HTTP/2.
        "$_vf_curl" --http1.1 "$@"
        _vf_rc=$?
        vward_tls_done "$_vf_rc"
        [ "$_vf_rc" -ge 126 ] || return "$_vf_rc"
    fi
    # A list of downloads (--config FILE with «url = "..."» and «output = "..."» lines, as the
    # updater's per-file fetch writes it): one by one through the fallback. Without this every
    # per-file update failed while curl crashed on HTTPS («Проверка обновления не прошла», a
    # Viva 2026-10-12: fix.24 could not be installed).
    _vf_cfg= _vf_p=
    for _vf_a in "$@"; do
        case "$_vf_p" in --config|-K) _vf_cfg=$_vf_a ;; esac
        _vf_p=$_vf_a
    done
    [ -z "$_vf_cfg" ] || { vward_fetch_list "$_vf_cfg" "$@"; return; }
    _vf_uc=${VWARD_UCLIENT_BIN:-$(vward_tool uclient-fetch)}
    # Keenetic's Entware has no uclient-fetch: the TLS of VWARD's Xray (Go, works on these
    # processors) carries the request instead.
    [ -n "$_vf_uc" ] || { vward_fetch_xray "$@"; return; }
    _vf_out=- _vf_wo= _vf_hdr= _vf_fail=0 _vf_max= _vf_retry=0 _vf_t= _vf_ct= _vf_ua= _vf_4=0 _vf_k=0 _vf_url=
    while [ "$#" -gt 0 ]; do
        case "$1" in
            -o|--output) _vf_out=$2; shift ;;
            -w|--write-out) _vf_wo=$2; shift ;;
            -D|--dump-header) _vf_hdr=$2; shift ;;
            --max-filesize) _vf_max=$2; shift ;;
            --retry) _vf_retry=$2; shift ;;
            -m|--max-time) _vf_t=$2; shift ;;
            --connect-timeout) _vf_ct=$2; shift ;;
            -A|--user-agent) _vf_ua=$2; shift ;;
            -H|--header|--interface|--proto|--noproxy|--cacert|--retry-delay|--retry-max-time|--max-redirs|-e|--referer) shift ;;
            -f|--fail) _vf_fail=1 ;;
            -4|--ipv4) _vf_4=1 ;;
            -k|--insecure) _vf_k=1 ;;
            --silent|--show-error|--location|--tlsv1.2|--tlsv1.3|--retry-all-errors|--compressed|--globoff) ;;
            -[fsSL4k]*)
                case "$1" in -*[!fsSL4k]*) return 2 ;; esac
                case "$1" in *f*) _vf_fail=1 ;; esac
                case "$1" in *4*) _vf_4=1 ;; esac
                case "$1" in *k*) _vf_k=1 ;; esac ;;
            http://*|https://*) _vf_url=$1 ;;
            *) return 2 ;;
        esac
        shift
    done
    [ -n "$_vf_url" ] || return 3
    case "$_vf_retry" in ''|*[!0-9]*) _vf_retry=0 ;; esac
    set -- -T "${_vf_t:-${_vf_ct:-30}}" -O "$_vf_out"
    [ "$_vf_4" = 0 ] || set -- "$@" -4
    [ -z "$_vf_ua" ] || set -- "$@" -U "$_vf_ua"
    [ "$_vf_k" = 0 ] || set -- "$@" --no-check-certificate
    for _vf_ca in ${VWARD_CA_BUNDLE:-/opt/etc/ssl/certs/ca-certificates.crt /opt/etc/ssl/cert.pem}; do
        [ -r "$_vf_ca" ] && { set -- "$@" --ca-certificate "$_vf_ca"; break; }
    done
    set -- "$@" "$_vf_url"
    _vf_err="${TMPDIR:-/tmp}/vward-fetch.$$.err" _vf_try=0
    while :; do
        # Not quiet: the server's status comes only in its message («HTTP error 404»).
        "$_vf_uc" "$@" 2>"$_vf_err"
        _vf_rc=$?
        _vf_code=$(sed -n 's/^HTTP error \([0-9][0-9][0-9]\).*/\1/p' "$_vf_err" 2>/dev/null | tail -n 1)
        [ "$_vf_rc" != 0 ] || _vf_code=200
        [ -z "$_vf_code" ] || break
        _vf_try=$((_vf_try + 1))
        [ "$_vf_try" -le "$_vf_retry" ] || break
        sleep 2
    done
    rm -f "$_vf_err"
    [ -z "$_vf_hdr" ] || : > "$_vf_hdr"
    _vf_code=${_vf_code:-000}
    if [ "$_vf_code" = 200 ] && [ -n "$_vf_max" ] && [ "$_vf_out" != - ] && [ "$(wc -c < "$_vf_out")" -gt "$_vf_max" ]; then
        rm -f "$_vf_out"; return 63
    fi
    [ -z "$_vf_wo" ] || printf '%b' "$(printf '%s' "$_vf_wo" | sed "s/%{http_code}/$_vf_code/g; s/%{time_total}/0/g; s/%{[a-z_]*}//g")"
    case "$_vf_code" in
        000) [ "$_vf_rc" = 5 ] && return 60; return 7 ;;
        2??) return 0 ;;
    esac
    [ "$_vf_fail" = 0 ] || return 22
    return 0
}

# vward_fetch_list CONFIG CURL-ARGUMENTS: each «url»/«output» pair of a curl config file as a
# request of its own (the other arguments kept, --config dropped); the first failure is the
# answer. curl is not asked again: it crashed (noted) or is missing.
vward_fetch_list()
{
    _vl_cfg=$1; shift
    [ -r "$_vl_cfg" ] || return 26
    _vl_n=$# _vl_skip=0
    while [ "$_vl_n" -gt 0 ]; do
        _vl_a=$1; shift; _vl_n=$((_vl_n - 1))
        if [ "$_vl_skip" = 1 ]; then _vl_skip=0; continue; fi
        case "$_vl_a" in --config|-K) _vl_skip=1; continue ;; esac
        set -- "$@" "$_vl_a"
    done
    _vl_url=
    while IFS= read -r _vl_line <&9 || [ -n "$_vl_line" ]; do
        _vl_key=$(printf '%s' "$_vl_line" | sed -n 's/^[[:space:]]*\([a-z-]*\)[[:space:]]*[=:][[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\1/p')
        _vl_val=$(printf '%s' "$_vl_line" | sed -n 's/^[[:space:]]*\([a-z-]*\)[[:space:]]*[=:][[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\2/p')
        case "$_vl_key" in
            url) [ -z "$_vl_url" ] || { vward_fetch "$@" "$_vl_url" || return $?; }
                 _vl_url=$_vl_val ;;
            output) [ -n "$_vl_url" ] || continue
                    vward_fetch "$@" -o "$_vl_val" "$_vl_url" || return $?
                    _vl_url= ;;
        esac
    done 9< "$_vl_cfg"
    [ -z "$_vl_url" ] || vward_fetch "$@" "$_vl_url"
}

# vward_fetch_xray CURL-ARGUMENTS: the same curl request in plain HTTP to a short-lived Xray of
# the VLESS module on 127.0.0.1, which speaks TLS to the server and checks its certificate
# (Entware's list of authorities). Every curl option keeps working; --interface and --resolve
# go to Xray (the provider's interface, the server's address). With --location a redirect is
# followed here, a new Xray for each server (curl itself would crash on the https:// address):
# GitHub sends every release file on to another server. Up to --max-redirs (5); only to
# https:// or a path on the same server; --resolve is for the first server only.
vward_fetch_xray()
{
    _vx_bin=${VWARD_XRAY_BIN:-/opt/share/vward/vless-engine/xray}
    [ -x "$_vx_bin" ] && [ -n "$_vf_curl" ] || return "$_vf_rc"
    _vx_url= _vx_if= _vx_res= _vx_prev= _vx_follow=0 _vx_max=5 _vx_dh=
    for _vx_a in "$@"; do
        case "$_vx_prev" in
            --interface) _vx_if=$_vx_a ;;
            --resolve) _vx_res=$_vx_a ;;
            --max-redirs) _vx_max=$_vx_a ;;
            -D|--dump-header) _vx_dh=$_vx_a ;;
        esac
        case "$_vx_a" in
            https://*) _vx_url=$_vx_a ;;
            --location) _vx_follow=1 ;;
            -[!-]*L*) _vx_follow=1 ;;
        esac
        _vx_prev=$_vx_a
    done
    [ -n "$_vx_url" ] || return 3
    case "$_vx_max" in ''|*[!0-9]*) _vx_max=5 ;; esac
    [ -z "$_vx_if" ] || vward_valid_ifname "$_vx_if" || return 2
    # The same arguments without the address (it goes last, one per server) and without what
    # Xray does (--interface/--resolve/--proto); following, also without -L and -D (read here).
    _vx_n=$# _vx_skip=0
    while [ "$_vx_n" -gt 0 ]; do
        _vx_a=$1; shift; _vx_n=$((_vx_n - 1))
        if [ "$_vx_skip" = 1 ]; then _vx_skip=0; continue; fi
        case "$_vx_a" in
            --interface|--resolve|--proto) _vx_skip=1; continue ;;
            "$_vx_url") continue ;;
        esac
        if [ "$_vx_follow" = 1 ]; then
            case "$_vx_a" in
                -D|--dump-header) _vx_skip=1; continue ;;
                --location) continue ;;
                -[!-]*L*) _vx_a=$(printf '%s' "$_vx_a" | tr -d L); [ "$_vx_a" != - ] || continue ;;
            esac
        fi
        set -- "$@" "$_vx_a"
    done
    _vx_tmp="${TMPDIR:-/tmp}/vward-fetch.$$" _vx_hop=0 _vx_rc=7
    while :; do
        _vx_rest=${_vx_url#https://}
        _vx_host=${_vx_rest%%/*} _vx_path=/
        case "$_vx_rest" in */*) _vx_path=/${_vx_rest#*/} ;; esac
        _vx_port=443
        case "$_vx_host" in *:*) _vx_port=${_vx_host##*:} _vx_host=${_vx_host%:*} ;; esac
        case "$_vx_host" in ''|*[!A-Za-z0-9.-]*) return 3 ;; esac
        case "$_vx_port" in ''|*[!0-9]*) return 3 ;; esac
        # --resolve HOST:PORT:ADDRESS: Xray connects to that address, the name stays the TLS name.
        _vx_addr=$_vx_host
        if [ "$_vx_hop" = 0 ]; then
            case "$_vx_res" in "$_vx_host:$_vx_port:"*) _vx_addr=${_vx_res##*:}; vward_valid_ipv4 "$_vx_addr" || return 2 ;; esac
        fi
        # A port of its own for each server: the previous Xray may still hold its port.
        _vx_lp=$(( 20000 + ($$ + _vx_hop) % 20000 ))
        _vx_conf="$_vx_tmp.json" _vx_so=
        [ -z "$_vx_if" ] || _vx_so=",\"sockopt\":{\"interface\":\"$_vx_if\"}"
        (umask 077; printf '{"log":{"loglevel":"none"},"inbounds":[{"listen":"127.0.0.1","port":%s,"protocol":"dokodemo-door","settings":{"address":"%s","port":%s,"network":"tcp"}}],"outbounds":[{"protocol":"freedom","streamSettings":{"security":"tls","tlsSettings":{"serverName":"%s","alpn":["http/1.1"]}%s}}]}\n' \
            "$_vx_lp" "$_vx_addr" "$_vx_port" "$_vx_host" "$_vx_so" > "$_vx_conf") || return "$_vf_rc"
        _vx_ca=
        for _vx_c in ${VWARD_CA_BUNDLE:-/opt/etc/ssl/certs/ca-certificates.crt /opt/etc/ssl/cert.pem}; do
            [ -r "$_vx_c" ] && { _vx_ca=$_vx_c; break; }
        done
        SSL_CERT_FILE=$_vx_ca "$_vx_bin" run -c "$_vx_conf" </dev/null >/dev/null 2>&1 &
        _vx_pid=$!
        # Listening within 5 s (the port in /proc/net/tcp, state 0A).
        _vx_hex=$(printf '%04X' "$_vx_lp") _vx_w=0
        until grep -q "^ *[0-9]*: 0100007F:$_vx_hex 00000000:0000 0A" /proc/net/tcp 2>/dev/null; do
            _vx_w=$((_vx_w + 1))
            [ "$_vx_w" -le 25 ] && kill -0 "$_vx_pid" 2>/dev/null || { kill "$_vx_pid" 2>/dev/null; rm -f "$_vx_conf" "$_vx_tmp.h" "$_vx_tmp.o"; return 7; }
            sleep 0.2 2>/dev/null || sleep 1
        done
        _vx_h=$_vx_host; [ "$_vx_port" = 443 ] || _vx_h=$_vx_host:$_vx_port
        _vx_local="http://127.0.0.1:$_vx_lp$_vx_path"
        if [ "$_vx_follow" = 0 ]; then
            "$_vf_curl" --noproxy '*' -H "Host: $_vx_h" "$@" "$_vx_local"
            _vx_rc=$?
            kill "$_vx_pid" 2>/dev/null
            rm -f "$_vx_conf"
            return "$_vx_rc"
        fi
        # Following: what curl prints waits until it is known whether this answer is the last.
        (umask 077; : > "$_vx_tmp.h"; : > "$_vx_tmp.o")
        "$_vf_curl" --noproxy '*' -H "Host: $_vx_h" -D "$_vx_tmp.h" "$@" "$_vx_local" > "$_vx_tmp.o"
        _vx_rc=$?
        kill "$_vx_pid" 2>/dev/null
        rm -f "$_vx_conf"
        _vx_next=
        if [ "$_vx_rc" = 0 ] && [ "$_vx_hop" -lt "$_vx_max" ]; then
            _vx_code=$(awk 'NR == 1 {print $2; exit}' "$_vx_tmp.h")
            _vx_loc=$(tr -d '\r' < "$_vx_tmp.h" | sed -n 's/^[Ll][Oo][Cc][Aa][Tt][Ii][Oo][Nn]:[[:space:]]*//p' | tail -n 1)
            case "$_vx_code" in
                301|302|303|307|308)
                    case "$_vx_loc" in
                        https://*) _vx_next=$_vx_loc ;;
                        //*|*://*|'') ;;
                        /*) _vx_next="https://$_vx_h$_vx_loc" ;;
                        *) _vx_next="https://$_vx_h${_vx_path%/*}/$_vx_loc" ;;
                    esac ;;
            esac
        fi
        if [ -z "$_vx_next" ]; then
            case "$_vx_dh" in '') ;; -) cat "$_vx_tmp.h" ;; *) cat "$_vx_tmp.h" > "$_vx_dh" ;; esac
            cat "$_vx_tmp.o"
            rm -f "$_vx_tmp.h" "$_vx_tmp.o"
            return "$_vx_rc"
        fi
        _vx_url=$_vx_next _vx_hop=$((_vx_hop + 1))
    done
}

# vward_https_broken: curl crashed on HTTPS within the hour (vward_fetch noted it). Site checks
# through curl say nothing then: «could not check», never «blocked».
vward_https_broken()
{
    [ -n "$(find "${VWARD_TLS_BROKEN_FLAG:-/tmp/vward-curl-tls.broken}" -mmin -60 2>/dev/null)" ]
}

# Keenetic's running configuration, one line per line.  RCI first: unlike ndmc
# it leaves no session lines in the router's log (checked on a real router).
# ndmc when RCI does not answer.  Nothing is printed until the whole reply parsed.
vward_running_config()
{
    _vrc_jq=${VWARD_JQ_BIN:-$(vward_tool jq)}
    _vrc_t0=$(date +%s)
    if [ -n "$_vrc_jq" ] &&
       _vrc_cfg=$(vward_rci_get show/running-config 30 |
           "$_vrc_jq" -er '.message | if type == "array" and length > 0 then .[] else error("empty") end' 2>/dev/null) &&
       [ -n "$_vrc_cfg" ]; then
        vward_keenetic_timed running-config "$_vrc_t0"
        printf '%s\n' "$_vrc_cfg"
        _vrc_cfg=
        return 0
    fi
    _vrc_cfg=
    command -v ndmc >/dev/null 2>&1 || { vward_keenetic_timed running-config "$_vrc_t0" failed; return 1; }
    ndmc -c 'show running-config' 2>/dev/null
    _vrc_rc=$?
    vward_keenetic_timed running-config "$_vrc_t0" "$([ "$_vrc_rc" = 0 ] || echo failed)"
    return "$_vrc_rc"
}

# «Роутер отвечает медленно» (fix.28.2): every VWARD agent read Keenetic's whole configuration
# for itself, several times a minute, and each read waits for Keenetic's busy configuration
# service. Now the agents that only look share one read: the first asks Keenetic, the others
# take its answer for VWARD_KEENETIC_AGE seconds (they wait for a read under way instead of
# asking again). Whoever changes Keenetic's configuration drops the copy (vward_keenetic_dirty);
# programs that change it read it fresh (vward_running_config). Kept in RAM.
# A stand-in ndmc (VWARD_NDMC, the tests) shares no copy unless its own place is given.
_VWARD_KCACHE_OWN=${VWARD_KCACHE:+1}
VWARD_KCACHE=${VWARD_KCACHE:-${VWARD_ROOT_PREFIX:-}/tmp/vward-keenetic}
VWARD_KEENETIC_SLOW_LOG=${VWARD_KEENETIC_SLOW_LOG:-${VWARD_ROOT_PREFIX:-}/opt/var/log/vward/keenetic-slow.log}

# vward_keenetic_timed WHAT T0 [failed]: an answer of Keenetic that took 3 s or more goes into the
# journal «who waited»: time, the program, what it asked, seconds (the last 300 kept).
vward_keenetic_timed()
{
    _vkt_s=$(( $(date +%s) - $2 ))
    [ "$_vkt_s" -ge "${VWARD_KEENETIC_SLOW:-3}" ] || [ -n "${3:-}" ] || return 0
    mkdir -p "${VWARD_KEENETIC_SLOW_LOG%/*}" 2>/dev/null
    printf '%s|%s|%s|%s|%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${VWARD_ACTOR:-${0##*/}}" "$1" "$_vkt_s" "${3:-ok}" >> "$VWARD_KEENETIC_SLOW_LOG" 2>/dev/null || return 0
    [ "$(wc -l < "$VWARD_KEENETIC_SLOW_LOG")" -le 360 ] ||
        { tail -n 300 "$VWARD_KEENETIC_SLOW_LOG" > "$VWARD_KEENETIC_SLOW_LOG.$$" && mv -f "$VWARD_KEENETIC_SLOW_LOG.$$" "$VWARD_KEENETIC_SLOW_LOG"; } 2>/dev/null
    return 0
}

vward_keenetic_dirty() { rm -f "$VWARD_KCACHE/running-config" 2>/dev/null; return 0; }

# _vward_kc_fresh AGE: the shared copy is younger than AGE seconds.
_vward_kc_fresh()
{
    [ -s "$VWARD_KCACHE/running-config" ] || return 1
    _vkf_m=$(date -r "$VWARD_KCACHE/running-config" +%s 2>/dev/null) || return 1
    _vkf_d=$(( $(date +%s) - _vkf_m ))
    [ "$_vkf_d" -ge 0 ] && [ "$_vkf_d" -lt "$1" ]
}

# vward_keenetic_config [AGE]: Keenetic's running configuration (ndmc text, no CR), shared.
vward_keenetic_config()
{
    _vkc_age=${1:-${VWARD_KEENETIC_AGE:-20}}
    if [ -n "${VWARD_NDMC:-}" ] && [ -z "$_VWARD_KCACHE_OWN" ]; then
        "$VWARD_NDMC" -c 'show running-config' 2>/dev/null | tr -d '\r'
        return
    fi
    _vward_kc_fresh "$_vkc_age" && { cat "$VWARD_KCACHE/running-config"; return 0; }
    mkdir -p "$VWARD_KCACHE" 2>/dev/null || return 1
    _vkc_own=0 _vkc_w=0
    while :; do
        mkdir "$VWARD_KCACHE/lock" 2>/dev/null && { _vkc_own=1; break; }
        # A read under way: its answer, at most 35 s later; a lock older than a minute is left over.
        [ -n "$(find "$VWARD_KCACHE/lock" -maxdepth 0 -mmin -1 2>/dev/null)" ] || { rmdir "$VWARD_KCACHE/lock" 2>/dev/null; continue; }
        [ "$_vkc_w" -lt 35 ] || break
        sleep 1; _vkc_w=$((_vkc_w + 1))
        _vward_kc_fresh "$_vkc_age" && { cat "$VWARD_KCACHE/running-config"; return 0; }
    done
    # The reader before us may have just finished: its answer then.
    if [ "$_vkc_own" = 1 ] && _vward_kc_fresh "$_vkc_age"; then
        rmdir "$VWARD_KCACHE/lock" 2>/dev/null
        cat "$VWARD_KCACHE/running-config"
        return 0
    fi
    _vkc_t0=$(date +%s)
    "${VWARD_NDMC:-ndmc}" -c 'show running-config' 2>/dev/null | tr -d '\r' > "$VWARD_KCACHE/running-config.$$"
    if [ -s "$VWARD_KCACHE/running-config.$$" ]; then
        vward_keenetic_timed running-config "$_vkc_t0"
        mv -f "$VWARD_KCACHE/running-config.$$" "$VWARD_KCACHE/running-config"
        [ "$_vkc_own" = 0 ] || rmdir "$VWARD_KCACHE/lock" 2>/dev/null
        cat "$VWARD_KCACHE/running-config"
        return 0
    fi
    vward_keenetic_timed running-config "$_vkc_t0" failed
    rm -f "$VWARD_KCACHE/running-config.$$"
    [ "$_vkc_own" = 0 ] || rmdir "$VWARD_KCACHE/lock" 2>/dev/null
    return 1
}

# State of one Keenetic interface as four lines: state, link, online (yes/no),
# seconds since the last handshake (empty when unknown).  RCI first, ndmc
# only when RCI does not answer, as in vward_running_config.
# vward_interface_state NAME: four lines - on/off in Keenetic, link, peer online, handshake age.
# On/off is Keenetic's own switch (the «conf» layer, `down` in the settings), not `state`: an
# OpkgTun's `state` is the adapter its program keeps up, «up» even while Keenetic has the
# tunnel switched off and routes nothing into it (VLESS, a Viva 2026-10-12).
vward_interface_state()
{
    vward_valid_ndm_name "$1" || return 1
    _vis_jq=${VWARD_JQ_BIN:-$(vward_tool jq)}
    if [ -n "$_vis_jq" ] &&
       _vis_out=$(vward_rci_get "show/interface?name=$1" 5 |
           "$_vis_jq" -er '
               select(type == "object" and has("state")) |
               ([.. | objects | select(has("online")) | .online][0]) as $on |
               ([.. | objects | select(has("last-handshake")) | .["last-handshake"]][0]) as $hs |
               (if ((.summary.layer.conf // "") | tostring) == "disabled" then "down" else (.state | tostring) end),
               ((.link // "") | tostring),
               (if $on == true or $on == "yes" then "yes" elif $on == null then "" else "no" end),
               (($hs // "") | tostring)' 2>/dev/null) &&
       [ -n "$_vis_out" ]; then
        printf '%s\n' "$_vis_out"
        return 0
    fi
    command -v ndmc >/dev/null 2>&1 || return 1
    ndmc -c "show interface $1" 2>/dev/null | awk '
        /^[[:space:]]*state:/ && s == "" {s = $2}
        /^[[:space:]]*conf:/ && $2 == "disabled" {off = 1}
        /^[[:space:]]*link:/ && l == "" {l = $2}
        /^[[:space:]]*online:/ && o == "" {o = $2}
        /last-handshake:/ && h == "" {h = $2}
        END {if (s == "") exit 1; print (off ? "down" : s); print l; print o; print h}'
}

# Device map records (tab separated), built from Keenetic RCI and running-config:
#   I <ndm-name> <type> <kernel-name> <security-level>
#   R <object-group> <route-target>
#   S <static-route-target>
vward_build_device_map()
{
    _vp_jq=${VWARD_JQ_BIN:-$(vward_tool jq)}
    [ -n "$_vp_jq" ] || return 1

    _vp_ifaces=$(vward_rci_get show/interface 4) || return 1
    _vp_list=$(printf '%s\n' "$_vp_ifaces" | "$_vp_jq" -r '
        to_entries[] | select(.value | type == "object") |
        [.key, (.value.type // "-"), (.value["security-level"] // "-")] | @tsv
    ' 2>/dev/null) || return 1
    [ -n "$_vp_list" ] || return 1

    _vp_tab=$(printf '\t')
    printf '%s\n' "$_vp_list" | head -n 128 |
    while IFS="$_vp_tab" read -r _vp_ndm _vp_type _vp_level
    do
        vward_valid_ndm_name "$_vp_ndm" || continue
        # Switch ports share their parent's kernel name and would make it ambiguous.
        [ "$_vp_type" = Port ] && continue
        vward_valid_ndm_name "$_vp_type" || _vp_type=-
        vward_valid_ndm_name "$_vp_level" || _vp_level=-
        _vp_sys=$(vward_rci_get "show/interface/system-name?name=$_vp_ndm" 3 |
            "$_vp_jq" -r '
                if type == "string" then .
                elif type == "object" then (.["system-name"] // .name // empty)
                else empty end
            ' 2>/dev/null)
        vward_valid_ifname "$_vp_sys" || _vp_sys=-
        printf 'I\t%s\t%s\t%s\t%s\n' "$_vp_ndm" "$_vp_type" "$_vp_sys" "$_vp_level"
    done

    vward_running_config | awk '
        $1=="route" && $2=="object-group" && NF>=4 {print "R\t" $3 "\t" $4}
        # A route to one address has no mask («ip route 192.0.2.1 OpkgTun2 auto»).
        $1=="ip" && $2=="route" && $3 ~ /^[0-9]/ && NF>=4 {print "S\t" ($4 ~ /^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$/ ? $5 : $4)}
    '
}

vward_map_filter()
{
    awk -F '\t' '
        {for (i=1;i<=NF;i++) if ($i !~ /^[A-Za-z0-9_.\/:-]+$/) next}
        $1=="I" && $3=="Port" {next}
        ($1=="I" && NF==5) || ($1=="R" && NF==3) || ($1=="S" && NF==2)
    '
}

vward_device_map()
{
    # Owned by us (a shell test: this runs every minute).
    if [ -f "$VWARD_DEVICE_MAP_CACHE" ] && [ ! -L "$VWARD_DEVICE_MAP_CACHE" ] && [ -O "$VWARD_DEVICE_MAP_CACHE" ]; then
        _vp_now=${VWARD_NOW:-}
        case "$_vp_now" in ''|*[!0-9]*) _vp_now=$(date +%s) ;; esac
        _vp_age=$(( _vp_now - $(date -r "$VWARD_DEVICE_MAP_CACHE" +%s 2>/dev/null || echo 0) ))
        if [ "$_vp_age" -ge 0 ] && [ "$_vp_age" -lt "$VWARD_DEVICE_MAP_TTL" ]; then
            vward_map_filter < "$VWARD_DEVICE_MAP_CACHE"
            return 0
        fi
    fi

    _vp_map=$(vward_build_device_map | vward_map_filter)
    printf '%s\n' "$_vp_map" | grep -q '^I' || return 1
    _vp_tmp="$VWARD_DEVICE_MAP_CACHE.$$"
    if (umask 077; printf '%s\n' "$_vp_map" > "$_vp_tmp") 2>/dev/null; then
        mv -f "$_vp_tmp" "$VWARD_DEVICE_MAP_CACHE" 2>/dev/null || rm -f "$_vp_tmp"
    fi
    printf '%s\n' "$_vp_map"
}

vward_map_ndm_for_kernel()
{
    printf '%s\n' "$1" | awk -F '\t' -v k="$2" '$1=="I" && $4==k {print $2}' | vward_unique
}

vward_map_level()
{
    printf '%s\n' "$1" | awk -F '\t' -v k="$2" '$1=="I" && $4==k {print $5; exit}'
}

vward_map_tunnels()
{
    printf '%s\n' "$1" | awk -F '\t' '$1=="I" && tolower($3)=="wireguard" && $4!="-" {print $2 " " $4}'
}

# Keenetic interface types a route can send traffic through as a VPN: WireGuard
# (AmneziaWG included), OpenVPN, SSTP, PPTP, L2TP, IPsec/IKE, Proxy clients and
# OpkgTun (a TUN adapter an Entware program runs, as VWARD's AmneziaWG engine does).
VWARD_VPN_TYPES=${VWARD_VPN_TYPES:-wireguard openvpn sstp pptp l2tp ike ipsec proxy opkgtun}

# vward_map_vpns MAP [WAN-DEVICE]: every VPN client as "<ndm-name> <kernel-name>".
# The connection to the provider itself (PPTP or L2TP at some ISPs) is not a VPN.
vward_map_vpns()
{
    printf '%s\n' "$1" | awk -F '\t' -v types="$VWARD_VPN_TYPES" -v wan="${2:-}" '
        BEGIN {n = split(types, t, " "); for (i = 1; i <= n; i++) vpn[t[i]] = 1}
        $1=="I" && (tolower($3) in vpn) && $4!="-" && $4!=wan {print $2 " " $4}'
}

vward_is_tunnel_sysfs()
{
    vward_is_wireguard_sysfs "$1" || [ -e "$VWARD_SYSFS_NET/$1/tun_flags" ]
}

# The provider's device: the default route that is not a tunnel (a VPN set as
# the router's default connection must not become the WAN).  With several
# providers the one with the lowest metric, the one the router uses; a tie
# stays ambiguous.
vward_discover_wan_device()
{
    ip -4 route show default 2>/dev/null |
        awk '$1=="default" {d = ""; m = 0
            for (i = 1; i <= NF; i++) {if ($i == "dev") d = $(i+1); if ($i == "metric") m = $(i+1) + 0}
            if (d != "") print m, d}' |
        while read -r _vp_m _vp_d; do
            vward_is_tunnel_sysfs "$_vp_d" || printf '%s %s\n' "$_vp_m" "$_vp_d"
        done |
        awk 'NR == 1 || $1 < min {min = $1} {m[NR] = $1; d[NR] = $2}
            END {for (i = 1; i <= NR; i++) if (m[i] == min) print d[i]}' |
        vward_unique
}

vward_discover_tunnel_device()
{
    for _vp_path in "$VWARD_SYSFS_NET"/*; do
        _vp_dev=${_vp_path##*/}
        vward_is_wireguard_sysfs "$_vp_dev" && printf '%s\n' "$_vp_dev"
    done | vward_unique
}

# Picks the managed VPN tunnel among any number of tunnels without relying
# on interface names: explicit config, the only tunnel, or the only tunnel that
# existing routes point to. Prints "<ndm-name> <kernel-name>".
vward_select_tunnel()
{
    _vp_map=$1
    _vp_cands=$(vward_map_vpns "$_vp_map" "${VWARD_WAN_DEVICE:-}")
    [ -n "$_vp_cands" ] || return 1

    if [ -n "${VWARD_TUNNEL_INTERFACE:-}" ] || [ -n "${VWARD_TUNNEL_DEVICE:-}" ]; then
        printf '%s\n' "$_vp_cands" | awk -v i="${VWARD_TUNNEL_INTERFACE:-}" -v d="${VWARD_TUNNEL_DEVICE:-}" '
            (i=="" || $1==i || $2==i) && (d=="" || $2==d)
        ' | vward_unique
        return 0
    fi

    _vp_one=$(printf '%s\n' "$_vp_cands" | vward_unique)
    [ -z "$_vp_one" ] || { printf '%s\n' "$_vp_one"; return 0; }

    printf '%s\n' "$_vp_map" | awk -F '\t' -v cands="$_vp_cands" '
        BEGIN {
            n=split(cands, rows, "\n")
            for (i=1;i<=n;i++) {split(rows[i], f, " "); owner[f[1]]=rows[i]; owner[f[2]]=rows[i]}
        }
        $1=="R" && ($3 in owner) {print owner[$3]}
        $1=="S" && ($2 in owner) {print owner[$2]}
    ' | vward_unique
}

vward_select_policy_group()
{
    printf '%s\n' "$1" | awk -F '\t' -v n="$2" -v k="$3" -v owned="$VWARD_OWNED_GROUPS" '
        BEGIN {m=split(owned, o, " "); for (i=1;i<=m;i++) skip[o[i]]=1}
        $1=="R" && ($3==n || $3==k) && !($2 in skip) {print $2}
    ' | vward_unique
}

vward_discover_lan_record()
{
    _vp_wan="$1"
    _vp_map="${2:-}"
    _vp_recs=$(ip -o -4 addr show scope global 2>/dev/null |
        awk -v wan="$_vp_wan" '$2!=wan {split($4,a,"/"); print $2, a[1]}' |
        while read -r _vp_dev _vp_addr; do
            vward_is_tunnel_sysfs "$_vp_dev" && continue
            [ -n "$_vp_map" ] && [ "$(vward_map_level "$_vp_map" "$_vp_dev")" = public ] && continue
            vward_map_vpns "$_vp_map" | awk -v k="$_vp_dev" '$2==k {found=1} END{exit !found}' && continue
            printf '%s %s\n' "$_vp_dev" "$_vp_addr"
        done)

    _vp_one=$(printf '%s\n' "$_vp_recs" | vward_unique)
    if [ -z "$_vp_one" ] && [ -n "$_vp_map" ]; then
        _vp_one=$(printf '%s\n' "$_vp_recs" | while read -r _vp_dev _vp_addr; do
            [ -n "$_vp_dev" ] || continue
            [ "$(vward_map_level "$_vp_map" "$_vp_dev")" = private ] && printf '%s %s\n' "$_vp_dev" "$_vp_addr"
        done | vward_unique)
    fi
    printf '%s\n' "$_vp_one" | sed '/^$/d'
}

vward_discover_lan_interface()
{
    VWARD_RCI_BASE=${VWARD_RCI_BASE:-http://127.0.0.1:79/rci}
    _vp_devmap=$(vward_device_map 2>/dev/null) || return 1
    _vp_lan=$(vward_discover_lan_record "$(vward_discover_wan_device)" "$_vp_devmap")
    [ -n "$_vp_lan" ] || return 1
    set -- $_vp_lan
    vward_map_ndm_for_kernel "$_vp_devmap" "$1"
}

# Smart DNS domains kept in AdGuard Home: per-domain upstreams of the form
# [/a.com/b.com/]https://... (or tls://, quic://, sdns://), from upstream_dns
# and from upstream_dns_file; also a local DoH client on this router
# ([/a.com/]127.0.0.1:5453, https-dns-proxy): it encrypts the same way.  Plain
# addresses, port 53 and "#" (the default upstream) are local rules, not Smart
# DNS.  One lower-case domain per line.
vward_agh_smartdns_domains()
{
    [ -r "$VWARD_ADGUARD_CONFIG" ] || return 0
    _vp_uf=$(awk '/^[^ #]/ {dns = ($1 == "dns:")} dns && $1 == "upstream_dns_file:" {print $2; exit}' "$VWARD_ADGUARD_CONFIG" 2>/dev/null | tr -d '"\047')
    {
        awk '
            /^[^ #]/ {dns = ($1 == "dns:"); u = 0; next}
            /^  [a-z_]+:/ {u = dns && ($1 == "upstream_dns:"); next}
            u && $1 == "-" {sub(/^[ \t]*-[ \t]*/, ""); print}
        ' "$VWARD_ADGUARD_CONFIG" 2>/dev/null
        case "$_vp_uf" in /*) [ -r "$_vp_uf" ] && cat "$_vp_uf" 2>/dev/null ;; esac
    } | tr -d '"\047' | awk '
        /^\[\// {
            e = index($0, "/]"); if (e < 3) next
            up = substr($0, e + 2)
            if (up !~ /^(https|tls|quic|sdns|h3):\/\// && (up !~ /^((udp|tcp):\/\/)?(127\.[0-9]+\.[0-9]+\.[0-9]+|\[::1\]):[0-9]+$/ || up ~ /:53$/)) next
            n = split(substr($0, 3, e - 3), a, "/")
            for (i = 1; i <= n; i++) if (a[i] ~ /^[A-Za-z0-9._-]+$/ && index(a[i], ".")) print tolower(a[i])
        }'
}

vward_profile_load()
{
    VWARD_RCI_BASE=${VWARD_RCI_BASE:-http://127.0.0.1:79/rci}
    VWARD_CONSOLE_PORT=${VWARD_CONSOLE_PORT:-8088}

    if [ -r "$VWARD_DEVICE_CONFIG" ]; then
        # Keenetic's BusyBox stat has no -c, so owner and mode come from ls.
        _vp_meta=$(ls -ln "$VWARD_DEVICE_CONFIG" 2>/dev/null | awk '{sub(/[.+]$/, "", $1); print $3, $1}')
        [ -n "$_vp_meta" ] || { vward_profile_error "cannot inspect device.conf"; return 1; }
        # Tests running unprivileged name their own uid; on the router it is root.
        _vp_owner=${VWARD_DEVICE_CONFIG_OWNER_UID:-0}
        case "$_vp_meta" in "$_vp_owner -rw-------"|"$_vp_owner -r--------") ;; *)
            vward_profile_error "device.conf must be root-owned and mode 0600 or 0400"; return 1
            ;;
        esac
        # The file is trusted root-owned configuration, never request input.
        . "$VWARD_DEVICE_CONFIG" || return 1
    fi

    _vp_need_map=0
    [ -n "${VWARD_TUNNEL_DEVICE:-}" ] && [ -n "${VWARD_TUNNEL_INTERFACE:-}" ] || _vp_need_map=1
    [ -n "${VWARD_WAN_INTERFACE:-}" ] || _vp_need_map=1
    [ -n "${VWARD_LAN_INTERFACE:-}" ] || _vp_need_map=1
    [ -n "${VWARD_POLICY_GROUP:-}" ] || _vp_need_map=1
    _vp_devmap=
    [ "$_vp_need_map" = 0 ] || _vp_devmap=$(vward_device_map 2>/dev/null) || _vp_devmap=

    [ -n "${VWARD_WAN_DEVICE:-}" ] || VWARD_WAN_DEVICE=$(vward_discover_wan_device)
    vward_valid_ifname "${VWARD_WAN_DEVICE:-}" ||
        { vward_profile_error "WAN device is missing or ambiguous"; return 1; }

    if [ -z "${VWARD_LAN_ADDRESS:-}" ] || [ -z "${VWARD_LAN_SUBNET:-}" ] || [ -z "${VWARD_LAN_DEVICE:-}" ]; then
        if [ -n "${VWARD_LAN_ADDRESS:-}" ]; then
            _vp_lan=$(ip -o -4 addr show 2>/dev/null |
                awk -v a="$VWARD_LAN_ADDRESS" '{split($4,f,"/"); if (f[1]==a) print $2, f[1]}' | vward_unique)
        else
            _vp_lan=$(vward_discover_lan_record "$VWARD_WAN_DEVICE" "$_vp_devmap")
        fi
        if [ -z "${VWARD_LAN_ADDRESS:-}" ] || [ -z "${VWARD_LAN_SUBNET:-}" ]; then
            [ -n "$_vp_lan" ] || { vward_profile_error "LAN address is missing or ambiguous"; return 1; }
        fi
        if [ -n "$_vp_lan" ]; then
            set -- $_vp_lan
            [ -n "${VWARD_LAN_DEVICE:-}" ] || VWARD_LAN_DEVICE=$1
            [ -n "${VWARD_LAN_ADDRESS:-}" ] || VWARD_LAN_ADDRESS=$2
            if [ -z "${VWARD_LAN_SUBNET:-}" ]; then
                VWARD_LAN_SUBNET=$(ip -4 route show dev "$1" scope link 2>/dev/null |
                    awk '$1 ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\/[0-9]+$/ {print $1; exit}')
            fi
        fi
    fi

    vward_valid_ipv4 "$VWARD_LAN_ADDRESS" || { vward_profile_error "invalid LAN address"; return 1; }
    case "$VWARD_LAN_SUBNET" in */[0-9]|*/[12][0-9]|*/3[0-2]) ;; *) vward_profile_error "invalid LAN subnet"; return 1 ;; esac
    vward_valid_ipv4 "${VWARD_LAN_SUBNET%/*}" || { vward_profile_error "invalid LAN subnet"; return 1; }

    [ -n "${VWARD_DNS_SERVER:-}" ] || VWARD_DNS_SERVER=$VWARD_LAN_ADDRESS
    vward_valid_ipv4 "$VWARD_DNS_SERVER" || { vward_profile_error "invalid DNS server"; return 1; }
    [ -n "${VWARD_PROBE_DNS:-}" ] || VWARD_PROBE_DNS=$VWARD_DNS_SERVER
    vward_valid_ipv4 "$VWARD_PROBE_DNS" || { vward_profile_error "invalid probe DNS server"; return 1; }

    # Where AdGuard Home really listens: its own config (http.address, or the
    # older bind_host/bind_port), unless device.conf says otherwise.
    if [ -z "${VWARD_ADGUARD_PORT:-}" ] && [ -r "$VWARD_ADGUARD_CONFIG" ]; then
        _vp_agh=$(awk '
            /^http:/ {h = 1; next}
            /^[^ ]/ {h = 0}
            h && $1 == "address:" {print $2; exit}
            $1 == "bind_host:" {bh = $2}
            $1 == "bind_port:" {bp = $2}
            END {if (bh != "" && bp != "") print bh ":" bp}' "$VWARD_ADGUARD_CONFIG" 2>/dev/null | head -n 1 | tr -d '"\047')
        case "$_vp_agh" in
            *:*) _vp_agh_host=${_vp_agh%:*}; _vp_agh_port=${_vp_agh##*:}
                 case "$_vp_agh_port" in ''|*[!0-9]*) ;; *) VWARD_ADGUARD_PORT=$_vp_agh_port ;; esac
                 if [ -z "${VWARD_ADGUARD_ADDRESS:-}" ] && [ "$_vp_agh_host" != 0.0.0.0 ] && vward_valid_ipv4 "$_vp_agh_host"; then
                     VWARD_ADGUARD_ADDRESS=$_vp_agh_host
                 fi ;;
        esac
    fi
    [ -n "${VWARD_ADGUARD_ADDRESS:-}" ] || VWARD_ADGUARD_ADDRESS=$VWARD_LAN_ADDRESS
    vward_valid_ipv4 "$VWARD_ADGUARD_ADDRESS" || { vward_profile_error "invalid AdGuard Home address"; return 1; }
    VWARD_ADGUARD_PORT=${VWARD_ADGUARD_PORT:-3000}
    case "$VWARD_ADGUARD_PORT" in ''|*[!0-9]*) vward_profile_error "invalid AdGuard Home port"; return 1 ;; esac
    [ "$VWARD_ADGUARD_PORT" -ge 1 ] && [ "$VWARD_ADGUARD_PORT" -le 65535 ] ||
        { vward_profile_error "AdGuard Home port must be 1..65535"; return 1; }

    if [ -z "${VWARD_TUNNEL_DEVICE:-}" ] || [ -z "${VWARD_TUNNEL_INTERFACE:-}" ]; then
        _vp_tunnel=
        [ -z "$_vp_devmap" ] || _vp_tunnel=$(vward_select_tunnel "$_vp_devmap")
        if [ -n "$_vp_tunnel" ]; then
            set -- $_vp_tunnel
            [ -n "${VWARD_TUNNEL_INTERFACE:-}" ] || VWARD_TUNNEL_INTERFACE=$1
            [ -n "${VWARD_TUNNEL_DEVICE:-}" ] || VWARD_TUNNEL_DEVICE=$2
        elif [ -z "$_vp_devmap" ]; then
            [ -n "${VWARD_TUNNEL_DEVICE:-}" ] || VWARD_TUNNEL_DEVICE=$(vward_discover_tunnel_device)
            [ -n "${VWARD_TUNNEL_INTERFACE:-}" ] || VWARD_TUNNEL_INTERFACE=${VWARD_TUNNEL_DEVICE:-}
        else
            _vp_cands=$(vward_map_vpns "$_vp_devmap" "$VWARD_WAN_DEVICE" | awk '{printf "%s%s(%s)", sep, $1, $2; sep=", "}')
            vward_profile_error "tunnel device is missing or ambiguous; VPN candidates: ${_vp_cands:-none}; set VWARD_TUNNEL_INTERFACE in device.conf"
            return 1
        fi
    fi
    vward_valid_ifname "${VWARD_TUNNEL_DEVICE:-}" ||
        { vward_profile_error "tunnel device is missing or ambiguous"; return 1; }
    vward_valid_ndm_name "$VWARD_TUNNEL_INTERFACE" || { vward_profile_error "invalid tunnel interface"; return 1; }

    if [ -n "$_vp_devmap" ]; then
        [ -n "${VWARD_WAN_INTERFACE:-}" ] ||
            VWARD_WAN_INTERFACE=$(vward_map_ndm_for_kernel "$_vp_devmap" "$VWARD_WAN_DEVICE")
        [ -n "${VWARD_LAN_INTERFACE:-}" ] || [ -z "${VWARD_LAN_DEVICE:-}" ] ||
            VWARD_LAN_INTERFACE=$(vward_map_ndm_for_kernel "$_vp_devmap" "$VWARD_LAN_DEVICE")
        [ -n "${VWARD_POLICY_GROUP:-}" ] ||
            VWARD_POLICY_GROUP=$(vward_select_policy_group "$_vp_devmap" "$VWARD_TUNNEL_INTERFACE" "$VWARD_TUNNEL_DEVICE")
    fi
    [ -z "${VWARD_WAN_INTERFACE:-}" ] || vward_valid_ndm_name "$VWARD_WAN_INTERFACE" ||
        { vward_profile_error "invalid WAN interface"; return 1; }
    [ -z "${VWARD_LAN_DEVICE:-}" ] || vward_valid_ifname "$VWARD_LAN_DEVICE" ||
        { vward_profile_error "invalid LAN device"; return 1; }
    [ -z "${VWARD_LAN_INTERFACE:-}" ] || vward_valid_ndm_name "$VWARD_LAN_INTERFACE" ||
        { vward_profile_error "invalid LAN interface"; return 1; }

    case "$VWARD_CONSOLE_PORT" in ''|*[!0-9]*) vward_profile_error "invalid Panel port"; return 1 ;; esac
    [ "$VWARD_CONSOLE_PORT" -ge 1024 ] && [ "$VWARD_CONSOLE_PORT" -le 65535 ] ||
        { vward_profile_error "Panel port must be 1024..65535"; return 1; }

    case "${VWARD_POLICY_GROUP:-}" in *[!A-Za-z0-9_.:-]*) vward_profile_error "invalid policy group"; return 1 ;; esac

    export VWARD_RCI_BASE VWARD_CONSOLE_PORT VWARD_WAN_DEVICE VWARD_LAN_ADDRESS
    export VWARD_LAN_SUBNET VWARD_DNS_SERVER VWARD_TUNNEL_DEVICE
    export VWARD_PROBE_DNS
    export VWARD_ADGUARD_ADDRESS VWARD_ADGUARD_PORT
    export VWARD_TUNNEL_INTERFACE VWARD_POLICY_GROUP
    export VWARD_WAN_INTERFACE VWARD_LAN_DEVICE VWARD_LAN_INTERFACE
}
