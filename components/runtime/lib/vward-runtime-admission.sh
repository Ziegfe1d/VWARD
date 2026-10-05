#!/bin/sh

# Two-phase admission protocol shared by runtime mutators and the updater.
VWARD_ADMISSION_OWNED=${VWARD_ADMISSION_OWNED:-0}
VWARD_ADMISSION_SLOT=${VWARD_ADMISSION_SLOT:-}
# Component switch: a disabled component keeps its files, but its entry points
# do nothing while <id>.disabled exists here (written by the Panel).
VWARD_COMPONENT_STATE=${VWARD_COMPONENT_STATE:-/opt/etc/vward/components}

# VWARD switched off as a whole (vward-off.sh, «Отключить VWARD»): every component is.
vward_off() { [ -e "$VWARD_COMPONENT_STATE/vward.off" ]; }

vward_component_enabled() {
    ! vward_off || return 1
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

# ---- Resources: VWARD gives way to the router -------------------------------------------
VWARD_PROC=${VWARD_PROC:-/proc}
VWARD_BUSY_MEM_KB=${VWARD_BUSY_MEM_KB:-24576}
VWARD_DEFER_DIR=${VWARD_DEFER_DIR:-${VWARD_ROOT_PREFIX:-}/tmp/vward-defer}
VWARD_SENTINEL_PIDFILE=${VWARD_SENTINEL_PIDFILE:-${VWARD_ROOT_PREFIX:-}/opt/var/run/vward/sentinel.pid}
VWARD_SENTINEL_STATE=${VWARD_SENTINEL_STATE:-${VWARD_ROOT_PREFIX:-}/tmp/vward-sentinel}

# vward_background: the lowest CPU priority for this job and everything it starts, once
# per job tree (one process). The tunnels' own programs take the normal priority back
# (their engines check VWARD_BACKGROUND): user traffic must not wait. The Panel's
# requests set VWARD_FOREGROUND and keep theirs.
vward_background() {
    [ "${VWARD_FOREGROUND:-0}" != 1 ] && [ "${VWARD_BACKGROUND:-0}" != 1 ] || return 0
    VWARD_BACKGROUND=1
    export VWARD_BACKGROUND
    renice -n 19 -p $$ >/dev/null 2>&1 || :
}

# vward_busy: the router is busy - the load of the last minute at its number of CPU
# threads or above, or less than 24 MiB of memory available. Read by the shell.
vward_busy() {
    # The real-time watcher keeps a busy flag: no /proc reading here while it runs.
    vb_pid=
    [ ! -r "$VWARD_SENTINEL_PIDFILE" ] || read -r vb_pid 2>/dev/null < "$VWARD_SENTINEL_PIDFILE" || :
    case "$vb_pid" in
        ''|*[!0-9]*) ;;
        *) if kill -0 "$vb_pid" 2>/dev/null; then [ -e "$VWARD_SENTINEL_STATE/busy" ]; return; fi ;;
    esac
    vb_cpus=0
    if [ -r "$VWARD_PROC/cpuinfo" ]; then
        while read -r vb_k _; do [ "$vb_k" != processor ] || vb_cpus=$((vb_cpus + 1)); done < "$VWARD_PROC/cpuinfo"
    fi
    [ "$vb_cpus" -gt 0 ] || vb_cpus=1
    vb_l=
    [ ! -r "$VWARD_PROC/loadavg" ] || read -r vb_l _ < "$VWARD_PROC/loadavg" || :
    vb_l=${vb_l%%.*}
    case "$vb_l" in ''|*[!0-9]*) ;; *) [ "$vb_l" -lt "$vb_cpus" ] || return 0 ;; esac
    vb_mem=
    if [ -r "$VWARD_PROC/meminfo" ]; then
        while read -r vb_k vb_v _; do
            [ "$vb_k" != MemAvailable: ] || { vb_mem=$vb_v; break; }
        done < "$VWARD_PROC/meminfo"
    fi
    case "$vb_mem" in ''|*[!0-9]*) return 1 ;; esac
    [ "$vb_mem" -lt "$VWARD_BUSY_MEM_KB" ]
}

