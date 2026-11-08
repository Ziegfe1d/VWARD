#!/bin/sh
# OFF DATA writer receipts: preparing a plan or observing somebody else's
# matching image is not evidence that this operation dispatched that delta.
# Receipts are flushed AFTER final preflight, BEFORE the leased final exec.
# They prove an authorised attempt, never a client packet or hardware ACK.
vrb_dispatch_valid() (
    [ "$#" -eq 5 ] && vrj2_ready "$1" "$2" && vrj2_seq "$3" || return 75
    case $4 in forward) vrb_dv_name=dispatched ;; inverse) vrb_dv_name=inverse-dispatched ;; *) return 2 ;; esac
    case $5 in *[!0-9a-f]*) return 75 ;; esac
    [ "${#5}" -eq 64 ] || return 75
    vrb_dv_file=$1/$2/step.$3/$vrb_dv_name.$5
    # vrj2_file leaves vrj_llinks: single_link of the same ls (cache-aware).
    vrj2_file "$vrb_dv_file" && [ "$vrj_llinks" = 1 ] && vrj2_file "$vrb_dv_file.sha" && [ "$vrj_llinks" = 1 ] || return 75
    vrb_dv_hash "$vrb_dv_file" && vrj_slurp "$vrb_dv_file.sha" && [ "$vrb_dvh" = "$vrj_sv" ] || return 75
    IFS="$(printf '\t')" read -r vrb_dv_tag vrb_dv_ver vrb_dv_op vrb_dv_n vrb_dv_scope vrb_dv_pid vrb_dv_start vrb_dv_boot vrb_dv_plan vrb_dv_extra < "$vrb_dv_file" || return 75
    vrj_slurp "$1/$2/plan.sha"
    [ "$vrb_dv_tag" = "$vrb_dv_name" ] && [ "$vrb_dv_ver" = 2 ] && [ "$vrb_dv_op" = "$2" ] &&
        [ "$vrb_dv_n" = "$3" ] && [ "$vrb_dv_scope" = "$5" ] && [ -z "$vrb_dv_extra" ] &&
        [ "$vrb_dv_plan" = "$vrj_sv" ] || return 75
    case $vrb_dv_pid:$vrb_dv_start in *[!0-9:]*|:*|*:) return 75 ;; esac
    vrb_dv_lease=$1/$2/workers/$vrb_dv_boot.$vrb_dv_pid.$vrb_dv_start
    vrj2_file "$vrb_dv_lease" && vrb_dv_links=$vrj_llinks && vrj_lmode_l=$vrj_lmode && vrj2_file "$vrb_dv_lease.sha" || return 75
    vrb_dv_hash "$vrb_dv_lease" && vrj_slurp "$vrb_dv_lease.sha" && [ "$vrb_dvh" = "$vrj_sv" ] || return 75
    # vward_lock_boot_id: 0600/0400 single-link owned leaf whose first line
    # (read -r, default IFS) is a UUID; here it must equal the issuer's boot.
    case "$vrj_lmode_l $vrb_dv_links" in '-rw------- 1'|'-r-------- 1') ;; *) return 75 ;; esac
    vrb_dv_lb=;read -r vrb_dv_lb < "$vrb_dv_lease" || return 75
    vrb_dv_x='[0-9a-f]'
    # shellcheck disable=SC2254
    case $vrb_dv_lb in
        $vrb_dv_x$vrb_dv_x$vrb_dv_x$vrb_dv_x$vrb_dv_x$vrb_dv_x$vrb_dv_x$vrb_dv_x-$vrb_dv_x$vrb_dv_x$vrb_dv_x$vrb_dv_x-$vrb_dv_x$vrb_dv_x$vrb_dv_x$vrb_dv_x-$vrb_dv_x$vrb_dv_x$vrb_dv_x$vrb_dv_x-$vrb_dv_x$vrb_dv_x$vrb_dv_x$vrb_dv_x$vrb_dv_x$vrb_dv_x$vrb_dv_x$vrb_dv_x$vrb_dv_x$vrb_dv_x$vrb_dv_x$vrb_dv_x) ;;
        *) return 75 ;;
    esac
    [ "$vrb_dv_lb" = "$vrb_dv_boot" ]
)
# vrb_dvh = vr2_hash FILE: from the batch map of vrb_dispatch_valid_range when
# that map proved this file (same size/line limits), else vr2_hash itself.
vrb_dv_hash() {
    vrb_dvh=
    if [ -n "${vrb_dvm_base:-}" ]; then
        case $1 in "$vrb_dvm_base"/*)
            if vrj_mc_key "${1#"$vrb_dvm_base"/}"; then
                eval "vrb_dvh=\${vrb_dvm_$vrj_mk-}"
                [ -z "$vrb_dvh" ] || return 0
            fi ;;
        esac
    fi
    vrb_dvh=$(vr2_hash "$1") || return 1
    [ -n "$vrb_dvh" ]
}
# Read-only batch form for steps FROM..TO of one operation: for every step
# whose current scope (CURDIR/current.N) equals its plan post-image, the same
# vrb_dispatch_valid verdict, with ONE ls -ln for the operation/step/worker
# directories and ONE wc -lc + ONE sha256sum for all receipts and leases.
vrb_dispatch_valid_range() (
    [ "$#" -eq 5 ] && vrj2_seq "$3" && vrj2_seq "$4" && [ -d "$5" ] || return 75
    vrb_dvr_j=$1;vrb_dvr_o=$2;vrb_dvr_from=$3;vrb_dvr_to=$4;vrb_dvr_cur=$5;vrb_dvr_op=$1/$2
    set -- "$vrb_dvr_op"
    for vrb_dvr_s in "$vrb_dvr_op"/step.*; do [ -d "$vrb_dvr_s" ] && [ ! -L "$vrb_dvr_s" ] && set -- "$@" "$vrb_dvr_s";done
    if [ -d "$vrb_dvr_op/workers" ] && [ ! -L "$vrb_dvr_op/workers" ]; then set -- "$@" "$vrb_dvr_op/workers";fi
    vrj_mc_load "$vrb_dvr_op" "$@"
    vrj_mc_plans "$vrb_dvr_op/plan"
    set --
    for vrb_dvr_f in "$vrb_dvr_op"/step.*/dispatched.* "$vrb_dvr_op"/workers/*; do
        [ -f "$vrb_dvr_f" ] && [ ! -L "$vrb_dvr_f" ] && [ -r "$vrb_dvr_f" ] || continue
        case $vrb_dvr_f in *.sha|*'
'*) continue ;; esac
        set -- "$@" "$vrb_dvr_f"
    done
    vrb_dvm_base=
    if [ "$#" -gt 0 ]; then
        vrb_dvr_wc=$(LC_ALL=C wc -lc "$@" 2>/dev/null) && vrb_dvr_sum=$(LC_ALL=C sha256sum "$@" 2>/dev/null) && {
            vrb_dvr_ok=1
            for vrb_dvr_f in "$@"; do
                vrb_dvr_l=${vrb_dvr_wc%%"$vrj_nl"*};vrb_dvr_wc=${vrb_dvr_wc#"$vrb_dvr_l"};vrb_dvr_wc=${vrb_dvr_wc#"$vrj_nl"}
                vrb_dvr_h=${vrb_dvr_sum%%"$vrj_nl"*};vrb_dvr_sum=${vrb_dvr_sum#"$vrb_dvr_h"};vrb_dvr_sum=${vrb_dvr_sum#"$vrj_nl"}
                # shellcheck disable=SC2086
                set -- $vrb_dvr_l
                [ "$#" -eq 3 ] && [ "$3" = "$vrb_dvr_f" ] && [ "${vrb_dvr_h#*  }" = "$vrb_dvr_f" ] || { vrb_dvr_ok=0;break; }
                case $1:$2 in *[!0-9:]*|:*|*:) vrb_dvr_ok=0;break ;; esac
                # vr2_file limits; a file over them has no map entry (vr2_hash fails it).
                [ "$2" -le 1048576 ] && [ "$1" -le 4096 ] || continue
                vrb_dvr_h=${vrb_dvr_h%%  *}
                case $vrb_dvr_h in *[!0-9a-f]*) vrb_dvr_ok=0;break ;; esac
                [ "${#vrb_dvr_h}" -eq 64 ] || { vrb_dvr_ok=0;break; }
                vrj_mc_key "${vrb_dvr_f#"$vrb_dvr_op"/}" || continue
                eval "vrb_dvm_$vrj_mk=\$vrb_dvr_h"
            done
            [ "$vrb_dvr_ok" = 1 ] && vrb_dvm_base=$vrb_dvr_op
        }
    fi
    vrb_dvr_n=$vrb_dvr_from
    while [ "$vrb_dvr_n" -le "$vrb_dvr_to" ]; do
        vrj2_row_fields "$vrb_dvr_op" "$vrb_dvr_n" || return 75
        vrj_slurp "$vrb_dvr_cur/current.$vrb_dvr_n"
        if [ "$vrj_sv" = "$vrj2_post" ]; then
            vrb_dispatch_valid "$vrb_dvr_j" "$vrb_dvr_o" "$vrb_dvr_n" forward "$vrj2_post" || return 75
        fi
        vrb_dvr_n=$((vrb_dvr_n+1))
    done
)
vrb_dispatch_scope() (
    : "${vrb_j:?}" "${vrb_op:?}" "${vrb_active_step:?}" "${vrb_e:?}" "${vrb_t:?}" "${vrb_pub_pid:?}" "${vrb_pub_mode:?}"
    [ "$#" -eq 2 ] || return 2
    vrb_ds_row=$(vrj2_step_row "$vrb_j/$vrb_op" "$vrb_active_step") || return 75
    vrb_ds_kind=$(printf '%s\n' "$vrb_ds_row" | cut -f4);vrb_ds_id=$(printf '%s\n' "$vrb_ds_row" | cut -f5)
    case $vrb_ds_kind:$vrb_ds_id in
        group:*)
            [ "$2" = "$(vrb_native_path)" ] && [ "$1" != - ] || return 75
            vrb_cfg_image "$1" "$vrb_ds_id" > "$vrb_t/dispatch.scope.$vrb_pub_pid" || return 75 ;;
        dns-scope:keenetic)
            [ "$2" = "$(vrb_native_path)" ] && [ "$1" != - ] || return 75
            vrb_https_scope "$1" > "$vrb_t/dispatch.scope.$vrb_pub_pid" || return 75 ;;
        dns-scope:agh)
            [ "$2" = "$(vrb_agh_path)" ] && [ "$1" != - ] || return 75
            vrb_agh_scope "$1" > "$vrb_t/dispatch.scope.$vrb_pub_pid" || return 75 ;;
        saved:routing-state)
            case $2 in "$vrb_e/decision/"*.tsv) ;; *) return 75 ;; esac
            vrb_ds_key=${2##*/};vrb_ds_key=${vrb_ds_key%.tsv}
            vrb_state_step_valid "$vrb_t" "$vrb_j/$vrb_op" "$vrb_active_step" || return 75
            vrb_state_image "$vrb_e/decision" "$vrb_t/dispatch.state.$vrb_pub_pid" &&
                cmp -s "$vrb_t/dispatch.state.$vrb_pub_pid" "$vrb_t/state.expected" || return 75
            if [ "$1" = - ]; then vrb_ds_line=$(printf '%s\t-\t-\t-' "$vrb_ds_key")
            else
                case $vrb_pub_mode in 0600) vrb_ds_mode=-rw------- ;; 0400) vrb_ds_mode=-r-------- ;; *) return 75 ;; esac
                vrb_ds_line=$(printf '%s\t%s\t%s\t%s' "$vrb_ds_key" "$(vr2_hash "$1")" "$vrb_ds_mode" "$(id -u)")
            fi
            awk -F'\t' -v k="$vrb_ds_key" -v line="$vrb_ds_line" '$1==k{print line;seen++;next}{print}END{if(seen!=1)exit 2}' \
                "$vrb_t/dispatch.state.$vrb_pub_pid" > "$vrb_t/dispatch.scope.$vrb_pub_pid" || return 75 ;;
        *)
            [ "$(vrb_local_path "$vrb_ds_kind" "$vrb_ds_id")" = "$2" ] || return 75
            if [ "$1" = - ]; then printf '%s\n' - > "$vrb_t/dispatch.scope.$vrb_pub_pid"
            else cat "$1" > "$vrb_t/dispatch.scope.$vrb_pub_pid";fi || return 1 ;;
    esac
    vr2_hash "$vrb_t/dispatch.scope.$vrb_pub_pid"
)
vrb_dispatch_mark() {
    : "${vrb_role:?}" "${vrb_pub_start:?}" "${vrj2_boot:?}"
    case $vrb_role in save|baseline-save) return 0 ;; forward|inverse) ;; *) return 75 ;; esac
    vrb_dm_new=0
    # A plain local-file publication (vrb_publish_local) supplies the scope it
    # computed from the same source bytes: the scope of such a kind IS the
    # source content (vrb_dispatch_scope's last case); destination checked.
    if [ -n "${vrb_pub_scope_known:-}" ]; then
        [ "$(vrb_local_path "$vrb_pk_k" "$(printf '%s\n' "$vrj2_row" | cut -f5)")" = "$2" ] || return 75
        vrb_dm_scope=$vrb_pub_scope_known
    else vrb_dm_scope=$(vrb_dispatch_scope "$1" "$2") || return 75;fi
    vrb_dm_row=$(vrj2_step_row "$vrb_j/$vrb_op" "$vrb_active_step") || return 75
    if [ "$vrb_role" = forward ]; then
        printf '%s\n' "$vrb_dm_row" | awk -F'\t' -v h="$vrb_dm_scope" '
            $7==h{ok=1}{n=split($10,a,",");for(i=1;i<=n;i++)if(a[i]=="prefix:" h)ok=1}END{exit ok?0:1}' || return 75
        vrb_dm_name=dispatched
    else
        [ "$(cat "$vrb_j/$vrb_op/step.$vrb_active_step/state")" = compensating ] || return 75
        vrb_dm_kind=$(printf '%s\n' "$vrb_dm_row" | cut -f4)
        vrb_dm_id=$(printf '%s\n' "$vrb_dm_row" | cut -f5)
        case $vrb_dm_kind:$vrb_dm_id in
            group:*) [ "$vrb_dm_scope" = "$(vr2_hash "$vrb_t/inverse.next")" ] || return 75 ;;
            dns-scope:keenetic) [ "$vrb_dm_scope" = "$(vr2_hash "$vrb_t/dns.inverse.next")" ] || return 75 ;;
            saved:routing-state)
                printf '%s\n' "$vrb_dm_row" | awk -F'\t' -v h="$vrb_dm_scope" '
                    $6==h{ok=1}{n=split($10,a,",");for(i=1;i<=n;i++)if(a[i]=="prefix:" h)ok=1}END{exit ok?0:1}' || return 75 ;;
            *) [ "$vrb_dm_scope" = "$(printf '%s\n' "$vrb_dm_row" | cut -f6)" ] || return 75 ;;
        esac
        vrb_dm_name=inverse-dispatched
    fi
    vrb_dm_file=$vrb_j/$vrb_op/step.$vrb_active_step/$vrb_dm_name.$vrb_dm_scope
    if [ -e "$vrb_dm_file" ] || [ -L "$vrb_dm_file" ] || [ -e "$vrb_dm_file.sha" ] || [ -L "$vrb_dm_file.sha" ]; then
        # Explicit inverse may retry a proved NOT-applied attempt after its
        # final utility is gone and the exact own precondition still holds.
        # Keep the original immutable receipt; never replay a forward step.
        [ "$vrb_role" = inverse ] && vrb_dispatch_valid "$vrb_j" "$vrb_op" "$vrb_active_step" inverse "$vrb_dm_scope" || return 75
        vrb_dm_issuer=$(awk -F'\t' '{print $8 "." $6 "." $7}' "$vrb_dm_file") || return 75
        vrb_dm_live=0;vlg_boot="$vrj2_boot" vward_lock_gate_live "$vrb_dm_issuer" || vrb_dm_live=$?
        [ "$vrb_dm_live" = 1 ] || return 75
        return 0
    fi
    vrj2_put "$vrb_dm_file" "$(printf '%s\t2\t%s\t%s\t%s\t%s\t%s\t%s\t%s' "$vrb_dm_name" "$vrb_op" "$vrb_active_step" "$vrb_dm_scope" "$vrb_pub_pid" "$vrb_pub_start" "$vrj2_boot" "$(cat "$vrb_j/$vrb_op/plan.sha")")" &&
        vrj2_put "$vrb_dm_file.sha" "$(vr2_hash "$vrb_dm_file")" && vrj2_flush || return 1
    # Output consumed by the calling publisher; not an admission override.
    # shellcheck disable=SC2034
    vrb_dm_new=1
}
