#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
SCRIPT="$ROOT/components/runtime-supervision/scripts/vward-discovery.sh"
JQ_BIN="${JQ_BIN:-$(command -v jq)}"

TMP="${TMPDIR:-/tmp}/vward-discovery-test.$$"
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT INT TERM

fail()
{
    echo "FAIL: $*" >&2
    exit 1
}

run_discovery()
{
    VWARD_JQ="$JQ_BIN" \
    VWARD_DISCOVERY_INTERFACES_FILE="$1" \
    VWARD_DISCOVERY_IP_ADDR_FILE="$2" \
    VWARD_DISCOVERY_CONFIG="$3" \
    VWARD_DISCOVERY_SYSTEM_NAMES_FILE="${5:-}" \
    "$SCRIPT" "$4"
}

cat > "$TMP/ip.txt" <<'EOF'
7: nwg7: <POINTOPOINT,UP,LOWER_UP> mtu 1420 qdisc noqueue state UNKNOWN
    inet 10.8.7.2/32 scope global nwg7
8: eth9: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP
    inet 100.64.10.20/24 scope global eth9
EOF

cat > "$TMP/none.json" <<'EOF'
{
  "ISP": {"type":"GigabitEthernet","address":"100.64.10.20"}
}
EOF

OUT="$(run_discovery "$TMP/none.json" "$TMP/ip.txt" "$TMP/missing.conf" wireguard)"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.count')" = 0 ] ||
    fail "zero WireGuard inventory"

cat > "$TMP/one.json" <<'EOF'
{
  "ISP": {"type":"GigabitEthernet","address":"100.64.10.20"},
  "VpnAlpha": {
    "type":"Wireguard",
    "description":"Test tunnel",
    "index":7,
    "address":"10.8.7.2",
    "link":"up",
    "connected":"yes",
    "state":"up"
  }
}
EOF

OUT="$(run_discovery "$TMP/one.json" "$TMP/ip.txt" "$TMP/missing.conf" wireguard)"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.count')" = 1 ] ||
    fail "arbitrary WireGuard ID not discovered"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.interfaces[0].rci_id')" = "VpnAlpha" ] ||
    fail "RCI ID mismatch"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.interfaces[0].linux_if')" = "nwg7" ] ||
    fail "Linux interface mapping mismatch"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.interfaces[0].mapping')" = "address" ] ||
    fail "mapping source mismatch"

cat > "$TMP/system-names.txt" <<'EOF'
VpnAlpha nwg42
GigabitEthernet1 eth3
PPPoE0 ppp0
WAN_A eth4
WAN_B eth5
EOF

OUT="$(run_discovery "$TMP/one.json" "$TMP/ip.txt" "$TMP/missing.conf" wireguard "$TMP/system-names.txt")"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.interfaces[0].linux_if')" = "nwg42" ] ||
    fail "system-name must be preferred over address mapping"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.interfaces[0].mapping')" = "system-name" ] ||
    fail "system-name mapping source"

OUT="$(run_discovery "$TMP/one.json" "$TMP/ip.txt" "$TMP/missing.conf" tunnel-guard)"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.state')" = "READY" ] ||
    fail "single-candidate role selection"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.selection')" = "single-candidate" ] ||
    fail "single-candidate selection label"

cat > "$TMP/two.json" <<'EOF'
{
  "VpnAlpha": {
    "type":"Wireguard",
    "address":"10.8.7.2",
    "link":"up",
    "connected":"yes",
    "state":"up"
  },
  "OfficeTunnel": {
    "type":"Wireguard",
    "address":"10.9.0.2",
    "link":"up",
    "connected":"yes",
    "state":"up"
  }
}
EOF

set +e
OUT="$(run_discovery "$TMP/two.json" "$TMP/ip.txt" "$TMP/missing.conf" tunnel-guard)"
RC=$?
set -e
[ "$RC" -eq 4 ] || fail "multiple candidates must require selection"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.state')" = "REQUIRES_SELECTION" ] ||
    fail "multiple candidate state"

cat > "$TMP/selected.conf" <<'EOF'
tunnel_guard_rci_id=OfficeTunnel
EOF

OUT="$(run_discovery "$TMP/two.json" "$TMP/ip.txt" "$TMP/selected.conf" tunnel-guard)"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.state')" = "READY" ] ||
    fail "configured role selection"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.selection')" = "configured" ] ||
    fail "configured selection label"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.interface.rci_id')" = "OfficeTunnel" ] ||
    fail "configured RCI ID"

cat > "$TMP/stale.conf" <<'EOF'
tunnel_guard_rci_id=DeletedTunnel
EOF

set +e
OUT="$(run_discovery "$TMP/two.json" "$TMP/ip.txt" "$TMP/stale.conf" tunnel-guard)"
RC=$?
set -e
[ "$RC" -eq 4 ] || fail "stale mapping must fail closed"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.state')" = "STALE_MAPPING" ] ||
    fail "stale mapping state"

