#!/bin/sh

# RS-5 normalized, read-only evaluator. Source loading defines this function only.
# Contract: docs/ROUTING_AUDIT_CONTRACT.md. There are no live inventory adapters.
vward_routing_audit() (
    if [ "$#" -ne 2 ]; then
        printf '%s\n' 'routing audit: expected INTENTS SNAPSHOT' >&2
        return 2
    fi
    # Absolute paths prevent awk treating a filename as an option/assignment/stdin.
    case $1 in /*) vra_intents=$1 ;; *) vra_intents=$PWD/$1 ;; esac
    case $2 in /*) vra_snapshot=$2 ;; *) vra_snapshot=$PWD/$2 ;; esac
    if [ "$vra_intents" = "$vra_snapshot" ] ||
        [ ! -f "$vra_intents" ] || [ ! -r "$vra_intents" ] ||
        [ ! -f "$vra_snapshot" ] || [ ! -r "$vra_snapshot" ]; then
        printf '%s\n' 'routing audit: two distinct readable regular files required' >&2
        return 2
    fi
    LC_ALL=C awk '
    BEGIN { FS="\t"; OFS="\t" }
    function bad() { invalid=1 }
    function id(s) { return length(s)<=64 && s ~ /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/ }
    function domain(s, n,a,i) {
        if (length(s)>253 || s !~ /^[a-z0-9.-]+$/) return 0
        n=split(s,a,".")
        if(n<2) return 0
        for(i=1;i<=n;i++)
            if(length(a[i])<1 || length(a[i])>63 || a[i] !~ /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/) return 0
        return 1
    }
    function scope(s) { return s=="exact" || s=="subtree" }
    function target(s) { return s=="ISP" || (s ~ /^VPN:/ && id(substr(s,5))) }
    function health(s) { return s=="available" || s=="unavailable" || s=="unknown" }
    function known(s) { return s=="known" || s=="unknown" }
    function source(s) { return s=="M" || s=="S" || s=="A" }
    function adddomain(s) {
        if(!(s in domains)) { domains[s]=1; domain_count++ }
        if(domain_count>1024) bad()
    }
    function covers(parent,sc,child) {
        return parent==child || (sc=="subtree" && length(child)>length(parent) &&
            substr(child,length(child)-length(parent))=="." parent)
    }
    # Sort each universe once with POSIX awk merge sort, then emit subsets by
    # walking that stable order. Repeated evidence never triggers per-row sort.
    function sortkeys(a,out, n,k,width,left,mid,right,i,j,pos,tmp) {
        n=0
        for(k in a) out[++n]=k
        for(width=1;width<n;width*=2) {
            for(left=1;left<=n;left+=2*width) {
                mid=left+width; right=left+2*width
                if(mid>n+1) mid=n+1
                if(right>n+1) right=n+1
                i=left; j=mid
                for(pos=left;pos<right;pos++) {
                    if(i<mid && (j>=right || "x" out[i]<= "x" out[j])) tmp[pos]=out[i++]
                    else tmp[pos]=out[j++]
                }
            }
            for(pos=1;pos<=n;pos++) out[pos]=tmp[pos]
        }
        return n
    }
    function subset(order,n,present, out,i,k) {
        out=""
        for(i=1;i<=n;i++) {
            k=order[i]
            if(k in present) out=out (out=="" ? "" : ",") k
        }
        return out=="" ? "-" : out
    }
    {
        bytes[FILENAME]+=length($0)+1
        if(FNR>4096 || bytes[FILENAME]>1048576) { bad(); next }
    }
    FILENAME==ARGV[1] {
        if(NF!=7 || !source($1) || !id($2) || !domain($3) || !scope($4) || !target($5) || !id($6) || $7 !~ /^[01]$/) { bad(); next }
        key=$1 ":" $2
        if(key in intent_line) { if(intent_line[key]!=$0) bad(); next }
        intent_line[key]=$0; isource[key]=$1; idomain[key]=$3; iscope[key]=$4
        itarget[key]=$5; idns[key]=$6; iselected[key]=$7
        adddomain($3)
        next
    }
    FILENAME==ARGV[2] {
        if($1=="snapshot") {
            if(NF!=3 || !id($2) || !known($3) || snapshot_count++) bad()
            generation=$2; snapshot_state=$3
        } else if($1=="source") {
            if(NF!=4 || !source($2) || $3 !~ /^[01]$/ || !known($4) || ($2 in toggle)) bad()
            toggle[$2]=$3; source_state[$2]=$4
        } else if($1=="health") {
            if(NF!=3 || !($2=="DNS" || $2=="AGH" || ($2 ~ /^VPN:/ && target($2))) || !health($3) || ($2 in hstate)) bad()
            hstate[$2]=$3
        } else if($1=="route") {
            if(NF!=8 || !id($2) || !domain($3) || !scope($4) || !target($5) || !id($6) ||
                $7 !~ /^(vward|manual|unknown)$/ || $8 !~ /^(managed|reference)$/ || ($8=="managed" && $7!="vward")) { bad(); next }
            key=$2
            if(key in route_line) { if(route_line[key]!=$0) bad(); next }
            route_line[key]=$0; rdomain[key]=$3; rscope[key]=$4; rtarget[key]=$5
            rdns[key]=$6; rowner[key]=$7; rpermission[key]=$8
            adddomain($3)
        } else bad()
        next
    }
    END {
        if(snapshot_count!=1 || !("M" in toggle) || !("S" in toggle) || !("A" in toggle) || !("DNS" in hstate) || !("AGH" in hstate)) bad()
        if(invalid) { print "routing audit: invalid normalized input" > "/dev/stderr"; exit 2 }
        unknown_snapshot=(snapshot_state=="unknown")
        for(k in toggle) if(toggle[k]==1 && source_state[k]=="unknown") unknown_snapshot=1
        if(domain_count==0) exit 0
        n=sortkeys(domains,order)
        ni=sortkeys(intent_line,intent_order)
        for(k in intent_line) {
            all_wanted[iscope[k] "@" itarget[k] "@" idns[k]]=1
            if(itarget[k] ~ /^VPN:/) {
                hs=(itarget[k] in hstate) ? hstate[itarget[k]] : "unknown"
                if(hs!="available") all_issues[itarget[k] ":" hs]=1
            }
        }
        for(r in route_line) {
            all_configured[r "@" rscope[r] "@" rtarget[r] "@" rdns[r]]=1
            all_rights[r "@" rowner[r] "@" rpermission[r]]=1
        }
        if(snapshot_state=="unknown") all_issues["snapshot:unknown"]=1
        for(k in toggle) if(toggle[k]==1 && source_state[k]=="unknown") all_issues["source:" k ":unknown"]=1
        if(hstate["DNS"]!="available") all_issues["DNS:" hstate["DNS"]]=1
        if(hstate["AGH"]!="available") all_issues["AGH:" hstate["AGH"]]=1
        nw=sortkeys(all_wanted,wanted_order)
        nc=sortkeys(all_configured,configured_order)
        nr=sortkeys(all_rights,rights_order)
        nh=sortkeys(all_issues,issues_order)
        for(di=1;di<=n;di++) {
            d=order[di]
            for(k in issues) delete issues[k]
            if(snapshot_state=="unknown") issues["snapshot:unknown"]=1
            for(k in toggle) if(toggle[k]==1 && source_state[k]=="unknown") issues["source:" k ":unknown"]=1
            for(k in refs) delete refs[k]
            for(k in active) delete active[k]
            for(k in wanted) delete wanted[k]
            for(k in configured) delete configured[k]
            for(k in rights) delete rights[k]
            for(k in paths) delete paths[k]
            for(k in route_coverage) delete route_coverage[k]
            duplicates=0; active_count=0; path_count=0; covered_count=0
            unavailable=0; unknown_health=0
            # One route scan supplies both evidence and scope-aware lookups.
            for(r in route_line) if(covers(rdomain[r],rscope[r],d)) {
                configured[r "@" rscope[r] "@" rtarget[r] "@" rdns[r]]=1
                rights[r "@" rowner[r] "@" rpermission[r]]=1
                p=rtarget[r] "@" rdns[r]
                route_coverage[p SUBSEP "exact"]=1
                if(rscope[r]=="subtree") route_coverage[p SUBSEP "subtree"]=1
                if(!(p in paths)) { paths[p]=1; path_count++ }
            }
            for(k in intent_line) {
                if(idomain[k]==d) refs[k]=1
                if(!covers(idomain[k],iscope[k],d) || iselected[k]!=1 || toggle[isource[k]]!=1) continue
                active[k]=1; active_count++
                sig=iscope[k] "@" itarget[k] "@" idns[k]
                if(sig in wanted) duplicates++; else wanted[sig]=1
                p=itarget[k] "@" idns[k]
                if(!(p in paths)) { paths[p]=1; path_count++ }
                if(itarget[k] ~ /^VPN:/) {
                    hs=(itarget[k] in hstate) ? hstate[itarget[k]] : "unknown"
                    if(hs!="available") issues[itarget[k] ":" hs]=1
                    if(hs=="unavailable") unavailable=1
                    if(hs=="unknown") unknown_health=1
                }
                if((p SUBSEP iscope[k]) in route_coverage) covered_count++
            }
            if(active_count) {
                if(hstate["DNS"]!="available") issues["DNS:" hstate["DNS"]]=1
                if(hstate["AGH"]!="available") issues["AGH:" hstate["AGH"]]=1
                if(hstate["DNS"]=="unavailable" || hstate["AGH"]=="unavailable") unavailable=1
                if(hstate["DNS"]=="unknown" || hstate["AGH"]=="unknown") unknown_health=1
            }
            if(path_count>1) { decision="unresolved"; reason="conflicting-target-or-dns" }
            else if(unknown_snapshot) { decision="unknown"; reason="snapshot-or-source-unknown" }
            else if(!active_count) { decision="inactive"; reason="no-active-intent" }
            else if(unavailable) { decision="blocked"; reason="dependency-unavailable" }
            else if(unknown_health) { decision="unknown"; reason="dependency-unknown" }
            else if(covered_count==active_count) { decision="covered"; reason="reuse-existing-coverage" }
            else { decision="review"; reason="new-coverage-needed" }
            print d,subset(intent_order,ni,refs),subset(intent_order,ni,active),subset(wanted_order,nw,wanted),subset(configured_order,nc,configured),subset(rights_order,nr,rights),duplicates,decision,reason,subset(issues_order,nh,issues),generation,"unknown"
        }
    }' "$vra_intents" "$vra_snapshot"
)

# B proposal, intent-only: canonical service choice, not a writer or permission.
# vward_routing_choice LEDGER SID ACTION TARGET DNS EXPECTED_REV
# No installed-state path, clock, checksum command, transport, lock or write.
# rc 2 invalid input; rc 3 stale input revision. Both emit no partial stdout.
vward_routing_choice() (
    [ "$#" -eq 6 ] || { printf '%s\n' 'routing choice: expected LEDGER SID ACTION TARGET DNS EXPECTED_REV' >&2; return 2; }
    case $1 in /*) ;; *) printf '%s\n' 'routing choice: absolute ledger required' >&2; return 2 ;; esac
    [ -f "$1" ] && [ -r "$1" ] && [ ! -L "$1" ] || { printf '%s\n' 'routing choice: readable regular ledger required' >&2; return 2; }
    LC_ALL=C awk -v sid="$2" -v action="$3" -v target="$4" -v dns="$5" -v expected="$6" '
    BEGIN {FS=OFS="\t"}
    function service(s) {return length(s)<=63 && s ~ /^[a-z0-9][a-z0-9.@_-]*$/}
    function id(s) {return length(s)<=64 && s ~ /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/}
    function revision(s) {return s ~ /^[0-9]+$/ && s+0<=2147483647}
    function valid(mode,t,d) {
        if(mode=="auto") return t=="-" && d=="-"
        if(mode=="vpn") return t ~ /^VPN:/ && id(substr(t,5)) && d=="default"
        if(mode=="dns") return t=="ISP" && id(d) && d!="default"
        return mode=="isp" && t=="ISP" && d=="default"
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
    {
        bytes+=length($0)+1
        if(FNR>4096 || bytes>1048576) {bad=1;next}
        if(FNR==1 && NF==2 && $1=="schema" && $2=="1") {header=1;next}
        if(NF!=7 || $1!="service" || !service($2) || !revision($3) ||
           !valid($4,$5,$6) || !revision($7) || $7+0>$3+0 || ($2 in mode)) {bad=1;next}
        key=$2; rev[key]=$3+0;mode[key]=$4;tgt[key]=$5;policy[key]=$6;floor[key]=$7+0
        keys[++n]=key
    }
    END {
        proposed=(action=="on") ? "vpn" : action
        if(!header || !service(sid) || !revision(expected) || n>1024 ||
           (action!="off" && !valid(proposed,target,dns)) ||
           (action=="off" && (target!="-" || dns!="-"))) bad=1
        if(bad) {print "routing choice: invalid input or limit exceeded" > "/dev/stderr";exit 2}
        oldrev=(sid in mode) ? rev[sid] : 0
        if(oldrev!=expected+0) {print "routing choice: stale-revision" > "/dev/stderr";exit 3}
        oldmode=(sid in mode) ? mode[sid] : "auto"
        oldtarget=(sid in mode) ? tgt[sid] : "-"
        olddns=(sid in mode) ? policy[sid] : "-"
        if(action=="off") {
            proposed=(oldmode=="vpn") ? "auto" : oldmode
            target=(oldmode=="vpn") ? "-" : oldtarget
            dns=(oldmode=="vpn") ? "-" : olddns
        }
        changed=(proposed!=oldmode || target!=oldtarget || dns!=olddns)
        if(changed) {
            if(oldrev==2147483647 || (!(sid in mode) && n==1024)) {
                print "routing choice: revision or service limit" > "/dev/stderr";exit 2
            }
            if(!(sid in mode)) keys[++n]=sid
            rev[sid]=oldrev+1;mode[sid]=proposed;tgt[sid]=target;policy[sid]=dns
            if(!(sid in floor)) floor[sid]=0
            if((oldmode=="dns" || oldmode=="isp") && (proposed=="auto" || proposed=="vpn")) floor[sid]=rev[sid]
        }
        sort(keys,n)
        print "schema",1
        for(i=1;i<=n;i++) {k=keys[i];print "service",k,rev[k],mode[k],tgt[k],policy[k],floor[k]}
    }' "$1"
)

# Intent-only projection for ONE prevalidated domain/scope atom. No area inference,
# health verdict, physical deletion, ownership, permission or packet-path proof.
# vward_routing_service_policy MODE TARGET DNS REV AUTO_FLOOR EVIDENCE
vward_routing_service_policy() (
    [ "$#" -eq 6 ] || { printf '%s\n' 'routing policy: expected MODE TARGET DNS REV FLOOR EVIDENCE' >&2; return 2; }
    case $6 in /*) ;; *) printf '%s\n' 'routing policy: absolute evidence required' >&2; return 2 ;; esac
    [ -f "$6" ] && [ -r "$6" ] && [ ! -L "$6" ] || { printf '%s\n' 'routing policy: readable regular evidence required' >&2; return 2; }
    LC_ALL=C awk -v mode="$1" -v target="$2" -v dns="$3" -v rev="$4" -v floor="$5" '
    BEGIN {FS=OFS="\t"}
    function id(s) {return length(s)<=64 && s ~ /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/}
    function revision(s) {return s ~ /^[0-9]+$/ && s+0<=2147483647}
    function route(t,d) {return (t=="ISP" || (t ~ /^VPN:/ && id(substr(t,5)))) && id(d)}
    function add(key,src,ref,t,d,state,reason) {
        rows[key]="contribution" OFS src OFS ref OFS t OFS d OFS state OFS reason
        keys[++n]=key
        if(state=="active") {pairs[t SUBSEP d]=1;active=1}
        if(state=="unknown") uncertain=1
    }
    {
        bytes+=length($0)+1
        if(FNR>4096 || bytes>1048576) {bad=1;next}
        if(FNR==1 && NF==2 && $1=="schema" && $2=="1") {header=1;next}
        k=$1 ":" $2
        if(NF!=8 || $1 !~ /^[MSA]$/ || !id($2) || !route($3,$4) || $5 !~ /^[01]$/ ||
           !revision($7) || $7+0>rev+0 || k in seen || ($1=="S" && $2=="choice")) {bad=1;next}
        seen[k]=1
        if($1=="A") {
            if($6 !~ /^(active|positive|history|unknown)$/ || $8 !~ /^(bound|excluded|unknown)$/) {bad=1;next}
            state="inactive";reason="history"
            if($5==0) reason="not-selected"
            else if($8=="excluded") reason="outside-service-scope"
            else if($8=="unknown" || $6=="unknown") {state="unknown";reason="evidence-unknown"}
            else if($6!="history") {
                if(($6=="positive" && $7+0!=rev+0) || $7+0<floor+0) reason="stale-auto-evidence"
                else if(mode=="dns" || mode=="isp" || (mode=="vpn" && ($3!=target || $4!=dns))) {
                    state="suppressed";reason="explicit-pin"
                } else {state="active";reason="auto-evidence"}
            }
        } else {
            if($6!="explicit" || $7+0!=0 || $8!="peer") {bad=1;next}
            state=($5==1) ? "active" : "inactive";reason=($5==1) ? "peer-explicit" : "not-selected"
        }
        add(k,$1,$2,$3,$4,state,reason)
    }
    END {
        valid=(mode=="auto" && target=="-" && dns=="-") ||
              (mode=="vpn" && target ~ /^VPN:/ && id(substr(target,5)) && dns=="default") ||
              (mode=="dns" && target=="ISP" && id(dns) && dns!="default") ||
              (mode=="isp" && target=="ISP" && dns=="default")
        if(!header || !valid || !revision(rev) || !revision(floor) || floor+0>rev+0 || n>1024 || bad) {
            print "routing policy: invalid input or limit exceeded" > "/dev/stderr";exit 2
        }
        if(mode!="auto") add("S:choice","S","choice",target,dns,"active","desired-explicit")
        for(k in pairs) count++
        verdict=(count>1) ? "unresolved" : (uncertain ? "unknown" : (active ? "desired" : "inactive"))
        print "policy",1,verdict,"denied","unknown"
        # Bounded keys, merge sort; no external sort or platform utilities.
        for(width=1;width<n;width*=2) {
            for(left=1;left<=n;left+=2*width) {
                mid=left+width;right=left+2*width
                if(mid>n+1) mid=n+1
                if(right>n+1) right=n+1
                i=left;j=mid
                for(k=left;k<right;k++)
                    if(i<mid && (j>=right || "x" keys[i]<="x" keys[j])) tmp[k]=keys[i++]
                    else tmp[k]=keys[j++]
            }
            for(k=1;k<=n;k++) keys[k]=tmp[k]
        }
        for(i=1;i<=n;i++) print rows[keys[i]]
    }' "$6"
)
