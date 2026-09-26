#!/bin/sh

# Stable launcher for updater self-updates. Slot selection is an atomic symlink swap.

set -u

ROOT_PREFIX=${VWARD_ROOT_PREFIX:-}
UPDATER_ROOT=${VWARD_UPDATER_ROOT:-${ROOT_PREFIX}/opt/share/vward/updater}
CURRENT=$UPDATER_ROOT/current

[ -x "$CURRENT/vward-update.sh" ] || {
    printf '%s\n' "Updater slot is unavailable: $CURRENT" >&2
    exit 30
}

exec "$CURRENT/vward-update.sh" "$@"
