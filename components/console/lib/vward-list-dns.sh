#!/bin/sh
# Explicit managed-list Smart DNS transaction. Loaded by the Panel writer only.
# Reuses its admission, EDIT/CHANGE locks, snapshots, ndm/doh_remove and recovery gate.

list_dns_scope() {
    { service_signature "$LD_GROUP" | sed 's/^/G /'; doh_lines | sed 's/^/D /'
      # DNS is global: another group's membership can revoke exclusive domain
      # ownership while we write. Keep it in transaction images, not long-lived proof.
      awk -v g="$LD_GROUP" '/^object-group fqdn / {cur=$3; if(cur!=g) print "O group " cur}
          /^!/ {cur=""} cur!="" && cur!=g && $1=="include" {print "O " cur " " tolower($2)}' "$RUNCFG"
    } | LC_ALL=C sort
}

list_dns_exclusive() {
    awk -v g="$LD_GROUP" 'FILENAME==ARGV[1] {want[$0]=1; next}
        /^object-group fqdn / {cur=$3} /^!/ {cur=""}
        cur!="" && cur!=g && $1=="include" {d=tolower($2); sub(/^\*\./,"",d); for(h in want)
            if(d==h || (length(d)>length(h) && substr(d,length(d)-length(h))=="." h) ||
               (length(h)>length(d) && substr(h,length(h)-length(d))=="." d)) bad=1}
        END {exit bad}' "$RUNCFG.domains" "$RUNCFG"
}

list_dns_read_scope() {
    "$NDMC" -c 'show running-config' > "$RUNCFG" 2>/dev/null &&
        config_snapshot_valid "$RUNCFG" && list_dns_scope > "$LD_DIR/current"
}

list_dns_step() {
    # Exact scope images bracket each write; inverse is durable BEFORE the command.
    list_dns_read_scope && cmp -s "$LD_DIR/current" "$LD_DIR/state.$LD_N" || die list_dns_concurrent
    LD_NEXT=$((LD_N + 1))
    printf '%s\n' "$3" > "$LD_DIR/line" || die write_failed
    if [ "$1" = add ]; then
        { cat "$LD_DIR/state.$LD_N"; cat "$LD_DIR/line"; } | LC_ALL=C sort -u > "$LD_DIR/state.$LD_NEXT"
    else
        awk 'FILENAME==ARGV[1] {d=$0; next} $0!=d' "$LD_DIR/line" "$LD_DIR/state.$LD_N" > "$LD_DIR/state.$LD_NEXT"
    fi
    printf '%s\n' "$4" > "$LD_DIR/inverse.$LD_NEXT" || die write_failed
    LD_N=$LD_NEXT
    [ "${VWARD_JOURNAL_SYNC:-1}" = 0 ] || sync
    ld_rc=0
    case "$2" in
        'REMOVE-DNS '*) doh_remove "${2#REMOVE-DNS }" || ld_rc=1 ;;
        *) ndm "$2" || ld_rc=1 ;;
    esac
    # Never echo a private DoH URL or Keenetic's reply through die/audit.
    # shellcheck disable=SC2034 # consumed by the caller's error renderer
    NDM_CMD='' NDM_REPLY=''
    [ "$ld_rc" = 0 ] || die list_dns_write_failed
    list_dns_read_scope && cmp -s "$LD_DIR/current" "$LD_DIR/state.$LD_N" || die list_dns_verification_failed
}

list_dns_file_before() {
    [ ! -L "$1" ] || die unsafe_target
    if [ -e "$1" ]; then
        [ -f "$1" ] && cp -p "$1" "$LD_DIR/$2.before" || die backup_failed
    else
        : > "$LD_DIR/$2.absent" || die write_failed
    fi
}

list_dns_file_same() {
    [ ! -L "$1" ] || return 1
    if [ -f "$LD_DIR/$2.absent" ]; then [ ! -e "$1" ]
    else cmp -s "$1" "$LD_DIR/$2.before"; fi
}

list_dns_file_restore() {
    list_dns_file_same "$1" "$2" && return 0
    # Only our own written postimage may be replaced; external edits survive.
    [ -f "$LD_DIR/$2.after" ] && [ ! -L "$1" ] && cmp -s "$1" "$LD_DIR/$2.after" || return 1
    if [ -f "$LD_DIR/$2.absent" ]; then rm -f "$1"
    else cp -p "$LD_DIR/$2.before" "$1.undo.$$" && mv -f "$1.undo.$$" "$1"; fi
}

