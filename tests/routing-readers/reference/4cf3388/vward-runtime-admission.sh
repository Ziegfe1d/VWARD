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
# vward_keenetic_busy: Keenetic answered VWARD in 2 s or more (VWARD_KEENETIC_BUSY_CS) at its last
# request within 90 s (fix.33.2, WP-C): its configuration service is busy, whatever the load says
# (load 3.5 of 4 threads while RCI took 20 s, Viva 2026-10-24). The last request's time and length
# come from the device library (every request to Keenetic writes them; wan-guard asks every minute).
VWARD_KEENETIC_LAST=${VWARD_KEENETIC_LAST:-${VWARD_ROOT_PREFIX:-}/tmp/vward-keenetic-last}
vward_keenetic_busy() {
    [ "${VWARD_KEENETIC_BUSY:-1}" = 1 ] || return 1
    vkb_at= vkb_cs= vkb_up=
    read -r vkb_at vkb_cs 2>/dev/null < "$VWARD_KEENETIC_LAST" || return 1
    read -r vkb_up _ 2>/dev/null < "$VWARD_PROC/uptime" || return 1
    vkb_up=${vkb_up%%.*}
    case "$vkb_at$vkb_cs$vkb_up" in ''|*[!0-9]*) return 1 ;; esac
    [ "$vkb_up" -ge "$vkb_at" ] && [ $((vkb_up - vkb_at)) -lt "${VWARD_KEENETIC_BUSY_AGE:-90}" ] &&
        [ "$vkb_cs" -ge "${VWARD_KEENETIC_BUSY_CS:-200}" ]
}

vward_busy() {
    vward_keenetic_busy && return 0
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

# vward_isp_control: the direct (provider) check itself works - Russian sites that are always up,
# reached the way a site check reaches a site (curl over the WAN device, the same time limits).
# A site check through the provider that failed while this fails too says nothing about the site
# (01.11.2026: the audit had ok 4 of 482, 281 timeouts, api.ozon.ru «broken»): the verdict is
# «unknown», never «the provider blocks it». One curl per VWARD_ISP_CONTROL_TTL (120 s) at most,
# the answer kept in /tmp. 0: works; 1: does not; 2: cannot tell (no WAN device, no curl).
# VWARD_ISP_CONTROL=0 turns it off (always 0).
vward_isp_control() {
    [ "${VWARD_ISP_CONTROL:-1}" = 1 ] || return 0
    vic_f=${VWARD_ISP_CONTROL_STATE:-/tmp/vward-isp-control}
    # The clock without a process: seconds since boot (the answer is kept in RAM, lost at boot).
    vic_now=
    read -r vic_now _ 2>/dev/null < "${VWARD_UPTIME_FILE:-/proc/uptime}" || :
    vic_now=${vic_now%%.*}
    case "$vic_now" in ''|*[!0-9]*) vic_now=0 ;; esac
    vic_t= vic_r=
    [ ! -r "$vic_f" ] || read -r vic_t vic_r 2>/dev/null < "$vic_f" || :
    case "$vic_t:$vic_r" in
        *[!0-9:]*|:*|*:) ;;
        *) [ "$vic_now" -lt "$vic_t" ] || [ $((vic_now - vic_t)) -ge "${VWARD_ISP_CONTROL_TTL:-120}" ] || return "$vic_r" ;;
    esac
    [ -n "${VWARD_WAN_DEVICE:-}" ] && command -v curl >/dev/null 2>&1 || return 2
    # curl crashing on HTTPS (Entware's OpenSSL on some MIPS routers): the shared turn and
    # «broken for an hour» of the site checks (vward_tls_take/done), never a crash of its own;
    # a curl that cannot do HTTPS cannot tell (2).
    [ -z "$(find "${VWARD_TLS_BROKEN_FLAG:-/tmp/vward-curl-tls.broken}" -mmin -60 2>/dev/null)" ] || return 2
    ! command -v vward_tls_take >/dev/null 2>&1 || vward_tls_take || return 2
    vic_r=1 vic_rc=0
    for vic_u in ${VWARD_ISP_CONTROL_URLS:-https://ya.ru/ https://vk.com/}; do
        vic_c=$(curl --http1.1 -4 --noproxy '*' --interface "$VWARD_WAN_DEVICE" \
            --connect-timeout "${VWARD_ISP_CONTROL_CT:-2}" --max-time "${VWARD_ISP_CONTROL_MT:-3}" \
            -A "Mozilla/5.0" -s -o /dev/null -w '%{http_code}' "$vic_u" 2>/dev/null)
        vic_rc=$?
        [ "$vic_rc" = 0 ] && [ "${vic_c:-000}" != 000 ] && { vic_r=0; break; }
        case "$vic_rc" in 132|134|135|136|139) vic_r=2; break ;; esac
    done
    ! command -v vward_tls_done >/dev/null 2>&1 || vward_tls_done "$vic_rc"
    [ "$vic_r" = 2 ] && return 2
    printf '%s %s\n' "$vic_now" "$vic_r" > "$vic_f" 2>/dev/null
    return "$vic_r"
}

