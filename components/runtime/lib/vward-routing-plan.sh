#!/bin/sh
# RS-7 stage 1: pure routing planner. Defines two functions; loading does nothing.
#
#   vward_routing_plan GENERATION AUDIT IDENTITY SHADOW CONTEXT
#   vward_routing_plan_log PLAN
#
# A PLAN IS TEXT. It is a proposal derived from one verified snapshot; it is not
# executed, not queued and not an approval. No writer, ndmc, DNS, AGH or VPN call,
# no file written, no lock, no clock read (age comes in CONTEXT). Every doubt is
# `unknown` -> action none: the planner never guesses.
#
# GENERATION  g-<16 hex> of the snapshot (vward_routing_consistent_read).
# AUDIT       vward_routing_audit output of that snapshot (its column 11 must equal it).
# IDENTITY    identity.tsv of that snapshot.
# SHADOW      vward_routing_shadow output of that snapshot (may be empty).
# CONTEXT     TSV `key<TAB>value`, each key at most once, missing = unknown:
#               dns_mode     agh | dnsmasq | native | both | unknown
#                            (exactly ONE handler may be active; `both` = conflict)
#               agh_recovery none | pending | unknown   (private AGH recovery evidence)
#               writers      disabled | enabled
#               age          seconds since the snapshot was taken (integer) | unknown
#               max_age      freshness limit in seconds (integer)
#
# PLAN rows (TSV, sorted):
#   DOMAIN ACTION TARGET DNS ELIGIBLE PERMIT NEEDS REASON GENERATION
# ACTION   none | add (stage 1 proposes only these; move/remove/restore are later stages)
# ELIGIBLE yes = the proposal is sound on this snapshot; no = blocked, REASON says why
# PERMIT   denied:writers-disabled | requires-approval   (never `granted`)
# NEEDS    what a future writer MUST still do before it touches anything:
#          recheck-generation,owner-proof,change-lock,journal-before-write   (or `-`)
# rc 0 ok; rc 2 invalid input/limit (no stdout); rc 3 generations disagree ->
# stdout `unknown<TAB>generation-mismatch`. Limits as RS5: 4096 lines, 1 MiB per input,
# 1024 domains, 4096 rows.

