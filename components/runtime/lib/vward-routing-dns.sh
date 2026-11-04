#!/bin/sh
# OFF DNS rehearsal helpers. Defines functions only. API traffic is represented
# by a private JSON DATA file; no HTTP client or environment-selected executor.

vrb_dns_uri() (
    [ "$#" -eq 2 ] && vr2_stage_valid "$1" || return 2
    vrb_du_tmp=$(mktemp -d "$1/.uri.XXXXXX") || return 1
    trap 'rm -rf "$vrb_du_tmp"' EXIT
    vr2_upstream_keys "$1/decision/upstreams.tsv" > "$vrb_du_tmp/keys" || return 2
    awk -F'\t' -v n="${2#upstream:}" '
        FILENAME==ARGV[1]{if($2==n)key=$1;next}
        $1==key{print $2;found++}END{exit found==1?0:2}' \
        "$vrb_du_tmp/keys" "$1/decision/upstreams.tsv"
)
vrb_keenetic_scope() (
    [ "$#" -eq 2 ] && vr2_file "$1" || return 2
    awk -v uri="$2" '{sub(/\r$/,"")}
        /^dns-proxy$/ {dns=1;next} /^[^ \t]/ {dns=0}
        dns && $1=="https" && $2=="upstream" && $3==uri {$1=$1;print}' "$1" | LC_ALL=C sort
)
vrb_agh_scope() {
    "${JQ:-jq}" -ceS 'if (.upstream_dns | type)=="array" and all(.upstream_dns[];type=="string")
        then {upstream_dns: .upstream_dns} else error("unknown") end' "$1"
}

vrb_https_scope() {
    awk '{sub(/\r$/,"")} /^dns-proxy$/ {dns=1;next} /^[^ \t]/ {dns=0}
        dns && $1=="https" && $2=="upstream" {$1=$1;print}' "$1" | LC_ALL=C sort
}
vrb_dns_bundle() (
    # Closed compile directory; execution evidence is deliberately elsewhere.
    cd "$1" || return 2
    for vrb_db_file in before after count commands params.* mode.* prefix.*; do
        [ ! -e "$vrb_db_file" ] && [ ! -L "$vrb_db_file" ] && continue
        vrj2_file "$vrb_db_file" || return 2
        printf '%s\t%s\n' "$vrb_db_file" "$(vr2_hash "$vrb_db_file")"
    done | sha256sum | awk '{print $1}'
)