# vward_spread SECONDS: a job crond started (with the minute jobs, at second 0) starts SECONDS
# later, so the heavy ones do not ask Keenetic together with the agents of the minute (fix.33.2,
# WP-C). Started otherwise (the Panel, a test, by hand): at once. VWARD_SPREAD=0 turns it off.
vward_spread() {
    [ "${VWARD_SPREAD:-1}" = 1 ] && [ "${VWARD_FOREGROUND:-0}" != 1 ] || return 0
    case "${1:-}" in ''|*[!0-9]*|0) return 0 ;; esac
    vs_p=$PPID
    for vs_i in 1 2; do
        vs_s=; read -r vs_s 2>/dev/null < "$VWARD_PROC/$vs_p/stat" || return 0
        case "$vs_s" in *" (crond) "*) sleep "$1"; return 0 ;; esac
        # shellcheck disable=SC2086
        set -- "$1" ${vs_s##*) }
        vs_p=${3:-}
        case "$vs_p" in ''|*[!0-9]*|0|1) return 0 ;; esac
    done
    return 0
}

# vward_defer NAME [MAX [CHECK]]: optional work (scans, speed, catalogs) waits while the router is
# busy, but at most MAX seconds in a row (2 hours): then it runs anyway. Returns 0 when
# NAME should wait now. Guards and repairs never call this.
vward_defer() {
    vd_f="$VWARD_DEFER_DIR/$1"
    # CHECK (3rd argument): what «busy» means for this job; vward_busy by default.
    if ! "${3:-vward_busy}"; then
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

# Cooperative short election for acquiring/reclaiming a lock. Each choosing
# ticket's NAME already contains actual PID/start/boot, before its first file.
# A dead reclaimer therefore leaves no ownerless global '.reclaim' semaphore.
# Bakery order serializes ALL updated contenders; stale observation alone
# never permits unlinking a path that another contender has since acquired.
vward_lock_gate_live() {
    vlg_key_boot=${1%%.*};vlg_key_rest=${1#*.}
    vlg_key_pid=${vlg_key_rest%%.*};vlg_key_start=${vlg_key_rest#*.}
    [ "${#vlg_key_boot}" -eq 36 ] || return 2
    case $vlg_key_boot in *[!0-9a-f-]*) return 2 ;; esac
    case $vlg_key_pid:$vlg_key_start in *[!0-9:]*|:*|*:) return 2 ;; esac
    [ "${#vlg_key_pid}" -le 10 ] && [ "${#vlg_key_start}" -le 20 ] || return 2
    [ "$vlg_key_boot" = "$vlg_boot" ] || return 1
    vlg_live_start=$(vward_admission_pid_start "$vlg_key_pid") || vlg_live_start=
    if [ -n "$vlg_live_start" ]; then
        [ "$vlg_live_start" = "$vlg_key_start" ] || return 1
        vlg_stat=;read -r vlg_stat < "/proc/$vlg_key_pid/stat" || return 2
        vlg_stat=${vlg_stat##*) }
        # A finished final utility can remain a zombie under an unreaping
        # container init. Z/X cannot execute another filesystem operation.
        case $vlg_stat in Z\ *|X\ *) return 1 ;; esac
        return 0
    fi
    kill -0 "$vlg_key_pid" 2>/dev/null && return 2
    return 1
}
# Metadata fields only; paths are never parsed as ls output.
# vward_lock_ls PATH sets vl_lsmode (first 10 chars of field 1, as awk
# substr($1,1,10)) and vl_lslinks (field 2) from ONE ls, without an awk
# pipeline: lock checks run hundreds of times per routing request.
# shellcheck disable=SC2012
vward_lock_ls() {
    vl_lst=$(LC_ALL=C ls -ldn "$1" 2>/dev/null) || return 1
    case $vl_lst in *'
'*|'') return 1 ;; esac
    vl_lsmode=${vl_lst%%[ 	]*};vl_lsmode=${vl_lsmode%"${vl_lsmode#??????????}"}
    vl_lst=${vl_lst#*[ 	]};vl_lst=${vl_lst#"${vl_lst%%[! 	]*}"};vl_lslinks=${vl_lst%%[ 	]*}
}
vward_lock_gate_dir() {
    [ -d "$1" ] && [ ! -L "$1" ] && [ -O "$1" ] && vward_lock_ls "$1" && [ "$vl_lsmode" = drwx------ ]
}
vward_lock_gate_number() {
    [ -f "$1/number" ] && [ ! -L "$1/number" ] && [ -O "$1/number" ] || return 1
    # shellcheck disable=SC2012
    vward_lock_ls "$1/number" && [ "$vl_lsmode $vl_lslinks" = '-rw------- 1' ] || return 2
    vlg_n=;read -r vlg_n < "$1/number" || return 2
    case $vlg_n in ''|*[!0-9]*|0*) return 2 ;; esac
    [ "${#vlg_n}" -le 10 ] && [ "$vlg_n" -lt 2147483647 ] || return 2
    printf '%s\n' "$vlg_n"
}
# A final filesystem utility may outlive the shell which called it. Its own
# actual identity is registered before exec, just as for DATA publication.
vward_lock_gate_exec() (
    # Final mkdir must create a private lock independently of the caller's
    # ambient umask; this affects only the leased utility's own process.
    umask 077
    vward_lock_gate_dir "$vlg_claim" && vward_lock_gate_live "$vlg_key" || return 75
    IFS=' ' read -r vlg_exec_pid _ < /proc/self/stat || return 75
    vlg_exec_start=$(vward_admission_pid_start "$vlg_exec_pid") || return 75
    (umask 077;printf '%s\n' "$vlg_boot" > "$vlg_claim/exec.$vlg_exec_pid.$vlg_exec_start") || return 75
    # If the parent died before registration, no write may start. If it dies
    # after this test, contenders see this actual exec PID until it is gone.
    vward_lock_gate_dir "$vlg_claim" && vward_lock_gate_live "$vlg_key" || return 75
    exec "$@"
)
vward_lock_gate_quiet() {
    for vlg_lease in "$1"/exec.*; do
        [ -e "$vlg_lease" ] || [ -L "$vlg_lease" ] || continue
        [ -f "$vlg_lease" ] && [ ! -L "$vlg_lease" ] && [ -O "$vlg_lease" ] || return 2
        # shellcheck disable=SC2012
        vward_lock_ls "$vlg_lease" && [ "$vl_lsmode $vl_lslinks" = '-rw------- 1' ] || return 2
        vlg_exec_key=${vlg_lease##*/exec.}
        vlg_exec_boot=;read -r vlg_exec_boot < "$vlg_lease" || return 2
        vlg_exec_rc=0;vward_lock_gate_live "$vlg_exec_boot.$vlg_exec_key" || vlg_exec_rc=$?
        [ "$vlg_exec_rc" = 1 ] || return 2
    done
}
# Read one decimal owner record with shell builtins. Like command-substitution
# cat, trailing empty lines are harmless; an embedded/extra field is not.
vward_lock_gate_decimal() (
    vlg_decimal=;vlg_decimal_tail=
    {
        IFS= read -r vlg_decimal || [ -n "$vlg_decimal" ] || return 2
        case $vlg_decimal in ''|*[!0-9]*) return 2 ;; esac
        [ "${#vlg_decimal}" -le 20 ] || return 2
        while IFS= read -r vlg_decimal_tail || [ -n "$vlg_decimal_tail" ]; do
            [ -z "$vlg_decimal_tail" ] || return 2
        done
    } < "$1" || return 2
    printf '%s\n' "$vlg_decimal"
)
vward_lock_gate_leave() {
    [ -n "${vlg_claim:-}" ] && [ "${vlg_claim%/*}" = "$1.gate" ] || return 75
    vward_lock_gate_dir "$vlg_claim" || return 75
    IFS=' ' read -r vlg_leave_pid _ < /proc/self/stat || return 75
    [ "$(vward_lock_gate_decimal "$vlg_claim/pid" 2>/dev/null)" = "$vlg_leave_pid" ] &&
        [ "$(vward_lock_gate_decimal "$vlg_claim/start" 2>/dev/null)" = "$(vward_admission_pid_start "$vlg_leave_pid")" ] || return 75
    rm -rf "$vlg_claim"
}
vward_lock_gate_enter() {
    case $1 in /*) ;; *) return 75 ;; esac
    IFS=' ' read -r vlg_me _ < /proc/self/stat || return 75
    vlg_start=$(vward_admission_pid_start "$vlg_me") || return 75
    IFS= read -r vlg_boot < /proc/sys/kernel/random/boot_id || return 75
    vlg_dir=$1.gate
    if [ -e "$vlg_dir" ] || [ -L "$vlg_dir" ]; then
        vward_lock_gate_dir "$vlg_dir" || return 75
    else
        (umask 077;mkdir "$vlg_dir" 2>/dev/null) || vward_lock_gate_dir "$vlg_dir" || return 75
    fi
    vlg_key=$vlg_boot.$vlg_me.$vlg_start;vlg_claim=$vlg_dir/$vlg_key
    (umask 077;mkdir "$vlg_claim") || return 75
    (umask 077;printf '%s\n' "$vlg_me" > "$vlg_claim/pid" && printf '%s\n' "$vlg_start" > "$vlg_claim/start") || return 75
    vlg_max=0;vlg_count=1
    for vlg_other in "$vlg_dir"/*; do
        [ -e "$vlg_other" ] || [ -L "$vlg_other" ] || continue
        # Our unnumbered choosing ticket contributes no maximum. Keep it in
        # the same 256-ticket bound without spawning metadata tools for self;
        # the final utility and leave still validate our own private claim.
        [ "$vlg_other" != "$vlg_claim" ] || continue
        vward_lock_gate_dir "$vlg_other" || { vward_lock_gate_leave "$1";return 75; }
        vlg_rc=0;vward_lock_gate_live "${vlg_other##*/}" || vlg_rc=$?
        [ "$vlg_rc" != 2 ] || { vward_lock_gate_leave "$1";return 75; }
        if [ "$vlg_rc" != 0 ]; then
            vward_lock_gate_quiet "$vlg_other" || { vward_lock_gate_leave "$1";return 75; }
            rm -rf "$vlg_other" || { vward_lock_gate_leave "$1";return 75; };continue
        fi
        vlg_count=$((vlg_count+1));[ "$vlg_count" -le 256 ] || { vward_lock_gate_leave "$1";return 75; }
        vlg_value=$(vward_lock_gate_number "$vlg_other") || vlg_value=0
        [ "$vlg_value" -le "$vlg_max" ] || vlg_max=$vlg_value
    done
    vlg_number=$((vlg_max+1));[ "$vlg_number" -lt 2147483647 ] || { vward_lock_gate_leave "$1";return 75; }
    (umask 077;printf '%s\n' "$vlg_number" > "$vlg_claim/number") || return 75
    vlg_attempt=0
    while [ "$vlg_attempt" -lt 40 ]; do
        vlg_wait=0
        for vlg_other in "$vlg_dir"/*; do
            [ -e "$vlg_other" ] || [ -L "$vlg_other" ] || continue
            [ "$vlg_other" != "$vlg_claim" ] || continue
            vward_lock_gate_dir "$vlg_other" || { vward_lock_gate_leave "$1";return 75; }
            vlg_rc=0;vward_lock_gate_live "${vlg_other##*/}" || vlg_rc=$?
            [ "$vlg_rc" != 2 ] || { vward_lock_gate_leave "$1";return 75; }
            if [ "$vlg_rc" != 0 ]; then
                vward_lock_gate_quiet "$vlg_other" || { vward_lock_gate_leave "$1";return 75; }
                continue
            fi
            vlg_value=$(vward_lock_gate_number "$vlg_other") || { vlg_wait=1;continue; }
            # Numeric number/PID ordering avoids locale-dependent path order.
            vlg_other_rest=${vlg_other##*/};vlg_other_rest=${vlg_other_rest#*.};vlg_other_pid=${vlg_other_rest%%.*}
            if [ "$vlg_value" -lt "$vlg_number" ] || { [ "$vlg_value" = "$vlg_number" ] && [ "$vlg_other_pid" -lt "$vlg_me" ]; }; then vlg_wait=1;fi
        done
        [ "$vlg_wait" != 0 ] || return 0
        vlg_attempt=$((vlg_attempt+1));sleep 0.05
    done
    vward_lock_gate_leave "$1"
    return 75
}

