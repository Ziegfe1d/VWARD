#!/bin/sh
# OFF server lifecycle preparation; SAME stage, lowerer and parent executor as
# service choices. No CLI/API caller, HTTP or environment-selected transport.

vrb_append_manifest() (
    [ "$#" -eq 5 ] && vrj_dir "$1" && vrj2_file "$3" && vrj2_file "$4" || return 2
    case $2 in version|choices|bindings|context|resources|proofs|upstreams|policies|tombstones|saved|queue|evidence) ;; *) return 2 ;; esac
    cmp -s "$3" "$4" && return 0
    vrb_lm_n=$(awk -F'\t' '$1=="step"{n++}END{print n+1}' "$1/plan")
    cp "$3" "$1/pre.$vrb_lm_n" && cp "$4" "$1/post.$vrb_lm_n" || return 1
    vrb_lm_checks=$5,attrs:$(vr2_hash "$1/inputs.fp")
    if [ -e "$1/reader" ] || [ -L "$1/reader" ]; then vrj2_file "$1/reader" || return 2;vrb_lm_checks=$vrb_lm_checks,reader:$(vr2_hash "$1/reader");fi
    printf 'step\t%s\tmove\tmanifest\t%s\t%s\t%s\tcreation-and-cas\t-\tgeneration,identity,postimage%s\trestore-own-scope\n' \
        "$vrb_lm_n" "$2" "$(vr2_hash "$3")" "$(vr2_hash "$4")" "$vrb_lm_checks" >> "$1/plan" || return 1
    vrj2_plan_valid "$1/plan"
)

# Durable withdrawals are monotonic, including requests interrupted before
# their first backend write. Restoring an older local ledger must refuse BEFORE
# writing; it cannot silently revoke an owner's accepted server withdrawal.
vrb_revocations_gate() (
    [ "$#" -eq 2 ] && vrj_dir "$1" && vrj_dir "$2" || return 75
    for vrb_rg_file in "$1"/*/withdrawal; do
        [ ! -e "$vrb_rg_file" ] && [ ! -L "$vrb_rg_file" ] && continue
        vrj2_file "$vrb_rg_file" && vrj2_file "$vrb_rg_file.sha" || return 75
        vrb_rg_hash=$(vr2_hash "$vrb_rg_file") || return 75
        [ "$vrb_rg_hash" = "$(cat "$vrb_rg_file.sha")" ] || return 75
        vrb_rg_op=${vrb_rg_file%/withdrawal};vrb_rg_op=${vrb_rg_op##*/}
        vrj2_ready "$1" "$vrb_rg_op" || return 75
        awk -F'\t' -v h="$vrb_rg_hash" '$1=="step"&&$4=="manifest"&&$5=="tombstones" {
            n=split($10,a,",");for(i=1;i<=n;i++)if(a[i]=="revocations:" h)ok=1}END{exit ok?0:1}' "$1/$vrb_rg_op/plan" || return 75
        vrj2_file "$2/tombstones.tsv" || return 75
        awk -F'\t' 'FILENAME==ARGV[1]{if(NF!=3 || $2!~/^[0-9]+$/ || $3!="deleted" || seen[$1]++)bad=1;floor[$1]=$2;next}
            NF!=3 || $2!~/^[0-9]+$/ || $3!="deleted"{bad=1}
            !($1 in floor) || $2+0>floor[$1]+0{bad=1}END{exit bad?1:0}' "$2/tombstones.tsv" "$vrb_rg_file" || return 75
    done
)

