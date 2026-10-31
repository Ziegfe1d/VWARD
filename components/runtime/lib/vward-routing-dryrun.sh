#!/bin/sh
# RS-7 stage 3: DRY-RUN executor for ONE narrow path - add a domain to a VWARD-owned
# service FQDN group - driven through the stage-2 journal. Defines functions only.
#
#   vward_routing_dryrun_add     JDIR OPID GENERATION GROUP DOMAIN
#   vward_routing_dryrun_recover JDIR
#
# It NEVER talks to the real router. Every router call goes to a stand-in named by
# VWARD_DRYRUN_NDMC, which must (a) be an absolute, regular, executable file outside
# /opt /bin /sbin /usr, (b) not be the ndmc found in PATH, and (c) carry the marker
# `VWARD-DRYRUN-STANDIN` in its first 256 bytes (checked by reading, never by running it). The switch VWARD_RS7_DRYRUN=1 is
# OFF by default; without it nothing runs. No real executor is wired to this file.
#
# Cycle: gate -> read pre-image -> journal begin (PENDING) -> one write -> read back ->
# journal finish (DONE / FAILED / UNKNOWN). A transport error after the write is treated as
# a possibly lost reply: the read-back decides; an unreadable read-back = UNKNOWN. Never a
# retry, never a compensation here; a recovery only classifies by re-reading.
# rc: 0 done or already present; 1 failed (proven not applied); 2 usage; 3 unknown;
#     75 refused (switch off, stand-in refused, gate closed, plan not eligible, no group).

vrd_standin() {
    [ "${VWARD_RS7_DRYRUN:-0}" = 1 ] || return 75
    vrd_n=${VWARD_DRYRUN_NDMC:-}
    case $vrd_n in /opt/*|/bin/*|/sbin/*|/usr/*|'') return 75 ;; /*) ;; *) return 75 ;; esac
    [ -f "$vrd_n" ] && [ ! -L "$vrd_n" ] && [ -x "$vrd_n" ] || return 75
    [ "$vrd_n" != "$(command -v ndmc 2>/dev/null)" ] || return 75
    # The stand-in declares itself in its first bytes; the candidate is never executed to ask.
    head -c 256 "$vrd_n" 2>/dev/null | grep -q 'VWARD-DRYRUN-STANDIN' || return 75
}

# Canonical, order-free image of one group: "group=G" then sorted unique "include=D".
vrd_image() {
    "$VWARD_DRYRUN_NDMC" -c 'show running-config' 2>/dev/null > "$2.cfg" || { rm -f "$2.cfg"; return 1; }
    grep -q '^object-group fqdn ' "$2.cfg" || { rm -f "$2.cfg"; return 1; }
    awk -v g="$1" '
        /^object-group fqdn / {cur = ($3 == g && NF == 3); if (cur) n++; next}
        /^!/ {cur = 0}
        cur && $1 == "include" && NF == 2 {print "include=" tolower($2)}
        END {exit n == 1 ? 0 : 3}' "$2.cfg" | LC_ALL=C sort -u > "$2.inc"
    vrd_rc=$?
    # A missing or duplicated group is not an image (rc 3): nothing may be written.
    awk -v g="$1" '/^object-group fqdn / && $3 == g && NF == 3 {n++} END {exit n == 1 ? 0 : 3}' "$2.cfg" || vrd_rc=3
    rm -f "$2.cfg"
    [ "$vrd_rc" = 0 ] || { rm -f "$2.inc"; return 3; }
    { printf 'group=%s\n' "$1"; cat "$2.inc"; } > "$2" && rm -f "$2.inc"
}

vward_routing_dryrun_add() (
    [ "$#" -eq 5 ] || return 2
    command -v vward_journal_begin >/dev/null 2>&1 || return 2
    vrd_standin || return 75
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
    vrd_out=$("$VWARD_DRYRUN_NDMC" -c "object-group fqdn $4 include $5" 2>&1); vrd_w=$?
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
# let the journal classify it. Nothing is written to the router.
vward_routing_dryrun_recover() (
    [ "$#" -eq 1 ] || return 2
    command -v vward_journal_recover >/dev/null 2>&1 || return 2
    vrd_standin || return 75
    vrd_c=$(umask 077; mktemp -d "$1/.recover.XXXXXX") || return 2
    trap 'rm -rf "$vrd_c"' EXIT
    vward_journal_status "$1" | awk -F'\t' '$2 == "pending" || $2 == "unknown" {print $1}' |
    while IFS= read -r vrd_o; do
        vrd_g=$(sed -n 's/^checks=group:\([A-Za-z0-9_.-]*\),.*/\1/p' "$1/$vrd_o/pending" 2>/dev/null)
        [ -n "$vrd_g" ] || continue
        vrd_image "$vrd_g" "$vrd_c/$vrd_o" || rm -f "$vrd_c/$vrd_o"
    done
    vward_journal_recover "$1" "$vrd_c"
)
