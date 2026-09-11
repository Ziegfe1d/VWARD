#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
ACTUATOR="$ROOT/components/wan-guardian/scripts/wan-recovery-actuator.sh"
TMP="${TMPDIR:-/tmp}/vward-wan-actuator-test.$$"
DISCOVERY="$TMP/discovery.sh"
CAPABILITY="$TMP/capability.sh"
NDMC="$TMP/ndmc"
NDMC_LOG="$TMP/ndmc.log"
NDMC_COUNT="$TMP/ndmc.count"
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

cat > "$NDMC" <<'EOF'
#!/bin/sh
printf 'LD_LIBRARY_PATH=%s|%s\n' "${LD_LIBRARY_PATH-UNSET}" "$*" >> "$VWARD_TEST_NDMC_LOG"
case "${VWARD_TEST_NDMC_MODE:-ok}" in
    fail-down)
        printf '%s\n' "$*" | grep -Fq ' down' && exit 1
        ;;
    fail-dhcp)
        printf '%s\n' "$*" | grep -Fq 'ip dhcp client renew' && exit 1
        ;;
    up-once-fail)
        if printf '%s\n' "$*" | grep -Fq ' up'; then
            count=0
            [ -r "$VWARD_TEST_NDMC_COUNT" ] && count=$(cat "$VWARD_TEST_NDMC_COUNT")
            count=$((count + 1))
            printf '%s\n' "$count" > "$VWARD_TEST_NDMC_COUNT"
            [ "$count" -eq 1 ] && exit 1
        fi
        ;;
esac
exit 0
EOF
chmod 0755 "$NDMC"

run_actuator()
{
    scenario="$1"
    action="$2"
    rci="$3"
    linux_if="$4"
    cap_mode="${5:-dhcp}"
    execution="${6:-0}"
    auth="${7:-0}"
    ndmc_mode="${8:-ok}"

    VWARD_DISCOVERY_BIN="$DISCOVERY" \
    VWARD_WAN_CAPABILITY_BIN="$CAPABILITY" \
    VWARD_JQ="$(command -v jq)" \
    VWARD_NDMC="$NDMC" \
    VWARD_WAN_RECOVERY_RECONNECT_PAUSE_SEC=0 \
    VWARD_WAN_RECOVERY_EXECUTION_ENABLED="$execution" \
    VWARD_WAN_RECOVERY_CONTROLLER_AUTH="$auth" \
    VWARD_TEST_SCENARIO="$scenario" \
    VWARD_TEST_CAP_MODE="$cap_mode" \
    VWARD_TEST_NDMC_MODE="$ndmc_mode" \
    VWARD_TEST_NDMC_LOG="$NDMC_LOG" \
    VWARD_TEST_NDMC_COUNT="$NDMC_COUNT" \
    sh "$ACTUATOR" "$action" "$rci" "$linux_if"
}

rm -f "$NDMC_LOG" "$NDMC_COUNT"
OUT="$(run_actuator physical INTERFACE_RECONNECT UplinkAlpha wan0)"
printf '%s\n' "$OUT" | grep -Fq 'RESULT=READY' || fail "physical reconnect was not accepted"
printf '%s\n' "$OUT" | grep -Fq 'MODE=dryrun' || fail "default mode must remain dry-run"
printf '%s\n' "$OUT" | grep -Fq 'EXECUTION_KIND=RCI_INTERFACE_RECONNECT' || fail "physical execution kind missing"
printf '%s\n' "$OUT" | grep -Fq 'EXECUTED=NO' || fail "default actuator must not execute"
[ ! -e "$NDMC_LOG" ] || fail "dry-run actuator invoked ndmc"

OUT="$(run_actuator logical SESSION_RECONNECT PPPoEOffice ppp0)"
printf '%s\n' "$OUT" | grep -Fq 'RESULT=READY' || fail "logical reconnect was not accepted"
printf '%s\n' "$OUT" | grep -Fq 'EXECUTION_KIND=RCI_SESSION_RECONNECT' || fail "logical execution kind missing"
printf '%s\n' "$OUT" | grep -Fq 'VIA_RCI_ID=EthernetWAN' || fail "logical via role missing"

OUT="$(run_actuator physical DHCP_RENEW UplinkAlpha wan0 dhcp)"
printf '%s\n' "$OUT" | grep -Fq 'RESULT=READY' || fail "DHCP renew was not accepted"
printf '%s\n' "$OUT" | grep -Fq 'EXECUTION_KIND=RCI_DHCP_RENEW' || fail "DHCP execution kind missing"
printf '%s\n' "$OUT" | grep -Fq 'CAPABILITY_STATE=READY' || fail "DHCP capability state missing"
printf '%s\n' "$OUT" | grep -Fq 'ADDRESSING_MODE=dhcp' || fail "DHCP addressing mode missing"

OUT="$(run_actuator physical DHCP_RENEW UplinkAlpha wan0 static)"
printf '%s\n' "$OUT" | grep -Fq 'RESULT=BLOCKED' || fail "static WAN DHCP renew must be blocked"
printf '%s\n' "$OUT" | grep -Fq 'REASON=addressing_not_dhcp' || fail "static WAN block reason missing"

OUT="$(run_actuator physical DHCP_RENEW UplinkAlpha wan0 wrong)"
printf '%s\n' "$OUT" | grep -Fq 'REASON=capability_ROLE_MISMATCH' || fail "capability role mismatch must block"

