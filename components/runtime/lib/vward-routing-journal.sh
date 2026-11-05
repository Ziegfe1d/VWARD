#!/bin/sh
# RS-7 stage 2: durable write-ahead journal for FUTURE routing operations.
# Defines functions only; loading does nothing. NOTHING here touches Keenetic, AGH,
# VPN or DNS: the journal records what a writer intends and proves, it never acts.
# No writer is connected to it in this stage; it is exercised on test data only.
#
# Layout: JDIR (absolute, private 0700, owned by the caller) holds one directory per
# operation, JDIR/<OPID>/, with records written atomically (tmp + rename + sync):
#   plan      what is proposed and why (from a vward_routing_plan row)
#   pending   written BEFORE any mutation: pre-image and expected post-image hashes
#   done      completion proven: the current image equals the expected post-image
#   failed    proven NOT applied: the current image still equals the pre-image
#   unknown   anything else (lost API reply, TERM, mismatch, corrupt record)
#   resolved  later evidence-based resolution of an unknown operation (done|failed)
#   pre       private copy of the pre-image (compensation evidence, never replayed)
# State of an operation (precedence): resolved > unknown > done|failed > pending > plan.
# A corrupt/contradictory record is `unknown`. PENDING or UNKNOWN anywhere blocks every
# new operation (vward_journal_gate). An operation id is used once: no replay, ever.
#
#   vward_journal_plan    JDIR OPID PLANFILE DOMAIN SOURCE OWNER IDENTITY
#   vward_journal_begin   JDIR OPID GENERATION PRE_IMAGE POST_IMAGE CHECKS
#   vward_journal_finish  JDIR OPID CURRENT_IMAGE
#   vward_journal_unknown JDIR OPID REASON          (lost reply, TERM handler, write fault)
#   vward_journal_recover JDIR CURDIR               (after restart: classify, never replay)
#   vward_journal_status  JDIR                      (OPID<TAB>STATE<TAB>REASON, sorted)
#   vward_journal_gate    JDIR                      (rc 0 clear, rc 75 blocked)
# rc: 0 ok; 1 write/IO failure (nothing new may be done); 2 invalid usage/input;
# 75 refused by the safety rules (busy, gate closed, replay, not eligible).