# JDIR OP POLICY delete|replace NEW_LOCATION_KEY EXPECTED_POLICY_REV.
vward_routing_server2() (
    umask 077
    [ "$#" -eq 6 ] && vrj_id "$3" || return 2
    case $4 in delete) [ "$5" = - ] || return 2 ;; replace) vrj_id "$5" || return 2 ;; *) return 2 ;; esac
    case $6 in ''|*[!0-9]*) return 2 ;; esac
    vrb_pipeline_ready "$1" || return 75
    vrb_envelope "$1" "$2" || return 75
    : "${vrb_e:?}" "${vrb_j:?}" "${vrb_op:?}"
    vward_routing_state_gate 2 "$vrb_e/decision" && vward_journal2_gate "$vrb_j" || return 75
    vrb_ls=$(mktemp -d "$vrb_j/.server.XXXXXX") || return 1
    mkdir "$vrb_ls/stage" "$vrb_ls/lowered" "$vrb_ls/after" || return 1
    cp "$vrb_e/running.cfg" "$vrb_e/running-config" || return 1
    vward_routing_consistent_read2 "$vrb_ls/stage" "$vrb_e/decision" > "$vrb_ls/read.status" || return 3
    vr2_dns_view "$vrb_ls/stage" > "$vrb_ls/dns.tsv" || return 3
    vr2_dns_owned_authority "$vrb_ls/stage/decision/resources.tsv" "$vrb_ls/stage/decision/proofs.tsv" "$vrb_ls/dns.tsv" > "$vrb_ls/authority" || return 3
    awk -F'\t' '$2!="authorized"{bad=1}END{exit bad?1:0}' "$vrb_ls/authority" || return 75
    vr2_upstream_keys "$vrb_ls/stage/decision/upstreams.tsv" > "$vrb_ls/keys" || return 3
    awk -F'\t' 'NF!=7 || $2!~/^(keenetic|agh)$/ || $3!~/^(available|unavailable|unknown)$/ ||
        $4!~/^(active|inactive|unknown)$/ || $5!~/^(none|supported|unsupported)$/ || $6!~/^[0-9]+$/ || $6+0>2147483647 {bad=1}END{exit bad?1:0}' \
        "$vrb_ls/stage/decision/policies.tsv" || return 75
    vrb_selected=$(awk -F'\t' -v p="$3" '$1==p&&NF==7{print $6 "\t" $7;n++}END{if(n!=1)exit 2}' "$vrb_ls/stage/decision/policies.tsv") || return 75
    [ "$(printf '%s\n' "$vrb_selected" | cut -f1)" = "$6" ] || return 75
    vrb_oldkey=$(printf '%s\n' "$vrb_selected" | cut -f2)
    if [ "$4" = replace ] && [ "$5" = "$vrb_oldkey" ]; then
        printf 'outcome\tunchanged\tconfigured\tverified\tfalse\temulated\n';return 0
    fi
    vrb_new_native=-
    if [ "$4" = replace ]; then
        vrb_new_native=$(awk -F'\t' -v k="$5" '$1==k{print "upstream:" $2;n++}END{if(n!=1)exit 2}' "$vrb_ls/keys") || return 75
    fi
    awk -F'\t' -v key="$vrb_oldkey" 'BEGIN{OFS="\t"}$7==key {if($6!~/^[0-9]+$/ || $6+0>=2147483647)exit 2;print $1,$6}' \
        "$vrb_ls/stage/decision/policies.tsv" > "$vrb_ls/affected" || return 75
    awk -F'\t' -v action="$4" 'BEGIN{OFS="\t"}{print $1,$2+(action=="delete"?1:0),"deleted"}' "$vrb_ls/affected" > "$vrb_ls/withdrawal" || return 1
    # Related policies, saved images and deferred requests are one operation.
    # These unpublished state2 bookkeeping formats carry opaque IDs/digests,
    # never transport URLs or proof of a fresh probe.
    awk -F'\t' 'NF!=6 || $3!~/^[0-9]+$/ || $4!~/^g-[0-9a-f]+$/ || $5!~/^[0-9]+$/ || length($6)!=64 || $6!~/^[0-9a-f]+$/{bad=1}END{exit bad?1:0}' "$vrb_ls/stage/decision/saved.tsv" || return 75
    awk -F'\t' 'NF!=10 || $3!~/^[0-9]+$/ || $9!~/^[0-9]+$/ || $10!~/^g-[0-9a-f]+$/{bad=1}END{exit bad?1:0}' "$vrb_ls/stage/decision/queue.tsv" || return 75
    for vrb_key in saved queue; do
        awk -F'\t' 'FILENAME==ARGV[1]{affected[$1]=1;next}!($2 in affected)' "$vrb_ls/affected" "$vrb_ls/stage/decision/$vrb_key.tsv" > "$vrb_ls/after/$vrb_key" || return 1
    done
    awk -F'\t' -v action="$4" 'BEGIN{OFS="\t"}FILENAME==ARGV[1]{affected[$1]=1;next}
        $6 in affected {if(action=="delete" || $1=="A")$7=0;if($1=="A"){$8="history";$9=0}}{print}' \
        "$vrb_ls/affected" "$vrb_ls/stage/decision/evidence.tsv" > "$vrb_ls/after/evidence" || return 1
    awk -F'\t' -v action="$4" -v location="$5" 'BEGIN{OFS="\t"}FILENAME==ARGV[1]{affected[$1]=1;next}
        $1 in affected {$6=$6+1;if(action=="delete"){$3="unavailable";$4="inactive"}else $7=location}{print}' \
        "$vrb_ls/affected" "$vrb_ls/stage/decision/policies.tsv" > "$vrb_ls/after/policies" || return 1
    awk -F'\t' 'BEGIN{OFS="\t"}FILENAME==ARGV[1]{if(NF!=3 || $2!~/^[0-9]+$/ || $3!="deleted" || seen[$1]++)exit 2;rows[$1]=$0;rev[$1]=$2;next}
        !($1 in rev) || $2+0>rev[$1]+0 {rows[$1]=$0;rev[$1]=$2}END{for(k in rows)print rows[k]}' \
        "$vrb_ls/stage/decision/tombstones.tsv" "$vrb_ls/withdrawal" > "$vrb_ls/after/tombstones" || return 75
    printf 'routing-plan\t2\t%s\tdenied\n' "$(cat "$vrb_ls/stage/generation")" > "$vrb_ls/typed"
    awk -F'\t' -v action="$4" -v native="$vrb_new_native" 'BEGIN{OFS="\t"}
        function enc(s){gsub(/\t/,"|",s);return s}
        FILENAME==ARGV[1]{affected[$1]=1;next}
        $1=="dns" && $9=="vward" && ($7 in affected) {
            pre=$0;post="-";refs="-"
            if(action=="replace"){
                count=split($11,a,",");for(i=1;i<=count;i++)if(a[i]!~/^A:/)refs=(refs=="-"?a[i]:refs "," a[i])
                if(refs!="-"){$3=native;$11=refs;post=$0}
            }
            print "step",++n,(post=="-"?"remove":"move"),"dns",$2,enc(pre),enc(post),$10,refs,"generation,identity,postimage,save","restore-own-resource"
        }' "$vrb_ls/affected" "$vrb_ls/stage/decision/resources.tsv" >> "$vrb_ls/typed" || return 2
    if [ "$4" = delete ]; then
        cp "$vrb_ls/stage/decision/choices.tsv" "$vrb_ls/choices" || return 1
        awk -F'\t' 'FILENAME==ARGV[1]{affected[$1]=1;next}$1=="service"&&$4=="dns"&&($6 in affected){print $2 "\t" $3}' \
            "$vrb_ls/affected" "$vrb_ls/choices" > "$vrb_ls/services"
        while IFS="$(printf '\t')" read -r vrb_sid vrb_rev; do
            vward_routing_choice "$vrb_ls/choices" "$vrb_sid" auto - - "$vrb_rev" > "$vrb_ls/choices.next" || return 75
            vrb_n=$(awk -F'\t' '$1=="step"{n++}END{print n+1}' "$vrb_ls/typed")
            awk -F'\t' -v sid="$vrb_sid" -v n="$vrb_n" 'BEGIN{OFS="\t"}FILENAME==ARGV[1]{if($1=="service"&&$2==sid)pre=$0;next}
                $1=="service"&&$2==sid {post=$0;gsub(/\t/,"|",pre);gsub(/\t/,"|",post)
                    print "step",n,"move","choice",sid,pre,post,"revision-cas","S:" sid,"generation,identity,postimage","restore-own-choice"}' \
                "$vrb_ls/choices" "$vrb_ls/choices.next" >> "$vrb_ls/typed" || return 1
            mv "$vrb_ls/choices.next" "$vrb_ls/choices" || return 1
        done < "$vrb_ls/services"
    fi
    vward_routing_lower2 "$vrb_ls/stage" "$vrb_ls/typed" "$vrb_ls/lowered" || return 75
    vrb_compile_legacy_prune "$vrb_ls/stage" "$vrb_ls/lowered" "$4" "$vrb_oldkey" "$5" || return 75
    cp "$vrb_ls/withdrawal" "$vrb_ls/lowered/withdrawal" || return 1
    vrb_withdraw_hash=$(vr2_hash "$vrb_ls/withdrawal") || return 1
    for vrb_key in saved queue evidence policies tombstones; do
        vrb_extra=;[ "$vrb_key" != tombstones ] || vrb_extra=,revocations:$vrb_withdraw_hash
        vrb_append_manifest "$vrb_ls/lowered" "$vrb_key" "$vrb_ls/stage/decision/$vrb_key.tsv" "$vrb_ls/after/$vrb_key" "$vrb_extra" || return 75
    done
    vrb_outcome_bind "$vrb_ls/stage" "$vrb_ls/lowered" - || return 75
    vrb_result=0;vrb_execute2 "$vrb_ls/lowered" || vrb_result=$?
    vrb_outcome_stage=$vrb_ls/lowered/fresh
    [ -e "$vrb_outcome_stage/generation" ] || vrb_outcome_stage=$vrb_ls/stage
    vrb_outcome_emit "$vrb_outcome_stage" "$vrb_ls/lowered" || return 3
    if [ -d "$vrb_j/$vrb_op/prepared" ] && cmp -s "$vrb_ls/lowered/plan" "$vrb_j/$vrb_op/plan"; then
        cp "$vrb_ls/lowered/outcome.json" "$vrb_j/$vrb_op/prepared/outcome.json" &&
            cp "$vrb_ls/lowered/outcome.json.sha" "$vrb_j/$vrb_op/prepared/outcome.json.sha" || return 3
    fi
    return "$vrb_result"
)
