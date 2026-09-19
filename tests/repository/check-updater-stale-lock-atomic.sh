#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
COMMON="$ROOT/components/update-engine/vward-update-common.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT HUP INT TERM

fail() { echo "FAIL: $*" >&2; exit 1; }

VWARD_ROOT_PREFIX="$TMP/root"
VWARD_UPDATE_CONFIG="$TMP/update.conf"
VWARD_UPDATE_BOOT_ID="test-boot-id"
SELF_DIR="$ROOT/components/update-engine"
export VWARD_ROOT_PREFIX VWARD_UPDATE_CONFIG VWARD_UPDATE_BOOT_ID SELF_DIR
mkdir -p "$VWARD_ROOT_PREFIX/opt/var/run/vward"
: > "$VWARD_UPDATE_CONFIG"
. "$COMMON"

LOCK="$VU_RUN_DIR/updater.lock"
RECLAIM="$VU_RUN_DIR/updater.lock.reclaim"
RECOVERY="$VU_RUN_DIR/updater.lock.recovery"

mkdir "$RECOVERY"
printf 'boot-recovery\n' > "$RECOVERY/owner"
if vu_lock_acquire; then
    fail "acquire bypassed an active boot-recovery gate"
fi
[ ! -e "$LOCK" ] || fail "lock was published while boot recovery was active"
rm -f "$RECOVERY/owner"
rmdir "$RECOVERY"

TARGET="$TMP/external-lock"
mkdir "$TARGET"
printf '999999:1:vward-update\n' > "$TARGET/owner"
ln -s "$TARGET" "$LOCK"
if vu_lock_acquire; then
    fail "symlink lock was accepted"
fi
[ -L "$LOCK" ] || fail "symlink lock path was changed"
[ -f "$TARGET/owner" ] || fail "symlink target owner was modified"
rm -f "$LOCK"

# Special owner files must be rejected before a reader can block on them.
mkdir "$LOCK"
mkfifo "$LOCK/owner"
FIFO_RESULT="$TMP/fifo-result"
(
    if vu_lock_acquire; then
        printf 'accepted\n' > "$FIFO_RESULT"
    else
        printf 'rejected\n' > "$FIFO_RESULT"
    fi
) &
FIFO_PID=$!
sleep 1
if kill -0 "$FIFO_PID" 2>/dev/null; then
    kill "$FIFO_PID" 2>/dev/null || :
    wait "$FIFO_PID" 2>/dev/null || :
    fail "FIFO owner blocked lock acquisition"
fi
wait "$FIFO_PID"
[ "$(cat "$FIFO_RESULT" 2>/dev/null)" = rejected ] || fail "FIFO owner was accepted"
rm -f "$LOCK/owner"
rmdir "$LOCK"

mkdir "$RECLAIM"
printf 'test-reclaimer\n' > "$RECLAIM/owner"
if vu_lock_acquire; then
    fail "acquire bypassed an active reclaim gate"
fi
[ ! -e "$LOCK" ] || fail "lock was published while reclaim gate was active"
rm -f "$RECLAIM/owner"
rmdir "$RECLAIM"

mkdir "$LOCK"
printf '999999:1:vward-update\n' > "$LOCK/owner"

# Deterministic interleaving: after the stale token has been validated but
# before reclamation, a successor publishes a different live-looking token.
VWARD_TEST_UPDATER_SUCCESSOR_AFTER_STALE=1
export VWARD_TEST_UPDATER_SUCCESSOR_AFTER_STALE
if vu_lock_acquire; then
    fail "stale reclaimer stole a successor lock"
fi

EXPECTED="test-successor-owner"
[ -d "$LOCK" ] || fail "successor lock directory was removed"
[ "$(cat "$LOCK/owner" 2>/dev/null)" = "$EXPECTED" ] ||
    fail "successor ownership was not preserved"
[ "$VU_LOCK_OWNED" = 0 ] || fail "failed reclaimer reported ownership"

rm -f "$LOCK/owner"
rmdir "$LOCK"
mkdir "$LOCK"
printf '999999:1:vward-update\n' > "$LOCK/owner"
HOLD="$TMP/reclaim-hold"
RESULT="$TMP/reclaim-result"
RELEASE="$TMP/reclaim-release"
: > "$HOLD"
(
    VWARD_TEST_UPDATER_SUCCESSOR_AFTER_STALE=0
    VWARD_TEST_UPDATER_RECLAIM_HOLD="$HOLD"
    export VWARD_TEST_UPDATER_SUCCESSOR_AFTER_STALE VWARD_TEST_UPDATER_RECLAIM_HOLD
    if vu_lock_acquire; then
        printf 'acquired\n' > "$RESULT"
        while [ ! -e "$RELEASE" ]; do sleep 1; done
        vu_lock_release
    else
        printf 'failed\n' > "$RESULT"
    fi
) &
FIRST_PID=$!

WAITED=0
while [ ! -e "$HOLD.ready" ] && [ "$WAITED" -lt 5 ]; do sleep 1; WAITED=$((WAITED + 1)); done
[ -e "$HOLD.ready" ] || fail "first reclaimer did not acquire reclaim gate"
TOKEN_OK=1
grep -q '^test-boot-id:[1-9][0-9]*:[0-9][0-9]*:vward-update-reclaim$' "$RECLAIM/owner" || TOKEN_OK=0
if VWARD_TEST_UPDATER_SUCCESSOR_AFTER_STALE=0 vu_lock_acquire; then
    fail "second reclaimer entered through the reclaim gate"
fi
[ "$(cat "$LOCK/owner" 2>/dev/null)" = '999999:1:vward-update' ] ||
    fail "second reclaimer changed the stale lock"

rm -f "$HOLD"
WAITED=0
while [ ! -e "$RESULT" ] && [ "$WAITED" -lt 5 ]; do sleep 1; WAITED=$((WAITED + 1)); done
[ "$(cat "$RESULT" 2>/dev/null)" = acquired ] || fail "elected reclaimer did not acquire lock"
: > "$RELEASE"
wait "$FIRST_PID"
[ "$TOKEN_OK" -eq 1 ] || fail "reclaim owner token does not bind ownership to boot_id"
[ ! -e "$LOCK" ] || fail "elected owner did not release lock"
[ ! -e "$RECLAIM" ] || fail "reclaim gate remains after successful acquisition"

echo "UPDATER_STALE_LOCK_ATOMIC=PASS"
