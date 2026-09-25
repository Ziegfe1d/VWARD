#!/bin/sh

# Two-phase admission protocol shared by runtime mutators and the updater.
VWARD_ADMISSION_OWNED=${VWARD_ADMISSION_OWNED:-0}
VWARD_ADMISSION_SLOT=${VWARD_ADMISSION_SLOT:-}
# Component switch: a disabled component keeps its files, but its entry points
# do nothing while <id>.disabled exists here (written by the Console).
VWARD_COMPONENT_STATE=${VWARD_COMPONENT_STATE:-/opt/etc/vward/components}

vward_component_enabled() {
    case "${1:-}" in ''|*[!a-z0-9-]*) return 0 ;; esac
    [ ! -e "$VWARD_COMPONENT_STATE/$1.disabled" ]
}

# vward_component_gate ID [RC]: leave quietly when the component is disabled.
# Scheduled jobs exit 0; manual tools pass a non-zero RC.
vward_component_gate() {
    vward_component_enabled "$1" && return 0
    echo "COMPONENT_DISABLED=$1"
    exit "${2:-0}"
}

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
    # Keenetic's BusyBox stat has no -c, so owner and mode come from ls.
    va_active_meta=$(ls -ldn "$va_active" 2>/dev/null | awk '{sub(/[.+]$/, "", $1); print $3, $1}')
    va_owner_uid=${VWARD_ADMISSION_OWNER_UID:-$(id -u)}
    [ "$va_active_meta" = "$va_owner_uid drwx------" ] || return 1
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

# ---------- Lock folders ----------
# Every lock a VWARD job or the updater waits for.  The updater starts nothing
# while one of them exists, and a lock kept on the USB drive outlives a power
# cut: vward_locks_sweep (at boot and hourly) removes those whose owner is gone.
VWARD_LOCKS="/tmp/vward-route-reconciler-maint.lock /tmp/vward-route-engine.lock /tmp/vward-policy-sync.lock
/tmp/vward-policy-reconcile.lock /tmp/vward-tunnel-health-watch.lock /tmp/vward-tunnel-guard-guard.lock
/tmp/vward-wan-guard.lock /tmp/vward-wan-guard.lock.d /tmp/vward-route.lock /tmp/vward-route-discovery.lock
/tmp/vward-cron-supervisor.lock /tmp/vward-route-change.lock /opt/var/lib/vward/policy-sync/lock
/opt/var/lib/vward/route-engine/classifier.lock /opt/var/lib/vward/ads-privacy-guard/scan.lock
/opt/var/lib/vward/ads-privacy-guard/sources-update.lock /opt/var/lib/vward/ads-privacy-guard/publish.lock
/opt/var/lib/vward/ads-privacy-guard/jobs/worker.lock"

# vward_lock_stale DIR: the lock's owner is gone - its process is dead or the
# id now belongs to another process (pid_start differs), or the lock has had no
# owner id for an hour.
# Shell builtins only: the hourly sweep looks at every lock.
vward_lock_stale() {
    vl_dir=$1
    [ -d "$vl_dir" ] && [ ! -L "$vl_dir" ] || return 1
    vl_pid=; [ ! -r "$vl_dir/pid" ] || read -r vl_pid < "$vl_dir/pid"
    case "$vl_pid" in
        ''|*[!0-9]*) [ -n "$(find "$vl_dir" -maxdepth 0 -mmin +60 2>/dev/null)" ]; return ;;
    esac
    kill -0 "$vl_pid" 2>/dev/null || return 0
    vl_saved=; [ ! -r "$vl_dir/pid_start" ] || read -r vl_saved < "$vl_dir/pid_start"
    case "$vl_saved" in ''|unknown) return 1 ;; esac
    # Field 22 of /proc/PID/stat, counted after the command name in brackets.
    vl_stat=; read -r vl_stat < "/proc/$vl_pid/stat" 2>/dev/null || return 1
    set -f; set -- ${vl_stat##*) }; set +f
    [ "$vl_saved" != "${20:-}" ]
}

# vward_lock_drop DIR: remove a stale lock; a rename first, so a lock a new
# owner has just taken is never removed.
vward_lock_drop() {
    vl_old=$1.stale.$$
    [ ! -e "$vl_old" ] && [ ! -L "$vl_old" ] || return 1
    mv "$1" "$vl_old" 2>/dev/null || return 1
    rm -rf "${vl_old:?}"
}

# vward_lock_take DIR: take the lock folder DIR for this shell ($$); a lock whose
# owner is gone is taken over.  Fails while a live owner holds it.
vward_lock_take() {
    if ! mkdir "$1" 2>/dev/null; then
        vward_lock_stale "$1" && vward_lock_drop "$1" || return 1
        mkdir "$1" 2>/dev/null || return 1
    fi
    printf '%s\n' "$$" > "$1/pid" || return 1
    vward_admission_pid_start $$ > "$1/pid_start" 2>/dev/null || :
}

# vward_locks_sweep: remove every stale lock of VWARD_LOCKS.
vward_locks_sweep() {
    for vl_lock in $VWARD_LOCKS; do
        vl_lock=${VWARD_ROOT_PREFIX:-}$vl_lock
        vward_lock_stale "$vl_lock" || continue
        vward_lock_drop "$vl_lock" && echo "STALE_LOCK_REMOVED|$vl_lock"
    done
    return 0
}
