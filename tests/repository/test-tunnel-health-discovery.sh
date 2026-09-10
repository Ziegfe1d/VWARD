#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
HEALTH="$ROOT/components/wireguard-protection/scripts/wg-health-watch.sh"
JQ_BIN="${JQ_BIN:-$(command -v jq)}"

TMP="${TMPDIR:-/tmp}/vward-tunnel-health-test.$$"
mkdir -p "$TMP/bin" "$TMP/sys/vpnlocal"
trap 'rm -rf "$TMP"' EXIT INT TERM

fail()
{
    echo "FAIL: $*" >&2
    exit 1
}

cat > "$TMP/bin/discovery" <<'EOF'
#!/bin/sh
case "${FAKE_DISCOVERY_MODE:-ready}" in
    ready)
        echo '{"schema":1,"provider":"vward-discovery","role":"tunnel-guard","state":"READY","selection":"single-candidate","interface":{"rci_id":"VpnAlpha","linux_if":"vpnlocal","mapping":"address"}}'
        exit 0
        ;;
    multi)
        echo '{"schema":1,"provider":"vward-discovery","role":"tunnel-guard","state":"REQUIRES_SELECTION","candidate_count":2}'
        exit 4
        ;;
    stale)
        echo '{"schema":1,"provider":"vward-discovery","role":"tunnel-guard","state":"STALE_MAPPING","configured_rci_id":"OldTunnel","candidate_count":1}'
        exit 4
        ;;
esac
EOF

cat > "$TMP/bin/curl" <<'EOF'
#!/bin/sh
printf 'curl:%s\n' "$*" >> "$FAKE_CALLS"
exit 0
EOF

cat > "$TMP/bin/ndmc" <<'EOF'
#!/bin/sh
printf 'ndmc:%s\n' "$*" >> "$FAKE_CALLS"
cat <<'OUT'
state: up
link: up
online: yes
last-handshake: 10
OUT
EOF

cat > "$TMP/bin/ip" <<'EOF'
#!/bin/sh
printf 'ip:%s\n' "$*" >> "$FAKE_CALLS"
case "$*" in
    '-4 addr show dev vpnlocal')
        echo '    inet 10.8.7.2/32 scope global vpnlocal'
        ;;
    'link show vpnlocal')
        echo '7: vpnlocal: <POINTOPOINT,UP,LOWER_UP> mtu 1420 state UNKNOWN'
        ;;
esac
EOF

chmod +x "$TMP/bin/discovery" "$TMP/bin/curl" "$TMP/bin/ndmc" "$TMP/bin/ip"
printf '1\n' > "$TMP/sys/vpnlocal/carrier"

run_health()
{
    CASE="$1"
    MODE="$2"
    CASEDIR="$TMP/$CASE"
    mkdir -p "$CASEDIR/state"
    : > "$CASEDIR/calls"

    FAKE_DISCOVERY_MODE="$MODE" \
    FAKE_CALLS="$CASEDIR/calls" \
    VWARD_WG_HEALTH_DIR="$CASEDIR/state" \
    VWARD_WG_HEALTH_LOG="$CASEDIR/health.log" \
    VWARD_WG_HEALTH_LOCK="$CASEDIR/lock" \
    VWARD_DISCOVERY_BIN="$TMP/bin/discovery" \
    VWARD_JQ="$JQ_BIN" \
    VWARD_CURL="$TMP/bin/curl" \
    VWARD_NDMC="$TMP/bin/ndmc" \
    VWARD_IP="$TMP/bin/ip" \
    VWARD_SYS_CLASS_NET="$TMP/sys" \
    "$HEALTH" > "$CASEDIR/out"
}

run_health ready ready
READY_STATE="$TMP/ready/state/state"

grep -q '^STATUS=UP$' "$READY_STATE" || fail "discovered healthy tunnel is not UP"
grep -q '^DISCOVERY_STATE=READY$' "$READY_STATE" || fail "READY discovery state missing"
grep -q '^RCI_ID=VpnAlpha$' "$READY_STATE" || fail "RCI role ID missing"
grep -q '^LINUX_IF=vpnlocal$' "$READY_STATE" || fail "Linux role interface missing"
grep -q 'ndmc:-c show interface VpnAlpha' "$TMP/ready/calls" || fail "RCI query did not use discovered ID"
grep -q 'curl:.*--interface vpnlocal' "$TMP/ready/calls" || fail "probe did not use discovered Linux interface"

run_health multi multi
MULTI_STATE="$TMP/multi/state/state"

grep -q '^STATUS=UNKNOWN$' "$MULTI_STATE" || fail "ambiguous tunnel must remain UNKNOWN"
grep -q '^DISCOVERY_STATE=REQUIRES_SELECTION$' "$MULTI_STATE" || fail "ambiguous state missing"
[ ! -s "$TMP/multi/calls" ] || fail "ambiguous discovery must not probe or query guessed interfaces"

run_health stale stale
STALE_STATE="$TMP/stale/state/state"

grep -q '^STATUS=UNKNOWN$' "$STALE_STATE" || fail "stale mapping must remain UNKNOWN"
grep -q '^DISCOVERY_STATE=STALE_MAPPING$' "$STALE_STATE" || fail "stale state missing"
[ ! -s "$TMP/stale/calls" ] || fail "stale mapping must not probe or query guessed interfaces"

if grep -Eq 'Wireguard[0-9]|nwg[0-9]|WG_IF="[[:alnum:]_]|WAN_IF="[[:alnum:]_]' "$HEALTH"; then
    fail "Tunnel health still contains installation-specific interface hardcode"
fi

if grep -Eq 'interface .* (up|down)' "$HEALTH"; then
    fail "read-only health watcher must not mutate tunnel state"
fi

sh -n "$HEALTH" || fail "health watcher shell syntax"

echo "TUNNEL_HEALTH_DISCOVERY_TESTS=PASS"
