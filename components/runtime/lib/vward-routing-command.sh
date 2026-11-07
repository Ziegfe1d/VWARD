#!/bin/sh
# Owner actions use the installed common coordinator. No transport, executable,
# physical pathname or backend flag is accepted from the CLI/API action.
vward_routing_live_command() (
    umask 077
    [ "$#" -eq 3 ] || return 2
    vrl_paths_bind || return 75
    : "${vrl_root:?}"
    vrl_cmd_action=$1;vrl_cmd_sid=$2;vrl_cmd_target=$3
    case $vrl_cmd_action in
        on|tunnel)
            case $vrl_cmd_target in auto) vrl_cmd_target=VPN:auto ;; ''|*[!A-Za-z0-9_.:-]*) return 2 ;; *) vrl_cmd_target=VPN:$vrl_cmd_target ;; esac
            vrl_cmd_mode=vpn;vrl_cmd_dns=default ;;
        off) [ -z "$vrl_cmd_target" ] || return 2;vrl_cmd_mode=off;vrl_cmd_target=-;vrl_cmd_dns=- ;;
        *) return 2 ;;
    esac
    printf '%s\n' "$vrl_cmd_sid" | grep -Eq '^[a-z0-9][a-z0-9.@_-]{0,62}$' || return 2
    vrl_cmd_tmp=$(mktemp -d "${VWARD_ROOT_PREFIX:-}/tmp/vward-routing-request.XXXXXX") || return 75
    trap 'rmdir "$vrl_cmd_tmp" 2>/dev/null || :' EXIT
    vrl_cmd_nonce=${vrl_cmd_tmp##*.};vrj2_id "r-$vrl_cmd_nonce" || return 75
    if [ ! -e "$vrl_root" ] && [ ! -L "$vrl_root" ]; then
        vward_routing_live_bootstrap "b-$vrl_cmd_nonce" || return 75
    fi
    vward_routing_state_gate 2 "$vrl_root/decision" || return 75
    vrl_cmd_rev=$(awk -F'\t' -v s="$vrl_cmd_sid" '$1=="service"&&$2==s {print $3;n++}END{if(!n)print 0;if(n>1)exit 2}' "$vrl_root/decision/choices.tsv") || return 75
    # Revision is rechecked under actual EDIT+CHANGE. A concurrent owner action
    # may refuse this request, never silently overwrite a newer accepted choice.
    # Installed ordinary actions always refresh inputs in that SAME envelope.
    # shellcheck disable=SC2317
    vrb_inputs_refresh() { vrl_inputs_refresh "$@"; }
    vward_routing_live_service "r-$vrl_cmd_nonce" "$vrl_cmd_sid" "$vrl_cmd_mode" "$vrl_cmd_target" "$vrl_cmd_dns" "$vrl_cmd_rev"
)
