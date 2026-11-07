#!/bin/sh
# One OFF outcome DTO for prepared choice/policy/plan/readback. It carries
# configuration evidence only, never packet/client proof or a live enablement.
vrb_outcome_bind() (
    [ "$#" -eq 3 ] && vr2_stage_valid "$1" && vrj_dir "$2" || return 2
    cp "$2/resources.after" "$2/outcome.resources" || return 1
    if [ -f "$2/choices.after" ]; then cp "$2/choices.after" "$2/outcome.choices"
    else cp "$1/decision/choices.tsv" "$2/outcome.choices";fi || return 1
    printf 'resources\t%s\nchoices\t%s\n' "$(vr2_hash "$2/outcome.resources")" "$(vr2_hash "$2/outcome.choices")" > "$2/outcome.data" || return 1
    vrb_ob_checks=outcome-data:$(vr2_hash "$2/outcome.data")
    if [ "$3" != - ]; then
        vr2_projection_valid "$3" || return 75
        mkdir "$2/outcome-view" || return 1
        for vrb_ob_file in atoms.tsv policy.tsv choices.tsv service dns.tsv upstream-keys.tsv generation seal seal.sha; do
            cp "$3/$vrb_ob_file" "$2/outcome-view/$vrb_ob_file" || return 1
        done
        vr2_projection_valid "$2/outcome-view" || return 75
        vrb_ob_checks=$vrb_ob_checks,outcome-view:$(vr2_hash "$2/outcome-view/seal")
    fi
    awk -F'\t' -v checks="$vrb_ob_checks" 'BEGIN{OFS="\t"}$1=="step"{$10=$10 "," checks}{print}' "$2/plan" > "$2/outcome.plan" &&
        mv "$2/outcome.plan" "$2/plan" && vrj2_plan_valid "$2/plan"
)
vrb_outcome_scope_hash() (
    [ "$#" -eq 3 ] && vr2_stage_valid "$1" || return 75
    vrb_osh_label=
    case $2:$3 in
        group:*) vrb_cfg_image "$1/native.cfg" "$3" | sha256sum | awk '{print $1}';return $? ;;
        dns-scope:keenetic) vrb_https_scope "$1/native.cfg" | sha256sum | awk '{print $1}';return $? ;;
        dns-scope:agh) vrb_agh_scope "$1/agh.json" | sha256sum | awk '{print $1}';return $? ;;
        manifest:*) vrb_osh_label=v2-$3 ;;
        nativeproof:*) vrb_osh_label=owned:$3 ;;
        registry:enabled) vrb_osh_label=enabled ;;
        saved:raw*) vrb_osh_label=$(vrb_legacy_scope "$3" label) || return 75 ;;
        *) return 75 ;;
    esac
    vrb_osh_hash=$(awk -v key="$vrb_osh_label" '$1==key {if($2=="absent")print "-";else if(length($2)==64 && $2~/^[0-9a-f]+$/)print $2;else exit 2;n++}END{if(n!=1)exit 2}' "$1/inputs.fp") || return 75
    if [ "$vrb_osh_hash" = - ]; then printf '%s\n' - | sha256sum | awk '{print $1}'
    else printf '%s\n' "$vrb_osh_hash";fi
)
# STAGE LOWERED. The journal may prove a write completed; a matching current
# image alone never clears an unknown/lost-POST barrier. Recompute the SAME
# common policy against the fresh stage so expired/old-boot A is not displayed
# as a current contributor merely because an old operation once committed.
vrb_outcome_emit() (
    umask 077
    [ "$#" -ge 2 ] && [ "$#" -le 3 ] && vr2_stage_valid "$1" && vrj_dir "$2" && vrj2_plan_valid "$2/plan" || return 75
    [ "$#" -eq 2 ] || [ "$3" = blocked ] || return 2
    rm -f "$2/outcome.json" "$2/outcome.json.sha" || return 1
    vrb_t=$2
    vrb_oe_tmp=$(mktemp -d "$2/.outcome.XXXXXX") || return 1
    trap 'rm -rf "$vrb_oe_tmp"' EXIT
    for vrb_oe_file in outcome.data outcome.resources outcome.choices; do vrj2_file "$2/$vrb_oe_file" || return 75;done
    [ "$(awk -F'\t' '$1=="resources"{print $2}' "$2/outcome.data")" = "$(vr2_hash "$2/outcome.resources")" ] &&
        [ "$(awk -F'\t' '$1=="choices"{print $2}' "$2/outcome.data")" = "$(vr2_hash "$2/outcome.choices")" ] || return 75
    vrb_oe_hash=$(vr2_hash "$2/outcome.data") || return 75
    awk -F'\t' -v h="$vrb_oe_hash" '$1=="step"{found=0;n=split($10,a,",");for(i=1;i<=n;i++)if(a[i]=="outcome-data:" h)found++;if(found!=1)bad=1}END{exit bad?1:0}' "$2/plan" || return 75
    vrb_oe_state=unrecorded;vrb_oe_matched=0;vrb_oe_total=0;vrb_oe_model=unknown;vrb_oe_sid=
    : > "$vrb_oe_tmp/atoms";: > "$vrb_oe_tmp/policy";: > "$vrb_oe_tmp/model.plan"
    if [ -d "$2/outcome-view" ]; then
        vr2_projection_valid "$2/outcome-view" || return 75
        vrb_oe_view_hash=$(vr2_hash "$2/outcome-view/seal") || return 75
        awk -F'\t' -v h="$vrb_oe_view_hash" '$1=="step"{found=0;n=split($10,a,",");for(i=1;i<=n;i++)if(a[i]=="outcome-view:" h)found++;if(found!=1)bad=1}END{exit bad?1:0}' "$2/plan" || return 75
        vrb_oe_sid=$(cat "$2/outcome-view/service")
        mkdir "$vrb_oe_tmp/project" || return 1
        if vward_routing_project2 "$1" "$vrb_oe_sid" "$2/outcome-view/choices.tsv" "$vrb_oe_tmp/project" &&
            vward_routing_plan2 "$1" "$vrb_oe_tmp/project" outcome-view > "$vrb_oe_tmp/model.plan"; then
            cp "$vrb_oe_tmp/project/atoms.tsv" "$vrb_oe_tmp/atoms" && cp "$vrb_oe_tmp/project/policy.tsv" "$vrb_oe_tmp/policy" || return 1
            vrb_oe_model=known
            if grep -Eq '^(step|hold)' "$vrb_oe_tmp/model.plan"; then vrb_oe_model=drift;fi
        else
            # Retain the declared scope, while marking every old observation
            # unknown if current choices/membership no longer validate it.
            awk -F'\t' 'BEGIN{OFS="\t"}{$9="current-snapshot-unknown";print}' "$2/outcome-view/atoms.tsv" > "$vrb_oe_tmp/atoms"
            awk -F'\t' 'BEGIN{OFS="\t"}$2=="policy"{$4="unknown";$5="denied";$6="unknown"}$2=="contribution"{$7="unknown";$8="current-snapshot-unknown"}{print}' "$2/outcome-view/policy.tsv" > "$vrb_oe_tmp/policy"
        fi
    else vrb_oe_model=operation-scope;fi
    if vrj2_ready "$vrb_j" "$vrb_op" && cmp -s "$vrb_j/$vrb_op/plan" "$2/plan"; then
        vrb_oe_state=$(cat "$vrb_j/$vrb_op/state")
        vward_routing_update_eligibility2 "$vrb_j" || vrb_oe_state=unknown
    fi
    [ "$#" -eq 2 ] || vrb_oe_state=blocked
    while IFS="$(printf '\t')" read -r vrb_tag vrb_n _vrb_action vrb_kind vrb_id _vrb_pre vrb_post _vrb_rest; do
        [ "$vrb_tag" = step ] || continue
        vrb_oe_total=$((vrb_oe_total+1))
        vrb_oe_actual=$(vrb_outcome_scope_hash "$1" "$vrb_kind" "$vrb_id") || vrb_oe_actual=unknown
        case $vrb_kind:$vrb_id in
            group:*|dns-scope:keenetic) vrb_oe_path=$(vrb_native_path) ;;
            dns-scope:agh) vrb_oe_path=$vrb_e/agh.json ;;
            *) vrb_oe_path=$(vrb_local_path "$vrb_kind" "$vrb_id") || vrb_oe_path= ;;
        esac
        if [ -z "$vrb_oe_path" ] || ! vrb_active_step="$vrb_n" vrb_role=inverse vrb_publication_mode "$vrb_oe_path" >/dev/null; then vrb_oe_actual=unknown;fi
        if [ "$vrb_oe_actual" = "$vrb_post" ]; then vrb_oe_matched=$((vrb_oe_matched+1));fi
    done < "$2/plan"
    vrb_oe_configured=unknown;vrb_oe_persisted=false
    if [ "$vrb_oe_state" = committed ]; then
        if [ "$vrb_oe_matched" = "$vrb_oe_total" ] && { [ "$vrb_oe_model" = known ] || [ "$vrb_oe_model" = operation-scope ]; }; then
            vrb_oe_configured=verified;vrb_oe_persisted=true
        elif [ "$vrb_oe_matched" -gt 0 ] && [ "$vrb_oe_matched" -lt "$vrb_oe_total" ]; then vrb_oe_configured=partial;fi
    elif [ "$vrb_oe_state" = unrecorded ] && [ "$vrb_oe_total" = 0 ] && [ "$vrb_oe_model" = known ]; then vrb_oe_configured=observed;fi
    # jq expressions and public row identifiers only. The private URL table,
    # native config and raw return files are deliberately NOT JSON inputs.
    # shellcheck disable=SC2016
    "${JQ:-jq}" -n --arg sid "$vrb_oe_sid" --arg generation "$(cat "$1/generation")" --arg desired_generation "$(cat "$2/generation")" \
        --arg activation "$(vrb_activation)" --arg state "$vrb_oe_state" --arg configured "$vrb_oe_configured" --argjson persisted "$vrb_oe_persisted" \
        --argjson matched "$vrb_oe_matched" --argjson steps "$vrb_oe_total" --rawfile choices "$2/outcome.choices" \
        --rawfile resources "$2/outcome.resources" --rawfile context "$1/decision/context.tsv" --rawfile atoms "$vrb_oe_tmp/atoms" --rawfile policy "$vrb_oe_tmp/policy" '
        def rows: split("\n") | map(select(length>0)|split("\t"));
        ($choices|rows|map(select(.[0]=="service" and .[1]==$sid))|first) as $c |
        ($atoms|rows) as $a | ($policy|rows) as $p |
        ($resources|rows|map({id:.[1],domain:.[3],scope:.[4],target:.[5],policy:.[6],consumers:(.[10]|split(","))})) as $r |
        ($p|map(select(.[1]=="contribution")|{domain:.[0],source:.[2],id:.[3],target:.[4],policy:.[5],state:.[6],reason:.[7]})) as $sources |
        ($sources|map(select(.state=="active")|[.target,.policy])|unique|length) as $targets |
        ($context|rows|map(select(.[0]|startswith("source:"))|{key:(.[0]|ltrimstr("source:")),value:(if .[1]=="0" then 0 elif .[1]=="1" then 1 else null end)})|from_entries) as $switches |
        ([$a[]|select(.[8]=="-")|.[1]]-[$p[]|select(.[1]=="policy" and (.[3]=="unknown" or .[3]=="unresolved"))|.[0]]|length) as $known |
        {schema:2,activation:$activation,evidence:"configuration",client_verified:false,client_path_verified:false,scope:"own-planned-deltas",source_switches:{M:$switches.M,S:$switches.S,A:$switches.A},
         service:(if $sid=="" then null else $sid end),operation:{state:$state},
         desired:{mode:($c[3]//(if $sid=="" then "server-policy" else "auto" end)),target:($c[4]//null),policy:($c[5]//null),revision:($c[2]|tonumber? // 0),generation:$desired_generation,resources:$r},
         configured:{state:(if $configured=="verified" and $targets>1 then "mixed" else $configured end),persisted:$persisted,generation:$generation,matched_steps:$matched,total_steps:$steps},
         sources:$sources,coverage:{total:($a|length),known:$known,unknown:(($a|length)-$known)}}' > "$vrb_oe_tmp/result" || return 1
    mv "$vrb_oe_tmp/result" "$2/outcome.json" || return 1
    vr2_hash "$2/outcome.json" > "$2/outcome.json.sha"
)
# Refresh over native DATA and current files instead of serving an old green
# cache. Defines no API dispatcher and can never reach a router transport.
vward_routing_outcome_read2() (
    umask 077
    [ "$#" -eq 2 ] && vrb_data_ready "$1" && vrj2_id "$2" && vrj2_ready "$1" "$2" || return 75
    vrb_j=$1;vrb_e=$1/.emu;vrb_op=$2;vrb_t=$1/$2/prepared
    vrj_dir "$vrb_t" && cmp -s "$vrb_t/plan" "$vrb_j/$vrb_op/plan" || return 75
    vrb_or_work=$(mktemp -d "$1/.outcome-read.XXXXXX") || return 1
    trap 'rm -rf "$vrb_or_work"' EXIT
    mkdir "$vrb_or_work/stage" || return 1
    vrb_capture_image "$(vrb_native_path)" "$vrb_or_work/running-config" || return 75
    VWARD_CONSOLE_ETC=$vrb_e;VWARD_ROUTE_STATE=$vrb_e/route;VWARD_KCACHE=$vrb_or_work;VWARD_ROOT_PREFIX=$vrb_e/root
    VWARD_DEVICE_CONFIG=$vrb_e/device.conf;VWARD_DEVICE_MAP_CACHE=$vrb_e/device-map.tsv
    VWARD_SERVICES_FETCHED=$vrb_e/catalog.json;VWARD_SERVICES_BUNDLED=$vrb_e/missing
    VWARD_ROUTING_AGH_DOMAINS=$vrb_e/agh-domains;VWARD_ROUTING_AGH_IMAGE=$vrb_e/agh.json;VWARD_CONSOLE_BACKUP_DIR=$vrb_e/backup
    export VWARD_CONSOLE_ETC VWARD_ROUTE_STATE VWARD_KCACHE VWARD_ROOT_PREFIX VWARD_DEVICE_CONFIG VWARD_DEVICE_MAP_CACHE VWARD_SERVICES_FETCHED VWARD_SERVICES_BUNDLED VWARD_ROUTING_AGH_DOMAINS VWARD_ROUTING_AGH_IMAGE VWARD_CONSOLE_BACKUP_DIR
    vward_routing_consistent_read2 "$vrb_or_work/stage" "$vrb_e/decision" > "$vrb_or_work/status" || return 3
    [ "$(vr2_hash "$(vrb_native_path)")" = "$(vr2_hash "$vrb_or_work/running-config")" ] || return 3
    vrb_outcome_emit "$vrb_or_work/stage" "$vrb_t" || return $?
    cat "$vrb_t/outcome.json"
)
