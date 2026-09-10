#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
ACTUATOR="$ROOT/components/wan-guardian/scripts/wan-recovery-actuator.sh"
TMP="${TMPDIR:-/tmp}/vward-wan-actuator-test.$$"
DISCOVERY="$TMP/discovery.sh"
CAPABILITY="$TMP/capability.sh"
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

cat > "$CAPABILITY" <<'EOF'
#!/bin/sh
case "${VWARD_TEST_CAP_MODE:-dhcp}" in
    dhcp)
        printf '%s\n' '{"schema":1,"provider":"wan-capability","role":"wan-guard","state":"READY","interface":{"rci_id":"UplinkAlpha","linux_if":"wan0"},"addressing":{"mode":"dhcp","evidence":"running_config_ip_address_dhcp","dhcp_renew":true}}'
        ;;
    static)
        printf '%s\n' '{"schema":1,"provider":"wan-capability","role":"wan-guard","state":"READY","interface":{"rci_id":"UplinkAlpha","linux_if":"wan0"},"addressing":{"mode":"static","evidence":"running_config_static_ipv4","dhcp_renew":false}}'
        ;;
    wrong)
        printf '%s\n' '{"schema":1,"provider":"wan-capability","role":"wan-guard","state":"READY","interface":{"rci_id":"OtherWAN","linux_if":"wan0"},"addressing":{"mode":"dhcp","dhcp_renew":true}}'
        ;;
esac
EOF
chmod 0755 "$CAPABILITY"

run_actuator()
{
    VWARD_DISCOVERY_BIN="$DISCOVERY" \
    VWARD_WAN_CAPABILITY_BIN="$CAPABILITY" \
    VWARD_JQ="$(command -v jq)" \
    VWARD_TEST_SCENARIO="$1" \
    VWARD_TEST_CAP_MODE="${5:-dhcp}" \
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

OUT="$(run_actuator physical DHCP_RENEW UplinkAlpha wan0 dhcp)"
printf '%s\n' "$OUT" | grep -Fq 'RESULT=READY' || fail "DHCP renew was not accepted"
printf '%s\n' "$OUT" | grep -Fq 'EXECUTION_KIND=RCI_DHCP_RENEW' || fail "DHCP execution kind missing"
printf '%s\n' "$OUT" | grep -Fq 'CAPABILITY_STATE=READY' || fail "DHCP capability state missing"
printf '%s\n' "$OUT" | grep -Fq 'ADDRESSING_MODE=dhcp' || fail "DHCP addressing mode missing"
printf '%s\n' "$OUT" | grep -Fq 'EXECUTED=NO' || fail "DHCP actuator must remain dry-run"

OUT="$(run_actuator physical DHCP_RENEW UplinkAlpha wan0 static)"
printf '%s\n' "$OUT" | grep -Fq 'RESULT=BLOCKED' || fail "static WAN DHCP renew must be blocked"
printf '%s\n' "$OUT" | grep -Fq 'REASON=addressing_not_dhcp' || fail "static WAN block reason missing"

OUT="$(run_actuator physical DHCP_RENEW UplinkAlpha wan0 wrong)"
printf '%s\n' "$OUT" | grep -Fq 'REASON=capability_ROLE_MISMATCH' || fail "capability role mismatch must block"

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

for forbidden in \
    'IFACE="ISP"' \
    'show/interface?name=ISP' \
    'eth3' \
    'ip dhcp client renew' \
    'COMMAND=' \
    'COMMAND_DOWN=' \
    'COMMAND_UP='
do
    if grep -Fq "$forbidden" "$ACTUATOR"; then
        fail "actuator contains forbidden legacy token: $forbidden"
    fi
done

if grep -Eq '(^|[[:space:]])eval([[:space:]]|$)' "$ACTUATOR"; then
    fail "actuator must not use eval"
fi
if grep -Eq '(^|[^A-Za-z])ndmc([^A-Za-z]|$)' "$ACTUATOR"; then
    fail "dry-run actuator must not invoke or prepare ndmc"
fi

echo "WAN_RECOVERY_ACTUATOR_TESTS=PASS"