# v2 keeps an immutable typed parent plan and per-step pre/post images. The v1
# parser deliberately sees these operation directories as unknown (no accidental
# downgrade/replay). These functions ONLY record evidence; no executor is loaded.
vrj2_id() { vrj_id "$1" && [ "${#1}" -le 32 ]; }
vrj2_seq() { case $1 in ''|0*|*[!0-9]*) return 2 ;; esac; [ "${#1}" -le 4 ] && [ "$1" -le 4096 ]; }
vrj2_gen() { printf '%s\n' "$1" | grep -Eq '^g-[0-9a-f]{16}$'; }
vrj2_file() {
    [ -f "$1" ] && [ ! -L "$1" ] && [ -O "$1" ] && [ -r "$1" ] || return 2
    case $(ls -ldn "$1" | awk '{print substr($1,1,10)}') in -rw-------|-r--------) ;; *) return 2 ;; esac
    [ "$(wc -c < "$1")" -le 1048576 ]
}
vrj2_pid_start() {
    [ -r "/proc/$1/stat" ] || return 1
    IFS= read -r vrj2_ps < "/proc/$1/stat" || return 1
    vrj2_ps=${vrj2_ps##*) }
    # shellcheck disable=SC2086
    set -- $vrj2_ps
    [ "$#" -ge 20 ] || return 1
    shift 19
    case $1 in ''|*[!0-9]*) return 1 ;; esac
    printf '%s\n' "$1"
}
# Requires the shared admission library's cooperative election. v1 below
# remains a separate parser/protocol; no state2 worker falls back to its lock.
vrj2_take_under_gate() {
    [ ! -e "$1/.reclaim" ] && [ ! -L "$1/.reclaim" ] || return 75
    if ! vward_lock_gate_exec mkdir "$1/.lock" 2>/dev/null; then
        vrj_dir "$1/.lock" && vrj2_file "$1/.lock/pid" && vrj2_file "$1/.lock/pid_start" || return 75
        vrj2_file "$1/.lock/owner" && vrj2_file "$1/.lock/owner.sha" || return 75
        [ "$(vrj_hash "$1/.lock/owner")" = "$(cat "$1/.lock/owner.sha")" ] || return 75
        vrj2_old=$(cat "$1/.lock/pid");vrj2_os=$(cat "$1/.lock/pid_start")
        vrj2_old_boot=$(vward_lock_boot_id "$1/.lock/boot") || return 75
        [ "$(cat "$1/.lock/owner")" = "$(printf '%s\t%s\t%s' "$vrj2_old" "$vrj2_os" "$vrj2_old_boot")" ] || return 75
        case $vrj2_old:$vrj2_os in *[!0-9:]*|:*|*:) return 75 ;; esac
        vrj2_alive_rc=0;vward_lock_gate_live "$vrj2_old_boot.$vrj2_old.$vrj2_os" || vrj2_alive_rc=$?
        [ "$vrj2_alive_rc" = 1 ] || return 75
        # Every new acquirer is inside the SAME actual-PID election here.
        vward_lock_gate_exec rm -rf "$1/.lock" && vward_lock_gate_exec mkdir "$1/.lock" || return 75
    fi
    printf '%s\n' "$vrj2_me" > "$1/.lock/pid" && printf '%s\n' "$vrj2_start" > "$1/.lock/pid_start" &&
        printf '%s\n' "$vrj2_boot" > "$1/.lock/boot" && printf '%s\t%s\t%s\n' "$vrj2_me" "$vrj2_start" "$vrj2_boot" > "$1/.lock/owner" &&
        vrj_hash "$1/.lock/owner" > "$1/.lock/owner.sha"
}
vrj2_lock() {
    vrj_lock_runtime || return 75
    IFS=' ' read -r vrj2_me _ < /proc/self/stat || return 1
    vrj2_start=$(vrj2_pid_start "$vrj2_me") || return 1
    IFS= read -r vrj2_boot < /proc/sys/kernel/random/boot_id || return 1
    vward_lock_gate_enter "$1/.lock" || return 75
    vrj2_take_rc=0;vrj2_take_under_gate "$1" || vrj2_take_rc=$?
    vward_lock_gate_leave "$1/.lock" || return 75
    return "$vrj2_take_rc"
}
vrj2_unlock() {
    [ ! -L "$1/.lock" ] && [ "$(cat "$1/.lock/pid" 2>/dev/null)" = "${vrj2_me:-}" ] &&
        [ "$(cat "$1/.lock/pid_start" 2>/dev/null)" = "${vrj2_start:-}" ] &&
        [ "$(vward_lock_boot_id "$1/.lock/boot")" = "${vrj2_boot:-}" ] || return 1
    vward_lock_release "$1/.lock"
}
# Batch atomic files then ONE compulsory flush per journal boundary. The caller
# cannot disable this flush with VWARD_JOURNAL_SYNC; no mutation follows a failure.
vrj2_put() { VWARD_JOURNAL_SYNC=0 vrj_put "$1" "$2"; }
vrj2_flush() { command -v sync >/dev/null 2>&1 && sync; }
vrj2_plan_valid() {
    [ -f "$1" ] && [ ! -L "$1" ] && [ "$(wc -c < "$1")" -le 1048576 ] || return 2
    LC_ALL=C awk -F'\t' '
        NR>4096 {bad=1}
        NR==1 {if(NF!=4 || $1!="routing-plan" || $2!=2 || $3!~/^g-[0-9a-f]+$/ || length($3)!=18 || $4!="denied") bad=1;next}
        {
            if(NF!=11 || $1!="step" || $2!=++n || $3!~/^(create|add|remove|move)$/ ||
               $4!~/^(route|dns|group|dns-scope|nativeproof|claims|choice|manifest|proof|registry|saved|queue|policy|tombstone)$/ ||
               length($5)>64 || $6==$7) bad=1
            if($4=="choice") {if($5!~/^[a-z0-9][a-z0-9.@_-]*$/ || length($5)>63)bad=1}
            else if($5!~/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/)bad=1
            for(i=1;i<=NF;i++) if($i!~/^[A-Za-z0-9_.:@,|\/-]+$/ || index($i,"//")) bad=1
        }
        END{exit (NR>0 && !bad) ? 0 : 2}' "$1"
}
vrj2_ready() {
    vrj_dir "$1" && vrj2_id "$2" && vrj_dir "$1/$2" || return 2
    for vrj2_f in schema plan plan.sha state generation; do vrj2_file "$1/$2/$vrj2_f" || return 2; done
    [ "$(cat "$1/$2/schema")" = "$(printf 'routing-journal\t2')" ] || return 2
    vrj2_digest=$(vrj_hash "$1/$2/plan") || return 2
    [ "$vrj2_digest" = "$(cat "$1/$2/plan.sha")" ] && vrj2_plan_valid "$1/$2/plan" || return 2
    vrj2_gen "$(cat "$1/$2/generation")" || return 2
    case $(cat "$1/$2/state") in planned|pending|unknown|committed|compensated) ;; *) return 2 ;; esac
}
vrj2_step_row() { awk -F'\t' -v n="$2" '$1=="step" && $2==n {print;found=1} END{exit found?0:1}' "$1/plan"; }
vrj2_decode() { printf '%s\n' "$1" | tr '|' '\t'; }
vrj2_step_valid() {
    vrj2_seq "$3" && vrj_dir "$1/$2/step.$3" || return 2
    vrj2_row=$(vrj2_step_row "$1/$2" "$3") || return 2
    vrj2_pre=$(printf '%s\n' "$vrj2_row" | cut -f6);vrj2_post=$(printf '%s\n' "$vrj2_row" | cut -f7)
    for vrj2_f in pre post state generation; do vrj2_file "$1/$2/step.$3/$vrj2_f" || return 2; done
    [ "$(vrj2_decode "$vrj2_pre")" = "$(cat "$1/$2/step.$3/pre")" ] &&
        [ "$(vrj2_decode "$vrj2_post")" = "$(cat "$1/$2/step.$3/post")" ] || return 2
    case $(cat "$1/$2/step.$3/state") in pending|done|failed|unknown|compensating|compensated) ;; *) return 2 ;; esac
}
vrj2_gate_except() (
    [ "$#" -eq 2 ] && vrj_dir "$1" || return 2
    for vrj2_d in "$1"/*; do
        [ -e "$vrj2_d" ] || [ -L "$vrj2_d" ] || continue
        vrj2_op=${vrj2_d##*/};vrj2_id "$vrj2_op" || return 75
        [ "$vrj2_op" != "$2" ] || continue
        if [ -e "$vrj2_d/schema" ]; then
            vrj2_ready "$1" "$vrj2_op" || return 75
            for vrj2_s in "$vrj2_d"/step.*; do
                [ -e "$vrj2_s" ] || [ -L "$vrj2_s" ] || continue
                vrj2_step_valid "$1" "$vrj2_op" "${vrj2_s##*/step.}" || return 75
                case $(cat "$vrj2_s/state") in pending|unknown|compensating) return 75 ;; esac
                [ "$(cat "$vrj2_d/state")" != planned ] || return 75
                if [ "$(cat "$vrj2_d/state")" = compensated ]; then
                    case $(cat "$vrj2_s/state") in compensated|failed) ;; *) return 75 ;; esac
                fi
            done
            case $(cat "$vrj2_d/state") in pending|unknown) return 75 ;; esac
            if [ "$(cat "$vrj2_d/state")" = committed ]; then
                vrj2_count=$(awk -F'\t' '$1=="step"{n++} END{print n+0}' "$vrj2_d/plan")
                vrj2_n=1
                while [ "$vrj2_n" -le "$vrj2_count" ]; do
                    vrj2_step_valid "$1" "$vrj2_op" "$vrj2_n" && [ "$(cat "$vrj2_d/step.$vrj2_n/state")" = 'done' ] || return 75
                    vrj2_n=$((vrj2_n+1))
                done
                if awk -F'\t' '$1=="step" && $4~/^(route|dns|group|dns-scope)$/{f=1} END{exit f?0:1}' "$vrj2_d/plan"; then
                    vrj2_file "$vrj2_d/save" && [ "$(cat "$vrj2_d/save")" = 'done' ] || return 75
                fi
            fi
            if [ "$(cat "$vrj2_d/state")" = compensated ]; then
                vrj2_file "$vrj2_d/resolved" && vrj2_file "$vrj2_d/resolved.sha" || return 75
                [ "$(vrj_hash "$vrj2_d/resolved")" = "$(cat "$vrj2_d/resolved.sha")" ] &&
                    [ "$(vrj_get "$vrj2_d/resolved" plan_sha "$vrj2_op")" = "$(cat "$vrj2_d/plan.sha")" ] &&
                    [ "$(vrj_get "$vrj2_d/resolved" result "$vrj2_op")" = compensated ] || return 75
            fi
        else
            case $(vrj_state "$1" "$vrj2_op" | cut -f1) in done|failed|resolved|plan) ;; *) return 75 ;; esac
        fi
    done
)
vward_journal2_gate() (
    [ "$#" -eq 1 ] || return 2
    vrj2_gate_except "$1" ""
)
vward_journal2_plan() (
    umask 077
    [ "$#" -eq 3 ] && vrj_dir "$1" && vrj2_id "$2" && vrj2_plan_valid "$3" || return 2
    vrj2_lock "$1" || return $?
    trap 'vrj2_unlock "$1"' EXIT
    vward_journal2_gate "$1" || return 75
    [ ! -e "$1/$2" ] && [ ! -L "$1/$2" ] || return 75
    mkdir "$1/$2" || return 1
    vrj2_text=$(cat "$3");vrj2_generation=$(printf '%s\n' "$vrj2_text" | head -n1 | cut -f3)
    vrj2_put "$1/$2/schema" "$(printf 'routing-journal\t2')" && vrj2_put "$1/$2/plan" "$vrj2_text" &&
        vrj2_put "$1/$2/plan.sha" "$(vrj_hash "$1/$2/plan")" && vrj2_put "$1/$2/state" planned &&
        vrj2_put "$1/$2/generation" "$vrj2_generation" && vrj2_flush
)
vward_journal2_begin() (
    umask 077
    [ "$#" -eq 5 ] && vrj2_seq "$3" && vrj2_gen "$4" && vrj2_file "$5" || return 2
    vrj2_ready "$1" "$2" || return 2
    vrj2_lock "$1" || return $?
    trap 'vrj2_unlock "$1"' EXIT
    case $(cat "$1/$2/state") in planned|pending) ;; *) return 75 ;; esac
    vrj2_gate_except "$1" "$2" || return 75
    [ "$(cat "$1/$2/generation")" = "$4" ] || return 75
    [ ! -e "$1/$2/step.$3" ] && [ ! -L "$1/$2/step.$3" ] || return 75
    vrj2_n=1
    while [ "$vrj2_n" -lt "$3" ]; do
        vrj2_step_valid "$1" "$2" "$vrj2_n" && [ "$(cat "$1/$2/step.$vrj2_n/state")" = 'done' ] || return 75
        vrj2_n=$((vrj2_n+1))
    done
    vrj2_row=$(vrj2_step_row "$1/$2" "$3") || return 2
    vrj2_pre=$(printf '%s\n' "$vrj2_row" | cut -f6);vrj2_post=$(printf '%s\n' "$vrj2_row" | cut -f7)
    [ "$(vrj2_decode "$vrj2_pre")" = "$(cat "$5")" ] || return 75
    mkdir "$1/$2/step.$3" || return 1
    vrj2_put "$1/$2/step.$3/pre" "$(vrj2_decode "$vrj2_pre")" &&
        vrj2_put "$1/$2/step.$3/post" "$(vrj2_decode "$vrj2_post")" &&
        vrj2_put "$1/$2/step.$3/generation" "$4" && vrj2_put "$1/$2/step.$3/state" pending &&
        vrj2_put "$1/$2/state" pending && vrj2_flush
)
vward_journal2_finish() (
    umask 077
    [ "$#" -eq 5 ] && vrj2_gen "$4" && vrj2_file "$5" || return 2
    vrj2_ready "$1" "$2" && vrj2_step_valid "$1" "$2" "$3" || return 2
    vrj2_lock "$1" || return $?
    trap 'vrj2_unlock "$1"' EXIT
    case $(cat "$1/$2/state") in pending|unknown) ;; *) return 75 ;; esac
    case $(cat "$1/$2/step.$3/state") in pending|unknown) ;; *) return 75 ;; esac
    vrj2_rc=3;vrj2_result=unknown
    if cmp -s "$5" "$1/$2/step.$3/post"; then vrj2_result='done';vrj2_rc=0
    elif cmp -s "$5" "$1/$2/step.$3/pre"; then vrj2_result=failed;vrj2_rc=1;fi
    vrj2_put "$1/$2/step.$3/observed" "$(cat "$5")" && vrj2_put "$1/$2/step.$3/state" "$vrj2_result" || return 1
    if [ "$vrj2_result" = 'done' ]; then vrj2_put "$1/$2/generation" "$4" || return 1;fi
    [ "$vrj2_result" != unknown ] || vrj2_put "$1/$2/state" unknown || return 1
    vrj2_flush || return 1
    return "$vrj2_rc"
)
vward_journal2_saved() (
    umask 077
    [ "$#" -eq 3 ] && vrj2_ready "$1" "$2" || return 2
    case $3 in pending|done|failed|unknown) ;; *) return 2 ;; esac
    vrj2_lock "$1" || return $?
    trap 'vrj2_unlock "$1"' EXIT
    case $(cat "$1/$2/state") in pending|unknown) ;; *) return 75 ;; esac
    vrj2_put "$1/$2/save" "$3" && vrj2_flush
)
vward_journal2_commit() (
    umask 077
    [ "$#" -eq 3 ] && vrj2_gen "$3" && vrj2_ready "$1" "$2" || return 2
    vrj2_lock "$1" || return $?
    trap 'vrj2_unlock "$1"' EXIT
    [ "$(cat "$1/$2/state")" = pending ] && [ "$(cat "$1/$2/generation")" = "$3" ] || return 75
    vrj2_count=$(awk -F'\t' '$1=="step"{n++} END{print n+0}' "$1/$2/plan")
    vrj2_n=1
    while [ "$vrj2_n" -le "$vrj2_count" ]; do
        vrj2_step_valid "$1" "$2" "$vrj2_n" && [ "$(cat "$1/$2/step.$vrj2_n/state")" = 'done' ] || return 75
        vrj2_n=$((vrj2_n+1))
    done
    if awk -F'\t' '$1=="step" && $4~/^(route|dns|group|dns-scope)$/{found=1} END{exit found?0:1}' "$1/$2/plan"; then
        vrj2_file "$1/$2/save" && [ "$(cat "$1/$2/save")" = 'done' ] || return 75
    fi
    vrj2_put "$1/$2/state" committed && vrj2_flush
)

