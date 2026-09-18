#!/bin/sh

# Two-phase admission protocol shared by runtime mutators and the updater.
VWARD_ADMISSION_OWNED=${VWARD_ADMISSION_OWNED:-0}
VWARD_ADMISSION_SLOT=${VWARD_ADMISSION_SLOT:-}

vward_admission_pid_start() {
    va_pid=${1:-$$}
    case "$va_pid" in ''|*[!0-9]*) return 1 ;; esac
    [ -r "/proc/$va_pid/stat" ] || return 1
    sed 's/^.*) //' "/proc/$va_pid/stat" 2>/dev/null | awk 'NF>=20 {print $20; exit}'
}

vward_admission_leave() {
    [ "${VWARD_ADMISSION_OWNED:-0}" = 1 ] || return 0
    va_slot=${VWARD_ADMISSION_SLOT:-}
    [ -n "$va_slot" ] && [ -d "$va_slot" ] && [ ! -L "$va_slot" ] || return 1
    va_owner=$(cat "$va_slot/pid" 2>/dev/null) || return 1
    va_saved_start=$(cat "$va_slot/pid_start" 2>/dev/null) || return 1
    va_own_start=$(vward_admission_pid_start $$ 2>/dev/null) || return 1
    [ "$va_owner" = "$$" ] && [ "$va_saved_start" = "$va_own_start" ] || return 1
    rm -f "$va_slot/pid" "$va_slot/pid_start" "$va_slot/component" 2>/dev/null || return 1
    rmdir "$va_slot" 2>/dev/null || return 1
    VWARD_ADMISSION_OWNED=0
    VWARD_ADMISSION_SLOT=
}

vward_admission_enter() {
    va_component=${1:-runtime}
    case "$va_component" in ''|*[!A-Za-z0-9_.-]*) return 64 ;; esac
    va_prefix=${VWARD_ROOT_PREFIX:-}
    va_request="$va_prefix/tmp/vward-update-requested"
    va_barrier="$va_prefix/tmp/vward-update.lock"
    va_active="$va_prefix/tmp/vward-runtime-active"
    [ ! -e "$va_request" ] && [ ! -L "$va_request" ] &&
        [ ! -e "$va_barrier" ] && [ ! -L "$va_barrier" ] || return 75
    [ ! -L "$va_active" ] || return 1
    if [ ! -e "$va_active" ]; then
        (umask 077; mkdir "$va_active") 2>/dev/null || return 1
    fi
    [ -d "$va_active" ] || return 1
    va_active_meta=$(stat -c '%u %a' "$va_active" 2>/dev/null) || return 1
    va_owner_uid=${VWARD_ADMISSION_OWNER_UID:-$(id -u)}
    [ "$va_active_meta" = "$va_owner_uid 700" ] || return 1
    va_start=$(vward_admission_pid_start $$ 2>/dev/null) || return 1
    va_slot="$va_active/$va_component.$$.$va_start"
    (umask 077; mkdir "$va_slot") 2>/dev/null || return 1
    if ! printf '%s\n' "$$" > "$va_slot/pid" ||
       ! printf '%s\n' "$va_start" > "$va_slot/pid_start" ||
       ! printf '%s\n' "$va_component" > "$va_slot/component"; then
        rm -f "$va_slot/pid" "$va_slot/pid_start" "$va_slot/component" 2>/dev/null
        rmdir "$va_slot" 2>/dev/null
        return 1
    fi
    chmod 0600 "$va_slot/pid" "$va_slot/pid_start" "$va_slot/component" 2>/dev/null || {
        rm -f "$va_slot/pid" "$va_slot/pid_start" "$va_slot/component" 2>/dev/null
        rmdir "$va_slot" 2>/dev/null
        return 1
    }
    VWARD_ADMISSION_SLOT=$va_slot
    VWARD_ADMISSION_OWNED=1
    [ "${VWARD_ADMISSION_TEST_REQUEST_AFTER_REGISTER:-0}" != 1 ] || printf 'test-request\n' > "$va_request"
    if [ -e "$va_request" ] || [ -L "$va_request" ] || [ -e "$va_barrier" ] || [ -L "$va_barrier" ]; then
        vward_admission_leave || return 1
        return 75
    fi
    return 0
}
