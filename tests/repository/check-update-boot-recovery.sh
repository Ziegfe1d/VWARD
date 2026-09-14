#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
HOOK=$ROOT/components/runtime/init.d/S89vward-update-recovery
TMP=${TMPDIR:-/tmp}/vward-boot-recovery-test.$$
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/state" "$TMP/log"

cat > "$TMP/updater" <<'EOF'
#!/bin/sh
printf '%s\n' "$1" >> "$VWARD_TEST_CALLS"
exit "${VWARD_TEST_RC:-0}"
EOF
chmod 0755 "$TMP/updater"

run_hook()
{
    VWARD_UPDATER="$TMP/updater" \
    VWARD_UPDATE_STATE_DIR="$TMP/state" \
    VWARD_UPDATE_JOURNAL="$TMP/state/journal.state" \
    VWARD_UPDATE_RECOVERY_FAILED="$TMP/state/boot-recovery.failed" \
    VWARD_UPDATE_RECOVERY_LOG="$TMP/log/recovery.log" \
    VWARD_TEST_CALLS="$TMP/calls" \
    VWARD_TEST_RC="${1:-0}" \
    "$HOOK" start
}

printf 'phase=IDLE\n' > "$TMP/state/journal.state"
run_hook
[ ! -e "$TMP/calls" ] || { echo "FAIL: idle boot invoked recovery" >&2; exit 1; }

printf 'phase=INSTALLING\n' > "$TMP/state/journal.state"
run_hook
[ "$(sed -n '1p' "$TMP/calls")" = --recover ] || { echo "FAIL: interrupted boot did not invoke recovery" >&2; exit 1; }
[ ! -e "$TMP/state/boot-recovery.failed" ] || { echo "FAIL: successful recovery left failure marker" >&2; exit 1; }

: > "$TMP/calls"
printf 'phase=ROLLING_BACK\n' > "$TMP/state/journal.state"
set +e
run_hook 42 >/dev/null 2>&1
rc=$?
set -e
[ "$rc" -eq 42 ] || { echo "FAIL: recovery failure return code was lost" >&2; exit 1; }
grep -q '^phase=ROLLING_BACK$' "$TMP/state/boot-recovery.failed" || { echo "FAIL: recovery failure was not persisted" >&2; exit 1; }
grep -q '^rc=42$' "$TMP/state/boot-recovery.failed" || { echo "FAIL: recovery failure code was not persisted" >&2; exit 1; }

echo "UPDATE_BOOT_RECOVERY=PASS"
