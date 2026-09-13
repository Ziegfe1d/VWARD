#!/opt/bin/sh

VWARD_DEVICE_CONFIG=${VWARD_DEVICE_CONFIG:-/opt/etc/vward/device.conf}

vward_profile_error()
{
    echo "VWARD device profile: $*" >&2
    return 1
}

vward_valid_ifname()
{
    case "$1" in ''|*[!A-Za-z0-9_.:-]*) return 1 ;; *) return 0 ;; esac
}

vward_valid_ipv4()
{
    printf '%s\n' "$1" | awk -F. '
        NF != 4 {exit 1}
        {for (i=1;i<=4;i++) if ($i !~ /^[0-9]+$/ || $i < 0 || $i > 255) exit 1}
    '
}

vward_discover_wan_device()
{
    ip -4 route show default 2>/dev/null |
        awk '$1=="default" {for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}' |
        sort -u |
        awk 'NR==1{first=$0} NR>1{many=1} END{if(!many) print first}'
}

vward_discover_tunnel_device()
{
    for P in /sys/class/net/nwg* /sys/class/net/wg*; do
        [ -e "$P" ] || continue
        basename "$P"
    done | awk 'NR==1{first=$0} NR>1{many=1} END{if(!many) print first}'
}

vward_discover_lan_record()
{
    WAN="$1"
    ip -o -4 addr show scope global 2>/dev/null |
        awk -v wan="$WAN" '
            $2!=wan && $2 !~ /^(nwg|wg|tun|tap)/ {
                split($4,a,"/"); print $2, a[1]
            }
        ' |
        awk 'NR==1{line=$0} NR>1{many=1} END{if(!many) print line}'
}

vward_profile_load()
{
    VWARD_RCI_BASE=${VWARD_RCI_BASE:-http://127.0.0.1:79/rci}
    VWARD_CONSOLE_PORT=${VWARD_CONSOLE_PORT:-8088}

    if [ -r "$VWARD_DEVICE_CONFIG" ]; then
        PROFILE_META=$(stat -c '%u %a' "$VWARD_DEVICE_CONFIG" 2>/dev/null) ||
            vward_profile_error "cannot inspect device.conf"
        case "$PROFILE_META" in "0 600"|"0 400") ;; *)
            vward_profile_error "device.conf must be root-owned and mode 0600 or 0400"
            ;;
        esac
        # The file is trusted root-owned configuration, never request input.
        . "$VWARD_DEVICE_CONFIG" || return 1
    fi

    [ -n "${VWARD_WAN_DEVICE:-}" ] || VWARD_WAN_DEVICE=$(vward_discover_wan_device)
    vward_valid_ifname "${VWARD_WAN_DEVICE:-}" ||
        vward_profile_error "WAN device is missing or ambiguous"

    if [ -z "${VWARD_LAN_ADDRESS:-}" ] || [ -z "${VWARD_LAN_SUBNET:-}" ]; then
        LAN_RECORD=$(vward_discover_lan_record "$VWARD_WAN_DEVICE")
        [ -n "$LAN_RECORD" ] || vward_profile_error "LAN address is missing or ambiguous"
        set -- $LAN_RECORD
        [ -n "${VWARD_LAN_ADDRESS:-}" ] || VWARD_LAN_ADDRESS=$2
        if [ -z "${VWARD_LAN_SUBNET:-}" ]; then
            VWARD_LAN_SUBNET=$(ip -4 route show dev "$1" scope link 2>/dev/null |
                awk '$1 ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+\/[0-9]+$/ {print $1; exit}')
        fi
    fi

    vward_valid_ipv4 "$VWARD_LAN_ADDRESS" || vward_profile_error "invalid LAN address"
    case "$VWARD_LAN_SUBNET" in */[0-9]|*/[12][0-9]|*/3[0-2]) ;; *) vward_profile_error "invalid LAN subnet" ;; esac
    vward_valid_ipv4 "${VWARD_LAN_SUBNET%/*}" || vward_profile_error "invalid LAN subnet"

    [ -n "${VWARD_DNS_SERVER:-}" ] || VWARD_DNS_SERVER=$VWARD_LAN_ADDRESS
    vward_valid_ipv4 "$VWARD_DNS_SERVER" || vward_profile_error "invalid DNS server"
    [ -n "${VWARD_PROBE_DNS:-}" ] || VWARD_PROBE_DNS=$VWARD_DNS_SERVER
    vward_valid_ipv4 "$VWARD_PROBE_DNS" || vward_profile_error "invalid probe DNS server"

    [ -n "${VWARD_ADGUARD_ADDRESS:-}" ] || VWARD_ADGUARD_ADDRESS=$VWARD_LAN_ADDRESS
    vward_valid_ipv4 "$VWARD_ADGUARD_ADDRESS" || vward_profile_error "invalid AdGuard Home address"
    VWARD_ADGUARD_PORT=${VWARD_ADGUARD_PORT:-3000}
    case "$VWARD_ADGUARD_PORT" in ''|*[!0-9]*) vward_profile_error "invalid AdGuard Home port" ;; esac
    [ "$VWARD_ADGUARD_PORT" -ge 1 ] && [ "$VWARD_ADGUARD_PORT" -le 65535 ] ||
        vward_profile_error "AdGuard Home port must be 1..65535"

    [ -n "${VWARD_TUNNEL_DEVICE:-}" ] || VWARD_TUNNEL_DEVICE=$(vward_discover_tunnel_device)
    vward_valid_ifname "${VWARD_TUNNEL_DEVICE:-}" ||
        vward_profile_error "tunnel device is missing or ambiguous"
    [ -n "${VWARD_TUNNEL_INTERFACE:-}" ] || VWARD_TUNNEL_INTERFACE=$VWARD_TUNNEL_DEVICE
    vward_valid_ifname "$VWARD_TUNNEL_INTERFACE" || vward_profile_error "invalid tunnel interface"
    [ -z "${VWARD_WAN_INTERFACE:-}" ] || vward_valid_ifname "$VWARD_WAN_INTERFACE" ||
        vward_profile_error "invalid WAN interface"

    case "$VWARD_CONSOLE_PORT" in ''|*[!0-9]*) vward_profile_error "invalid Console port" ;; esac
    [ "$VWARD_CONSOLE_PORT" -ge 1024 ] && [ "$VWARD_CONSOLE_PORT" -le 65535 ] ||
        vward_profile_error "Console port must be 1024..65535"

    case "${VWARD_POLICY_GROUP:-}" in *[!A-Za-z0-9_.:-]*) vward_profile_error "invalid policy group" ;; esac

    export VWARD_RCI_BASE VWARD_CONSOLE_PORT VWARD_WAN_DEVICE VWARD_LAN_ADDRESS
    export VWARD_LAN_SUBNET VWARD_DNS_SERVER VWARD_TUNNEL_DEVICE
    export VWARD_PROBE_DNS
    export VWARD_ADGUARD_ADDRESS VWARD_ADGUARD_PORT
    export VWARD_TUNNEL_INTERFACE VWARD_POLICY_GROUP
    export VWARD_WAN_INTERFACE
}
