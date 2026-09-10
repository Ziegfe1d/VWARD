#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
SCRIPT="$ROOT/components/wan-guardian/scripts/wan-recovery-plan.sh"
JQ_BIN="${JQ_BIN:-$(command -v jq)}"

TMP="${TMPDIR:-/tmp}/vward-wan-recovery-plan-test.$$"
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT INT TERM

fail()
{
    echo "FAIL: $*" >&2
    exit 1
}

cat > "$TMP/discovery.sh" <<'EOF'
#!/bin/sh
cat "$VWARD_TEST_DISCOVERY_JSON_FILE"
exit "${VWARD_TEST_DISCOVERY_RC:-0}"
EOF
chmod 0755 "$TMP/discovery.sh"

cat > "$TMP/capability.sh" <<'EOF'
#!/bin/sh
cat "$VWARD_TEST_CAPABILITY_JSON_FILE"
EOF
chmod 0755 "$TMP/capability.sh"

write_state()
{
    STATUS_VALUE="$1"
    CLASS_VALUE="$2"
    FAIL_VALUE="$3"
    RCI_VALUE="$4"
    IF_VALUE="$5"
    LAST_VALUE="${6:-1000}"

    cat > "$TMP/state" <<EOF
STATUS=$STATUS_VALUE
CLASS=$CLASS_VALUE
LAST_CHECK=$LAST_VALUE
FAIL_COUNT=$FAIL_VALUE
RCI_ID=$RCI_VALUE
LINUX_IF=$IF_VALUE
EOF
}

run_plan()
{
    VWARD_WAN_HEALTH_STATE="$TMP/state" \
    VWARD_DISCOVERY_BIN="$TMP/discovery.sh" \
    VWARD_WAN_CAPABILITY_BIN="$TMP/capability.sh" \
    VWARD_JQ="$JQ_BIN" \
    VWARD_NOW_EPOCH=1050 \
    VWARD_WAN_RECOVERY_MAX_STATE_AGE=120 \
    VWARD_WAN_RECOVERY_CONFIRM_FAILURES=3 \
    VWARD_TEST_DISCOVERY_JSON_FILE="$1" \
    VWARD_TEST_DISCOVERY_RC="${2:-0}" \
    VWARD_TEST_CAPABILITY_JSON_FILE="${3:-$TMP/dhcp-capability.json}" \
    sh "$SCRIPT"
}

value()
{
    printf '%s\n' "$1" | awk -F= -v k="$2" '$1==k {print substr($0,index($0,"=")+1); exit}'
}

cat > "$TMP/physical.json" <<'EOF'
{"schema":1,"provider":"vward-discovery","role":"wan-guard","state":"READY","selection":"single-candidate","interface":{"rci_id":"UplinkAlpha","linux_if":"eth9","mapping":"system-name","via_rci_id":"","via_linux_if":"","type":"GigabitEthernet"}}
EOF

cat > "$TMP/logical.json" <<'EOF'
{"schema":1,"provider":"vward-discovery","role":"wan-guard","state":"READY","selection":"configured","interface":{"rci_id":"InternetSession","linux_if":"ppp0","mapping":"system-name","via_rci_id":"PhysicalUplink","via_linux_if":"eth9","type":"PPPoE"}}
EOF

cat > "$TMP/ambiguous.json" <<'EOF'
{"schema":1,"provider":"vward-discovery","role":"wan-guard","state":"REQUIRES_SELECTION","candidate_count":2}
EOF

cat > "$TMP/dhcp-capability.json" <<'EOF'
{"schema":1,"provider":"wan-capability","role":"wan-guard","state":"READY","interface":{"rci_id":"UplinkAlpha","linux_if":"eth9"},"addressing":{"mode":"dhcp","evidence":"running_config_ip_address_dhcp","dhcp_renew":true},"recovery":{"interface_reconnect":true,"session_reconnect":false}}
EOF

cat > "$TMP/static-capability.json" <<'EOF'
{"schema":1,"provider":"wan-capability","role":"wan-guard","state":"READY","interface":{"rci_id":"UplinkAlpha","linux_if":"eth9"},"addressing":{"mode":"static","evidence":"running_config_static_ipv4","dhcp_renew":false},"recovery":{"interface_reconnect":true,"session_reconnect":false}}
EOF

cat > "$TMP/wrong-capability.json" <<'EOF'
{"schema":1,"provider":"wan-capability","role":"wan-guard","state":"READY","interface":{"rci_id":"OtherWAN","linux_if":"eth9"},"addressing":{"mode":"dhcp","dhcp_renew":true}}
EOF

write_state UP HEALTHY 0 UplinkAlpha eth9
OUT="$(run_plan "$TMP/physical.json")"
[ "$(value "$OUT" DECISION)" = "HOLD" ] || fail "healthy decision"
[ "$(value "$OUT" ACTION)" = "NONE" ] || fail "healthy action"
[ "$(value "$OUT" EXECUTED)" = "NO" ] || fail "planner must never execute"