vward_journal2_unknown() (
    umask 077
    [ "$#" -eq 3 ] && vrj_tok "$3" && vrj2_ready "$1" "$2" || return 2
    vrj2_lock "$1" || return $?
    trap 'vrj2_unlock "$1"' EXIT
    case $(cat "$1/$2/state") in planned|pending|unknown) ;; *) return 75 ;; esac
    vrj2_put "$1/$2/reason" "$3" && vrj2_put "$1/$2/state" unknown && vrj2_flush
)

# The inverse is authorised only from the immutable full post-image, or a
# GROUP/DNS-SCOPE prefix whose hash was included BEFORE the original write.
# Nothing is executed here; a worker still must compare its fresh actual scope.
vward_journal2_compensating() (
    umask 077
    [ "$#" -eq 4 ] && vrj2_file "$4" && vrj2_ready "$1" "$2" && vrj2_step_valid "$1" "$2" "$3" || return 2
    vrj2_lock "$1" || return $?
    trap 'vrj2_unlock "$1"' EXIT
    case $(cat "$1/$2/state") in pending|unknown) ;; *) return 75 ;; esac
    # A proved failure/finished inverse withdraws this write capability. If a
    # resource is recreated later, identical bytes alone do not grant replay.
    case $(cat "$1/$2/step.$3/state") in pending|unknown|done|compensating) ;; *) return 75 ;; esac
    vrj2_allowed=0
    if cmp -s "$4" "$1/$2/step.$3/post"; then vrj2_allowed=1
    else
        vrj2_observed=$(cat "$4")
        vrj2_row=$(vrj2_step_row "$1/$2" "$3") || return 2
        if printf '%s\n' "$vrj2_row" | awk -F'\t' -v h="$vrj2_observed" '
            ($4~/^(group|dns-scope)$/ || ($4=="saved" && $5=="routing-state")) && h~/^[0-9a-f]+$/ && length(h)==64 {
                n=split($10,a,",");for(i=1;i<=n;i++) if(a[i]=="prefix:" h) found=1
            } END{exit found?0:1}'; then vrj2_allowed=1;fi
    fi
    [ "$vrj2_allowed" = 1 ] || return 75
    vrj2_put "$1/$2/step.$3/inverse.from" "$(cat "$4")" &&
        vrj2_put "$1/$2/step.$3/state" compensating && vrj2_flush
)
vward_journal2_compensated() (
    umask 077
    [ "$#" -eq 5 ] && vrj2_gen "$4" && vrj2_file "$5" && vrj2_ready "$1" "$2" && vrj2_step_valid "$1" "$2" "$3" || return 2
    vrj2_lock "$1" || return $?
    trap 'vrj2_unlock "$1"' EXIT
    case $(cat "$1/$2/state") in pending|unknown) ;; *) return 75 ;; esac
    cmp -s "$5" "$1/$2/step.$3/pre" || return 75
    vrj2_put "$1/$2/step.$3/state" compensated && vrj2_put "$1/$2/generation" "$4" && vrj2_flush
)
vward_journal2_rollback_saved() (
    umask 077
    [ "$#" -eq 3 ] && vrj2_ready "$1" "$2" || return 2
    case $3 in pending|done|failed|unknown) ;; *) return 2 ;; esac
    vrj2_lock "$1" || return $?
    trap 'vrj2_unlock "$1"' EXIT
    case $(cat "$1/$2/state") in pending|unknown) ;; *) return 75 ;; esac
    vrj2_put "$1/$2/rollback-save" "$3" && vrj2_flush
)

