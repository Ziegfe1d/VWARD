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