write_state DOWN GATEWAY_FAILURE 2 UplinkAlpha eth9
OUT="$(run_plan "$TMP/physical.json")"
[ "$(value "$OUT" DECISION)" = "DEFER" ] || fail "confirmation gate"

write_state DOWN GATEWAY_FAILURE 3 UplinkAlpha eth9
OUT="$(run_plan "$TMP/physical.json")"
[ "$(value "$OUT" DECISION)" = "PLAN" ] || fail "physical failure plan"
[ "$(value "$OUT" ACTION)" = "INTERFACE_RECONNECT" ] || fail "physical failure action"

write_state DOWN ADDRESS_FAILURE 3 UplinkAlpha eth9
OUT="$(run_plan "$TMP/physical.json" 0 "$TMP/dhcp-capability.json")"
[ "$(value "$OUT" DECISION)" = "PLAN" ] || fail "DHCP address failure must plan"
[ "$(value "$OUT" ACTION)" = "DHCP_RENEW" ] || fail "DHCP address failure action"
[ "$(value "$OUT" CAPABILITY_STATE)" = "READY" ] || fail "DHCP capability state"
[ "$(value "$OUT" ADDRESSING_MODE)" = "dhcp" ] || fail "DHCP addressing mode"

OUT="$(run_plan "$TMP/physical.json" 0 "$TMP/static-capability.json")"
[ "$(value "$OUT" DECISION)" = "HOLD" ] || fail "static address failure must hold"
[ "$(value "$OUT" REASON)" = "addressing_not_dhcp" ] || fail "static address failure reason"

OUT="$(run_plan "$TMP/physical.json" 0 "$TMP/wrong-capability.json")"
[ "$(value "$OUT" DECISION)" = "BLOCKED" ] || fail "capability role mismatch must block"
[ "$(value "$OUT" REASON)" = "capability_ROLE_MISMATCH" ] || fail "capability mismatch reason"

write_state DOWN PHY_DOWN 9 UplinkAlpha eth9
OUT="$(run_plan "$TMP/physical.json")"
[ "$(value "$OUT" DECISION)" = "HOLD" ] || fail "physical carrier failure must hold"

write_state DEGRADED DNS_ONLY_FAILURE 9 UplinkAlpha eth9
OUT="$(run_plan "$TMP/physical.json")"
[ "$(value "$OUT" DECISION)" = "HOLD" ] || fail "DNS-only failure must hold"

write_state DOWN SESSION_FAILURE 3 InternetSession ppp0
OUT="$(run_plan "$TMP/logical.json")"
[ "$(value "$OUT" DECISION)" = "PLAN" ] || fail "logical session plan"
[ "$(value "$OUT" ACTION)" = "SESSION_RECONNECT" ] || fail "logical session action"
[ "$(value "$OUT" VIA_RCI_ID)" = "PhysicalUplink" ] || fail "logical via RCI"

write_state DOWN ADDRESS_FAILURE 3 InternetSession ppp0
OUT="$(run_plan "$TMP/logical.json")"
[ "$(value "$OUT" ACTION)" = "SESSION_RECONNECT" ] || fail "logical address failure must not DHCP renew"

write_state DOWN INTERNET_FAILURE 3 WrongUplink eth9
OUT="$(run_plan "$TMP/physical.json")"
[ "$(value "$OUT" DECISION)" = "BLOCKED" ] || fail "role mismatch must block"
[ "$(value "$OUT" REASON)" = "observer_role_mismatch" ] || fail "role mismatch reason"

write_state DOWN INTERNET_FAILURE 3 UplinkAlpha wrong9
OUT="$(run_plan "$TMP/physical.json")"
[ "$(value "$OUT" DECISION)" = "BLOCKED" ] || fail "mapping mismatch must block"

write_state DOWN INTERNET_FAILURE 3 UplinkAlpha eth9 800
OUT="$(run_plan "$TMP/physical.json")"
[ "$(value "$OUT" DECISION)" = "BLOCKED" ] || fail "stale observer must block"

write_state DOWN INTERNET_FAILURE 3 UplinkAlpha eth9
OUT="$(run_plan "$TMP/ambiguous.json" 4)"
[ "$(value "$OUT" DECISION)" = "BLOCKED" ] || fail "ambiguous discovery must block"

if grep -Eq 'ip dhcp client renew|interface [^" ]+ (down|up)|[Nn][Dd][Mm][Cc]' "$SCRIPT"; then
    fail "planner contains mutation command"
fi
if grep -Eq 'Wireguard[0-9]|nwg[0-9]|eth3|192\.168\.|show/interface\?name=ISP' "$SCRIPT"; then
    fail "planner contains installation-specific network hardcode"
fi
if grep -Eq 'test\(|match\(|sub\(' "$SCRIPT"; then
    fail "planner contains jq regex dependency"
fi

sh -n "$SCRIPT" || fail "planner shell syntax"

echo "WAN_RECOVERY_PLAN_TESTS=PASS"
