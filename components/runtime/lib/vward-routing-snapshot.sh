#!/bin/sh
# RS-6: consistent read coordinator. Defines ONE function; loading does nothing.
#
#   vward_routing_consistent_read OUTDIR
#
# OUTDIR: absolute, existing, private (0700), owned by the caller, not a symlink.
# On success writes intents.tsv, snapshot.tsv and identity.tsv (all produced from
# ONE verified input set) and, last, the file `generation`; stdout `ok<TAB>GEN`,
# rc 0. A directory is valid only while `generation` exists.
# If a correct snapshot cannot be proven: NO output file is left, stdout is
# `unknown<TAB>REASON`, rc 3. Usage/environment errors: rc 2 (stderr).
#
# Consistency is proved, not assumed: every input is fingerprinted (content CRC+
# size, inode, mtime) before AND after the three projections are read; any
# difference -> unknown. The generation is a hash of the CONTENT fingerprints only,
# so the same data gives the same generation after a reboot. It is still not a
# live-router proof: it covers the files and the shared Keenetic cache the
# projections are derived from. The cache is never refreshed here (no ndmc/RCI).
# No daemon, no timer, no background process, nothing outside OUTDIR is written.
vward_routing_consistent_read() (
    [ "$#" = 1 ] || return 2
    command -v vward_routing_read >/dev/null 2>&1 || { printf '%s\n' 'routing snapshot: reader not loaded' >&2; return 2; }
    vrs_out=$1
    case $vrs_out in /*) ;; *) printf '%s\n' 'routing snapshot: absolute OUTDIR required' >&2; return 2 ;; esac
    if [ -L "$vrs_out" ] || [ ! -d "$vrs_out" ] || [ ! -O "$vrs_out" ] || [ ! -w "$vrs_out" ] ||
        [ "$(ls -ldn "$vrs_out" 2>/dev/null | awk '{print substr($1,1,10)}')" != drwx------ ]; then
        printf '%s\n' 'routing snapshot: OUTDIR must be a private directory owned by the caller' >&2
        return 2
    fi
    # A previous result must never survive a failed attempt.
    rm -f "$vrs_out/generation" "$vrs_out/intents.tsv" "$vrs_out/snapshot.tsv" "$vrs_out/identity.tsv" 2>/dev/null
    vrs_tmp=$(umask 077; mktemp -d "$vrs_out/.read.XXXXXX" 2>/dev/null) || return 2
    trap 'rm -rf "$vrs_tmp"' EXIT
    trap 'exit 3' HUP INT TERM

    vrs_unknown() { printf 'unknown\t%s\n' "$1"; return 3; }

    # Same inputs and defaults as vward_routing_read (read-only mirror).
    vrs_etc=${VWARD_CONSOLE_ETC:-/opt/etc/vward}
    vrs_state=${VWARD_ROUTE_STATE:-/opt/var/lib/vward/route-engine}
    vrs_cfg=${VWARD_KCACHE:-${VWARD_ROOT_PREFIX:-}/tmp/vward-keenetic}/running-config
    vrs_backup=${VWARD_CONSOLE_BACKUP_DIR:-/opt/var/backups/vward/console-config}
    vrs_max_age=${VWARD_ROUTING_CACHE_AGE:-${VWARD_KEENETIC_AGE:-20}}
    vrs_limit=${VWARD_ROUTING_READ_TIMEOUT:-10}
    case $vrs_max_age$vrs_limit in ''|*[!0-9]*) return 2 ;; esac

    # One line per input: LABEL STATE. STATE: absent | bad | oversize | nostat |
    # "CRC SIZE INODE MTIME". Labels never contain a host path.
    vrs_one() {
        if [ ! -e "$2" ] && [ ! -L "$2" ]; then printf '%s absent\n' "$1"; return 0; fi
        if [ -L "$2" ] || [ ! -f "$2" ] || [ ! -r "$2" ]; then printf '%s bad\n' "$1"; return 0; fi
        vrs_sz=$(wc -c < "$2" 2>/dev/null) || { printf '%s bad\n' "$1"; return 0; }
        if [ "$vrs_sz" -gt 1048576 ]; then printf '%s oversize\n' "$1"; return 0; fi
        vrs_crc=$(cksum < "$2" 2>/dev/null) || { printf '%s bad\n' "$1"; return 0; }
        # BusyBox on Keenetic has no stat format option: inode from ls -di, mtime seconds from date -r.
        vrs_ino=$(ls -di "$2" 2>/dev/null | awk '{print $1}')
        vrs_mt=$(date -r "$2" +%s 2>/dev/null)
        case $vrs_ino$vrs_mt in ''|*[!0-9]*) printf '%s nostat\n' "$1"; return 0 ;; esac
        printf '%s %s %s %s\n' "$1" "$vrs_crc" "$vrs_ino" "$vrs_mt"
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
        vrs_dir list "$vrs_etc/route-engine/domain-lists"
        vrs_dir owned "$vrs_etc/services/owned"
        # Unfinished recovery evidence: presence only; the reader makes sources unknown.
        for vrs_t in "$vrs_backup"/service-transactions/*/pending; do vrs_presence txn "$vrs_t"; done
        for vrs_t in "$vrs_backup-recovery"/smartdns.*; do vrs_presence smartdns-recovery "$vrs_t"; done
    }

    vrs_start=$(date +%s) || return 2
    vrs_fingerprint > "$vrs_tmp/fp.before" || return 2
    if awk '$2=="bad" || $2=="oversize" || $2=="nostat" {f=1} END{exit f?0:1}' "$vrs_tmp/fp.before"; then
        # Which input: label only (never a path), enough to find it.
        vrs_unknown "input-unreadable:$(awk '$2=="bad" || $2=="oversize" || $2=="nostat" {print $1; exit}' "$vrs_tmp/fp.before")"
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

    for vrs_mode in intents snapshot identity; do
        vward_routing_read "$vrs_mode" > "$vrs_tmp/$vrs_mode.tsv" 2> "$vrs_tmp/$vrs_mode.err" || { vrs_unknown "reader-failed:$vrs_mode"; return 3; }
        if [ "$(wc -c < "$vrs_tmp/$vrs_mode.tsv")" -gt 1048576 ]; then vrs_unknown "output-oversize:$vrs_mode"; return 3; fi
    done
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

    # Generation: content-only fingerprint (no inode/time), stable across reboot.
    vrs_gen=$(awk '{print $1, $2, $3}' "$vrs_tmp/fp.after" | LC_ALL=C awk '
        BEGIN {for(c=32;c<127;c++) ord[sprintf("%c",c)]=c; hd="0123456789abcdef"}
        function hex8(n, i,r) {r=""; for(i=0;i<8;i++) {r=substr(hd,(n%16)+1,1) r; n=int(n/16)} return r}
        {s=s $0 "\n"}
        END {
            a=5381; b=52711
            for(i=1;i<=length(s);i++) {c=ord[substr(s,i,1)]; if(c=="") c=63; a=(a*131+c)%4294967291; b=(b*257+c+i)%4294967279}
            print "g-" hex8(a) hex8(b)
        }') || return 2
    case $vrs_gen in g-????????????????) ;; *) vrs_unknown generation-failed; return 3 ;; esac

    if ! LC_ALL=C awk -v g="$vrs_gen" 'BEGIN{FS=OFS="\t"}
        $1=="snapshot" && $2=="legacy-read" && $3=="unknown" && !n {print "snapshot", g, "known"; n=1; next}
        $1=="snapshot" {bad=1}
        {print}
        END {exit (n==1 && !bad) ? 0 : 1}' "$vrs_tmp/snapshot.tsv" > "$vrs_tmp/snapshot.final"; then
        vrs_unknown snapshot-header; return 3
    fi
    mv "$vrs_tmp/snapshot.final" "$vrs_tmp/snapshot.tsv" || return 2
    for vrs_name in intents snapshot identity; do
        mv "$vrs_tmp/$vrs_name.tsv" "$vrs_out/$vrs_name.tsv" || { rm -f "$vrs_out/intents.tsv" "$vrs_out/snapshot.tsv" "$vrs_out/identity.tsv"; return 2; }
    done
    # The marker is written last: no marker, no valid snapshot.
    printf '%s\n' "$vrs_gen" > "$vrs_out/generation" || { rm -f "$vrs_out/intents.tsv" "$vrs_out/snapshot.tsv" "$vrs_out/identity.tsv"; return 2; }
    printf 'ok\t%s\n' "$vrs_gen"
)
