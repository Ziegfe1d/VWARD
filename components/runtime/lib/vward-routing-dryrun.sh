#!/bin/sh
# RS-7 stage 3: DRY-RUN executor for ONE narrow path - add a domain to a VWARD-owned
# service FQDN group - driven through the stage-2 journal. Defines functions only.
#
#   vward_routing_dryrun_add     JDIR OPID GENERATION GROUP DOMAIN
#   vward_routing_dryrun_recover JDIR
#
# NOTHING is executed on behalf of a router. There is no command, binary or path taken
# from the environment: the "router" is a built-in emulator (functions below) acting on a
# DATA file, JDIR/.emu/running.cfg, inside the journal's own private directory (absolute,
# 0700, owned by the caller - checked by the journal). The emulator directory and file must
# be real (no symlink), owned by the caller and private. VWARD_DRYRUN_NDMC is NOT supported:
# if it is set at all, everything is refused (it once named an executable stand-in).
# The switch VWARD_RS7_DRYRUN=1 is OFF by default. No real executor is wired to this file.
#
# Emulator fault switches (test fixture only; plain files in JDIR/.emu): refuse, lost,
# foreign, show-fails, show-fails-after, slow-before[=seconds], slow-after[=seconds].
#
# Cycle: gate -> PLAN-only id -> read pre-image -> journal begin (PENDING) -> one write ->
# read back -> journal finish (DONE / FAILED / UNKNOWN). A transport error after the write is
# treated as a possibly lost reply: the read-back decides; an unreadable read-back = UNKNOWN.
# Never a retry, never a compensation here; a recovery only classifies by re-reading.
# rc: 0 done or already present; 1 failed (proven not applied); 2 usage; 3 unknown;
#     75 refused (switch off, environment override, emulator unsafe, gate closed, no group).

vrd_private() {
    # $1 path, $2 d|f: real (not a symlink), owned by the caller, no group/other access.
    [ ! -L "$1" ] && [ -O "$1" ] || return 1
    case $2 in d) [ -d "$1" ] ;; f) [ -f "$1" ] ;; esac || return 1
    case $(ls -ldn "$1" 2>/dev/null | awk '{print substr($1,5,6)}') in ------) return 0 ;; esac
    return 1
}

vrd_ready() {
    [ "${VWARD_RS7_DRYRUN:-0}" = 1 ] || return 75
    # An environment-selected executor is never honoured, whatever it points to.
    [ -z "${VWARD_DRYRUN_NDMC+x}" ] || return 75
    vrd_e=$1/.emu
    vrd_private "$1" d && vrd_private "$vrd_e" d && vrd_private "$vrd_e/running.cfg" f || return 75
}

vrd_sleep() { vrd_s=$(head -c 8 "$1" 2>/dev/null | tr -cd 0-9); sleep "${vrd_s:-30}"; }

# Emulated `show running-config`: the data file, nothing else.
vrd_emu_show() {
    echo show >> "$vrd_e/calls"
    [ ! -e "$vrd_e/show-fails" ] || return 1
    cat "$vrd_e/running.cfg"
}