# Baseline proof is supplied as private readbacks step.N for the EARLIEST image
# of each kind/resource, after all inverses. It permits unrelated foreign edits:
# only this operation own scopes are compared, not a whole-file restore.
vward_journal2_abort() (
    umask 077
    [ "$#" -eq 4 ] && vrj2_gen "$3" && vrj_dir "$4" && vrj2_ready "$1" "$2" || return 2
    vrj2_lock "$1" || return $?
    trap 'vrj2_unlock "$1"' EXIT
    case $(cat "$1/$2/state") in planned|pending|unknown) ;; *) return 75 ;; esac
    [ "$(cat "$4/generation" 2>/dev/null)" = "$3" ] || return 75
    vrj2_need_save=0
    for vrj2_step in "$1/$2"/step.*; do
        [ -e "$vrj2_step" ] || [ -L "$vrj2_step" ] || continue
        vrj2_n=${vrj2_step##*/step.}
        vrj2_step_valid "$1" "$2" "$vrj2_n" || return 75
        case $(cat "$vrj2_step/state") in compensated|failed) ;; *) return 75 ;; esac
        if [ -e "$vrj2_step/inverse.from" ]; then
            vrj2_row=$(vrj2_step_row "$1/$2" "$vrj2_n") || return 2
            case $(printf '%s\n' "$vrj2_row" | cut -f4) in route|dns|group|dns-scope) vrj2_need_save=1 ;; esac
        fi
    done
    vrj2_list=$(awk -F'\t' '$1=="step" && !seen[$4 SUBSEP $5]++ {print $2}' "$1/$2/plan")
    for vrj2_n in $vrj2_list; do
        vrj2_file "$4/step.$vrj2_n" || return 75
        vrj2_row=$(vrj2_step_row "$1/$2" "$vrj2_n") || return 2
        vrj2_pre=$(printf '%s\n' "$vrj2_row" | cut -f6)
        [ "$(cat "$4/step.$vrj2_n")" = "$(vrj2_decode "$vrj2_pre")" ] || return 75
    done
    if [ "$vrj2_need_save" = 1 ]; then
        vrj2_file "$1/$2/rollback-save" && [ "$(cat "$1/$2/rollback-save")" = 'done' ] || return 75
    fi
    vrj2_receipt=$(printf 'record=resolved\nopid=%s\nplan_sha=%s\ngeneration=%s\nresult=compensated' "$2" "$(cat "$1/$2/plan.sha")" "$3")
    vrj2_put "$1/$2/resolved" "$vrj2_receipt" && vrj2_put "$1/$2/resolved.sha" "$(vrj_hash "$1/$2/resolved")" &&
        vrj2_put "$1/$2/generation" "$3" && vrj2_put "$1/$2/state" compensated && vrj2_flush
)