# vward_lock_stale DIR: the lock's owner is gone - its process is dead or the
# id now belongs to another process (pid_start differs), or the lock has had no
# owner id for an hour.
# Native boot identity is checked before PID/start; a reused pair after reboot
# is not the old owner. A missing legacy boot stamp keeps the older PID rule.
vward_lock_boot_id() {
    [ -f "$1" ] && [ ! -L "$1" ] && [ -O "$1" ] || return 1
    # Authority metadata only, not filename fields.
    # shellcheck disable=SC2012
    vward_lock_ls "$1" || return 1
    case "$vl_lsmode $vl_lslinks" in '-rw------- 1'|'-r-------- 1') ;; *) return 1 ;; esac
    vl_boot=;read -r vl_boot < "$1" || return 1
    printf '%s\n' "$vl_boot" | grep -Eq '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$' || return 1
    printf '%s\n' "$vl_boot"
}
vward_lock_stale() {
    vl_dir=$1
    [ -d "$vl_dir" ] && [ ! -L "$vl_dir" ] || return 1
    if [ -e "$vl_dir/boot" ] || [ -L "$vl_dir/boot" ]; then
        vl_old_boot=$(vward_lock_boot_id "$vl_dir/boot") || return 1
        IFS= read -r vl_now_boot < /proc/sys/kernel/random/boot_id || return 1
        [ "$vl_old_boot" = "$vl_now_boot" ] || return 0
    fi
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

# Drop only a proved STALE lock, under the same election as acquisition.
# Active holders use release, which requires their actual owner identity.
vward_lock_drop() {
    vward_lock_gate_enter "$1" || return 1
    vl_drop_rc=1
    if vward_lock_stale "$1"; then vward_lock_gate_exec rm -rf "$1" && vl_drop_rc=0;fi
    vward_lock_gate_leave "$1" || return 1
    return "$vl_drop_rc"
}

# vward_lock_take DIR: take the lock folder DIR for this actual kernel shell; a lock whose
# owner is gone is taken over.  Fails while a live owner holds it.
vward_lock_take() {
    vward_lock_gate_enter "$1" || return 1
    vl_take_rc=0
    if ! vward_lock_gate_exec mkdir "$1" 2>/dev/null; then
        if vward_lock_stale "$1"; then
            vward_lock_gate_exec rm -rf "${1:?}" && vward_lock_gate_exec mkdir "$1" 2>/dev/null || vl_take_rc=1
        else vl_take_rc=1;fi
    fi
    if [ "$vl_take_rc" = 0 ]; then
        IFS=' ' read -r vl_take_pid _ < /proc/self/stat || vl_take_rc=1
        # Shared-path metadata must be written by the elected owner itself,
        # never by an unleased shell which could outlive that owner.
        if vl_take_umask=$(umask); then
            umask 077
            printf '%s\n' "$vlg_boot" > "$1/boot" && printf '%s\n' "$vl_take_pid" > "$1/pid" &&
                vward_admission_pid_start "$vl_take_pid" > "$1/pid_start" || vl_take_rc=1
            umask "$vl_take_umask" || vl_take_rc=1
        else vl_take_rc=1;fi
    fi
    vward_lock_gate_leave "$1" || return 1
    return "$vl_take_rc"
}

# Release is a mutation too. A delayed orphan rm cannot run over a new
# holder: it has a final-utility lease in the same election until completion.
vward_lock_release() {
    vward_lock_gate_enter "$1" || return 1
    vl_release_rc=1
    if [ ! -e "$1" ] && [ ! -L "$1" ]; then vl_release_rc=0
    elif [ -d "$1" ] && [ ! -L "$1" ] && [ -O "$1" ]; then
        IFS=' ' read -r vl_release_pid _ < /proc/self/stat || vl_release_pid=
        vl_release_start=$(vward_admission_pid_start "$vl_release_pid") || vl_release_start=
        if [ -n "$vl_release_start" ] && [ "$(vward_lock_gate_decimal "$1/pid" 2>/dev/null)" = "$vl_release_pid" ] &&
            [ "$(vward_lock_gate_decimal "$1/pid_start" 2>/dev/null)" = "$vl_release_start" ] &&
            [ "$(vward_lock_boot_id "$1/boot")" = "$vlg_boot" ]; then
            vward_lock_gate_exec rm -rf "$1" && vl_release_rc=0
        fi
    fi
    vward_lock_gate_leave "$1" || return 1
    return "$vl_release_rc"
}

# Sweep and take participate in the SAME short election. The stale test is
# inside it; a stale value observed before entering grants no deletion right.
vward_locks_sweep() {
    for vl_lock in $VWARD_LOCKS; do
        vl_lock=${VWARD_ROOT_PREFIX:-}$vl_lock
        if [ ! -d "$vl_lock" ] || [ -L "$vl_lock" ]; then continue;fi
        # Observation of a healthy lock is read-only. This preliminary test
        # grants NO deletion authority: stale candidates are checked again
        # inside the same election as take/release below (including ABA).
        vward_lock_stale "$vl_lock" || continue
        vward_lock_gate_enter "$vl_lock" || continue
        vl_swept=0
        if vward_lock_stale "$vl_lock"; then vward_lock_gate_exec rm -rf "$vl_lock" && vl_swept=1;fi
        vward_lock_gate_leave "$vl_lock" || return 1
        [ "$vl_swept" != 1 ] || echo "STALE_LOCK_REMOVED|$vl_lock"
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

# vward_doh_keep: a local DoH client that AdGuard Home's Smart DNS goes through ([/a.com/]
# 127.0.0.1:5453 - https-dns-proxy) and that does not listen is started again by its own start
# script (Viva 2026-10-13: https-dns-proxy crashed in libnghttp2 at night and the AI services
# behind Smart DNS stayed broken until someone started it). Three restarts within 6 hours: its
# HTTPS libraries are noted for the maintenance agent's repair (VWARD_DOH_BROKEN_FLAG); curl is
# not marked broken for it (a DoH client that does not start is no proof curl crashes: VWARD went
# around a working curl for hours, Viva 2026-10-17).
# 0: nothing to do, 10: started again, 11: the start did not help (the caller waits longer;
# VD_WHY: not_running - the client is not running at all, not_listening - it runs, the port is shut;
# VD_INIT: the start scripts run).
vward_doh_keep() {
    vd_cfg=${VWARD_ADGUARD_CONFIG:-/opt/etc/AdGuardHome/AdGuardHome.yaml}
    [ -r "$vd_cfg" ] || vd_cfg=/opt/etc/AdGuardHome.yaml
    [ -r "$vd_cfg" ] || return 0
    vd_net=${VWARD_PROC_NET:-/proc/net}
    vd_down=
    for vd_p in $(awk '{ while (match($0, /\]((udp|tcp):\/\/)?127\.0\.0\.1:[0-9]+/)) { s = substr($0, RSTART, RLENGTH); sub(/.*:/, "", s); print s; $0 = substr($0, RSTART + RLENGTH) } }' "$vd_cfg" 2>/dev/null | sort -u); do
        [ "$vd_p" != 53 ] || continue
        vd_hex=$(printf '%04X' "$vd_p")
        awk -v h=":$vd_hex" '$2 ~ h "$" {f = 1} END {exit !f}' "$vd_net/udp" "$vd_net/tcp" 2>/dev/null || vd_down="$vd_down $vd_p"
    done
    [ -n "$vd_down" ] || return 0
    # The start script of the port AdGuard Home asks: the one that names that port. The first
    # script called «doh» or «https-dns-proxy» was the package's own instance on 5053, and the
    # Smart DNS one (S98…, port 5453) stayed down for hours (Viva 2026-10-17). Only when no
    # script names the port (it is in the client's config file) the old guess by the name.
    VD_INIT=
    for vd_p in $vd_down; do
        vd_init=
        for vd_s in "${VWARD_INITD:-/opt/etc/init.d}"/S*; do
            [ -x "$vd_s" ] || continue
            grep -Eq "(^|[^0-9])$vd_p([^0-9]|\$)" "$vd_s" 2>/dev/null && { vd_init=$vd_s; break; }
        done
        [ -n "$vd_init" ] || for vd_s in "${VWARD_INITD:-/opt/etc/init.d}"/S*; do
            [ -x "$vd_s" ] || continue
            case "${vd_s##*/}" in *doh*|*https-dns-proxy*) vd_init=$vd_s; break ;; esac
            grep -q 'https-dns-proxy' "$vd_s" 2>/dev/null && { vd_init=$vd_s; break; }
        done
        [ -n "$vd_init" ] || continue
        case " $VD_INIT " in *" ${vd_init##*/} "*) continue ;; esac
        VD_INIT="${VD_INIT:+$VD_INIT }${vd_init##*/}"
        ${VWARD_UNNICE:-} "$vd_init" restart </dev/null >/dev/null 2>&1 || ${VWARD_UNNICE:-} "$vd_init" start </dev/null >/dev/null 2>&1
    done
    [ -n "$VD_INIT" ] || return 0
    vd_log=${VWARD_DOH_RESTARTS:-/tmp/vward-doh-restarts}
    vd_now=$(date +%s)
    { [ ! -r "$vd_log" ] || awk -v n="$vd_now" '$1 + 21600 > n' "$vd_log"; echo "$vd_now"; } > "$vd_log.$$" 2>/dev/null && mv -f "$vd_log.$$" "$vd_log"
    [ "$(wc -l < "$vd_log" 2>/dev/null)" -lt 3 ] || : > "${VWARD_DOH_BROKEN_FLAG:-/tmp/vward-doh.broken}" 2>/dev/null
    sleep "${VWARD_DOH_SETTLE:-2}"
    for vd_p in $vd_down; do
        vd_hex=$(printf '%04X' "$vd_p")
        awk -v h=":$vd_hex" '$2 ~ h "$" {f = 1} END {exit !f}' "$vd_net/udp" "$vd_net/tcp" 2>/dev/null && continue
        VD_WHY=not_listening
        pidof "${VWARD_DOH_COMM:-https-dns-proxy}" >/dev/null 2>&1 || VD_WHY=not_running
        return 11
    done
    return 10
}

