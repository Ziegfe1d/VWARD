#!/bin/sh
# VWARD external-package lifecycle (Entware). Defines functions only; loading does nothing.
# Part of Update Engine 2.0's managed path for EXTERNAL packages: VWARD's own signed files
# keep their own path; this file never widens VWARD's signed ownership to Entware files.
#
#   vward_entware_status  PKG                      installed version, arch, service state
#   vward_entware_check   PKG INDEX                candidate from an Entware Packages index
#   vward_entware_inspect PKG IPK INDEX            integrity, control, scripts, file list
#   vward_entware_apply   PKG IPK INDEX MODE       install/upgrade ONE package (MODE manual|auto)
#   vward_entware_recover PKG                      after TERM/SIGKILL/power loss: classify only
#   vward_entware_gate                             rc 0 clear, 75 an operation is unresolved
#   vward_entware_allowed check|download|apply     owner permissions (all off by default)
#
# Only allow-listed packages (dnsmasq-full, sing-box-go). Never `opkg upgrade`, never a
# dependency pulled implicitly (every dependency must already be installed), never another
# package touched or restarted. A package is installed DISABLED: its init scripts are set to
# ENABLED=no and it must not be running afterwards. Apply is refused unless the owner switch
# VWARD_ENTWARE_APPLY=1 is set (off by default) - nothing in VWARD calls it yet.
# Root: ${VWARD_ROOT_PREFIX:-}/opt (an emulated root in tests); opkg is "$ROOT/opt/bin/opkg".
# rc: 0 ok; 1 failed and restored; 2 usage/invalid; 3 unknown (state kept, gate closed);
#     75 refused (switch/permission, not allow-listed, unsafe, gate closed, busy).

vwe_root() { VWE_R=${VWARD_ROOT_PREFIX:-}; VWE_OPKG=$VWE_R/opt/bin/opkg; VWE_DB=$VWE_R/opt/lib/opkg
    VWE_STATE=$VWE_R/opt/var/lib/vward/entware; VWE_CACHE=$VWE_R/opt/var/cache/vward/entware; }

# Allow-list: package -> daemon binary path (relative to root) used to detect a running copy.
vwe_known() {
    case $1 in
        dnsmasq-full) VWE_BIN=/opt/sbin/dnsmasq ;;
        sing-box-go) VWE_BIN=/opt/bin/sing-box ;;
        *) return 1 ;;
    esac
}

vward_entware_allowed() (
    vwe_root
    case $1 in check|download|apply) ;; *) return 2 ;; esac
    f=$VWE_R/opt/etc/vward/entware.conf
    [ -f "$f" ] && [ ! -L "$f" ] || return 75
    [ "$(awk -F= -v k="auto_$1" '$1 == k {v = $2} END {print v}' "$f")" = 1 ] || return 75
)

# One stanza of an opkg status / Packages file: prints "Field<TAB>value" lines.
vwe_stanza() {
    awk -v p="$1" '
        /^Package: / {cur = ($2 == p); if (cur) n++}
        cur && /^[A-Za-z0-9-]+: / {k = $1; sub(/:$/, "", k); v = substr($0, length($1) + 2); print k "\t" v}
        /^$/ {cur = 0}
        END {exit n == 1 ? 0 : 1}' "$2"
}
vwe_field() { printf '%s\n' "$1" | awk -F'\t' -v k="$2" '$1 == k {print $2; exit}'; }

# A running copy: any process whose argv[0] is exactly the package's daemon path (/proc, so a
# long command line is never cut off as with `ps w`).
vwe_running() {
    for vwe_p in /proc/[0-9]*; do
        [ -r "$vwe_p/cmdline" ] || continue
        [ "$(tr '\000' '\n' < "$vwe_p/cmdline" 2>/dev/null | head -n 1)" = "$VWE_R$VWE_BIN" ] && return 0
    done
    return 1
}

# Init scripts owned by the package (from its own file list).
vwe_inits() { [ -f "$VWE_DB/info/$1.list" ] && grep -E '^/opt/etc/init\.d/S[0-9]+' "$VWE_DB/info/$1.list"; }

vward_entware_status() (
    [ "$#" -eq 1 ] || return 2
    vwe_root; vwe_known "$1" || return 75
    st=$(vwe_stanza "$1" "$VWE_DB/status" 2>/dev/null) || st=
    case $(vwe_field "$st" Status) in
        *" installed") ;;
        *) printf '%s\tabsent\t-\t-\toff\n' "$1"; return 0 ;;
    esac
    svc=off
    for i in $(vwe_inits "$1"); do
        grep -q '^ENABLED=yes' "$VWE_R$i" 2>/dev/null && svc=enabled
    done
    vwe_running && svc=running
    printf '%s\tinstalled\t%s\t%s\t%s\n' "$1" "$(vwe_field "$st" Version)" "$(vwe_field "$st" Architecture)" "$svc"
)