# Closed tokens only: no spaces, no quotes, no URL ("//"), so no secret can be stored.
vrj_tok() { case $1 in ''|*[!A-Za-z0-9_.:@,/-]*|*//*) return 1 ;; esac; [ "${#1}" -le 256 ]; }
vrj_id() { case $1 in ''|[!A-Za-z0-9]*|*[!A-Za-z0-9_.:-]*) return 1 ;; esac; [ "${#1}" -le 64 ]; }

vrj_dir() {
    case $1 in /*) ;; *) return 2 ;; esac
    [ -d "$1" ] && [ ! -L "$1" ] && [ -O "$1" ] && [ -w "$1" ] || return 2
    [ "$(ls -ldn "$1" 2>/dev/null | awk '{print substr($1,1,10)}')" = drwx------ ] || return 2
}

# Atomic durable record: tmp, rename, sync. A failure leaves the previous state intact.
vrj_put() {
    vrj_tmp="$1.tmp.$$"
    if ! (umask 077; printf '%s\n' "$2" > "$vrj_tmp") 2>/dev/null; then rm -f "$vrj_tmp" 2>/dev/null; return 1; fi
    if ! mv -f "$vrj_tmp" "$1" 2>/dev/null; then rm -f "$vrj_tmp" 2>/dev/null; return 1; fi
    [ "${VWARD_JOURNAL_SYNC:-1}" = 0 ] || ! command -v sync >/dev/null 2>&1 || sync
    return 0
}

vrj_hash() {
    [ -f "$1" ] && [ ! -L "$1" ] && [ -r "$1" ] || return 1
    [ "$(wc -c < "$1")" -le 1048576 ] || return 1
    vrj_h=$(sha256sum < "$1" 2>/dev/null) || return 1
    vrj_h=${vrj_h%% *}
    case $vrj_h in [0-9a-f]*) [ "${#vrj_h}" = 64 ] && printf '%s\n' "$vrj_h" ;; *) return 1 ;; esac
}

# Value of KEY in a record, only if the record is well formed for OPID.
vrj_get() {
    [ -f "$1" ] && [ ! -L "$1" ] || return 1
    awk -F= -v k="$2" -v op="$3" '
        NF < 2 || $1 !~ /^[a-z_]+$/ || substr($0, length($1) + 2) !~ /^[A-Za-z0-9_.:@,\/-]*$/ || index($0, "//") || seen[$1]++ { bad = 1 }
        $1 == "opid" && substr($0, 6) != op { bad = 1 }
        $1 == "opid" { has = 1 }
        $1 == k { v = substr($0, length($1) + 2); found = 1 }
        END { if (bad || !has || !found) exit 1; print v }' "$1"
}

# State of one operation directory: STATE<TAB>REASON.
vrj_state() {
    vrj_d=$1/$2
    vrj_r=; vrj_s=
    for vrj_f in plan pending 'done' failed unknown resolved; do
        [ -e "$vrj_d/$vrj_f" ] || [ -L "$vrj_d/$vrj_f" ] || continue
        if ! vrj_get "$vrj_d/$vrj_f" record "$2" >/dev/null; then printf 'unknown\tcorrupt-%s\n' "$vrj_f"; return 0; fi
    done
    if [ -e "$vrj_d/resolved" ]; then
        vrj_s=$(vrj_get "$vrj_d/resolved" result "$2"); vrj_r=$(vrj_get "$vrj_d/resolved" reason "$2")
        case $vrj_s in done|failed) printf '%s\t%s\n' "$vrj_s" "$vrj_r"; return 0 ;; esac
        printf 'unknown\tcorrupt-resolved\n'; return 0
    fi
    if [ -e "$vrj_d/unknown" ]; then printf 'unknown\t%s\n' "$(vrj_get "$vrj_d/unknown" reason "$2")"; return 0; fi
    if [ -e "$vrj_d/done" ] && [ -e "$vrj_d/failed" ]; then printf 'unknown\tcontradictory\n'; return 0; fi
    if [ -e "$vrj_d/done" ] || [ -e "$vrj_d/failed" ]; then
        [ -e "$vrj_d/pending" ] || { printf 'unknown\tterminal-without-pending\n'; return 0; }
        for vrj_s in 'done' failed; do [ -e "$vrj_d/$vrj_s" ] && printf '%s\t%s\n' "$vrj_s" "$(vrj_get "$vrj_d/$vrj_s" reason "$2")"; done
        return 0
    fi
    if [ -e "$vrj_d/pending" ]; then
        [ -e "$vrj_d/plan" ] || { printf 'unknown\tpending-without-plan\n'; return 0; }
        printf 'pending\tunproven\n'; return 0
    fi
    if [ -e "$vrj_d/plan" ]; then printf 'plan\t%s\n' "$(vrj_get "$vrj_d/plan" reason "$2")"; return 0; fi
    printf 'void\tno-record\n'
}

# Existing v1 may contend with v2 on the SAME directory before its parser
# refuses state2. Its lock/release must participate in the same election.
vrj_lock_runtime() {
    command -v vward_lock_gate_enter >/dev/null 2>&1 && return 0
    vrj_admission_lib=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
    [ -r "$vrj_admission_lib" ] || return 75
    # Existing trusted runtime-library locator, not an executor/guard bypass.
    # shellcheck disable=SC1090
    . "$vrj_admission_lib"
    command -v vward_lock_gate_enter >/dev/null 2>&1
}
vrj_lock() {
    vrj_lock_runtime && vward_lock_take "$1/.lock" || return 75
}
vrj_unlock() { vward_lock_release "$1/.lock"; }

vward_journal_status() (
    [ "$#" -eq 1 ] || return 2
    vrj_dir "$1" || return 2
    for vrj_o in "$1"/*; do
        [ -d "$vrj_o" ] && [ ! -L "$vrj_o" ] || continue
        vrj_i=${vrj_o##*/}
        if vrj_id "$vrj_i"; then printf '%s\t%s\n' "$vrj_i" "$(vrj_state "$1" "$vrj_i")"
        else printf '%s\tunknown\tbad-operation-name\n' invalid-entry; fi
    done | LC_ALL=C sort
)

