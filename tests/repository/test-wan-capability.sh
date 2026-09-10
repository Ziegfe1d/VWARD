#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
CAPABILITY="$ROOT/components/wan-guardian/scripts/wan-capability.sh"
TMP="${TMPDIR:-/tmp}/vward-wan-capability-test.$$"
DISCOVERY="$TMP/discovery.sh"
CONFIG="$TMP/running-config"
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT INT TERM

fail()
{
    echo "FAIL: $*" >&2
    exit 1
}

cat > "$DISCOVERY" <<'EOF'
#!/bin/sh
case "${VWARD_TEST_SCENARIO:-dhcp}" in
    dhcp|static|missing)
        printf '%s\n' '{"schema":1,"provider":"vward-discovery","role":"wan-guard","state":"READY","interface":{"rci_id":"UplinkAlpha","linux_if":"wan0","type":"GigabitEthernet","via_rci_id":"","via_linux_if":""}}'
        ;;
    logical)
        printf '%s\n' '{"schema":1,"provider":"vward-discovery","role":"wan-guard","state":"READY","interface":{"rci_id":"PPPoEOffice","linux_if":"ppp0","type":"PPPoE","via_rci_id":"EthernetWAN","via_linux_if":"wan0"}}'
        ;;
    ambiguous)
        printf '%s\n' '{"schema":1,"provider":"vward-discovery","role":"wan-guard","state":"REQUIRES_SELECTION","candidate_count":2}'
        exit 4
        ;;
esac
EOF
chmod 0755 "$DISCOVERY"

run_capability()
{
    VWARD_DISCOVERY_BIN="$DISCOVERY" \
    VWARD_JQ="$(command -v jq)" \
    VWARD_RUNNING_CONFIG_FILE="$CONFIG" \
    VWARD_TEST_SCENARIO="$1" \
    sh "$CAPABILITY"
}

cat > "$CONFIG" <<'EOF'
interface UplinkAlpha
    description Example
    security-level public
    ip address dhcp
    ip dhcp client dns-routes
    up
!
EOF
OUT="$(run_capability dhcp)"
printf '%s\n' "$OUT" | jq -e '.state=="READY" and .addressing.mode=="dhcp" and .addressing.dhcp_renew==true and .recovery.interface_reconnect==true and .recovery.session_reconnect==false' >/dev/null ||
    fail "DHCP capability classification failed"

cat > "$CONFIG" <<'EOF'
interface UplinkAlpha
    description Static
    security-level public
    ip address 203.0.113.10 255.255.255.0
    up
!
EOF
OUT="$(run_capability static)"
printf '%s\n' "$OUT" | jq -e '.state=="READY" and .addressing.mode=="static" and .addressing.dhcp_renew==false' >/dev/null ||
    fail "static capability classification failed"

cat > "$CONFIG" <<'EOF'
interface PPPoEOffice
    description Office
    via EthernetWAN
    pppoe username secret-user
    pppoe password secret-password
    up
!
interface EthernetWAN
    ip address dhcp
    up
!
EOF
OUT="$(run_capability logical)"
printf '%s\n' "$OUT" | jq -e '.state=="READY" and .addressing.mode=="logical" and .addressing.dhcp_renew==false and .recovery.session_reconnect==true and .interface.via_rci_id=="EthernetWAN"' >/dev/null ||
    fail "logical capability classification failed"
printf '%s\n' "$OUT" | grep -Fq 'secret-user' && fail "username leaked from running-config"
printf '%s\n' "$OUT" | grep -Fq 'secret-password' && fail "password leaked from running-config"

cat > "$CONFIG" <<'EOF'
interface UplinkAlpha
    ip address dhcp
    up
!
EOF
OUT="$(run_capability ambiguous || true)"
printf '%s\n' "$OUT" | jq -e '.state=="UNAVAILABLE" and .reason=="discovery_REQUIRES_SELECTION"' >/dev/null ||
    fail "ambiguous WAN role must block capability discovery"

cat > "$CONFIG" <<'EOF'
interface AnotherWAN
    ip address dhcp
    up
!
EOF
OUT="$(run_capability missing || true)"
printf '%s\n' "$OUT" | jq -e '.state=="UNAVAILABLE" and .reason=="interface_block_not_found"' >/dev/null ||
    fail "missing interface block must fail safe"

for forbidden in \
    'ip dhcp client renew' \
    'interface $RCI_ID down' \
    'interface $RCI_ID up' \
    'system config-save' \
    'eval '
do
    if grep -Fq "$forbidden" "$CAPABILITY"; then
        fail "capability provider contains mutation token: $forbidden"
    fi
done

grep -Fq 'show running-config' "$CAPABILITY" || fail "capability provider must use read-only running-config"

echo "WAN_CAPABILITY_TESTS=PASS"