# v2 is a separate typed format. v1 functions/validation below remain intact.
# STAGE and PROJECT are verified private operation directories, not router paths.
# The result never grants live permission. Only the offline coordinator can
# exercise these deltas against its explicitly checked built-in emulator.
vward_routing_plan2() (
    [ "$#" -eq 3 ] || return 2
    vr2_private_dir "$1" && vr2_private_dir "$2" || return 2
    vr2_stage_valid "$1" && vr2_projection_valid "$2" || return 3
    case $3 in ''|[!A-Za-z0-9]*|*[!A-Za-z0-9_.-]*) return 2 ;; esac
    [ "${#3}" -le 32 ] || return 2
    for vr2_f in "$1/generation" "$2/generation" "$2/service" "$2/policy.tsv" "$2/atoms.tsv" \
        "$1/decision/resources.tsv" "$1/decision/proofs.tsv" "$1/decision/context.tsv" \
        "$1/decision/policies.tsv" "$1/decision/tombstones.tsv" "$1/decision/choices.tsv" \
        "$2/choices.tsv" "$1/inventory.tsv" "$1/groups.tsv"; do vr2_file "$vr2_f" || return 2; done
    cmp -s "$1/generation" "$2/generation" || return 3
    vr2_gen=$(cat "$1/generation");vr2_sid=$(cat "$2/service")
    printf '%s\n' "$vr2_gen" | grep -Eq '^g-[0-9a-f]{16}$' || return 2
    vr2_authority=$(mktemp "$2/.dns-authority.XXXXXX") || return 1
    trap 'rm -f "$vr2_authority"' EXIT
    vr2_dns_owned_authority "$1/decision/resources.tsv" "$1/decision/proofs.tsv" "$2/dns.tsv" > "$vr2_authority" || return 2
    VWARD_B_GEN=$vr2_gen VWARD_B_SID=$vr2_sid VWARD_B_OP=$3 LC_ALL=C awk '
    BEGIN {FS=OFS="\t";gen=ENVIRON["VWARD_B_GEN"];sid=ENVIRON["VWARD_B_SID"];op=ENVIRON["VWARD_B_OP"]}
    function id(s) {return length(s)<=64 && s ~ /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/}
    function refid(s) {return length(s)<=64 && s ~ /^[A-Za-z0-9][A-Za-z0-9_.:@-]*$/}
    function service(s) {return length(s)<=63 && s ~ /^[a-z0-9][a-z0-9.@_-]*$/}
    function domain(s,a,n,i) {
        if(length(s)>253 || s !~ /^[a-z0-9.-]+$/) return 0
        n=split(s,a,".");if(n<2 || a[n] ~ /^[0-9]+$/) return 0
        for(i=1;i<=n;i++) if(length(a[i])>63 || a[i] !~ /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/) return 0
        return 1
    }
    function covers(p,d,s) {return p==d || (s=="subtree" && length(d)>length(p) && substr(d,length(d)-length(p))=="." p)}
    function encode(s) {gsub(/\t/,"|",s);return s}
    function prefix(s,a,n,i,r) {n=split(s,a,OFS);r=a[1];for(i=2;i<=10;i++)r=r OFS a[i];return r}
    function hold(d,reason) {holds[d SUBSEP reason]=1;nh=1}
    function union_refs(left,right, a,n,i,seen,keys,k,nk,result) {
        n=split(left "," right,a,",")
        for(i=1;i<=n;i++)if(a[i]!="" && a[i]!="-")seen[a[i]]=1
        for(k in seen)keys[++nk]=k
        sort(keys,nk);result=""
        for(i=1;i<=nk;i++)result=result (i==1?"":",") keys[i]
        return result==""?"-":result
    }
    function consumers_known(list,d, a,n,i,r,src,key) {
        if(list=="-")return 0
        n=split(list,a,",")
        for(i=1;i<=n;i++) {
            r=a[i];src=substr(r,1,1);key=d SUBSEP r
            if(index("," refs[d] ",","," r ","))continue
            if(ctx["source:" src]=="0")continue
            if(r=="S:" sid && atom_mode[d]=="auto")continue
            if(src=="S" && choice_mode[substr(r,3)]=="auto")continue
            if(contribution_state[key]=="inactive" || contribution_state[key]=="suppressed")continue
            return 0
        }
        return 1
    }
    function sort(a,n, width,left,mid,right,i,j,k,tmp) {
        for(width=1;width<n;width*=2) {
            for(left=1;left<=n;left+=2*width) {
                mid=left+width;right=left+2*width
                if(mid>n+1) mid=n+1
                if(right>n+1) right=n+1
                i=left;j=mid
                for(k=left;k<right;k++)
                    if(i<mid && (j>=right || "x" a[i]<="x" a[j])) tmp[k]=a[i++]
                    else tmp[k]=a[j++]
            }
            for(k=1;k<=n;k++) a[k]=tmp[k]
        }
    }
    function step(action,kind,rid,pre,post,proof,refs,inverse) {
        if(++ns>4096) {bad=1;return}
        steps[ns]="step" OFS ns OFS action OFS kind OFS rid OFS encode(pre) OFS encode(post) OFS proof OFS refs OFS "generation,identity,postimage,save" OFS inverse
        if((plan_bytes+=length(steps[ns])+1)>1048000) {bad=1;delete steps[ns]}
    }
    function check_dependency(kind,backend,target,d) {
        if(kind=="route" && target ~ /^VPN:/ && (ctx[target]!="available" || !(target in native_vpn))) hold(d,"vpn-unavailable-or-unknown")
        if(kind=="dns" && (ctx["storage:" backend]!="available" || dns_observed[backend]!="known")) hold(d,"storage-unavailable-or-unknown")
    }
    function native_group(target,policy, key,i,r,a,j) {
        key=target SUBSEP policy
        if(key in allocated) return allocated[key]
        for(j=1;j<=nk;j++) {r=rkeys[j]
            split(resource[r],a,OFS)
            if(a[1]=="route" && a[6]==target && a[7]==policy && a[9]=="vward" && proof_ok[r]) return allocated[key]=a[3]
        }
        for(i=0;i<100;i++) if(!("domain-list" i in group_names)) {
            group_names["domain-list" i]=1;return allocated[key]="group:domain-list" i
        }
        return ""
    }
    {bytes[FILENAME]+=length($0)+1;if(FNR>4096 || bytes[FILENAME]>1048576) {bad=1;next}}
    FILENAME==ARGV[1] {
        if($2=="policy") {
            if(NF!=6 || $3!=1 || $5!="denied" || $6!="unknown" || ($1 in verdict) ||
               $4 !~ /^(desired|inactive|unresolved|unknown)$/) {bad=1;next}
            verdict[$1]=$4
            if($4=="unknown" || $4=="unresolved") hold($1,$4)
        } else if($2=="contribution") {
            if(NF!=8 || $3 !~ /^[MSA]$/ || !refid($4) || $7 !~ /^(active|inactive|suppressed|unknown)$/) {bad=1;next}
            contribution_state[$1 SUBSEP $3 ":" $4]=$7
            if($7=="active") {
                key=$5 SUBSEP $6
                if($1 in wanted && wanted[$1]!=key) hold($1,"peer-conflict")
                wanted[$1]=key;wt[$1]=$5;wp[$1]=$6
                ref=$3 ":" $4
                if(!index("," refs[$1] ",","," ref ",")) refs[$1]=refs[$1] ? refs[$1] "," ref : ref
            }
        } else bad=1
        next
    }
    FILENAME==ARGV[2] {
        if(NF!=9 || $1!="atom" || !domain($2) || $3 !~ /^(exact|subtree)$/ || ($2 in scope)) {bad=1;next}
        scope[$2]=$3;atom_mode[$2]=$4;domains[++nd]=$2;next
    }
    FILENAME==ARGV[3] {
        if(NF!=11 || $1 !~ /^(route|dns)$/ || !id($2) || !id($3) ||
           ($4!="-" && !domain($4)) || $5 !~ /^(exact|subtree)$/ ||
           ($6!="ISP" && !($6 ~ /^VPN:/ && id(substr($6,5)))) || !id($7) ||
           $8 !~ /^(native|keenetic|agh)$/ || $9 !~ /^(vward|manual|unknown)$/ || !id($10) ||
           $11 !~ /^(-|[MSA]:[A-Za-z0-9_.:@-]+(,[MSA]:[A-Za-z0-9_.:@-]+)*)$/ || ($2 in resource)) {bad=1;next}
        resource[$2]=$0;nr++;next
    }
    FILENAME==ARGV[4] {
        pn=split($11,pv,":")
        if(NF!=11 || !id($2) || pv[1] !~ /^[0-9]+$/ || pv[1]+0>2147483647 || ($2 in proof) ||
            ($1=="dns" && (pn!=2 || length(pv[2])!=48 || pv[2]!~/^[0-9a-f]+$/)) ||
            ($1=="route" && pn!=1) || $1!~/^(route|dns)$/) {bad=1;next}
        proof_content[$2]=pv[2]
        proof[$2]=prefix($0);next
    }
    FILENAME==ARGV[5] {if(NF!=2 || ($1 in ctx)) bad=1;ctx[$1]=$2;next}
    FILENAME==ARGV[6] {
        if(NF!=7 || !id($1) || $2 !~ /^(keenetic|agh)$/ || $3 !~ /^(available|unavailable|unknown)$/ ||
           $4 !~ /^(active|inactive|unknown)$/ || $5 !~ /^(none|supported|unsupported)$/ ||
           $6 !~ /^[0-9]+$/ || $6+0>2147483647 || !id($7) || ($1 in backend)) {bad=1;next}
        backend[$1]=$2;available[$1]=$3;handler[$1]=$4;upfile[$1]=$5;policy_rev[$1]=$6;url[$1]=$7;next
    }
    FILENAME==ARGV[7] {
        if(NF!=3 || !id($1) || $2 !~ /^[0-9]+$/ || $3!="deleted" || ($1 in tomb)) {bad=1;next}
        tomb[$1]=$2;next
    }
    FILENAME==ARGV[8] {if($1=="service" && $2==sid) choice_pre=$0;next}
    FILENAME==ARGV[9] {if($1=="service") {choice_mode[$2]=$4;if($2==sid)choice_post=$0}next}
    FILENAME==ARGV[10] {
        if(NF!=13 || $1!="resource" || $11!="reference") {bad=1;next}
        native["group:" $3 SUBSEP $4 SUBSEP $5 SUBSEP $6 SUBSEP $7]=$0
        native_row[$13]="route" OFS $13 OFS "group:" $3 OFS $4 OFS $5 OFS $6 OFS $7 OFS "native" OFS "unknown" OFS "reference" OFS "-"
        next
    }
    FILENAME==ARGV[11] {if(NF!=1 || !id($1)) bad=1;group_names[$1]=1;next}
    FILENAME==ARGV[12] {if($1=="health" && $2~/^VPN:/)native_vpn[$2]=1;next}
    FILENAME==ARGV[13] {
        if($1=="backend") {
            if(NF!=4 || $2!~/^(keenetic|agh)$/ || $3!~/^(known|unknown)$/ || $4!~/^[0-9]+$/ || ($2 in dns_observed)){bad=1;next}
            dns_observed[$2]=$3;dns_slots[$2]=$4+0;next
        }
        if($1=="witness") {
            if(NF!=3 || !id($2) || length($3)!=48 || $3!~/^[0-9a-f]+$/ || ($2 in dns_content)){bad=1;next}
            dns_content[$2]=$3;next
        }
        if(NF!=11 || $1!="dns" || $9!="manual" || $10!="reference"){bad=1;next}
        dns_native[$3 SUBSEP $4 SUBSEP $5 SUBSEP $8]=$0;dns_row[$2]=$0;next
    }
    FILENAME==ARGV[15] {if(NF!=2 || ($1 in dns_authority))bad=1;dns_authority[$1]=$2;next}
    FILENAME==ARGV[14] {if(NF!=2 || !id($1) || !id($2) || ($1 in upstream_key))bad=1;upstream_key[$1]=$2;next}
    END {
        if(nd>1024 || nr>4096 || bad || !service(sid)) exit 2
        # Map actual native observations. Omitted resources remain references;
        # an input manifest cannot make a missing/replaced native row managed.
        for(r in resource) {
            split(resource[r],a,OFS)
            relevant=0
            for(k=1;k<=nd;k++)if(covers(a[4],domains[k],a[5]) || covers(domains[k],a[4],scope[domains[k]])) {relevant=1;break}
            # Out-of-scope resources remain immutable observations. Their
            # unavailable backend neither grants rights nor becomes a health
            # dependency of this operation. Any actual overlap still validates.
            if(!relevant)continue
            if(a[9]=="vward") {
                if(!(r in proof) || proof[r]!=prefix(resource[r])) hold(a[4],"ownership-unproven")
                else proof_ok[r]=1
            }
            if(a[1]=="route") {
                key=a[3] SUBSEP a[4] SUBSEP a[5] SUBSEP a[6] SUBSEP a[7]
                if(!(key in native)) hold(a[4],"native-resource-changed")
                else {
                    split(native[key],b,OFS);matched_native[b[13]]=1
                    if(a[9]=="vward" && (b[8]!="vward" || b[10]!="verified")) hold(a[4],"native-proof-unverified")
                }
            } else {
                key=a[3] SUBSEP a[4] SUBSEP a[5] SUBSEP a[8]
                if(!(key in dns_native))hold(a[4],"native-dns-resource-changed")
                else {
                    split(dns_native[key],b,OFS);matched_dns[b[2]]=1
                    if(a[9]=="vward" && dns_authority[r]!="authorized")hold(a[4],dns_authority[r]==""?"ownership-unproven":dns_authority[r])
                }
            }
        }
        for(r in native_row) if(!matched_native[r]) resource[r]=native_row[r]
        for(r in dns_row)if(!matched_dns[r])resource[r]=dns_row[r]
        for(r in resource) rkeys[++nk]=r
        if(nk>4096) exit 2
        sort(rkeys,nk)
        # Parent suffixes are compiled before their known descendants. One
        # backend binding carries the UNION of all compatible consumer claims.
        # An excluded/conflicting descendant cannot be silently covered by a
        # broader physical suffix merely because its root was confirmed.
        for(i=1;i<=nd;i++)domain_order[i]=sprintf("%03d:%s",length(domains[i]),domains[i])
        sort(domain_order,nd)
        for(i=1;i<=nd;i++)domains[i]=substr(domain_order[i],5)
        for(i=1;i<=nd;i++) {
            d=domains[i]
            if(!(d in wanted) || wp[d]=="default")continue
            dns_root[d]=d
            for(j=1;j<i;j++) {
                p=domains[j]
                if((p in dns_root) && scope[p]=="subtree" && covers(p,d,"subtree") &&
                    wt[p]==wt[d] && backend[wp[p]]==backend[wp[d]] &&
                    upstream_key[url[wp[p]]]==upstream_key[url[wp[d]]]) {dns_root[d]=dns_root[p];break}
            }
            dns_refs[dns_root[d]]=union_refs(dns_refs[dns_root[d]],refs[d])
            if(scope[d]=="subtree")for(j=1;j<=nd;j++) {
                child=domains[j]
                if(child==d || !covers(d,child,"subtree"))continue
                if(!(child in wanted) || wt[child]!=wt[d] || wp[child]=="default" ||
                    backend[wp[child]]!=backend[wp[d]] || upstream_key[url[wp[child]]]!=upstream_key[url[wp[d]]])
                    hold(d,"dns-prefix-child-conflict")
            }
        }
        for(d in dns_refs)refs[d]=dns_refs[d]
        if(nd==0 && choice_post!="") {
            split(choice_post,a,OFS)
            if(a[4]!="auto") hold("-","service-scope-unknown")
        }
        for(i=1;i<=nd;i++) {
            d=domains[i];target=(d in wanted) ? wt[d] : "ISP";policy=(d in wanted) ? wp[d] : "default"
            if((d in dns_root) && dns_root[d]!=d) {
                # Existing exact own child rows may be consolidated into the
                # authorised parent. Unknown/independent claims HOLD first.
                for(j=1;j<=nk;j++) {
                    r=rkeys[j];split(resource[r],a,OFS)
                    if(a[1]!="dns" || a[4]!=d || a[9]!="vward")continue
                    if(!proof_ok[r] || !consumers_known(a[11],d)) {hold(d,"resource-has-independent-consumers");continue}
                    if(!removed[r]) {check_dependency("dns",a[8],a[6],d)
                        step("remove","dns",r,resource[r],"-",a[10],"-","restore-own-resource");removed[r]=1}
                }
                continue
            }
            move_rid="";move_pre="";move_birth=""
            if(scope[d]=="subtree" && ctx["scope:subtree"]!="available") hold(d,"scope-unproven")
            kind=(policy!="default") ? "dns" : (target ~ /^VPN:/ ? "route" : "none")
            # A native include is an observed exact name. Subtree attribution
            # lets later confirmed names inherit intent; it does not turn the
            # current physical include into a wildcard ownership proof.
            physical_scope=(kind=="dns"?"subtree":"exact")
            dest_backend="native"
            if(kind=="dns") {
                dest_backend=backend[policy]
                if(dest_backend=="" || available[policy]!="available" || handler[policy]!="active") hold(d,"dns-policy-unavailable-or-unknown")
                if(dest_backend=="agh" && upfile[policy]=="unsupported") hold(d,"upstream-file-unsupported")
                if(policy in tomb && policy_rev[policy]+0<=tomb[policy]+0) hold(d,"dns-policy-deleted")
                if(!(url[policy] in upstream_key))hold(d,"dns-policy-location-unknown")
                # Both current upstream backends express a DNS suffix. An
                # exact-only service attribution cannot authorise that broader
                # physical scope, even if the server is healthy.
                if(scope[d]!="subtree")hold(d,"dns-prefix-scope-unproven")
            }
            if(kind!="none") check_dependency(kind,dest_backend,target,d)
            covered=0
            for(j=1;j<=nk;j++) {r=rkeys[j]
                split(resource[r],a,OFS)
                if(!covers(a[4],d,a[5])) continue
                compatible=((kind=="none" && a[1]=="route" && a[6]=="ISP" && a[7]=="default") ||
                    (a[1]==kind && a[6]==target && ((kind!="dns" && a[7]==policy) || (kind=="dns" && a[3]=="upstream:" upstream_key[url[policy]])) &&
                        a[8]==dest_backend && (physical_scope=="exact" || a[5]=="subtree")))
                if(compatible) {
                    covered=1
                    if(a[9]=="vward" && proof_ok[r] && !touched[r]) {
                        if(!consumers_known(a[11],d))hold(d,"resource-consumer-unknown")
                        post=prefix(resource[r]) OFS refs[d]
                        if(post!=resource[r]) step("add","claims",r,resource[r],post,a[10],refs[d],"restore-own-consumers")
                        touched[r]=1
                    }
                    continue
                }
                if(a[9]!="vward" || !proof_ok[r]) {
                    # Auto/off withdraws only S. Observed independent references
                    # remain configured; this is not an explicit ISP pin.
                    if(!(kind=="none" && atom_mode[d]=="auto")) hold(d,"foreign-resource-conflict")
                    continue
                }
                # Removal is scoped to this one resource. A parent subtree or
                # independently consumed atom requires a separate reconciliation.
                if(a[4]!=d || !consumers_known(a[11],d)) {hold(d,"resource-has-independent-consumers");continue}
                if(!removed[r]) {
                    if(a[1]=="dns") check_dependency("dns",a[8],a[6],d)
                    if(kind==a[1] && kind!="none") {
                        if(move_rid!="")hold(d,"ambiguous-owned-move")
                        move_rid=r;move_pre=resource[r];move_birth=a[10]
                    } else step("remove",a[1],r,resource[r],"-",a[10],"-","restore-own-resource")
                    removed[r]=1
                }
            }
            if(covered && move_rid!="") step("remove",kind,move_rid,move_pre,"-",move_birth,"-","restore-own-resource")
            if(kind!="none" && !covered) {
                if(move_rid!="") {rid=move_rid;birth=move_birth}
                else {rid="b-" op "-" ++newid;birth="p-" op "-" newid}
                nat=(kind=="route") ? native_group(target,policy) : "upstream:" upstream_key[url[policy]]
                if(nat=="") {hold(d,"no-free-native-group");continue}
                post=kind OFS rid OFS nat OFS d OFS physical_scope OFS target OFS policy OFS dest_backend OFS "vward" OFS birth OFS refs[d]
                if(move_rid!="") step("move",kind,rid,move_pre,post,birth,refs[d],"restore-own-resource")
                else step("create",kind,rid,"-",post,birth,refs[d],"remove-own-resource")
                created[rid]=post
            }
        }
        slots=dns_slots["keenetic"]
        for(r in resource) {split(resource[r],a,OFS);if(a[1]=="dns" && a[8]=="keenetic" && removed[r])slots--}
        for(r in created) {split(created[r],a,OFS);if(a[1]=="dns" && a[8]=="keenetic")slots++}
        if(slots>8) hold("-","keenetic-capacity")
        if(choice_pre!=choice_post) step("move","choice",sid,(choice_pre=="" ? "-" : choice_pre),(choice_post=="" ? "-" : choice_post),"revision-cas","S:" sid,"restore-own-choice")
        if(bad) exit 2
        print "routing-plan",2,gen,"denied"
        if(nh) {
            for(h in holds) hkeys[++hn]=h
            sort(hkeys,hn)
            for(i=1;i<=hn;i++) {split(hkeys[i],a,SUBSEP);print "hold",a[1],a[2]}
            exit
        }
        for(i=1;i<=ns;i++) print steps[i]
    }' "$2/policy.tsv" "$2/atoms.tsv" "$1/decision/resources.tsv" "$1/decision/proofs.tsv" \
        "$1/decision/context.tsv" "$1/decision/policies.tsv" "$1/decision/tombstones.tsv" \
        "$1/decision/choices.tsv" "$2/choices.tsv" "$1/inventory.tsv" "$1/groups.tsv" "$1/snapshot.tsv" "$2/dns.tsv" "$2/upstream-keys.tsv" "$vr2_authority"
)