vward_journal_gate() (
    [ "$#" -eq 1 ] || return 2
    vrj_out=$(vward_journal_status "$1") || return 2
    vrj_block=$(printf '%s\n' "$vrj_out" | awk -F'\t' '$2 == "pending" || $2 == "unknown"')
    [ -z "$vrj_block" ] && return 0
    printf '%s\n' "$vrj_block"
    return 75
)

vward_journal_plan() (
    [ "$#" -eq 7 ] || return 2
    vrj_dir "$1" || return 2
    vrj_id "$2" || return 2
    case $4 in ''|*[!a-z0-9.-]*) return 2 ;; esac
    case $5 in M|S|A|-) ;; *) return 2 ;; esac
    case $6 in vward|manual|unknown) ;; *) return 2 ;; esac
    case $7 in verified|reference-only|unknown) ;; *) return 2 ;; esac
    [ -f "$3" ] && [ ! -L "$3" ] || return 2
    # Exactly one row of the planner for DOMAIN, all of it tokens.
    vrj_row=$(awk -F'\t' -v d="$4" '$1 == d {n++; r=$0} END {if (n == 1) print r; else exit 1}' "$3") || return 2
    vrj_rec=$(printf '%s\n' "$vrj_row" | awk -F'\t' -v op="$2" -v src="$5" -v own="$6" -v idn="$7" '
        NF != 9 || $2 !~ /^(none|add)$/ || $5 !~ /^(yes|no)$/ || $9 !~ /^g-[0-9a-f]{16}$/ { exit 1 }
        { for (i = 1; i <= 9; i++) if ($i !~ /^[A-Za-z0-9_.:@,\/-]+$/ || index($i, "//")) exit 1
          printf "record=plan\nopid=%s\ngeneration=%s\nsource=%s\nowner=%s\nidentity=%s\naction=%s\ndomain=%s\ntarget=%s\ndns=%s\neligible=%s\npermit=%s\nneeds=%s\nreason=%s\n", op, $9, src, own, idn, $2, $1, $3, $4, $5, $6, $7, $8 }') || return 2
    vrj_lock "$1" || return $?
    # An operation id is used once. A directory left by a crash during this very call is
    # empty (void) and may be re-planned; anything recorded is never overwritten.
    if [ -e "$1/$2" ] || [ -L "$1/$2" ]; then
        if [ -d "$1/$2" ] && [ ! -L "$1/$2" ] && [ "$(vrj_state "$1" "$2" | cut -f1)" = void ]; then :
        else vrj_unlock "$1"; return 75; fi
    fi
    (umask 077; mkdir -p "$1/$2") 2>/dev/null || { vrj_unlock "$1"; return 1; }
    vrj_put "$1/$2/plan" "$vrj_rec" || { vrj_unlock "$1"; return 1; }
    vrj_unlock "$1"
)