vward_agh_ensure() {
    va_init=${1:-$VWARD_AGH_INIT}
    va_now=; { read -r va_now _ < "${VWARD_UPTIME_FILE:-/proc/uptime}"; } 2>/dev/null || :
    va_now=${va_now%%.*}
    if pidof AdGuardHome >/dev/null 2>&1; then
        # Running for a whole grace since the last start: that start worked, the books are clean
        # (and a later failure is told in the bell again: «noted», the supervisor's).
        # A program that dies a minute after every start keeps its growing pauses.
        va_last=; [ ! -r "$VWARD_AGH_STATE/last" ] || read -r va_last < "$VWARD_AGH_STATE/last"
        if [ -n "$va_last" ]; then
            case "$va_last$va_now" in
                *[!0-9]*|"$va_last") ;;
                *) [ "$va_now" -lt "$va_last" ] || [ $((va_now - va_last)) -lt "$VWARD_AGH_GRACE" ] || rm -f "$VWARD_AGH_STATE/last" "$VWARD_AGH_STATE/fails" "$VWARD_AGH_STATE/noted" 2>/dev/null ;;
            esac
        else
            rm -f "$VWARD_AGH_STATE/noted" 2>/dev/null
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
            vward_lock_release "$VWARD_AGH_STATE/lock"
            return 11
        fi
        # The previous start did not bring it up: the next pause is longer.
        va_fails=$((va_fails + 1))
    fi
    if va_bin=$(vward_agh_binary); then
        # Found broken within the hour and the file not replaced since: not run again (every
        # request of the real-time watcher crashed it once more, the router emulator, fix.24).
        va_was=; [ ! -r "$VWARD_AGH_STATE/broken" ] || { IFS= read -r va_was < "$VWARD_AGH_STATE/broken"; } 2>/dev/null || :
        if [ "${va_was#*|*|}" = "$va_bin" ] && [ -n "$(find "$VWARD_AGH_STATE/broken" -mmin -60 2>/dev/null)" ] &&
           [ -z "$(find "$va_bin" -newer "$VWARD_AGH_STATE/broken" 2>/dev/null)" ]; then
            vward_lock_release "$VWARD_AGH_STATE/lock"
            return 13
        fi
        "$va_bin" --version >/dev/null 2>&1; va_rc=$?
        if [ "$va_rc" != 0 ]; then
            printf '%s|%s|%s\n' "$va_now" "$va_rc" "$va_bin" > "$VWARD_AGH_STATE/broken"
            vward_lock_release "$VWARD_AGH_STATE/lock"
            return 13
        fi
        rm -f "$VWARD_AGH_STATE/broken"
    fi
    vward_agh_pidfiles_clean
    printf '%s\n' "$va_now" > "$VWARD_AGH_STATE/last"
    printf '%s\n' "$va_fails" > "$VWARD_AGH_STATE/fails"
    vward_lock_release "$VWARD_AGH_STATE/lock"
    ${VWARD_UNNICE:-} "$va_init" start </dev/null >/dev/null 2>&1
    return 10
}

