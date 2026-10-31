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

vrj_lock() {
    vrj_n=0
    while ! mkdir "$1/.lock" 2>/dev/null; do
        vrj_p=$(cat "$1/.lock/pid" 2>/dev/null)
        # A lock left by a killed process (SIGKILL, reboot) is taken over; a live one is busy.
        case $vrj_p in ''|*[!0-9]*) vrj_p= ;; esac
        if [ -n "$vrj_p" ] && kill -0 "$vrj_p" 2>/dev/null; then return 75; fi
        [ -n "$vrj_p" ] || [ "$vrj_n" -ge 1 ] || { vrj_n=1; continue; }
        rm -rf "$1/.lock" 2>/dev/null
        vrj_n=$((vrj_n + 1)); [ "$vrj_n" -le 2 ] || return 75
    done
    echo $$ > "$1/.lock/pid" 2>/dev/null || { rmdir "$1/.lock" 2>/dev/null; return 1; }
}
vrj_unlock() { rm -rf "$1/.lock" 2>/dev/null; }

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
