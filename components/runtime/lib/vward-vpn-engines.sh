#!/bin/sh
# VWARD VPN engines: Xray (main VLESS engine), AmneziaWG (kept), sing-box (alternative,
# Entware sing-box-go, OFF by default). Defines functions only; loading does nothing.
# Nothing here starts, stops or switches a tunnel or an engine: it reports, classifies,
# renders and plans. A tunnel is served by at most ONE engine; a protocol that the installed
# sing-box build does not provably support stays on its current engine.
#
#   vward_vpn_engine_owner   NAME            xray|awg|singbox|none, or conflict (rc 75)
#   vward_vpn_link_class     FILE            protocol, transport, security of ONE link (no secret printed)
#   vward_singbox_caps                       tags of the installed build (sing-box version), or unknown
#   vward_vpn_engine_compat  ENGINE PROTO TRANSPORT SECURITY CAPS   yes|no + reason
#   vward_singbox_render     LINKFILE OUT TUN   sing-box JSON for one VLESS/Trojan link (0600)
#   vward_singbox_check      CONF            `sing-box check` when installed, else unknown
#   vward_vpn_engine_plan    NAME TARGET FACTS   ordered switch steps or a refusal (never executed)

vve_root() {
    VVE_R=${VWARD_ROOT_PREFIX:-}
    VVE_XRAY=${VWARD_VLESS_ETC:-$VVE_R/opt/etc/vward/vless-engine}
    VVE_AWG=${VWARD_AWG_ETC:-$VVE_R/opt/etc/vward/awg-engine}
    VVE_SB=${VWARD_SINGBOX_ETC:-$VVE_R/opt/etc/vward/singbox-engine}
    VVE_SBBIN=$VVE_R/opt/bin/sing-box
}

vward_vpn_engine_owner() (
    [ "$#" -eq 1 ] || return 2
    case $1 in OpkgTun[0-9]|OpkgTun[0-9][0-9]|Wireguard[0-9]*|Proxy[0-9]*) ;; *) return 2 ;; esac
    vve_root
    found=
    for e in "xray|$VVE_XRAY" "awg|$VVE_AWG" "singbox|$VVE_SB"; do
        f=${e#*|}/tunnels.tsv
        [ -f "$f" ] || continue
        awk -F'\t' -v n="$1" '$2 == n {x = 1} END {exit !x}' "$f" || continue
        found="$found ${e%%|*}"
    done
    # shellcheck disable=SC2086
    set -- $found
    case $# in 0) echo none ;; 1) echo "$1" ;; *) echo "conflict$found" | tr ' ' ','; return 75 ;; esac
)

# Classify one link without printing it (it carries the user's id/key).
vward_vpn_link_class() (
    [ "$#" -eq 1 ] && [ -f "$1" ] && [ ! -L "$1" ] || return 2
    awk '
        function q(k,  i, a, n) { n = split(query, a, "&"); for (i = 1; i <= n; i++) if (index(a[i], k "=") == 1) return tolower(substr(a[i], length(k) + 2)); return "" }
        NF && $0 !~ /^#/ {
            l = $0; sch = tolower(l); sub(/:.*/, "", sch)
            query = l; if (index(query, "?")) query = substr(query, index(query, "?") + 1); else query = ""
            sub(/#.*/, "", query)
            if (sch == "vless" || sch == "trojan") {
                net = q("type"); if (net == "") net = "tcp"
                sec = q("security"); if (sec == "") sec = (sch == "trojan" ? "tls" : "none")
                print sch "\t" net "\t" sec; found = 1; exit
            }
            if (l ~ /^\[Interface\]/) { iface = 1; next }
            if (iface && l ~ /^(Jc|Jmin|Jmax|S1|S2|H1|H2|H3|H4)[ \t]*=/) awg = 1
            if (iface && l ~ /^\[Peer\]/) peer = 1
        }
        END {
            if (found) exit 0
            if (iface && peer) { print (awg ? "amneziawg" : "wireguard") "\tudp\tnone"; exit 0 }
            print "unknown\t-\t-"; exit 3
        }' "$1"
)

