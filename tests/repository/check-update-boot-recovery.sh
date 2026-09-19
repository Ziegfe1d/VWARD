#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd -P)
HOOK=$ROOT/components/runtime/init.d/S89vward-update-recovery
TMP=${TMPDIR:-/tmp}/vward-boot-recovery-test.$$
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/state" "$TMP/log"
mkdir -p "$TMP/run"
printf 'current-boot\n' > "$TMP/boot-id"

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
    VWARD_UPDATE_RUN_DIR="$TMP/run" \
    VWARD_UPDATE_BOOT_ID_FILE="$TMP/boot-id" \
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

# Only the boot hook may recover an abandoned reclaim gate. A token from a
# previous boot is unambiguously orphaned and must be atomically quarantined.
rm -f "$TMP/state/boot-recovery.failed"
printf 'phase=IDLE\n' > "$TMP/state/journal.state"
mkdir "$TMP/run/updater.lock.reclaim"
printf 'previous-boot:999999:1:vward-update-reclaim\n' > "$TMP/run/updater.lock.reclaim/owner"
run_hook
[ ! -e "$TMP/run/updater.lock.reclaim" ] || { echo "FAIL: old-boot reclaim gate was not recovered" >&2; exit 1; }
find "$TMP/run" -maxdepth 1 -name 'updater.lock.reclaim.quarantine.*' | grep -q . && {
    echo "FAIL: reclaim quarantine was not cleaned" >&2
    exit 1
}

# A same-boot token may still belong to a live recovery path. Fail closed.
mkdir "$TMP/run/updater.lock.reclaim"
printf 'current-boot:999999:1:vward-update-reclaim\n' > "$TMP/run/updater.lock.reclaim/owner"
set +e
run_hook >/dev/null 2>&1
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAIL: same-boot reclaim gate was accepted" >&2; exit 1; }
[ -d "$TMP/run/updater.lock.reclaim" ] || { echo "FAIL: same-boot reclaim gate was changed" >&2; exit 1; }
rm -f "$TMP/run/updater.lock.reclaim/owner"
rmdir "$TMP/run/updater.lock.reclaim"

# Malformed and symlinked recovery state must never be deleted by boot recovery.
mkdir "$TMP/run/updater.lock.reclaim"
printf 'malformed\n' > "$TMP/run/updater.lock.reclaim/owner"
set +e
run_hook >/dev/null 2>&1
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAIL: malformed reclaim token was accepted" >&2; exit 1; }
[ -f "$TMP/run/updater.lock.reclaim/owner" ] || { echo "FAIL: malformed reclaim state was changed" >&2; exit 1; }
rm -f "$TMP/run/updater.lock.reclaim/owner"
rmdir "$TMP/run/updater.lock.reclaim"

mkdir "$TMP/reclaim-target"
printf 'previous-boot:999999:1:vward-update-reclaim\n' > "$TMP/reclaim-target/owner"
ln -s "$TMP/reclaim-target" "$TMP/run/updater.lock.reclaim"
set +e
run_hook >/dev/null 2>&1
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAIL: symlinked reclaim gate was accepted" >&2; exit 1; }
[ -L "$TMP/run/updater.lock.reclaim" ] || { echo "FAIL: symlinked reclaim gate was changed" >&2; exit 1; }
[ -f "$TMP/reclaim-target/owner" ] || { echo "FAIL: symlink target was changed" >&2; exit 1; }
rm -f "$TMP/run/updater.lock.reclaim"

reject_owner()
{
    label=$1
    owner_source=$2
    mkdir "$TMP/run/updater.lock.reclaim"
    cp "$owner_source" "$TMP/run/updater.lock.reclaim/owner"
    before=$(sha256sum "$TMP/run/updater.lock.reclaim/owner" | awk '{print $1}')
    set +e
    run_hook >/dev/null 2>&1
    rc=$?
    set -e
    [ "$rc" -ne 0 ] || { echo "FAIL: $label owner was accepted" >&2; exit 1; }
    after=$(sha256sum "$TMP/run/updater.lock.reclaim/owner" | awk '{print $1}')
    [ "$before" = "$after" ] || { echo "FAIL: $label owner was changed" >&2; exit 1; }
    rm -f "$TMP/run/updater.lock.reclaim/owner"
    rmdir "$TMP/run/updater.lock.reclaim"
}

