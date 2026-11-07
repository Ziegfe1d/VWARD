#!/bin/sh
# RS-6: consistent read coordinators v1/v2; loading defines functions only.
#
#   vward_routing_consistent_read OUTDIR
#
# OUTDIR: absolute, existing, private (0700), owned by the caller, not a symlink.
# On success writes intents.tsv, snapshot.tsv and identity.tsv (all produced from
# ONE verified input set), legacy.tsv (the five read-only observers of the existing
# mechanisms, derived from VERIFIED COPIES of their inputs) and, last, the file `generation`; stdout `ok<TAB>GEN`,
# rc 0. A directory is valid only while `generation` exists.
# If a correct snapshot cannot be proven: NO output file is left, stdout is
# `unknown<TAB>REASON`, rc 3. Usage/environment errors: rc 2 (stderr).
#
# Consistency is proved, not assumed: every input is fingerprinted (content SHA256+
# size, inode, mtime) before AND after the projections are read; any difference ->
# unknown. Observer inputs are COPIED into a private stage and each copy must equal
# the fingerprint taken before the copy (a file replaced meanwhile -> unknown);
# observers read only the stage, so they see exactly the state the generation names. The generation is a hash of the CONTENT fingerprints only,
# so the same data gives the same generation after a reboot. It is still not a
# live-router proof: it covers the files and the shared Keenetic cache the
# projections are derived from. The cache is never refreshed here (no ndmc/RCI).
# No daemon, no timer, no background process, nothing outside OUTDIR is written.
# Read-only native clock. Persisted wall time cannot establish probe freshness.
# Tests may substitute DATA facts by defining this function after sourcing;
# production accepts no clock executable/path override.
vr2_clock_read() {
    IFS= read -r vr2_cr_boot < /proc/sys/kernel/random/boot_id || return 1
    read -r vr2_cr_now _ < /proc/uptime || return 1
    vr2_cr_now=${vr2_cr_now%%.*}
    printf '%s %s\n' "$vr2_cr_boot" "$vr2_cr_now"
}
vrsi_consistent_read() (
    umask 077
    [ "$#" -eq 2 ] || return 2
    vrs_read_kind=$2
    case $vrs_read_kind in strict|legacy-observation) ;; *) return 2 ;; esac
    if ! command -v vward_routing_read >/dev/null 2>&1 || ! command -v vward_routing_observe >/dev/null 2>&1; then
        printf '%s\n' 'routing snapshot: reader and observers must be loaded' >&2; return 2
    fi
    vrs_out=$1
    case $vrs_out in /*) ;; *) printf '%s\n' 'routing snapshot: absolute OUTDIR required' >&2; return 2 ;; esac
    # Read only mode metadata; filename fields are never parsed.
    # shellcheck disable=SC2012
    if [ -L "$vrs_out" ] || [ ! -d "$vrs_out" ] || [ ! -O "$vrs_out" ] || [ ! -w "$vrs_out" ] ||
        [ "$(ls -ldn "$vrs_out" 2>/dev/null | awk '{print substr($1,1,10)}')" != drwx------ ]; then
        printf '%s\n' 'routing snapshot: OUTDIR must be a private directory owned by the caller' >&2
        return 2
    fi
    # A previous result must never survive a failed attempt.
    rm -f "$vrs_out/generation" "$vrs_out/intents.tsv" "$vrs_out/snapshot.tsv" "$vrs_out/identity.tsv" "$vrs_out/legacy.tsv" 2>/dev/null
    [ -z "${VWARD_ROUTING_INPUTS:-}" ] || rm -f "$vrs_out/inventory.tsv"
    [ -z "${VWARD_ROUTING_INPUTS:-}" ] || rm -f "$vrs_out/groups.tsv"
    [ -z "${VWARD_ROUTING_INPUTS:-}" ] || rm -f "$vrs_out/native.cfg" "$vrs_out/enabled.tsv" "$vrs_out/agh.json" "$vrs_out/inputs.fp"
    [ -z "${VWARD_ROUTING_INPUTS:-}" ] || rm -f "$vrs_out/seal" "$vrs_out/seal.sha"
    [ -z "${VWARD_ROUTING_INPUTS:-}" ] || rm -rf "$vrs_out/decision"
    vrs_tmp=$(umask 077; mktemp -d "$vrs_out/.read.XXXXXX" 2>/dev/null) || return 2
    trap 'rm -rf "$vrs_tmp"' EXIT
    trap 'exit 3' HUP INT TERM

    vrs_unknown() { printf 'unknown\t%s\n' "$1"; return 3; }

    # Same inputs and defaults as vward_routing_read (read-only mirror).
    vrs_etc=${VWARD_CONSOLE_ETC:-/opt/etc/vward}
    vrs_state=${VWARD_ROUTE_STATE:-/opt/var/lib/vward/route-engine}
    vrs_cfg=${VWARD_KCACHE:-${VWARD_ROOT_PREFIX:-}/tmp/vward-keenetic}/running-config
    vrs_backup=${VWARD_CONSOLE_BACKUP_DIR:-/opt/var/backups/vward/console-config}
    vrs_max_age=${VWARD_ROUTING_CACHE_AGE:-${VWARD_KEENETIC_AGE:-55}}
    vrs_limit=${VWARD_ROUTING_READ_TIMEOUT:-10}
    case $vrs_max_age$vrs_limit in ''|*[!0-9]*) return 2 ;; esac

    # One line per input: LABEL STATE. STATE: absent | bad | oversize | nostat |
    # "SHA256 SIZE INODE MTIME MODE UID". Authority is part of consistency.
    vrs_one_file() {
        if [ ! -e "$2" ] && [ ! -L "$2" ]; then printf '%s absent\n' "$1"; return 0; fi
        if [ -L "$2" ] || [ ! -f "$2" ] || [ ! -r "$2" ]; then printf '%s bad\n' "$1"; return 0; fi
        # Process budget (runs ~50 files x 2 per consistent read): ONE ls -ldin
        # gives inode, mode, uid and byte size of this regular file. Same output
        # fields as the separate wc -c / ls -di / ls -ldn path below, which stays
        # the fallback whenever that single line cannot be parsed.
        vrs_ll=$(LC_ALL=C ls -ldin "$2" 2>/dev/null) || vrs_ll=
        case $vrs_ll in *'
'*) vrs_ll= ;; esac
        vrs_ll=${vrs_ll#"${vrs_ll%%[! 	]*}"}
        vrs_ino=${vrs_ll%%[ 	]*};vrs_ll=${vrs_ll#"$vrs_ino"};vrs_ll=${vrs_ll#"${vrs_ll%%[! 	]*}"}
        vrs_am=${vrs_ll%%[ 	]*};vrs_am=${vrs_am%"${vrs_am#??????????}"}
        vrs_ll=${vrs_ll#*[ 	]};vrs_ll=${vrs_ll#"${vrs_ll%%[! 	]*}"}
        vrs_ll=${vrs_ll#*[ 	]};vrs_ll=${vrs_ll#"${vrs_ll%%[! 	]*}"};vrs_au=${vrs_ll%%[ 	]*}
        vrs_ll=${vrs_ll#*[ 	]};vrs_ll=${vrs_ll#"${vrs_ll%%[! 	]*}"}
        vrs_ll=${vrs_ll#*[ 	]};vrs_ll=${vrs_ll#"${vrs_ll%%[! 	]*}"};vrs_sz=${vrs_ll%%[ 	]*}
        case $vrs_ino:$vrs_au:$vrs_sz in
            *[!0-9:]*|:*|*::*|*:) ;;
            *)  if [ "${#vrs_am}" = 10 ]; then
                    if [ "$vrs_sz" -gt 1048576 ]; then printf '%s oversize\n' "$1"; return 0; fi
                    vrs_crc=$(sha256sum < "$2" 2>/dev/null) || { printf '%s bad\n' "$1"; return 0; }
                    vrs_crc=${vrs_crc%% *}
                    case $vrs_crc in ''|*[!0-9a-f]*) printf '%s bad\n' "$1"; return 0 ;; esac
                    [ "${#vrs_crc}" = 64 ] || { printf '%s bad\n' "$1"; return 0; }
                    vrs_mt=$(date -r "$2" +%s 2>/dev/null)
                    case $vrs_mt in ''|*[!0-9]*) printf '%s nostat\n' "$1"; return 0 ;; esac
                    printf '%s %s %s %s %s %s %s\n' "$1" "$vrs_crc" "$vrs_sz" "$vrs_ino" "$vrs_mt" "$vrs_am" "$vrs_au"
                    return 0
                fi ;;
        esac
        vrs_sz=$(wc -c < "$2" 2>/dev/null) || { printf '%s bad\n' "$1"; return 0; }
        if [ "$vrs_sz" -gt 1048576 ]; then printf '%s oversize\n' "$1"; return 0; fi
        vrs_crc=$(sha256sum < "$2" 2>/dev/null) || { printf '%s bad\n' "$1"; return 0; }
        vrs_crc=${vrs_crc%% *}
        case $vrs_crc in ''|*[!0-9a-f]*) printf '%s bad\n' "$1"; return 0 ;; esac
        [ "${#vrs_crc}" = 64 ] || { printf '%s bad\n' "$1"; return 0; }
        # BusyBox on Keenetic has no stat format option: inode from ls -di, mtime seconds from date -r.
        # shellcheck disable=SC2012
        # One fork per field instead of ls|awk pipelines (same fields as awk
        # $1 / substr($1,1,10),$3); multi-line output fails closed as nostat.
        vrs_ino=$(LC_ALL=C ls -di "$2" 2>/dev/null)
        case $vrs_ino in *'
'*) vrs_ino= ;; esac
        vrs_ino=${vrs_ino#"${vrs_ino%%[! 	]*}"};vrs_ino=${vrs_ino%%[ 	]*}
        vrs_mt=$(date -r "$2" +%s 2>/dev/null)
        case $vrs_ino$vrs_mt in ''|*[!0-9]*) printf '%s nostat\n' "$1"; return 0 ;; esac
        # shellcheck disable=SC2012
        vrs_auth=$(LC_ALL=C ls -ldn "$2" 2>/dev/null)
        case $vrs_auth in *'
'*|'') printf '%s nostat\n' "$1"; return 0 ;; esac
        vrs_am=${vrs_auth%%[ 	]*};vrs_am=${vrs_am%"${vrs_am#??????????}"}
        vrs_auth=${vrs_auth#*[ 	]};vrs_auth=${vrs_auth#"${vrs_auth%%[! 	]*}"}
        vrs_auth=${vrs_auth#*[ 	]};vrs_auth=${vrs_auth#"${vrs_auth%%[! 	]*}"}
        vrs_auth="$vrs_am ${vrs_auth%%[ 	]*}"
        printf '%s %s %s %s %s %s\n' "$1" "$vrs_crc" "$vrs_sz" "$vrs_ino" "$vrs_mt" "$vrs_auth"
    }
    # Process budget: a fingerprint covers ~50 inputs and runs twice per
    # consistent read, ~12-19 reads per request. The walk below runs twice:
    # "collect" records the (label, path) list, ONE ls -ldin --full-time and
    # ONE sha256sum then cover the whole set, and "emit" prints exactly the
    # rows vrs_one_file would print (mtime as epoch seconds, as date -r +%s).
    # Any input the batch cannot prove (unsupported option, vanished file,
    # unparsable row, name mismatch) falls back to vrs_one_file for that input.
    # shellcheck disable=SC2154
    vrs_one() {
        vrs_k=$((vrs_k+1))
        if [ "$vrs_fp_mode" = collect ]; then
            eval "vrs_p_$vrs_k=\$2"
            return 0
        fi
        eval "vrs_pp=\${vrs_p_$vrs_k-};vrs_rr=\${vrs_r_$vrs_k-}"
        if [ "$vrs_pp" = "$2" ] && [ -n "$vrs_rr" ]; then printf '%s %s\n' "$1" "$vrs_rr"; return 0; fi
        vrs_one_file "$1" "$2"
    }
    # Epoch seconds of an ls --full-time date/time/zone triple; rc 1 if unparsable.
    vrs_epoch() {
        vrs_ey=${1%%-*};vrs_et=${1#*-};vrs_em=${vrs_et%%-*};vrs_ed=${vrs_et#*-}
        vrs_eh=${2%%:*};vrs_et=${2#*:};vrs_emi=${vrs_et%%:*};vrs_es=${vrs_et#*:};vrs_es=${vrs_es%%.*}
        case $vrs_ey:$vrs_em:$vrs_ed:$vrs_eh:$vrs_emi:$vrs_es in
            [0-9][0-9][0-9][0-9]:[0-9][0-9]:[0-9][0-9]:[0-9][0-9]:[0-9][0-9]:[0-9][0-9]) ;; *) return 1 ;;
        esac
        case $3 in [+-][0-9][0-9][0-9][0-9]) ;; *) return 1 ;; esac
        vrs_ez=${3#?};vrs_ezh=${vrs_ez%??};vrs_ezm=${vrs_ez#??}
        # Strip leading zeros: arithmetic would read them as octal.
        vrs_em=${vrs_em#0};vrs_ed=${vrs_ed#0};vrs_eh=${vrs_eh#0};vrs_emi=${vrs_emi#0};vrs_es=${vrs_es#0}
        vrs_ezh=${vrs_ezh#0};vrs_ezm=${vrs_ezm#0};vrs_ey=${vrs_ey#0};vrs_ey=${vrs_ey#0};vrs_ey=${vrs_ey#0}
        [ "$vrs_em" -ge 1 ] && [ "$vrs_em" -le 12 ] && [ "$vrs_ed" -ge 1 ] && [ "$vrs_ed" -le 31 ] || return 1
        # Days from civil (proleptic Gregorian), integer arithmetic only.
        [ "$vrs_em" -gt 2 ] || vrs_ey=$((vrs_ey-1))
        vrs_era=$((vrs_ey/400));vrs_yoe=$((vrs_ey-vrs_era*400))
        if [ "$vrs_em" -gt 2 ]; then vrs_mp=$((vrs_em-3)); else vrs_mp=$((vrs_em+9)); fi
        vrs_doy=$(((153*vrs_mp+2)/5+vrs_ed-1));vrs_doe=$((vrs_yoe*365+vrs_yoe/4-vrs_yoe/100+vrs_doy))
        vrs_eo=$(((vrs_ezh*60+vrs_ezm)*60));[ "${3%"${3#?}"}" = + ] || vrs_eo=$((0-vrs_eo))
        vrs_ev=$(((vrs_era*146097+vrs_doe-719468)*86400+vrs_eh*3600+vrs_emi*60+vrs_es-vrs_eo))
    }
    # vrs_p_N/vrs_r_N are set through eval below.
    # shellcheck disable=SC2154
    vrs_fp_batch() {
        vrs_n=$vrs_k;vrs_i=0;set --
        while [ "$vrs_i" -lt "$vrs_n" ]; do
            vrs_i=$((vrs_i+1));eval "vrs_pp=\$vrs_p_$vrs_i";eval "vrs_r_$vrs_i="
            [ -e "$vrs_pp" ] || [ -L "$vrs_pp" ] || continue
            [ ! -L "$vrs_pp" ] && [ -f "$vrs_pp" ] && [ -r "$vrs_pp" ] || continue
            case $vrs_pp in /*) ;; *) continue ;; esac
            case $vrs_pp in *'
'*|*\\*) continue ;; esac
            set -- "$@" "$vrs_pp"
        done
        [ "$#" -gt 0 ] || return 0
        # shellcheck disable=SC2012
        vrs_ls=$(LC_ALL=C ls -ldin --full-time "$@" 2>/dev/null) || return 0
        vrs_sum=;vrs_i=0
        while [ "$vrs_i" -lt "$vrs_n" ]; do
            vrs_i=$((vrs_i+1));eval "vrs_pp=\$vrs_p_$vrs_i"
            vrs_row=
            while IFS= read -r vrs_line; do
                vrs_t=${vrs_line#"${vrs_line%%[! ]*}"}
                vrs_ino=${vrs_t%% *};vrs_t=${vrs_t#*[ ]};vrs_t=${vrs_t#"${vrs_t%%[! ]*}"}
                vrs_am=${vrs_t%% *};vrs_t=${vrs_t#*[ ]};vrs_t=${vrs_t#"${vrs_t%%[! ]*}"}
                vrs_t=${vrs_t#*[ ]};vrs_t=${vrs_t#"${vrs_t%%[! ]*}"};vrs_au=${vrs_t%% *}
                vrs_t=${vrs_t#*[ ]};vrs_t=${vrs_t#"${vrs_t%%[! ]*}"}
                vrs_t=${vrs_t#*[ ]};vrs_t=${vrs_t#"${vrs_t%%[! ]*}"};vrs_sz=${vrs_t%% *}
                vrs_t=${vrs_t#*[ ]};vrs_t=${vrs_t#"${vrs_t%%[! ]*}"};vrs_d1=${vrs_t%% *}
                vrs_t=${vrs_t#*[ ]};vrs_t=${vrs_t#"${vrs_t%%[! ]*}"};vrs_d2=${vrs_t%% *}
                vrs_t=${vrs_t#*[ ]};vrs_t=${vrs_t#"${vrs_t%%[! ]*}"};vrs_d3=${vrs_t%% *}
                vrs_t=${vrs_t#*[ ]}
                [ "$vrs_t" = "$vrs_pp" ] || continue
                vrs_am=${vrs_am%"${vrs_am#??????????}"}
                case $vrs_ino:$vrs_au:$vrs_sz in *[!0-9:]*|:*|*::*|*:) break ;; esac
                [ "${#vrs_am}" = 10 ] || break
                case $vrs_am in -*) ;; *) break ;; esac
                vrs_epoch "$vrs_d1" "$vrs_d2" "$vrs_d3" || break
                vrs_row="$vrs_sz $vrs_ino $vrs_ev $vrs_am $vrs_au";break
            done <<EOF
$vrs_ls
EOF
            [ -n "$vrs_row" ] || continue
            if [ "${vrs_row%% *}" -gt 1048576 ]; then eval "vrs_r_$vrs_i=oversize";continue;fi
            eval "vrs_r_$vrs_i=\$vrs_row";vrs_sum="$vrs_sum $vrs_i"
        done
        set --
        for vrs_i in $vrs_sum; do eval "set -- \"\$@\" \"\$vrs_p_$vrs_i\""; done
        [ "$#" -gt 0 ] || return 0
        vrs_ck=$(LC_ALL=C sha256sum "$@" 2>/dev/null) || vrs_ck=
        vrs_left=$vrs_sum
        while IFS= read -r vrs_line; do
            vrs_i=${vrs_left# };vrs_i=${vrs_i%% *};[ -n "$vrs_i" ] || { vrs_left=bad;break; }
            vrs_left=${vrs_left# };vrs_left=${vrs_left#"$vrs_i"}
            eval "vrs_pp=\$vrs_p_$vrs_i;vrs_rr=\$vrs_r_$vrs_i"
            vrs_h=${vrs_line%%  *}
            if [ "${vrs_line#*  }" != "$vrs_pp" ] || [ "${#vrs_h}" != 64 ]; then vrs_left=bad;break;fi
            case $vrs_h in *[!0-9a-f]*) vrs_left=bad;break ;; esac
            eval "vrs_r_$vrs_i=\"\$vrs_h \$vrs_rr\""
        done <<EOF
$vrs_ck
EOF
        if [ -n "${vrs_left# }" ]; then
            # Unproven digest set: every row of this batch uses the per-file path.
            for vrs_i in $vrs_sum; do eval "vrs_r_$vrs_i="; done
        fi
        return 0
    }
    # Directory entries, bounded to 256, names restricted to the identifier charset.
    vrs_dir() {
        vrs_n=0
        for vrs_f in "$2"/*; do
            [ -e "$vrs_f" ] || [ -L "$vrs_f" ] || continue
            vrs_n=$((vrs_n + 1))
            if [ "$vrs_n" -gt 256 ]; then printf '%s:toomany bad\n' "$1"; return 0; fi
            case ${vrs_f##*/} in
                ''|[!A-Za-z0-9]*|*[!A-Za-z0-9_.:-]*) printf '%s:badname bad\n' "$1"; continue ;;
            esac
            vrs_one "$1:${vrs_f##*/}" "$vrs_f"
        done
    }
    vrs_presence() {
        if [ -e "$2" ] || [ -L "$2" ]; then printf '%s present\n' "$1"; fi
    }
    vrs_fingerprint() {
        vrs_fp_mode=collect;vrs_k=0;vrs_fp_walk > /dev/null
        vrs_fp_batch
        vrs_fp_mode=emit;vrs_k=0;vrs_fp_walk
    }
    vrs_fp_walk() {
        vrs_one cfg "$vrs_cfg"
        vrs_one dev "${VWARD_DEVICE_CONFIG:-$vrs_etc/device.conf}"
        vrs_one map "${VWARD_DEVICE_MAP_CACHE:-/tmp/vward-device-map.tsv}"
        vrs_one agh "${VWARD_ROUTING_AGH_DOMAINS:-/nonexistent/vward-agh-domains}"
        vrs_one enabled "$vrs_etc/services/enabled.tsv"
        vrs_one categories "$vrs_etc/services/categories.tsv"
        vrs_one persist "$vrs_state/adaptive-persist.txt"
        vrs_one disabled "$vrs_etc/route-engine/adaptive.disabled"
        vrs_one catalog-fetched "${VWARD_SERVICES_FETCHED:-/opt/var/lib/vward/services/catalog.json}"
        vrs_one catalog-bundled "${VWARD_SERVICES_BUNDLED:-/opt/share/vward/console/services-catalog.json}"
        # Observer-only inputs. A bad/oversize one is soft: it turns that mechanism unknown.
        vrs_one obs-manual "$vrs_state/manual-domains.txt"
        vrs_one obs-adaptive "$vrs_state/adaptive-domains.txt"
        vrs_one obs-forcevpn "$vrs_etc/route-engine/force-vpn.conf"
        vrs_one obs-listsfb "${VWARD_TUNNEL_GUARD_DIR:-/opt/var/lib/vward/tunnel-guard}/lists-fallback"
        vrs_one obs-samples "${VWARD_TUNNEL_QUALITY_DIR:-/tmp/vward-tunnel-quality}/samples.tsv"
        vrs_dir list "$vrs_etc/route-engine/domain-lists"
        vrs_dir owned "$vrs_etc/services/owned"
        # Unfinished recovery evidence: presence only; the reader makes sources unknown.
        for vrs_t in "$vrs_backup"/service-transactions/*/pending; do vrs_presence txn "$vrs_t"; done
        for vrs_t in "$vrs_backup-recovery"/smartdns.*; do vrs_presence smartdns-recovery "$vrs_t"; done
        for vrs_l in $vrs_decision_names; do vrs_one "$vrs_l" "$VWARD_ROUTING_INPUTS/${vrs_l#v2-}.tsv"; done
        if [ -n "$vrs_decision_names" ]; then
            vrs_one obs-agh-image "${VWARD_ROUTING_AGH_IMAGE:-/nonexistent/vward-agh-image}"
            vrs_one obs-smartdns-profile "$vrs_etc/smartdns.conf"
            vrs_dir obs-dnsproof "$vrs_etc/route-engine/domain-lists.dns"
            [ "$vrs_fp_mode" = emit ] || return 0
            vrs_clock=$(vr2_clock_read) || vrs_clock=unknown
            printf '%s\n' "$vrs_clock" | awk '
                NF==2 && length($1)==36 && $1~/^[0-9a-f-]+$/ && $2~/^[0-9]+$/ && length($2)<=10 {ok=1;print "obs-boot",$1}
                END{if(!ok)print "obs-boot unknown"}'
            if [ -r "$VWARD_ROUTING_INPUTS/evidence.tsv" ] && [ -r "$VWARD_ROUTING_INPUTS/context.tsv" ]; then
                # A probe lease is at most the existing native cache window
                # (55 s). No operation or persisted 'fresh' extends it.
                awk -F'\t' -v clock="$vrs_clock" 'BEGIN{split(clock,c," ");valid=(length(c[1])==36 && c[1]~/^[0-9a-f-]+$/ && c[2]~/^[0-9]+$/ && length(c[2])<=10)}
                    FILENAME==ARGV[1]{if(NF!=2 || seen[$1]++)bad=1;ctx[$1]=$2;next}
                    $1=="A" && $2~/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/ && length($2)<=64 {
                        r=$2;s="history"
                        if($8=="active" || $8=="positive") {
                            s="unknown";b=ctx["probe-boot:" r];u=ctx["probe-until:" r]
                            if(!bad && valid && length(b)==36 && b~/^[0-9a-f-]+$/ && u~/^[0-9]+$/ && length(u)<=10) {
                                if(b!=c[1])s="old-boot"
                                else if(u+0<=c[2]+0)s="expired"
                                else if(u+0-c[2]<=55 && ctx["probe:" r]=="fresh")s="fresh"
                            }
                        }
                        print "obs-probe:" r,s
                    }' "$VWARD_ROUTING_INPUTS/context.tsv" "$VWARD_ROUTING_INPUTS/evidence.tsv" | LC_ALL=C sort
            fi
        fi
    }

    vrs_decision_names=;vrs_aux_names=
    if [ -n "${VWARD_ROUTING_INPUTS:-}" ]; then
        case $VWARD_ROUTING_INPUTS in /*) ;; *) return 2 ;; esac
        # shellcheck disable=SC2012
        [ -d "$VWARD_ROUTING_INPUTS" ] && [ ! -L "$VWARD_ROUTING_INPUTS" ] && [ -O "$VWARD_ROUTING_INPUTS" ] &&
            [ "$(ls -ldn "$VWARD_ROUTING_INPUTS" | awk '{print substr($1,1,10)}')" = drwx------ ] || return 2
        vrs_decision_names='v2-version v2-choices v2-bindings v2-evidence v2-policies v2-saved v2-queue v2-tombstones v2-context v2-resources v2-proofs v2-upstreams'
        vrs_aux_names=obs-agh-image
    fi
    vrs_start=$(date +%s) || return 2
    vrs_fingerprint > "$vrs_tmp/fp.before" || return 2
    # Literal awk field expressions, not shell expansion.
    # shellcheck disable=SC2016
    vrs_fatal='$2=="nostat" || ($1 ~ /^v2-/ && $2=="absent") || (($2=="bad" || $2=="oversize") && $1 !~ /^obs-/)'
    if [ "$vrs_read_kind" = legacy-observation ]; then
        # Read-only observation of absent/partial bootstrap data. This is NOT
        # usable state2: its staged version is forced to observation0 below.
        # shellcheck disable=SC2016
        vrs_fatal='$2=="nostat" || (($2=="bad" || $2=="oversize") && $1 !~ /^obs-/)'
    fi
    if awk "$vrs_fatal {f=1} END{exit f?0:1}" "$vrs_tmp/fp.before"; then
        # Which input: label only (never a path), enough to find it.
        vrs_unknown "input-unreadable:$(awk "$vrs_fatal {print \$1; exit}" "$vrs_tmp/fp.before")"
        return 3
    fi
    # Freshness of the shared cache (necessary, not sufficient). Missing cache is
    # reported as such: the reader would show an unknown source, not an empty one.
    if awk '$1=="cfg" && $2=="absent" {f=1} END{exit f?0:1}' "$vrs_tmp/fp.before"; then
        vrs_unknown config-cache-missing; return 3
    fi
    vrs_mtime=$(awk '$1=="cfg" {print $5}' "$vrs_tmp/fp.before")
    vrs_age=$(( $(date +%s) - vrs_mtime ))
    if [ "$vrs_age" -lt 0 ] || [ "$vrs_age" -ge "$vrs_max_age" ]; then
        vrs_unknown config-cache-stale; return 3
    fi

    # Verified copies for the observers. Every copy must match the fingerprint taken
    # BEFORE copying (content CRC+size); the originals are re-fingerprinted afterwards.
    vrs_stage=$vrs_tmp/stage
    mkdir "$vrs_stage" || return 2
    : > "$vrs_stage/STATE" || return 2
    vrs_verify=
    for vrs_l in cfg dev map agh enabled categories persist catalog-fetched catalog-bundled \
        obs-manual obs-adaptive obs-forcevpn obs-listsfb obs-samples $vrs_decision_names $vrs_aux_names; do
        case $vrs_l in
            cfg) vrs_src=$vrs_cfg ;;
            dev) vrs_src=${VWARD_DEVICE_CONFIG:-$vrs_etc/device.conf} ;;
            map) vrs_src=${VWARD_DEVICE_MAP_CACHE:-/tmp/vward-device-map.tsv} ;;
            agh) vrs_src=${VWARD_ROUTING_AGH_DOMAINS:-/nonexistent/vward-agh-domains} ;;
            enabled) vrs_src=$vrs_etc/services/enabled.tsv ;;
            categories) vrs_src=$vrs_etc/services/categories.tsv ;;
            persist) vrs_src=$vrs_state/adaptive-persist.txt ;;
            catalog-fetched) vrs_src=${VWARD_SERVICES_FETCHED:-/opt/var/lib/vward/services/catalog.json} ;;
            catalog-bundled) vrs_src=${VWARD_SERVICES_BUNDLED:-/opt/share/vward/console/services-catalog.json} ;;
            obs-manual) vrs_src=$vrs_state/manual-domains.txt ;;
            obs-adaptive) vrs_src=$vrs_state/adaptive-domains.txt ;;
            obs-forcevpn) vrs_src=$vrs_etc/route-engine/force-vpn.conf ;;
            obs-listsfb) vrs_src=${VWARD_TUNNEL_GUARD_DIR:-/opt/var/lib/vward/tunnel-guard}/lists-fallback ;;
            obs-samples) vrs_src=${VWARD_TUNNEL_QUALITY_DIR:-/tmp/vward-tunnel-quality}/samples.tsv ;;
            obs-agh-image) vrs_src=${VWARD_ROUTING_AGH_IMAGE:-/nonexistent/vward-agh-image} ;;
            obs-smartdns-profile) vrs_src=$vrs_etc/smartdns.conf ;;
            obs-dnsproof:*) vrs_src=$vrs_etc/route-engine/domain-lists.dns/${vrs_l#obs-dnsproof:} ;;
            v2-*) vrs_src=$VWARD_ROUTING_INPUTS/${vrs_l#v2-}.tsv ;;
        esac
        # First row whose first field is the label (as awk $1==l; print; exit).
        vrs_row=
        while IFS= read -r vrs_line; do
            [ "${vrs_line%%[ 	]*}" = "$vrs_l" ] || continue
            vrs_row=$vrs_line;break
        done < "$vrs_tmp/fp.before"
        # shellcheck disable=SC2086
        set -- $vrs_row
        case ${2:-} in
            absent) printf '%s\tabsent\n' "$vrs_l" >> "$vrs_stage/STATE" ;;
            bad|oversize) printf '%s\t%s\n' "$vrs_l" "$2" >> "$vrs_stage/STATE" ;;
            '') vrs_unknown "stage-state:$vrs_l"; return 3 ;;
            *)
                if [ -L "$vrs_src" ] || [ ! -f "$vrs_src" ] || ! cp "$vrs_src" "$vrs_stage/$vrs_l" 2>/dev/null; then
                    vrs_unknown changed-during-read; return 3
                fi
                # Verified below with ONE sha256sum and ONE wc for all copies.
                vrs_verify="$vrs_verify$vrs_l $2 $3
"
                printf '%s\tok\n' "$vrs_l" >> "$vrs_stage/STATE" ;;
        esac
    done
    set --
    vrs_want=
    while IFS=' ' read -r vrs_l vrs_h vrs_sz; do
        [ -n "$vrs_l" ] || continue
        set -- "$@" "$vrs_stage/$vrs_l";vrs_want="$vrs_want$vrs_h:$vrs_sz "
    done <<EOF
$vrs_verify
EOF
    if [ "$#" -gt 0 ]; then
        vrs_ck=$(LC_ALL=C sha256sum "$@" 2>/dev/null) || { vrs_unknown changed-during-read; return 3; }
        vrs_wc=$(LC_ALL=C wc -c "$@" 2>/dev/null) || { vrs_unknown changed-during-read; return 3; }
        vrs_left=$vrs_want;vrs_n=0
        while IFS= read -r vrs_line; do
            [ "$vrs_n" -lt "$#" ] || break;vrs_n=$((vrs_n+1))
            vrs_e=${vrs_left%% *};vrs_left=${vrs_left#* }
            [ "${vrs_line%%  *}" = "${vrs_e%%:*}" ] || { vrs_unknown changed-during-read; return 3; }
        done <<EOF
$vrs_ck
EOF
        [ "$vrs_n" -eq "$#" ] && [ -z "$vrs_left" ] || { vrs_unknown changed-during-read; return 3; }
        vrs_left=$vrs_want;vrs_n=0
        while IFS= read -r vrs_line; do
            [ "$vrs_n" -lt "$#" ] || break;vrs_n=$((vrs_n+1))
            vrs_e=${vrs_left%% *};vrs_left=${vrs_left#* }
            vrs_line=${vrs_line#"${vrs_line%%[! 	]*}"};vrs_line=${vrs_line%%[ 	]*}
            case $vrs_line in ''|*[!0-9]*) vrs_unknown changed-during-read; return 3 ;; esac
            [ "$vrs_line" -eq "${vrs_e#*:}" ] || { vrs_unknown changed-during-read; return 3; }
        done <<EOF
$vrs_wc
EOF
        [ "$vrs_n" -eq "$#" ] && [ -z "$vrs_left" ] || { vrs_unknown changed-during-read; return 3; }
    fi
    set --

    # Content + authority, excluding inode/time: stable across reboot, but a
    # revoked private proof cannot retain its former generation.
    vrs_gen=$(awk '{print $1, $2, $3, $6, $7}' "$vrs_tmp/fp.before" | LC_ALL=C awk '
        BEGIN {for(c=32;c<127;c++) ord[sprintf("%c",c)]=c; hd="0123456789abcdef"}
        function hex8(n, i,r) {r=""; for(i=0;i<8;i++) {r=substr(hd,(n%16)+1,1) r; n=int(n/16)} return r}
        {s=s $0 "\n"}
        END {
            a=5381; b=52711
            for(i=1;i<=length(s);i++) {c=ord[substr(s,i,1)]; if(c=="") c=63; a=(a*131+c)%4294967291; b=(b*257+c+i)%4294967279}
            print "g-" hex8(a) hex8(b)
        }') || return 2
    case $vrs_gen in g-????????????????) ;; *) vrs_unknown generation-failed; return 3 ;; esac

    vrs_modes='intents snapshot identity'
    [ -z "$vrs_decision_names" ] || vrs_modes="$vrs_modes inventory"
    for vrs_mode in $vrs_modes; do
        vward_routing_read "$vrs_mode" > "$vrs_tmp/$vrs_mode.tsv" 2> "$vrs_tmp/$vrs_mode.err" || { vrs_unknown "reader-failed:$vrs_mode"; return 3; }
        if [ "$(wc -c < "$vrs_tmp/$vrs_mode.tsv")" -gt 1048576 ]; then vrs_unknown "output-oversize:$vrs_mode"; return 3; fi
    done
    # Read-only observers of the five mechanisms, on the verified stage only.
    vward_routing_observe "$vrs_stage" "$vrs_tmp" "$vrs_gen" "$vrs_start" > "$vrs_tmp/legacy.tsv" 2> "$vrs_tmp/legacy.err" || { vrs_unknown observer-failed; return 3; }
    if [ "$(wc -c < "$vrs_tmp/legacy.tsv")" -gt 1048576 ]; then vrs_unknown output-oversize:legacy; return 3; fi
    if [ $(( $(date +%s) - vrs_start )) -gt "$vrs_limit" ]; then vrs_unknown timeout; return 3; fi

    vrs_fingerprint > "$vrs_tmp/fp.after" || return 2
    cmp -s "$vrs_tmp/fp.before" "$vrs_tmp/fp.after" || { vrs_unknown changed-during-read; return 3; }

    # The three projections must describe the same records.
    if ! LC_ALL=C awk -F'\t' '
        FILENAME==ARGV[1] {i[$2]=1; next}
        FILENAME==ARGV[2] {if($1=="route") s[$2]=1; next}
        {d[$1]=1}
        END {
            for(k in i) if(!(k in d)) bad=1
            for(k in s) if(!(k in d)) bad=1
            for(k in d) if(!(k in i) && !(k in s)) bad=1
            exit bad?1:0
        }' "$vrs_tmp/intents.tsv" "$vrs_tmp/snapshot.tsv" "$vrs_tmp/identity.tsv"; then
        vrs_unknown inconsistent-projections; return 3
    fi

    if ! LC_ALL=C awk -v g="$vrs_gen" 'BEGIN{FS=OFS="\t"}
        $1=="snapshot" && $2=="legacy-read" && $3=="unknown" && !n {print "snapshot", g, "known"; n=1; next}
        $1=="snapshot" {bad=1}
        {print}
        END {exit (n==1 && !bad) ? 0 : 1}' "$vrs_tmp/snapshot.tsv" > "$vrs_tmp/snapshot.final"; then
        vrs_unknown snapshot-header; return 3
    fi
    mv "$vrs_tmp/snapshot.final" "$vrs_tmp/snapshot.tsv" || return 2
    for vrs_name in $vrs_modes legacy; do
        mv "$vrs_tmp/$vrs_name.tsv" "$vrs_out/$vrs_name.tsv" || { rm -f "$vrs_out/intents.tsv" "$vrs_out/snapshot.tsv" "$vrs_out/identity.tsv" "$vrs_out/legacy.tsv"; return 2; }
    done
    if [ -n "$vrs_decision_names" ]; then
        cp "$vrs_tmp/fp.before" "$vrs_out/inputs.fp" || return 2
        awk '$1~/^obs-probe:/{sub(/^obs-probe:/,"",$1);print $1 "\t" $2}' "$vrs_tmp/fp.before" > "$vrs_out/probes.tsv" || return 2
        cp "$vrs_stage/cfg" "$vrs_out/native.cfg" || return 2
        if [ -f "$vrs_stage/obs-agh-image" ]; then cp "$vrs_stage/obs-agh-image" "$vrs_out/agh.json" || return 2
        else printf '%s\n' '{"unknown":true}' > "$vrs_out/agh.json";fi
        if [ -f "$vrs_stage/enabled" ]; then cp "$vrs_stage/enabled" "$vrs_out/enabled.tsv" || return 2
        else : > "$vrs_out/enabled.tsv";fi
        awk '/^object-group fqdn / && NF==3 {print $3}' "$vrs_stage/cfg" | LC_ALL=C sort -u > "$vrs_out/groups.tsv" || return 2
        (umask 077; mkdir "$vrs_out/decision") || return 2
        for vrs_l in $vrs_decision_names; do
            if [ -f "$vrs_stage/$vrs_l" ]; then
                mv "$vrs_stage/$vrs_l" "$vrs_out/decision/${vrs_l#v2-}.tsv" || return 2
            elif [ "$vrs_read_kind" = legacy-observation ]; then
                : > "$vrs_out/decision/${vrs_l#v2-}.tsv" || return 2
                [ "$vrs_l" != v2-choices ] || printf 'schema\t1\n' > "$vrs_out/decision/choices.tsv"
            else return 2;fi
        done
        if [ "$vrs_read_kind" = legacy-observation ]; then printf 'routing-state\t0\n' > "$vrs_out/decision/version.tsv" || return 2;fi
        printf 'routing-stage\t2\t%s\n' "$vrs_gen" > "$vrs_out/seal" || return 2
        vrs_names='intents.tsv snapshot.tsv identity.tsv legacy.tsv inventory.tsv groups.tsv native.cfg enabled.tsv agh.json inputs.fp probes.tsv
            decision/version.tsv decision/choices.tsv decision/bindings.tsv decision/evidence.tsv
            decision/policies.tsv decision/saved.tsv decision/queue.tsv decision/tombstones.tsv
            decision/context.tsv decision/resources.tsv decision/proofs.tsv decision/upstreams.tsv'
        # ONE sha256sum for the closed name set (was one per file, every read).
        # Rows must come back in argument order with exactly these names.
        # shellcheck disable=SC2086
        vrs_ck=$(cd "$vrs_out" && LC_ALL=C sha256sum $vrs_names) || return 2
        # shellcheck disable=SC2086
        vrs_want=$(printf '%s ' $vrs_names)
        while IFS=' 	' read -r vrs_h vrs_name vrs_rest; do
            [ "$vrs_name" = "${vrs_want%% *}" ] && [ -z "$vrs_rest" ] && [ "${#vrs_h}" = 64 ] || return 2
            case $vrs_h in *[!0-9a-f]*) return 2 ;; esac
            printf '%s\t%s\n' "$vrs_h" "$vrs_name" >> "$vrs_out/seal" || return 2
            vrs_want=${vrs_want#* }
        done <<EOF
$vrs_ck
EOF
        [ -z "$vrs_want" ] || return 2
        vrs_ck=$(sha256sum < "$vrs_out/seal") || return 2
        printf '%s\n' "${vrs_ck%% *}" > "$vrs_out/seal.sha" || return 2
    fi
    # The marker is written last: no marker, no valid snapshot.
    printf '%s\n' "$vrs_gen" > "$vrs_out/generation" || { rm -f "$vrs_out/intents.tsv" "$vrs_out/snapshot.tsv" "$vrs_out/identity.tsv" "$vrs_out/legacy.tsv"; return 2; }
    printf 'ok\t%s\n' "$vrs_gen"
)

# Same native snapshot AND decision inputs under the SAME content generation.
# Data are staged, not declared semantically valid here: policy/plan validates schemas.
# No new live reader, configuration refresh, transport or installed-state writer.
vward_routing_consistent_read() (
    [ "$#" -eq 1 ] || return 2
    vrsi_consistent_read "$1" strict
)
vward_routing_consistent_read2() (
    [ "$#" -eq 2 ] || return 2
    VWARD_ROUTING_INPUTS=$2
    export VWARD_ROUTING_INPUTS
    vrsi_consistent_read "$1" strict
)
# Observes a legacy bootstrap only. It always emits version0, including after
# a partial/final version marker, so ordinary project2 cannot grant authority.
# No environment switch selects this adapter or authorises a writer.
vward_routing_bootstrap_read2() (
    [ "$#" -eq 2 ] || return 2
    VWARD_ROUTING_INPUTS=$2
    export VWARD_ROUTING_INPUTS
    vrsi_consistent_read "$1" legacy-observation
)
