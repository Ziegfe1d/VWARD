#!/bin/sh
# VWARD DNS mode: one selector, three MUTUALLY EXCLUSIVE handlers. Defines functions only.
#
#   agh      AdGuard Home (default, current installations): Keenetic :53 -> AGH :65053
#   dnsmasq  Entware dnsmasq-full instead of AGH:          Keenetic :53 -> dnsmasq :PORT
#   native   neither: Keenetic's own DNS -> configured upstream
#
# Keenetic's dns-proxy stays the front (:53) in every mode, so FQDN routing (ipset + marks)
# keeps seeing every answer. AGH and dnsmasq are never in the active chain together.
# dnsmasq is installed DISABLED and stays off until an explicit, transactional switch; its
# DHCP is never enabled and it never takes :53 or AGH's port. This file only reads, renders
# and plans: no service is started or stopped, no Keenetic command is sent (no DNS writer
# is connected), nothing outside the given output file is written.
#
#   vward_dns_mode_get                         agh|dnsmasq|native|unknown (+ reason)
#   vward_dns_dnsmasq_render  OUT PORT UPSTREAMS SMARTDNS_MAP ADS_BLOCK
#   vward_dns_dnsmasq_validate CONF            static safety checks (+ `dnsmasq --test` if present)
#   vward_dns_mode_plan TARGET FACTS           transactional step list or a refusal
# rc: 0 ok; 2 usage/invalid input; 75 refused (unsafe or unknown).

vwd_root() { VWD_R=${VWARD_ROOT_PREFIX:-}; VWD_ETC=$VWD_R/opt/etc/vward; }

vwd_ip() { printf '%s\n' "$1" | awk -F. 'NF == 4 {for (i = 1; i <= 4; i++) if ($i !~ /^[0-9]+$/ || $i > 255) exit 1; exit 0} {exit 1}'; }
vwd_port() { case $1 in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
vwd_domain() { printf '%s\n' "$1" | grep -Eq '^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$' && [ "${#1}" -le 253 ]; }

vward_dns_mode_get() (
    vwd_root
    f=$VWD_ETC/dns-mode.conf
    if [ ! -e "$f" ] && [ ! -L "$f" ]; then printf 'agh\tdefault\n'; return 0; fi
    [ -f "$f" ] && [ ! -L "$f" ] || { printf 'unknown\tunsafe-file\n'; return 75; }
    m=$(awk -F= '$1 == "mode" {n++; v = $2} END {if (n == 1) print v}' "$f")
    case $m in agh|dnsmasq|native) printf '%s\tconfigured\n' "$m" ;; *) printf 'unknown\tinvalid\n'; return 75 ;; esac
)