# The caller supplies the existing vrb_emit closure. One physical DNS scope per
# backend, with immutable private parameters and every possible own prefix.
vrb_dns_compile() {
    vrb_dc_stage=$1;vrb_dc_out=$2
    : > "$2/dns-witness" || return 1
    vr2_dns_view "$1" > "$2/dns-observed" || return 2
    awk -F'\t' '
        function key(){return $3 SUBSEP $4 SUBSEP $5 SUBSEP $8}
        FILENAME==ARGV[1]{if($1=="dns" && $9=="vward")own[key()]=1;next}
        FILENAME==ARGV[2]{if($1=="dns")observed[key()]=1;next}
        $1=="dns" && $9=="vward" && !(key() in own) && (key() in observed){bad=1}
        END{exit bad?1:0}' "$2/resources.before" "$2/dns-observed" "$2/resources.after" || return 75
    for vrb_dc_backend in keenetic agh; do
        mkdir "$2/dns-$vrb_dc_backend" || return 1
        vrb_dc_dir=$2/dns-$vrb_dc_backend
        for vrb_dc_side in before after; do
            awk -F'\t' -v backend="$vrb_dc_backend" 'BEGIN{OFS="\t"}
                $1=="dns" && $8==backend && $9=="vward" {for(i=1;i<=10;i++)printf "%s%s",$i,(i==10?ORS:OFS)}' \
                "$vrb_dc_out/resources.$vrb_dc_side" | LC_ALL=C sort > "$vrb_dc_dir/physical.$vrb_dc_side" || return 1
        done
        # No physical delta: do not consult that backend, resolve its endpoint
        # or recreate its ownership evidence. Claims-only updates stay local.
        cmp -s "$vrb_dc_dir/physical.before" "$vrb_dc_dir/physical.after" && continue
        : > "$vrb_dc_dir/take";: > "$vrb_dc_dir/put"
        for vrb_dc_side in before after; do
            : > "$vrb_dc_dir/owned.$vrb_dc_side"
            while IFS="$(printf '\t')" read -r vrb_dc_kind vrb_dc_rid vrb_dc_native vrb_dc_domain _vrb_scope _vrb_target _vrb_policy vrb_dc_store vrb_dc_owner _vrb_birth _vrb_consumers; do
                [ "$vrb_dc_kind:$vrb_dc_store:$vrb_dc_owner" = "dns:$vrb_dc_backend:vward" ] || continue
                vrb_dc_uri=$(vrb_dns_uri "$vrb_dc_stage" "$vrb_dc_native") || return 75
                if [ "$vrb_dc_backend" = keenetic ]; then
                    # Keep the exact witnessed options of a retained row.
                    vrb_dc_line=$(awk -v u="$vrb_dc_uri" -v d="$vrb_dc_domain" '
                        /^dns-proxy$/ {dns=1;next} /^[^ \t]/ {dns=0}
                        dns && $1=="https" && $3==u && $(NF-1)=="domain" && $NF==d {$1=$1;print}' "$vrb_dc_stage/native.cfg")
                    [ -n "$vrb_dc_line" ] || vrb_dc_line="https upstream $vrb_dc_uri dnsm domain $vrb_dc_domain"
                    printf '%s\n' "$vrb_dc_line" >> "$vrb_dc_dir/owned.$vrb_dc_side" || return 1
                    vrb_dc_sha=$(printf '%s\n' "$vrb_dc_line" | sha256sum);vrb_dc_sha=${vrb_dc_sha%% *}
                else
                    printf '%s\t%s\n' "$vrb_dc_domain" "$vrb_dc_uri" >> "$vrb_dc_dir/owned.$vrb_dc_side" || return 1
                    vrb_dc_sha=${vrb_dc_native#upstream:uh-}
                fi
                if [ "$vrb_dc_side" = after ]; then
                    printf '%s\t%s\n' "$vrb_dc_rid" "${vrb_dc_sha%????????????????}" > "$vrb_dc_dir/witness.tmp"
                    # AGH's witness is already a 48-hex physical URI hash.
                    if [ "$vrb_dc_backend" = agh ]; then printf '%s\t%s\n' "$vrb_dc_rid" "$vrb_dc_sha" > "$vrb_dc_dir/witness.tmp";fi
                    cat "$vrb_dc_dir/witness.tmp" >> "$vrb_dc_out/dns-witness" || return 1
                fi
            done < "$vrb_dc_out/resources.$vrb_dc_side"
        done
        LC_ALL=C sort -u "$vrb_dc_dir/owned.before" > "$vrb_dc_dir/old"
        LC_ALL=C sort -u "$vrb_dc_dir/owned.after" > "$vrb_dc_dir/new"
        awk 'FILENAME==ARGV[1]{seen[$0]=1;next}!($0 in seen)' "$vrb_dc_dir/new" "$vrb_dc_dir/old" > "$vrb_dc_dir/take"
        awk 'FILENAME==ARGV[1]{seen[$0]=1;next}!($0 in seen)' "$vrb_dc_dir/old" "$vrb_dc_dir/new" > "$vrb_dc_dir/put"
        [ -s "$vrb_dc_dir/take" ] || [ -s "$vrb_dc_dir/put" ] || continue
        if [ "$vrb_dc_backend" = agh ]; then
            mkdir "$vrb_dc_dir/predict" || return 1
            vrb_agh_predict "$vrb_dc_stage" "$vrb_dc_dir/take" "$vrb_dc_dir/put" "$vrb_dc_dir/predict" || return 75
            for vrb_dc_file in before after count; do cp "$vrb_dc_dir/predict/$vrb_dc_file" "$vrb_dc_dir/$vrb_dc_file" || return 1;done
            for vrb_dc_file in "$vrb_dc_dir/predict"/params.* "$vrb_dc_dir/predict"/mode.* "$vrb_dc_dir/predict"/prefix.*; do
                [ ! -f "$vrb_dc_file" ] || cp "$vrb_dc_file" "$vrb_dc_dir/" || return 1
            done
        else
            vrb_https_scope "$vrb_dc_stage/native.cfg" > "$vrb_dc_dir/before" || return 2
            # URL-wide withdrawal is allowed only when every temporarily removed
            # row has an exact own witness. Foreign shared/global rows HOLD.
            awk '{print $3}' "$vrb_dc_dir/take" | LC_ALL=C sort -u > "$vrb_dc_dir/urls"
            cat "$vrb_dc_dir/take" "$vrb_dc_dir/put" | awk '{print $3}' | LC_ALL=C sort -u > "$vrb_dc_dir/urls.affected"
            awk 'FILENAME==ARGV[1]{own[$0]=1;next}FILENAME==ARGV[2]{urls[$0]=1;next}
                $3 in urls && !($0 in own){bad=1}END{exit bad?1:0}' \
                "$vrb_dc_dir/old" "$vrb_dc_dir/urls.affected" "$vrb_dc_dir/before" || return 75
            awk -F'\t' 'BEGIN{OFS="\t"}
                function physical(){v=$1;for(i=2;i<=10;i++)v=v OFS $i;return v}
                FILENAME==ARGV[1]{if($1=="dns"&&$8=="keenetic"&&$9=="vward"){old[$2]=physical();native[$2]=$3}next}
                $1=="dns"&&$8=="keenetic"&&$9=="vward"{after[$2]=1;if(old[$2]!=physical()){print $3;if($2 in native)print native[$2]}}
                END{for(r in native)if(!(r in after))print native[r]}' "$vrb_dc_out/resources.before" "$vrb_dc_out/resources.after" > "$vrb_dc_dir/natives.affected"
            vr2_dns_owned_authority "$vrb_dc_out/resources.before" "$vrb_dc_stage/decision/proofs.tsv" "$vrb_dc_out/dns-observed" > "$vrb_dc_dir/authority" || return 2
            awk -F'\t' 'FILENAME==ARGV[1]{affected[$1]=1;next}FILENAME==ARGV[2]{auth[$1]=$2;next}
                $1=="dns"&&$8=="keenetic"&&$9=="vward"&&($3 in affected)&&auth[$2]!="authorized"{bad=1}END{exit bad?1:0}' \
                "$vrb_dc_dir/natives.affected" "$vrb_dc_dir/authority" "$vrb_dc_out/resources.before" || return 75
            awk 'FILENAME==ARGV[1]{take[$0]=1;next}!($0 in take){print}' "$vrb_dc_dir/take" "$vrb_dc_dir/before" > "$vrb_dc_dir/retained"
            cat "$vrb_dc_dir/retained" "$vrb_dc_dir/put" | LC_ALL=C sort -u > "$vrb_dc_dir/after" || return 1
            [ "$(wc -l < "$vrb_dc_dir/after")" -le 8 ] || return 75
            : > "$vrb_dc_dir/commands";cp "$vrb_dc_dir/before" "$vrb_dc_dir/prefix"
            vrb_dc_count=0
            while IFS= read -r vrb_dc_uri; do
                printf 'remove\t%s\n' "$vrb_dc_uri" >> "$vrb_dc_dir/commands"
                awk -v u="$vrb_dc_uri" '$3!=u' "$vrb_dc_dir/prefix" > "$vrb_dc_dir/prefix.next"
                vrb_dc_count=$((vrb_dc_count+1))
                mv "$vrb_dc_dir/prefix.next" "$vrb_dc_dir/prefix"
                cp "$vrb_dc_dir/prefix" "$vrb_dc_dir/prefix.$vrb_dc_count"
            done < "$vrb_dc_dir/urls"
            awk 'FILENAME==ARGV[1]{seen[$0]=1;next}!($0 in seen){print}' "$vrb_dc_dir/prefix" "$vrb_dc_dir/after" > "$vrb_dc_dir/adds"
            while IFS= read -r vrb_dc_line; do
                printf 'add\t%s\n' "$vrb_dc_line" >> "$vrb_dc_dir/commands"
                { cat "$vrb_dc_dir/prefix";printf '%s\n' "$vrb_dc_line"; } | LC_ALL=C sort > "$vrb_dc_dir/prefix.next"
                vrb_dc_count=$((vrb_dc_count+1))
                mv "$vrb_dc_dir/prefix.next" "$vrb_dc_dir/prefix"
                cp "$vrb_dc_dir/prefix" "$vrb_dc_dir/prefix.$vrb_dc_count"
            done < "$vrb_dc_dir/adds"
            cmp -s "$vrb_dc_dir/prefix" "$vrb_dc_dir/after" || return 2
            printf '%s\n' "$vrb_dc_count" > "$vrb_dc_dir/count"
        fi
        vrb_dc_checks=generation,identity,postimage
        vrb_dc_i=1
        while [ "$vrb_dc_i" -le "$(cat "$vrb_dc_dir/count")" ]; do
            vrb_dc_checks=$vrb_dc_checks,prefix:$(vr2_hash "$vrb_dc_dir/prefix.$vrb_dc_i")
            vrb_dc_i=$((vrb_dc_i+1))
        done
        vrb_dc_checks=$vrb_dc_checks,commands:$(vrb_dns_bundle "$vrb_dc_dir")
        vrb_emit dns-scope "$vrb_dc_backend" "$vrb_dc_dir/before" "$vrb_dc_dir/after" "$vrb_dc_checks" || return 1
    done
}

# Run the ACTUAL existing AGH internal worker against a DATA model. The caller
# chooses a cloned model for prediction and the emulator model for execution;
# there is no path to an HTTP transport. Every invocation still takes the real
# component lock. Fault files affect only this test DATA transport.
vrb_agh_model_session() (
    umask 077
    [ "$#" -eq 7 ] && vrj2_file "$1" && vrj2_file "$3" && vrj_dir "$5" || return 2
    command -v ads_smartdns_locked >/dev/null 2>&1 || return 75
    case $2 in smartdns-put|smartdns-take-pairs|guarded-back) ;; *) return 2 ;; esac
    vrb_am_model=$1;AG_SET=$2;A1=$3;A2=$4;vrb_am_work=$5;vrb_am_evidence=$6;vrb_am_faults=$7
    vrj_dir "$vrb_am_evidence" || return 2
    W=$vrb_am_work;ADS_JQ=$(command -v "${JQ:-jq}") || return 2
    CONTROL_LOCK=${VWARD_ROOT_PREFIX:?}/tmp/vward-ads-control.lock
    CL_HELD=0
    ads_lock_acquire "$CONTROL_LOCK" 30 || return 75
    CL_HELD=1
    export AG_SET A1 A2 CL_HELD
    trap 'ads_lock_release "$CONTROL_LOCK"' EXIT
    VWARD_AGH_RECOVERY_DIR=$vrb_am_evidence
    export VWARD_AGH_RECOVERY_DIR
    # These fixed DATA adapters are invoked by the imported component worker.
    # shellcheck disable=SC2317
    ads_log() { :; }
    # shellcheck disable=SC2317
    ads_agh_api_get() {
        [ "$1" = dns_info ] || return 2
        if [ "$vrb_am_model" = "${vrb_e:-}/agh.json" ]; then printf 'GET\tdns_info\n' >> "$vrb_e/agh.calls" || return 1;fi
        [ ! -e "$vrb_am_faults/agh-read-fails" ] || return 1
        cat "$vrb_am_model" > "$2"
    }
    # shellcheck disable=SC2317
    ads_agh_api_post() {
        [ "$1" = dns_config ] || return 2
        if [ "$vrb_am_model" = "${vrb_e:-}/agh.json" ]; then vrb_worker_context || return 75;fi
        if [ "$vrb_am_model" = "${vrb_e:-}/agh.json" ]; then printf 'POST\tdns_config\n' >> "$vrb_e/agh.calls" || return 1;fi
        [ ! -e "$vrb_am_faults/agh-refuse" ] || return 1
        "$ADS_JQ" -e 'keys==["upstream_dns"] and (.upstream_dns | type)=="array" and
            all(.upstream_dns[];type=="string")' "$2" >/dev/null || return 2
        # Original helper already persisted before/planned. Preserve a separate
        # in-flight marker until its ACK AND readback have both been accepted.
        printf '%s\n' pending > "$vrb_am_evidence/request.pending" && vrj2_flush || return 1
        vrb_am_new=$(mktemp "${vrb_am_model%/*}/.agh-data.XXXXXX") || return 1
        # shellcheck disable=SC2016
        "$ADS_JQ" -cS --slurpfile n "$2" '.upstream_dns=$n[0].upstream_dns' "$vrb_am_model" > "$vrb_am_new" || return 1
        if [ "$vrb_am_model" = "${vrb_e:-}/agh.json" ]; then
            vrb_publish "$vrb_am_new" "$vrb_am_model" || return 1
        else mv "$vrb_am_new" "$vrb_am_model" || return 1;fi
        if [ -e "$vrb_am_faults/agh-lost" ]; then vrb_am_uncertain=1;return 22;fi
        printf '%s\n' '{}' > "$3"
    }
    vrb_am_rc=0;vrb_am_uncertain=0
    if [ "$AG_SET" = guarded-back ]; then
        cp "$A1" "$W/dns.json" && cp "$A2" "$W/plan.json" || return 1
        cp "$A2" "$vrb_am_evidence/dns.before.json" && cp "$A1" "$vrb_am_evidence/dns.planned.json" || return 1
        # Explicit own inverse, using the SAME existing pre/post CAS helper.
        agh_guarded_back > "$W/result" 2>&1 || vrb_am_rc=$?
    else (ads_smartdns_locked) > "$W/result" 2>&1 || vrb_am_rc=$?;fi
    [ "$vrb_am_uncertain" = 0 ] || vrb_am_rc=3
    if [ "$vrb_am_rc" = 0 ]; then rm -f "$vrb_am_evidence/request.pending" || return 1;fi
    return "$vrb_am_rc"
)