printf 'previous-boot:123:1:vward-update-reclaim\nforeign-data\n' > "$TMP/multiline-owner"
reject_owner multiline "$TMP/multiline-owner"
printf 'previous-boot:123:1:vward-update-reclaim:\n' > "$TMP/trailing-owner"
reject_owner trailing-delimiter "$TMP/trailing-owner"
printf 'VERSIO?:123:1:vward-update-reclaim\n' > "$TMP/glob-owner"
reject_owner glob "$TMP/glob-owner"

mkdir "$TMP/run/updater.lock.reclaim"
printf 'previous-boot:123:1:vward-update-reclaim\n' > "$TMP/run/updater.lock.reclaim/owner"
: > "$TMP/run/updater.lock.reclaim/foreign"
set +e
run_hook >/dev/null 2>&1
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAIL: additional reclaim content was accepted" >&2; exit 1; }
[ -f "$TMP/run/updater.lock.reclaim/owner" ] && [ -f "$TMP/run/updater.lock.reclaim/foreign" ] || {
    echo "FAIL: additional reclaim content was changed" >&2
    exit 1
}
rm -f "$TMP/run/updater.lock.reclaim/owner" "$TMP/run/updater.lock.reclaim/foreign"
rmdir "$TMP/run/updater.lock.reclaim"

# Concurrent recovery must be serialized, and an updater must remain blocked
# while the old gate is temporarily under quarantine.
mkdir "$TMP/run/updater.lock.reclaim"
printf 'previous-boot:123:1:vward-update-reclaim\n' > "$TMP/run/updater.lock.reclaim/owner"
HOLD="$TMP/recovery-hold"
: > "$HOLD"
VWARD_TEST_RECOVERY_HOLD="$HOLD" run_hook > "$TMP/recovery-first.out" 2>&1 &
recovery_pid=$!
waited=0
while [ ! -e "$HOLD.ready" ] && [ "$waited" -lt 5 ]; do sleep 1; waited=$((waited + 1)); done
[ -e "$HOLD.ready" ] || { echo "FAIL: recovery did not enter serialized section" >&2; exit 1; }
[ -d "$TMP/run/updater.lock.recovery" ] || { echo "FAIL: recovery serialization gate is missing" >&2; exit 1; }
set +e
run_hook >/dev/null 2>&1
second_rc=$?
set -e
[ "$second_rc" -ne 0 ] || { echo "FAIL: concurrent recovery entered serialized section" >&2; exit 1; }
rm -f "$HOLD"
wait "$recovery_pid"
[ ! -e "$TMP/run/updater.lock.recovery" ] || { echo "FAIL: recovery serialization gate remains" >&2; exit 1; }

# A failure after atomic quarantine must restore the exact original gate.
mkdir "$TMP/run/updater.lock.reclaim"
printf 'previous-boot:123:1:vward-update-reclaim\n' > "$TMP/run/updater.lock.reclaim/owner"
before=$(sha256sum "$TMP/run/updater.lock.reclaim/owner" | awk '{print $1}')
set +e
VWARD_TEST_RECOVERY_FAIL_AFTER_QUARANTINE=1 run_hook >/dev/null 2>&1
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAIL: injected quarantine failure was accepted" >&2; exit 1; }
after=$(sha256sum "$TMP/run/updater.lock.reclaim/owner" | awk '{print $1}')
[ "$before" = "$after" ] || { echo "FAIL: quarantine rollback did not restore owner" >&2; exit 1; }
[ ! -e "$TMP/run/updater.lock.recovery" ] || { echo "FAIL: safe quarantine rollback left recovery gate" >&2; exit 1; }

echo "UPDATE_BOOT_RECOVERY=PASS"
