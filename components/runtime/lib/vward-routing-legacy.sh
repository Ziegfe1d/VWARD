#!/bin/sh
# OFF import of DEPLOYED legacy formats, distinct from normalized state1.
# Native files are observed/archived, never rewritten by this importer.

vrb_bootstrap_plan() (
    [ "$#" -eq 1 ] && vrj_dir "$1" && vrj2_file "$1/reader" && vrj2_file "$1/inputs.fp" && vrj2_plan_valid "$1/plan" || return 75
    [ "$(cat "$1/reader")" = legacy-observation ] || return 75
    vrb_bp_hash=$(vr2_hash "$1/reader") || return 75
    vrb_bp_attrs=$(vr2_hash "$1/inputs.fp") || return 75
    awk -F'\t' -v h="$vrb_bp_hash" -v attrs="$vrb_bp_attrs" 'NR==1{next}{
        if(!(($4=="manifest" && $5~/^(version|choices|bindings|context|resources|proofs|upstreams|policies|tombstones|saved|queue|evidence)$/) || ($4=="saved" && $5=="routing-state")))bad=1
        ok=0;attr_ok=0;n=split($10,a,",");for(i=1;i<=n;i++) {
            if(a[i]=="reader:" h)ok++
            else if(a[i]~/^reader:/)bad=1
            if(a[i]=="attrs:" attrs)attr_ok++
            else if(a[i]~/^attrs:/)bad=1
        }
        if(ok!=1 || attr_ok!=1)bad=1
    }END{exit bad?1:0}' "$1/plan"
)
vrb_legacy_empty() (
    vrj_dir "$1" || return 75
    [ ! -e "$1/.migration-pending" ] && [ ! -L "$1/.migration-pending" ] || return 75
    for vrb_le_file in "$1"/*; do
        [ ! -e "$vrb_le_file" ] && [ ! -L "$vrb_le_file" ] || return 75
    done
)
vrb_legacy_native_fp() {
    # Content, mode and owner matter; cache inode/mtime alone do not constitute
    # a changed accepted setting after reboot or an equivalent cache refresh.
    awk '$1!~/^(v2-|obs-probe:|obs-boot$)/ {if(NF==7)print $1,$2,$3,$6,$7;else print}' "$1" | LC_ALL=C sort
}
vrb_legacy_archive() (
    [ "$#" -eq 3 ] && vr2_stage_valid "$1" && vrj_dir "$2" && vrj_dir "$3" || return 2
    while read -r vrb_la_label vrb_la_hash vrb_la_size _vrb_inode _vrb_mtime vrb_la_mode vrb_la_uid; do
        case $vrb_la_label in
            cfg) vrb_la_src=$2/running.cfg ;;
            dev) vrb_la_src=$2/device.conf ;;
            map) vrb_la_src=$2/device-map.tsv ;;
            enabled) vrb_la_src=$2/services/enabled.tsv ;;
            categories) vrb_la_src=$2/services/categories.tsv ;;
            persist) vrb_la_src=$2/route/adaptive-persist.txt ;;
            catalog-fetched) vrb_la_src=$2/catalog.json ;;
            owned:*) vrb_la_src=$2/services/owned/${vrb_la_label#owned:} ;;
            list:*) vrb_la_src=$2/route-engine/domain-lists/${vrb_la_label#list:} ;;
            obs-dnsproof:*) vrb_la_src=$2/route-engine/domain-lists.dns/${vrb_la_label#obs-dnsproof:} ;;
            obs-smartdns-profile) vrb_la_src=$2/smartdns.conf ;;
            *) continue ;;
        esac
        [ "$vrb_la_hash" != absent ] || continue
        case $vrb_la_hash in *[!0-9a-f]*) return 75 ;; esac
        [ "${#vrb_la_hash}" -eq 64 ] && [ ! -L "$vrb_la_src" ] && [ -f "$vrb_la_src" ] || return 75
        vrb_data_ancestry "$vrb_la_src" || return 75
        cp -p "$vrb_la_src" "$3/$vrb_la_label" || return 1
        [ "$(vr2_hash "$3/$vrb_la_label")" = "$vrb_la_hash" ] && [ "$(wc -c < "$3/$vrb_la_label")" -eq "$vrb_la_size" ] || return 75
        # Numeric metadata only, never filename fields. stat -c is not portable
        # to Keenetic; archived files may be a legacy public registry0644.
        # shellcheck disable=SC2012
        [ "$(ls -ldn "$3/$vrb_la_label" | awk '{print substr($1,1,10),$3}')" = "$vrb_la_mode $vrb_la_uid" ] || return 75
    done < "$1/inputs.fp"
)
vrb_legacy_history() {
    awk -v target="$2" 'BEGIN{FS=OFS="\t";for(c=32;c<127;c++)ord[sprintf("%c",c)]=c;hex="0123456789abcdef"}
        function hex8(v,i,r){r="";for(i=0;i<8;i++){r=substr(hex,v%16+1,1) r;v=int(v/16)}return r}
        function id(d,i,a,b,c){a=5381;b=52711;for(i=1;i<=length(d);i++){c=ord[substr(d,i,1)];a=(a*131+c)%4294967291;b=(b*257+c+i)%4294967279}return "legacy-a-" hex8(a) hex8(b)}
        function domain(d,a,n,i){if(length(d)>253 || d!~/^[a-z0-9.-]+$/)return 0;n=split(d,a,".");if(n<2 || a[n]~/^[0-9]+$/)return 0
            for(i=1;i<=n;i++)if(length(a[i])>63 || a[i]!~/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/)return 0;return 1}
        {sub(/\r$/,"");if($0=="")next;if(NR>4096 || !domain($0)){bad=1;next}
            r=id($0);if(r in seen && seen[r]!=$0)bad=1;seen[r]=$0}
        END{if(bad)exit 2;for(r in seen)print "A",r,seen[r],"exact",target,"default",0,"history",0,"-"}' "$1"
}

vward_routing_legacy_migrate2() (
    umask 077
    [ "$#" -eq 2 ] || return 2
    vrb_envelope "$1" "$2" || return 75
    : "${vrb_e:?}" "${vrb_j:?}" "${vrb_op:?}"
    vrb_legacy_empty "$vrb_e/decision" && vward_journal2_gate "$vrb_j" || return 75
    if [ ! -e "$vrb_j/.migrations" ]; then mkdir "$vrb_j/.migrations" || return 1;fi
    vrj_dir "$vrb_j/.migrations" || return 75
    vrb_li=$vrb_j/.migrations/$vrb_op
    [ ! -e "$vrb_li" ] && [ ! -L "$vrb_li" ] || return 75
    mkdir "$vrb_li" "$vrb_li/stage" "$vrb_li/legacy" "$vrb_li/after" "$vrb_li/lowered" || return 1
    printf '%s\n' legacy0 > "$vrb_li/kind"
    cp "$vrb_e/running.cfg" "$vrb_e/running-config" || return 1
    vward_routing_bootstrap_read2 "$vrb_li/stage" "$vrb_e/decision" > "$vrb_li/read.status" || return 3
    vrb_legacy_archive "$vrb_li/stage" "$vrb_e" "$vrb_li/legacy" || return 75
    vrb_legacy_native_fp "$vrb_li/stage/inputs.fp" > "$vrb_li/native.before" || return 1
    for vrb_key in $(vrb_state_names); do : > "$vrb_li/after/$vrb_key" || return 1;done
    printf 'schema\t1\n' > "$vrb_li/after/choices"
    printf 'routing-state\t2\n' > "$vrb_li/after/version"
    # Existing accepted registration is an intent. Ownership still requires the
    # independent exact PRIVATE native proof. Names/catalog/persist are not it.
    awk -F'\t' 'BEGIN{OFS="\t"}FILENAME==ARGV[1]{if(NF!=3 || seen[$1]++ || ($2 in sid && sid[$2]!=$1)){bad=1;next}sid[$2]=$1;next}
        $1=="resource" && ($3 in sid) {
            if($6!~/^VPN:/ || ($3 in target && target[$3]!=$6))bad=1;target[$3]=$6
        }END{if(bad)exit 2;for(g in sid){if(!(g in target))exit 2;print sid[g],g,target[g]}}' \
        "$vrb_li/stage/enabled.tsv" "$vrb_li/stage/inventory.tsv" > "$vrb_li/registrations" || return 75
    while IFS="$(printf '\t')" read -r vrb_sid _vrb_group vrb_target; do
        vward_routing_choice "$vrb_li/after/choices" "$vrb_sid" vpn "$vrb_target" default 0 > "$vrb_li/choices.next" || return 75
        mv "$vrb_li/choices.next" "$vrb_li/after/choices" || return 1
    done < "$vrb_li/registrations"
    # jq variables are literal; an empty but valid catalog has zero records.
    # shellcheck disable=SC2016
    "${JQ:-jq}" -r 'if .schema==1 and (.services|type)=="array" then .services[] | .id as $s |
        .domains[] | select(type=="string") | [$s,ascii_downcase] | @tsv else error("catalog unknown") end' \
        "$vrb_li/legacy/catalog-fetched" > "$vrb_li/catalog.tsv" || return 75
    awk -F'\t' -v op="$vrb_op" 'BEGIN{OFS="\t"}
        FILENAME==ARGV[1]{sid[$2]=$1;next}
        $1=="resource"&&($3 in sid)&&$8=="vward"&&$10=="verified"&&$7=="default" {
            print "route",$13,"group:" $3,$4,"exact",$6,"default","native","vward","p-" op "-" $13,"S:" sid[$3]
        }' "$vrb_li/registrations" "$vrb_li/stage/inventory.tsv" | LC_ALL=C sort > "$vrb_li/after/resources" || return 1
    awk -F'\t' 'BEGIN{OFS="\t"}{for(i=1;i<=10;i++)printf "%s\t",$i;print 1}' "$vrb_li/after/resources" > "$vrb_li/after/proofs"
    awk -F'\t' 'BEGIN{OFS="\t"}FILENAME==ARGV[1]{catalog[$1 SUBSEP $2]=1;next}
        {s=$11;sub(/^S:/,"",s);known=((s SUBSEP $4) in catalog);print s,$4,"exact",(known?"confirmed":"unknown"),(known?"ipv4":"unknown"),(known?"known":"unknown")}' \
        "$vrb_li/catalog.tsv" "$vrb_li/after/resources" | LC_ALL=C sort -u > "$vrb_li/after/bindings"
    printf 'source:M\t1\nsource:S\t1\nsource:A\t1\n' > "$vrb_li/after/context"
    if awk '$1=="disabled"&&$2!="absent"{found=1}END{exit found?0:1}' "$vrb_li/stage/inputs.fp"; then
        printf 'source:M\t1\nsource:S\t1\nsource:A\t0\n' > "$vrb_li/after/context"
    fi
    # Profile existence is NOT a positive health probe.
    awk -F'\t' '$1=="health"&&$2~/^VPN:/{print $2 "\tunknown"}' "$vrb_li/stage/snapshot.tsv" >> "$vrb_li/after/context"
    vrb_target=$(awk -F= '$1=="VWARD_TUNNEL_INTERFACE"{print "VPN:" $2;n++}END{if(n!=1)exit 2}' "$vrb_li/legacy/dev") || return 75
    printf '%s\n' "$vrb_target" | grep -Eq '^VPN:[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$' || return 75
    if [ -f "$vrb_li/legacy/persist" ]; then
        vrb_legacy_history "$vrb_li/legacy/persist" "$vrb_target" > "$vrb_li/history" || return 75
        LC_ALL=C sort "$vrb_li/history" > "$vrb_li/after/evidence"
    fi
    # Old return images are archived opaque references, never restoration
    # authority. The digest points to the exact private legacy capture.
    while read -r vrb_label vrb_hash _vrb_rest; do
        case $vrb_label in list:*|obs-dnsproof:*) ;; *) continue ;; esac
        [ "$vrb_hash" != absent ] || continue
        case $vrb_hash in *[!0-9a-f]*) return 75 ;; esac
        vrb_saved_id=$(printf '%s' "$vrb_label" | sha256sum);vrb_saved_id=${vrb_saved_id%% *}
        printf 'legacy-%s\tlegacy-history\t0\t%s\t0\t%s\n' "${vrb_saved_id%????????????????}" "$(cat "$vrb_li/stage/generation")" "$vrb_hash" >> "$vrb_li/after/saved"
    done < "$vrb_li/stage/inputs.fp"
    # Version last. A crash keeps the parent barrier and observation0; neither
    # ordinary producer nor old journal treats a partial state as usable v2.
    vrb_compile_state_set "$vrb_li/stage" "$vrb_e/decision" "$vrb_li/after" "$vrb_li/lowered" '' || return 75
    vrb_execute2 "$vrb_li/lowered"
)

vward_routing_legacy_restore0() (
    umask 077
    [ "$#" -eq 3 ] && vrj2_id "$2" && vrj2_id "$3" || return 2
    vrb_envelope "$1" "$3" || return 75
    : "${vrb_e:?}" "${vrb_j:?}"
    vward_routing_state_gate 2 "$vrb_e/decision" && vward_journal2_gate "$vrb_j" || return 75
    vrb_lr_source=$vrb_j/$2
    vrj2_ready "$vrb_j" "$2" && [ "$(cat "$vrb_lr_source/state")" = committed ] || return 75
    vrb_lr=$vrb_j/.migrations/$2
    vrj_dir "$vrb_lr" && [ "$(cat "$vrb_lr/kind")" = legacy0 ] && vrb_bootstrap_plan "$vrb_lr_source/prepared" || return 75
    vrb_lr_work=$(mktemp -d "$vrb_j/.downgrade.XXXXXX") || return 1
    mkdir "$vrb_lr_work/stage" "$vrb_lr_work/lowered" "$vrb_lr_work/empty" || return 1
    vrb_revocations_gate "$vrb_j" "$vrb_lr_work/empty" || return 75
    cp "$vrb_e/running.cfg" "$vrb_e/running-config" || return 1
    vward_routing_bootstrap_read2 "$vrb_lr_work/stage" "$vrb_e/decision" > "$vrb_lr_work/read.status" || return 3
    vrb_legacy_native_fp "$vrb_lr_work/stage/inputs.fp" > "$vrb_lr_work/native.now"
    vrb_legacy_native_fp "$vrb_lr_source/prepared/inputs.fp" > "$vrb_lr_work/native.before" || return 75
    cmp -s "$vrb_lr_work/native.now" "$vrb_lr_work/native.before" || return 75
    # Inspect ALL current postimages and authority before removing one file.
    vrb_state_step_valid "$vrb_lr_source/prepared" "$vrb_lr_source" 1 || return 75
    vrb_state_image "$vrb_e/decision" "$vrb_lr_work/current" &&
        cmp -s "$vrb_lr_work/current" "$vrb_lr_source/prepared/state/post" || return 75
    vrb_compile_state_set "$vrb_lr_work/stage" "$vrb_e/decision" "$vrb_lr_work/empty" "$vrb_lr_work/lowered" '' || return 75
    vrb_execute2 "$vrb_lr_work/lowered"
)

# Opaque plan ID -> one CLOSED legacy bookkeeping path. The binding is sealed
# in the immutable plan; names/saved bytes grant no native/DNS ownership.
vrb_legacy_scope() (
    : "${vrb_t:?}" "${vrb_e:?}"
    case $1 in raw[1-9]*) ;; *) return 75 ;; esac
    vrb_rs_n=${1#raw};vrj2_seq "$vrb_rs_n" || return 75
    vrj2_file "$vrb_t/raw.$1" && vrj2_plan_valid "$vrb_t/plan" || return 75
    vrb_rs_hash=$(vr2_hash "$vrb_t/raw.$1") || return 75
    awk -F'\t' -v id="$1" -v h="$vrb_rs_hash" '$1=="step" && $4=="saved" && $5==id {
        n=split($10,a,",");for(i=1;i<=n;i++)if(a[i]=="raw-scope:" h)ok++}END{exit ok==1?0:1}' "$vrb_t/plan" || return 75
    vrb_rs_label=$(cat "$vrb_t/raw.$1") || return 75
    case $vrb_rs_label in
        list:*|obs-dnsproof:*)
            vrb_rs_group=${vrb_rs_label#*:}
            printf '%s\n' "$vrb_rs_group" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$' || return 75
            [ "$vrb_rs_group" != AdaptiveAuto ] || return 75
            case $vrb_rs_label in list:*) vrb_rs_path=$vrb_e/route-engine/domain-lists/$vrb_rs_group ;;
                *) vrb_rs_path=$vrb_e/route-engine/domain-lists.dns/$vrb_rs_group ;; esac ;;
        obs-smartdns-profile) vrb_rs_path=$vrb_e/smartdns.conf ;;
        *) return 75 ;;
    esac
    vrb_data_ancestry "$vrb_rs_path" || return 75
    case $2 in path) printf '%s\n' "$vrb_rs_path" ;; label) printf '%s\n' "$vrb_rs_label" ;; *) return 2 ;; esac
)
vrb_predict_legacy_prune() (
    [ "$#" -eq 1 ] && vrj_dir "$1" || return 2
    export LISTS_STATE="$1/model/domain-lists" SMARTDNS_CONF="$1/selector.conf"
    JOURNAL=$1/model/journal;export BACKUP_DIR="$1/model/backup" BACKUP_KEEP=20 ADAPTIVE_GROUP=AdaptiveAuto
    : > "$JOURNAL" || return 1
    # Only a fixed DATA failure reporter is substituted. Matching/filtering,
    # backup and file installation use the existing console implementation.
    # shellcheck disable=SC2317
    die() { exit 75; }
    smartdns_prune_saved server
)
# STAGE LOWERED delete|replace OLD_LOCATION_KEY NEW_LOCATION_KEY. Private URLs
# are read from the sealed table into private files, never into a plan/log.
vrb_compile_legacy_prune() (
    [ "$#" -eq 5 ] && vr2_stage_valid "$1" && vrj_dir "$2" || return 2
    vrb_lp=$2/legacy
    mkdir "$vrb_lp" "$vrb_lp/before" "$vrb_lp/model" "$vrb_lp/model/domain-lists" "$vrb_lp/model/domain-lists.dns" || return 1
    awk -F'\t' -v key="$4" '$1==key{print "SMARTDNS_URL=" $2;n++}END{if(n!=1)exit 2}' "$1/decision/upstreams.tsv" > "$vrb_lp/selector.conf" || return 75
    vr2_upstream_keys "$1/decision/upstreams.tsv" > "$vrb_lp/keys" || return 75
    vrb_lp_native=$(awk -F'\t' -v k="$4" '$1==k{print "upstream:" $2}' "$vrb_lp/keys")
    vr2_dns_view "$1" > "$vrb_lp/dns" || return 75
    # Every ACTUAL binding of the withdrawn endpoint must already have exact
    # common ownership. A legacy proof/reference alone cannot grant deletion.
    awk -F'\t' -v native="$vrb_lp_native" -v key="$4" '
        FILENAME==ARGV[1]{if($7==key)affected[$1]=1;next}
        FILENAME==ARGV[2]{if($1=="dns" && $3==native && $9=="vward" && ($7 in affected))own[$4 SUBSEP $5 SUBSEP $8]=1;next}
        $1=="dns" && $3==native && !(($4 SUBSEP $5 SUBSEP $8) in own){bad=1}END{exit bad?1:0}' \
        "$1/decision/policies.tsv" "$1/decision/resources.tsv" "$vrb_lp/dns" || return 75
    vrb_lp_bytes=0
    while read -r vrb_lp_label vrb_lp_hash _vrb_size _vrb_inode _vrb_time vrb_lp_mode vrb_lp_uid; do
        case $vrb_lp_label in
            list:*|obs-dnsproof:*)
                vrb_lp_group=${vrb_lp_label#*:}
                printf '%s\n' "$vrb_lp_group" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$' || return 75
                [ "$vrb_lp_group" != AdaptiveAuto ] || return 75
                case $vrb_lp_label in list:*) vrb_lp_source=$vrb_e/route-engine/domain-lists/$vrb_lp_group;vrb_lp_model=$vrb_lp/model/domain-lists/$vrb_lp_group ;;
                    *) vrb_lp_source=$vrb_e/route-engine/domain-lists.dns/$vrb_lp_group;vrb_lp_model=$vrb_lp/model/domain-lists.dns/$vrb_lp_group ;; esac ;;
            obs-smartdns-profile) vrb_lp_source=$vrb_e/smartdns.conf;vrb_lp_model=$vrb_lp/model/profile ;;
            *) continue ;;
        esac
        [ "$vrb_lp_hash" != absent ] || continue
        vrb_data_ancestry "$vrb_lp_source" || return 75
        vrb_owned_data_file "$vrb_lp_source" && vrb_single_link "$vrb_lp_source" || return 75
        [ "$(vr2_hash "$vrb_lp_source")" = "$vrb_lp_hash" ] || return 75
        # Metadata, not filename parsing.
        # shellcheck disable=SC2012
        [ "$(ls -ldn "$vrb_lp_source" | awk '{print substr($1,1,10),$3}')" = "$vrb_lp_mode $vrb_lp_uid" ] || return 75
        vrb_lp_bytes=$((vrb_lp_bytes+$(wc -c < "$vrb_lp_source")));[ "$vrb_lp_bytes" -le 1048576 ] || return 75
        cp -p "$vrb_lp_source" "$vrb_lp/before/$vrb_lp_label" && cp -p "$vrb_lp_source" "$vrb_lp_model" || return 1
        [ "$(vr2_hash "$vrb_lp_model")" = "$vrb_lp_hash" ] && [ "$(vr2_hash "$vrb_lp/before/$vrb_lp_label")" = "$vrb_lp_hash" ] || return 75
    done < "$1/inputs.fp"
    vrb_predict_legacy_prune "$vrb_lp" || return 75
    if [ -f "$vrb_lp/model/profile" ]; then
        # Only the exact currently selected endpoint is changed. A manually
        # removed/other profile is not restored, nor is its store preference.
        awk -F= -v action="$3" -v key="$5" '
            FILENAME==ARGV[1]{if($1=="SMARTDNS_URL")old=substr($0,index($0,"=")+1);next}
            FILENAME==ARGV[2]{split($0,a,"\t");if(a[1]==key)new=substr($0,index($0,"\t")+1);next}
            $1=="SMARTDNS_URL" && substr($0,index($0,"=")+1)==old {if(action=="replace")print "SMARTDNS_URL=" new;next}{print}' \
            "$vrb_lp/selector.conf" "$1/decision/upstreams.tsv" "$vrb_lp/model/profile" > "$vrb_lp/model/profile.next" || return 1
        mv "$vrb_lp/model/profile.next" "$vrb_lp/model/profile" || return 1
    fi
    for vrb_lp_before in "$vrb_lp/before"/*; do
        [ -f "$vrb_lp_before" ] || continue
        vrb_lp_label=${vrb_lp_before##*/}
        case $vrb_lp_label in list:*) vrb_lp_after=$vrb_lp/model/domain-lists/${vrb_lp_label#*:} ;;
            obs-dnsproof:*) vrb_lp_after=$vrb_lp/model/domain-lists.dns/${vrb_lp_label#*:} ;;
            obs-smartdns-profile) vrb_lp_after=$vrb_lp/model/profile ;; *) return 75 ;; esac
        cmp -s "$vrb_lp_before" "$vrb_lp_after" && continue
        vrb_lp_n=$(awk -F'\t' '$1=="step"{n++}END{print n+1}' "$2/plan")
        vrb_lp_id=raw$vrb_lp_n
        printf '%s\n' "$vrb_lp_label" > "$2/raw.$vrb_lp_id" || return 1
        cp "$vrb_lp_before" "$2/pre.$vrb_lp_n" && cp "$vrb_lp_after" "$2/post.$vrb_lp_n" || return 1
        printf 'step\t%s\tmove\tsaved\t%s\t%s\t%s\tcreation-and-cas\t-\tgeneration,identity,postimage,attrs:%s,raw-scope:%s\trestore-own-scope\n' \
            "$vrb_lp_n" "$vrb_lp_id" "$(vr2_hash "$2/pre.$vrb_lp_n")" "$(vr2_hash "$2/post.$vrb_lp_n")" \
            "$(vr2_hash "$2/inputs.fp")" "$(vr2_hash "$2/raw.$vrb_lp_id")" >> "$2/plan" || return 1
    done
    vrj2_plan_valid "$2/plan"
)

