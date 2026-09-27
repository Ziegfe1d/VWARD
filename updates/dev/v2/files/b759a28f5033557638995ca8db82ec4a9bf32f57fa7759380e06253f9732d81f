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
#
#   vward-ads-privacy-dns-guard.sh status
#   vward-ads-privacy-dns-guard.sh set enforce|bypass 0|1
#   vward-ads-privacy-dns-guard.sh set exclude MAC[,MAC...]   ("-" for none)
#   vward-ads-privacy-dns-guard.sh apply|tick                 (tick: the scheduler, every minute)
#   vward-ads-privacy-dns-guard.sh hook nat|filter            (Keenetic netfilter.d)

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
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

OP="${1:-status}"

ENFORCE=0 BYPASS=0 EXCLUDE=""
conf_load()
{
    [ -r "$CONF" ] || return 0
    while IFS='=' read -r K V; do
        case "$K" in
            ENFORCE) case "$V" in 1) ENFORCE=1 ;; *) ENFORCE=0 ;; esac ;;
            BYPASS) case "$V" in 1) BYPASS=1 ;; *) BYPASS=0 ;; esac ;;
            EXCLUDE) EXCLUDE=$V ;;
        esac
    done < "$CONF"
}

conf_write()
{
    mkdir -p "$(dirname "$CONF")" || return 1
    printf 'ENFORCE=%s\nBYPASS=%s\nEXCLUDE=%s\n' "$ENFORCE" "$BYPASS" "$EXCLUDE" > "$CONF.tmp.$$" &&
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
    ipt -t nat -A VWARD_DNS -j DNAT --to-destination "$LAN:$PORT" || return 1
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
         {n++; if ($0 !~ /^(https|tls|quic|h3|sdns):\/\//) p++}
         END {print (n == 0 ? "unknown" : (p == 0 ? "encrypted" : "plain"))}'
}

# reconcile FULL: rules as the settings and AdGuard Home want them.
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

case "$OP" in
    status)
        echo "enforce=$ENFORCE"
        echo "bypass=$BYPASS"
        echo "exclude=$EXCLUDE"
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
    set|apply|tick) ;;
    *) echo "usage: $0 status|set enforce|bypass 0|1|set exclude MACS|apply|tick|hook nat|filter" >&2; exit 64 ;;
esac

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
    if [ "${3:-}" = 1 ]; then
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