cat > "$TMP/wan-one.json" <<'EOF'
{
  "Home": {
    "type":"Bridge",
    "interface-name":"Home",
    "global":true,
    "defaultgw":false,
    "security-level":"private",
    "address":"192.0.2.1"
  },
  "GigabitEthernet1": {
    "type":"GigabitEthernet",
    "interface-name":"PrimaryWAN",
    "description":"Broadband connection",
    "global":true,
    "defaultgw":true,
    "priority":700,
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

OUT="$(run_discovery "$TMP/wan-one.json" "$TMP/ip.txt" "$TMP/missing.conf" wan "$TMP/system-names.txt")"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.count')" = 1 ] ||
    fail "WAN inventory must exclude misc tunnel default routes"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.interfaces[0].rci_id')" = "GigabitEthernet1" ] ||
    fail "WAN RCI ID mismatch"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.interfaces[0].linux_if')" = "eth3" ] ||
    fail "WAN system-name mapping"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.interfaces[0].mapping')" = "system-name" ] ||
    fail "WAN mapping source"

OUT="$(run_discovery "$TMP/wan-one.json" "$TMP/ip.txt" "$TMP/missing.conf" wan-guard "$TMP/system-names.txt")"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.state')" = "READY" ] ||
    fail "single WAN role selection"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.selection')" = "single-candidate" ] ||
    fail "single WAN selection label"

cat > "$TMP/wan-pppoe.json" <<'EOF'
{
  "GigabitEthernet1": {
    "type":"GigabitEthernet",
    "global":true,
    "defaultgw":false,
    "security-level":"public",
    "link":"up",
    "state":"up"
  },
  "PPPoE0": {
    "type":"PPPoE",
    "interface-name":"PPPoE0",
    "global":true,
    "defaultgw":true,
    "priority":1000,
    "security-level":"public",
    "via":"GigabitEthernet1",
    "address":"198.51.100.20",
    "link":"up",
    "connected":"yes",
    "state":"up"
  }
}
EOF

OUT="$(run_discovery "$TMP/wan-pppoe.json" "$TMP/ip.txt" "$TMP/missing.conf" wan "$TMP/system-names.txt")"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.interfaces[0].rci_id')" = "PPPoE0" ] ||
    fail "PPPoE WAN discovery"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.interfaces[0].linux_if')" = "ppp0" ] ||
    fail "PPPoE system interface"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.interfaces[0].via_rci_id')" = "GigabitEthernet1" ] ||
    fail "PPPoE underlying RCI interface"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.interfaces[0].via_linux_if')" = "eth3" ] ||
    fail "PPPoE underlying Linux interface"

cat > "$TMP/wan-two.json" <<'EOF'
{
  "WAN_A": {
    "type":"GigabitEthernet",
    "global":true,
    "defaultgw":true,
    "security-level":"public",
    "address":"198.51.100.10"
  },
  "WAN_B": {
    "type":"UsbLte",
    "global":true,
    "defaultgw":true,
    "security-level":"public",
    "address":"203.0.113.10"
  }
}
EOF

set +e
OUT="$(run_discovery "$TMP/wan-two.json" "$TMP/ip.txt" "$TMP/missing.conf" wan-guard "$TMP/system-names.txt")"
RC=$?
set -e
[ "$RC" -eq 4 ] || fail "multiple WAN candidates must require selection"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.state')" = "REQUIRES_SELECTION" ] ||
    fail "multiple WAN candidate state"

cat > "$TMP/wan-selected.conf" <<'EOF'
wan_guard_rci_id=WAN_B
EOF

OUT="$(run_discovery "$TMP/wan-two.json" "$TMP/ip.txt" "$TMP/wan-selected.conf" wan-guard "$TMP/system-names.txt")"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.state')" = "READY" ] ||
    fail "configured WAN role selection"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.interface.rci_id')" = "WAN_B" ] ||
    fail "configured WAN RCI ID"

cat > "$TMP/wan-down.json" <<'EOF'
{
  "WAN_A": {
    "type":"GigabitEthernet",
    "global":true,
    "defaultgw":true,
    "security-level":"public",
    "address":"198.51.100.10"
  },
  "WAN_B": {
    "type":"UsbLte",
    "global":true,
    "defaultgw":false,
    "security-level":"public",
    "link":"down",
    "connected":"no",
    "state":"up"
  }
}
EOF

OUT="$(run_discovery "$TMP/wan-down.json" "$TMP/ip.txt" "$TMP/wan-selected.conf" wan-guard "$TMP/system-names.txt")"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.state')" = "READY" ] ||
    fail "configured WAN must remain selectable while default route is down"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.interface.defaultgw')" = "false" ] ||
    fail "configured down WAN state must be preserved"

cat > "$TMP/wan-stale.conf" <<'EOF'
wan_guard_rci_id=DeletedWAN
EOF

set +e
OUT="$(run_discovery "$TMP/wan-two.json" "$TMP/ip.txt" "$TMP/wan-stale.conf" wan-guard "$TMP/system-names.txt")"
RC=$?
set -e
[ "$RC" -eq 4 ] || fail "stale WAN mapping must fail closed"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.state')" = "STALE_MAPPING" ] ||
    fail "stale WAN mapping state"

cat > "$TMP/wan-invalid.conf" <<'EOF'
wan_guard_rci_id=Home
EOF

set +e
OUT="$(run_discovery "$TMP/wan-one.json" "$TMP/ip.txt" "$TMP/wan-invalid.conf" wan-guard "$TMP/system-names.txt")"
RC=$?
set -e
[ "$RC" -eq 4 ] || fail "private interface WAN mapping must fail closed"
[ "$(printf '%s\n' "$OUT" | "$JQ_BIN" -r '.state')" = "INVALID_MAPPING" ] ||
    fail "invalid WAN mapping state"

if grep -Eq 'test\(|match\(|sub\(' "$SCRIPT"; then
    fail "jq regex dependency detected"
fi

if grep -Eq 'Wireguard[0-9]|nwg[0-9]|192\.168\.|domain-list[0-9]|WAN_IF="|WG_IF="' "$SCRIPT"; then
    fail "installation-specific hardcode detected"
fi

sh -n "$SCRIPT" || fail "discovery shell syntax"

echo "DISCOVERY_TESTS=PASS"