# vward_defer NAME [MAX]: optional work (scans, speed, catalogs) waits while the router is
# busy, but at most MAX seconds in a row (2 hours): then it runs anyway. Returns 0 when
# NAME should wait now. Guards and repairs never call this.
vward_defer() {
    vd_f="$VWARD_DEFER_DIR/$1"
    if ! vward_busy; then
        [ ! -e "$vd_f" ] || rm -f "$vd_f"
        return 1
    fi
    vd_up=
    [ ! -r "$VWARD_PROC/uptime" ] || read -r vd_up _ < "$VWARD_PROC/uptime" || :
    vd_up=${vd_up%%.*}
    case "$vd_up" in ''|*[!0-9]*) return 1 ;; esac
    vd_first=
    [ ! -r "$vd_f" ] || read -r vd_first < "$vd_f" || :
    case "$vd_first" in
        ''|*[!0-9]*)
            [ -d "$VWARD_DEFER_DIR" ] || mkdir -p "$VWARD_DEFER_DIR" 2>/dev/null || return 1
            echo "$vd_up" > "$vd_f" 2>/dev/null || return 1
            vd_first=$vd_up
            ;;
    esac
    [ $((vd_up - vd_first)) -lt "${2:-7200}" ] && return 0
    rm -f "$vd_f"
    return 1
}

# vward_cpu_account COMPONENT: the CPU this job and everything it started used, added to
# /tmp/vward-cpu/COMPONENT as "runs centiseconds" (RAM, since boot). The shell's own
# `times`, no process: what VWARD costs the router, per component, measured on it.
VWARD_CPU_DIR=${VWARD_CPU_DIR:-${VWARD_ROOT_PREFIX:-}/tmp/vward-cpu}

vward_cs() {
    # 1m2.345678s -> centiseconds in VC_CS (no subshell)
    vc_v=${1%s}
    vc_m=${vc_v%%m*}
    vc_s=${vc_v#*m}
    vc_i=${vc_s%%.*}
    vc_f=${vc_s#*.}
    [ "$vc_f" != "$vc_s" ] || vc_f=0
    vc_f="${vc_f}00"
    vc_f=${vc_f%"${vc_f#??}"}
    for vc_x in vc_m vc_i vc_f; do
        eval "vc_y=\$$vc_x"
        while :; do case "$vc_y" in 0?*) vc_y=${vc_y#0} ;; *) break ;; esac; done
        case "$vc_y" in ''|*[!0-9]*) vc_y=0 ;; esac
        eval "$vc_x=\$vc_y"
    done
    VC_CS=$((vc_m * 6000 + vc_i * 100 + vc_f))
}

vward_cpu_account() {
    case "${1:-}" in ''|*[!A-Za-z0-9_.-]*) return 0 ;; esac
    [ -d "$VWARD_CPU_DIR" ] || mkdir -p "$VWARD_CPU_DIR" 2>/dev/null || return 0
    vc_tmp="$VWARD_CPU_DIR/.times.$1"
    times > "$vc_tmp" 2>/dev/null || return 0
    vc_a= vc_b= vc_c= vc_d=
    { read -r vc_a vc_b; read -r vc_c vc_d; } 2>/dev/null < "$vc_tmp" || :
    vc_total=0
    for vc_t in $vc_a $vc_b $vc_c $vc_d; do
        vward_cs "$vc_t"
        vc_total=$((vc_total + VC_CS))
    done
    vc_runs=0 vc_sum=0
    [ ! -r "$VWARD_CPU_DIR/$1" ] || read -r vc_runs vc_sum < "$VWARD_CPU_DIR/$1" || :
    case "$vc_runs$vc_sum" in *[!0-9]*|'') vc_runs=0 vc_sum=0 ;; esac
    echo "$((vc_runs + 1)) $((vc_sum + vc_total))" > "$VWARD_CPU_DIR/$1" 2>/dev/null || :
}

# vward_pid_start_var PID: the process's start time (field 22 of /proc/PID/stat) in
# VA_PS, read by the shell: every job enters and leaves through here.
vward_pid_start_var() {
    VA_PS=
    va_pid=${1:-$$}
    case "$va_pid" in ''|*[!0-9]*) return 1 ;; esac
    [ -r "/proc/$va_pid/stat" ] || return 1
    va_line=
    read -r va_line 2>/dev/null < "/proc/$va_pid/stat" || [ -n "$va_line" ] || return 1
    va_rest=${va_line##*) }
    [ "$va_rest" != "$va_line" ] || return 1
    # shellcheck disable=SC2086
    set -- $va_rest
    [ "$#" -ge 20 ] || return 1
    eval "VA_PS=\${20}"
    case "$VA_PS" in ''|*[!0-9]*) VA_PS=; return 1 ;; esac
}

