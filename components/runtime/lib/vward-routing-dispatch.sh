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
    vrj2_file "$vrb_dv_file" && vrj2_file "$vrb_dv_file.sha" &&
        vrb_single_link "$vrb_dv_file" && vrb_single_link "$vrb_dv_file.sha" &&
        [ "$(vr2_hash "$vrb_dv_file")" = "$(cat "$vrb_dv_file.sha")" ] || return 75
    IFS="$(printf '\t')" read -r vrb_dv_tag vrb_dv_ver vrb_dv_op vrb_dv_n vrb_dv_scope vrb_dv_pid vrb_dv_start vrb_dv_boot vrb_dv_plan vrb_dv_extra < "$vrb_dv_file" || return 75
    [ "$vrb_dv_tag" = "$vrb_dv_name" ] && [ "$vrb_dv_ver" = 2 ] && [ "$vrb_dv_op" = "$2" ] &&
        [ "$vrb_dv_n" = "$3" ] && [ "$vrb_dv_scope" = "$5" ] && [ -z "$vrb_dv_extra" ] &&
        [ "$vrb_dv_plan" = "$(cat "$1/$2/plan.sha")" ] || return 75
    case $vrb_dv_pid:$vrb_dv_start in *[!0-9:]*|:*|*:) return 75 ;; esac
    vrb_dv_lease=$1/$2/workers/$vrb_dv_boot.$vrb_dv_pid.$vrb_dv_start
    vrj2_file "$vrb_dv_lease" && vrj2_file "$vrb_dv_lease.sha" &&
        [ "$(vr2_hash "$vrb_dv_lease")" = "$(cat "$vrb_dv_lease.sha")" ] &&
        [ "$(vward_lock_boot_id "$vrb_dv_lease")" = "$vrb_dv_boot" ]
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
    vrb_dm_scope=$(vrb_dispatch_scope "$1" "$2") || return 75
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
