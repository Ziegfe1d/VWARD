#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
ACTUATOR="$ROOT/components/wan-guardian/scripts/wan-recovery-actuator.sh"
TMP="${TMPDIR:-/tmp}/vward-wan-actuator-test.$$"
DISCOVERY="$TMP/discovery.sh"
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT INT TERM

fail()
{
    echo "FAIL: $*" >&2
    exit 1
}

cat > "$DISCOVERY" <<'EOF'
#!/bin/sh
case "${VWARD_TEST_SCENARIO:-physical}" in
    physical)
        printf '%s\n' '{"schema":1,"provider":"vward-discovery","role":"wan-guard","state":"READY","interface":{"rci_id":"UplinkAlpha","linux_if":"wan0","type":"GigabitEthernet","via_rci_id":"","via_linux_if":""}}'
        ;;
    logical)
        printf '%s\n' '{"schema":1,"provider":"vward-discovery","role":"wan-guard","state":"READY","interface":{"rci_id":"PPPoEOffice","linux_if":"ppp0","type":"PPPoE","via_rci_id":"EthernetWAN","via_linux_if":"wan0"}}'
        ;;
    ambiguous)
        printf '%s\n' '{"schema":1,"provider":"vward-discovery","role":"wan-guard","state":"REQUIRES_SELECTION","candidate_count":2}'
        exit 4
        ;;
    invalid)
        printf '%s\n' 'not-json'
        ;;
esac
EOF
chmod 0755 "$DISCOVERY"

run_actuator()
{
    VWARD_DISCOVERY_BIN="$DISCOVERY" \
    VWARD_JQ="$(command -v jq)" \
    VWARD_TEST_SCENARIO="$1" \
    sh "$ACTUATOR" "$2" "$3" "$4"
}

OUT="$(run_actuator physical INTERFACE_RECONNECT UplinkAlpha wan0)"
printf '%s\n' "$OUT" | grep -Fq 'RESULT=READY' || fail "physical reconnect was not accepted"
printf '%s\n' "$OUT" | grep -Fq 'EXECUTION_KIND=RCI_INTERFACE_RECONNECT' || fail "physical execution kind missing"
printf '%s\n' "$OUT" | grep -Fq 'EXECUTED=NO' || fail "actuator must remain dry-run"

OUT="$(run_actuator logical SESSION_RECONNECT PPPoEOffice ppp0)"
printf '%s\n' "$OUT" | grep -Fq 'RESULT=READY' || fail "logical reconnect was not accepted"
printf '%s\n' "$OUT" | grep -Fq 'EXECUTION_KIND=RCI_SESSION_RECONNECT' || fail "logical execution kind missing"
printf '%s\n' "$OUT" | grep -Fq 'VIA_RCI_ID=EthernetWAN' || fail "logical via role missing"

OUT="$(run_actuator physical INTERFACE_RECONNECT WrongRole wan0)"
printf '%s\n' "$OUT" | grep -Fq 'RESULT=BLOCKED' || fail "role mismatch must be blocked"
printf '%s\n' "$OUT" | grep -Fq 'REASON=target_role_mismatch' || fail "role mismatch reason missing"

OUT="$(run_actuator physical INTERFACE_RECONNECT UplinkAlpha wrong0)"
printf '%s\n' "$OUT" | grep -Fq 'REASON=target_mapping_mismatch' || fail "mapping mismatch must be blocked"

OUT="$(run_actuator physical SESSION_RECONNECT UplinkAlpha wan0)"
printf '%s\n' "$OUT" | grep -Fq 'REASON=logical_uplink_required' || fail "session reconnect on physical WAN must be blocked"

OUT="$(run_actuator logical INTERFACE_RECONNECT PPPoEOffice ppp0)"
printf '%s\n' "$OUT" | grep -Fq 'REASON=physical_uplink_required' || fail "interface reconnect on logical WAN must be blocked"

OUT="$(run_actuator ambiguous INTERFACE_RECONNECT UplinkAlpha wan0)"
printf '%s\n' "$OUT" | grep -Fq 'REASON=discovery_REQUIRES_SELECTION' || fail "ambiguous discovery must be blocked"

OUT="$(run_actuator physical INTERFACE_RECONNECT 'bad;id' wan0)"
printf '%s\n' "$OUT" | grep -Fq 'REASON=invalid_expected_rci_id' || fail "unsafe RCI ID must be rejected"

OUT="$(run_actuator invalid INTERFACE_RECONNECT UplinkAlpha wan0)"
printf '%s\n' "$OUT" | grep -Fq 'REASON=discovery_invalid_result' || fail "invalid discovery result must be blocked"

if grep -Eq 'IFACE=["'"']?ISP|show/interface\?name=ISP|eth3|ip dhcp client renew|eval[[:space:]]|COMMAND(_DOWN|_UP)?=' "$ACTUATOR"; then
    fail "actuator contains legacy target hardcode or executable command string"
fi
if grep -Eq '(^|[^A-Za-z])ndmc([^A-Za-z]|$)' "$ACTUATOR"; then
    fail "dry-run actuator must not invoke or prepare ndmc"
fi

echo "WAN_RECOVERY_ACTUATOR_TESTS=PASS"