vward_admission_pid_start() {
    vward_pid_start_var "${1:-$$}" || return 1
    printf '%s\n' "$VA_PS"
}

vward_admission_leave() {
    [ "${VWARD_ADMISSION_OWNED:-0}" = 1 ] || return 0
    vward_cpu_account "${VWARD_ADMISSION_COMPONENT:-}"
    va_slot=${VWARD_ADMISSION_SLOT:-}
    [ -n "$va_slot" ] && [ -d "$va_slot" ] && [ ! -L "$va_slot" ] || return 1
    va_owner= va_saved_start=
    [ -r "$va_slot/pid" ] && read -r va_owner < "$va_slot/pid" || return 1
    [ -r "$va_slot/pid_start" ] && read -r va_saved_start < "$va_slot/pid_start" || return 1
    vward_pid_start_var $$ || return 1
    [ "$va_owner" = "$$" ] && [ "$va_saved_start" = "$VA_PS" ] || return 1
    rm -f "$va_slot/pid" "$va_slot/pid_start" "$va_slot/component" 2>/dev/null || return 1
    rmdir "$va_slot" 2>/dev/null || return 1
    VWARD_ADMISSION_OWNED=0
    VWARD_ADMISSION_SLOT=
}

vward_admission_enter() {
    va_component=${1:-runtime}
    VWARD_ADMISSION_COMPONENT=$va_component
    vward_background
    case "$va_component" in ''|*[!A-Za-z0-9_.-]*) return 64 ;; esac
    va_prefix=${VWARD_ROOT_PREFIX:-}
    va_request="$va_prefix/tmp/vward-update-requested"
    va_barrier="$va_prefix/tmp/vward-update.lock"
    va_active="$va_prefix/tmp/vward-runtime-active"
    [ ! -e "$va_request" ] && [ ! -L "$va_request" ] &&
        [ ! -e "$va_barrier" ] && [ ! -L "$va_barrier" ] || return 75
    [ ! -L "$va_active" ] || return 1
    if [ ! -e "$va_active" ]; then
        # Jobs started at the same moment (cron, boot) may race here: one makes it.
        (umask 077; mkdir "$va_active") 2>/dev/null || [ -d "$va_active" ] || return 1
    fi
    [ -d "$va_active" ] || return 1
    # Keenetic's BusyBox stat has no -c: the mode comes from ls (one process), the owner
    # from the shell's own test (or the uid a test sets).
    va_active_meta=$(ls -ldn "$va_active" 2>/dev/null)
    case "$va_active_meta" in "drwx------"[\ .+]*) ;; *) return 1 ;; esac
    if [ -n "${VWARD_ADMISSION_OWNER_UID:-}" ]; then
        # shellcheck disable=SC2086
        set -- $va_active_meta
        [ "${3:-}" = "$VWARD_ADMISSION_OWNER_UID" ] || return 1
    else
        [ -O "$va_active" ] || return 1
    fi
    vward_pid_start_var $$ || return 1
    va_start=$VA_PS
    va_slot="$va_active/$va_component.$$.$va_start"
    (umask 077; mkdir "$va_slot") 2>/dev/null || return 1
    # Written under umask 077: the files are 0600 without a chmod.
    if ! (umask 077
          printf '%s\n' "$$" > "$va_slot/pid" &&
          printf '%s\n' "$va_start" > "$va_slot/pid_start" &&
          printf '%s\n' "$va_component" > "$va_slot/component") 2>/dev/null; then
        rm -f "$va_slot/pid" "$va_slot/pid_start" "$va_slot/component" 2>/dev/null
        rmdir "$va_slot" 2>/dev/null
        return 1
    fi
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
/opt/var/lib/vward/ads-privacy-guard/jobs/worker.lock /opt/var/lib/vward/ext-update/lock
/tmp/vward-ads-control.lock /tmp/vward-console-edit.lock"

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
    vl_stat=; read -r vl_stat 2>/dev/null < "/proc/$vl_pid/stat" || return 1
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

