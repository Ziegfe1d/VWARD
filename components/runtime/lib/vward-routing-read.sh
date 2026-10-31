#!/bin/sh
# RS-6: native persisted inputs -> RS-5 TSV; explicit invocation, stdout only.
# Reads the existing shared cache; NEVER refreshes it or invokes a writer.
# Modes: intents | snapshot (RS5 TSV) | identity (RS-6 stable identity table).
# REF = hash of canonical content (source, container, domain, scope, route, DNS),
# never a row position: reordering lines cannot rename a record. Identity is not
# ownership: only a private proof file that matches the group exactly says
# `verified`; the right to change is always `reference` here.
vward_routing_read() (
    [ "$#" = 1 ] || return 2
    case "$1" in intents|snapshot|identity) VRR_MODE=$1 ;; *) return 2 ;; esac
    VRR_ETC=${VWARD_CONSOLE_ETC:-/opt/etc/vward}
    VRR_STATE=${VWARD_ROUTE_STATE:-/opt/var/lib/vward/route-engine}
    VRR_CFG=${VWARD_KCACHE:-${VWARD_ROOT_PREFIX:-}/tmp/vward-keenetic}/running-config
    VRR_DEV=${VWARD_DEVICE_CONFIG:-$VRR_ETC/device.conf}
    VRR_MAP=${VWARD_DEVICE_MAP_CACHE:-/tmp/vward-device-map.tsv}
    VRR_AGH=${VWARD_ROUTING_AGH_DOMAINS:-/nonexistent/vward-agh-domains}
    VRR_BACKUP=${VWARD_CONSOLE_BACKUP_DIR:-/opt/var/backups/vward/console-config}
    export VRR_MODE VRR_ETC VRR_STATE VRR_CFG VRR_DEV VRR_MAP VRR_AGH VRR_BACKUP
    # Match the existing fetched -> bundled catalog preference; never fetch.
    vrr_catalog=
    for vrr_path in "${VWARD_SERVICES_FETCHED:-/opt/var/lib/vward/services/catalog.json}" \
                    "${VWARD_SERVICES_BUNDLED:-/opt/share/vward/console/services-catalog.json}"; do
        [ -f "$vrr_path" ] && [ ! -L "$vrr_path" ] && [ -r "$vrr_path" ] || continue
        [ "$(wc -c < "$vrr_path")" -le 524288 ] || continue
        vrr_catalog=$("${JQ:-jq}" -er '
            if .schema == 1 and (.services | type) == "array" and (.services | length) > 0 and
                all(.services[]; (.id | type) == "string" and (.category | type) == "string" and
                    (.domains | type) == "array" and (.domains | length) > 0 and
                    all(.domains[]; type == "string"))
            then .services[] | . as $s | .domains[] | [$s.id,$s.category,.] | @tsv
            else error("catalog") end' "$vrr_path" 2>/dev/null) && break
        vrr_catalog=
    done
    # Private evidence may be read, but is never promoted to write permission.
    # Paths must be absolute to keep awk away from options/assignment semantics.
    for vrr_path in "$VRR_ETC" "$VRR_STATE" "$VRR_CFG" "$VRR_DEV" "$VRR_MAP" "$VRR_AGH" "$VRR_BACKUP"; do
        case "$vrr_path" in /*) ;; *) return 2 ;; esac
    done
    {
        printf '%s\n' "$vrr_catalog" | awk 'NF {print "catalog\t" $0}'
        for vrr_input in "$VRR_CFG" "$VRR_DEV" "$VRR_MAP" "$VRR_AGH" \
            "$VRR_ETC/services/enabled.tsv" "$VRR_ETC/services/categories.tsv" \
            "$VRR_STATE/adaptive-persist.txt" "$VRR_ETC"/route-engine/domain-lists/*; do
            [ -f "$vrr_input" ] && [ ! -L "$vrr_input" ] && [ -r "$vrr_input" ] || continue
            printf 'readable\t%s\n' "$vrr_input"
        done
        for vrr_proof in "$VRR_ETC"/services/owned/*; do
            if [ -e "$vrr_proof" ] || [ -L "$vrr_proof" ]; then printf 'proofpresent\t%s\n' "${vrr_proof##*/}"; fi
            [ -f "$vrr_proof" ] && [ ! -L "$vrr_proof" ] && [ -O "$vrr_proof" ] || continue
            vrr_meta=$(ls -ln "$vrr_proof" 2>/dev/null | awk '{print $1}')
            case "$vrr_meta" in -rw-------|-r--------) printf 'private\t%s\n' "${vrr_proof##*/}" ;; esac
        done
        # A durable pending/reservation after reboot makes the observation unknown.
        for vrr_pending in "$VRR_BACKUP"/service-transactions/*/pending "$VRR_BACKUP-recovery"/smartdns.*; do
            if [ -e "$vrr_pending" ] || [ -L "$vrr_pending" ]; then printf 'pending\t1\n'; fi
        done
        if [ -e "$VRR_ETC/route-engine/adaptive.disabled" ]; then printf 'disabled\t1\n'; fi
    } | LC_ALL=C awk '
    BEGIN {
        FS=OFS="\t"; mode=ENVIRON["VRR_MODE"]; etc=ENVIRON["VRR_ETC"]; state=ENVIRON["VRR_STATE"]
        for(ci=32;ci<127;ci++) ord[sprintf("%c",ci)]=ci
        hexd="0123456789abcdef"
    }
    # Stable 64-bit style fingerprint of validated ASCII tokens (two independent
    # moduli; doubles stay exact). Collisions are detected where IDs are issued.
    function hex8(n, i,r) {r=""; for(i=0;i<8;i++) {r=substr(hexd,(n%16)+1,1) r; n=int(n/16)} return r}
    function hh(str, i,c,a,b) {
        a=5381; b=52711
        for(i=1;i<=length(str);i++) {
            c=ord[substr(str,i,1)]
            a=(a*131+c)%4294967291; b=(b*257+c+i)%4294967279
        }
        HA=a; HB=b
        return hex8(a) hex8(b)
    }
    # Issue an ID for a canonical record; two different records with one ID is fatal.
    function mkid(prefix,canon, v) {
        v=hh(canon)
        if((v in idcanon) && idcanon[v]!=canon) {invalid=1; return prefix "-collision"}
        idcanon[v]=canon
        return prefix "-" v
    }
    function id(s) {return length(s)<=64 && s ~ /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/}
    function domain(s, n,a,i) {
        if(length(s)>253 || s !~ /^[a-z0-9.-]+$/) return 0
        n=split(s,a,"."); if(n<2) return 0
        for(i=1;i<=n;i++) if(length(a[i])<1 || length(a[i])>63 || a[i] !~ /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/) return 0
        return 1
    }
    function load(file,kind, l,rc,n,b) {
        if(!(file in readable)) {known[kind]=0; return}
        n=b=0
        while((rc=(getline l < file))>0) {
            n++; b+=length(l)+1
            if(n>4096 || b>1048576) {bad[kind]=1; break}
            parse(kind,l)
        }
        close(file); known[kind]=(rc==0 && !bad[kind])
        if(kind=="cfg" && !cfg_structure) known[kind]=0
    }
    function parse(kind,l, n,a,k,v,t,g,idx) {
        sub(/\r$/, "", l)
        if(kind=="cfg") {
            if(l ~ /^(interface |dns-proxy$|object-group fqdn )/) cfg_structure=1
            if(tolower(l) ~ /(^|[^a-z])(error|failed|invalid|unknown command)([^a-z]|$)/) bad[kind]=1
            n=split(l,a,/[ \t]+/); if(a[1]=="") {for(k=1;k<n;k++) a[k]=a[k+1]; n--}
            if(l ~ /^[^ \t!]/) {ctx=(l=="dns-proxy"); group=""}
            if(l ~ /^!/) {ctx=0;group="";return}
            if(a[1]=="object-group" && a[2]=="fqdn") {
                if(l !~ /^object-group fqdn /) {bad[kind]=1;group="";return}
                if(!id(a[3]) || n!=3) {bad[kind]=1;return}
                group=a[3]
                if(!(group in gn)) {gn[group]=++ng; groups[ng]=group}
                else dup[group]=1  # same name declared twice: ambiguous, never merged silently
                return
            }
            if(ctx && a[1]=="route" && a[2]=="object-group") {
                g=a[3];t=a[4]; if(!id(g)||!id(t)) {bad[kind]=1;return}
                v=""; for(k=5;k<=n;k++) v=v (v==""?"":" ") a[k]; if(v=="") v="-"
                idx=g SUBSEP t SUBSEP v
                if(!(idx in route_seen)) {route_seen[idx]=1; nr[g]++; rt[g,nr[g]]=t; sig[g,"route=" t "\t" v]++}
            }
            if(ctx && a[1]=="https" && a[2]=="upstream" && a[n-1]=="domain") {
                v=tolower(a[n]); if(domain(v)) smart[v]=1; else bad[kind]=1
            }
            if(group!="") {
                v=l; sub(/^[ \t]+/,"",v); if(v!="") sig[group,v]++
                if(a[1]=="include") {
                    v=tolower(a[2]); if(n!=2 || !domain(v)) {bad[kind]=1;return}
                    if(!member[group,v]++) {nd[group]++; dom[group,nd[group]]=v}
                }
            }
        } else if(kind=="dev") {
            if(l ~ /^[ \t]*#/ || l=="") return
            k=l; sub(/=.*/,"",k); v=substr(l,length(k)+2)
            if(k=="VWARD_TUNNEL_INTERFACE" || k=="VWARD_WAN_INTERFACE" || k=="VWARD_WAN_DEVICE") {
                if(!id(v) || k in profile) bad[kind]=1; else profile[k]=v
            }
        } else if(kind=="map") {
            n=split(l,a,"\t"); if(a[1]=="I" && n==5 && id(a[2])) {
                t=tolower(a[3]); if(t ~ /^(wireguard|openvpn|sstp|pptp|l2tp|ike|ipsec|proxy|opkgtun)$/ && a[4]!="-") vpn[a[2]]=1
            }
        } else if(kind=="enabled") {
            if(l=="") return
            n=split(l,a,"\t"); if(n!=3 || !id(a[2]) || a[1] in service_group) {bad[kind]=1;return}
            service_group[a[1]]=a[2]; pin[a[1]]=a[3]; used[a[2]]=1; sn[a[1]]=++ns
        } else if(kind=="categories") {
            if(l=="") return
            n=split(l,a,"\t"); if(n!=2 || a[1] in category) {bad[kind]=1;return}; category[a[1]]=a[2]
        } else if(kind=="saved") {
            # Deferred DNS/return routes are evidence, never active route rows.
            if(l ~ /^route=/) {
                n=split(substr(l,7),a,"\t")
                if(n!=2 || (a[1]!="-" && !id(a[1]))) bad[kind]=1
                saved_header++
            } else if(l ~ /^agh=/) {
                n=split(substr(l,5),a,"\t"); if(n!=2 || !domain(a[1])) bad[kind]=1
            } else if(l !~ /^doh=https upstream / && l!="") bad[kind]=1
        } else if(kind=="persist" || kind=="agh") {
            if(l=="") return
            v=tolower(l); if(!domain(v)) {bad[kind]=1;return}
            if(kind=="agh") smart[v]=1
            else if(!(v in adaptive)) {adaptive[v]=++na}
        }
    }
    function target(t) {
        if(t=="ISP" || (known["dev"] && t==profile["VWARD_WAN_INTERFACE"])) return "ISP"
        if(known["map"] && t in vpn && t!=profile["VWARD_WAN_INTERFACE"]) return "VPN:" t
        return ""
    }
    function dns(d, k) {
        for(k in smart) if(d==k || (length(d)>length(k) && substr(d,length(d)-length(k))=="." k)) return "smartdns"
        return known["agh"] ? "default" : "unknown"
    }
    # absent = never claimed; unknown = present but not a safe private file or
    # config unreadable; mismatch = claimed once, content changed since (edit or
    # reused group name); vward = private proof matches the group exactly.
    function owned(g, path,l,rc,n,k,a,b,ok) {
        if(!known["cfg"]) return "unknown"
        if(!(g in proofpresent)) return "absent"
        if(!(g in private)) return "unknown"
        path=etc "/services/owned/" g; ok=1;n=0
        while((rc=(getline l < path))>0) {
            n++; if(n>4096 || !(g SUBSEP l in sig)) {ok=0;break}; proof[l]++
        }
        close(path); if(rc<0) ok=0
        for(k in sig) {split(k,a,SUBSEP); if(a[1]==g && proof[a[2]]!=sig[k]) ok=0}
        for(k in proof) delete proof[k]
        return ok && n>0 ? "vward" : "mismatch"
    }
    function identstate(g) {
        if(!known["cfg"] || (g in dup)) return "unknown"
        if(pst[g]=="vward") return "verified"
        if(pst[g]=="absent") return "reference-only"
        return "unknown"
    }
    function remember(d) {
        if(d!="" && !(d in output_domains)) {output_domains[d]=1; output_nd++}
        if(output_nd>1024) invalid=1
    }
    function emit(line,d) {
        remember(d)
        if(invalid) return
        if(!(line in output_seen)) {
            output_seen[line]=1; output_n++; output_bytes+=length(line)+1
            if(output_n<=4096 && output_bytes<=1048576) output[output_n]=line
        }
        if(output_n>4096 || output_bytes>1048576 || output_nd>1024) invalid=1
    }
    function flush( width,left,mid,right,i,j,pos,tmp) {
        if(invalid) {print "routing read: expanded input exceeds RS5 bounds" > "/dev/stderr"; exit 2}
        for(width=1;width<output_n;width*=2) {
            for(left=1;left<=output_n;left+=2*width) {
                mid=left+width;right=left+2*width
                if(mid>output_n+1) mid=output_n+1
                if(right>output_n+1) right=output_n+1
                i=left;j=mid
                for(pos=left;pos<right;pos++) {
                    if(i<mid && (j>=right || "x" output[i]<= "x" output[j])) tmp[pos]=output[i++]
                    else tmp[pos]=output[j++]
                }
            }
            for(pos=1;pos<=output_n;pos++) output[pos]=tmp[pos]
        }
        for(pos=1;pos<=output_n;pos++) print output[pos]
    }
    function intent(s,key,d,t,cont,content,link,ident, r,x) {
        remember(d); x=dns(d)
        r=mkid(tolower(s), s "|" key "|" d "|exact|" t "|" x)
        if(mode=="intents") emit(s OFS r OFS d OFS "exact" OFS t OFS x OFS 1,d)
        else if(mode=="identity") emit(r OFS "intent" OFS s OFS cont OFS content OFS mkid("t","T|exact|" t "|" x) OFS link OFS ident OFS "reference",d)
    }
    $1=="catalog" {
        if(NF!=4 || !domain(tolower($4))) catalog_bad=1
        else {nc++; cid[nc]=$2; ccat[nc]=$3; cd[nc]=tolower($4)}; next
    }
    $1=="readable" && NF==2 {readable[$2]=1;next}
    $1=="private" && id($2) {private[$2]=1;next}
    $1=="proofpresent" && id($2) {proofpresent[$2]=1;next}
    $1=="pending" {pending=1;next}
    $1=="disabled" {disabled=1;next}
    END {
        load(ENVIRON["VRR_DEV"],"dev"); load(ENVIRON["VRR_MAP"],"map")
        load(ENVIRON["VRR_CFG"],"cfg"); load(ENVIRON["VRR_AGH"],"agh")
        load(etc "/services/enabled.tsv","enabled"); load(etc "/services/categories.tsv","categories")
        load(state "/adaptive-persist.txt","persist")
        mk=known["cfg"] ? "known":"unknown"; sk=known["enabled"] ? "known":"unknown"
        ak=known["persist"] ? "known":"unknown"
        # Legacy groups have no global manual switch. These are observed enabled
        # sources, NOT persisted RS-7 toggles. Missing input never means disabled.
        # Order-independent content fingerprint: commutative sum of line hashes.
        for(k in sig) {split(k,a,SUBSEP); hh(a[2] "*" sig[k]); cA[a[1]]=(cA[a[1]]+HA)%4294967291; cB[a[1]]=(cB[a[1]]+HB)%4294967279; cN[a[1]]++}
        for(i=1;i<=ng && !invalid;i++) {
            g=groups[i]; pst[g]=owned(g); owner=(pst[g]=="vward") ? "vward" : "unknown"
            gcont[g]=mkid("g","G|" g); gcontent[g]="c-" hex8(cA[g]) hex8(cB[g]) "." cN[g]+0
            if(g in dup) mk="unknown"
            saved_header=0; bad["saved"]=0
            load(etc "/route-engine/domain-lists/" g,"saved")
            # Missing saved state is normal; a present malformed state cannot
            # be treated as a verified return plan. No replay is attempted.
            if(known["saved"] && saved_header!=1) mk="unknown"
            for(j=1;j<=nd[g] && !invalid;j++) for(k=1;k<=nr[g] && !invalid;k++) {
                d=dom[g,j]; t=target(rt[g,k]); if(t=="") {mk="unknown";continue}
                if(known["cfg"]) remember(d)
                lnk=(g=="AdaptiveAuto") ? "runtime-group" : "native-group"
                if(known["cfg"] && mode!="intents") {
                    rr=mkid("r","R|" g "|" d "|exact|" t "|" dns(d))
                    if(mode=="snapshot") emit("route" OFS rr OFS d OFS "exact" OFS t OFS dns(d) OFS owner OFS "reference",d)
                    else emit(rr OFS "route" OFS "-" OFS gcont[g] OFS gcontent[g] OFS mkid("t","T|exact|" t "|" dns(d)) OFS lnk OFS identstate(g) OFS "reference",d)
                }
                if(known["cfg"] && !(g in used) && g!="AdaptiveAuto") intent("M",g,d,t,gcont[g],gcontent[g],lnk,identstate(g))
            }
            if(nd[g]>0 && nr[g]==0) mk="unknown"
        }
        for(s in service_group) {
            if(invalid) break
            # Category comes from the selected catalog record, not display order.
            found=0
            for(c=1;c<=nc && !invalid;c++) if(cid[c]==s) {
                found=1; t=pin[s]
                if(t=="auto") {t=category[ccat[c]]; if(t=="") t=profile["VWARD_TUNNEL_INTERFACE"]}
                t=target(t)
                if(t=="" || catalog_bad || !known["enabled"] || !known["dev"] || !known["categories"]) {sk="unknown";continue}
                sg=service_group[s]
                intent("S",s,cd[c],t,mkid("v","V|" s),(sg in gn) ? gcontent[sg] : "-","service-link",(sg in gn) ? identstate(sg) : "unknown")
            }
            if(!found) sk="unknown"
        }
        t=target(profile["VWARD_TUNNEL_INTERFACE"])
        if(t=="" || !known["dev"] || !known["cfg"]) ak="unknown"
        if(t!="" && known["persist"] && known["dev"]) for(d in adaptive) {if(invalid) break; intent("A","",d,t,"-","-","adaptive-persist","reference-only")}
        if(pending) mk=sk=ak="unknown"
        if(mode=="snapshot") {
            emit("snapshot" OFS "legacy-read" OFS "unknown","")
            emit("source" OFS "M" OFS 1 OFS mk,""); emit("source" OFS "S" OFS 1 OFS sk,""); emit("source" OFS "A" OFS (disabled?0:1) OFS ak,"")
            emit("health" OFS "DNS" OFS "unknown",""); emit("health" OFS "AGH" OFS "unknown","")
            for(v in vpn) emit("health" OFS "VPN:" v OFS "unknown","")
        }
        flush()
    }'
)