# Compile from exactly the same actual worker and private model that execution
# uses. Only cloned state changes here. Parameters and each intermediate image
# are available BEFORE the parent journal can authorise a backend mutation.
vrb_agh_predict() (
    umask 077
    [ "$#" -eq 4 ] && vr2_stage_valid "$1" && vr2_private_dir "$4" || return 2
    vrb_ap_root=$4
    cp "$1/agh.json" "$vrb_ap_root/model.json" || return 1
    vrb_agh_scope "$vrb_ap_root/model.json" > "$vrb_ap_root/before" || return 2
    vrb_ap_n=0
    for vrb_ap_action in take put; do
        if [ "$vrb_ap_action" = take ]; then vrb_ap_input=$2;vrb_ap_mode=smartdns-take-pairs
        else vrb_ap_input=$3;vrb_ap_mode=smartdns-put;fi
        [ -s "$vrb_ap_input" ] || continue
        vrb_ap_n=$((vrb_ap_n+1))
        mkdir "$vrb_ap_root/call.$vrb_ap_n" "$vrb_ap_root/evidence.$vrb_ap_n" || return 1
        cp "$vrb_ap_input" "$vrb_ap_root/params.$vrb_ap_n" || return 1
        printf '%s\n' "$vrb_ap_mode" > "$vrb_ap_root/mode.$vrb_ap_n" || return 1
        vrb_agh_model_session "$vrb_ap_root/model.json" "$vrb_ap_mode" "$vrb_ap_root/params.$vrb_ap_n" \
            "$vrb_ap_root/taken.$vrb_ap_n" "$vrb_ap_root/call.$vrb_ap_n" "$vrb_ap_root/evidence.$vrb_ap_n" \
            "$vrb_ap_root/no-faults" || return 75
        vrb_agh_scope "$vrb_ap_root/model.json" > "$vrb_ap_root/prefix.$vrb_ap_n" || return 2
    done
    vrb_agh_scope "$vrb_ap_root/model.json" > "$vrb_ap_root/after" || return 2
    printf '%s\n' "$vrb_ap_n" > "$vrb_ap_root/count"
)

