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
