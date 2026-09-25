#!/opt/bin/sh

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
    printf '%s\n' "$1" | awk -F. '
        NF != 4 {exit 1}
        {for (i=1;i<=4;i++) if ($i !~ /^[0-9]+$/ || $i < 0 || $i > 255) exit 1}
    '
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

# Device map records (tab separated), built from Keenetic RCI and running-config:
#   I <ndm-name> <type> <kernel-name> <security-level>
#   R <object-group> <route-target>
#   S <static-route-target>
vward_build_device_map()
{
    _vp_curl=${VWARD_CURL_BIN:-$(vward_tool curl)}
    _vp_jq=${VWARD_JQ_BIN:-$(vward_tool jq)}
    [ -n "$_vp_curl" ] && [ -n "$_vp_jq" ] || return 1

    _vp_ifaces=$("$_vp_curl" --fail --silent --connect-timeout 2 --max-time 4 \
        "$VWARD_RCI_BASE/show/interface" 2>/dev/null) || return 1
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
        _vp_sys=$("$_vp_curl" --fail --silent --connect-timeout 2 --max-time 3 \
            "$VWARD_RCI_BASE/show/interface/system-name?name=$_vp_ndm" 2>/dev/null |
            "$_vp_jq" -r '
                if type == "string" then .
                elif type == "object" then (.["system-name"] // .name // empty)
                else empty end
            ' 2>/dev/null)
        vward_valid_ifname "$_vp_sys" || _vp_sys=-
        printf 'I\t%s\t%s\t%s\t%s\n' "$_vp_ndm" "$_vp_type" "$_vp_sys" "$_vp_level"
    done

    command -v ndmc >/dev/null 2>&1 || return 0
    ndmc -c 'show running-config' 2>/dev/null | awk '
        $1=="route" && $2=="object-group" && NF>=4 {print "R\t" $3 "\t" $4}
        $1=="ip" && $2=="route" && NF>=5 {print "S\t" $5}
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
    if [ -f "$VWARD_DEVICE_MAP_CACHE" ] && [ ! -L "$VWARD_DEVICE_MAP_CACHE" ] &&
        [ "$(ls -ln "$VWARD_DEVICE_MAP_CACHE" 2>/dev/null | awk '{print $3}')" = "$(id -u)" ]; then
        _vp_age=$(( $(date +%s) - $(date -r "$VWARD_DEVICE_MAP_CACHE" +%s 2>/dev/null || echo 0) ))
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

vward_discover_wan_device()
{
    ip -4 route show default 2>/dev/null |
        awk '$1=="default" {for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}' |
        vward_unique
}

vward_discover_tunnel_device()
{
    for _vp_path in "$VWARD_SYSFS_NET"/*; do
        _vp_dev=${_vp_path##*/}
        vward_is_wireguard_sysfs "$_vp_dev" && printf '%s\n' "$_vp_dev"
    done | vward_unique
}

# Picks the managed WireGuard tunnel among any number of tunnels without relying
# on interface names: explicit config, the only tunnel, or the only tunnel that
# existing routes point to. Prints "<ndm-name> <kernel-name>".
vward_select_tunnel()
{
    _vp_map=$1
    _vp_cands=$(vward_map_tunnels "$_vp_map")
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
            vward_is_wireguard_sysfs "$_vp_dev" && continue
            [ -e "$VWARD_SYSFS_NET/$_vp_dev/tun_flags" ] && continue
            [ -n "$_vp_map" ] && [ "$(vward_map_level "$_vp_map" "$_vp_dev")" = public ] && continue
            printf '%s\n' "$_vp_map" | awk -F '\t' -v k="$_vp_dev" '
                $1=="I" && $4==k && tolower($3)=="wireguard" {found=1} END{exit !found}
            ' && continue
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
# and from upstream_dns_file.  Plain addresses and "#" (the default upstream)
# are local rules, not Smart DNS.  One lower-case domain per line.
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
            if (up !~ /^(https|tls|quic|sdns|h3):\/\//) next
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
            _vp_cands=$(vward_map_tunnels "$_vp_devmap" | awk '{printf "%s%s(%s)", sep, $1, $2; sep=", "}')
            vward_profile_error "tunnel device is missing or ambiguous; WireGuard candidates: ${_vp_cands:-none}; set VWARD_TUNNEL_INTERFACE in device.conf"
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

    case "$VWARD_CONSOLE_PORT" in ''|*[!0-9]*) vward_profile_error "invalid Console port"; return 1 ;; esac
    [ "$VWARD_CONSOLE_PORT" -ge 1024 ] && [ "$VWARD_CONSOLE_PORT" -le 65535 ] ||
        { vward_profile_error "Console port must be 1024..65535"; return 1; }

    case "${VWARD_POLICY_GROUP:-}" in *[!A-Za-z0-9_.:-]*) vward_profile_error "invalid policy group"; return 1 ;; esac

    export VWARD_RCI_BASE VWARD_CONSOLE_PORT VWARD_WAN_DEVICE VWARD_LAN_ADDRESS
    export VWARD_LAN_SUBNET VWARD_DNS_SERVER VWARD_TUNNEL_DEVICE
    export VWARD_PROBE_DNS
    export VWARD_ADGUARD_ADDRESS VWARD_ADGUARD_PORT
    export VWARD_TUNNEL_INTERFACE VWARD_POLICY_GROUP
    export VWARD_WAN_INTERFACE VWARD_LAN_DEVICE VWARD_LAN_INTERFACE
}