# Fixed native DATA parser. The existing console helpers construct these
# commands; neither a router address nor executable can be selected here.
vrb_emu_dns_command() (
    : "${vrb_e:?}" "${vrb_t:?}"
    vrb_worker_context || return 75
    vrb_ed_cmd=$1
    case $vrb_ed_cmd in
        'dns-proxy no https upstream '*) vrb_ed_uri=${vrb_ed_cmd#dns-proxy no https upstream };vrb_ed_add= ;;
        'dns-proxy https upstream '*) vrb_ed_add=${vrb_ed_cmd#dns-proxy };vrb_ed_uri= ;;
        *) return 2 ;;
    esac
    awk -v u="$vrb_ed_uri" -v add="$vrb_ed_add" '
        /^dns-proxy$/ {dns=1;print;if(add!="")print "    " add;next}
        /^[^ \t]/ {dns=0}
        dns && $1=="https" && $2=="upstream" && u!="" && $3==u {next}
        {print}' "$vrb_e/running.cfg" > "$vrb_t/config.next" || return 1
    vrb_publish "$vrb_t/config.next" "$vrb_e/running.cfg" || return 1
    [ ! -e "$vrb_e/dns-lost" ] || return 28
)

vrb_dns_write() (
    : "${vrb_e:?}" "${vrb_t:?}" "${vrb_j:?}" "${vrb_op:?}" "${vrb_write_row:?}"
    vrb_dw_backend=$1;vrb_dw_step=$2;vrb_dw_dir=$vrb_t/dns-$1
    vrj_dir "$vrb_dw_dir" || return 2
    vrb_dw_hash=$(vrb_dns_bundle "$vrb_dw_dir") || return 3
    printf '%s\n' "$vrb_write_row" | awk -F'\t' -v h="$vrb_dw_hash" '
        {n=split($10,a,",");for(i=1;i<=n;i++)if(a[i]=="commands:" h)ok=1}END{exit ok?0:1}' || return 3
    cp "$vrb_t/pre.$vrb_dw_step" "$vrb_t/dns.expected" || return 1
    vrb_dw_i=0
    if [ "$vrb_dw_backend" = keenetic ]; then
        while IFS="$(printf '\t')" read -r vrb_dw_action vrb_dw_value; do
            vrb_scope_read dns-scope keenetic "$vrb_t/current" || return 3
            cmp -s "$vrb_t/current" "$vrb_t/dns.expected" || return 3
            vrb_dw_i=$((vrb_dw_i+1))
            if [ "$vrb_dw_action" = remove ]; then
                # The compile-time coverage check proved every URL-wide row
                # own. The actual helper rechecks the whole HTTPS observation.
                snapshot;doh_lines > "$vrb_t/doh.before" || return 3
                DOH_ALLOWED=$vrb_dw_dir/before
                export DOH_ALLOWED
                vrb_dw_line=$(awk -v u="$vrb_dw_value" '$3==u{print;exit}' "$vrb_t/doh.before")
                [ -n "$vrb_dw_line" ] || return 3
                doh_remove_url "$vrb_dw_line" "$vrb_dw_value" "$vrb_t/doh.before" || return 3
            elif [ "$vrb_dw_action" = add ]; then ndm "dns-proxy $vrb_dw_value" || :
            else return 2;fi
            vrb_scope_read dns-scope keenetic "$vrb_t/current" || return 3
            cmp -s "$vrb_t/current" "$vrb_dw_dir/prefix.$vrb_dw_i" || return 3
            cp "$vrb_t/current" "$vrb_t/dns.expected" || return 1
        done < "$vrb_dw_dir/commands"
    elif [ "$vrb_dw_backend" = agh ]; then
        mkdir "$vrb_j/$vrb_op/dns-evidence" || return 1
        while [ "$vrb_dw_i" -lt "$(cat "$vrb_dw_dir/count")" ]; do
            vrb_scope_read dns-scope agh "$vrb_t/current" || return 3
            cmp -s "$vrb_t/current" "$vrb_t/dns.expected" || return 3
            vrb_dw_i=$((vrb_dw_i+1))
            vrb_dw_work=$vrb_j/$vrb_op/dns-evidence/call.$vrb_dw_i
            vrb_dw_evidence=$vrb_j/$vrb_op/dns-evidence/evidence.$vrb_dw_i
            mkdir "$vrb_dw_work" "$vrb_dw_evidence" || return 1
            vrb_agh_model_session "$vrb_e/agh.json" "$(cat "$vrb_dw_dir/mode.$vrb_dw_i")" \
                "$vrb_dw_dir/params.$vrb_dw_i" "$vrb_dw_work/taken" "$vrb_dw_work" "$vrb_dw_evidence" "$vrb_e" || return 3
            [ ! -e "$vrb_dw_evidence/request.pending" ] || return 3
            vrb_scope_read dns-scope agh "$vrb_t/current" || return 3
            cmp -s "$vrb_t/current" "$vrb_dw_dir/prefix.$vrb_dw_i" || return 3
            cp "$vrb_t/current" "$vrb_t/dns.expected" || return 1
        done
    else return 2;fi
)