OUT="$(run_actuator physical INTERFACE_RECONNECT WrongRole wan0)"
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

# execution_enabled alone is insufficient: direct actuator execution must fail closed.
rm -f "$NDMC_LOG"
OUT="$(run_actuator physical INTERFACE_RECONNECT UplinkAlpha wan0 dhcp 1 0)"
printf '%s\n' "$OUT" | grep -Fq 'MODE=execute' || fail "execution mode not reported"
printf '%s\n' "$OUT" | grep -Fq 'REASON=controller_authorization_required' || fail "controller authorization gate missing"
[ ! -e "$NDMC_LOG" ] || fail "unauthorized actuator invoked ndmc"

# Authorized physical reconnect must use only the dynamically discovered RCI ID.
rm -f "$NDMC_LOG" "$NDMC_COUNT"
OUT="$(run_actuator physical INTERFACE_RECONNECT UplinkAlpha wan0 dhcp 1 1)"
printf '%s\n' "$OUT" | grep -Fq 'RESULT=EXECUTED' || fail "authorized physical reconnect did not execute"
printf '%s\n' "$OUT" | grep -Fq 'EXECUTED=YES' || fail "physical execution result missing"
[ "$(wc -l < "$NDMC_LOG" | tr -d ' ')" -eq 2 ] || fail "physical reconnect must issue exactly down/up"
grep -Fq 'LD_LIBRARY_PATH=|-c interface UplinkAlpha down' "$NDMC_LOG" || fail "physical down command mismatch or LD_LIBRARY_PATH not cleared"
grep -Fq 'LD_LIBRARY_PATH=|-c interface UplinkAlpha up' "$NDMC_LOG" || fail "physical up command mismatch"
grep -Fq 'system configuration save' "$NDMC_LOG" && fail "recovery must not persist configuration"

# Logical reconnect uses the logical RCI role, not its physical via interface.
rm -f "$NDMC_LOG" "$NDMC_COUNT"
OUT="$(run_actuator logical SESSION_RECONNECT PPPoEOffice ppp0 dhcp 1 1)"
printf '%s\n' "$OUT" | grep -Fq 'RESULT=EXECUTED' || fail "authorized logical reconnect did not execute"
grep -Fq -- '-c interface PPPoEOffice down' "$NDMC_LOG" || fail "logical down command mismatch"
grep -Fq -- '-c interface PPPoEOffice up' "$NDMC_LOG" || fail "logical up command mismatch"
grep -Fq 'EthernetWAN down' "$NDMC_LOG" && fail "logical reconnect must not bounce physical via"

# DHCP renew is one exact interface-scoped command and remains capability-gated.
rm -f "$NDMC_LOG" "$NDMC_COUNT"
OUT="$(run_actuator physical DHCP_RENEW UplinkAlpha wan0 dhcp 1 1)"
printf '%s\n' "$OUT" | grep -Fq 'RESULT=EXECUTED' || fail "authorized DHCP renew did not execute"
[ "$(wc -l < "$NDMC_LOG" | tr -d ' ')" -eq 1 ] || fail "DHCP renew must issue exactly one ndmc command"
grep -Fq -- '-c interface UplinkAlpha ip dhcp client renew' "$NDMC_LOG" || fail "DHCP renew command mismatch"

rm -f "$NDMC_LOG" "$NDMC_COUNT"
OUT="$(run_actuator physical DHCP_RENEW UplinkAlpha wan0 static 1 1)"
printf '%s\n' "$OUT" | grep -Fq 'REASON=addressing_not_dhcp' || fail "live static WAN must block DHCP renew"
[ ! -e "$NDMC_LOG" ] || fail "blocked static DHCP path invoked ndmc"

# If the first up fails, one best-effort up retry is allowed.
rm -f "$NDMC_LOG" "$NDMC_COUNT"
OUT="$(run_actuator physical INTERFACE_RECONNECT UplinkAlpha wan0 dhcp 1 1 up-once-fail)"
printf '%s\n' "$OUT" | grep -Fq 'RESULT=EXECUTED' || fail "up retry did not recover reconnect"
printf '%s\n' "$OUT" | grep -Fq 'RECOVERY_NOTE=up_retry_succeeded' || fail "up retry note missing"
[ "$(grep -Fc -- '-c interface UplinkAlpha up' "$NDMC_LOG")" -eq 2 ] || fail "exactly one up retry expected"

for forbidden in \
    'IFACE="ISP"' \
    'show/interface?name=ISP' \
    'eth3' \
    'COMMAND=' \
    'COMMAND_DOWN=' \
    'COMMAND_UP=' \
    'system configuration save'
do
    if grep -Fq "$forbidden" "$ACTUATOR"; then
        fail "actuator contains forbidden legacy/persistence token: $forbidden"
    fi
done

if grep -Eq '(^|[[:space:]])eval([[:space:]]|$)' "$ACTUATOR"; then
    fail "actuator must not use eval"
fi

grep -Fq 'VWARD_WAN_RECOVERY_EXECUTION_ENABLED' "$ACTUATOR" || fail "execution switch missing"
grep -Fq 'controller_authorization_required' "$ACTUATOR" || fail "controller authorization guard missing"
grep -Fq 'LD_LIBRARY_PATH= "$NDMC"' "$ACTUATOR" || fail "Entware-safe ndmc invocation missing"

echo "WAN_RECOVERY_ACTUATOR_TESTS=PASS"