# Build tags of the installed sing-box (e.g. with_quic,with_utls,with_wireguard). Read-only:
# `sing-box version` prints and exits; nothing is started. Absent binary -> unknown.
vward_singbox_caps() (
    vve_root
    [ -x "$VVE_SBBIN" ] && [ ! -L "$VVE_SBBIN" ] || { echo unknown; return 0; }
    out=$("$VVE_SBBIN" version 2>/dev/null) || { echo unknown; return 0; }
    v=$(printf '%s\n' "$out" | awk '/^sing-box version / {print $3; exit}')
    t=$(printf '%s\n' "$out" | awk -F': ' '/^Tags: / {print $2; exit}')
    [ -n "$v" ] || { echo unknown; return 0; }
    printf 'version=%s\ttags=%s\n' "$v" "${t:--}"
)

# Proven support only. CAPS is the line from vward_singbox_caps.
vward_vpn_engine_compat() (
    [ "$#" -eq 5 ] || return 2
    e=$1 p=$2 n=$3 s=$4 c=$5
    no() { printf 'no\t%s\n' "$1"; exit 0; }
    case $e in
        xray)
            case $p in vless|trojan) ;; *) no protocol-not-xray ;; esac
            case $n in tcp|ws|grpc|xhttp|httpupgrade) ;; *) no transport-unknown ;; esac
            case $s in none|tls|reality) printf 'yes\tmain-engine\n' ;; *) no security-unknown ;; esac ;;
        awg)
            case $p in amneziawg|wireguard) printf 'yes\tawg-engine\n' ;; *) no protocol-not-awg ;; esac ;;
        singbox)
            [ "$c" != unknown ] || no singbox-capabilities-unknown
            tags=$(printf '%s' "$c" | sed -n 's/.*tags=//p')
            has() { printf ',%s,' "$tags" | grep -q ",$1,"; }
            case $p in
                amneziawg) no amneziawg-not-supported-by-singbox ;;
                wireguard) has with_wireguard && printf 'yes\twireguard-endpoint\n' || no wireguard-tag-missing ;;
                vless|trojan)
                    case $n in
                        xhttp) no xhttp-not-supported-by-singbox ;;
                        tcp|ws|grpc|httpupgrade) ;;
                        *) no transport-unknown ;;
                    esac
                    case $s in
                        reality) has with_utls && printf 'yes\treality-utls\n' || no reality-needs-with_utls ;;
                        tls|none) printf 'yes\tsupported\n' ;;
                        *) no security-unknown ;;
                    esac ;;
                *) no protocol-unknown ;;
            esac ;;
        *) return 2 ;;
    esac
)

