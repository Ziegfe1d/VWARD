#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
PLANNER="$ROOT/components/wan-guardian/scripts/wan-recovery-plan.sh"
ACTUATOR="$ROOT/components/wan-guardian/scripts/wan-recovery-actuator.sh"
TMP="${TMPDIR:-/tmp}/vward-wan-pipeline-test.$$"
DISCOVERY="$TMP/discovery.sh"
CAPABILITY="$TMP/capability.sh"
STATE="$TMP/state"
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
    replacement)
        printf '%s\n' '{"schema":1,"provider":"vward-discovery","role":"wan-guard","state":"READY","interface":{"rci_id":"ReplacementWAN","linux_if":"wan9","type":"GigabitEthernet","via_rci_id":"","via_linux_if":""}}'
        ;;
esac
EOF
chmod 0755 "$DISCOVERY"

cat > "$CAPABILITY" <<'EOF'
#!/bin/sh
case "${VWARD_TEST_CAP_MODE:-dhcp}" in
    dhcp)
        printf '%s\n' '{"schema":1,"provider":"wan-capability","role":"wan-guard","state":"READY","interface":{"rci_id":"UplinkAlpha","linux_if":"wan0"},"addressing":{"mode":"dhcp","evidence":"running_config_ip_address_dhcp","dhcp_renew":true},"recovery":{"interface_reconnect":true,"session_reconnect":false}}'
        ;;
    static)
        printf '%s\n' '{"schema":1,"provider":"wan-capability","role":"wan-guard","state":"READY","interface":{"rci_id":"UplinkAlpha","linux_if":"wan0"},"addressing":{"mode":"static","evidence":"running_config_static_ipv4","dhcp_renew":false},"recovery":{"interface_reconnect":true,"session_reconnect":false}}'
        ;;
esac
EOF
chmod 0755 "$CAPABILITY"

value()
{
    printf '%s\n' "$1" | awk -F= -v k="$2" '$1==k {print substr($0,index($0,"=")+1); exit}'
}

write_state()
{
    rci="$1"
    linux_if="$2"
    class="$3"
    cat > "$STATE" <<EOF
STATUS=DOWN
CLASS=$class
FAIL_COUNT=3
LAST_CHECK=1000
RCI_ID=$rci
LINUX_IF=$linux_if
EOF
}

run_planner()
{
    VWARD_WAN_HEALTH_STATE="$STATE" \
    VWARD_DISCOVERY_BIN="$DISCOVERY" \
    VWARD_WAN_CAPABILITY_BIN="$CAPABILITY" \
    VWARD_JQ="$(command -v jq)" \
    VWARD_NOW_EPOCH=1000 \
    VWARD_TEST_SCENARIO="$1" \
    VWARD_TEST_CAP_MODE="${2:-dhcp}" \
    sh "$PLANNER"
}

run_actuator()
{
    VWARD_DISCOVERY_BIN="$DISCOVERY" \
    VWARD_WAN_CAPABILITY_BIN="$CAPABILITY" \
    VWARD_JQ="$(command -v jq)" \
    VWARD_TEST_SCENARIO="$1" \
    VWARD_TEST_CAP_MODE="${5:-dhcp}" \
    sh "$ACTUATOR" "$2" "$3" "$4"
}

write_state UplinkAlpha wan0 INTERNET_FAILURE
PLAN="$(run_planner physical)"
[ "$(value "$PLAN" DECISION)" = PLAN ] || fail "physical planner did not produce PLAN"
ACTION="$(value "$PLAN" ACTION)"
RCI_ID="$(value "$PLAN" TARGET_RCI_ID)"
LINUX_IF="$(value "$PLAN" TARGET_LINUX_IF)"
[ "$ACTION" = INTERFACE_RECONNECT ] || fail "physical planner action mismatch"
ACT="$(run_actuator physical "$ACTION" "$RCI_ID" "$LINUX_IF")"
[ "$(value "$ACT" RESULT)" = READY ] || fail "physical actuator rejected planner output"
[ "$(value "$ACT" EXECUTION_KIND)" = RCI_INTERFACE_RECONNECT ] || fail "physical execution kind mismatch"
[ "$(value "$ACT" EXECUTED)" = NO ] || fail "physical pipeline executed a mutation"

write_state PPPoEOffice ppp0 INTERNET_FAILURE
PLAN="$(run_planner logical)"
[ "$(value "$PLAN" DECISION)" = PLAN ] || fail "logical planner did not produce PLAN"
ACTION="$(value "$PLAN" ACTION)"
RCI_ID="$(value "$PLAN" TARGET_RCI_ID)"
LINUX_IF="$(value "$PLAN" TARGET_LINUX_IF)"
[ "$ACTION" = SESSION_RECONNECT ] || fail "logical planner action mismatch"
ACT="$(run_actuator logical "$ACTION" "$RCI_ID" "$LINUX_IF")"
[ "$(value "$ACT" RESULT)" = READY ] || fail "logical actuator rejected planner output"
[ "$(value "$ACT" EXECUTION_KIND)" = RCI_SESSION_RECONNECT ] || fail "logical execution kind mismatch"
[ "$(value "$ACT" EXECUTED)" = NO ] || fail "logical pipeline executed a mutation"

write_state UplinkAlpha wan0 ADDRESS_FAILURE
PLAN="$(run_planner physical dhcp)"
[ "$(value "$PLAN" DECISION)" = PLAN ] || fail "DHCP planner did not produce PLAN"
ACTION="$(value "$PLAN" ACTION)"
RCI_ID="$(value "$PLAN" TARGET_RCI_ID)"
LINUX_IF="$(value "$PLAN" TARGET_LINUX_IF)"
[ "$ACTION" = DHCP_RENEW ] || fail "DHCP planner action mismatch"
ACT="$(run_actuator physical "$ACTION" "$RCI_ID" "$LINUX_IF" dhcp)"
[ "$(value "$ACT" RESULT)" = READY ] || fail "DHCP actuator rejected planner output"
[ "$(value "$ACT" EXECUTION_KIND)" = RCI_DHCP_RENEW ] || fail "DHCP execution kind mismatch"
[ "$(value "$ACT" EXECUTED)" = NO ] || fail "DHCP pipeline executed a mutation"

# Capability TOCTOU: addressing changed after planning.
ACT="$(run_actuator physical "$ACTION" "$RCI_ID" "$LINUX_IF" static)"
[ "$(value "$ACT" RESULT)" = BLOCKED ] || fail "DHCP action must block after capability change"
[ "$(value "$ACT" REASON)" = addressing_not_dhcp ] || fail "DHCP capability change reason mismatch"

# Role TOCTOU: WAN role changed after planning.
ACT="$(run_actuator replacement INTERFACE_RECONNECT UplinkAlpha wan0)"
[ "$(value "$ACT" RESULT)" = BLOCKED ] || fail "changed WAN role must block actuation"
[ "$(value "$ACT" REASON)" = target_role_mismatch ] || fail "changed WAN role reason mismatch"

for forbidden in 'COMMAND=' 'COMMAND_DOWN=' 'COMMAND_UP='; do
    if printf '%s\n%s\n' "$PLAN" "$ACT" | grep -Fq "$forbidden"; then
        fail "pipeline exposed executable command text"
    fi
done

echo "WAN_RECOVERY_PIPELINE_TESTS=PASS"
