#!/bin/sh
# RS-6 shadow comparison. Defines ONE function; loading does nothing.
#
#   vward_routing_shadow GENERATION AUDIT IDENTITY LEGACY
#
# GENERATION  g-<16 hex> from vward_routing_consistent_read (file `generation`).
# AUDIT       RS5 vward_routing_audit output computed from that same snapshot.
# IDENTITY    identity.tsv of that snapshot (stable IDs, identity states).
# LEGACY      normalized observations of the existing mechanisms, stamped with the
#             same generation (format below). Producing them is the job of
#             read-only observers; this library NEVER calls route-engine,
#             reconciler, Services, tunnel-guard, policy-sync, ndmc, DNS or AGH
#             and writes nothing but stdout. It is a pure function of 3 files.
#
# LEGACY, TSV, no comments/blank lines, ONE line `generation<TAB>GEN` and rows
#   MECH DOMAIN CONFIGURED DESIRED DNS OWNERSHIP ACTION BASIS   (8 fields)
#   MECH: route-engine|route-reconciler|services|tunnel-guard|policy-sync
#   DOMAIN: normalized FQDN, or `-` (tunnel-guard: interface level)
#   CONFIGURED/DESIRED: ISP | VPN:IFACE | none | unknown | - (no opinion)
#   DNS: opaque policy id | unknown | -      OWNERSHIP: vward|manual|unknown|-
#   ACTION: none|observe|skip|add|remove|switch|restore
#   BASIS: native-config|catalog-pin|persist|state|manual-list|guard-fallback|cidr-plan|none
# Every field is a closed token or a safe identifier: free text (and with it any
# secret/URL/token) cannot pass.
#
# OUTPUT, one row per observation, sorted, TSV:
#   DOMAIN MECH VERDICT CLASS SEVERITY CONFIDENCE SOURCES IDS CONFIGURED DESIRED
#   DNS OWNERSHIP ACTION REASON
# VERDICT match|diverge|unknown|not-comparable; SEVERITY info|review. A difference
# is not an error by itself: guard fallbacks, VPN state, and the purpose of each
# mechanism are applied first (see docs/RS6_IDENTITY_SNAPSHOT_SHADOW.md).
# rc 0 ok; rc 2 invalid input or limit breach (no stdout); rc 3 generations
# disagree = the three files are not one input set -> stdout `unknown<TAB>REASON`.
# Limits: 4096 lines / 1 MiB per input, 4096 output rows / 1 MiB, no partial output.
vward_routing_shadow() (
    [ "$#" -eq 4 ] || { printf '%s\n' 'routing shadow: expected GENERATION AUDIT IDENTITY LEGACY' >&2; return 2; }
    vrh_gen=$1
    printf '%s\n' "$vrh_gen" | grep -Eq '^g-[0-9a-f]{16}$' || { printf '%s\n' 'routing shadow: generation must be g-<16 hex>' >&2; return 2; }
    shift
    for vrh_f in "$@"; do
        case $vrh_f in /*) ;; *) printf '%s\n' 'routing shadow: absolute file paths required' >&2; return 2 ;; esac
        if [ -L "$vrh_f" ] || [ ! -f "$vrh_f" ] || [ ! -r "$vrh_f" ]; then
            printf '%s\n' 'routing shadow: regular readable files required' >&2; return 2
        fi
    done
    [ "$1" != "$2" ] && [ "$1" != "$3" ] && [ "$2" != "$3" ] || { printf '%s\n' 'routing shadow: distinct files required' >&2; return 2; }
    LC_ALL=C awk -v gen="$vrh_gen" '
    BEGIN { FS=OFS="\t" }
    function id(s) { return length(s)<=64 && s ~ /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/ }
    function domain(s, n,a,i) {
        if (length(s)>253 || s !~ /^[a-z0-9.-]+$/) return 0
        n=split(s,a,"."); if(n<2) return 0
        for(i=1;i<=n;i++) if(length(a[i])<1 || length(a[i])>63 || a[i] !~ /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/) return 0
        return 1
    }
    function target(s) { return s=="ISP" || (s ~ /^VPN:/ && id(substr(s,5))) }
    function ltarget(s) { return target(s) || s=="none" || s=="unknown" || s=="-" }
    function sources(s, n,a,i,r) { n=split(s,a,","); r=""; for(i=1;i<=n;i++) if(a[i] ~ /^[MSA]:/) { if(index(r,substr(a[i],1,1))==0) r=r substr(a[i],1,1) }; return r }
    function join(arr, k,out,n,i,keys) {
        n=0; for(k in arr) keys[++n]=k
        sortarr(keys,n)
        out=""; for(i=1;i<=n;i++) out=out (out==""?"":",") keys[i]
        for(k in keys) delete keys[k]
        return out==""?"-":out
    }
    function sortarr(a,n, width,left,mid,right,i,j,pos,tmp) {
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
        if(NF!=12 || !domain($1) || $8 !~ /^(unknown|unresolved|inactive|blocked|covered|review)$/ || $12!="unknown") { invalid=1; next }
        if($1 in a_line) { invalid=1; next }
        if($11!=gen) { gen_mismatch=1 }
        a_line[$1]=$0; a_n++
        next
    }
    FILENAME==ARGV[2] {
        if(NF!=9 || !id($1) || $2!~/^(route|intent)$/ || $8!~/^(verified|reference-only|unknown)$/ || $9!="reference") { invalid=1; next }
        ident[$1]=$8; next
    }
    FILENAME==ARGV[3] {
        if($1=="generation") {
            if(NF!=2 || lgen_seen++) invalid=1; else { if($2!=gen) gen_mismatch=1 }
            next
        }
        if(NF!=8 || $1!~/^(route-engine|route-reconciler|services|tunnel-guard|policy-sync)$/ ||
           !($2=="-" ? $1=="tunnel-guard" : domain($2)) || ($1=="tunnel-guard" && $2!="-") ||
           !ltarget($3) || !ltarget($4) || !($5=="-" || $5=="unknown" || id($5)) ||
           $6!~/^(vward|manual|unknown|-)$/ || $7!~/^(none|observe|skip|add|remove|switch|restore)$/ ||
           $8!~/^(native-config|catalog-pin|persist|state|manual-list|guard-fallback|cidr-plan|none)$/) { invalid=1; next }
        ln++; l_mech[ln]=$1; l_dom[ln]=$2; l_conf[ln]=$3; l_des[ln]=$4; l_dns[ln]=$5; l_own[ln]=$6; l_act[ln]=$7; l_basis[ln]=$8
        next
    }
    function emit(dom,mech,verdict,class,sev,conf,srcs,ids,cfg,des,dns,own,act,reason, line) {
        line=dom OFS mech OFS verdict OFS class OFS sev OFS conf OFS srcs OFS ids OFS cfg OFS des OFS dns OFS own OFS act OFS reason
        out_n++; out_bytes+=length(line)+1
        if(out_n>4096 || out_bytes>1048576) invalid=1
        else outl[out_n]=line
    }
    # Facts of one RS audit row (never mutated).
    function rs_load(dom, f,n,a,i,b,m) {
        for(i in wt) delete wt[i]; for(i in wdns) delete wdns[i]; for(i in wpath) delete wpath[i]
        for(i in ct) delete ct[i]; for(i in act_src) delete act_src[i]
        split(a_line[dom],f,"\t")
        rs_decision=f[8]; rs_issues=f[10]; rs_active=f[3]; rs_sources=f[2]; rs_rights=f[6]
        if(f[4]!="-") { n=split(f[4],a,","); for(i=1;i<=n;i++) { split(a[i],b,"@"); wt[b[2]]=1; wdns[b[3]]=1; wpath[b[2] "@" b[3]]=1 } }
        if(f[5]!="-") { n=split(f[5],a,","); for(i=1;i<=n;i++) { split(a[i],b,"@"); ct[b[3]]=1 } }
        if(rs_active!="-") { n=split(rs_active,a,","); for(i=1;i<=n;i++) { split(a[i],b,":"); act_src[b[1]]=1 } }
        rs_ident="reference-only"; rs_have_ident=0
        # Worst identity state among ACTIVE refs (unknown > reference-only > verified).
        if(rs_active!="-") { n=split(rs_active,a,","); w="verified"
            for(i=1;i<=n;i++) { m=a[i]; sub(/^[MSA]:/,"",m); st=(m in ident)?ident[m]:"unknown"
                if(st=="unknown") w="unknown"; else if(st=="reference-only" && w!="unknown") w="reference-only" }
            rs_ident=w }
        else rs_ident="unknown"
    }
    function count(arr, k,n) { n=0; for(k in arr) n++; return n }
    function relevant_unknown(letters, i,t) {
        if(index(rs_issues,"snapshot:unknown")) return 1
        for(i=1;i<=length(letters);i++) if(index(rs_issues,"source:" substr(letters,i,1) ":unknown")) return 1
        return 0
    }
    function mech_letters(m) { return m=="route-engine"?"M":m=="route-reconciler"?"A":m=="services"?"S":"MSA" }
    END {
        if(!lgen_seen) invalid=1
        if(invalid) { print "routing shadow: invalid input or limit exceeded" > "/dev/stderr"; exit 2 }
        if(gen_mismatch) { print "unknown\tgeneration-mismatch"; exit 3 }
        for(r=1;r<=ln;r++) {
            mech=l_mech[r]; dom=l_dom[r]; lc=l_conf[r]; ld=l_des[r]; ldn=l_dns[r]; lo=l_own[r]; la=l_act[r]; lb=l_basis[r]
            if(dom=="-") {
                # tunnel-guard owns tunnel quality/fallback; RS6 has no health evidence yet.
                if(lc=="unknown" || ld=="unknown") emit("-",mech,"unknown","legacy-unknown","info","low","-","-","legacy=" lc,"legacy=" ld,"-","-","rs=observe-only|legacy=" la,"legacy-state-unknown")
                else if(ld==lc || ld=="none") emit("-",mech,"match","guard-stable","info","medium","-","-","legacy=" lc,"legacy=" ld,"-","-","rs=observe-only|legacy=" la,"no-switch-proposed")
                else emit("-",mech,"diverge","guard-owned-switch","info","low","-","-","legacy=" lc,"legacy=" ld,"-","-","rs=observe-only|legacy=" la,"rs-health-unknown")
                continue
            }
            if(!(dom in a_line)) {
                emit(dom,mech,"diverge","legacy-only-domain","review","medium","-","-","rs=-|legacy=" lc,"rs=-|legacy=" ld,"rs=-|legacy=" ldn,"identity=unknown|legacy=" lo,"rs=observe-only|legacy=" la,"domain-missing-in-rs")
                continue
            }
            rs_load(dom)
            L=mech_letters(mech)
            srcs=(rs_active=="-")?"-":""; if(rs_active!="-") { for(k=1;k<=length("MSA");k++) { s=substr("MSA",k,1); if(s in act_src) srcs=srcs (srcs==""?"":",") s } }
            ids=rs_sources
            wlist=join(wt); clist=join(ct); dlist=join(wdns)
            cfg="rs=" clist "|legacy=" lc; des="rs=" wlist "|legacy=" ld; dns="rs=" dlist "|legacy=" ldn
            own="identity=" rs_ident "|legacy=" lo; act="rs=observe-only|legacy=" la
            conf=(rs_issues=="-") ? "high" : "medium"
            # Route facts come from the native config (source M): when it is unknown no
            # mechanism can be compared on configured routes, whatever its own source.
            if(relevant_unknown(L "M")) { emit(dom,mech,"unknown","rs-unknown","info","low",srcs,ids,cfg,des,dns,own,act,"snapshot-or-source-unknown"); continue }
            if(lc=="unknown" || ld=="unknown") { emit(dom,mech,"unknown","legacy-unknown","info","low",srcs,ids,cfg,des,dns,own,act,"legacy-state-unknown"); continue }
            if(mech!="policy-sync") {
                hit=0; for(k=1;k<=length(L);k++) if(substr(L,k,1) in act_src) hit=1
                if(!hit) {
                    if(ld=="none" || ld=="-" || la=="observe" || la=="skip" || la=="none") emit(dom,mech,"match","observe-agrees","info",conf,srcs,ids,cfg,des,dns,own,act,"rs-inactive-legacy-observes")
                    else emit(dom,mech,"not-comparable","source-inactive","info",conf,srcs,ids,cfg,des,dns,own,act,"rs-source-inactive-legacy-acts")
                    continue
                }
            }
            nt=count(wpath)
            cnt=count(ct)
            # Conflicts that RS keeps explicit but a legacy mechanism may settle silently.
            if(rs_decision=="unresolved") { emit(dom,mech,"diverge","rs-conflict-legacy-picks","review",conf,srcs,ids,cfg,des,dns,own,act,"rs-keeps-conflict"); continue }
            cls="match"; sev="info"; reason="agree"
            if(mech!="policy-sync" && ld!="none" && ld!="-") {
                if(nt==0) { cls="rs-no-intent"; sev="review"; reason="legacy-wants-rs-has-none" }
                else if(!(ld in wt)) {
                    if(lb=="guard-fallback" && (index(rs_issues,"VPN:") || ld=="ISP")) { cls="expected-guard"; reason="guard-fallback-vs-vpn-state" }
                    else { cls="target-mismatch"; sev="review"; reason="desired-targets-differ" }
                }
            }
            if(cls=="match" && lc!="none" && lc!="-" && cnt>0 && !(lc in ct)) { cls="configured-mismatch"; sev="review"; reason="configured-targets-differ" }
            if(cls=="match" && lc!="none" && lc!="-" && cnt==0) { cls="configured-mismatch"; sev="review"; reason="legacy-sees-route-rs-none" }
            if(cls=="match" && lc=="none" && cnt>0) { cls="configured-mismatch"; sev="review"; reason="rs-sees-route-legacy-none" }
            if(cls=="match" && mech!="policy-sync" && ld!="none" && ld!="-" && ldn!="-" && ldn!="unknown" && !(ldn in wdns)) { cls="dns-mismatch"; sev="review"; reason="dns-policy-differs" }
            if(cls=="match" && (la=="add" || la=="remove" || la=="switch" || la=="restore")) reason="agree-rs-observe-only"
            if(cls=="match" && lo=="vward" && rs_ident!="verified") reason=reason "-ownership-unproven"
            emit(dom,mech,(cls=="match")?"match":"diverge",cls,sev,conf,srcs,ids,cfg,des,dns,own,act,reason)
        }
        if(invalid) { print "routing shadow: output limit exceeded" > "/dev/stderr"; exit 2 }
        sortarr(outl,out_n)
        for(r=1;r<=out_n;r++) print outl[r]
    }' "$@"
)