# ---- AdGuard Home: one gate for every starter ---------------------------------------------
# Several programs start AdGuard Home (the supervisor at boot, the real-time watcher when DNS
# stops answering). It loads its lists for a minute or more, so a second starter that only
# looked for the process restarted it again and again. Now every starter asks here:
# - running: nothing to do;
# - the last start is younger than the grace (120 s): wait;
# - after each start that did not bring it up the pause doubles (120, 240, 480, 600 s), the
#   number of tries is not limited, one success resets it;
# - a PID file that points to nothing, or to another program, is removed before a start (the
#   start script takes such a file for «already running» and does nothing).
# A program that dies on «--version» (a broken file; seen on a router in October 2026) is not started
# again and again: the state «broken» (uptime|exit code|path) tells the Panel, 13 is returned.
# vward_agh_ensure [INIT]: 0 running, 10 started now, 11 waiting for the grace, 12 no start script,
# 13 the program itself is broken.
# Bookkeeping in VWARD_AGH_STATE (RAM): «last» (uptime seconds of the last start) and «fails».
VWARD_AGH_INIT=${VWARD_AGH_INIT:-/opt/etc/init.d/S99adguardhome}
VWARD_AGH_STATE=${VWARD_AGH_STATE:-${VWARD_ROOT_PREFIX:-}/tmp/vward-agh-start}
VWARD_AGH_PIDFILES=${VWARD_AGH_PIDFILES:-${VWARD_ROOT_PREFIX:-}/opt/var/run/AdGuardHome.pid ${VWARD_ROOT_PREFIX:-}/opt/var/run/adguardhome.pid}
VWARD_AGH_GRACE=${VWARD_AGH_GRACE:-120}
# Where the start script finds the program (its PATH order: /opt/sbin before /opt/bin).
VWARD_AGH_BIN_DIRS=${VWARD_AGH_BIN_DIRS:-/opt/sbin /opt/bin /usr/local/sbin /usr/local/bin /usr/sbin /usr/bin /sbin /bin}

vward_agh_binary()
{
    for vb_d in $VWARD_AGH_BIN_DIRS; do
        [ -f "$vb_d/AdGuardHome" ] && [ -x "$vb_d/AdGuardHome" ] && { printf '%s\n' "$vb_d/AdGuardHome"; return 0; }
    done
    return 1
}

vward_agh_pidfiles_clean() {
    for va_f in $VWARD_AGH_PIDFILES; do
        [ -f "$va_f" ] || continue
        va_p=; { read -r va_p < "$va_f"; } 2>/dev/null || :
        case "$va_p" in ''|*[!0-9]*) rm -f "$va_f"; continue ;; esac
        va_c=; { read -r va_c < "${VWARD_PROC:-/proc}/$va_p/comm"; } 2>/dev/null || :
        [ "$va_c" = AdGuardHome ] || rm -f "$va_f"
    done
}