# ---- Observation mode («Наблюдение | Действие», fix.28.2) ---------------------------------
# Failures grew as the agents grew; before they are rebuilt around one core, the owner can let
# an agent only watch: what it would do it writes down as a proposed action («Предполагаемое
# действие») and does nothing. agents.conf: all=act|watch, then network=, components=, updates=,
# maintenance= (empty: as all); no file, no choice: watch (owner 2026-10-18). Not gated, ever: starting a stopped VWARD program, the Panel and
# SSH, AdGuard Home out of the DNS chain when it is silent (the home keeps its internet).
VWARD_AGENTS_CONF=${VWARD_AGENTS_CONF:-${VWARD_ROOT_PREFIX:-}/opt/etc/vward/agents.conf}
VWARD_PROPOSED=${VWARD_PROPOSED:-${VWARD_ROOT_PREFIX:-}/opt/var/lib/vward/agents/proposed.tsv}

# vward_agent_mode AGENT: act or watch.
vward_agent_mode() {
    _vam_one='' _vam_all=''
    if [ -r "$VWARD_AGENTS_CONF" ]; then
        while IFS='=' read -r _vam_k _vam_v; do
            case "$_vam_k" in all) _vam_all=$_vam_v ;; "$1") _vam_one=$_vam_v ;; esac
        done < "$VWARD_AGENTS_CONF"
    fi
    case "$_vam_one" in act|watch) ;; *) _vam_one=$_vam_all ;; esac
    case "$_vam_one" in act) echo act ;; *) echo watch ;; esac
}

