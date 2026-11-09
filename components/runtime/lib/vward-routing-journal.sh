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
# Same verdict as printf '%s\n' "$1" | grep -Eq '^g-[0-9a-f]{16}$' (ANY line
# matches), with shell builtins: generations are checked hundreds of times.
vrj2_gen() {
    vrj2_gl=$1
    while :; do
        vrj2_g1=${vrj2_gl%%"$vrj_nl"*}
        case $vrj2_g1 in
            g-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) return 0 ;;
        esac
        [ "$vrj2_g1" != "$vrj2_gl" ] || return 1
        vrj2_gl=${vrj2_gl#*"$vrj_nl"}
    done
}
vrj_nl='
'
vrj_tab=$(printf '\t')
# Read-only metadata cache (process budget). ONE ls -ln over a set of
# directories records mode/links/uid/size of every listed entry, ONE
# sha256sum the plan digests and ONE awk the plan schema. It is set only
# inside a read-only validation subshell (gate, ready/step checks before a
# journal write) and consulted by the SAME predicates; any path the batch did
# not prove falls back to its own ls/sha256sum/awk. Writers clear it first.
vrj_mc_key() {
    vrj_mk=;vrj_mr=$1
    while [ -n "$vrj_mr" ]; do
        vrj_mcs=${vrj_mr%%[!A-Za-z0-9]*}
        if [ -n "$vrj_mcs" ]; then vrj_mk=$vrj_mk$vrj_mcs;vrj_mr=${vrj_mr#"$vrj_mcs"};continue;fi
        case $vrj_mr in
            /*) vrj_mk=${vrj_mk}_s ;; .*) vrj_mk=${vrj_mk}_d ;; :*) vrj_mk=${vrj_mk}_c ;;
            -*) vrj_mk=${vrj_mk}_h ;; _*) vrj_mk=${vrj_mk}_u ;; *) return 1 ;;
        esac
        vrj_mr=${vrj_mr#?}
    done
}
vrj_mc_off() { vrj_mc_base=; }
# vrj_mc_load BASE DIR... (every DIR is BASE or below it)
vrj_mc_load() {
    vrj_mc_base=;vrj_mc_b=$1;shift
    [ "$#" -gt 0 ] || return 0
    case $vrj_mc_b in /*) ;; *) return 0 ;; esac
    # shellcheck disable=SC2012
    vrj_mc_out=$(LC_ALL=C ls -ln "$@" 2>/dev/null) || return 0
    vrj_mc_cur=;[ "$#" -ne 1 ] || vrj_mc_cur=$1
    while IFS= read -r vrj_mc_l; do
        case $vrj_mc_l in
            '') continue ;;
            /*:) vrj_mc_cur=${vrj_mc_l%:};continue ;;
            total\ *) continue ;;
        esac
        case $vrj_mc_cur in "$vrj_mc_b") vrj_mc_rel= ;; "$vrj_mc_b"/*) vrj_mc_rel=${vrj_mc_cur#"$vrj_mc_b"/}/ ;; *) continue ;; esac
        vrj_mc_t=$vrj_mc_l;vrj_mc_f=
        # shellcheck disable=SC2034
        for vrj_mc_i in 1 2 3 4 5 6 7 8; do
            vrj_mc_w=${vrj_mc_t%%[ ]*};vrj_mc_f="$vrj_mc_f $vrj_mc_w"
            vrj_mc_t=${vrj_mc_t#*[ ]};vrj_mc_t=${vrj_mc_t#"${vrj_mc_t%%[! ]*}"}
        done
        case $vrj_mc_t in ''|[!A-Za-z0-9]*|*[!A-Za-z0-9_.:-]*) continue ;; esac
        # shellcheck disable=SC2086
        set -- $vrj_mc_f
        [ "$#" -eq 8 ] || continue
        vrj_mc_key "$vrj_mc_rel$vrj_mc_t" || continue
        eval "vrj_mc_$vrj_mk=\"\${1%\"\${1#??????????}\"} \$2 \$3 \$5\""
    done <<EOF
$vrj_mc_out
EOF
    vrj_mc_base=$vrj_mc_b
}
vrj_mc_get() {
    [ -n "${vrj_mc_base:-}" ] || return 1
    case $1 in "$vrj_mc_base"/*) ;; *) return 1 ;; esac
    vrj_mc_key "${1#"$vrj_mc_base"/}" || return 1
    eval "vrj_mv=\${vrj_mc_$vrj_mk-}"
    [ -n "$vrj_mv" ] || return 1
    # shellcheck disable=SC2086
    set -- $vrj_mv
    [ "$#" -eq 4 ] || return 1
    vrj_lmode=$1;vrj_llinks=$2;vrj_luid=$3;vrj_lsize=$4
}
# vrj_mc_plans PLAN...: digests (one sha256sum) and schema verdicts (one awk).
vrj_mc_plans() {
    [ -n "${vrj_mc_base:-}" ] && [ "$#" -gt 0 ] || return 0
    vrj_mc_sums=$(LC_ALL=C sha256sum "$@" 2>/dev/null) || vrj_mc_sums=
    if [ -n "$vrj_mc_sums" ]; then
        for vrj_mc_p in "$@"; do
            vrj_mc_l=${vrj_mc_sums%%"$vrj_nl"*};vrj_mc_sums=${vrj_mc_sums#"$vrj_mc_l"};vrj_mc_sums=${vrj_mc_sums#"$vrj_nl"}
            [ "${vrj_mc_l#*  }" = "$vrj_mc_p" ] || break
            vrj_mc_h=${vrj_mc_l%%  *}
            case $vrj_mc_h in *[!0-9a-f]*) break ;; esac
            [ "${#vrj_mc_h}" = 64 ] || break
            vrj_mc_key "${vrj_mc_p#"$vrj_mc_base"/}" || break
            eval "vrj_mh_$vrj_mk=\$vrj_mc_h"
        done
    fi
    vrj_mc_pv=$(vrj2_plan_awk "$@" 2>/dev/null) || return 0
    for vrj_mc_p in "$@"; do
        vrj_mc_key "${vrj_mc_p#"$vrj_mc_base"/}" || continue
        case "$vrj_nl$vrj_mc_pv$vrj_nl" in *"${vrj_nl}V$vrj_tab$vrj_mc_p$vrj_nl"*) eval "vrj_mp_$vrj_mk=0" ;; *) eval "vrj_mp_$vrj_mk=2" ;; esac
    done
}
vrj_mc_value() { # vrj_mc_value PREFIX PATH -> vrj_mv
    [ -n "${vrj_mc_base:-}" ] || return 1
    case $2 in "$vrj_mc_base"/*) ;; *) return 1 ;; esac
    vrj_mc_key "${2#"$vrj_mc_base"/}" || return 1
    eval "vrj_mv=\${$1_$vrj_mk-}"
    [ -n "$vrj_mv" ]
}
# vrj_ls PATH: fields of ONE ls -ldn, without an awk pipeline (these checks
# run hundreds of times per request): vrj_lmode = first 10 chars of field 1
# (as awk substr($1,1,10)), vrj_llinks/vrj_luid/vrj_lsize = fields 2/3/5.
# Multi-line output fails closed. Read only numeric metadata, never filename text.
# vrj_llinks/vrj_luid are read by the pipeline/state libraries.
# shellcheck disable=SC2012,SC2034
vrj_ls() {
    vrj_mc_get "$1" && return 0
    vrj_lt=$(LC_ALL=C ls -ldn "$1" 2>/dev/null) || return 1
    case $vrj_lt in *'
'*|'') return 1 ;; esac
    vrj_lmode=${vrj_lt%%[ 	]*};vrj_lmode=${vrj_lmode%"${vrj_lmode#??????????}"}
    vrj_lt=${vrj_lt#*[ 	]};vrj_lt=${vrj_lt#"${vrj_lt%%[! 	]*}"};vrj_llinks=${vrj_lt%%[ 	]*}
    vrj_lt=${vrj_lt#*[ 	]};vrj_lt=${vrj_lt#"${vrj_lt%%[! 	]*}"};vrj_luid=${vrj_lt%%[ 	]*}
    vrj_lt=${vrj_lt#*[ 	]};vrj_lt=${vrj_lt#"${vrj_lt%%[! 	]*}"}
    vrj_lt=${vrj_lt#*[ 	]};vrj_lt=${vrj_lt#"${vrj_lt%%[! 	]*}"};vrj_lsize=${vrj_lt%%[ 	]*}
}
# vrj_lsmodes PATH...: ONE ls -ldn for a set; vrj_lmodes = the first 10 chars
# of field 1 of every row (space separated, in ls order), vrj_lcount = rows.
# For checks where every path must have a mode from the same allowed set
# (an ancestor chain), row order is irrelevant: no filename text is parsed.
# shellcheck disable=SC2012
vrj_lsmodes() {
    vrj_lmodes=;vrj_lcount=0
    vrj_lt=$(LC_ALL=C ls -ldn "$@" 2>/dev/null) || return 1
    while IFS= read -r vrj_ll; do
        vrj_ll=${vrj_ll%%[ 	]*};vrj_ll=${vrj_ll%"${vrj_ll#??????????}"}
        vrj_lmodes="$vrj_lmodes$vrj_ll ";vrj_lcount=$((vrj_lcount+1))
    done <<EOF
$vrj_lt
EOF
}
# vrj_slurp FILE: vrj_sv = exactly what "$(cat FILE 2>/dev/null)" yields
# (all lines, trailing newlines removed; empty when unreadable), without a
# fork+exec: these small state files are compared hundreds of times per request.
vrj_slurp() {
    vrj_sv=;vrj_sn=;vrj_sr=0
    { while IFS= read -r vrj_sl || [ -n "$vrj_sl" ]; do
        vrj_sv=$vrj_sv$vrj_sn$vrj_sl;vrj_sn='
'
      done; } 2>/dev/null < "$1" || vrj_sr=1
    while :; do case $vrj_sv in *'
') vrj_sv=${vrj_sv%?} ;; *) break ;; esac; done
    return "$vrj_sr"
}
vrj2_file() {
    [ -f "$1" ] && [ ! -L "$1" ] && [ -O "$1" ] && [ -r "$1" ] || return 2
    vrj_ls "$1" || return 2
    case $vrj_lmode in -rw-------|-r--------) ;; *) return 2 ;; esac
    # Regular file (checked above): ls size field = byte count, as wc -c.
    case $vrj_lsize in ''|*[!0-9]*) return 2 ;; esac
    [ "$vrj_lsize" -le 1048576 ]
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
    # Metadata stays in the elected owner process: a separate writer shell
    # could survive it and corrupt a replacement shared lock after reclaim.
    vrj2_metadata_umask=$(umask) || return 1
    umask 077
    vrj2_metadata_rc=0
    printf '%s\n' "$vrj2_me" > "$1/.lock/pid" && printf '%s\n' "$vrj2_start" > "$1/.lock/pid_start" &&
        printf '%s\n' "$vrj2_boot" > "$1/.lock/boot" && printf '%s\t%s\t%s\n' "$vrj2_me" "$vrj2_start" "$vrj2_boot" > "$1/.lock/owner" &&
        vrj_hash "$1/.lock/owner" > "$1/.lock/owner.sha" || vrj2_metadata_rc=$?
    umask "$vrj2_metadata_umask" || return 1
    return "$vrj2_metadata_rc"
}
# One journal lock per request (owner decision 08.11.2026). The coordinator
# takes the SAME elected lock once (vrj2_hold) in its own process and keeps it
# until vrj2_release or its death: a dead holder leaves an ordinary stale lock
# that the existing election reclaims. A journal writer subshell of that
# coordinator borrows the held lock only when (a) the holder identity recorded
# at hold time still owns .lock, (b) the holder is alive with the same start
# time and boot, and (c) the writer is a DESCENDANT of the holder (an orphan
# whose coordinator died is reparented and therefore refused). Any other
# process takes the lock through the election as before and sees a live owner.
vrj2_hold() {
    if [ -n "${vrj2_held:-}" ]; then
        # Re-entrant for the SAME journal in the SAME holder process only.
        IFS=' ' read -r vrj2_hd_me _ < /proc/self/stat || return 1
        [ "$vrj2_held" = "$1" ] && [ "$vrj2_hd_me" = "$vrj2_hme" ] || return 75
        vrj2_borrow "$1" || return 75
        vrj2_borrowed=;return 0
    fi
    vrj2_lock "$1" || return $?
    vrj2_held=$1;vrj2_hme=$vrj2_me;vrj2_hstart=$vrj2_start;vrj2_hboot=$vrj2_boot
}
vrj2_release() {
    [ -n "${vrj2_held:-}" ] || return 0
    vrj2_rl_dir=$vrj2_held
    IFS=' ' read -r vrj2_rl_me _ < /proc/self/stat || return 1
    [ "$vrj2_rl_me" = "$vrj2_hme" ] || return 75
    vrj2_me=$vrj2_hme;vrj2_start=$vrj2_hstart;vrj2_boot=$vrj2_hboot
    vrj2_held=;vrj2_borrowed=
    vrj2_unlock "$vrj2_rl_dir"
}
# Builtins only: walk the parent chain from this process to the holder.
vrj2_descends_from_holder() {
    vrj2_dp=self;vrj2_dn=0
    while [ "$vrj2_dn" -lt 16 ]; do
        vrj2_dl=;IFS= read -r vrj2_dl < "/proc/$vrj2_dp/stat" 2>/dev/null || return 1
        vrj2_dl=${vrj2_dl##*) }
        # shellcheck disable=SC2086
        set -- $vrj2_dl
        [ "$#" -ge 20 ] || return 1
        case $2 in ''|*[!0-9]*) return 1 ;; esac
        [ "$2" -gt 1 ] || return 1
        if [ "$2" = "$vrj2_hme" ]; then
            vward_pid_start_var "$2" && [ "$VA_PS" = "$vrj2_hstart" ] || return 1
            return 0
        fi
        vrj2_dp=$2;vrj2_dn=$((vrj2_dn+1))
    done
    return 1
}
vrj2_borrow() {
    [ -n "${vrj2_held:-}" ] && [ "$vrj2_held" = "$1" ] && [ -n "${vrj2_hme:-}" ] || return 1
    IFS=' ' read -r vrj2_bme _ < /proc/self/stat || return 1
    # The holder itself: it already owns the lock.
    if [ "$vrj2_bme" != "$vrj2_hme" ]; then vrj2_descends_from_holder || return 75;fi
    [ ! -L "$1/.lock" ] && vrj_dir "$1/.lock" || return 75
    vrj_slurp "$1/.lock/owner";[ "$vrj_sv" = "$vrj2_hme$vrj_tab$vrj2_hstart$vrj_tab$vrj2_hboot" ] || return 75
    vrj_slurp "$1/.lock/pid";[ "$vrj_sv" = "$vrj2_hme" ] || return 75
    vrj_slurp "$1/.lock/pid_start";[ "$vrj_sv" = "$vrj2_hstart" ] || return 75
    vrj_slurp /proc/sys/kernel/random/boot_id;[ "$vrj_sv" = "$vrj2_hboot" ] || return 75
    vlg_boot=$vrj2_hboot vward_lock_gate_live "$vrj2_hboot.$vrj2_hme.$vrj2_hstart" || return 75
    vrj2_borrowed=$1
}
vrj2_lock() {
    vrj_lock_runtime || return 75
    vrj2_borrowed=
    vrj2_brc=0;vrj2_borrow "$1" || vrj2_brc=$?
    [ "$vrj2_brc" != 0 ] || return 0
    [ "$vrj2_brc" = 1 ] || return 75
    IFS=' ' read -r vrj2_me _ < /proc/self/stat || return 1
    vrj2_start=$(vrj2_pid_start "$vrj2_me") || return 1
    IFS= read -r vrj2_boot < /proc/sys/kernel/random/boot_id || return 1
    vward_lock_gate_enter "$1/.lock" || return 75
    vrj2_take_rc=0;vrj2_take_under_gate "$1" || vrj2_take_rc=$?
    vward_lock_gate_leave "$1/.lock" || return 75
    return "$vrj2_take_rc"
}
# vl_boot is set by vward_lock_boot_var (runtime admission library).
# shellcheck disable=SC2154
vrj2_unlock() {
    # A borrowed lock stays with its holder (released by vrj2_release).
    if [ -n "${vrj2_borrowed:-}" ] && [ "$vrj2_borrowed" = "$1" ]; then vrj2_borrowed=;return 0;fi
    # vrj_slurp == "$(cat F 2>/dev/null)"; vward_lock_boot_var == lock_boot_id.
    [ ! -L "$1/.lock" ] && { vrj_slurp "$1/.lock/pid";[ "$vrj_sv" = "${vrj2_me:-}" ]; } &&
        { vrj_slurp "$1/.lock/pid_start";[ "$vrj_sv" = "${vrj2_start:-}" ]; } &&
        { vward_lock_boot_var "$1/.lock/boot" || :;[ "$vl_boot" = "${vrj2_boot:-}" ]; } || return 1
    vward_lock_release "$1/.lock"
}
# Batch atomic files then ONE compulsory flush per journal boundary. The caller
# cannot disable this flush with VWARD_JOURNAL_SYNC; no mutation follows a failure.
vrj2_put() { VWARD_JOURNAL_SYNC=0 vrj_put "$1" "$2"; }
vrj2_flush() { command -v sync >/dev/null 2>&1 && sync; }
vrj2_plan_valid() {
    [ -f "$1" ] && [ ! -L "$1" ] || return 2
    if vrj_mc_get "$1"; then [ "$vrj_lsize" -le 1048576 ] || return 2
    else [ "$(wc -c < "$1")" -le 1048576 ] || return 2;fi
    if vrj_mc_value vrj_mp "$1"; then return "$vrj_mv";fi
    vrj2_plan_awk "$1" >/dev/null
}
# One awk for any number of plans: prints V<TAB>FILE for each valid plan
# (same per-file rules as before; NR is per file). With ONE file its exit
# status is the former plan_valid result.
vrj2_plan_awk() {
    LC_ALL=C awk -F'\t' '
        function fin() {if(cur!="" && lines>0 && !bad) {print "V\t" cur;ok++}}
        FNR==1 {fin();cur=FILENAME;bad=0;n=0;lines=0;files++}
        {lines=FNR}
        FNR>4096 {bad=1}
        FNR==1 {if(NF!=4 || $1!="routing-plan" || $2!=2 || $3!~/^g-[0-9a-f]+$/ || length($3)!=18 || $4!="denied") bad=1;next}
        {
            if(NF!=11 || $1!="step" || $2!=++n || $3!~/^(create|add|remove|move)$/ ||
               $4!~/^(route|dns|group|dns-scope|nativeproof|claims|choice|manifest|proof|registry|saved|queue|policy|tombstone)$/ ||
               length($5)>64 || $6==$7) bad=1
            if($4=="choice") {if($5!~/^[a-z0-9][a-z0-9.@_-]*$/ || length($5)>63)bad=1}
            else if($5!~/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/)bad=1
            for(i=1;i<=NF;i++) if($i!~/^[A-Za-z0-9_.:@,|\/-]+$/ || index($i,"//")) bad=1
        }
        END{fin();exit (ARGC==2 ? (ok==1 ? 0 : 2) : 0)}' "$@"
}
vrj2_ready() {
    vrj_dir "$1" && vrj2_id "$2" && vrj_dir "$1/$2" || return 2
    for vrj2_f in schema plan plan.sha state generation; do vrj2_file "$1/$2/$vrj2_f" || return 2; done
    vrj_slurp "$1/$2/schema";[ "$vrj_sv" = "routing-journal${vrj_tab}2" ] || return 2
    # Same checks as vrj_hash; a batch digest avoids the command substitution.
    if [ -f "$1/$2/plan" ] && [ ! -L "$1/$2/plan" ] && [ -r "$1/$2/plan" ] && vrj_mc_get "$1/$2/plan" &&
        [ "$vrj_lsize" -le 1048576 ] && vrj_mc_value vrj_mh "$1/$2/plan"; then vrj2_digest=$vrj_mv
    else vrj2_digest=$(vrj_hash "$1/$2/plan") || return 2;fi
    vrj_slurp "$1/$2/plan.sha";[ "$vrj2_digest" = "$vrj_sv" ] && vrj2_plan_valid "$1/$2/plan" || return 2
    vrj_slurp "$1/$2/generation";vrj2_gen "$vrj_sv" || return 2
    vrj_slurp "$1/$2/state";case $vrj_sv in planned|pending|unknown|committed|compensated) ;; *) return 2 ;; esac
}
vrj2_step_row() { awk -F'\t' -v n="$2" '$1=="step" && $2==n {print;found=1} END{exit found?0:1}' "$1/plan"; }
vrj2_decode() { printf '%s\n' "$1" | tr '|' '\t'; }
# vrj2_row_fields PLANDIR N: vrj2_row, vrj2_pre (cut -f6), vrj2_post (cut -f7)
# without awk/cut/tr forks. Only the canonical case is answered in shell:
# exactly one "step" row whose field 2 is the plain decimal N and no row with
# a non-canonical field 2. Anything else uses the original pipelines.
vrj2_row_fields() {
    vrj2_row=;vrj2_rn=0;vrj2_rx=0
    { while IFS= read -r vrj2_rl || [ -n "$vrj2_rl" ]; do
        case $vrj2_rl in "step$vrj_tab"*) ;; *) continue ;; esac
        vrj2_r2=${vrj2_rl#*"$vrj_tab"};vrj2_r2=${vrj2_r2%%"$vrj_tab"*}
        case $vrj2_r2 in [1-9]|[1-9][0-9]|[1-9][0-9][0-9]|[1-9][0-9][0-9][0-9]) ;; *) vrj2_rx=1;continue ;; esac
        [ "$vrj2_r2" = "$2" ] || continue
        vrj2_row=$vrj2_rl;vrj2_rn=$((vrj2_rn+1))
      done; } < "$1/plan" 2>/dev/null || vrj2_rx=1
    if [ "$vrj2_rx" = 0 ] && [ "$vrj2_rn" = 1 ]; then
        case $vrj2_row in *"$vrj_tab"*"$vrj_tab"*"$vrj_tab"*"$vrj_tab"*"$vrj_tab"*"$vrj_tab"*) ;; *) vrj2_rx=1 ;; esac
    fi
    if [ "$vrj2_rx" != 0 ] || [ "$vrj2_rn" != 1 ]; then
        vrj2_row=$(vrj2_step_row "$1" "$2") || return 2
        vrj2_pre=$(printf '%s\n' "$vrj2_row" | cut -f6);vrj2_post=$(printf '%s\n' "$vrj2_row" | cut -f7)
        vrj2_dpre=$(vrj2_decode "$vrj2_pre");vrj2_dpost=$(vrj2_decode "$vrj2_post")
        return 0
    fi
    vrj2_rt=${vrj2_row#*"$vrj_tab"*"$vrj_tab"*"$vrj_tab"*"$vrj_tab"*"$vrj_tab"}
    vrj2_pre=${vrj2_rt%%"$vrj_tab"*};vrj2_rt=${vrj2_rt#*"$vrj_tab"};vrj2_post=${vrj2_rt%%"$vrj_tab"*}
    # tr '|' TAB, as vrj2_decode; plan_valid admits no newline in a field.
    vrj2_dpre=;vrj2_rt=$vrj2_pre
    while :; do case $vrj2_rt in *'|'*) vrj2_dpre=$vrj2_dpre${vrj2_rt%%'|'*}$vrj_tab;vrj2_rt=${vrj2_rt#*'|'} ;; *) vrj2_dpre=$vrj2_dpre$vrj2_rt;break ;; esac;done
    vrj2_dpost=;vrj2_rt=$vrj2_post
    while :; do case $vrj2_rt in *'|'*) vrj2_dpost=$vrj2_dpost${vrj2_rt%%'|'*}$vrj_tab;vrj2_rt=${vrj2_rt#*'|'} ;; *) vrj2_dpost=$vrj2_dpost$vrj2_rt;break ;; esac;done
}
vrj2_step_valid() {
    vrj2_seq "$3" && vrj_dir "$1/$2/step.$3" || return 2
    vrj2_row_fields "$1/$2" "$3" || return 2
    for vrj2_f in pre post state generation; do vrj2_file "$1/$2/step.$3/$vrj2_f" || return 2; done
    vrj_slurp "$1/$2/step.$3/pre";[ "$vrj2_dpre" = "$vrj_sv" ] || return 2
    vrj_slurp "$1/$2/step.$3/post";[ "$vrj2_dpost" = "$vrj_sv" ] || return 2
    vrj_slurp "$1/$2/step.$3/state";case $vrj_sv in pending|done|failed|unknown|compensating|compensated) ;; *) return 2 ;; esac
}
# vrj2_plan_counts PLAN: vrj2_count = rows with $1=="step", vrj2_native = 1 if
# such a row has $4 route|dns|group|dns-scope (the former two awk scans).
vrj2_plan_counts() {
    vrj2_count=0;vrj2_native=0
    { while IFS= read -r vrj2_pl || [ -n "$vrj2_pl" ]; do
        case $vrj2_pl in step|"step$vrj_tab"*) ;; *) continue ;; esac
        vrj2_count=$((vrj2_count+1))
        case $vrj2_pl in "step$vrj_tab"*"$vrj_tab"*"$vrj_tab"*) ;; *) continue ;; esac
        vrj2_p4=${vrj2_pl#*"$vrj_tab"*"$vrj_tab"*"$vrj_tab"};vrj2_p4=${vrj2_p4%%"$vrj_tab"*}
        case $vrj2_p4 in route|dns|group|dns-scope) vrj2_native=1 ;; esac
      done; } < "$1" || return 1
}
# Read-only cache for ONE operation directory and its step directories.
vrj2_cache_op() {
    set -- "$1" "$1"
    for vrj2_s in "$1"/step.*; do [ -d "$vrj2_s" ] && [ ! -L "$vrj2_s" ] && set -- "$@" "$vrj2_s"; done
    vrj_mc_load "$@"
}
# Load the read-only cache for JDIR, its v2 operations and their steps.
vrj2_cache_ops() {
    if [ -n "${1%/*}" ]; then set -- "${1%/*}" "${1%/*}" "$1";else set -- "$1" "$1";fi
    vrj2_cp=
    for vrj2_d in "${3:-$1}"/*; do
        [ -d "$vrj2_d" ] && [ ! -L "$vrj2_d" ] || continue
        set -- "$@" "$vrj2_d"
        for vrj2_s in "$vrj2_d"/step.*; do
            [ -d "$vrj2_s" ] && [ ! -L "$vrj2_s" ] && set -- "$@" "$vrj2_s"
        done
        [ ! -f "$vrj2_d/plan" ] || vrj2_cp="$vrj2_cp$vrj2_d/plan$vrj_nl"
    done
    vrj_mc_load "$@"
    [ -n "${vrj_mc_base:-}" ] || return 0
    set --
    while IFS= read -r vrj2_p; do [ -z "$vrj2_p" ] || set -- "$@" "$vrj2_p"; done <<EOF
$vrj2_cp
EOF
    vrj_mc_plans "$@"
}
vrj2_gate_except() (
    [ "$#" -eq 2 ] && vrj_dir "$1" || return 2
    vrj2_cache_ops "$1"
    for vrj2_d in "$1"/*; do
        [ -e "$vrj2_d" ] || [ -L "$vrj2_d" ] || continue
        vrj2_op=${vrj2_d##*/};vrj2_id "$vrj2_op" || return 75
        [ "$vrj2_op" != "$2" ] || continue
        if [ -e "$vrj2_d/schema" ]; then
            vrj2_ready "$1" "$vrj2_op" || return 75
            vrj2_seen=0
            vrj_slurp "$vrj2_d/state";vrj2_ds=$vrj_sv
            for vrj2_s in "$vrj2_d"/step.*; do
                [ -e "$vrj2_s" ] || [ -L "$vrj2_s" ] || continue
                vrj2_step_valid "$1" "$vrj2_op" "${vrj2_s##*/step.}" || return 75
                vrj2_seen=$((vrj2_seen+1))
                # vrj_slurp == "$(cat FILE)" (check-validation-primitives).
                vrj_slurp "$vrj2_s/state";vrj2_ss=$vrj_sv
                vrj_slurp "$vrj2_d/state";vrj2_ds=$vrj_sv
                case $vrj2_ss in pending|unknown|compensating) return 75 ;; esac
                [ "$vrj2_ds" != planned ] || return 75
                if [ "$vrj2_ds" = compensated ]; then
                    case $vrj2_ss in compensated|failed) ;; *) return 75 ;; esac
                fi
                if [ "$vrj2_ds" = committed ]; then
                    [ "$vrj2_ss" = done ] || return 75
                fi
            done
            vrj_slurp "$vrj2_d/state";vrj2_ds=$vrj_sv
            case $vrj2_ds in pending|unknown) return 75 ;; esac
            if [ "$vrj2_ds" = committed ]; then
                vrj2_plan_counts "$vrj2_d/plan" || return 75
                # plan_valid enforces unique sequential step IDs. Every leaf
                # above must match one exact plan row (no zero/alias/extra ID),
                # so cardinality proves completeness without validating each
                # closed historical leaf a second time on every later step.
                [ "$vrj2_seen" = "$vrj2_count" ] || return 75
                if [ "$vrj2_native" = 1 ]; then
                    vrj2_file "$vrj2_d/save" && { vrj_slurp "$vrj2_d/save";[ "$vrj_sv" = 'done' ]; } || return 75
                fi
            fi
            if [ "$vrj2_ds" = compensated ]; then
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
    vrj_slurp "$1/$2/state";case $vrj_sv in planned|pending) ;; *) return 75 ;; esac
    vrj2_gate_except "$1" "$2" || return 75
    vrj_slurp "$1/$2/generation";[ "$vrj_sv" = "$4" ] || return 75
    [ ! -e "$1/$2/step.$3" ] && [ ! -L "$1/$2/step.$3" ] || return 75
    # Read-only checks of this operation's earlier steps: one ls for all.
    vrj2_cache_op "$1/$2"
    vrj2_n=1
    while [ "$vrj2_n" -lt "$3" ]; do
        vrj2_step_valid "$1" "$2" "$vrj2_n" && { vrj_slurp "$1/$2/step.$vrj2_n/state";[ "$vrj_sv" = 'done' ]; } || return 75
        vrj2_n=$((vrj2_n+1))
    done
    vrj_mc_off
    vrj2_row_fields "$1/$2" "$3" || return 2
    vrj_slurp "$5";[ "$vrj2_dpre" = "$vrj_sv" ] || return 75
    mkdir "$1/$2/step.$3" || return 1
    vrj2_put "$1/$2/step.$3/pre" "$vrj2_dpre" &&
        vrj2_put "$1/$2/step.$3/post" "$vrj2_dpost" &&
        vrj2_put "$1/$2/step.$3/generation" "$4" && vrj2_put "$1/$2/step.$3/state" pending &&
        vrj2_put "$1/$2/state" pending && vrj2_flush
)
# Batch form of begin (owner decision 08.11.2026): EVERY step of a planned
# operation becomes pending BEFORE anything is dispatched, with exactly the
# per-step records of vward_journal2_begin (pre/post/generation/state), so the
# existing recovery and compensation read them unchanged. CURDIR/current.N is
# the fresh scope hash of step N; each must equal the plan pre-image. One
# gate, one lock (normally borrowed from the coordinator), one flush.
vward_journal2_begin_all() (
    umask 077
    [ "$#" -eq 4 ] && vrj2_gen "$3" && vrj_dir "$4" || return 2
    vrj2_ready "$1" "$2" || return 2
    vrj2_lock "$1" || return $?
    trap 'vrj2_unlock "$1"' EXIT
    vrj_slurp "$1/$2/state";[ "$vrj_sv" = planned ] || return 75
    vrj2_gate_except "$1" "$2" || return 75
    vrj_slurp "$1/$2/generation";[ "$vrj_sv" = "$3" ] || return 75
    for vrj2_s in "$1/$2"/step.*; do
        [ ! -e "$vrj2_s" ] && [ ! -L "$vrj2_s" ] || return 75
    done
    vrj2_plan_counts "$1/$2/plan" || return 2
    [ "$vrj2_count" -gt 0 ] || return 2
    vrj2_n=1
    while [ "$vrj2_n" -le "$vrj2_count" ]; do
        vrj2_file "$4/current.$vrj2_n" || return 2
        vrj2_row_fields "$1/$2" "$vrj2_n" || return 2
        vrj_slurp "$4/current.$vrj2_n";[ "$vrj2_dpre" = "$vrj_sv" ] || return 75
        vrj2_n=$((vrj2_n+1))
    done
    vrj2_n=1
    while [ "$vrj2_n" -le "$vrj2_count" ]; do
        vrj2_row_fields "$1/$2" "$vrj2_n" || return 2
        mkdir "$1/$2/step.$vrj2_n" || return 1
        vrj2_put "$1/$2/step.$vrj2_n/pre" "$vrj2_dpre" &&
            vrj2_put "$1/$2/step.$vrj2_n/post" "$vrj2_dpost" &&
            vrj2_put "$1/$2/step.$vrj2_n/generation" "$3" &&
            vrj2_put "$1/$2/step.$vrj2_n/state" pending || return 1
        vrj2_n=$((vrj2_n+1))
    done
    vrj2_put "$1/$2/state" pending && vrj2_flush
)
# Batch form of finish for steps FROM..TO from ONE shared readback: the same
# per-step verdict as vward_journal2_finish (post = done, pre = failed, other =
# unknown). rc 0 all done, 1 a proved failure (none unknown), 3 unknown.
vward_journal2_finish_range() (
    umask 077
    [ "$#" -eq 6 ] && vrj2_gen "$3" && vrj_dir "$4" && vrj2_seq "$5" && vrj2_seq "$6" && [ "$5" -le "$6" ] || return 2
    vrj2_ready "$1" "$2" || return 2
    vrj2_lock "$1" || return $?
    trap 'vrj2_unlock "$1"' EXIT
    case $(cat "$1/$2/state") in pending|unknown) ;; *) return 75 ;; esac
    vrj2_n=$5
    while [ "$vrj2_n" -le "$6" ]; do
        vrj2_step_valid "$1" "$2" "$vrj2_n" && vrj2_file "$4/current.$vrj2_n" || return 2
        vrj_slurp "$1/$2/step.$vrj2_n/state";case $vrj_sv in pending|unknown) ;; *) return 75 ;; esac
        vrj2_n=$((vrj2_n+1))
    done
    vrj2_rc=0;vrj2_n=$5
    while [ "$vrj2_n" -le "$6" ]; do
        vrj2_result=unknown
        if cmp -s "$4/current.$vrj2_n" "$1/$2/step.$vrj2_n/post"; then vrj2_result='done'
        elif cmp -s "$4/current.$vrj2_n" "$1/$2/step.$vrj2_n/pre"; then vrj2_result=failed;fi
        vrj_slurp "$4/current.$vrj2_n"
        vrj2_put "$1/$2/step.$vrj2_n/observed" "$vrj_sv" && vrj2_put "$1/$2/step.$vrj2_n/state" "$vrj2_result" || return 1
        case $vrj2_result in
            failed) [ "$vrj2_rc" = 3 ] || vrj2_rc=1 ;;
            unknown) vrj2_rc=3 ;;
        esac
        vrj2_n=$((vrj2_n+1))
    done
    if [ "$vrj2_rc" = 0 ]; then vrj2_put "$1/$2/generation" "$3" || return 1;fi
    [ "$vrj2_rc" != 3 ] || vrj2_put "$1/$2/state" unknown || return 1
    vrj2_flush || return 1
    return "$vrj2_rc"
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
    vrj_ls "$1" && [ "$vrj_lmode" = drwx------ ] || return 2
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
    if vrj_mc_get "$1"; then
        [ "$vrj_lsize" -le 1048576 ] || return 1
        if vrj_mc_value vrj_mh "$1"; then printf '%s\n' "$vrj_mv";return 0;fi
    else [ "$(wc -c < "$1")" -le 1048576 ] || return 1;fi
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
