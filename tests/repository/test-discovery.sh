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

if grep -Eq 'test\(|match\(|sub\(' "$SCRIPT"; then
    fail "jq regex dependency detected"
fi

if grep -Eq 'Wireguard[0-9]|nwg[0-9]|192\.168\.|domain-list[0-9]|WAN_IF="|WG_IF="' "$SCRIPT"; then
    fail "installation-specific hardcode detected"
fi

sh -n "$SCRIPT" || fail "discovery shell syntax"

echo "DISCOVERY_TESTS=PASS"