# Accepted architectures: the device's own opkg.conf (`arch NAME PRIORITY`).
vwe_archs() { awk '$1 == "arch" && NF >= 2 {print $2}' "$VWE_R/opt/etc/opkg.conf" 2>/dev/null; }

vward_entware_check() (
    [ "$#" -eq 2 ] || return 2
    vwe_root; vwe_known "$1" || return 75
    [ -f "$2" ] && [ ! -L "$2" ] && [ "$(wc -c < "$2")" -le 8388608 ] || return 2
    st=$(vwe_stanza "$1" "$2") || { printf '%s\trefuse\tnot-in-index\n' "$1"; return 75; }
    ver=$(vwe_field "$st" Version); arch=$(vwe_field "$st" Architecture)
    sha=$(vwe_field "$st" SHA256sum); size=$(vwe_field "$st" Size)
    case $sha in *[!0-9a-f]*|'') printf '%s\trefuse\tno-sha256\n' "$1"; return 75 ;; esac
    [ "${#sha}" = 64 ] || { printf '%s\trefuse\tno-sha256\n' "$1"; return 75; }
    case $size in ''|*[!0-9]*) printf '%s\trefuse\tno-size\n' "$1"; return 75 ;; esac
    vwe_archs | grep -qx "$arch" || { printf '%s\trefuse\tarch-%s\n' "$1" "$arch"; return 75; }
    # Every dependency must already be installed: nothing is pulled in implicitly.
    for d in $(vwe_field "$st" Depends | tr ',' '\n' | sed 's/(.*//; s/^ *//; s/ *$//'); do
        case $(vwe_field "$(vwe_stanza "$d" "$VWE_DB/status" 2>/dev/null)" Status) in
            *" installed") ;;
            *) printf '%s\trefuse\tmissing-dependency-%s\n' "$1" "$d"; return 75 ;;
        esac
    done
    cur=$(vward_entware_status "$1" | cut -f3)
    printf '%s\tcandidate\t%s\t%s\t%s\t%s\t%s\n' "$1" "$cur" "$ver" "$arch" "$size" "$sha"
)

# Integrity and content of a downloaded .ipk (gzip tar: debian-binary, control.tar.gz, data.tar.gz).
vward_entware_inspect() (
    [ "$#" -eq 3 ] || return 2
    vwe_root; vwe_known "$1" || return 75
    [ -f "$2" ] && [ ! -L "$2" ] || return 2
    line=$(vward_entware_check "$1" "$3") || { printf '%s\n' "$line"; return 75; }
    want_sha=$(printf '%s' "$line" | cut -f7); want_size=$(printf '%s' "$line" | cut -f6)
    [ "$(wc -c < "$2")" = "$want_size" ] || { printf '%s\trefuse\tsize-mismatch\n' "$1"; return 75; }
    got=$(sha256sum < "$2"); got=${got%% *}
    [ "$got" = "$want_sha" ] || { printf '%s\trefuse\tsha256-mismatch\n' "$1"; return 75; }
    t=$(umask 077; mktemp -d "${TMPDIR:-/tmp}/vward-ipk.XXXXXX") || return 2
    trap 'rm -rf "$t"' EXIT
    (cd "$t" && tar -xzf "$2" ./control.tar.gz ./data.tar.gz 2>/dev/null || tar -xzf "$2" control.tar.gz data.tar.gz) 2>/dev/null ||
        { printf '%s\trefuse\tcorrupt-package\n' "$1"; return 75; }
    mkdir "$t/c" && tar -xzf "$t/control.tar.gz" -C "$t/c" 2>/dev/null || { printf '%s\trefuse\tcorrupt-control\n' "$1"; return 75; }
    cf=$(find "$t/c" -name control -type f | head -n 1)
    [ -n "$cf" ] && [ "$(sed -n 's/^Package: //p' "$cf")" = "$1" ] || { printf '%s\trefuse\tcontrol-mismatch\n' "$1"; return 75; }
    [ "$(sed -n 's/^Version: //p' "$cf")" = "$(printf '%s' "$line" | cut -f4)" ] || { printf '%s\trefuse\tversion-mismatch\n' "$1"; return 75; }
    # Maintainer scripts must not start, restart or enable a service on their own.
    for s in preinst postinst prerm postrm; do
        sf=$(find "$t/c" -name "$s" -type f | head -n 1)
        [ -n "$sf" ] || continue
        if grep -Eq '(/opt/etc/init\.d/S[0-9A-Za-z_.-]+|service|rc\.unslung)[[:space:]]+(start|restart|enable|reload)|(start-stop-daemon|nohup)|^[[:space:]]*/opt/s?bin/[A-Za-z0-9_.-]+[[:space:]]+-' "$sf"; then
            printf '%s\trefuse\tscript-starts-service-%s\n' "$1" "$s"; return 75
        fi
    done
    # Payload: only under /opt, never a VWARD-owned path, never outside the root.
    tar -tzf "$t/data.tar.gz" 2>/dev/null > "$t/files" || { printf '%s\trefuse\tcorrupt-data\n' "$1"; return 75; }
    if awk '{p = $0; sub(/^\.\//, "/", p)} p !~ /^\/opt(\/|$)/ || p ~ /\.\./ || p ~ /^\/opt\/bin\/vward-/ || p ~ /^\/opt\/lib\/vward\// || p ~ /^\/opt\/share\/vward\// || p ~ /^\/opt\/etc\/init\.d\/S..vward-/ {bad = 1} END {exit bad ? 0 : 1}' "$t/files"; then
        printf '%s\trefuse\tunsafe-payload-path\n' "$1"; return 75
    fi
    printf '%s\tverified\t%s\t%s\n' "$1" "$(printf '%s' "$line" | cut -f4)" "$got"
)

