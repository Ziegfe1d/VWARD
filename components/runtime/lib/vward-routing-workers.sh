#!/bin/sh
# OFF preparation only. No entrypoint, environment-selected transport or lock
# bypass. The pipeline below supplies a built-in DATA emulator, never NDMC.+
# One canonical native scope; includes ALL body/route metadata. Missing is a
# distinct image. A duplicate/malformed scope is not an empty group.
vrb_cfg_image() (
    [ "$#" -eq 2 ] && vr2_file "$1" || return 2
    vrb_img=$(LC_ALL=C awk -v g="$2" '
        /^object-group fqdn / {cur=($3==g);if(cur)n++;next}
        /^!/ {cur=0;dns=0;next}
        /^dns-proxy$/ {dns=1;next}
        cur {sub(/^[ \t]+/,"");if(NF)body[$0]=1}
        dns && $1=="route" && $2=="object-group" && $3==g {
            r=$4;for(i=5;i<=NF;i++)r=r "\t" $i;body["route=" r]=1
        }
        END {if(n>1)exit 3;if(!n) {for(k in body)exit 3;print "-";exit}
             print "group=" g;for(k in body)print k}' "$1") || return 3
    printf '%s\n' "$vrb_img" | LC_ALL=C sort
)

# Lower route atoms into ONE journaled native scope per group and separately
# journaled local files. Sidecars are bound by their SHA in the immutable plan.
# A native write is never confused with successful local registration.
vward_routing_lower2() (
    umask 077
    [ "$#" -eq 3 ] && vr2_stage_valid "$1" && vr2_file "$2" && vr2_private_dir "$3" || return 2
    [ ! -e "$3/plan" ] && [ ! -e "$3/generation" ] || return 75
    cp "$1/inputs.fp" "$3/inputs.fp" || return 1
    vrb_attrs_hash=$(vr2_hash "$3/inputs.fp") || return 1
    head -n1 "$2" > "$3/plan" || return 1
    vrb_g=$(cat "$1/generation")
    [ "$(cut -f3 "$3/plan")" = "$vrb_g" ] && vrj2_plan_valid "$2" || return 2
    # Reject unsupported physical actions before ANY journal/writer. This is a
    # preparation compiler, not an implicit fallback to a different backend.
    awk -F'\t' '$1=="step" && $4!~/^(route|dns|claims|choice)$/{bad=1} END{exit bad?1:0}' "$2" || return 75
    cp "$1/decision/resources.tsv" "$3/resources.before" || return 1
    cp "$3/resources.before" "$3/resources.after" || return 1
    # Typed rows replace their exact own RID; peers remain byte-for-byte rows.
    awk -F'\t' 'BEGIN{OFS="\t"}
        FILENAME==ARGV[1] {$1=$1;rows[$2]=$0;next}
        $1=="step" && $4~/^(route|dns|claims)$/ {
            if($7=="-")delete rows[$5]
            else {v=$7;gsub(/\|/,OFS,v);rows[$5]=v}
        }
        END{for(k in rows)print rows[k]}' "$3/resources.before" "$2" | LC_ALL=C sort > "$3/resources.after" || return 1
    awk -F'\t' '$1=="step" && $4=="route" {
        if($6!="-"){split($6,a,"|");sub(/^group:/,"",a[3]);print a[3]}
        if($7!="-"){split($7,a,"|");sub(/^group:/,"",a[3]);print a[3]}
    }' "$2" | LC_ALL=C sort -u > "$3/groups" || return 1
    vrb_n=0
    vrb_emit() {
        vrb_n=$((vrb_n+1))
        # PRE/POST files already exist in private scratch; freeze their bytes.
        cp "$3" "$vrb_out/pre.$vrb_n" && cp "$4" "$vrb_out/post.$vrb_n" || return 1
        printf 'step\t%s\tmove\t%s\t%s\t%s\t%s\tcreation-and-cas\t-\t%s\trestore-own-scope\n' \
            "$vrb_n" "$1" "$2" "$(vr2_hash "$3")" "$(vr2_hash "$4")" "$5,attrs:$vrb_attrs_hash" >> "$vrb_out/plan"
    }
    vrb_out=$3
    while IFS= read -r vrb_group; do
        case $vrb_group in domain-list[0-9]|domain-list[0-9][0-9]) ;; *) return 75 ;; esac
        vrb_cfg_image "$1/native.cfg" "$vrb_group" > "$3/native.pre" || return 3
        # Existing unsupported body/options cannot be erased by a guessed inverse.
        awk '/^(group=|include [a-z0-9.-]+$|route=[A-Za-z0-9_.:-]+\tauto$|-$)/{next}{bad=1}END{exit bad?1:0}' "$3/native.pre" || return 75
        awk -F'\t' -v g="group:$vrb_group" '$1=="route" && $3==g {print "include " $4;print "route=" substr($6,5) "\tauto"}' \
            "$3/resources.after" | LC_ALL=C sort -u > "$3/native.members" || return 1
        if [ -s "$3/native.members" ]; then
            { printf 'group=%s\n' "$vrb_group";cat "$3/native.members"; } | LC_ALL=C sort > "$3/native.post"
        else printf '%s\n' - > "$3/native.post";fi
        # Every native include must be represented by the verified manifest.
        awk -F'\t' -v g="group:$vrb_group" '$1=="route" && $3==g {print "include " $4;print "route=" substr($6,5) "\tauto"}' \
            "$3/resources.before" | LC_ALL=C sort -u > "$3/native.coverage"
        if [ "$(cat "$3/native.pre")" != - ]; then
            grep -v '^group=' "$3/native.pre" > "$3/native.oldmembers"
            cmp -s "$3/native.oldmembers" "$3/native.coverage" || return 75
        fi
        # Compile exact commands and EVERY prefix image before the first write.
        : > "$3/commands.next";cp "$3/native.pre" "$3/prefix"
        if [ "$(cat "$3/native.pre")" = - ]; then
            printf 'create\t%s\t-\tadd\n' "$vrb_group" >> "$3/commands.next"
        fi
        awk 'FILENAME==ARGV[1]{old[$0]=1;next}!($0 in old)&&/^include /{print "include\t" substr($0,9) "\tadd"}' "$3/native.pre" "$3/native.post" |
            while IFS="$(printf '\t')" read -r vrb_kind vrb_value vrb_action; do
                printf '%s\t%s\t%s\t%s\n' "$vrb_kind" "$vrb_group" "$vrb_value" "$vrb_action"
            done >> "$3/commands.next"
        awk 'FILENAME==ARGV[1]{new[$0]=1;next}!($0 in new)&&/^include /{print "include\t" substr($0,9) "\tremove"}' "$3/native.post" "$3/native.pre" |
            while IFS="$(printf '\t')" read -r vrb_kind vrb_value vrb_action; do
                printf '%s\t%s\t%s\t%s\n' "$vrb_kind" "$vrb_group" "$vrb_value" "$vrb_action"
            done >> "$3/commands.next"
        for vrb_dir in remove add; do
            if [ "$vrb_dir" = remove ]; then vrb_left=$3/native.post;vrb_right=$3/native.pre
            else vrb_left=$3/native.pre;vrb_right=$3/native.post;fi
            awk 'FILENAME==ARGV[1]{seen[$0]=1;next}!($0 in seen)&&/^route=/{print substr($0,7)}' "$vrb_left" "$vrb_right" |
                while IFS="$(printf '\t')" read -r vrb_target vrb_option; do
                    [ "$vrb_option" = auto ] || exit 1
                    printf 'route\t%s\t%s\t%s\n' "$vrb_group" "$vrb_target" "$vrb_dir"
                done >> "$3/commands.next" || return 75
        done
        if [ "$(cat "$3/native.post")" = - ]; then
            printf 'delete\t%s\t-\tremove\n' "$vrb_group" >> "$3/commands.next"
        fi
        vrb_checks=generation,identity,postimage,save
        while IFS="$(printf '\t')" read -r vrb_kind _vrb_unused vrb_value vrb_action; do
            vrb_prefix_apply "$3/prefix" "$vrb_kind" "$vrb_group" "$vrb_value" "$vrb_action" > "$3/prefix.next" || return 2
            mv "$3/prefix.next" "$3/prefix" || return 1
            vrb_checks=$vrb_checks,prefix:$(vr2_hash "$3/prefix")
        done < "$3/commands.next"
        cmp -s "$3/prefix" "$3/native.post" || return 3
        vrb_checks=$vrb_checks,commands:$(vr2_hash "$3/commands.next")
        vrb_emit group "$vrb_group" "$3/native.pre" "$3/native.post" "$vrb_checks" || return 1
        mv "$3/commands.next" "$3/commands.$vrb_n" || return 1
        # Native legacy ownership is its exact signature, not a group name.
        if [ "$(cat "$3/native.pre")" = - ]; then printf '%s\n' - > "$3/proof.pre"
        else grep -v '^group=' "$3/native.pre" > "$3/proof.pre";fi
        if [ "$(cat "$3/native.post")" = - ]; then printf '%s\n' - > "$3/proof.post"
        else grep -v '^group=' "$3/native.post" > "$3/proof.post";fi
        vrb_emit nativeproof "$vrb_group" "$3/proof.pre" "$3/proof.post" generation,identity,postimage || return 1
    done < "$3/groups"
    vrb_dns_compile "$1" "$3" || return $?
    # Model manifest and its origin/content revision proof have separate writes.
    awk -F'\t' 'BEGIN{OFS="\t"}FILENAME==ARGV[1]{old[$2]=$0;next}
        FILENAME==ARGV[2]{witness[$1]=$2;next}
        $9=="vward" {r=$0;sub(/\t[^\t]*$/,"",r);rev=1
            if($2 in old){split(old[$2],a,OFS);before=old[$2];sub(/\t[^\t]*$/,"",before)
                if($1=="dns" && before==r){print old[$2];next}
                split(a[11],version,":");rev=version[1]+(before==r?0:1)}
            if($1=="dns"){if(!($2 in witness))exit 2;rev=rev ":" witness[$2]}
            print r,rev}' \
        "$1/decision/proofs.tsv" "$3/dns-witness" "$3/resources.after" > "$3/proofs.unsorted" || return 2
    LC_ALL=C sort "$3/proofs.unsorted" > "$3/proofs.after" || return 1
    for vrb_key in resources proofs choices; do
        if [ "$vrb_key" = choices ]; then
            awk -F'\t' 'BEGIN{OFS="\t"}FILENAME==ARGV[1]{if($1=="schema")header=$0;else rows[$2]=$0;next}
                $1=="step" && $4=="choice" {v=$7;gsub(/\|/,OFS,v);if(v=="-")delete rows[$5];else rows[$5]=v}
                END{print header;for(k in rows)print rows[k]}' "$1/decision/choices.tsv" "$2" | LC_ALL=C sort > "$3/choices.after" || return 1
        fi
        cmp -s "$1/decision/$vrb_key.tsv" "$3/$vrb_key.after" ||
            vrb_emit manifest "$vrb_key" "$1/decision/$vrb_key.tsv" "$3/$vrb_key.after" generation,identity,postimage || return 1
    done
    # The old services view remains a projection; DNS/ISP are not service-on.
    awk -F'\t' 'BEGIN{OFS="\t"}
        FILENAME==ARGV[1] || FILENAME==ARGV[2] {
            if($1!="route" || $9!="vward")next
            n=split($11,refs,",");g=$3;sub(/^group:/,"",g)
            for(i=1;i<=n;i++)if(refs[i]~/^S:/) {
                s=substr(refs[i],3)
                if(FILENAME==ARGV[1])prior[s SUBSEP g]=1
                else {v=s OFS g OFS substr($6,5);if(s in desired && desired[s]!=v)bad=1;desired[s]=v}
            }next
        }
        {if(($1 SUBSEP $2) in prior)next
            if($1 in desired) {if($0!=desired[$1])bad=1;next}
            keep[++nk]=$0}
        END{if(bad)exit 75;for(i=1;i<=nk;i++)print keep[i];for(s in desired)print desired[s]}' \
        "$3/resources.before" "$3/resources.after" "$1/enabled.tsv" > "$3/enabled.unsorted" || return 75
    LC_ALL=C sort "$3/enabled.unsorted" > "$3/enabled.after" || return 1
    cmp -s "$1/enabled.tsv" "$3/enabled.after" || vrb_emit registry enabled "$1/enabled.tsv" "$3/enabled.after" generation,identity,postimage || return 1
    vrj2_plan_valid "$3/plan" || return 2
    printf '%s\n' "$vrb_g" > "$3/generation"
)

# Pure prediction; also used by the DATA emulator. No transport or clock.
vrb_prefix_apply() (
    [ "$#" -eq 5 ] || return 2
    awk -v k="$2" -v g="$3" -v v="$4" -v a="$5" '
        {rows[$0]=1}
        END{
            if(k=="create"){delete rows["-"];rows["group=" g]=1}
            else if(k=="delete"){print "-";exit}
            else {r=(k=="include"?"include " v:"route=" v "\tauto");if(a=="add")rows[r]=1;else delete rows[r]}
            for(r in rows)print r
        }' "$1" | LC_ALL=C sort
)
