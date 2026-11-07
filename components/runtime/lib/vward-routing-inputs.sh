#!/bin/sh
# Fresh configuration observations for ordinary owner actions. Catalog binding
# proves configured membership only, never native ownership or a client path.

vrl_interface_observe() (
    : "${vrl_ndmc:?}"
    vward_valid_ndm_name "$1" || return 75
    vrl_io_body=$("$vrl_ndmc" -c "show interface $1" 2>/dev/null) || { printf 'unknown\n';return 0; }
    printf '%s\n' "$vrl_io_body" | awk '
        /^[[:space:]]*(Command::|[Ee][Rr][Rr][Oo][Rr][: ]|[Ff]ailed[: ])/ {bad=1}
        /^[[:space:]]*state:/ {s=$2;ns++}
        /^[[:space:]]*link:/ {l=$2;nl++}
        /^[[:space:]]*conf:/ && $2=="disabled" {off=1}
        END {if(bad || ns!=1 || nl!=1)print "unknown"
            else if(off || s=="down" || l=="down")print "unavailable"
            else if(s=="up" && l=="up")print "available"
            else print "unknown"}'
)

vrl_inputs_compile() (
    [ "$#" -eq 5 ] && vr2_stage_valid "$1" && vrj_dir "$2" && vrj_dir "$4" || return 75
    vrl_ic_stage=$1;vrl_ic_raw=$2;vrl_ic_sid=$3;vrl_ic_out=$4
    # Match the existing profile's private owned 0600/0400 trust boundary;
    # capturing otherwise consistent bytes does not grant configuration rights.
    vrj2_file "$vrl_ic_raw/dev" || return 75
    case $5 in off) vrl_ic_withdraw=1 ;; vpn) vrl_ic_withdraw=0 ;; *) return 75 ;; esac
    printf '%s\n' "$vrl_ic_sid" | grep -Eq '^[a-z0-9][a-z0-9.@_-]{0,62}$' || return 75
    for vrl_ic_key in $(vrb_state_names); do
        cp "$vrl_ic_stage/decision/$vrl_ic_key.tsv" "$vrl_ic_out/$vrl_ic_key" || return 1
    done
    vrl_ic_cat=0
    for vrl_ic_key in catalog-fetched catalog-bundled; do
        [ -f "$vrl_ic_raw/$vrl_ic_key" ] || continue
        # shellcheck disable=SC2016
        if "${JQ:-jq}" -er 'if .schema==1 and (.services|type)=="array" and (.services|length)>0 and
            all(.services[];(.id|type)=="string" and (.category|type)=="string" and
                (.domains|type)=="array" and (.domains|length)>0 and all(.domains[];type=="string"))
            then .services[] | . as $s | .domains[] | [$s.id,$s.category,ascii_downcase] | @tsv
            else error("catalog unknown") end' "$vrl_ic_raw/$vrl_ic_key" > "$vrl_ic_out/catalog"; then
            vrl_ic_cat=1;break
        fi
    done
    if [ "$vrl_ic_cat" != 1 ]; then
        [ "$vrl_ic_withdraw" = 1 ] || return 75
        : > "$vrl_ic_out/catalog" || return 1
    fi
    vrl_ic_categories=$vrl_ic_raw/categories
    if [ ! -e "$vrl_ic_categories" ] && [ ! -L "$vrl_ic_categories" ]; then
        # Absent means ordinary profile default only when the SAME captured
        # generation explicitly recorded absence. An unreadable file is not it.
        awk '$1=="categories"{if(NF!=2 || $2!="absent")bad=1;n++}END{exit bad || n!=1}' "$vrl_ic_stage/inputs.fp" || return 75
        vrl_ic_categories=$vrl_ic_out/categories.empty
        : > "$vrl_ic_categories" || return 1
    fi
    awk -F'\t' -v sid="$vrl_ic_sid" -v withdrawal="$vrl_ic_withdraw" 'BEGIN{OFS="\t";wanted[sid]=1}
        function id(s){return length(s)<=63 && s~/^[a-z0-9][a-z0-9.@_-]*$/}
        function domain(d,a,n,i){if(length(d)>253 || d!~/^[a-z0-9.-]+$/)return 0;n=split(d,a,".");if(n<2 || a[n]~/^[0-9]+$/)return 0
            for(i=1;i<=n;i++)if(length(a[i])>63 || a[i]!~/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/)return 0;return 1}
        FILENAME==ARGV[1]{if($1=="service")wanted[$2]=1;next}
        FILENAME==ARGV[2]{if(NF!=6 || !id($1) || !domain($2) || seen[$1 SUBSEP $2 SUBSEP $3]++)bad=1;old[++n]=$0;next}
        {if(NF!=3 || !id($1) || !id($2) || !domain($3) || (($1 in category) && category[$1]!=$2))bad=1
            category[$1]=$2;if($1 in wanted)catalog[$1 SUBSEP $3]=1}
        END{if(!(sid in category) && !withdrawal)bad=1;if(bad)exit 2
            for(i=1;i<=n;i++){
                split(old[i],a,OFS)
                # No provenance permits retaining old catalog confirmation
                # after membership retirement. Keep the row conservatively as
                # unknown; exclusions/shared/manual evidence are not erased.
                if(a[4]=="confirmed" && (a[3]!="exact" || !(a[1] SUBSEP a[2] in catalog)))
                    print a[1],a[2],a[3],"unknown","unknown","unknown"
                else print old[i]
            }
            for(k in catalog){split(k,a,SUBSEP);if(!(a[1] SUBSEP a[2] SUBSEP "exact" in seen)) {if(++n>1024)exit 2;print a[1],a[2],"exact","confirmed","ipv4","known"}}
            if(n>1024)exit 2}' "$vrl_ic_out/choices" "$vrl_ic_out/bindings" "$vrl_ic_out/catalog" > "$vrl_ic_out/bindings.next" || return 75
    LC_ALL=C sort "$vrl_ic_out/bindings.next" > "$vrl_ic_out/bindings" || return 1
    # Profile and category files are the SAME archived generation as catalog.
    # No sourcing of shell configuration and no fallback for a missing target.
    awk -F'\t' 'BEGIN{OFS="\t"}
        function target(t){return length(t)<=64 && t~/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/ && t!="auto"}
        FILENAME==ARGV[1]{if($1!~/^VPN:/ && $1!="default-vpn" && $1!~/^service-vpn:/)print;next}
        FILENAME==ARGV[2]{n=split($0,a,"=");if(a[1]=="VWARD_TUNNEL_INTERFACE"){if(n!=2 || !target(a[2]) || def++)bad=1;default_t=a[2]}next}
        FILENAME==ARGV[3]{if(NF!=2 || !target($2) || ($1 in cats))bad=1;cats[$1]=$2;next}
        {if(!($1 in services)){services[$1]=1;if($2 in cats)print "service-vpn:" $1,"VPN:" cats[$2]}}
        END{if(bad || def!=1)exit 2;print "default-vpn","VPN:" default_t}' \
        "$vrl_ic_out/context" "$vrl_ic_raw/dev" "$vrl_ic_categories" "$vrl_ic_out/catalog" > "$vrl_ic_out/context.next" || return 75
    vrl_ic_wan=$(awk -F= '$1=="VWARD_WAN_DEVICE"{if(++n>1)exit 2;print $2}' "$vrl_ic_raw/dev") || return 75
    vrl_ic_wan_name=$(awk -F= '$1=="VWARD_WAN_INTERFACE"{if(++n>1)exit 2;print $2}END{if(n!=1)exit 2}' "$vrl_ic_raw/dev") || return 75
    vward_valid_ndm_name "$vrl_ic_wan_name" || return 75
    vrl_ic_map=$(cat "$vrl_ic_raw/map") || return 75
    vrl_ic_vpns=$(vward_map_vpns "$vrl_ic_map" "$vrl_ic_wan" | awk -v wan="$vrl_ic_wan_name" '$1!=wan') || return 75
    vrl_ic_n=0
    while read -r vrl_ic_vpn _vrl_ic_kernel; do
        [ -n "$vrl_ic_vpn" ] || continue
        vrl_ic_n=$((vrl_ic_n+1));[ "$vrl_ic_n" -le 128 ] || return 75
        vrl_ic_health=$(vrl_interface_observe "$vrl_ic_vpn") || return 75
        printf 'VPN:%s\t%s\n' "$vrl_ic_vpn" "$vrl_ic_health" >> "$vrl_ic_out/context.next" || return 1
    done <<EOF
