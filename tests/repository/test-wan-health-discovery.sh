#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
SCRIPT="$ROOT/components/wan-guardian/scripts/wan-health-watch.sh"
JQ_BIN="${JQ_BIN:-$(command -v jq)}"

TMP="${TMPDIR:-/tmp}/vward-wan-health-test.$$"
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT INT TERM

fail()
{
    echo "FAIL: $*" >&2
    exit 1
}

mkdir -p "$TMP/sys/eth9"
echo 1 > "$TMP/sys/eth9/carrier"

cat > "$TMP/discovery.sh" <<'EOF'
#!/bin/sh
cat "$VWARD_TEST_DISCOVERY_JSON_FILE"
exit "${VWARD_TEST_DISCOVERY_RC:-0}"
EOF
chmod 0755 "$TMP/discovery.sh"

cat > "$TMP/ping.sh" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "$VWARD_TEST_PING_LOG"
exit "${VWARD_TEST_PING_RC:-0}"
EOF
chmod 0755 "$TMP/ping.sh"

cat > "$TMP/internet.json" <<'EOF'
{
  "gateway": {"address": "100.64.10.1"},
  "gateway-accessible": true,
  "dns-accessible": true,
  "internet": true,
  "reliable": true
}
EOF

run_watch()
{
    VWARD_WAN_HEALTH_DIR="$TMP/state" \
    VWARD_WAN_HEALTH_LOG="$TMP/wan-health.log" \
    VWARD_WAN_HEALTH_LOCK="$TMP/wan-health.lock" \
    VWARD_JQ="$JQ_BIN" \
    VWARD_DISCOVERY_BIN="$TMP/discovery.sh" \
    VWARD_WAN_HEALTH_INET_FILE="$TMP/internet.json" \
    VWARD_PING="$TMP/ping.sh" \
    VWARD_SYS_CLASS_NET="$TMP/sys" \
    VWARD_TEST_DISCOVERY_JSON_FILE="$1" \
    VWARD_TEST_DISCOVERY_RC="${2:-0}" \
    VWARD_TEST_PING_LOG="$TMP/ping.log" \
    "$SCRIPT" >/dev/null
}

cat > "$TMP/wan.json" <<'EOF'
{
  "schema":1,
  "provider":"vward-discovery",
  "role":"wan-guard",
  "state":"READY",
  "selection":"single-candidate",
  "interface":{
    "rci_id":"UplinkAlpha",
    "linux_if":"eth9",
    "mapping":"system-name",
    "via_rci_id":"",
    "via_linux_if":"",
    "via_mapping":"",
    "type":"GigabitEthernet",
    "address":"100.64.10.20",
    "link":"up",
    "connected":"yes",
    "state":"up",
    "defaultgw":true
  }
}
EOF

: > "$TMP/ping.log"
run_watch "$TMP/wan.json"

STATE="$TMP/state/state"
[ "$(awk -F= '$1=="STATUS"{print $2}' "$STATE")" = "UP" ] ||
    fail "healthy WAN status"
[ "$(awk -F= '$1=="CLASS"{print $2}' "$STATE")" = "HEALTHY" ] ||
    fail "healthy WAN class"
[ "$(awk -F= '$1=="RCI_ID"{print $2}' "$STATE")" = "UplinkAlpha" ] ||
    fail "arbitrary WAN RCI ID"
[ "$(awk -F= '$1=="PATH_IF"{print $2}' "$STATE")" = "eth9" ] ||
    fail "WAN path interface"
[ "$(awk -F= '$1=="PHYSICAL_IF"{print $2}' "$STATE")" = "eth9" ] ||
    fail "WAN physical interface"
grep -Fq -- '-I eth9 1.0.0.1' "$TMP/ping.log" ||
    fail "probe not bound to discovered WAN interface"
grep -Fq -- '-I eth9 77.88.8.1' "$TMP/ping.log" ||
    fail "second probe not bound to discovered WAN interface"