# vward_journal_begin: the ONLY door before a mutation. rc 0 = the caller may act now.
vward_journal_begin() (
    [ "$#" -eq 6 ] || return 2
    vrj_dir "$1" || return 2
    vrj_id "$2" || return 2
    printf '%s\n' "$3" | grep -Eq '^g-[0-9a-f]{16}$' || return 2
    vrj_tok "$6" || return 2
    vrj_pre=$(vrj_hash "$4") || return 2
    vrj_post=$(vrj_hash "$5") || return 2
    vrj_lock "$1" || return $?
    vrj_fail() { vrj_unlock "$1"; return "$2"; }
    [ -d "$1/$2" ] && [ ! -L "$1/$2" ] || { vrj_fail "$1" 75; return 75; }
    # Every unresolved operation (pending/unknown, this one or another) closes the gate.
    vrj_blk=$(vward_journal_status "$1" | awk -F'\t' '$2 == "pending" || $2 == "unknown"')
    [ -z "$vrj_blk" ] || { vrj_fail "$1" 75; return 75; }
    [ "$(vrj_state "$1" "$2" | cut -f1)" = plan ] || { vrj_fail "$1" 75; return 75; }
    vrj_p=$1/$2/plan
    # The plan must be sound AND still describe the current snapshot AND own the resource.
    [ "$(vrj_get "$vrj_p" eligible "$2")" = yes ] || { vrj_fail "$1" 75; return 75; }
    [ "$(vrj_get "$vrj_p" generation "$2")" = "$3" ] || { vrj_fail "$1" 75; return 75; }
    [ "$(vrj_get "$vrj_p" identity "$2")" = verified ] || { vrj_fail "$1" 75; return 75; }
    [ "$(vrj_get "$vrj_p" owner "$2")" = vward ] || { vrj_fail "$1" 75; return 75; }
    [ "$(vrj_get "$vrj_p" action "$2")" != none ] || { vrj_fail "$1" 75; return 75; }
    [ "$vrj_pre" != "$vrj_post" ] || { vrj_fail "$1" 75; return 75; }
    # Pre-image first (private evidence), then the pending record. Either failing = no start.
    if ! (umask 077; cp "$4" "$1/$2/pre.tmp.$$" && mv -f "$1/$2/pre.tmp.$$" "$1/$2/pre") 2>/dev/null; then
        rm -f "$1/$2/pre.tmp.$$" 2>/dev/null; vrj_fail "$1" 1; return 1
    fi
    [ "$(vrj_hash "$1/$2/pre")" = "$vrj_pre" ] || { rm -f "$1/$2/pre"; vrj_fail "$1" 1; return 1; }
    vrj_put "$1/$2/pending" "record=pending
opid=$2
generation=$3
pre=$vrj_pre
post=$vrj_post
checks=$6
reason=prepared" || { rm -f "$1/$2/pre"; vrj_fail "$1" 1; return 1; }
    vrj_unlock "$1"
)

