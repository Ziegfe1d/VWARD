#!/bin/sh
# Updater simulations model a router where the shared runtime is installed:
# every optional component declares it as an install dependency.
seed_runtime() {
    jq -r '.components[] | select(.id == "runtime") | .runtime_targets[]' \
        "$REPO/config/components/component-registry.json" |
    while IFS= read -r target; do
        mkdir -p "$1$(dirname "$target")" || return 1
        [ -e "$1$target" ] || printf 'runtime placeholder\n' > "$1$target" || return 1
    done
}