vward_routing_plan() (
    [ "$#" -eq 5 ] || { printf '%s\n' 'routing plan: expected GENERATION AUDIT IDENTITY SHADOW CONTEXT' >&2; return 2; }
    vrp_gen=$1
    printf '%s\n' "$vrp_gen" | grep -Eq '^g-[0-9a-f]{16}$' || { printf '%s\n' 'routing plan: generation must be g-<16 hex>' >&2; return 2; }
    shift
    for vrp_f in "$@"; do
        case $vrp_f in /*) ;; *) printf '%s\n' 'routing plan: absolute file paths required' >&2; return 2 ;; esac
        if [ -L "$vrp_f" ] || [ ! -f "$vrp_f" ] || [ ! -r "$vrp_f" ]; then
            printf '%s\n' 'routing plan: regular readable files required' >&2; return 2
        fi
    done
    LC_ALL=C awk -v gen="$vrp_gen" '
    BEGIN { FS=OFS="\t" }
    function id(s) { return length(s)<=64 && s ~ /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/ }
    function domain(s, n,a,i) {
        if (length(s)>253 || s !~ /^[a-z0-9.-]+$/) return 0
        n=split(s,a,"."); if(n<2) return 0
        for(i=1;i<=n;i++) if(length(a[i])<1 || length(a[i])>63 || a[i] !~ /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/) return 0
        return 1
    }
    function msort(a,n, width,left,mid,right,i,j,pos,tmp) {
        for(width=1;width<n;width*=2) {
            for(left=1;left<=n;left+=2*width) {
                mid=left+width; right=left+2*width
                if(mid>n+1) mid=n+1
                if(right>n+1) right=n+1
                i=left; j=mid
                for(pos=left;pos<right;pos++) {
                    if(i<mid && (j>=right || "x" a[i] <= "x" a[j])) tmp[pos]=a[i++]
                    else tmp[pos]=a[j++]
                }
            }
            for(pos=1;pos<=n;pos++) a[pos]=tmp[pos]
        }
    }
    {
        bytes[FILENAME]+=length($0)+1
        if(FNR>4096 || bytes[FILENAME]>1048576) { invalid=1; next }
    }
    FILENAME==ARGV[1] {
        if(NF!=12 || !domain($1) || $8 !~ /^(unknown|unresolved|inactive|blocked|covered|review)$/ || $12!="unknown" || ($1 in a_line)) { invalid=1; next }
        if($11!=gen) gen_mismatch=1
        a_line[$1]=$0; nd++
        next
    }
    FILENAME==ARGV[2] {
        if(NF!=9 || !id($1) || $8 !~ /^(verified|reference-only|unknown)$/ || $9!="reference") { invalid=1; next }
        ident[$1]=$8; next
    }
    FILENAME==ARGV[3] {
        if(NF!=14 || ($1!="-" && !domain($1)) || $3 !~ /^(match|diverge|unknown|not-comparable)$/ || $5 !~ /^(info|review)$/ || $4 !~ /^[a-z0-9-]+$/) { invalid=1; next }
        if($1=="-") next    # interface-level / mechanism-level rows: no domain to block
        if($4=="service-target-defaulted") s_defaulted[$1]=1
        else if($5=="review") s_review[$1]=$4
        else if($4=="rs-unknown") s_unknown[$1]=1
        s_seen[$1]=1
        next
    }
    FILENAME==ARGV[4] {
        if(NF!=2 || ($1 in ctx) || $1 !~ /^(dns_mode|agh_recovery|writers|age|max_age)$/) { invalid=1; next }
        ctx[$1]=$2; next
    }
    END {
        dns_mode=("dns_mode" in ctx) ? ctx["dns_mode"] : "unknown"
        agh=("agh_recovery" in ctx) ? ctx["agh_recovery"] : "unknown"
        writers=("writers" in ctx) ? ctx["writers"] : "disabled"
        if(dns_mode !~ /^(agh|dnsmasq|native|both|unknown)$/ || agh !~ /^(none|pending|unknown)$/ || writers !~ /^(disabled|enabled)$/) invalid=1
        age=("age" in ctx) ? ctx["age"] : "unknown"; maxage=("max_age" in ctx) ? ctx["max_age"] : "unknown"
        if((age!="unknown" && age !~ /^[0-9]+$/) || (maxage!="unknown" && maxage !~ /^[0-9]+$/)) invalid=1
        if(nd>1024) invalid=1
        if(invalid) { print "routing plan: invalid input or limit exceeded" > "/dev/stderr"; exit 2 }
        if(gen_mismatch) { print "unknown\tgeneration-mismatch"; exit 3 }
        permit=(writers=="enabled") ? "requires-approval" : "denied:writers-disabled"
        for(d in a_line) {
            split(a_line[d],f,"\t"); decision=f[8]; areason=f[9]
            act="none"; tgt="-"; dns="-"; elig="no"; need="-"; reason=""
            if(decision=="inactive") reason="no-active-intent"
            else if(decision=="covered") reason="already-covered"
            else if(decision=="unresolved") reason="conflicting-target-or-dns"
            else if(decision=="blocked") reason="dependency-unavailable"
            else if(decision=="unknown") reason=(areason=="snapshot-or-source-unknown") ? "snapshot-or-source-unknown" : "dependency-unknown"
            else {
                # review: new coverage is needed. One unambiguous wanted path or nothing.
                n=0; w=f[4]; nw=(w=="-") ? 0 : split(w,wa,",")
                if(nw==1) { split(wa[1],p,"@"); tgt=p[2]; dns=p[3]; act="add" }
                if(act!="add") reason="ambiguous-wanted"
                else if(d in s_defaulted) reason="service-target-defaulted"
                else if(d in s_review) reason="shadow-" s_review[d]
                else if(d in s_unknown) reason="shadow-unknown"
                else {
                    # Ownership of every ACTIVE ref, not of the name: unknown beats reference-only.
                    worst="verified"; na=(f[3]=="-") ? 0 : split(f[3],aa,",")
                    if(na==0) worst="unknown"
                    for(i=1;i<=na;i++) { r=aa[i]; sub(/^[MSA]:/,"",r); st=(r in ident) ? ident[r] : "unknown"
                        if(st=="unknown") worst="unknown"; else if(st=="reference-only" && worst!="unknown") worst="reference-only" }
                    if(worst=="unknown") reason="ownership-unknown"
                    else if(worst=="reference-only") reason="ownership-unproven"
                    else if(age=="unknown" || maxage=="unknown") reason="snapshot-age-unknown"
                    else if(age+0>maxage+0) reason="snapshot-stale"
                    else if(dns_mode=="unknown") reason="dns-mode-unknown"
                    else if(dns_mode=="both") reason="dns-modes-conflict"
                    else if(agh=="pending") reason="agh-recovery-pending"
                    else if(agh=="unknown" && dns_mode=="agh") reason="agh-recovery-unknown"
                    else { elig="yes"; reason="new-coverage-needed"; need="recheck-generation,owner-proof,change-lock,journal-before-write" }
                }
            }
            line=d OFS act OFS tgt OFS dns OFS elig OFS ((elig=="yes") ? permit : "denied:not-eligible") OFS need OFS reason OFS gen
            out[++no]=line
        }
        for(d in s_seen) if(!(d in a_line)) out[++no]=d OFS "none" OFS "-" OFS "-" OFS "no" OFS "denied:not-eligible" OFS "-" OFS "domain-not-in-snapshot" OFS gen
        if(no>4096) { print "routing plan: output limit exceeded" > "/dev/stderr"; exit 2 }
        msort(out,no)
        for(i=1;i<=no;i++) print out[i]
    }' "$@"
)

# vward_routing_plan_log PLAN: one bounded, secret-free event line per plan row, ready
# for the existing event log (the caller adds the time stamp and appends; nothing is
# written here). Every field is a closed token or a normalized FQDN.
vward_routing_plan_log() (
    [ "$#" -eq 1 ] || return 2
    case $1 in /*) ;; *) return 2 ;; esac
    [ -f "$1" ] && [ ! -L "$1" ] && [ -r "$1" ] || return 2
    LC_ALL=C awk 'BEGIN { FS="\t" }
        FNR>4096 { bad=1; next }
        NF!=9 || $2 !~ /^(none|add)$/ || $5 !~ /^(yes|no)$/ || $6 !~ /^(denied:[a-z-]+|requires-approval)$/ || $8 !~ /^[a-z0-9-]+$/ || $9 !~ /^g-[0-9a-f]{16}$/ || $1 !~ /^[a-z0-9.-]+$/ { bad=1; next }
        { out[++n]="PLAN|" $1 "|" $2 "|" $5 "|" $6 "|" $8 "|" $9 }
        END { if(bad) { print "routing plan log: invalid plan" > "/dev/stderr"; exit 2 }; for(i=1;i<=n;i++) print out[i] }' "$1"
)
