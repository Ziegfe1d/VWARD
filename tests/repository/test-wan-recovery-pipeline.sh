#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
PLANNER="$ROOT/components/wan-guardian/scripts/wan-recovery-plan.sh"
ACTUATOR="$ROOT/components/wan-guardian/scripts/wan-recovery-actuator.sh"
TMP="${TMPDIR:-/tmp}/vward-wan-pipeline-test.$$"
DISCOVERY="$TMP/discovery.sh"
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
    VWARD_JQ="$(command -v jq)" \
    VWARD_NOW_EPOCH=1000 \
    VWARD_TEST_SCENARIO="$1" \
    sh "$PLANNER"
}

run_actuator()
{
    VWARD_DISCOVERY_BIN="$DISCOVERY" \
    VWARD_JQ="$(command -v jq)" \
    VWARD_TEST_SCENARIO="$1" \
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

# TOCTOU guard: the role changes after planning, before actuation.
ACT="$(run_actuator replacement "$ACTION" "$RCI_ID" "$LINUX_IF")"
[ "$(value "$ACT" RESULT)" = BLOCKED ] || fail "changed WAN role must block actuation"
[ "$(value "$ACT" REASON)" = target_role_mismatch ] || fail "changed WAN role reason mismatch"

# The pipeline contract must stay typed, not shell-command based.
for forbidden in 'COMMAND=' 'COMMAND_DOWN=' 'COMMAND_UP='; do
    if printf '%s\n%s\n' "$PLAN" "$ACT" | grep -Fq "$forbidden"; then
        fail "pipeline exposed executable command text"
    fi
done

echo "WAN_RECOVERY_PIPELINE_TESTS=PASS"