# Classify by evidence. Writes done/failed/unknown (or resolved for an unknown op).
vrj_classify() {
    vrj_st=$(vrj_state "$1" "$2" | cut -f1)
    case $vrj_st in pending|unknown) ;; *) return 75 ;; esac
    vrj_pre=$(vrj_get "$1/$2/pending" pre "$2") || vrj_pre=
    vrj_post=$(vrj_get "$1/$2/pending" post "$2") || vrj_post=
    vrj_cur=; [ -z "$3" ] || vrj_cur=$(vrj_hash "$3") || vrj_cur=
    if [ -z "$vrj_pre" ] || [ -z "$vrj_post" ]; then vrj_res=unknown vrj_why=pending-unreadable
    elif [ -z "$vrj_cur" ]; then vrj_res=unknown vrj_why=current-unavailable
    elif [ "$vrj_cur" = "$vrj_post" ]; then vrj_res='done' vrj_why=${4:-verified}
    elif [ "$vrj_cur" = "$vrj_pre" ]; then vrj_res=failed vrj_why=not-applied
    else vrj_res=unknown vrj_why=state-differs; fi
    if [ "$vrj_st" = unknown ]; then
        # Only evidence resolves an unknown operation; otherwise it stays unknown.
        [ "$vrj_res" != unknown ] || return 0
        vrj_put "$1/$2/resolved" "record=resolved
opid=$2
result=$vrj_res
current=$vrj_cur
reason=$vrj_why" || return 1
        return 0
    fi
    vrj_put "$1/$2/$vrj_res" "record=$vrj_res
opid=$2
current=${vrj_cur:-none}
reason=$vrj_why" || return 1
}

vward_journal_finish() (
    [ "$#" -eq 3 ] || return 2
    vrj_dir "$1" || return 2
    vrj_id "$2" || return 2
    [ "$(vrj_state "$1" "$2" | cut -f1)" = pending ] || return 75
    vrj_lock "$1" || return $?
    vrj_classify "$1" "$2" "$3" verified; vrj_rc=$?
    vrj_unlock "$1"
    return "$vrj_rc"
)

vward_journal_unknown() (
    [ "$#" -eq 3 ] || return 2
    vrj_dir "$1" || return 2
    vrj_id "$2" || return 2
    case $3 in ''|*[!a-z0-9-]*) return 2 ;; esac
    [ "$(vrj_state "$1" "$2" | cut -f1)" = pending ] || return 75
    vrj_lock "$1" || return $?
    vrj_put "$1/$2/unknown" "record=unknown
opid=$2
reason=$3"; vrj_rc=$?
    vrj_unlock "$1"
    return "$vrj_rc"
)

# After a restart: every pending/unknown operation is classified from the CURRENT image
# the caller re-read (CURDIR/<OPID>); a missing image keeps it unknown. Nothing is replayed,
# nothing is compensated here; leftover tmp files of a killed write are removed.
vward_journal_recover() (
    [ "$#" -eq 2 ] || return 2
    vrj_dir "$1" || return 2
    case $2 in /*) ;; *) return 2 ;; esac
    vrj_lock "$1" || return $?
    vrj_rc=0
    for vrj_o in "$1"/*; do
        [ -d "$vrj_o" ] && [ ! -L "$vrj_o" ] || continue
        vrj_i=${vrj_o##*/}
        vrj_id "$vrj_i" || continue
        rm -f "$vrj_o"/*.tmp.* 2>/dev/null
        case $(vrj_state "$1" "$vrj_i" | cut -f1) in
            pending|unknown)
                vrj_c=; [ ! -f "$2/$vrj_i" ] || [ -L "$2/$vrj_i" ] || vrj_c=$2/$vrj_i
                vrj_classify "$1" "$vrj_i" "$vrj_c" confirmed-after-restart || vrj_rc=1 ;;
        esac
    done
    vrj_unlock "$1"
    return "$vrj_rc"
)