# Prepared read-only bridge for OLD writers/updater. It is not installed or
# called by a production dispatcher. One journal remains the source of the
# persistent unknown barrier after every originating PID has exited.
vward_routing_update_eligibility2() (
    [ "$#" -eq 1 ] && vrj_dir "$1" && vward_journal2_gate "$1" || return 75
    for vrb_ue_op in "$1"/*; do
        [ ! -e "$vrb_ue_op" ] && [ ! -L "$vrb_ue_op" ] && continue
        vrj_dir "$vrb_ue_op" && vrb_publish_quiet "$vrb_ue_op" || return 75
        for vrb_ue_pending in "$vrb_ue_op"/dns-evidence/*/request.pending "$vrb_ue_op"/dns-inverse.*/evidence/request.pending; do
            [ ! -e "$vrb_ue_pending" ] && [ ! -L "$vrb_ue_pending" ] || return 75
        done
    done
)
# STAGE JDIR group|domain|auto|policy SELECTOR. "legacy-unmanaged" is only
# absence of a B claim: existing legacy ownership/admission still applies. It
# never grants a B capability. Protected candidates must use common policy.
vward_routing_legacy_eligibility2() (
    [ "$#" -eq 4 ] && vr2_stage_valid "$1" &&
        [ "$(cat "$1/decision/version.tsv")" = "$(printf 'routing-state\t2')" ] || return 75
    vward_routing_update_eligibility2 "$2" || return 75
    case $3 in domain|group|auto|policy) ;; *) return 2 ;; esac
    case $4 in ''|*[!A-Za-z0-9_.:@-]*) return 2 ;; esac
    [ "${#4}" -le 253 ] || return 2
    # Auto's old persist/return/queue is never a fresh proof. Even a new probe
    # is merely an input to the common policy, never a direct legacy writer.
    if [ "$3" = auto ]; then printf 'legacy\thandoff\tcommon-policy-required\n';return 75;fi
    awk -F'\t' -v kind="$3" -v query="$4" '
        function covers(p,d,s){return p==d || (s=="subtree" && length(d)>length(p) && substr(d,length(d)-length(p))=="." p)}
        function protected(d, i,s,result){
            for(i=1;i<=nr;i++)if(covers(rd[i],d,rs[i]))return 1
            for(s in mode)if(mode[s]!="auto" && ctx["source:S"]!="0") {
                result="none"
                for(i=1;i<=nb;i++)if(bs[i]==s && covers(bd[i],d,bsc[i])) {
                    if(ba[i]=="excluded"){result="excluded";break}
                    result=(ba[i]=="confirmed" && bf[i]!="unknown" && bc[i]=="known")?"confirmed":"unknown"
                }
                if(result=="unknown")bad=1
                if(result=="confirmed")return 1
            }
            return 0
        }
        FILENAME==ARGV[1]{if(NF!=2 || ($1 in ctx))bad=1;ctx[$1]=$2;next}
        FILENAME==ARGV[2]{if(FNR==1){if(NF!=2 || $1!="schema" || $2!=1)bad=1;next}
            if(NF!=7 || $1!="service" || $4!~/^(auto|vpn|dns|isp)$/ || $3!~/^[0-9]+$/ || $7!~/^[0-9]+$/ || ($2 in mode))bad=1;mode[$2]=$4;next}
        FILENAME==ARGV[3]{if(NF!=6 || $3!~/^(exact|subtree)$/ || $4!~/^(confirmed|excluded|shared|unknown)$/)bad=1
            bs[++nb]=$1;bd[nb]=$2;bsc[nb]=$3;ba[nb]=$4;bf[nb]=$5;bc[nb]=$6;next}
        FILENAME==ARGV[4]{if(NF!=11 || $1!~/^(route|dns)$/ || $5!~/^(exact|subtree)$/)bad=1
            if($9=="vward"){rd[++nr]=$4;rs[nr]=$5;if($3=="group:" query && kind=="group")hold=1}next}
        FILENAME==ARGV[5]{if(NF!=3 || $3!="deleted")bad=1;if(kind=="policy" && $1==query)hold=1;next}
        /^object-group fqdn / {inside=($3==query);next} /^!/ {inside=0}
        inside && $1=="include" && NF==2 {group_domain[$2]=1}
        END{
            if(kind=="domain" && protected(query))hold=1
            if(kind=="group")for(d in group_domain)if(protected(d))hold=1
            if(bad){print "legacy\tunknown\tincomplete-scope";exit 75}
            if(hold){print "legacy\thandoff\tcommon-policy-required";exit 75}
            print "legacy\tlegacy-unmanaged\texisting-guards-required"
        }' "$1/decision/context.tsv" "$1/decision/choices.tsv" "$1/decision/bindings.tsv" \
        "$1/decision/resources.tsv" "$1/decision/tombstones.tsv" "$1/native.cfg"
)
# Actual OFF reconcile path for a legacy request whose service is KNOWN. It
# retains the accepted owner choice and delegates to the SAME full pipeline;
# it never restores a raw return image or silently changes a pin to Auto.
vward_routing_legacy_reconcile2() (
    [ "$#" -eq 3 ] && vrb_pipeline_ready "$1" && vrj2_id "$2" || return 75
    vrb_lr_choice=$1/.emu/decision/choices.tsv
    vrj2_file "$vrb_lr_choice" || return 75
    vrb_lr_current=$(awk -F'\t' -v s="$3" '$1=="service"&&$2==s {if(NF!=7)exit 2;print $4 "\t" $5 "\t" $6 "\t" $3;n++}END{if(n!=1)exit 2}' "$vrb_lr_choice") || return 75
    vrb_lr_mode=$(printf '%s\n' "$vrb_lr_current" | cut -f1)
    vrb_lr_target=$(printf '%s\n' "$vrb_lr_current" | cut -f2)
    vrb_lr_dns=$(printf '%s\n' "$vrb_lr_current" | cut -f3)
    vrb_lr_rev=$(printf '%s\n' "$vrb_lr_current" | cut -f4)
    vward_routing_pipeline2 "$1" "$2" "$3" "$vrb_lr_mode" "$vrb_lr_target" "$vrb_lr_dns" "$vrb_lr_rev"
)
