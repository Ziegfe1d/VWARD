#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
SCRIPT="$ROOT/components/runtime-supervision/scripts/vward-discovery.sh"
JQ_BIN="${JQ_BIN:-$(command -v jq)}"

TMP="${TMPDIR:-/tmp}/vward-discovery-snapshot-test.$$"
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT INT TERM

fail()
{
    echo "FAIL: $*" >&2
    exit 1
}

cat > "$TMP/interfaces.json" <<'EOF'
{
  "VpnAlpha": {
    "type":"Wireguard",
    "description":"Primary tunnel",
    "address":"10.8.7.2",
    "link":"up",
    "connected":"yes",
    "state":"up"
  },
  "GigabitEthernet1": {
    "type":"GigabitEthernet",
    "interface-name":"Broadband",
    "description":"Internet uplink",
    "global":true,
    "defaultgw":true,
    "security-level":"public",
    "address":"100.64.10.20",
    "link":"up",
    "connected":"yes",
    "state":"up"
  },
  "VpnDefault": {
    "type":"OpenVPN",
    "role":["misc"],
    "global":true,
    "defaultgw":true,
    "security-level":"public",
    "address":"10.20.30.40",
    "link":"up",
    "connected":"yes",
    "state":"up"
  }
}
EOF

cat > "$TMP/ip.txt" <<'EOF'
7: nwg7: <POINTOPOINT,UP,LOWER_UP> mtu 1420 qdisc noqueue state UNKNOWN
    inet 10.8.7.2/32 scope global nwg7
8: eth3: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP
    inet 100.64.10.20/24 scope global eth3
EOF

cat > "$TMP/system-names.txt" <<'EOF'
VpnAlpha nwg7
GigabitEthernet1 eth3
VpnDefault tun0
EOF

OUT="$(
    VWARD_JQ="$JQ_BIN" \
    VWARD_DISCOVERY_INTERFACES_FILE="$TMP/interfaces.json" \
    VWARD_DISCOVERY_IP_ADDR_FILE="$TMP/ip.txt" \
    VWARD_DISCOVERY_CONFIG="$TMP/missing.conf" \
    VWARD_DISCOVERY_SYSTEM_NAMES_FILE="$TMP/system-names.txt" \
    "$SCRIPT" snapshot
)"

printf '%s\n' "$OUT" | "$JQ_BIN" -e '
    .schema == 1 and
    .provider == "vward-discovery" and
    .kind == "snapshot" and
    .wireguard.count == 1 and
    .wireguard.interfaces[0].rci_id == "VpnAlpha" and
    .wireguard.interfaces[0].linux_if == "nwg7" and
    .wan.count == 1 and
    .wan.interfaces[0].rci_id == "GigabitEthernet1" and
    .wan.interfaces[0].linux_if == "eth3" and
    .roles.tunnel_guard.state == "READY" and
    .roles.tunnel_guard.interface.rci_id == "VpnAlpha" and
    .roles.wan_guard.state == "READY" and
    .roles.wan_guard.interface.rci_id == "GigabitEthernet1" and
    ([.wan.interfaces[].rci_id] | index("VpnDefault")) == null
' >/dev/null || fail "unified snapshot contract"

echo "DISCOVERY_SNAPSHOT_TEST=PASS"