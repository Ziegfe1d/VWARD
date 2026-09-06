#!/opt/bin/sh

VERSION="0.1-dryrun"
MODE="dryrun"

NDMC="/bin/ndmc"
IFACE="ISP"

case "$1" in

    dhcp-renew)
        echo "VERSION=$VERSION"
        echo "MODE=$MODE"
        echo "REQUEST=DHCP_RENEW"
        echo "COMMAND=$NDMC -c \"interface $IFACE ip dhcp client renew\""
        echo "EXECUTED=NO"
        ;;

    wan-bounce)
        echo "VERSION=$VERSION"
        echo "MODE=$MODE"
        echo "REQUEST=WAN_BOUNCE"
        echo "COMMAND_DOWN=$NDMC -c \"interface $IFACE down\""
        echo "WAIT_SEC=5"
        echo "COMMAND_UP=$NDMC -c \"interface $IFACE up\""
        echo "EXECUTED=NO"
        ;;

    *)
        echo "ERROR=INVALID_REQUEST"
        echo "ALLOWED=dhcp-renew|wan-bounce"
        exit 2
        ;;
esac

exit 0