list_dns_rollback() {
    list_dns_read_scope || return 1
    ld_at=$LD_N
    while [ "$ld_at" -ge 0 ]; do
        cmp -s "$LD_DIR/current" "$LD_DIR/state.$ld_at" && break
        ld_at=$((ld_at - 1))
    done
    # Unknown state (lost read or concurrent owner edit): keep evidence, no replay.
    [ "$ld_at" -ge 0 ] || return 1
    while [ "$ld_at" -gt 0 ]; do
        list_dns_read_scope && cmp -s "$LD_DIR/current" "$LD_DIR/state.$ld_at" || return 1
        ld_inverse=$(cat "$LD_DIR/inverse.$ld_at") || return 1
        case "$ld_inverse" in
            'REMOVE-DNS '*) doh_remove "${ld_inverse#REMOVE-DNS }" >/dev/null 2>&1 || return 1 ;;
            *) ndm "$ld_inverse" >/dev/null 2>&1 || return 1 ;;
        esac
        ld_at=$((ld_at - 1))
        list_dns_read_scope && cmp -s "$LD_DIR/current" "$LD_DIR/state.$ld_at" || return 1
    done
    list_dns_file_restore "$LISTS_CONF" conf && list_dns_file_restore "$LD_PROOF" proof &&
        save_router || return 1
    rm -rf "${LD_DIR:?}"
    LD_DIR=
}