vward_entware_gate() (
    vwe_root
    [ -d "$VWE_STATE" ] || return 0
    for f in "$VWE_STATE"/*.pending "$VWE_STATE"/*.unknown; do
        [ -e "$f" ] || [ -L "$f" ] || continue
        printf '%s\n' "${f##*/}"; return 75
    done
    return 0
)

vwe_put() { (umask 077; printf '%s\n' "$2" > "$1.tmp.$$") && mv -f "$1.tmp.$$" "$1" && { [ "${VWARD_JOURNAL_SYNC:-1}" = 0 ] || sync; }; }

# Disable every init script of the package and make sure no copy runs.
vwe_disable() {
    for i in $(vwe_inits "$1"); do
        f=$VWE_R$i
        [ -f "$f" ] && [ ! -L "$f" ] || continue
        if grep -q '^ENABLED=' "$f"; then sed -i 's/^ENABLED=.*/ENABLED=no/' "$f" || return 1; fi
        if vwe_running; then sh "$f" stop >/dev/null 2>&1 || :; fi
    done
    vwe_running && return 1
    return 0
}

# Conffiles of the installed package with their hashes, for "the user's edits survive".
vwe_conffiles() { awk -v p="$1" '
    /^Package: / {cur = ($2 == p)} cur && /^Conffiles:/ {c = 1; next} c && /^ / {print $1; next} {c = 0}' "$VWE_DB/status" 2>/dev/null; }

vward_entware_apply() (
    [ "$#" -eq 4 ] || return 2
    vwe_root; vwe_known "$1" || return 75
    case $4 in manual) [ "${VWARD_ENTWARE_APPLY:-0}" = 1 ] || return 75 ;;
              auto) [ "${VWARD_ENTWARE_APPLY:-0}" = 1 ] && vward_entware_allowed apply || return 75 ;;
              *) return 2 ;; esac
    [ -x "$VWE_OPKG" ] && [ ! -L "$VWE_OPKG" ] || return 75
    (umask 077; mkdir -p "$VWE_STATE" "$VWE_CACHE") || return 2
    mkdir "$VWE_STATE/.lock" 2>/dev/null || return 75
    trap 'rm -rf "$VWE_STATE/.lock" "$VWE_STATE/.work.$$"' EXIT
    echo $$ > "$VWE_STATE/.lock/pid" || return 2
    vward_entware_gate >/dev/null || return 75
    ins=$(vward_entware_inspect "$1" "$2" "$3") || { printf '%s\n' "$ins"; return 75; }
    newv=$(printf '%s' "$ins" | cut -f3); sha=$(printf '%s' "$ins" | cut -f4)
    prev=$(vward_entware_status "$1"); prevv=$(printf '%s' "$prev" | cut -f3)
    [ "$prevv" != "$newv" ] || { printf '%s\tunchanged\t%s\n' "$1" "$newv"; return 0; }
    # Room: twice the unpacked size plus the package, on the /opt filesystem.
    isz=$(tar -xzOf "$2" ./control.tar.gz 2>/dev/null | tar -xzO 2>/dev/null | sed -n 's/^Installed-Size: //p' | head -n 1)
    case $isz in ''|*[!0-9]*) isz=$(wc -c < "$2") ;; esac
    need=$(( (isz * 2 + $(wc -c < "$2")) / 1024 + 1 ))
    free=$(df -k "$VWE_R/opt" 2>/dev/null | awk 'NR == 2 {print $4}')
    case $free in ''|*[!0-9]*) return 75 ;; esac
    [ "$free" -ge "$need" ] || { printf '%s\trefuse\tno-space-%sKB-needed\n' "$1" "$need"; return 75; }
    # Rollback image: the previously verified package must be in the private cache, or the
    # package must be absent (rollback = remove). Otherwise no safe way back: refuse.
    back=
    if [ "$prevv" != - ]; then
        back=$VWE_CACHE/$1_$prevv.ipk
        [ -f "$back" ] && [ ! -L "$back" ] || { printf '%s\trefuse\tno-rollback-image\n' "$1"; return 75; }
    fi
    w=$VWE_STATE/.work.$$; (umask 077; mkdir "$w") || return 2
    # Private backup of the conffiles (the user's edits) before anything changes.
    for c in $(vwe_conffiles "$1"); do
        [ -f "$VWE_R$c" ] || continue
        (umask 077; mkdir -p "$w/conf${c%/*}" && cp -p "$VWE_R$c" "$w/conf$c") || return 2
    done
    vwe_put "$VWE_STATE/$1.pending" "package=$1