# sing-box configuration for one VLESS/Trojan link on an existing Keenetic TUN (OpkgTunN ->
# its kernel device opkgtunN). The link is read from a private file and never printed.
vward_singbox_render() (
    [ "$#" -eq 3 ] || return 2
    [ -f "$1" ] && [ ! -L "$1" ] || return 2
    case $3 in opkgtun[0-9]|opkgtun[0-9][0-9]) ;; *) return 2 ;; esac
    cls=$(vward_vpn_link_class "$1") || return 75
    vve_p=$(printf '%s' "$cls" | cut -f1); vve_n=$(printf '%s' "$cls" | cut -f2)
    case $vve_p in vless|trojan) ;; *) return 75 ;; esac
    [ "$vve_n" != xhttp ] || return 75
    t=$2.tmp.$$
    (umask 077; "${JQ:-jq}" -Rn --arg tun "$3" '
        def dec: gsub("%2F"; "/") | gsub("%3A"; ":") | gsub("%40"; "@") | gsub("%3D"; "=") | gsub("%2C"; ",");
        [inputs | select(length > 0 and (startswith("#") | not))] | .[0] as $l
        | ($l | capture("^(?<sch>[a-zA-Z]+)://(?<id>[^@]+)@(?<host>\\[[^]]+\\]|[^:/?#]+):(?<port>[0-9]+)[^?#]*(\\?(?<q>[^#]*))?")) as $m
        | (($m.q // "") | split("&") | map(select(length > 0) | split("=") | {(.[0]): ((.[1:] | join("=")) | dec)}) | add // {}) as $p
        | ($m.sch | ascii_downcase) as $sch
        | ($p.security // (if $sch == "trojan" then "tls" else "none" end)) as $sec
        | ($p.type // "tcp") as $net
        | {log: {level: "warn"},
           inbounds: [{type: "tun", tag: "tun-in", interface_name: $tun, auto_route: false, strict_route: false, stack: "system"}],
           outbounds: [({type: $sch, tag: "proxy", server: ($m.host | ltrimstr("[") | rtrimstr("]")), server_port: ($m.port | tonumber)}
             + (if $sch == "vless" then {uuid: ($m.id | dec), flow: ($p.flow // "")} else {password: ($m.id | dec)} end)
             + (if $sec == "tls" or $sec == "reality" then {tls: ({enabled: true, server_name: ($p.sni // $p.host // "")}
                 + (if $sec == "reality" then {utls: {enabled: true, fingerprint: ($p.fp // "chrome")},
                      reality: {enabled: true, public_key: ($p.pbk // ""), short_id: ($p.sid // "")}} else {} end))} else {} end)
             + (if $net == "ws" then {transport: {type: "ws", path: ($p.path // "/"), headers: {Host: ($p.host // "")}}}
                elif $net == "grpc" then {transport: {type: "grpc", service_name: ($p.serviceName // "")}}
                elif $net == "httpupgrade" then {transport: {type: "httpupgrade", path: ($p.path // "/"), host: ($p.host // "")}}
                else {} end)),
             {type: "direct", tag: "direct"}],
           route: {final: "proxy", auto_detect_interface: false}}' < "$1" > "$t") || { rm -f "$t"; return 75; }
    mv -f "$t" "$2"
)

vward_singbox_check() (
    [ "$#" -eq 1 ] && [ -f "$1" ] || return 2
    vve_root
    [ -x "$VVE_SBBIN" ] && [ ! -L "$VVE_SBBIN" ] || { echo unknown; return 0; }
    # `check` only parses and validates; it does not start anything.
    if "$VVE_SBBIN" check -c "$1" >/dev/null 2>&1; then echo valid; else echo invalid; return 75; fi
)

# Plan a change of engine for one tunnel. FACTS ("key<TAB>value", each once, from read-only probes):
#   compat (yes|no from vward_vpn_engine_compat), config (valid|invalid|unknown),
#   probe (ok|fail|none: the target engine reached the server on a test path, outside the tunnel),
#   target_installed (yes|no), writer (disabled|enabled)
vward_vpn_engine_plan() (
    [ "$#" -eq 3 ] || return 2
    case $2 in xray|awg|singbox) ;; *) return 2 ;; esac
    [ -f "$3" ] && [ ! -L "$3" ] || return 2
    vve_facts=$3
    f() { awk -F'\t' -v k="$1" '$1 == k {n++; v = $2} END {if (n == 1) print v}' "$vve_facts"; }
    ref() { printf 'refuse\t%s\n' "$1"; exit 75; }
    cur=$(vward_vpn_engine_owner "$1") || ref two-engines-claim-the-tunnel
    [ "$cur" != none ] || ref tunnel-has-no-engine
    [ "$cur" != "$2" ] || { printf 'none\talready-%s\n' "$cur"; exit 0; }
    [ "$(f target_installed)" = yes ] || ref target-engine-not-installed
    [ "$(f compat)" = yes ] || ref protocol-not-supported-by-target
    [ "$(f config)" = valid ] || ref target-config-not-validated
    [ "$(f probe)" = ok ] || ref target-not-proven-working
    echo "1	journal-plan tunnel=$1 engine=$cur->$2 (keys, profiles, subscriptions kept with $cur)"
    echo "2	stop $cur on $1 (tunnels.tsv entry kept as the return path)"
    echo "3	claim $1 for $2 and start it on the same OpkgTun adapter"
    echo "4	verify the tunnel answers (tunnel-guard probe) within the existing health limits"
    echo "5	commit; on failure: stop $2, release $1, start $cur again (its entry was never removed)"
    [ "$(f writer)" = enabled ] && echo "writer	enabled: requires owner approval" || echo "writer	disabled: plan only, nothing executed"
)