op_list_dns() {
    list_steerable "$1"
    list_managed "$1" || die list_not_managed 64
    case "$2" in dns|vpn|bypass|auto) ;; *) is_tunnel "$2" || die invalid_value 64 ;; esac
    [ "${EDIT_LOCKED:-0}" = 1 ] || edit_lock
    change_lock
    snapshot
    LD_GROUP=$1 LD_MODE=$2 LD_N=0
    LD_PROOF="$LISTS_STATE.dns/$LD_GROUP"
    [ ! -L "$LISTS_STATE.dns" ] && [ ! -L "$LD_PROOF" ] || die unsafe_target
    group_domains "$LD_GROUP" > "$RUNCFG.domains"
    [ -s "$RUNCFG.domains" ] || die empty_list 64
    # This applies on exit too: a later foreign reference revokes compensation rights.
    list_dns_exclusive || die list_dns_shared_domain 75
    # Reuse an owned DNS decision only while its exact group/route proof matches.
    if [ -f "$LD_PROOF" ]; then
        service_signature "$LD_GROUP" > "$RUNCFG.identity"
        sed -n 's/^G //p' "$LD_PROOF" | cmp -s - "$RUNCFG.identity" || die list_dns_reference_only 75
        while IFS= read -r ld_line; do
            case "$ld_line" in 'D '*) doh_present "${ld_line#D }" || die list_dns_reference_only 75 ;; esac
        done < "$LD_PROOF"
    fi
    if [ "$LD_MODE" = dns ]; then
        ld_url=$(awk -F= '$1=="SMARTDNS_URL" {print substr($0,index($0,"=")+1); exit}' "$SMARTDNS_CONF" 2>/dev/null)
        [ -n "$ld_url" ] || die smartdns_not_configured
        VWARD_DOH_ALIVE_FRESH=1 vward_doh_alive "$ld_url"; ld_alive=$?
        case "$ld_alive" in 0) ;; 1) die smartdns_dead ;; *) die smartdns_unknown ;; esac
        ld_target=$(wan_route_target)
    else
        case "$LD_MODE" in vpn) ld_target=$VWARD_TUNNEL_INTERFACE ;; bypass|auto) ld_target=$(wan_route_target) ;; *) ld_target=$LD_MODE ;; esac
    fi
    ld_current=$(group_route "$LD_GROUP"); ld_tab=$(printf '\t')
    ld_cur=${ld_current%%"$ld_tab"*}; ld_opt=${ld_current#*"$ld_tab"}
    [ "$(group_routes "$LD_GROUP" | grep -c .)" -le 1 ] || die list_dns_reference_only 75
    [ -z "$ld_cur" ] || [ "$ld_cur" = "$ld_target" ] || is_tunnel "$ld_cur" ||
        [ "$ld_cur" = "$(wan_route_target)" ] || die list_dns_reference_only 75
    # A durable private reservation is also the existing global routing recovery barrier.
    umask 077
    mkdir -p "$BACKUP_DIR-recovery" || die backup_failed
    LD_DIR=$(mktemp -d "$BACKUP_DIR-recovery/smartdns.XXXXXX") || die backup_failed
    printf 'list-dns %s %s\n' "$LD_GROUP" "$LD_MODE" > "$LD_DIR/operation" || die write_failed
    list_dns_scope > "$LD_DIR/state.0" || die write_failed
    cp "$RUNCFG" "$LD_DIR/config.before" || die backup_failed
    list_dns_file_before "$LISTS_CONF" conf
    list_dns_file_before "$LD_PROOF" proof
    : > "$LD_DIR/owned"
    [ ! -f "$LD_PROOF" ] || sed -n 's/^D //p' "$LD_PROOF" > "$LD_DIR/owned"
    LD_TXN=1
    # Preflight every domain/slot BEFORE any route or DNS mutation.
    : > "$LD_DIR/add"
    if [ "$LD_MODE" = dns ]; then
        ld_used=$(doh_lines | grep -c .); ld_need=0
        ld_tpl=$(doh_lines | awk '$(NF-1)=="domain" {NF-=1; print; exit}')
        # The URL stays in a private input file, never in awk's arguments.
        printf '%s\n' "$ld_url" > "$LD_DIR/url"
        while IFS= read -r ld_domain; do
            valid_domain "$ld_domain" || die invalid_domain 64
            ld_existing=$(doh_lines | awk -v d="$ld_domain" '$(NF-1)=="domain" && $NF==d')
            if [ -n "$ld_existing" ]; then
                printf '%s\n' "$ld_existing" > "$LD_DIR/existing"
                awk 'FILENAME==ARGV[1] {u=$0; next} $3!=u {bad=1} END{exit bad}' "$LD_DIR/url" "$LD_DIR/existing" || die list_dns_conflict 75
                continue
            fi
            ld_need=$((ld_need + 1))
            if [ -n "$ld_tpl" ]; then
                printf '%s\n' "$ld_tpl" | awk -v d="$ld_domain" 'BEGIN{getline u < ARGV[1]; ARGV[1]=""} {$3=u; print $0 " " d}' "$LD_DIR/url" >> "$LD_DIR/add"
            else
                printf 'https upstream %s dnsm on %s domain %s\n' "$ld_url" "$ld_target" "$ld_domain" >> "$LD_DIR/add"
            fi
        done < "$RUNCFG.domains"
        [ $((ld_used + ld_need)) -le "$SMARTDNS_KEENETIC_MAX" ] || die smartdns_keenetic_full 75
    fi
    if [ "$LD_MODE" != dns ]; then
        while IFS= read -r ld_line; do
            [ -n "$ld_line" ] || continue
            list_dns_step remove "REMOVE-DNS $ld_line" "D $ld_line" "dns-proxy $ld_line"
        done < "$LD_DIR/owned"
        # Remaining matching rows are references owned elsewhere, never delete them.
        [ -z "$(group_doh_lines "$LD_GROUP")" ] || die list_dns_reference_only 75
    fi
    if [ "$ld_cur" != "$ld_target" ]; then
        list_dns_step add "dns-proxy route object-group $LD_GROUP $ld_target auto" "G route=$ld_target${ld_tab}auto" "dns-proxy no route object-group $LD_GROUP $ld_target"
        if [ -n "$ld_cur" ]; then
            ld_old_opts=; [ "$ld_opt" = - ] || ld_old_opts=" $ld_opt"
            list_dns_step remove "dns-proxy no route object-group $LD_GROUP $ld_cur" "G route=$ld_cur$ld_tab$ld_opt" "dns-proxy route object-group $LD_GROUP $ld_cur$ld_old_opts"
        fi
    fi
    while IFS= read -r ld_line; do
        [ -n "$ld_line" ] || continue
        list_dns_step add "dns-proxy $ld_line" "D $ld_line" "REMOVE-DNS $ld_line"
        printf '%s\n' "$ld_line" >> "$LD_DIR/owned"
    done < "$LD_DIR/add"
    ld_watch=0; [ "$LD_MODE" != auto ] || ld_watch=1
    { [ ! -f "$LISTS_CONF" ] || cat "$LISTS_CONF"; } |
        awk -F= -v k="watch.$LD_GROUP" -v v="$ld_watch" '$1==k {next} {print} END{print k "=" v}' > "$LD_DIR/conf.after"
    if [ "$LD_MODE" = dns ]; then
        { service_signature "$LD_GROUP" | sed 's/^/G /'; sed 's/^/D /' "$LD_DIR/owned"; } > "$LD_DIR/proof.after"
    else
        # Empty proof is atomically written first; deletion follows a successful commit.
        : > "$LD_DIR/proof.after"
    fi
    list_dns_file_same "$LISTS_CONF" conf && list_dns_file_same "$LD_PROOF" proof || die list_dns_concurrent
    ld_changed=$LD_N
    cmp -s "$LD_DIR/conf.after" "$LISTS_CONF" && cmp -s "$LD_DIR/proof.after" "$LD_PROOF" || ld_changed=$((ld_changed + 1))
    new_tmp "$LISTS_CONF" && cp "$LD_DIR/conf.after" "$TMPFILE" && install_tmp "$LISTS_CONF" 0644 || die write_failed
    mkdir -p "$LISTS_STATE.dns" && chmod 0700 "$LISTS_STATE.dns" || die write_failed
    new_tmp "$LD_PROOF" && cp "$LD_DIR/proof.after" "$TMPFILE" && install_tmp "$LD_PROOF" 0600 || die write_failed
    list_dns_read_scope && cmp -s "$LD_DIR/current" "$LD_DIR/state.$LD_N" || die list_dns_concurrent
    save_router || die config_save_failed
    # shellcheck disable=SC2034 # consumed by the caller's EXIT trap
    LD_TXN=0
    [ "$LD_MODE" = dns ] || rm -f "$LD_PROOF"
    rm -rf "${LD_DIR:?}"; LD_DIR=
    [ "$ld_changed" != 0 ] || done_ok "list-mode $LD_GROUP $LD_MODE" unchanged
    done_ok "list-mode $LD_GROUP $LD_MODE" changed
}
