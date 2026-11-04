#!/bin/sh
# B v2 decision projection. Functions only; no caller, installed-state path or transport.
# All scratch belongs to the explicitly supplied private output directory.

vr2_private_dir() {
    case $1 in /*) ;; *) return 2 ;; esac
    [ -d "$1" ] && [ ! -L "$1" ] && [ -O "$1" ] &&
        [ "$(ls -ldn "$1" | awk '{print substr($1,1,10)}')" = drwx------ ]
}

vr2_file() {
    [ -f "$1" ] && [ ! -L "$1" ] && [ -r "$1" ] &&
        [ "$(wc -c < "$1")" -le 1048576 ] && [ "$(wc -l < "$1")" -le 4096 ]
}
vr2_hash() {
    vr2_file "$1" || return 2
    vr2_h=$(sha256sum < "$1") || return 2
    vr2_h=${vr2_h%% *}
    case $vr2_h in ''|*[!0-9a-f]*) return 2 ;; esac
    [ "${#vr2_h}" = 64 ] && printf '%s\n' "$vr2_h"
}
vr2_stage_files() {
    printf '%s\n' 'intents.tsv snapshot.tsv identity.tsv legacy.tsv inventory.tsv groups.tsv native.cfg enabled.tsv decision/version.tsv decision/choices.tsv decision/bindings.tsv decision/evidence.tsv decision/policies.tsv decision/saved.tsv decision/queue.tsv decision/tombstones.tsv decision/context.tsv decision/resources.tsv decision/proofs.tsv'
}
# Integrity of published preparation files, including the exact expected file
# set. A valid-looking edit cannot keep using an earlier content generation.
vr2_seal_valid() (
    [ "$#" -eq 3 ] && vr2_private_dir "$1" || return 2
    vr2_file "$1/generation" && vr2_file "$1/seal" && vr2_file "$1/seal.sha" || return 2
    [ "$(vr2_hash "$1/seal")" = "$(cat "$1/seal.sha")" ] || return 3
    vr2_count=0;vr2_seen=' '
    exec 3< "$1/seal" || return 2
    IFS="$(printf '\t')" read -r vr2_type vr2_version vr2_generation vr2_extra <&3 || return 2
    [ "$vr2_type" = "$2" ] && [ "$vr2_version" = 2 ] && [ -z "$vr2_extra" ] &&
        [ "$vr2_generation" = "$(cat "$1/generation")" ] || return 3
    printf '%s\n' "$vr2_generation" | grep -Eq '^g-[0-9a-f]{16}$' || return 2
    while IFS="$(printf '\t')" read -r vr2_digest vr2_path vr2_extra <&3; do
        [ -z "$vr2_extra" ] || return 2
        case " $3 " in *" $vr2_path "*) ;; *) return 2 ;; esac
        case "$vr2_seen" in *" $vr2_path "*) return 2 ;; esac
        [ "$(vr2_hash "$1/$vr2_path")" = "$vr2_digest" ] || return 3
        vr2_seen="$vr2_seen$vr2_path ";vr2_count=$((vr2_count+1))
    done
    # Closed, compiled-in names only; shell word splitting counts that set.
    # shellcheck disable=SC2086
    set -- $3
    [ "$vr2_count" -eq "$#" ]
)
vr2_stage_valid() { vr2_private_dir "$1/decision" && vr2_seal_valid "$1" routing-stage "$(vr2_stage_files)"; }
vr2_projection_valid() { vr2_seal_valid "$1" routing-projection 'atoms.tsv policy.tsv choices.tsv service'; }

# STAGE SID CANONICAL_NEXT_CHOICES OUTDIR -> OUTDIR/atoms.tsv, policy.tsv.
# Atoms keep unknown membership/client policy explicit. This does not claim ownership.
vward_routing_project2() (
    umask 077
    [ "$#" -eq 4 ] || return 2
    vr2_private_dir "$1" && vr2_private_dir "$4" || return 2
    vr2_stage_dir=$(CDPATH='' cd -- "$1" && pwd -P) || return 2
    vr2_out_dir=$(CDPATH='' cd -- "$4" && pwd -P) || return 2
    case "$vr2_out_dir/" in "$vr2_stage_dir/"*) return 2 ;; esac
    rm -f "$4/generation" "$4/seal" "$4/seal.sha" || return 2
    vr2_stage_valid "$1" || return 3
    for vr2_f in "$1/generation" "$1/decision/version.tsv" "$1/decision/bindings.tsv" \
        "$1/decision/evidence.tsv" "$1/decision/context.tsv" "$1/decision/resources.tsv" \
        "$1/intents.tsv" "$1/snapshot.tsv" "$3"; do
        vr2_file "$vr2_f" || return 2
    done
    [ "$(cat "$1/decision/version.tsv")" = "$(printf 'routing-state\t2')" ] || return 2
    vr2_tmp=$(mktemp -d "$4/.projection.XXXXXX") || return 2
    trap 'rm -rf "$vr2_tmp"' EXIT
    vr2_next_hash=$(vr2_hash "$3") || return 2
    cp "$3" "$vr2_tmp/choices" || return 2
    [ "$vr2_next_hash" = "$(vr2_hash "$vr2_tmp/choices")" ] || return 3
    vr2_current=$(awk -F'\t' -v s="$2" '$1=="service" && $2==s {print $4,$5,$6,$3;found=1} END{if(!found) print "auto - - 0"}' "$vr2_tmp/choices")
    # Recompute the ENTIRE candidate from the staged ledger through the real
    # canonical transition. This binds epoch/revision and preserves every peer.
    # No callback can smuggle in a second service choice through NEXT_CHOICES.
    # shellcheck disable=SC2086
    set -- "$1" "$2" "$3" "$4" $vr2_current
    [ "$#" -eq 8 ] || return 2
    vr2_old_rev=$(awk -F'\t' -v s="$2" '$1=="service" && $2==s {print $3;found=1} END{if(!found)print 0}' "$1/decision/choices.tsv")
    vward_routing_choice "$1/decision/choices.tsv" "$2" "$5" "$6" "$7" "$vr2_old_rev" > "$vr2_tmp/expected" || return 2
    cmp -s "$vr2_tmp/expected" "$vr2_tmp/choices" || return 3
    VWARD_B_SID=$2 LC_ALL=C awk '
    BEGIN {FS=OFS="\t";sid=ENVIRON["VWARD_B_SID"]}
    function id(s) {return length(s)<=64 && s ~ /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/}
    function refid(s) {return length(s)<=64 && s ~ /^[A-Za-z0-9][A-Za-z0-9_.:@-]*$/}
    function service(s) {return length(s)<=63 && s ~ /^[a-z0-9][a-z0-9.@_-]*$/}
    function domain(s, a,n,i) {
        if(length(s)>253 || s !~ /^[a-z0-9.-]+$/) return 0
        n=split(s,a,".");if(n<2 || a[n] ~ /^[0-9]+$/) return 0
        for(i=1;i<=n;i++) if(length(a[i])>63 || a[i] !~ /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/) return 0
        return 1
    }
    function covers(p,d,s) {return p==d || (s=="subtree" && length(d)>length(p) && substr(d,length(d)-length(p))=="." p)}
    function emit(line) {if(++out_n>4096 || (out_bytes+=length(line)+1)>1048576) exit 2;print line}
    function binding(s,d, i,result) {
        result="none"
        for(i=1;i<=nb;i++) if(bs[i]==s && covers(bd[i],d,bsc[i])) {
            if(ba[i]=="excluded") return "excluded"
            if(ba[i]!="confirmed" || bf[i]=="unknown" || bc[i]=="unknown") result="unknown"
            else if(result=="none") result="confirmed"
        }
        return result
    }
    {bytes[FILENAME]+=length($0)+1;if(FNR>4096 || bytes[FILENAME]>1048576) {bad=1;next}}
    FILENAME==ARGV[1] {
        if(FNR==1 && $1=="schema" && $2==1 && NF==2) next
        mode[$2]=$4;tgt[$2]=$5;dns[$2]=$6;rev[$2]=$3;floor[$2]=$7;next
    }
    FILENAME==ARGV[2] {
        if(NF!=6 || !service($1) || !domain($2) || $3 !~ /^(exact|subtree)$/ ||
           $4 !~ /^(confirmed|excluded|shared|unknown)$/ || $5 !~ /^(ipv4|dual|unknown)$/ ||
           $6 !~ /^(known|unknown)$/ || seenb[$1 SUBSEP $2 SUBSEP $3]++) {bad=1;next}
        bs[++nb]=$1;bd[nb]=$2;bsc[nb]=$3;ba[nb]=$4;bf[nb]=$5;bc[nb]=$6;domains[$2]=1
        if($1==sid) {scope[$2]=$3;own[$2]=1}
        next
    }
    FILENAME==ARGV[3] {
        if(NF!=10 || $1 !~ /^[MSA]$/ || !refid($2) || !domain($3) || $4 !~ /^(exact|subtree)$/ ||
           ($5!="ISP" && !($5 ~ /^VPN:/ && id(substr($5,5)))) || !id($6) || $7 !~ /^[01]$/ ||
           $8 !~ /^(explicit|active|positive|history|unknown)$/ || $9 !~ /^[0-9]+$/ || $9+0>2147483647 ||
           ($10!="-" && !service($10)) || seene[$1 SUBSEP $2]++) {bad=1;next}
        if(($1!="A" && ($8!="explicit" || $9+0!=0)) || ($1=="A" && $8=="explicit")) {bad=1;next}
        e[++ne]=$0;es[ne]=$1;er[ne]=$2;ed[ne]=$3;escp[ne]=$4;et[ne]=$5;ep[ne]=$6
        selected[ne]=$7;kind[ne]=$8;epoch[ne]=$9;origin[ne]=$10;domains[$3]=1;next
    }
    FILENAME==ARGV[4] {if(NF!=2 || ($1 in ctx)) bad=1;ctx[$1]=$2;next}
    FILENAME==ARGV[5] {
        if(NF!=11 || !id($2) || ($4!="-" && !domain($4)) || $5 !~ /^(exact|subtree)$/) {bad=1;next}
        if($4!="-") domains[$4]=1
        if(index("," $11 ",",",S:" sid ",")) {own[$4]=1;if(!($4 in scope)) scope[$4]=$5}
        if($1=="route" && $9=="vward") {
            own_key[$2]=$3 SUBSEP $4 SUBSEP $5 SUBSEP $6 SUBSEP $7
            own_prefix[$2]=$1;for(j=2;j<=10;j++)own_prefix[$2]=own_prefix[$2] OFS $j
        }
        next
    }
    FILENAME==ARGV[6] {
        # Native manual rules remain independent explicit contributors. Their
        # observed presence is not replaced by an empty v2 evidence file.
        if($1!="M") next
        es[++ne]="M";er[ne]=$2;ed[ne]=$3;escp[ne]=$4;et[ne]=$5;ep[ne]=$6
        selected[ne]=$7;kind[ne]="explicit";epoch[ne]=0;origin[ne]="-";domains[$3]=1;native_ref[ne]=$2;next
    }
    FILENAME==ARGV[7] {
        if($1=="source" && $4=="unknown") native_unknown[$2]=1
        next
    }
    FILENAME==ARGV[8] {
        if($1=="resource" && $8=="vward" && $10=="verified")
            native_group[$12]="group:" $3
        next
    }
    FILENAME==ARGV[9] {
        p=$1;for(j=2;j<=10;j++)p=p OFS $j
        if(NF==11)origin_proof[$2]=p
        next
    }
    FILENAME==ARGV[10] {
        if($2=="intent" && $3=="M" && $8=="verified")intent_container[$1]=$4
        next
    }
    END {
        if(!service(sid) || nb>1024 || ne>4096 || bad) exit 2
        if(!(sid in mode)) {mode[sid]="auto";tgt[sid]="-";dns[sid]="-";rev[sid]=floor[sid]=0}
        # A native projection of this same managed physical resource is not a
        # second manual source. Require BOTH exact private native proof and the
        # v2 origin/content row; names or a manifest alone never suppress M.
        for(r in own_key) if(origin_proof[r]==own_prefix[r])common_key[own_key[r]]=1
        for(i in native_ref) {
            c=intent_container[native_ref[i]]
            if(!(c in native_group))continue
            k=native_group[c] SUBSEP ed[i] SUBSEP escp[i] SUBSEP et[i] SUBSEP ep[i]
            if(k in common_key)common_native[i]=1
        }
        for(d in domains) {
            member=binding(sid,d)
            if(member=="none" && !own[d]) continue
            if(++nd>1024) exit 2
            sc=(d in scope) ? scope[d] : "exact";why="-"
            if(member=="unknown") why="membership-unknown"
            if(ctx["source:S"]!="1" && mode[sid]!="auto") why="service-source-disabled"
            for(src in native_unknown) if(ctx["source:" src]!="0") why="native-source-unknown"
            for(i=1;i<=ne;i++) if(covers(ed[i],d,escp[i]) && selected[i]==1 &&
                ctx["source:" es[i]]!="0" && ctx["source:" es[i]]!="1") why="source-unknown"
            for(s in mode) if(s!=sid && mode[s]!="auto") {
                peer=binding(s,d)
                if(peer=="unknown") why="peer-membership-unknown"
                if(peer=="confirmed" && ctx["source:S"]!="1") why="service-source-disabled"
            }
            m=mode[sid];t=tgt[sid];p=dns[sid]
            if(member=="none" || member=="excluded") {m="auto";t=p="-"}
            emit("atom" OFS d OFS sc OFS m OFS t OFS p OFS rev[sid] OFS floor[sid] OFS why)
            for(i=1;i<=ne;i++) if(covers(ed[i],d,escp[i])) {
                if(i in common_native) continue
                if(es[i]=="S" && origin[i]==sid) continue
                sel=(ctx["source:" es[i]]=="1") ? selected[i] : 0
                k=kind[i];membership=(es[i]=="A") ? (member=="unknown" ? "unknown" : (member=="excluded" ? "excluded" : "bound")) : "peer"
                if(es[i]=="A" && origin[i]!="-" && origin[i]!=sid) membership="unknown"
                if(es[i]=="A" && k=="positive" && ctx["probe:" er[i]]!="fresh") k="unknown"
                emit("intent" OFS d OFS es[i] OFS er[i] OFS et[i] OFS ep[i] OFS sel OFS k OFS epoch[i] OFS membership)
            }
            for(s in mode) if(s!=sid && mode[s]!="auto" && binding(s,d)=="confirmed")
                emit("intent" OFS d OFS "S" OFS s OFS tgt[s] OFS dns[s] OFS (ctx["source:S"]=="1" ? 1 : 0) OFS "explicit" OFS 0 OFS "peer")
        }
    }' "$vr2_tmp/choices" "$1/decision/bindings.tsv" "$1/decision/evidence.tsv" "$1/decision/context.tsv" \
        "$1/decision/resources.tsv" "$1/intents.tsv" "$1/snapshot.tsv" "$1/inventory.tsv" "$1/decision/proofs.tsv" "$1/identity.tsv" > "$vr2_tmp/input" || return 2
    awk -F'\t' '$1=="atom"' "$vr2_tmp/input" | LC_ALL=C sort -t "$(printf '\t')" -k2,2 > "$vr2_tmp/atoms"
    : > "$vr2_tmp/policy"
    while IFS="$(printf '\t')" read -r _vr2_tag vr2_d _vr2_scope vr2_mode vr2_target vr2_dns vr2_rev vr2_floor vr2_why; do
        { printf 'schema\t1\n'; awk -F'\t' -v d="$vr2_d" 'BEGIN{OFS="\t"} $1=="intent" && $2==d {for(i=3;i<=10;i++) printf "%s%s",$i,(i==10?ORS:OFS)}' "$vr2_tmp/input"; } > "$vr2_tmp/evidence"
        vward_routing_service_policy "$vr2_mode" "$vr2_target" "$vr2_dns" "$vr2_rev" "$vr2_floor" "$vr2_tmp/evidence" > "$vr2_tmp/one" || return 2
        if [ "$vr2_why" != - ]; then
            printf '%s\tpolicy\t1\tunknown\tdenied\tunknown\n' "$vr2_d" >> "$vr2_tmp/policy"
        fi
        awk -F'\t' -v d="$vr2_d" -v s="$2" -v why="$vr2_why" 'BEGIN{OFS="\t"}
            $1=="policy" && why!="-" {next}
            $1=="contribution" && $2=="S" && $3=="choice" {$3=s}
            {print d,$0}' "$vr2_tmp/one" >> "$vr2_tmp/policy"
    done < "$vr2_tmp/atoms"
    vr2_file "$vr2_tmp/policy" || return 2
    [ "$vr2_next_hash" = "$(vr2_hash "$3")" ] && vr2_stage_valid "$1" || return 3
    printf '%s\n' "$2" > "$vr2_tmp/service" || return 2
    cp "$1/generation" "$vr2_tmp/generation" || return 2
    mv "$vr2_tmp/atoms" "$4/atoms.tsv" && mv "$vr2_tmp/policy" "$4/policy.tsv" &&
        mv "$vr2_tmp/choices" "$4/choices.tsv" && mv "$vr2_tmp/service" "$4/service" || return 2
    printf 'routing-projection\t2\t%s\n' "$(cat "$vr2_tmp/generation")" > "$4/seal" || return 2
    for vr2_f in atoms.tsv policy.tsv choices.tsv service; do
        printf '%s\t%s\n' "$(vr2_hash "$4/$vr2_f")" "$vr2_f" >> "$4/seal" || return 2
    done
    vr2_hash "$4/seal" > "$4/seal.sha" || return 2
    mv "$vr2_tmp/generation" "$4/generation"
)