vrb_dns_inverse() (
    : "${vrb_e:?}" "${vrb_t:?}" "${vrb_j:?}" "${vrb_op:?}"
    vrb_role=inverse;vrb_active_step=$2
    export vrb_role vrb_active_step
    vrb_worker_context || return 75
    if [ "$1" = agh ]; then
        vrb_di_work=$(mktemp -d "$vrb_j/$vrb_op/dns-inverse.XXXXXX") || return 1
        mkdir "$vrb_di_work/call" "$vrb_di_work/evidence" || return 1
        vrb_scope_read dns-scope agh "$vrb_t/check" || return 3
        cmp -s "$vrb_t/check" "$vrb_t/current" || return 75
        vrb_agh_model_session "$vrb_e/agh.json" guarded-back "$vrb_t/pre.$2" "$vrb_t/current" \
            "$vrb_di_work/call" "$vrb_di_work/evidence" "$vrb_e" || return 3
    elif [ "$1" = keenetic ]; then
        cp "$vrb_t/current" "$vrb_t/dns.inverse.expected" || return 1
        awk 'FILENAME==ARGV[1]{old[$0]=1;next}!($0 in old){print $3}' "$vrb_t/pre.$2" "$vrb_t/current" |
            LC_ALL=C sort -u > "$vrb_t/dns.inverse.urls"
        while IFS= read -r vrb_di_uri; do
            vrb_scope_read dns-scope keenetic "$vrb_t/check" || return 3
            cmp -s "$vrb_t/check" "$vrb_t/dns.inverse.expected" || return 75
            snapshot;doh_lines > "$vrb_t/doh.inverse.before"
            vrb_di_line=$(awk -v u="$vrb_di_uri" '$3==u{print;exit}' "$vrb_t/doh.inverse.before")
            DOH_ALLOWED=$vrb_t/dns.inverse.expected;export DOH_ALLOWED
            doh_remove_url "$vrb_di_line" "$vrb_di_uri" "$vrb_t/doh.inverse.before" || return 3
            awk -v u="$vrb_di_uri" '$3!=u' "$vrb_t/dns.inverse.expected" > "$vrb_t/dns.inverse.next"
            mv "$vrb_t/dns.inverse.next" "$vrb_t/dns.inverse.expected" || return 1
        done < "$vrb_t/dns.inverse.urls"
        awk 'FILENAME==ARGV[1]{seen[$0]=1;next}!($0 in seen){print}' "$vrb_t/dns.inverse.expected" "$vrb_t/pre.$2" > "$vrb_t/dns.inverse.adds"
        while IFS= read -r vrb_di_line; do
            vrb_scope_read dns-scope keenetic "$vrb_t/check" || return 3
            cmp -s "$vrb_t/check" "$vrb_t/dns.inverse.expected" || return 75
            ndm "dns-proxy $vrb_di_line" || :
            { cat "$vrb_t/dns.inverse.expected";printf '%s\n' "$vrb_di_line"; } | LC_ALL=C sort > "$vrb_t/dns.inverse.next"
            mv "$vrb_t/dns.inverse.next" "$vrb_t/dns.inverse.expected" || return 1
        done < "$vrb_t/dns.inverse.adds"
    else return 2;fi
    vrb_scope_read dns-scope "$1" "$vrb_t/check" && cmp -s "$vrb_t/check" "$vrb_t/pre.$2"
)