vward_agh_ensure() {
    va_init=${1:-$VWARD_AGH_INIT}
    va_now=; { read -r va_now _ < "${VWARD_UPTIME_FILE:-/proc/uptime}"; } 2>/dev/null || :
    va_now=${va_now%%.*}
    if pidof AdGuardHome >/dev/null 2>&1; then
        # Running for a whole grace since the last start: that start worked, the books are clean.
        # A program that dies a minute after every start keeps its growing pauses.
        va_last=; [ ! -r "$VWARD_AGH_STATE/last" ] || read -r va_last < "$VWARD_AGH_STATE/last"
        if [ -n "$va_last" ]; then
            case "$va_last$va_now" in
                *[!0-9]*|"$va_last") ;;
                *) [ "$va_now" -lt "$va_last" ] || [ $((va_now - va_last)) -lt "$VWARD_AGH_GRACE" ] || rm -f "$VWARD_AGH_STATE/last" "$VWARD_AGH_STATE/fails" 2>/dev/null ;;
            esac
        fi
        return 0
    fi
    [ -x "$va_init" ] || return 12
    case "$va_now" in ''|*[!0-9]*) return 11 ;; esac
    mkdir -p "$VWARD_AGH_STATE" 2>/dev/null || return 11
    # One starter at a time: whoever holds the lock decides, the others wait.
    vward_lock_take "$VWARD_AGH_STATE/lock" || return 11
    va_last=; [ ! -r "$VWARD_AGH_STATE/last" ] || read -r va_last < "$VWARD_AGH_STATE/last"
    va_fails=; [ ! -r "$VWARD_AGH_STATE/fails" ] || read -r va_fails < "$VWARD_AGH_STATE/fails"
    case "$va_last" in ''|*[!0-9]*) va_last= ;; esac
    case "$va_fails" in ''|*[!0-9]*) va_fails=0 ;; esac
    va_pause=$VWARD_AGH_GRACE
    if [ -n "$va_last" ]; then
        # A reboot restarts the uptime: a «last» from the future is an old one.
        [ "$va_last" -le "$va_now" ] || va_last=
    fi
    if [ -n "$va_last" ]; then
        va_i=0
        while [ "$va_i" -lt "$va_fails" ] && [ "$va_pause" -lt 600 ]; do va_pause=$((va_pause * 2)); va_i=$((va_i + 1)); done
        [ "$va_pause" -le 600 ] || va_pause=600
        if [ $((va_now - va_last)) -lt "$va_pause" ]; then
            vward_lock_drop "$VWARD_AGH_STATE/lock"
            return 11
        fi
        # The previous start did not bring it up: the next pause is longer.
        va_fails=$((va_fails + 1))
    fi
    if va_bin=$(vward_agh_binary); then
        "$va_bin" --version >/dev/null 2>&1; va_rc=$?
        if [ "$va_rc" != 0 ]; then
            printf '%s|%s|%s\n' "$va_now" "$va_rc" "$va_bin" > "$VWARD_AGH_STATE/broken"
            vward_lock_drop "$VWARD_AGH_STATE/lock"
            return 13
        fi
        rm -f "$VWARD_AGH_STATE/broken"
    fi
    vward_agh_pidfiles_clean
    printf '%s\n' "$va_now" > "$VWARD_AGH_STATE/last"
    printf '%s\n' "$va_fails" > "$VWARD_AGH_STATE/fails"
    vward_lock_drop "$VWARD_AGH_STATE/lock"
    ${VWARD_UNNICE:-} "$va_init" start </dev/null >/dev/null 2>&1
    return 10
}

# ---- Agents ---------------------------------------------------------------------------
# Four agents, one zone each: network (internet, VPN, DNS, routes), components (VWARD's
# programs, the tunnels' modules, AdGuard Home), updates, maintenance. Only the components
# agent (the cron supervisor) starts, stops and restarts a program; the others ask it:
#   agh-start | start:NAME | restart:NAME | engine-restart:TUNNEL | engine-kick:TUNNEL
# A request is a file; a byte into the agent's pipe wakes it at once (a pipe opened for reading
# and writing never blocks, and a byte nobody reads is simply dropped: the file stays).
VWARD_AGENT_REQ=${VWARD_AGENT_REQ:-${VWARD_ROOT_PREFIX:-}/tmp/vward-agent-components}
VWARD_AGENT_PIDFILE=${VWARD_AGENT_PIDFILE:-${VWARD_ROOT_PREFIX:-}/opt/var/run/vward/cron-supervisor.pid}

# vward_agent_ask REQUEST [WAIT]: 0 = queued (no WAIT) or done within WAIT seconds. A components
# agent that is not running is started first, so a request is never left alone.
vward_agent_ask() {
    case "$1" in ''|*[!a-z0-9:._-]*) return 64 ;; esac
    mkdir -p "$VWARD_AGENT_REQ" 2>/dev/null || return 1
    : > "$VWARD_AGENT_REQ/$1" 2>/dev/null || return 1
    [ ! -p "$VWARD_AGENT_REQ/.wake" ] || printf 'x\n' 1<>"$VWARD_AGENT_REQ/.wake" 2>/dev/null || :
    _va_p=
    [ ! -r "$VWARD_AGENT_PIDFILE" ] || read -r _va_p 2>/dev/null < "$VWARD_AGENT_PIDFILE" || :
    case "$_va_p" in ''|*[!0-9]*) _va_p=0 ;; esac
    if [ "$_va_p" -le 1 ] || ! kill -0 "$_va_p" 2>/dev/null; then
        "${VWARD_AGENT_INIT:-/opt/etc/init.d/S92vward-runtime}" start </dev/null >/dev/null 2>&1 || :
    fi
    _va_w=${2:-0}
    case "$_va_w" in ''|*[!0-9]*) _va_w=0 ;; esac
    _va_n=0
    while [ -e "$VWARD_AGENT_REQ/$1" ] && [ "$_va_n" -lt "$_va_w" ]; do sleep 1; _va_n=$((_va_n + 1)); done
    [ "$_va_w" = 0 ] || [ ! -e "$VWARD_AGENT_REQ/$1" ]
}