from=$prevv
to=$newv
sha256=$sha
rollback=${back:-remove}" || return 1
    # One package, from the verified local file; no feed, no dependency resolution, no upgrade.
    "$VWE_OPKG" install --nodeps "$2" >/dev/null 2>&1; rc=$?
    vwe_disable "$1"; drc=$?
    now=$(vward_entware_status "$1" | cut -f3)
    if [ "$rc" = 0 ] && [ "$drc" = 0 ] && [ "$now" = "$newv" ]; then
        # The user's own conffile edits are never overwritten by a package update.
        for c in $(cd "$w/conf" 2>/dev/null && find . -type f | sed 's/^\.//'); do
            cmp -s "$w/conf$c" "$VWE_R$c" || cp -p "$w/conf$c" "$VWE_R$c" || { vwe_put "$VWE_STATE/$1.unknown" "reason=conffile-restore-failed"; rm -f "$VWE_STATE/$1.pending"; return 3; }
        done
        (umask 077; cp "$2" "$VWE_CACHE/$1_$newv.ipk.tmp" && mv -f "$VWE_CACHE/$1_$newv.ipk.tmp" "$VWE_CACHE/$1_$newv.ipk") || :
        rm -f "$VWE_STATE/$1.pending"
        printf '%s\tdone\t%s\toff\n' "$1" "$newv"; return 0
    fi
    # Failed: back to the previous verified state, never a retry of the failed version.
    if [ -n "$back" ]; then "$VWE_OPKG" install --nodeps --force-downgrade "$back" >/dev/null 2>&1
    else "$VWE_OPKG" remove "$1" >/dev/null 2>&1; fi
    vwe_disable "$1" || :
    for c in $(cd "$w/conf" 2>/dev/null && find . -type f | sed 's/^\.//'); do cp -p "$w/conf$c" "$VWE_R$c" 2>/dev/null || :; done
    after=$(vward_entware_status "$1")
    if [ "$(printf '%s' "$after" | cut -f3)" = "$prevv" ] && [ "$(printf '%s' "$after" | cut -f5)" = off ]; then
        rm -f "$VWE_STATE/$1.pending"
        printf '%s\tfailed-restored\t%s\n' "$1" "$prevv"; return 1
    fi
    vwe_put "$VWE_STATE/$1.unknown" "reason=rollback-unverified
from=$prevv
to=$newv" || :
    rm -f "$VWE_STATE/$1.pending"
    printf '%s\tunknown\n' "$1"; return 3
)

# After TERM/SIGKILL/power loss in the middle of an apply: classify by what is installed now.
# Nothing is installed, removed or retried here; only a provably clean state clears the gate.
vward_entware_recover() (
    [ "$#" -eq 1 ] || return 2
    vwe_root; vwe_known "$1" || return 75
    p=$VWE_STATE/$1.pending
    [ -f "$p" ] || return 0
    from=$(sed -n 's/^from=//p' "$p"); to=$(sed -n 's/^to=//p' "$p")
    # A live apply still holds the lock: nothing to recover yet. A dead one's lock is stale.
    lp=$(cat "$VWE_STATE/.lock/pid" 2>/dev/null)
    case $lp in ''|*[!0-9]*) ;; *) if kill -0 "$lp" 2>/dev/null; then return 75; fi ;; esac
    rm -rf "$VWE_STATE/.lock"
    now=$(vward_entware_status "$1")
    v=$(printf '%s' "$now" | cut -f3); svc=$(printf '%s' "$now" | cut -f5)
    if [ "$svc" != off ]; then res=unknown why=service-not-off
    elif [ "$v" = "$to" ]; then res='done' why=installed-after-restart
    elif [ "$v" = "$from" ]; then res=failed why=not-applied
    else res=unknown why=version-differs; fi
    if [ "$res" = unknown ]; then vwe_put "$VWE_STATE/$1.unknown" "reason=$why
from=$from
to=$to" || return 1; fi
    rm -f "$p"
    printf '%s\t%s\t%s\n' "$1" "$res" "$why"
    [ "$res" = unknown ] && return 3
    return 0
)