cat > "$TMP/ambiguous.json" <<'EOF'
{
  "schema":1,
  "provider":"vward-discovery",
  "role":"wan-guard",
  "state":"REQUIRES_SELECTION",
  "candidate_count":2
}
EOF

: > "$TMP/ping.log"
run_watch "$TMP/ambiguous.json" 4

[ "$(awk -F= '$1=="STATUS"{print $2}' "$STATE")" = "UNKNOWN" ] ||
    fail "ambiguous WAN must be unknown"
[ "$(awk -F= '$1=="CLASS"{print $2}' "$STATE")" = "DISCOVERY_REQUIRES_SELECTION" ] ||
    fail "ambiguous WAN class"
[ ! -s "$TMP/ping.log" ] ||
    fail "ambiguous WAN must not probe a guessed interface"

cat > "$TMP/pppoe.json" <<'EOF'
{
  "schema":1,
  "provider":"vward-discovery",
  "role":"wan-guard",
  "state":"READY",
  "selection":"configured",
  "interface":{
    "rci_id":"InternetSession",
    "linux_if":"ppp0",
    "mapping":"system-name",
    "via_rci_id":"PhysicalUplink",
    "via_linux_if":"eth9",
    "via_mapping":"system-name",
    "type":"PPPoE",
    "address":"203.0.113.2",
    "link":"up",
    "connected":"yes",
    "state":"up",
    "defaultgw":true
  }
}
EOF

: > "$TMP/ping.log"
run_watch "$TMP/pppoe.json"

[ "$(awk -F= '$1=="STATUS"{print $2}' "$STATE")" = "UP" ] ||
    fail "PPPoE WAN status"
[ "$(awk -F= '$1=="PATH_IF"{print $2}' "$STATE")" = "ppp0" ] ||
    fail "PPPoE logical path interface"
[ "$(awk -F= '$1=="PHYSICAL_IF"{print $2}' "$STATE")" = "eth9" ] ||
    fail "PPPoE physical interface"
grep -Fq -- '-I ppp0 1.0.0.1' "$TMP/ping.log" ||
    fail "PPPoE probe must use logical WAN path"

echo 0 > "$TMP/sys/eth9/carrier"
: > "$TMP/ping.log"
run_watch "$TMP/wan.json"

[ "$(awk -F= '$1=="CLASS"{print $2}' "$STATE")" = "PHY_DOWN" ] ||
    fail "physical carrier loss"
[ ! -s "$TMP/ping.log" ] ||
    fail "physical down state must not run external probes"

cat > "$TMP/unresolved.json" <<'EOF'
{
  "schema":1,
  "provider":"vward-discovery",
  "role":"wan-guard",
  "state":"READY",
  "selection":"single-candidate",
  "interface":{
    "rci_id":"UplinkNoMap",
    "linux_if":"",
    "mapping":"unresolved",
    "type":"GigabitEthernet",
    "address":"",
    "link":"up",
    "connected":"yes",
    "state":"up",
    "defaultgw":false
  }
}
EOF

: > "$TMP/ping.log"
run_watch "$TMP/unresolved.json"

[ "$(awk -F= '$1=="CLASS"{print $2}' "$STATE")" = "MAPPING_UNRESOLVED" ] ||
    fail "unresolved Linux mapping"
[ ! -s "$TMP/ping.log" ] ||
    fail "unresolved WAN mapping must not run unbound probes"

if grep -Eq 'test\(|match\(|sub\(' "$SCRIPT"; then
    fail "jq regex dependency detected"
fi

if grep -Eq 'Wireguard[0-9]|nwg[0-9]|eth3|192\.168\.' "$SCRIPT"; then
    fail "installation-specific interface hardcode detected"
fi

if grep -Eq 'ip dhcp client renew|interface [^"]+ (down|up)|[Nn][Dd][Mm][Cc]' "$SCRIPT"; then
    fail "read-only WAN observer contains mutation command"
fi

sh -n "$SCRIPT" || fail "WAN observer shell syntax"

echo "WAN_HEALTH_DISCOVERY_TESTS=PASS"
