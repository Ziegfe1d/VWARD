#!/bin/sh
set -u

CONF=${VWARD_WIFI_CLIENT_GUARD_CONF:-/opt/etc/vward/wifi-client-guard.conf}
ENABLED=0

[ ! -r "$CONF" ] || . "$CONF"
[ "$ENABLED" = 1 ] || exit 0

/opt/bin/vward-wifi-client-monitor.sh --once || exit $?
/opt/bin/vward-wifi-client-analyze.sh --once