$vrl_ic_vpns
EOF
    LC_ALL=C sort "$vrl_ic_out/context.next" > "$vrl_ic_out/context" || return 1
    awk -F'\t' 'NF!=2 || seen[$1]++ {bad=1}END{exit bad?1:0}' "$vrl_ic_out/context" || return 75
)

vrl_inputs_refresh() {
    # Direct call inside the SAME admitted EDIT/CHANGE owner. No nested CLI or
    # second lock acquisition; the accepted owner choice remains a later J2.
    : "${vrb_op:?}" "${vrb_j:?}" "${vrb_e:?}"
    vrl_map_prepare || return 75
    vrl_if_parent=$vrb_op
    vrl_if_hash=$(printf '%s' "$vrb_op" | sha256sum);vrl_if_hash=${vrl_if_hash%% *}
    vrb_op=i-${vrl_if_hash%????????????????????????????????????????????????}
    vrl_if_work=$(mktemp -d "$vrb_j/.inputs.XXXXXX") || return 1
    mkdir "$vrl_if_work/stage" "$vrl_if_work/raw" "$vrl_if_work/after" "$vrl_if_work/lowered" || return 1
    vrb_transport_refresh && vward_routing_consistent_read2 "$vrl_if_work/stage" "$vrb_e/decision" > "$vrl_if_work/read.status" &&
        vrb_legacy_archive "$vrl_if_work/stage" "$vrb_e" "$vrl_if_work/raw" &&
        vrl_inputs_compile "$vrl_if_work/stage" "$vrl_if_work/raw" "$1" "$vrl_if_work/after" "$2" || return 75
    vrl_if_changed=0
    for vrl_if_key in $(vrb_state_names); do
        cmp -s "$vrl_if_work/stage/decision/$vrl_if_key.tsv" "$vrl_if_work/after/$vrl_if_key" || vrl_if_changed=1
    done
    # Fresh observations may be semantically unchanged. Do not manufacture a
    # physical matching-image transaction or a new receipt for a no-op. The
    # following action still captures/checks its own generation under the lock.
    if [ "$vrl_if_changed" = 1 ]; then
        # Eligibility uses the SAME pure canonical projection/planner against
        # prospective observations. This is a denied preview, never execution
        # authority: allowed requests discard it and re-read/re-plan after the
        # real metadata J2. Refused selections need no durable state receipt.
        mkdir "$vrl_if_work/candidate" "$vrl_if_work/preview" "$vrl_if_work/project" || return 1
        for vrl_if_key in $(vrb_state_names); do
            cp "$vrl_if_work/after/$vrl_if_key" "$vrl_if_work/candidate/$vrl_if_key.tsv" || return 1
        done
        vward_routing_consistent_read2 "$vrl_if_work/preview" "$vrl_if_work/candidate" > "$vrl_if_work/preview.status" &&
            vward_routing_choice "$vrl_if_work/preview/decision/choices.tsv" "$1" "$2" "$3" "$4" "$5" > "$vrl_if_work/preview.next" &&
            vward_routing_project2 "$vrl_if_work/preview" "$1" "$vrl_if_work/preview.next" "$vrl_if_work/project" &&
            vward_routing_plan2 "$vrl_if_work/preview" "$vrl_if_work/project" preview > "$vrl_if_work/preview.plan" || return 75
        if grep -q '^hold' "$vrl_if_work/preview.plan"; then
            printf 'outcome\tblocked\tdesired-only\tunknown\tfalse\t%s\n' "$(vrb_execution_evidence)"
            return 75
        fi
        vrb_compile_state_set "$vrl_if_work/stage" "$vrb_e/decision" "$vrl_if_work/after" "$vrl_if_work/lowered" '' &&
            vrb_execute2 "$vrl_if_work/lowered" > "$vrl_if_work/result" || return 75
    fi
    # Shared executor context is consumed by the next real service operation.
    vrb_op=$vrl_if_parent
    # shellcheck disable=SC2034
    vrb_role=
    # shellcheck disable=SC2034
    vrb_active_step=
}
