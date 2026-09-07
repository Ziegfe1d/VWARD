#!/bin/sh

# Loader for VWARD Smart Updater shared primitives.
# The stable core is kept separate so focused hardening overrides can remain small and auditable.

if [ -n "${SELF_DIR:-}" ] && [ -r "$SELF_DIR/vward-update-common-base.sh" ]; then
    VU_COMMON_DIR=$SELF_DIR
elif [ -n "${1:-}" ]; then
    case "$1" in
        */vward-update-common.sh)
            VU_COMMON_DIR=${1%/*}
            ;;
        *)
            VU_COMMON_DIR=
            ;;
    esac
else
    VU_COMMON_DIR=
fi

[ -n "$VU_COMMON_DIR" ] && [ -r "$VU_COMMON_DIR/vward-update-common-base.sh" ] || {
    printf '%s\n' 'Cannot locate VWARD updater common library' >&2
    return 30 2>/dev/null || exit 30
}

. "$VU_COMMON_DIR/vward-update-common-base.sh"
. "$VU_COMMON_DIR/vward-update-hardening.sh"
