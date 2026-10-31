#!/bin/sh
# RS-6 stage 3: read-only observers of the five existing routing mechanisms.
# Defines ONE function; loading does nothing and changes no caller variable.
#
#   vward_routing_observe STAGE PROJDIR GENERATION NOW
#
# STAGE   directory of verified COPIES written by vward_routing_consistent_read
#         (files named by label, plus STATE: "label<TAB>ok|absent|bad|oversize").
# PROJDIR the intents.tsv / snapshot.tsv / identity.tsv of the same snapshot.
# NOW     epoch seconds fixed once by the coordinator (no clock reads here).
# stdout  LEGACY file for vward_routing_shadow: `generation<TAB>GEN` + rows
#         `MECH DOMAIN CONFIGURED DESIRED DNS OWNERSHIP ACTION BASIS`.
# rc 0 ok; rc 2 invalid usage or a limit breach (no stdout).
#
# NOTHING here runs a route-engine/reconciler/Services/tunnel-guard/policy-sync
# script, ndmc, curl, DNS or AGH: the decision logic of each mechanism is read
# from its own files and applied exactly as that mechanism applies it. Parity
# with the real functions is proved by tests/routing-readers/check-observe.py.
# A mechanism whose input is missing/unreadable/invalid yields ONE mechanism-level
# row `MECH - unknown unknown - - none none`, never silence and never a match.
# Rows are limited to domains that the RS snapshot knows. Live probes (ISP vs VPN),
# tunnel health on the device and the packet path are NOT observable here: they stay
# `unknown`. Limits: 4096 lines / 1 MiB per input, 4096 rows, 1024 domains.
vward_routing_observe() (
    [ "$#" -eq 4 ] || return 2
    VRO_STAGE=$1 VRO_PROJ=$2 VRO_GEN=$3 VRO_NOW=$4
    for vro_d in "$VRO_STAGE" "$VRO_PROJ"; do
        case $vro_d in /*) ;; *) return 2 ;; esac
        [ -d "$vro_d" ] && [ ! -L "$vro_d" ] || return 2
    done
    printf '%s\n' "$VRO_GEN" | grep -Eq '^g-[0-9a-f]{16}$' || return 2
    case $VRO_NOW in ''|*[!0-9]*) return 2 ;; esac
    export VRO_STAGE VRO_PROJ VRO_GEN VRO_NOW
    # Catalog: same preference and shape check as the reader (fetched, then bundled).
    vro_cat=
    for vro_c in catalog-fetched catalog-bundled; do
        [ -f "$VRO_STAGE/$vro_c" ] && [ ! -L "$VRO_STAGE/$vro_c" ] || continue
        vro_cat=$("${JQ:-jq}" -er '
            if .schema == 1 and (.services | type) == "array" and (.services | length) > 0 and
                all(.services[]; (.id | type) == "string" and (.category | type) == "string" and
                    (.domains | type) == "array" and (.domains | length) > 0 and
                    all(.domains[]; type == "string"))
            then .services[] | . as $s | .domains[] | [$s.id,$s.category,.] | @tsv
            else error("catalog") end' "$VRO_STAGE/$vro_c" 2>/dev/null) && break
        vro_cat=
    done
    {
        if [ -n "$vro_cat" ]; then printf '%s\n' "$vro_cat" | awk 'NF {print "catalog\t" $0}'; else printf 'nocatalog\t1\n'; fi
        if [ -f "$VRO_STAGE/STATE" ] && [ ! -L "$VRO_STAGE/STATE" ]; then awk -F'\t' 'NF==2 {print "state\t" $1 "\t" $2}' "$VRO_STAGE/STATE"; fi
    } | LC_ALL=C awk '
    BEGIN { FS=OFS="\t"; stage=ENVIRON["VRO_STAGE"]; proj=ENVIRON["VRO_PROJ"]; gen=ENVIRON["VRO_GEN"]; now=ENVIRON["VRO_NOW"]+0 }
    function id(s) {return length(s)<=64 && s ~ /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/}
    function domain(s, n,a,i) {
        if(length(s)>253 || s !~ /^[a-z0-9.-]+$/) return 0
        n=split(s,a,"."); if(n<2) return 0
        for(i=1;i<=n;i++) if(length(a[i])<1 || length(a[i])>63 || a[i] !~ /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/) return 0
        return 1
    }
    function under(h,d) { return h==d || (length(h)>length(d) && substr(h,length(h)-length(d))=="." d) }
    function strict_under(h,d) { return length(h)>length(d) && substr(h,length(h)-length(d))=="." d }
    # Read one staged file. Returns the line count; sets rstate to ok|absent|bad.
    function rd(label, arr, n,l,b,rc,path) {
        n=0; b=0; rstate="ok"
        if(label in st && st[label]=="absent") {rstate="absent"; return 0}
        if(!(label in st) || st[label]!="ok") {rstate="bad"; return 0}
        path=stage "/" label
        while((rc=(getline l < path))>0) {
            sub(/\r$/,"",l); n++; b+=length(l)+1
            if(n>4096 || b>1048576) {invalid=1; rstate="bad"; break}
            arr[n]=l
        }
        close(path)
        if(rc<0) rstate="bad"
        return n
    }
    function rdproj(path, arr, n,l,b,rc) {
        n=0; b=0
        while((rc=(getline l < path))>0) {n++; b+=length(l)+1; if(n>4096 || b>1048576) {invalid=1; break}; arr[n]=l}
        close(path)
        if(rc<0) invalid=1
        return n
    }
    # Same target classification as the RS reader (WAN -> ISP, known VPN interface -> VPN:x).
    function target(t) {
        if(t=="ISP" || (devok && t==wan)) return "ISP"
        if(mapok && (t in vpn) && t!=wan) return "VPN:" t
        return ""
    }
    function out(mech,d,conf,des,dns,own,act,basis, line) {
        if(d!="-" && !(d in U)) return
        line=mech OFS d OFS conf OFS des OFS dns OFS own OFS act OFS basis
        if(!(line in seen)) {
            seen[line]=1; nout++; obytes+=length(line)+1
            if(nout>4096 || obytes>1048576) invalid=1; else outl[nout]=line
        }
    }
    function mechunknown(mech) { out(mech,"-","unknown","unknown","-","-","none","none") }
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
    # The mechanisms apply wildcards differently; both are reproduced exactly.
    # route-engine is_manual_known: "*.d" matches only STRICT subdomains of d.
    # reconciler force_vpn_match: "*.d" is reduced to d, so d itself matches too.
    function manual_known(h, k) { if(h in man_exact) return 1; for(k in man_wild) if(strict_under(h,k)) return 1; return 0 }
    function force_match(h, k) { for(k in force) if(under(h,k)) return 1; return 0 }
    $1=="catalog" { if(NF!=4 || !domain(tolower($4))) catbad=1; else {nc++; cid[nc]=$2; ccat[nc]=$3; cdom[nc]=tolower($4)}; next }
    $1=="nocatalog" { catbad=1; next }
    $1=="state" { st[$2]=$3; next }
    END {
        # --- RS universe (domains the snapshot knows) and S-intent identity ---
        n=rdproj(proj "/intents.tsv", pi)
        for(i=1;i<=n;i++) { split(pi[i],f,"\t"); if(domain(f[3])) {U[f[3]]=1; if(f[1]=="S") sref[f[3]]=sref[f[3]] " " f[2]} }
        n=rdproj(proj "/snapshot.tsv", ps)
        for(i=1;i<=n;i++) { split(ps[i],f,"\t"); if(f[1]=="route" && domain(f[3])) U[f[3]]=1 }
        n=rdproj(proj "/identity.tsv", pd)
        for(i=1;i<=n;i++) { split(pd[i],f,"\t"); idst[f[1]]=f[8] }
        for(k in U) nu++
        if(nu>1024) invalid=1
        # --- device profile, interface map, running config ---
        n=rd("dev",a1); devok=(rstate=="ok")
        for(i=1;i<=n;i++) if(a1[i] !~ /^[ \t]*#/ && a1[i]!="") {
            k=a1[i]; sub(/=.*/,"",k); v=substr(a1[i],length(k)+2)
            if(k=="VWARD_TUNNEL_INTERFACE" || k=="VWARD_WAN_INTERFACE") { if(!id(v) || (k in prof)) devok=0; else prof[k]=v }
        }
        tun=prof["VWARD_TUNNEL_INTERFACE"]; wan=prof["VWARD_WAN_INTERFACE"]
        if(tun=="" || wan=="") devok=0
        n=rd("map",a2); mapok=(rstate=="ok")
        for(i=1;i<=n;i++) { m=split(a2[i],f,"\t"); if(f[1]=="I" && m==5 && id(f[2])) { t=tolower(f[3]); if(t ~ /^(wireguard|openvpn|sstp|pptp|l2tp|ike|ipsec|proxy|opkgtun)$/ && f[4]!="-") { vpn[f[2]]=1; dev[f[2]]=f[4] } } }
        vt0=target(tun)
        n=rd("cfg",cl); cfgok=(rstate=="ok"); structure=0
        grp=""; ctx=0
        for(i=1;i<=n && cfgok;i++) {
            l=cl[i]
            if(l ~ /^(interface |dns-proxy$|object-group fqdn )/) structure=1
            if(tolower(l) ~ /(^|[^a-z])(error|failed|invalid|unknown command)([^a-z]|$)/) cfgok=0
            if(l ~ /^!/) {ctx=0; grp=""; continue}
            if(l ~ /^[^ \t!]/) {ctx=(l=="dns-proxy"); grp=""}
            m=split(l,a,/[ \t]+/); if(a[1]=="") {for(k=1;k<m;k++) a[k]=a[k+1]; m--}
            if(a[1]=="object-group" && a[2]=="fqdn" && l ~ /^object-group fqdn /) {
                if(!id(a[3]) || m!=3) {cfgok=0; continue}
                grp=a[3]; if(grp in gdecl) cfgok=0; gdecl[grp]=1; continue
            }
            if(ctx && a[1]=="route" && a[2]=="object-group") {
                if(!id(a[3]) || !id(a[4])) {cfgok=0; continue}
                key=a[3] SUBSEP a[4]
                if(!(key in rseen)) {rseen[key]=1; nrt[a[3]]++; rtg[a[3],nrt[a[3]]]=a[4]}
            }
            if(grp!="" && a[1]=="include") {
                v=tolower(a[2]); if(m!=2 || !domain(v)) {cfgok=0; continue}
                if(!((grp,v) in gmem)) {gmem[grp,v]=1; ndm[grp]++; gdom[grp,ndm[grp]]=v}
            }
        }
        if(!structure) cfgok=0
        # --- route-engine ---
        nm=rd("obs-manual",ma); ms=rstate
        mok=(ms!="bad");
        for(i=1;i<=nm && mok;i++) {
            l=ma[i]; if(l=="") continue
            if(l ~ /^\*\./) { d=substr(l,3); if(domain(d)) man_wild[d]=1; else mok=0 }
            else if(domain(l)) man_exact[l]=1
            else mok=0
        }
        na=rd("obs-adaptive",aa); as=rstate
        nps=rd("persist",pp); ps_=rstate
        if(ms=="bad" || !mok || as=="bad" || ps_=="bad") mechunknown("route-engine")
        else {
            for(d in U) if(manual_known(d)) out("route-engine",d,"-","none","-","manual","skip","manual-list")
            if(!cfgok || !devok) { if(na>0 || nps>0) mechunknown("route-engine") }
            else {
                aat=""; aan=nrt["AdaptiveAuto"]
                if(aan==1) aat=target(rtg["AdaptiveAuto",1]); else if(aan==0) aat="none"
                for(j=1;j<=ndm["AdaptiveAuto"];j++) inaa[gdom["AdaptiveAuto",j]]=1
                for(i=1;i<=na;i++) { d=tolower(aa[i]); if(domain(d)) radapt[d]=1 }
                for(i=1;i<=nps;i++) { d=tolower(pp[i]); if(domain(d)) radapt[d]=1 }
                for(d in radapt) {
                    if(manual_known(d)) continue
                    conf=(d in inaa) ? aat : "none"; if(conf=="") conf="unknown"
                    des=(vt0=="") ? "unknown" : vt0
                    out("route-engine",d,conf,des,"-","vward",(d in inaa) ? "none" : "add","state")
                }
            }
        }
        # --- route-reconciler ---
        nf=rd("obs-forcevpn",fa); fs=rstate; fok=(fs!="bad")
        for(i=1;i<=nf && fok;i++) {
            l=fa[i]; sub(/#.*/,"",l); l=tolower(l); split(l,f," "); d=f[1]; if(d=="") continue
            if(d ~ /^\*\./) d=substr(d,3)
            if(domain(d)) force[d]=1; else fok=0
        }
        if(!cfgok || !devok || !fok) mechunknown("route-reconciler")
        else {
            aat=""; aan=nrt["AdaptiveAuto"]
            if(aan==1) aat=target(rtg["AdaptiveAuto",1]); else if(aan==0) aat="none"
            if(aat=="") aat="unknown"
            for(j=1;j<=ndm["AdaptiveAuto"];j++) {
                d=gdom["AdaptiveAuto",j]
                # ISP-vs-VPN probes are live network work: only force-vpn is observable.
                if(force_match(d)) out("route-reconciler",d,aat,(vt0=="")?"unknown":vt0,"-","vward","none","force-vpn")
                else out("route-reconciler",d,aat,"unknown","-","vward","observe","none")
            }
        }
        # --- services ---
        ne=rd("enabled",ea); es=rstate
        nct=rd("categories",ca); cs=rstate
        if(es=="bad" || catbad || !devok || !mapok || !cfgok || cs=="bad") mechunknown("services")
        else {
            for(i=1;i<=nct;i++) { if(ca[i]=="") continue; m=split(ca[i],f,"\t"); if(m!=2 || (f[1] in cat)) {cs="bad"; break}; cat[f[1]]=f[2] }
            if(cs=="bad") mechunknown("services")
            else {
                for(i=1;i<=ne;i++) {
                    if(ea[i]=="") continue
                    m=split(ea[i],f,"\t"); if(m!=3 || !id(f[2]) || (f[1] in sgrp)) {sbad=1; break}
                    sgrp[f[1]]=f[2]; spin[f[1]]=f[3]
                }
                if(sbad) mechunknown("services")
                else for(s in sgrp) {
                    g=sgrp[s]; p=spin[s]
                    # Group route as the service writer sees it.
                    if(!(g in gdecl) && nrt[g]==0) gc="none"
                    else if(nrt[g]==1) { gc=target(rtg[g,1]); if(gc=="") gc="unknown" }
                    else if(nrt[g]==0) gc="none"
                    else gc="unknown"
                    for(c=1;c<=nc;c++) if(cid[c]==s) {
                        d=cdom[c]
                        # service_target: not auto -> the pin; auto -> category tunnel; else the literal "vpn".
                        basis="catalog-pin"
                        if(p!="auto") { t=p } else { t=cat[ccat[c]]; if(t=="") t="" }
                        if(t=="" || (p=="auto" && !(t in vpn)) || t=="vpn") { des=(vt0=="") ? "unknown" : vt0; basis="service-target-defaulted" }
                        else { des=target(t); if(des=="") des="unknown" }
                        w="unknown"; r=sref[d]; nr=split(r,rf," ")
                        for(q=1;q<=nr;q++) { x=(rf[q] in idst) ? idst[rf[q]] : "unknown"; if(q==1) w=x; else if(x!=w) w="unknown" }
                        own=(w=="verified") ? "vward" : "unknown"
                        out("services",d,gc,des,"-",own,"none",basis)
                    }
                }
            }
        }
        # --- tunnel-guard: persistent list moves + quality of the VWARD tunnel ---
        nl=rd("obs-listsfb",la); ls=rstate
        nq=rd("obs-samples",qa); qs=rstate
        if(ls=="bad" || !cfgok || !devok) mechunknown("tunnel-guard")
        else {
            for(i=1;i<=nl;i++) {
                if(la[i]=="") continue
                m=split(la[i],f,"\t")
                if(m!=4 || !id(f[1]) || !id(f[2]) || !id(f[3]) || f[4] !~ /^[0-9]+$/) {lbad=1; break}
                lg[i]=f[1]; lfrom[i]=f[2]; lto[i]=f[3]
            }
            if(lbad) mechunknown("tunnel-guard")
            else for(i=1;i<=nl;i++) if(i in lg) {
                g=lg[i]
                # The guard forgets a move when the list no longer routes to "to": nothing is claimed then.
                ok=0; for(k=1;k<=nrt[g];k++) if(rtg[g,k]==lto[i]) ok=1
                if(!ok) continue
                tc=target(lto[i]); tf=target(lfrom[i])
                for(j=1;j<=ndm[g];j++) out("tunnel-guard",gdom[g,j],(tc=="")?"unknown":tc,(tf=="")?"unknown":tf,"-","-","restore","guard-fallback")
            }
            # Quality of the profile tunnel (lists_best / fallback decision), from the staged samples only.
            if(qs=="bad" || qs=="absent" || vt0=="") out("tunnel-guard","-","unknown","unknown","-","-","none","none")
            else {
                newest=0
                for(i=1;i<=nq;i++) { m=split(qa[i],f,"\t"); if(m<5 || f[1] !~ /^[0-9]+$/ || !id(f[2]) || f[4] !~ /^[0-9]+$/) {qbad=1; break}; if(f[1]+0>newest) newest=f[1]+0 }
                if(qbad || newest==0 || now-newest>180 || newest>now+60) out("tunnel-guard","-","unknown","unknown","-","-","none","none")
                else {
                    for(i=1;i<=nq;i++) {
                        split(qa[i],f,"\t")
                        if(f[1]+0 < now-1800) continue
                        nme=f[2]
                        if(!(nme in qn)) {qn[nme]=1; qord[++nqn]=nme}
                        lloss[nme]=f[4]+0
                        if(f[4]+0<100) { streak[nme]++; fails[nme]=0; if(f[5]!="-" && f[5] ~ /^[0-9]+$/) {sms[nme]+=f[5]; nms[nme]++} }
                        else { streak[nme]=0; fails[nme]++ }
                        cnt[nme]++; sloss[nme]+=f[4]+0
                    }
                    cur=tun; best=""; bl=0; bm=0
                    if((cur in qn) && fails[cur]>=2) {
                        for(i=1;i<=nqn;i++) { nme=qord[i]
                            if(nme==cur || streak[nme]<2 || lloss[nme]>=100) continue
                            al=int(sloss[nme]/cnt[nme]); am=(nms[nme]>0) ? int(sms[nme]/nms[nme]) : 99999
                            if(best=="" || al<bl || (al==bl && am<bm) || (al==bl && am==bm && nme<best)) {best=nme; bl=al; bm=am}
                        }
                    }
                    if(!(cur in qn)) out("tunnel-guard","-","unknown","unknown","-","-","none","none")
                    else if(best!="" && target(best)!="") out("tunnel-guard","-",vt0,target(best),"-","-","switch","guard-fallback")
                    else out("tunnel-guard","-",vt0,vt0,"-","-","none","none")
                }
            }
        }
        # --- policy-sync: domains of groups routed to the VWARD tunnel (no IP/CIDR claim) ---
        if(!cfgok || !devok) mechunknown("policy-sync")
        else for(g in gdecl) {
            hit=0; for(k=1;k<=nrt[g];k++) if(rtg[g,k]==tun || (tun in dev && rtg[g,k]==dev[tun])) hit=1
            if(hit) for(j=1;j<=ndm[g];j++) out("policy-sync",gdom[g,j],(vt0=="")?"unknown":vt0,"-","-","-","observe","cidr-plan")
        }
        if(invalid) { print "routing observe: invalid input or limit exceeded" > "/dev/stderr"; exit 2 }
        msort(outl,nout)
        print "generation" OFS gen
        for(i=1;i<=nout;i++) print outl[i]
    }'
)
