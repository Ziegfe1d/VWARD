#!/bin/sh
# One physical local-state transaction, like one native group with several
# commands. Every file delta/prefix is frozen before BEGIN; version is last.
# No schema migration flag grants native/DNS permissions.
vrb_state_image() (
    [ "$#" -eq 2 ] && vrj_dir "$1" || return 2
    for vrb_si_file in "$1"/*; do
        [ ! -e "$vrb_si_file" ] && [ ! -L "$vrb_si_file" ] && continue
        case ${vrb_si_file##*/} in version.tsv|choices.tsv|bindings.tsv|evidence.tsv|policies.tsv|saved.tsv|queue.tsv|tombstones.tsv|context.tsv|resources.tsv|proofs.tsv|upstreams.tsv) ;; *) return 75 ;; esac
    done
    : > "$2" || return 1
    for vrb_si_key in $(vrb_state_names); do
        vrb_si_file=$1/$vrb_si_key.tsv
        if [ ! -e "$vrb_si_file" ] && [ ! -L "$vrb_si_file" ]; then printf '%s\t-\t-\t-\n' "$vrb_si_key" >> "$2"
        else
            vrj2_file "$vrb_si_file" && vrb_single_link "$vrb_si_file" || return 75
            # Numeric owner and mode only, no filename fields.
            # shellcheck disable=SC2012
            vrb_si_meta=$(ls -ldn "$vrb_si_file" | awk '{print substr($1,1,10) "\t" $3}') || return 75
            printf '%s\t%s\t%s\n' "$vrb_si_key" "$(vr2_hash "$vrb_si_file")" "$vrb_si_meta" >> "$2" || return 1
        fi
    done
)
vrb_state_bundle() (
    cd "$1" || return 2
    for vrb_sb_file in pre post commands prefix.* before/* after/*; do
        [ ! -e "$vrb_sb_file" ] && [ ! -L "$vrb_sb_file" ] && continue
        vrj2_file "$vrb_sb_file" || return 2
        printf '%s\t%s\n' "$vrb_sb_file" "$(vr2_hash "$vrb_sb_file")"
    done | sha256sum | awk '{print $1}'
)
vrb_state_step_valid() (
    [ "$#" -eq 3 ] && vrj2_seq "$3" && vrj_dir "$1/state" || return 75
    vrb_sv_hash=$(vrb_state_bundle "$1/state") || return 75
    vrb_sv_pre=$(vr2_hash "$1/state/pre") && vrb_sv_post=$(vr2_hash "$1/state/post") || return 75
    vrj2_step_row "$2" "$3" | awk -F'\t' -v h="$vrb_sv_hash" -v pre="$vrb_sv_pre" -v post="$vrb_sv_post" '
        $4=="saved" && $5=="routing-state" && $6==pre && $7==post {
            n=split($10,a,",");for(i=1;i<=n;i++)if(a[i]=="state-data:" h)ok++
        }END{exit ok==1?0:1}'
)
vrb_compile_state_set() (
    umask 077
    [ "$#" -eq 5 ] && vr2_stage_valid "$1" && vrj_dir "$2" && vrj_dir "$3" && vrj_dir "$4" || return 2
    case $5 in ''|.tsv) ;; *) return 2 ;; esac
    vrb_ss_ext=$5
    [ ! -e "$4/state" ] && [ ! -L "$4/state" ] || return 75
    mkdir "$4/state" "$4/state/before" "$4/state/after" || return 1
    vrb_state_image "$2" "$4/state/pre" || return 75
    : > "$4/state/post";: > "$4/state/commands"
    for vrb_ss_key in $(vrb_state_names); do
        vrb_ss_before=$(awk -F'\t' -v k="$vrb_ss_key" '$1==k{print $2 "\t" $3 "\t" $4}' "$4/state/pre")
        vrb_ss_expected=$(awk -v k="v2-$vrb_ss_key" '$1==k{if($2=="absent")print "-\t-\t-";else print $2 "\t" $6 "\t" $7}' "$1/inputs.fp")
        [ "$vrb_ss_before" = "$vrb_ss_expected" ] || return 75
        vrb_ss_oldhash=$(printf '%s\n' "$vrb_ss_before" | cut -f1)
        if [ "$vrb_ss_oldhash" != - ]; then cp "$2/$vrb_ss_key.tsv" "$4/state/before/$vrb_ss_key" || return 1;fi
        vrb_ss_file=$3/$vrb_ss_key$vrb_ss_ext
        if [ -e "$vrb_ss_file" ] || [ -L "$vrb_ss_file" ]; then
            vrj2_file "$vrb_ss_file" || return 75
            cp "$vrb_ss_file" "$4/state/after/$vrb_ss_key" || return 1
            vrb_ss_hash=$(vr2_hash "$vrb_ss_file") || return 1
            vrb_ss_mode=$(printf '%s\n' "$vrb_ss_before" | cut -f2)
            [ "$vrb_ss_mode" != - ] || vrb_ss_mode=-rw-------
            printf '%s\t%s\t%s\t%s\n' "$vrb_ss_key" "$vrb_ss_hash" "$vrb_ss_mode" "$(id -u)" >> "$4/state/post"
        else printf '%s\t-\t-\t-\n' "$vrb_ss_key" >> "$4/state/post";fi
    done
    cp "$4/state/pre" "$4/state/prefix"
    vrb_ss_n=0;vrb_ss_checks=generation,identity,postimage
    for vrb_ss_key in $(vrb_state_names); do
        vrb_ss_pre=$(awk -F'\t' -v k="$vrb_ss_key" '$1==k' "$4/state/pre")
        vrb_ss_post=$(awk -F'\t' -v k="$vrb_ss_key" '$1==k' "$4/state/post")
        [ "$vrb_ss_pre" != "$vrb_ss_post" ] || continue
        printf '%s\n' "$vrb_ss_key" >> "$4/state/commands"
        awk -F'\t' -v k="$vrb_ss_key" 'FILENAME==ARGV[1]{if($1==k)r=$0;next}{if($1==k)print r;else print}' "$4/state/post" "$4/state/prefix" > "$4/state/next" || return 2
        mv "$4/state/next" "$4/state/prefix" || return 1
        vrb_ss_n=$((vrb_ss_n+1))
        cp "$4/state/prefix" "$4/state/prefix.$vrb_ss_n" || return 1
        vrb_ss_checks=$vrb_ss_checks,prefix:$(vr2_hash "$4/state/prefix")
    done
    cmp -s "$4/state/prefix" "$4/state/post" || return 2
    cp "$1/inputs.fp" "$4/inputs.fp" && cp "$1/generation" "$4/generation" || return 1
    printf 'routing-plan\t2\t%s\tdenied\n' "$(cat "$1/generation")" > "$4/plan"
    printf '%s\n' legacy-observation > "$4/reader"
    cp "$4/state/pre" "$4/pre.1" && cp "$4/state/post" "$4/post.1" || return 1
    printf 'step\t1\tmove\tsaved\trouting-state\t%s\t%s\tcreation-and-cas\t-\t%s,state-data:%s,attrs:%s,reader:%s\trestore-own-scope\n' \
        "$(vr2_hash "$4/pre.1")" "$(vr2_hash "$4/post.1")" "$vrb_ss_checks" "$(vrb_state_bundle "$4/state")" \
        "$(vr2_hash "$4/inputs.fp")" "$(vr2_hash "$4/reader")" >> "$4/plan"
    vrj2_plan_valid "$4/plan"
)
vrb_state_write() (
    : "${vrb_e:?}" "${vrb_t:?}" "${vrb_j:?}" "${vrb_op:?}" "${vrb_active_step:?}"
    vrb_sw_step=$vrb_active_step
    vrb_state_step_valid "$vrb_t" "$vrb_j/$vrb_op" "$vrb_sw_step" || return 75
    if [ "$1" = forward ]; then
        cp "$vrb_t/state/pre" "$vrb_t/state.expected" || return 1
        cp "$vrb_t/state/commands" "$vrb_t/state.sequence" || return 1
    elif [ "$1" = inverse ]; then
        vrb_role=inverse;export vrb_role
        cp "$vrb_t/current" "$vrb_t/state.expected" || return 1
        awk '{a[NR]=$0}END{for(i=NR;i>0;i--)print a[i]}' "$vrb_t/state/commands" > "$vrb_t/state.sequence"
    else return 2;fi
    vrb_sw_n=0
    while IFS= read -r vrb_sw_key; do
        vrb_state_image "$vrb_e/decision" "$vrb_t/state.current" || return 75
        cmp -s "$vrb_t/state.current" "$vrb_t/state.expected" || return 75
        if [ "$1" = forward ]; then vrb_sw_side=after;vrb_sw_image=$vrb_t/state/post
        else vrb_sw_side=before;vrb_sw_image=$vrb_t/state/pre;fi
        vrb_sw_line=$(awk -F'\t' -v k="$vrb_sw_key" '$1==k' "$vrb_sw_image")
        vrb_sw_current=$(awk -F'\t' -v k="$vrb_sw_key" '$1==k' "$vrb_t/state.current")
        [ "$vrb_sw_current" != "$vrb_sw_line" ] || continue
        vrb_sw_pre=$(printf '%s\n' "$vrb_sw_current" | cut -f2)
        vrb_sw_post=$(printf '%s\n' "$vrb_sw_line" | cut -f2)
        if [ "$vrb_sw_pre" = - ]; then vrb_sw_pre=$(printf '%s\n' - | sha256sum | awk '{print $1}');fi
        [ ! -f "$vrb_e/local-fails" ] || [ "$(cat "$vrb_e/local-fails")" != "$vrb_sw_key" ] || return 1
        if [ "$vrb_sw_post" = - ]; then vrb_publish - "$vrb_e/decision/$vrb_sw_key.tsv" "$vrb_sw_pre" || return 75
        else
            [ "$(vr2_hash "$vrb_t/state/$vrb_sw_side/$vrb_sw_key")" = "$vrb_sw_post" ] || return 75
            vrb_publish_image "$vrb_t/state/$vrb_sw_side/$vrb_sw_key" "$vrb_e/decision/$vrb_sw_key.tsv" "$vrb_sw_pre" || return 75
        fi
        awk -F'\t' -v k="$vrb_sw_key" 'FILENAME==ARGV[1]{if($1==k)r=$0;next}{if($1==k)print r;else print}' "$vrb_sw_image" "$vrb_t/state.expected" > "$vrb_t/state.next"
        mv "$vrb_t/state.next" "$vrb_t/state.expected" || return 1
        vrb_state_image "$vrb_e/decision" "$vrb_t/state.current" && cmp -s "$vrb_t/state.current" "$vrb_t/state.expected" || return 75
        vrb_sw_n=$((vrb_sw_n+1))
    done < "$vrb_t/state.sequence"
)
