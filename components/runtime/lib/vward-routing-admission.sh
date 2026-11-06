#!/bin/sh
# Scoped OLD-writer admission. Loading defines functions only; it neither owns
# a scope nor enables a transport. The installed binding supplies a fresh stage
# under the existing CHANGE lock and the common persistent journal.

vward_routing_legacy_command_scopes() (
    [ "$#" -eq 1 ] && [ "${#1}" -le 2048 ] || return 75
    # Tokens are data, never shell code. Only canonical scope IDs leave here;
    # URLs/credentials are deliberately never included in the result.
    printf '%s\n' "$1" | LC_ALL=C awk '
    function ident(s) {return length(s)<=64 && s~/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/}
    function domain(s,a,n,i) {
        if(length(s)>253 || s!~/^[a-z0-9.-]+$/)return 0
        n=split(s,a,".");if(n<2 || a[n]~/^[0-9]+$/)return 0
        for(i=1;i<=n;i++)if(length(a[i])>63 || a[i]!~/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/)return 0
        return 1
    }
    function emit(k,v) {print k "\t" v}
    {
        if(NR!=1 || NF<1 || NF>32 || $0~/\r/){bad=1;next}
        if($1=="show"){emit("readonly","-");next}
        start=($1=="no"?2:1);n=0
        for(i=start;i<=NF;i++)a[++n]=$i
        if(a[1]=="object-group" && a[2]=="fqdn") {
            if(!ident(a[3]) || (n!=3 && n!=5)){bad=1;next}
            emit("group",a[3])
            if(n==5) {
                if(a[4]!~/^(include|exclude)$/ || !domain(a[5])){bad=1;next}
                emit("domain",a[5])
            }
            next
        }
        if(a[1]=="dns-proxy") {
            if(a[2]=="no"){for(i=2;i<n;i++)a[i]=a[i+1];n--}
            if(a[2]=="route" && a[3]=="object-group" && ident(a[4]) && ident(a[5]) &&
               (n==5 || (n==6 && a[6]=="auto"))){emit("group",a[4]);next}
            if(a[2]!="https" || a[3]!="upstream"){bad=1;next}
            # Keenetic may remove HTTPS rows URL-wide even when a legacy
            # caller supplies a domain. Neighbours/shared capacity belong to
            # the common DNS plan, never to a domain-only legacy permission.
            emit("broad-dns","-");next
        }
        if(a[1]=="ip" && a[2]=="name-server") {
            if(n==4 && domain(a[4])){emit("domain",a[4]);next}
            if(n>=5 && a[n-1]=="domain" && domain(a[n])){emit("domain",a[n]);next}
            emit("broad-dns","-");next
        }
        if(n==3 && a[1]=="system" && a[2]=="configuration" && a[3]=="save")emit("save","-")
        else emit("other","-")
    }
    END {if(bad || NR!=1)exit 75}'
)

# STAGE JDIR COMMAND. 0 permits only the existing legacy path and its guards;
# 75 requires common-policy handoff/refusal, never automatic forward replay.
vward_routing_legacy_command_gate() (
    [ "$#" -eq 3 ] || return 75
    vrg_scopes=$(vward_routing_legacy_command_scopes "$3") || return 75
    [ "$vrg_scopes" != "$(printf 'readonly\t-')" ] || return 0
    vward_routing_update_eligibility2 "$2" || return 75
    while IFS="$(printf '\t')" read -r vrg_kind vrg_key vrg_extra; do
        [ -z "$vrg_extra" ] || return 75
        case $vrg_kind in
            group|domain) vward_routing_legacy_eligibility2 "$1" "$2" "$vrg_kind" "$vrg_key" || return 75 ;;
            save|other) [ "$vrg_key" = - ] || return 75 ;;
            *) return 75 ;;
        esac
    done <<VRG_SCOPES
$vrg_scopes
VRG_SCOPES
)