# vward_agent_acts AGENT ACTION TEXT: 0 the agent acts; 1 it only watches, and the action is
# written down (time, agent, action, text; the same action of the same agent once an hour,
# the last 200 kept).
vward_agent_acts() {
    [ "$(vward_agent_mode "$1")" = watch ] || return 0
    _vaa_now=$(date +%s)
    mkdir -p "${VWARD_PROPOSED%/*}" 2>/dev/null || return 1
    _vaa_last=$(awk -F'\t' -v a="$1" -v x="$2" '$2 == a && $3 == x {t = $1} END {print t + 0}' "$VWARD_PROPOSED" 2>/dev/null)
    case "$_vaa_last" in ''|*[!0-9]*) _vaa_last=0 ;; esac
    [ $((_vaa_now - _vaa_last)) -lt 3600 ] && return 1
    printf '%s\t%s\t%s\t%s\n' "$_vaa_now" "$1" "$2" "$(printf '%s' "$3" | tr '\000-\037\177' ' ')" >> "$VWARD_PROPOSED" 2>/dev/null
    [ "$(wc -l < "$VWARD_PROPOSED")" -le 220 ] ||
        { tail -n 200 "$VWARD_PROPOSED" > "$VWARD_PROPOSED.$$" && mv -f "$VWARD_PROPOSED.$$" "$VWARD_PROPOSED"; } 2>/dev/null
    return 1
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
# An update is stopping or replacing VWARD's programs: nothing is started meanwhile.
vward_update_pending() {
    [ -e "${VWARD_ROOT_PREFIX:-}/tmp/vward-update-requested" ] || [ -e "${VWARD_ROOT_PREFIX:-}/tmp/vward-update.lock" ]
}

vward_agent_ask() {
    # Capitals too: Keenetic names its tunnels with them (without them every
    # «engine-kick:OpkgTun2» of the tunnel guard was refused before it was sent).
    case "$1" in ''|*[!A-Za-z0-9:._-]*) return 64 ;; esac
    # During an update the components agent is stopped on purpose: asking would start it.
    ! vward_update_pending || return 75
    mkdir -p "$VWARD_AGENT_REQ" 2>/dev/null || return 1
    # Who asks (VWARD_ACTOR), for the journals: «started by the components agent, asked by…».
    printf '%s\n' "${VWARD_ACTOR:-}" | tr -cd 'A-Za-z0-9 ._:=\n-' > "$VWARD_AGENT_REQ/$1" 2>/dev/null || return 1
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
