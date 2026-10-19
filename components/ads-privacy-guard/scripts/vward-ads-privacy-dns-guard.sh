#!/bin/sh

# DNS of the whole home network goes through AdGuard Home, with no setting on
# the devices and no certificate:
#   enforce  every DNS query from the LAN (port 53, any server) is answered by
#            AdGuard Home; queries to the router itself are left to the rules
#            already there, so AdGuard Home keeps seeing each device
#   bypass   encrypted DNS around it is closed: DoT/DoQ (853) is refused, the
#            well-known DoH addresses are refused on 443, and AdGuard Home gets
#            HaGeZi's Encrypted DNS list for the DoH names
# Devices in the exclusion list (by MAC) are left alone.  When AdGuard Home's DNS
# port is closed the redirect is taken off, so the home is never left without DNS.
# Keenetic rebuilds its firewall now and then: a netfilter.d hook puts the rules back.
# Fail-open for the owner's own redirect too (FAILOPEN=1, the default): a netfilter.d hook of the
# owner's that sends port 53 of the router into AdGuard Home never asks whether AdGuard Home lives,
# so when it dies every device of the home loses DNS. A redirect into a port nothing answers on is
# taken off (parked in RAM) and put back when AdGuard Home answers again.
# The chain (CHAIN=1, the default): Keenetic hands the queries of the home to AdGuard Home
# through «ip name-server ADDRESS:PORT». AdGuard Home that stops answering (3 minutes in a row,
# each check three tries) or restarts again and again (4 times in 10 minutes) is taken out of the chain - Keenetic goes
# to the provider's DNS and the home keeps its internet - and put back after 3 answers in a row
# (Viva 2026-10-04: AdGuard Home restarted in a loop at night, the home lost DNS, the line was
# removed by hand and stayed out: no ad filtering, no Smart DNS). CHAIN=0: VWARD leaves the
# line alone.
#
#   vward-ads-privacy-dns-guard.sh status
#   vward-ads-privacy-dns-guard.sh set enforce|bypass|chain 0|1
#   vward-ads-privacy-dns-guard.sh set exclude MAC[,MAC...]   ("-" for none)
#   vward-ads-privacy-dns-guard.sh apply|tick                 (tick: the scheduler, every minute)
#   vward-ads-privacy-dns-guard.sh chain-out                  (the real-time watcher: AdGuard Home silent)
#   vward-ads-privacy-dns-guard.sh hook nat|filter            (Keenetic netfilter.d)

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
# Who acts, for the journals of the programs it asks (one decision, one agent).
VWARD_ACTOR=network-agent
export VWARD_ACTOR