# Render a dnsmasq configuration. UPSTREAMS: one "IP" or "IP#PORT" per line (plain DNS; DoH is
# not a dnsmasq feature). SMARTDNS_MAP: "domain<TAB>IP#PORT" of a LOCAL DoH client. ADS_BLOCK:
# one domain per line. Any invalid line refuses the whole render: nothing half-written.
vward_dns_dnsmasq_render() (
    [ "$#" -eq 5 ] || return 2
    vwd_port "$2" || return 2
    case $2 in 53|65053) printf 'refuse\tport-reserved-%s\n' "$2"; return 75 ;; esac
    for f in "$3" "$4" "$5"; do
        [ -f "$f" ] && [ ! -L "$f" ] || return 2
        [ "$(wc -l < "$f")" -le 20000 ] || { printf 'refuse\tinput-too-large\n'; return 75; }
    done
    t=$1.tmp.$$
    (umask 077
    {
        echo '# VWARD-generated dnsmasq configuration. Edit through the VWARD Panel only.'
        echo "port=$2"
        echo 'listen-address=127.0.0.1'
        echo 'bind-interfaces'
        echo 'no-resolv'
        echo 'no-poll'
        echo 'no-hosts'
        echo 'cache-size=1000'
        echo '# DHCP is never served by this dnsmasq: no dhcp-range, no dhcp-host.'
    } > "$t") || return 2
    while IFS= read -r u || [ -n "$u" ]; do
        [ -n "$u" ] || continue
        ip=${u%%#*}; pt=; case $u in *'#'*) pt=${u#*#} ;; esac
        vwd_ip "$ip" && { [ -z "$pt" ] || vwd_port "$pt"; } || { rm -f "$t"; printf 'refuse\tbad-upstream\n'; return 75; }
        echo "server=$u" >> "$t"
    done < "$3"
    grep -q '^server=' "$t" || { rm -f "$t"; printf 'refuse\tno-upstream\n'; return 75; }
    tab=$(printf '\t')
    while IFS="$tab" read -r d a || [ -n "$d" ]; do
        [ -n "$d" ] || continue
        ip=${a%%#*}; pt=; case $a in *'#'*) pt=${a#*#} ;; esac
        { vwd_domain "$d" && vwd_ip "$ip" && { [ -z "$pt" ] || vwd_port "$pt"; }; } ||
            { rm -f "$t"; printf 'refuse\tbad-smartdns-rule\n'; return 75; }
        echo "server=/$d/$a" >> "$t"
    done < "$4"
    while IFS= read -r d || [ -n "$d" ]; do
        [ -n "$d" ] || continue
        vwd_domain "$d" || { rm -f "$t"; printf 'refuse\tbad-ads-domain\n'; return 75; }
        echo "address=/$d/0.0.0.0" >> "$t"
    done < "$5"
    mv -f "$t" "$1" || { rm -f "$t"; return 2; }
    printf 'rendered\t%s\n' "$(grep -c . "$1")"
)

# Static safety of a rendered (or hand-edited) configuration.
vward_dns_dnsmasq_validate() (
    [ "$#" -eq 1 ] || return 2
    vwd_root
    [ -f "$1" ] && [ ! -L "$1" ] || return 2
    r=$(awk -F= '
        /^[ \t]*(#|$)/ {next}
        {k = $1; v = substr($0, length($1) + 2)}
        k == "port" {np++; port = v}
        k ~ /^dhcp-/ || k == "enable-tftp" || k == "interface" || k == "except-interface" {print "dhcp-or-interface-" k; exit}
        k == "listen-address" && v != "127.0.0.1" {print "listen-not-loopback"; exit}
        k == "conf-file" || k == "conf-dir" || k == "addn-hosts" || k == "dhcp-script" {print "external-include-" k; exit}
        k == "server" {s = v; sub(/^\/[^\/]*\//, "", s); split(s, a, "#")
            if (a[1] ~ /^127\./ && (a[2] == "" || a[2] == "53" || a[2] == port)) {print "loop-" s; exit}
            if (a[1] == "192.168.1.1" || a[1] == "0.0.0.0") {print "loop-" s; exit}
            ns++}
        END {if (np != 1) print "port-count"; else if (port == 53 || port == 65053) print "port-reserved"; else if (!ns) print "no-upstream"}' "$1")
    [ -z "$r" ] || { printf 'refuse\t%s\n' "$r" | head -n 1; return 75; }
    # The real parser, when the program is installed. --test only parses: nothing binds or starts.
    if [ -x "$VWD_R/opt/sbin/dnsmasq" ] && [ ! -L "$VWD_R/opt/sbin/dnsmasq" ]; then
        "$VWD_R/opt/sbin/dnsmasq" --test -C "$1" >/dev/null 2>&1 || { printf 'refuse\tdnsmasq-test-failed\n'; return 75; }
    fi
    printf 'valid\n'
)

# Plan a switch. FACTS (from read-only probes by the caller), "key<TAB>value", each once:
#   agh_running dnsmasq_running   yes|no
#   dnsmasq_installed             yes|no      (vward_entware_status)
#   dnsmasq_config                valid|invalid|missing
#   dnsmasq_port                  PORT;  port_free yes|no  (nothing else listens on it)
#   smartdns_rules smartdns_mapped  counts (every Smart DNS domain must keep its route)
#   native_upstream               yes|no      (Keenetic has its own upstream configured)
#   probe_dnsmasq                 ok|fail|none (answers from dnsmasq on its port, before the switch)
#   writer                        disabled|enabled
# Output: one step per line, "STEP<TAB>action", or "refuse<TAB>reason".
vward_dns_mode_plan() (
    [ "$#" -eq 2 ] || return 2
    case $1 in agh|dnsmasq|native) ;; *) return 2 ;; esac
    [ -f "$2" ] && [ ! -L "$2" ] || return 2
    cur=$(vward_dns_mode_get | cut -f1)
    vwd_facts=$2
    f() { awk -F'\t' -v k="$1" '$1 == k {n++; v = $2} END {if (n == 1) print v}' "$vwd_facts"; }
    ref() { printf 'refuse\t%s\n' "$1"; exit 75; }
    [ "$cur" != unknown ] || ref current-mode-unknown
    ar=$(f agh_running); dr=$(f dnsmasq_running)
    case $ar$dr in yesyes) ref both-handlers-running ;; yesno|noyes|nono) ;; *) ref handler-state-unknown ;; esac
    # The recorded mode must match what actually runs, or the starting point is unknown.
    case $cur in
        agh) [ "$ar$dr" = yesno ] || ref mode-disagrees-with-running ;;
        dnsmasq) [ "$ar$dr" = noyes ] || ref mode-disagrees-with-running ;;
        native) [ "$ar$dr" = nono ] || ref mode-disagrees-with-running ;;
    esac
    [ "$1" != "$cur" ] || { printf 'none\talready-%s\n' "$cur"; exit 0; }
    if [ "$1" = dnsmasq ]; then
        [ "$(f dnsmasq_installed)" = yes ] || ref dnsmasq-not-installed
        [ "$(f dnsmasq_config)" = valid ] || ref dnsmasq-config-not-valid
        p=$(f dnsmasq_port); vwd_port "$p" || ref dnsmasq-port-unknown
        case $p in 53|65053) ref dnsmasq-port-reserved ;; esac
        [ "$(f port_free)" = yes ] || ref dnsmasq-port-busy
        [ "$(f smartdns_rules)" = "$(f smartdns_mapped)" ] && [ -n "$(f smartdns_rules)" ] || ref smartdns-not-fully-mapped
    fi
    if [ "$1" = native ]; then [ "$(f native_upstream)" = yes ] || ref native-upstream-missing; fi
    # Order: the new handler is proven BEFORE the chain moves; the chain moves in one replace
    # (old out, then new in: a short gap, never two handlers); the old one stops only after the
    # new chain answers. Rollback is the same in reverse. Every step is journaled before it runs.
    echo "1	journal-plan mode=$cur->$1"
    case $1 in
        dnsmasq)
            echo "2	start dnsmasq on 127.0.0.1:$(f dnsmasq_port) (not in the chain yet)"
            [ "$(f probe_dnsmasq)" = ok ] && echo "3	probe dnsmasq directly: ok (given)" || echo "3	probe dnsmasq directly: REQUIRED before step 4" ;;
        agh) echo "2	start AdGuard Home on :65053 (not in the chain yet), probe it directly" ;;
        native) echo "2	verify Keenetic's own upstream answers" ;;
    esac
    old=; case $cur in agh) old=192.168.1.1:65053 ;; dnsmasq) old=192.168.1.1:$(f dnsmasq_port) ;; esac
    new=; case $1 in agh) new=192.168.1.1:65053 ;; dnsmasq) new=192.168.1.1:$(f dnsmasq_port) ;; esac
    if [ -n "$new" ]; then into="ip name-server $new"; else into=native; fi
    echo "4	replace chain: ${old:+no ip name-server $old; }$into"
    echo "5	verify answers through Keenetic :53 (FQDN routing and Smart DNS domains included)"
    [ "$cur" = native ] || echo "6	stop $cur (stays installed, disabled at boot)"
    echo "7	commit mode=$1; on any failure: reverse steps 6..2 and restore mode=$cur"
    [ "$(f writer)" = enabled ] && echo "writer	enabled: requires owner approval" || echo "writer	disabled: plan only, nothing executed"
)