# Emulated `object-group fqdn GROUP include DOMAIN`: an awk edit of the data file (tmp + rename).
vrd_emu_write() {
    echo "write $1 $2" >> "$vrd_e/calls"
    [ ! -e "$vrd_e/slow-before" ] || vrd_sleep "$vrd_e/slow-before"
    if [ -e "$vrd_e/refuse" ]; then echo "Network::ObjectGroup: error: synthetic refusal"; return 0; fi
    vrd_f=0; [ ! -e "$vrd_e/foreign" ] || vrd_f=1
    # The data file stays private across the rewrite (umask 077 for the replacement).
    (umask 077; awk -v g="$1" -v d="$2" -v f="$vrd_f" '
        /^object-group fqdn / {cur = ($3 == g && NF == 3)}
        /^!/ && cur {print "    include " d; if (f) print "    include user-added.example"; cur = 0}
        {print}' "$vrd_e/running.cfg" > "$vrd_e/running.cfg.tmp") &&
        mv -f "$vrd_e/running.cfg.tmp" "$vrd_e/running.cfg" || return 1
    [ ! -e "$vrd_e/show-fails-after" ] || : > "$vrd_e/show-fails"
    [ ! -e "$vrd_e/slow-after" ] || vrd_sleep "$vrd_e/slow-after"
    [ ! -e "$vrd_e/lost" ] || return 28
    return 0
}

# Canonical, order-free image of one group: "group=G" then sorted unique "include=D".
vrd_image() {
    vrd_emu_show > "$2.cfg" 2>/dev/null || { rm -f "$2.cfg"; return 1; }
    grep -q '^object-group fqdn ' "$2.cfg" || { rm -f "$2.cfg"; return 1; }
    # A missing or duplicated group is not an image: nothing may be written.
    if ! awk -v g="$1" '/^object-group fqdn / && $3 == g && NF == 3 {n++} END {exit n == 1 ? 0 : 3}' "$2.cfg"; then
        rm -f "$2.cfg"; return 3
    fi
    {
        printf 'group=%s\n' "$1"
        awk -v g="$1" '
            /^object-group fqdn / {cur = ($3 == g && NF == 3); next}
            /^!/ {cur = 0}
            cur && $1 == "include" && NF == 2 {print "include=" tolower($2)}' "$2.cfg" | LC_ALL=C sort -u
    } > "$2"
    rm -f "$2.cfg"
}

vward_routing_dryrun_add() (
    umask 077
    [ "$#" -eq 5 ] || return 2
    command -v vward_journal_begin >/dev/null 2>&1 || return 2
    case $1 in /*) ;; *) return 2 ;; esac
    vrd_ready "$1" || return 75
    case $4 in ''|[!A-Za-z0-9]*|*[!A-Za-z0-9_.-]*) return 2 ;; esac
    case $5 in ''|*[!a-z0-9.-]*|.*|*.|*..*) return 2 ;; esac
    [ "${#5}" -le 253 ] || return 2
    vward_journal_gate "$1" >/dev/null || return 75
    # An operation id is used once: only an operation still in PLAN may start.
    [ "$(vward_journal_status "$1" | awk -F'\t' -v o="$2" '$1 == o {print $2}')" = plan ] || return 75
    vrd_t=$(umask 077; mktemp -d "$1/.dryrun.XXXXXX") || return 2
    trap 'rm -rf "$vrd_t"' EXIT
    vrd_image "$4" "$vrd_t/pre" || return 75
    if grep -qx "include=$5" "$vrd_t/pre"; then echo "result=unchanged"; return 0; fi
    { cat "$vrd_t/pre"; printf 'include=%s\n' "$5"; } | { read -r vrd_h; printf '%s\n' "$vrd_h"; LC_ALL=C sort -u; } > "$vrd_t/post"
    vward_journal_begin "$1" "$2" "$3" "$vrd_t/pre" "$vrd_t/post" "group:$4,dryrun" || return $?
    # PENDING is durable: from here on a crash is recovered by re-reading, never by replay.
    vrd_out=$(vrd_emu_write "$4" "$5" 2>&1); vrd_w=$?
    if ! vrd_image "$4" "$vrd_t/now"; then
        vward_journal_unknown "$1" "$2" read-back-failed >/dev/null 2>&1
        echo "result=unknown"; return 3
    fi
    vward_journal_finish "$1" "$2" "$vrd_t/now" || { echo "result=unknown"; return 3; }
    vrd_st=$(vward_journal_status "$1" | awk -F'\t' -v o="$2" '$1 == o {print $2}')
    # A refused command that changed nothing is a proven failure; a transport error with the
    # change visible is DONE (the reply was lost, the write was not).
    [ "$vrd_w" = 0 ] || printf 'write_rc=%s\n' "$vrd_w"
    : "$vrd_out"
    echo "result=$vrd_st"
    case $vrd_st in done) return 0 ;; failed) return 1 ;; *) return 3 ;; esac
)

# After a crash or reboot: re-read the group of every pending/unknown dry-run operation and
# let the journal classify it. Nothing is written.
vward_routing_dryrun_recover() (
    umask 077
    [ "$#" -eq 1 ] || return 2
    command -v vward_journal_recover >/dev/null 2>&1 || return 2
    case $1 in /*) ;; *) return 2 ;; esac
    vrd_ready "$1" || return 75
    # Scratch left by an executor killed with SIGKILL (its EXIT trap never ran). Recovery runs
    # after a restart; an executor still alive would only lose its read-back (-> UNKNOWN).
    rm -rf "$1"/.dryrun.* "$1"/.recover.* 2>/dev/null
    vrd_c=$(umask 077; mktemp -d "$1/.recover.XXXXXX") || return 2
    trap 'rm -rf "$vrd_c"' EXIT
    vward_journal_status "$1" | awk -F'\t' '$2 == "pending" || $2 == "unknown" {print $1}' > "$vrd_c/.ops"
    while IFS= read -r vrd_o; do
        vrd_g=$(sed -n 's/^checks=group:\([A-Za-z0-9_.-]*\),.*/\1/p' "$1/$vrd_o/pending" 2>/dev/null)
        [ -n "$vrd_g" ] || continue
        vrd_image "$vrd_g" "$vrd_c/$vrd_o" || rm -f "$vrd_c/$vrd_o"
    done < "$vrd_c/.ops"
    rm -f "$vrd_c/.ops"
    vward_journal_recover "$1" "$vrd_c"
)