# The script's own folder, by the shell (no process: some of these run every minute).
case "$0" in */*) SELF_DIR=${0%/*} ;; *) SELF_DIR=. ;; esac
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "FAIL: common library not found" >&2; exit 1; }
. "$LIB"

CONF="${VWARD_DNS_GUARD_CONF:-$ADS_ETC/dns-guard.conf}"
STATE="${VWARD_DNS_GUARD_STATE:-/tmp/vward-dns-guard.state}"
LOCK="${VWARD_DNS_GUARD_LOCK:-/tmp/vward-dns-guard.lock}"
IPT="${VWARD_IPTABLES:-/opt/sbin/iptables}"
NETSTAT="${VWARD_NETSTAT:-netstat}"
HOOK_DIR="${VWARD_NETFILTER_DIR:-/opt/etc/ndm/netfilter.d}"
HOOK="$HOOK_DIR/060-vward-dns-guard.sh"
SELF_BIN="${VWARD_DNS_GUARD_BIN:-/opt/bin/vward-ads-privacy-dns-guard.sh}"
CONTROL="${VWARD_ADS_CONTROL_BIN:-/opt/bin/vward-ads-privacy-control.sh}"
[ -x "$CONTROL" ] || CONTROL="$SELF_DIR/vward-ads-privacy-control.sh"
RCI_BASE="${VWARD_RCI_BASE:-http://127.0.0.1:79/rci}"
DOH_LIST_URL="https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/doh.txt"
DOH_LIST_NAME="HaGeZi Encrypted DNS Bypass"
# Public resolvers that answer DoH/DoT on these addresses only: refusing 443 there
# closes the apps that speak DoH to a fixed address without a DNS lookup.
DOH_IPS="${VWARD_DOH_IPS:-1.1.1.1 1.0.0.1 1.1.1.2 1.0.0.2 1.1.1.3 1.0.0.3 8.8.8.8 8.8.4.4 9.9.9.9 149.112.112.112 9.9.9.10 149.112.112.10 9.9.9.11 149.112.112.11 94.140.14.14 94.140.15.15 94.140.14.140 94.140.14.141 208.67.222.222 208.67.220.220 77.88.8.8 77.88.8.1 77.88.8.88 77.88.8.2 45.90.28.0 45.90.30.0 185.228.168.9 185.228.169.9 76.76.2.0 76.76.10.0}"

NSLOOKUP="${VWARD_NSLOOKUP:-nslookup}"
PARK="${VWARD_DNS_GUARD_PARK:-/tmp/vward-dns-guard.parked}"
PROBE_FAILS="${VWARD_DNS_GUARD_PROBE_FAILS:-/tmp/vward-dns-guard.probe-fails}"
PROBE_HOST="${VWARD_DNS_GUARD_PROBE_HOST:-example.com}"
NDMC="${VWARD_NDMC:-ndmc}"
PIDOF="${VWARD_PIDOF:-pidof}"
CHAIN_DIR="${VWARD_DNS_CHAIN_STATE:-/tmp/vward-dns-chain}"
# List domains the route engine bound to AdGuard Home in Keenetic (agh_bind there).
AGH_BIND="${VWARD_AGH_BINDINGS:-/opt/var/lib/vward/agh-bindings.txt}"

OP="${1:-status}"

ENFORCE=0 BYPASS=0 EXCLUDE="" FAILOPEN=1 CHAIN=1
conf_load()
{
    [ -r "$CONF" ] || return 0
    while IFS='=' read -r K V; do
        case "$K" in
            ENFORCE) case "$V" in 1) ENFORCE=1 ;; *) ENFORCE=0 ;; esac ;;
            BYPASS) case "$V" in 1) BYPASS=1 ;; *) BYPASS=0 ;; esac ;;
            EXCLUDE) EXCLUDE=$V ;;
            FAILOPEN) case "$V" in 0) FAILOPEN=0 ;; *) FAILOPEN=1 ;; esac ;;
            CHAIN) case "$V" in 0) CHAIN=0 ;; *) CHAIN=1 ;; esac ;;
        esac
    done < "$CONF"
}

conf_write()
{
    mkdir -p "$(dirname "$CONF")" || return 1
    printf 'ENFORCE=%s\nBYPASS=%s\nEXCLUDE=%s\nFAILOPEN=%s\nCHAIN=%s\n' "$ENFORCE" "$BYPASS" "$EXCLUDE" "$FAILOPEN" "$CHAIN" > "$CONF.tmp.$$" &&
        chmod 0600 "$CONF.tmp.$$" && mv -f "$CONF.tmp.$$" "$CONF"
}

state_get() { [ -r "$STATE" ] && awk -F= -v k="$1" '$1 == k {print substr($0, length(k) + 2); exit}' "$STATE"; }
state_write()
{
    {
        for sw_kv in "$@"; do echo "$sw_kv"; done
    } > "$STATE.$$" && mv -f "$STATE.$$" "$STATE"
}

# The router's LAN address and subnet, and where AdGuard Home keeps its settings.
LAN="" SUB="" AGH_YAML=""
profile_load()
{
    pl_out=$(
        VWARD_DEVICE_CONFIG="$ADS_DEVICE_CONFIG"; export VWARD_DEVICE_CONFIG
        . "$ADS_DEVICE_PROFILE_LIB" >/dev/null 2>&1 || exit 1
        vward_profile_load >/dev/null 2>&1 || exit 1
        printf '%s %s %s\n' "${VWARD_LAN_ADDRESS:-}" "${VWARD_LAN_SUBNET:-}" "${VWARD_ADGUARD_CONFIG:-}"
    ) || return 1
    set -- $pl_out
    LAN=${1:-} SUB=${2:-} AGH_YAML=${3:-}
    [ -n "$LAN" ] && [ -n "$SUB" ]
}

agh_port()
{
    awk '/^[^ #]/ {d = ($1 == "dns:")} d && $1 == "port:" {print $2; exit}' "$AGH_YAML" 2>/dev/null
}

# AdGuard Home's DNS port is open (UDP).
agh_up()
{
    "$NETSTAT" -lnu 2>/dev/null | awk -v p=":$1" '$4 ~ p "$" {f = 1} END {exit !f}'
}

# AdGuard Home answers a DNS query on its port (BusyBox nslookup takes «address:port»); waits at most 5 s.
agh_answers()
{
    aa_out="/tmp/vward-dns-guard.probe.$$"
    "$NSLOOKUP" "$PROBE_HOST" "$LAN:$1" > "$aa_out" 2>&1 &
    aa_pid=$!
    aa_i=0
    while kill -0 "$aa_pid" 2>/dev/null && [ "$aa_i" -lt 5 ]; do sleep 1; aa_i=$((aa_i + 1)); done
    kill "$aa_pid" 2>/dev/null
    awk '/^Name:/ {f = 1} f && /^Address/ {n++} END {exit !n}' "$aa_out"
    aa_rc=$?
    rm -f "$aa_out"
    return "$aa_rc"
}

valid_mac() { case "$1" in [0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]) return 0 ;; esac; return 1; }
valid_ip() { case "$1" in ''|*[!0-9.]*|*..*|.*|*.) return 1 ;; esac; [ "$(printf '%s\n' "$1" | awk -F. 'NF == 4 && $1 <= 255 && $2 <= 255 && $3 <= 255 && $4 <= 255 {print "ok"}')" = ok ]; }

# The current addresses of the excluded devices, from Keenetic.  Fails when
# Keenetic does not answer: an excluded device must never be redirected by accident.
excluded_ips()
{
    [ -n "$EXCLUDE" ] || return 0
    ei_json=$("$ADS_CURL" -fsS --connect-timeout 2 --max-time 8 "$RCI_BASE/show/ip/hotspot" 2>/dev/null) || return 1
    ei_list=$(printf '%s' "$ei_json" | "$ADS_JQ" -r --arg m "$EXCLUDE" '
        ($m | split(",")) as $want |
        [(.host // [])[] | select(((.mac // "") | ascii_downcase) as $x | $want | index([$x])) | .ip // empty] |
        .[]' 2>/dev/null) || return 1
    printf '%s\n' "$ei_list" | while IFS= read -r ei; do valid_ip "$ei" && printf '%s\n' "$ei"; done | sort -u
    return 0
}

ipt() { "$IPT" "$@" 2>/dev/null; }

nat_remove()
{
    for p in udp tcp; do
        while ipt -t nat -D PREROUTING -s "$SUB" -p "$p" --dport 53 -j VWARD_DNS; do :; done
    done
    ipt -t nat -F VWARD_DNS; ipt -t nat -X VWARD_DNS
    return 0
}

nat_apply()
{
    ipt -t nat -N VWARD_DNS || ipt -t nat -F VWARD_DNS || return 1
    for ip in $EX_IPS; do ipt -t nat -A VWARD_DNS -s "$ip" -j RETURN || return 1; done
    # Queries to the router go on to the rules already there (AdGuard Home sees the device).
    ipt -t nat -A VWARD_DNS -d "$LAN" -j RETURN || return 1
    # A port in DNAT needs the protocol: iptables 1.4 (Keenetic's Entware) refuses it
    # without one («Need TCP, UDP...», the rule never went in on a router).
    for p in udp tcp; do
        ipt -t nat -A VWARD_DNS -p "$p" -j DNAT --to-destination "$LAN:$PORT" || return 1
    done
    for p in udp tcp; do
        ipt -t nat -C PREROUTING -s "$SUB" -p "$p" --dport 53 -j VWARD_DNS ||
            ipt -t nat -I PREROUTING 1 -s "$SUB" -p "$p" --dport 53 -j VWARD_DNS || return 1
    done
}

fwd_remove()
{
    while ipt -D FORWARD -s "$SUB" -j VWARD_DNS_FWD; do :; done
    ipt -F VWARD_DNS_FWD; ipt -X VWARD_DNS_FWD
    return 0
}

# refuse PROTO PORT [DEST]: REJECT where the kernel has it, DROP otherwise.
refuse()
{
    rf_dst=""; [ -z "${3:-}" ] || rf_dst="-d $3"
    if [ "$1" = tcp ]; then
        ipt -A VWARD_DNS_FWD $rf_dst -p tcp --dport "$2" -j REJECT --reject-with tcp-reset ||
            ipt -A VWARD_DNS_FWD $rf_dst -p tcp --dport "$2" -j DROP
    else
        ipt -A VWARD_DNS_FWD $rf_dst -p udp --dport "$2" -j REJECT ||
            ipt -A VWARD_DNS_FWD $rf_dst -p udp --dport "$2" -j DROP
    fi
}

fwd_apply()
{
    ipt -N VWARD_DNS_FWD || ipt -F VWARD_DNS_FWD || return 1
    for ip in $EX_IPS; do ipt -A VWARD_DNS_FWD -s "$ip" -j RETURN || return 1; done
    refuse tcp 853 || return 1
    refuse udp 853 || return 1
    for ip in $DOH_IPS; do
        refuse tcp 443 "$ip" || return 1
        refuse udp 443 "$ip" || return 1
    done
    ipt -C FORWARD -s "$SUB" -j VWARD_DNS_FWD || ipt -I FORWARD 1 -s "$SUB" -j VWARD_DNS_FWD || return 1
}

hook_install()
{
    mkdir -p "$HOOK_DIR" || return 1
    cat > "$HOOK.tmp.$$" <<EOF || return 1
#!/bin/sh
# VWARD: DNS of the home network through AdGuard Home (vward-ads-privacy-dns-guard.sh).
# Keenetic rebuilt its firewall: the rules go back.
[ "\$type" = iptables ] || exit 0
case "\$table" in nat|filter) ;; *) exit 0 ;; esac
[ -x "$SELF_BIN" ] && "$SELF_BIN" hook "\$table" >/dev/null 2>&1
exit 0
EOF
    chmod 0755 "$HOOK.tmp.$$" && mv -f "$HOOK.tmp.$$" "$HOOK"
}

nat_count() { ipt -t nat -L VWARD_DNS -n -v -x | awk '$3 == "DNAT" {n += $1} END {print n + 0}'; }
fwd_count() { ipt -L VWARD_DNS_FWD -n -v -x | awk '$3 == "REJECT" || $3 == "DROP" {n += $1} END {print n + 0}'; }
nat_present() { ipt -t nat -C PREROUTING -s "$SUB" -p udp --dport 53 -j VWARD_DNS; }
fwd_present() { ipt -C FORWARD -s "$SUB" -j VWARD_DNS_FWD; }

# The DoH names list in AdGuard Home follows the bypass switch (never removed).
doh_list()
{
    dl_dir=$(mktemp -d /tmp/vward-dns-guard.XXXXXX) || return 1
    ads_agh_api_get filtering/status "$dl_dir/f.json" >/dev/null 2>&1 || { rm -rf "${dl_dir:?}"; return 1; }
    dl_have=$("$ADS_JQ" -r --arg u "$DOH_LIST_URL" '[.filters[]? | select(.url == $u)][0] | if . == null then "none" elif .enabled then "on" else "off" end' "$dl_dir/f.json")
    rm -rf "${dl_dir:?}"
    case "$1:$dl_have" in
        1:none) "$CONTROL" agh filter-add "$DOH_LIST_URL" "$DOH_LIST_NAME" >/dev/null 2>&1 ;;
        1:off) "$CONTROL" agh filter-enable "$DOH_LIST_URL" 1 >/dev/null 2>&1 ;;
        0:on) "$CONTROL" agh filter-enable "$DOH_LIST_URL" 0 >/dev/null 2>&1 ;;
        *) return 0 ;;
    esac
}

# Once every DNS query of the home goes through AdGuard Home its own way out must be
# encrypted, or a device that used DoH before would now be read by the ISP.  Read
# only: "encrypted", "plain" or "unknown" (Smart DNS rows [/domain/]... are ignored).
upstream_state()
{
    [ -r "$AGH_YAML" ] || { echo unknown; return 0; }
    awk '/^  upstream_dns:/ {f = 1; next} f && /^  [a-z_]+:/ {exit}
         f && /^ *- / {sub(/^ *- /, ""); gsub(/^'"'"'|'"'"'$|^"|"$/, ""); print}' "$AGH_YAML" |
    awk 'BEGIN {n = 0; p = 0}
         /^\[\// || /^#/ || NF == 0 {next}
         # A local DoH client (127.0.0.1:5453, https-dns-proxy) encrypts too; port 53 is Keenetic.
         {n++; if ($0 !~ /^(https|tls|quic|h3|sdns):\/\// && ($0 !~ /^((udp|tcp):\/\/)?(127\.[0-9]+\.[0-9]+\.[0-9]+|\[::1\]):[0-9]+$/ || $0 ~ /:53$/)) p++}
         END {print (n == 0 ? "unknown" : (p == 0 ? "encrypted" : "plain"))}'
}

# reconcile FULL: rules as the settings and AdGuard Home want them.
# The nat PREROUTING rules that send port 53 into AdGuard Home's port, whoever put them there
# (VWARD's own go through the VWARD_DNS chain and are handled by reconcile).
foreign_rules() { ipt -t nat -S PREROUTING | grep -e '--dport 53 ' | grep -e "-j REDIRECT --to-ports $1\$" | grep -v '"'; }

failopen_park()
{
    fp_rules=$(foreign_rules "$1")
    [ -n "$fp_rules" ] || return 0
    { [ ! -r "$PARK" ] || cat "$PARK"; printf '%s\n' "$fp_rules"; } | sort -u > "$PARK.new" && mv -f "$PARK.new" "$PARK"
    printf '%s\n' "$fp_rules" | while IFS= read -r fp_r; do
        # shellcheck disable=SC2046
        ipt -t nat $(printf '%s' "$fp_r" | sed 's/^-A /-D /')
    done
    ads_log "DNS_FAILOPEN|port=$1|rules=$(printf '%s\n' "$fp_rules" | wc -l | tr -d ' ')|redirect taken off: nothing answers there"
}

failopen_restore()
{
    [ -s "$PARK" ] || return 0
    fr_bad=0 fr_n=0
    while IFS= read -r fr_r; do
        [ -n "$fr_r" ] || continue
        # shellcheck disable=SC2046
        if ipt -t nat $(printf '%s' "$fr_r" | sed 's/^-A /-C /'); then :
        elif ipt -t nat $(printf '%s' "$fr_r" | sed 's/^-A PREROUTING /-I PREROUTING 1 /'); then fr_n=$((fr_n + 1))
        else fr_bad=1; fi
    done < "$PARK"
    [ "$fr_bad" = 1 ] || rm -f "$PARK"
    ads_log "DNS_RESTORED|port=$1|rules=$fr_n|redirect put back: AdGuard Home answers again"
}

# MODE quick (the firewall hook: never waits): only whether the port is open.
# MODE full (the minute tick): the port answers a query; open but silent twice in a row counts as dead.
failopen_sync()
{
    [ "$FAILOPEN" = 1 ] || return 0
    fo_port=$(agh_port)
    case "$fo_port" in ''|*[!0-9]*) return 0 ;; esac
    fo_open=0; agh_up "$fo_port" && fo_open=1
    fo_ok=0
    if [ "$fo_open" = 1 ]; then
        if [ "$1" = quick ]; then fo_ok=1; elif agh_answers "$fo_port"; then fo_ok=1; fi
    fi
    if [ "$fo_ok" = 1 ]; then
        rm -f "$PROBE_FAILS"
        failopen_restore "$fo_port"
        return 0
    fi
    if [ "$fo_open" = 1 ]; then
        fo_n=0; [ ! -r "$PROBE_FAILS" ] || read -r fo_n < "$PROBE_FAILS"
        case "$fo_n" in ''|*[!0-9]*) fo_n=0 ;; esac
        fo_n=$((fo_n + 1)); echo "$fo_n" > "$PROBE_FAILS"
        [ "$fo_n" -ge 2 ] || return 0
    fi
    failopen_park "$fo_port"
}

# ------------------------------------------------------------ the chain
# AdGuard Home's DNS address for Keenetic: its first bind host that is an address of the
# router (not 0.0.0.0 / ::), else the LAN address.
agh_dns_host()
{
    awk -v lan="$LAN" '/^[^ #]/ {d = ($1 == "dns:"); b = 0; next}
        d && /^  bind_hosts:/ {b = 1; next} d && /^  [a-z_]+:/ {b = 0}
        b && $1 == "-" {gsub(/["\047]/, "", $2); n = split($2, o, ".")
            if (n == 4 && $2 ~ /^[0-9.]+$/ && $2 != "0.0.0.0" && o[1] <= 255 && o[2] <= 255 && o[3] <= 255 && o[4] <= 255) {print $2; f = 1; exit}}
        END {if (!f) print lan}' "$AGH_YAML" 2>/dev/null || echo "$LAN"
}

# A change drops the configuration copy the agents share (vward_keenetic_config).
ndm() {
    rm -f "${VWARD_KCACHE:-${VWARD_ROOT_PREFIX:-}/tmp/vward-keenetic}/running-config" 2>/dev/null
    nd_out=$("$NDMC" -c "$1" 2>&1) || return 1; ! printf '%s\n' "$nd_out" | grep -Eqi '(^|[^a-z])(error|failed|invalid|unknown command)'
}
# ndm_running: Keenetic's configuration, the copy the agents share when the device library is
# there (one read for all, «Роутер отвечает медленно», fix.28.2), else asked directly.
ndm_running() {
    if [ -z "${VWARD_NDMC:-}" ] && [ -r "$ADS_DEVICE_PROFILE_LIB" ]; then
        ( . "$ADS_DEVICE_PROFILE_LIB" >/dev/null 2>&1 && vward_keenetic_config ) && return 0
    fi
    "$NDMC" -c "show running-config" 2>/dev/null
}

# AdGuard Home restarted 4 times within 10 minutes (its process id changed), the last one
# within 3 minutes: a loop.
agh_looping()
{
    al_pid=$("$PIDOF" AdGuardHome 2>/dev/null); al_pid=${al_pid%% *}
    al_now=$(ads_epoch)
    # A restart VWARD made on purpose (an update: «planned») is not a crash.
    al_plan=
    [ ! -r "$CHAIN_DIR/planned" ] || read -r al_plan < "$CHAIN_DIR/planned" || :
    case "$al_plan" in ''|*[!0-9]*) al_plan=0 ;; esac
    # Read and pruned in the shell: this runs every minute, and a router counts its processes.
    # Lines: «time pid» for a crash, «time pid p» for a planned restart; the first id seen
    # is the running one, not a restart.
    al_n=0 al_t=0 al_last= al_keep= al_first=1
    if [ -r "$CHAIN_DIR/pids" ]; then
        while read -r al_et al_ep al_ek; do
            case "$al_et" in ''|*[!0-9]*) continue ;; esac
            al_last=$al_ep
            [ $((al_now - al_et)) -le 600 ] || continue
            al_keep="$al_keep$al_et $al_ep${al_ek:+ $al_ek}
"
            if [ "$al_first" = 1 ]; then al_first=0; continue; fi
            [ -n "$al_ek" ] || { al_n=$((al_n + 1)); al_t=$al_et; }
        done < "$CHAIN_DIR/pids"
    fi
    if [ -n "$al_pid" ] && [ "$al_pid" != "$al_last" ]; then
        al_k=; [ "$al_now" -gt "$al_plan" ] || al_k=p
        al_keep="$al_keep$al_now $al_pid${al_k:+ $al_k}
"
        if [ "$al_first" = 0 ] && [ -z "$al_k" ]; then al_n=$((al_n + 1)); al_t=$al_now; fi
    fi
    printf '%s' "$al_keep" > "$CHAIN_DIR/pids"
    # Two crashes within 10 minutes, the last within 3 minutes: a loop (one crash is not:
    # the minute check and the real-time watcher take a silent AdGuard Home out anyway).
    [ "$al_n" -ge 2 ] && [ $((al_now - al_t)) -lt 180 ]
}

# agh_unbind: the list domains the route engine bound to AdGuard Home in Keenetic go with it
# (Keenetic asks the provider's DNS for them again); the route engine binds them anew on use
# once AdGuard Home is back in the chain. Bindings made by hand («ext») stay.
agh_unbind()
{
    [ -s "$AGH_BIND" ] || return 0
    au_n=0
    while read -r au_d au_ns; do
        case "$au_ns" in ''|ext|failed) continue ;; esac
        ndm "no ip name-server $au_ns $au_d" </dev/null && au_n=$((au_n + 1))
    done < "$AGH_BIND"
    rm -f "$AGH_BIND"
    ads_log "AGH_UNBIND|count=$au_n|list domains asked of the provider's DNS while AdGuard Home is out"
}

# orphan_sync: Keenetic hands DNS to a server on the router itself (the LAN address or 127.0.0.1,
# a port other than 53) that nothing listens on: AdGuard Home removed with the USB stick, its
# chain line and its list bindings left behind - Keenetic asked a dead server for ChatGPT,
# Claude, YouTube... (Viva 2026-10-19: 25 such lines, no AdGuard Home on the router at all).
# Seen twice 5 minutes apart (a restart is not a death), every line to it goes: the chain line,
# the bindings, the record of them. The chain comes back by chain_sync once AdGuard Home answers.
# Not the observation mode's to hold: a DNS nobody answers breaks the home, taking it out does not.
ORPHAN_EVERY=${VWARD_DNS_ORPHAN_EVERY_MIN:-4}
orphan_listening()
{
    ol_hex=$(printf '%04X' "$1")
    awk -v h=":$ol_hex" 'FNR > 1 && $2 ~ h "$" {f = 1} END {exit !f}' \
        "${VWARD_PROC_NET:-/proc/net}/udp" "${VWARD_PROC_NET:-/proc/net}/udp6" 2>/dev/null
}
# ns_release NS CONFIG REASON: every Keenetic DNS line into NS (the chain line and the domains
# bound to it) out, the chain «out» and the bindings forgotten; prints how many lines went.
ns_release()
{
    nr_n=0
    for nr_d in $(printf '%s\n' "$2" | awk -v n="$1" '$1 == "ip" && $2 == "name-server" && $3 == n && NF >= 4 && $4 != "on" && $4 != "\"\"" {print $4}'); do
        ndm "no ip name-server $1 $nr_d" </dev/null >/dev/null 2>&1 && nr_n=$((nr_n + 1))
    done
    if printf '%s\n' "$2" | chain_line "$1"; then
        ndm "no ip name-server $1" </dev/null >/dev/null 2>&1 && nr_n=$((nr_n + 1))
    fi
    # «out»: the route engine binds nothing more to it until chain_sync sees it answer again.
    echo out > "$CHAIN_DIR/state"; echo "$3" > "$CHAIN_DIR/reason"; ads_epoch > "$CHAIN_DIR/since"
    if [ -s "$AGH_BIND" ]; then
        awk -v n="$1" '$2 != n' "$AGH_BIND" > "$AGH_BIND.$$" && mv -f "$AGH_BIND.$$" "$AGH_BIND"
        [ -s "$AGH_BIND" ] || rm -f "$AGH_BIND"
    fi
    echo "$nr_n"
}

# release_all: AdGuard Home switched off or removed from the Panel (fix.32) - its DNS lines in
# Keenetic go at once, whoever answers on the port, so DNS never points at a stopped program.
release_all()
{
    mkdir -p "$CHAIN_DIR" || return 1
    ra_rc=$(ndm_running) || return 1
    ra_list=$(printf '%s\n' "$ra_rc" | awk -v lan="$LAN" '$1 == "ip" && $2 == "name-server" {
            n = split($3, a, ":"); if (n != 2 || a[2] !~ /^[0-9]+$/ || a[2] == 53) next
            if (a[1] == lan || a[1] == "127.0.0.1") print $3}' | awk '!s[$0]++')
    ra_n=0
    for ra_ns in $ra_list; do ra_n=$((ra_n + $(ns_release "$ra_ns" "$ra_rc" released))); done
    [ "$ra_n" = 0 ] || { ndm "system configuration save" </dev/null >/dev/null 2>&1 || :; ads_log "DNS_RELEASED|lines=$ra_n|AdGuard Home switched off from the Panel"; }
    echo "released=$ra_n"
}

orphan_sync()
{
    mkdir -p "$CHAIN_DIR" || return 0
    [ -z "$(find "$CHAIN_DIR/orphan.at" -mmin "-$ORPHAN_EVERY" 2>/dev/null)" ] || return 0
    : > "$CHAIN_DIR/orphan.at"
    os_rc=$(ndm_running) || return 0
    os_list=$(printf '%s\n' "$os_rc" | awk -v lan="$LAN" '$1 == "ip" && $2 == "name-server" {
            n = split($3, a, ":"); if (n != 2 || a[2] !~ /^[0-9]+$/ || a[2] == 53) next
            if (a[1] == lan || a[1] == "127.0.0.1") print $3}' | awk '!s[$0]++')
    [ -n "$os_list" ] || { rm -f "$CHAIN_DIR"/orphan.*.n; return 0; }
    for os_ns in $os_list; do
        os_port=${os_ns##*:} os_f=$CHAIN_DIR/orphan.$os_port.n
        if orphan_listening "$os_port"; then rm -f "$os_f"; continue; fi
        [ "$(count_up "$os_f")" -ge 2 ] || continue
        os_n=$(ns_release "$os_ns" "$os_rc" absent)
        rm -f "$os_f"
        [ "$os_n" = 0 ] && continue
        ndm "system configuration save" </dev/null || :
        ads_log "DNS_ORPHAN_OUT|ns=$os_ns|lines=$os_n|nothing answers on the router at this port: Keenetic asks the provider's DNS"
        ( . "$ADS_DEVICE_PROFILE_LIB" >/dev/null 2>&1 && vward_note warn "DNS AdGuard Home убран из Keenetic" \
            "На роутере никто не отвечает на порту $os_port, а Keenetic отправлял туда запросы ($os_n строк). Строки убраны: DNS идёт через провайдера. Установите или запустите AdGuard Home - VWARD вернёт его в цепочку сам." d-agh ) || :
    done
}

count_up() { cu_n=0; [ ! -r "$1" ] || read -r cu_n < "$1"; case "$cu_n" in ''|*[!0-9]*) cu_n=0 ;; esac; echo $((cu_n + 1)) > "$1"; echo $((cu_n + 1)); }

# chain_line NS (Keenetic's configuration on stdin): Keenetic hands all queries to NS - the line
# without a domain («""» in its place when an interface follows). A domain bound to it (Smart DNS, a list) is not the chain: with 24 such
# bindings the guard took AdGuard Home for in after a fast take-out and never put it back (Viva
# 2026-10-13).
chain_line()
{
    awk -v n="$1" '$1 == "ip" && $2 == "name-server" && $3 == n && (NF == 3 || $4 == "\"\"" || $4 == "on") {f = 1} END {exit !f}'
}

# chain_take_out NS REASON: Keenetic stops handing queries to AdGuard Home (the provider's DNS
# answers alone); back in by chain_sync after 3 answers in a row.
chain_take_out()
{
    ndm "no ip name-server $1" || return 1
    agh_unbind
    ndm "system configuration save" || :
    rm -f "$CHAIN_DIR/fails" "$CHAIN_DIR/oks"
    echo out > "$CHAIN_DIR/state"; ads_epoch > "$CHAIN_DIR/since"; echo "$2" > "$CHAIN_DIR/reason"
    # The take-outs of the last hour: each more waits longer before AdGuard Home goes back in.
    to_now=$(ads_epoch)
    { [ ! -r "$CHAIN_DIR/outs" ] || awk -v n="$to_now" '$1 + 3600 > n' "$CHAIN_DIR/outs"; echo "$to_now"; } > "$CHAIN_DIR/outs.new" 2>/dev/null &&
        mv -f "$CHAIN_DIR/outs.new" "$CHAIN_DIR/outs"
    ads_log "DNS_CHAIN_OUT|ns=$1|reason=$2|AdGuard Home taken out of the DNS chain: Keenetic uses the provider's DNS"
}

# provider_answers NS: one of Keenetic's other DNS servers answers (the internet is there, only
# AdGuard Home is not). No other server known: yes (nothing to compare with).
provider_answers()
{
    pa_list=$("$NDMC" -c "show ip name-server" 2>/dev/null | awk '$1 == "address:" {print $2}' |
        grep -E '^[0-9]+(\.[0-9]+){3}$' | grep -vx "${1%:*}" | awk '!s[$0]++' | head -n 2)
    [ -n "$pa_list" ] || return 0
    for pa in $pa_list; do
        "$NSLOOKUP" "$PROBE_HOST" "$pa" 2>/dev/null | awk '/^Name:/ {f = 1} f && /^Address/ {n++} END {exit !n}' && return 0
    done
    return 1
}

# chain_out: the real-time watcher saw AdGuard Home silent 3 times in a row (15 s): out at once,
# when it still does not answer and the provider's DNS does.
chain_out()
{
    [ "$CHAIN" = 1 ] && [ -n "$AGH_YAML" ] && [ -r "$AGH_YAML" ] || return 0
    co_port=$(agh_port)
    case "$co_port" in ''|*[!0-9]*|53) return 0 ;; esac
    mkdir -p "$CHAIN_DIR" || return 0
    # Already out: the watcher asks again each minute while AdGuard Home is silent; Keenetic's
    # configuration is not read for it (it answered slowly enough already, Viva 2026-10-17).
    co_st=; [ ! -r "$CHAIN_DIR/state" ] || read -r co_st < "$CHAIN_DIR/state" || :
    [ "$co_st" != out ] || return 0
    co_ns="$(agh_dns_host):$co_port"
    ndm_running | chain_line "$co_ns" || return 0
    agh_up "$co_port" && agh_answers "$co_port" && return 0
    provider_answers "$co_ns" || { ads_log "DNS_CHAIN_KEEP|ns=$co_ns|the provider's DNS is silent too: AdGuard Home stays"; return 0; }
    chain_take_out "$co_ns" fast
}

# chain_sync: AdGuard Home in Keenetic's DNS chain while it answers, out of it while it does not.
chain_sync()
{
    [ "$CHAIN" = 1 ] && [ -n "$AGH_YAML" ] && [ -r "$AGH_YAML" ] || return 0
    cs_port=$(agh_port)
    case "$cs_port" in ''|*[!0-9]*|53) return 0 ;; esac
    mkdir -p "$CHAIN_DIR" || return 0
    cs_ns="$(agh_dns_host):$cs_port"
    # A planned restart (an update) in progress: chain_planned_done decides.
    cs_plan=; [ ! -r "$CHAIN_DIR/planned" ] || read -r cs_plan < "$CHAIN_DIR/planned" || :
    case "$cs_plan" in ''|*[!0-9]*) ;; *) [ "$(ads_epoch)" -gt "$cs_plan" ] || return 0 ;; esac
    cs_rc=$(ndm_running) || return 0
    [ -n "$cs_rc" ] || return 0
    cs_in=0
    printf '%s\n' "$cs_rc" | chain_line "$cs_ns" && cs_in=1
    # A short pause (a filter reload, a quick restart) is not a death: a check is three tries
    # 5 s apart, and only three failed checks in a row (3 minutes) take AdGuard Home out.
    cs_ok=0 cs_try=0
    while [ "$cs_try" -lt "${VWARD_DNS_CHAIN_TRIES:-3}" ]; do
        agh_up "$cs_port" && agh_answers "$cs_port" && { cs_ok=1; break; }
        cs_try=$((cs_try + 1))
        [ "$cs_try" -ge "${VWARD_DNS_CHAIN_TRIES:-3}" ] || sleep "${VWARD_DNS_CHAIN_PAUSE:-5}"
    done
    cs_loop=0
    if agh_looping; then cs_ok=0 cs_loop=1; fi
    if [ "$cs_ok" = 1 ]; then rm -f "$CHAIN_DIR/fails"; else rm -f "$CHAIN_DIR/oks"; fi
    if [ "$cs_in" = 1 ]; then
        echo in > "$CHAIN_DIR/state"
        # In the chain while AdGuard Home asks the router back (its servers changed since): out
        # at once, the provider's DNS answers; back only when the loop is gone (below).
        if agh_upstream_loops; then
            chain_take_out "$cs_ns" loop_upstream
            return 0
        fi
        [ "$cs_ok" = 0 ] || return 0
        [ "$(count_up "$CHAIN_DIR/fails")" -ge 3 ] || [ "$cs_loop" = 1 ] || return 0
        # The whole internet down (the provider's DNS silent too): not AdGuard Home's fault,
        # and taking it out would change nothing.
        if [ "$cs_loop" = 0 ] && ! provider_answers "$cs_ns"; then
            ads_log "DNS_CHAIN_KEEP|ns=$cs_ns|the provider's DNS is silent too: AdGuard Home stays"
            return 0
        fi
        chain_take_out "$cs_ns" "$([ "$cs_loop" = 1 ] && echo loop || echo silent)"
        return 0
    fi
    # Out of the chain: back after 3 answers in a row, unless AdGuard Home would send the
    # queries back to the router (a loop Keenetic answers by dropping them).
    [ "$cs_ok" = 1 ] || { echo out > "$CHAIN_DIR/state"; return 0; }
    # 3 answers in a row (3 minutes); taken out again within the hour: 9, then 15 (out and in
    # every few minutes, each with a save, was 114 Keenetic errors an hour, Viva 2026-10-16).
    cs_outs=$(awk -v n="$(ads_epoch)" '$1 + 3600 > n' "$CHAIN_DIR/outs" 2>/dev/null | wc -l)
    cs_need=3; [ "$cs_outs" -lt 2 ] || cs_need=9; [ "$cs_outs" -lt 3 ] || cs_need=15
    [ "$(count_up "$CHAIN_DIR/oks")" -ge "$cs_need" ] || { echo out > "$CHAIN_DIR/state"; return 0; }
    if agh_upstream_loops; then
        echo loop_upstream > "$CHAIN_DIR/reason"; echo out > "$CHAIN_DIR/state"
        return 0
    fi
    chain_put_in "$cs_ns"
}

# agh_upstream_loops: AdGuard Home sends every query (not a [/domain/] row) back to the
# router's own DNS, so with it in the chain Keenetic and AdGuard Home ask each other («proxy
# loop detected», Keenetic then drops the server: task 158). Its fallback servers count too.
agh_upstream_loops()
{
    awk '/^[^ #]/ {d = ($1 == "dns:"); u = 0; next} /^  [a-z_]+:/ {u = d && ($1 == "upstream_dns:" || $1 == "fallback_dns:"); next}
            u && $1 == "-" {gsub(/["\047]/, "", $2); print $2}' "$AGH_YAML" |
        grep -Eq "^((udp|tcp)://)?($LAN|127\.0\.0\.1|localhost)(:53)?$"
}

# chain_put_in NS: Keenetic hands the queries to AdGuard Home again.
chain_put_in()
{
    if ndm "ip name-server $1"; then
        ndm "system configuration save" || :
        rm -f "$CHAIN_DIR/fails" "$CHAIN_DIR/oks" "$CHAIN_DIR/reason"
        echo in > "$CHAIN_DIR/state"; ads_epoch > "$CHAIN_DIR/since"
        ads_log "DNS_CHAIN_IN|ns=$1|AdGuard Home back in the DNS chain"
    fi
}

# chain_planned SECONDS: VWARD is about to restart or update AdGuard Home on purpose: out of
# the chain first, so nobody waits on a DNS that is being replaced (the provider's DNS
# answers meanwhile); its process changes in that time are not crashes.
chain_planned()
{
    [ "$CHAIN" = 1 ] && [ -n "$AGH_YAML" ] && [ -r "$AGH_YAML" ] || return 0
    mkdir -p "$CHAIN_DIR" || return 0
    echo $(( $(ads_epoch) + $1 )) > "$CHAIN_DIR/planned"
    cp_port=$(agh_port)
    case "$cp_port" in ''|*[!0-9]*|53) return 0 ;; esac
    cp_ns="$(agh_dns_host):$cp_port"
    ndm_running | chain_line "$cp_ns" || return 0
    provider_answers "$cp_ns" || return 0
    chain_take_out "$cp_ns" update
}

# chain_planned_done: the planned restart is over: back in at once when AdGuard Home answers
# (else the minute check brings it back after 3 answers, as after any silence).
chain_planned_done()
{
    rm -f "$CHAIN_DIR/planned"
    [ "$(cat "$CHAIN_DIR/state" 2>/dev/null)" = out ] && [ "$(cat "$CHAIN_DIR/reason" 2>/dev/null)" = update ] || return 0
    pd_port=$(agh_port)
    case "$pd_port" in ''|*[!0-9]*|53) return 0 ;; esac
    pd_try=0
    while [ "$pd_try" -lt "${VWARD_DNS_PLANNED_WAIT:-12}" ]; do
        agh_up "$pd_port" && agh_answers "$pd_port" && { chain_put_in "$(agh_dns_host):$pd_port"; return 0; }
        pd_try=$((pd_try + 1)); sleep 5
    done
}

reconcile()
{
    rc_full=$1
    PORT=$(agh_port)
    case "$PORT" in ''|*[!0-9]*) PORT="" ;; esac
    if [ "$ENFORCE" = 0 ] && [ "$BYPASS" = 0 ]; then
        nat_remove; fwd_remove; rm -f "$HOOK"
        state_write "applied=0" "reason=off" "since=$(ads_epoch)"
        return 0
    fi
    if ! EX_IPS=$(excluded_ips); then
        state_write "applied=$(state_get applied)" "reason=router_unavailable" "sig=$(state_get sig)" "since=$(state_get since)"
        return 1
    fi
    EX_IPS=$(printf '%s\n' "$EX_IPS" | tr '\n' ' ')
    UP=0; [ -n "$PORT" ] && agh_up "$PORT" && UP=1
    sig="$ENFORCE|$BYPASS|$UP|$PORT|$LAN|$SUB|$EX_IPS"
    reason=ok
    [ "$ENFORCE" = 0 ] || [ "$UP" = 1 ] || reason=agh_down
    if [ "$rc_full" = 0 ] && [ "$sig" = "$(state_get sig)" ] &&
       { [ "$ENFORCE" = 0 ] || [ "$UP" = 0 ] || nat_present; } &&
       { [ "$BYPASS" = 0 ] || fwd_present; }; then
        return 0
    fi
    hook_install || reason=hook_failed
    if [ "$ENFORCE" = 1 ] && [ "$UP" = 1 ]; then
        nat_apply || { nat_remove; reason=nat_failed; }
    else
        nat_remove
    fi
    if [ "$BYPASS" = 1 ]; then
        fwd_apply || { fwd_remove; reason=filter_failed; }
    else
        fwd_remove
    fi
    [ "$rc_full" = 0 ] || doh_list "$BYPASS" || [ "$BYPASS" = 0 ] || reason=agh_list_failed
    since=$(state_get since); [ -n "$since" ] && [ "$(state_get sig)" = "$sig" ] || since=$(ads_epoch)
    state_write "applied=1" "reason=$reason" "sig=$sig" "since=$since"
    ads_log "DNS_GUARD|enforce=$ENFORCE|bypass=$BYPASS|agh_up=$UP|excluded=$(printf '%s' "$EX_IPS" | wc -w | tr -d ' ')|$reason"
    [ "$reason" = ok ] || [ "$reason" = agh_down ]
}

conf_load

# VWARD switched off as a whole («Отключить VWARD»): nothing of this guard runs; when Keenetic
# rebuilds its firewall, redirects into AdGuard Home go out again (vward-off.sh keep).
if [ -e "${VWARD_COMPONENT_STATE:-/opt/etc/vward/components}/vward.off" ] && [ "$OP" != status ]; then
    OFF_BIN="${VWARD_OFF_BIN:-/opt/bin/vward-off.sh}"
    [ "$OP" != hook ] || [ "${2:-}" != nat ] || [ ! -x "$OFF_BIN" ] || "$OFF_BIN" keep >/dev/null 2>&1
    echo "DNS_GUARD=VWARD_OFF"
    exit 0
fi

case "$OP" in
    status)
        echo "enforce=$ENFORCE"
        echo "bypass=$BYPASS"
        echo "exclude=$EXCLUDE"
        echo "failopen=$FAILOPEN"
        echo "chain=$CHAIN"
        echo "chain_state=$(cat "$CHAIN_DIR/state" 2>/dev/null)"
        echo "chain_reason=$(cat "$CHAIN_DIR/reason" 2>/dev/null)"
        echo "chain_since=$(cat "$CHAIN_DIR/since" 2>/dev/null)"
        echo "parked=$([ -s "$PARK" ] && wc -l < "$PARK" | tr -d ' ' || echo 0)"
        if profile_load; then
            PORT=$(agh_port)
            UP=0; [ -n "$PORT" ] && agh_up "$PORT" && UP=1
            echo "agh_up=$UP"
            N=0; nat_present && N=1; echo "redirect_active=$N"
            F=0; fwd_present && F=1; echo "bypass_active=$F"
            [ "$N" = 0 ] || echo "redirected=$(nat_count)"
            [ "$F" = 0 ] || echo "refused=$(fwd_count)"
        fi
        [ -r "$STATE" ] && grep -E '^(reason|since)=' "$STATE"
        [ -z "$AGH_YAML" ] || echo "upstream=$(upstream_state)"
        exit 0 ;;
    hook)
        # Called by Keenetic while it rebuilds the firewall: quick, and never blocking.
        # The owner's own redirect (hook 050) was just put back, asked or not: off again if nothing listens.
        if [ "$FAILOPEN" = 1 ] && [ "${2:-}" = nat ] && ads_lock_acquire "$LOCK" 60; then
            profile_load && failopen_sync quick
            ads_lock_release "$LOCK"
        fi
        [ "$ENFORCE" = 1 ] || [ "$BYPASS" = 1 ] || exit 0
        ads_lock_acquire "$LOCK" 60 || exit 0
        trap 'ads_lock_release "$LOCK"' EXIT
        profile_load || exit 0
        EX_IPS=$(state_get sig | cut -d'|' -f7)
        PORT=$(agh_port)
        case "${2:-}" in
            nat) [ "$ENFORCE" = 1 ] && [ -n "$PORT" ] && agh_up "$PORT" && nat_apply ;;
            filter) [ "$BYPASS" = 1 ] && fwd_apply ;;
        esac
        exit 0 ;;
    chain-out)
        ads_lock_acquire "$LOCK" 60 || exit 0
        trap 'ads_lock_release "$LOCK"' EXIT
        profile_load && chain_out
        echo "chain_state=$(cat "$CHAIN_DIR/state" 2>/dev/null)"
        exit 0 ;;
    planned|planned-done)
        # The minute check may hold the lock for a few seconds: wait for it (an update waits on us).
        pl_n=0; until ads_lock_acquire "$LOCK" 60; do pl_n=$((pl_n + 1)); [ "$pl_n" -lt 10 ] || exit 0; sleep 2; done
        trap 'ads_lock_release "$LOCK"' EXIT
        profile_load || exit 0
        if [ "$OP" = planned ]; then
            ps_s=${2:-300}; case "$ps_s" in ''|*[!0-9]*) ps_s=300 ;; esac; [ "$ps_s" -le 1800 ] || ps_s=1800
            chain_planned "$ps_s"
        else
            chain_planned_done
        fi
        echo "chain_state=$(cat "$CHAIN_DIR/state" 2>/dev/null)"
        exit 0 ;;
    orphan)
        # Every minute from the ads scheduler, before anything of ad blocking (that may be off or
        # not set up at all): DNS lines into a dead server on the router go.
        ads_lock_acquire "$LOCK" 60 || exit 0
        trap 'ads_lock_release "$LOCK"' EXIT
        profile_load && orphan_sync
        exit 0 ;;
    release)
        pl_n=0; until ads_lock_acquire "$LOCK" 60; do pl_n=$((pl_n + 1)); [ "$pl_n" -lt 10 ] || exit 1; sleep 2; done
        trap 'ads_lock_release "$LOCK"' EXIT
        profile_load || exit 1
        release_all || exit 1
        exit 0 ;;
    set|apply|tick) ;;
    *) echo "usage: $0 status|set enforce|bypass|chain 0|1|set exclude MACS|apply|tick|orphan|release|chain-out|planned SECONDS|planned-done|hook nat|filter" >&2; exit 64 ;;
esac

# Fail-open for a redirect into a dead AdGuard Home (the owner's own hook included).
if [ "$OP" = tick ] && [ "$FAILOPEN" = 1 ]; then
    if [ -s "$PARK" ] || ipt -t nat -S PREROUTING | grep -q -e '--dport 53 .*REDIRECT --to-ports'; then
        if ads_lock_acquire "$LOCK" 60; then
            profile_load && failopen_sync full
            ads_lock_release "$LOCK"
        fi
    fi
fi

# AdGuard Home in Keenetic's DNS chain while it answers (CHAIN=1).
if [ "$OP" = tick ] && [ "$CHAIN" = 1 ] && ads_lock_acquire "$LOCK" 60; then
    profile_load && chain_sync
    ads_lock_release "$LOCK"
fi

# Nothing on and nothing left over: the minute tick costs no process.
if [ "$OP" = tick ] && [ "$ENFORCE" = 0 ] && [ "$BYPASS" = 0 ] && [ ! -e "$HOOK" ] && [ ! -e "$STATE" ]; then
    exit 0
fi

ads_admission_enter ads-dns-guard
trap 'ads_lock_release "$LOCK" 2>/dev/null; ads_admission_leave' EXIT
trap 'exit 1' HUP INT TERM
ads_lock_acquire "$LOCK" 60 || { echo "DNS_GUARD=BUSY"; exit 75; }

FULL=0
if [ "$OP" = set ]; then
    case "${2:-}:${3:-}" in
        enforce:0|enforce:1) ENFORCE=$3 ;;
        bypass:0|bypass:1) BYPASS=$3 ;;
        chain:0|chain:1) CHAIN=$3 ;;
        exclude:-) EXCLUDE="" ;;
        exclude:*)
            NEW=""
            for m in $(printf '%s' "$3" | tr 'A-F,' 'a-f '); do
                valid_mac "$m" || { echo "DNS_GUARD=FAIL"; echo "ERROR=invalid_mac"; exit 64; }
                case ",$NEW," in *",$m,"*) ;; *) NEW="${NEW:+$NEW,}$m" ;; esac
            done
            EXCLUDE=$NEW ;;
        *) echo "DNS_GUARD=FAIL"; echo "ERROR=invalid_setting"; exit 64 ;;
    esac
    # Switching a part on needs an encrypted way out of AdGuard Home (see upstream_state).
    if [ "${3:-}" = 1 ] && [ "${2:-}" != chain ]; then
        profile_load && [ "$(upstream_state)" = encrypted ] ||
            { echo "DNS_GUARD=FAIL"; echo "ERROR=upstream_not_encrypted"; exit 1; }
    fi
    conf_write || { echo "DNS_GUARD=FAIL"; echo "ERROR=config_write_failed"; exit 1; }
    FULL=1
fi
[ "$OP" = apply ] && FULL=1

profile_load || { echo "DNS_GUARD=FAIL"; echo "ERROR=profile_unavailable"; exit 1; }
if reconcile "$FULL"; then
    echo "DNS_GUARD=PASS"
    echo "REASON=$(state_get reason)"
    exit 0
fi
echo "DNS_GUARD=FAIL"
echo "ERROR=$(state_get reason)"
exit 1
