#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
# Who acts, for the journals of the programs it asks (one decision, one agent).
VWARD_ACTOR=maintenance-agent
export VWARD_ACTOR

VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
[ -r "$VWARD_ADMISSION_LIB" ] || { echo "VWARD runtime admission library is unavailable" >&2; exit 1; }
. "$VWARD_ADMISSION_LIB"
command -v vward_defer >/dev/null 2>&1 || vward_defer() { return 1; }
# An admission library of an older release: the agent acts, as before observation mode.
command -v vward_agent_acts >/dev/null 2>&1 || vward_agent_acts() { return 0; }
vward_admission_enter housekeeping || exit $?
cleanup() { vward_admission_leave 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

# The root of every path below; tests point it at a scratch tree.
R=${VWARD_ROOT_PREFIX:-}
HOUSE_LOG="$R/opt/var/log/vward-housekeeping.log"

# Формат:
# файл|максимальный_размер_байт
POLICY="
/opt/var/log/crond.log|524288
/opt/var/log/vward-route-engine-events.log|524288
/opt/var/log/vward-route-engine.log|262144
/opt/var/log/vward-tunnel-health.log|262144
/opt/var/log/vward-tunnel-guard.log|262144
/opt/var/log/vward-wan-guard.log|262144
/opt/var/log/vward-wan-guard-recovery.log|262144
/opt/var/log/vward-policy-audit.log|524288
/opt/var/log/vward-policy-audit-summary.log|262144
/opt/var/log/vward-policy-audit-chain.log|262144
/opt/var/log/vward-policy-reconcile.log|262144
/opt/var/log/vward-policy-sync-sync.log|262144
/opt/var/log/vward-route-hints.log|262144
/opt/var/log/vward-route.log|262144
/opt/var/log/vward-cron-supervisor.log|262144
/opt/var/log/vward-integrity.log|262144
/opt/var/log/vward-route-discovery.log|262144
/opt/var/log/vward-ads-privacy-guard.log|524288
/opt/var/log/vward-wifi-client-guard.log|262144
/opt/var/log/vward-console-lighttpd.log|131072
/opt/var/log/vward/console-audit.log|262144
/opt/var/log/vward/updater-watch.log|262144
/opt/var/log/vward/updater.log|262144
/opt/var/log/vward/updater-recovery.log|131072
/opt/var/log/vward-sentinel.log|262144
/opt/var/log/vward-off.log|131072
/opt/var/log/vward-awg-engine.log|262144
/opt/var/log/vward-vless-engine.log|262144
/opt/var/log/vward-housekeeping.log|262144
"

# Technical journals: nothing is thrown away until the owner's limits say so («Технические
# журналы → Хранение»). A journal over its size goes whole, compressed, into the archive under
# the time it went there; the archive keeps KEEP_DAYS days and, with the live journals, at most
# MAX_MB (0: no limit but the USB drive itself). A small limit makes the journals turn over sooner.
ARCHIVE="$R/opt/var/log/vward/archive"
JOURNAL_CONF=${VWARD_JOURNAL_CONF:-$R/opt/etc/vward/journal.conf}
KEEP_DAYS=30
MAX_MB=30
if [ -r "$JOURNAL_CONF" ]; then
    while IFS='=' read -r JK JV; do
        case "$JK:$JV" in
            KEEP_DAYS:1|KEEP_DAYS:3|KEEP_DAYS:7|KEEP_DAYS:30|KEEP_DAYS:180|KEEP_DAYS:365) KEEP_DAYS=$JV ;;
            MAX_MB:0|MAX_MB:1|MAX_MB:5|MAX_MB:10|MAX_MB:30) MAX_MB=$JV ;;
        esac
    done < "$JOURNAL_CONF"
fi
PER_CAP=0
[ "$MAX_MB" = 0 ] || PER_CAP=$((MAX_MB * 32768))

rotate_file()
{
    F="$1"
    SIZE="$2"

    mkdir -p "$ARCHIVE" || return 1
    TMP="$F.rotate.$$"

    cp "$F" "$TMP" || {
        rm -f "$TMP"
        return 1
    }

    gzip -1 "$TMP" || {
        rm -f "$TMP"
        return 1
    }

    mv "$TMP.gz" "$ARCHIVE/${F##*/}.$(date '+%Y%m%d-%H%M%S').gz" || {
        rm -f "$TMP.gz"
        return 1
    }

    # copytruncate: процессы могут держать активный logfile открытым.
    : > "$F" || return 1

    echo "ROTATED|$F|bytes=$SIZE"
    return 0
}

ROTATED=0
ERRORS=0

# One listing per log folder gives every size: no process per log file.
# Prints "file|size" for each policy file over its limit.
OVER="$(for LD in "$R/opt/var/log" "$R/opt/var/log/vward"; do
        [ -d "$LD" ] && { echo "$LD:"; ls -ln "$LD" 2>/dev/null; }
    done |
    POLICY="$POLICY" R="$R" PER_CAP="$PER_CAP" awk '
        BEGIN {
            n = split(ENVIRON["POLICY"], rows, "\n"); cap = ENVIRON["PER_CAP"] + 0
            for (i = 1; i <= n; i++) if (split(rows[i], f, "|") == 2) limit[ENVIRON["R"] f[1]] = (cap > 0 && cap < f[2] + 0) ? cap : f[2] + 0
        }
        /:$/ { dir = substr($0, 1, length($0) - 1); next }
        /^-/ {
            name = $0
            for (i = 1; i <= 8; i++) sub(/^[^ ]+ +/, "", name)
            path = dir "/" name
            if ((path in limit) && $5 + 0 >= limit[path]) print path "|" $5
        }')"

OLDIFS="$IFS"
IFS='
'
for ROW in $OVER; do
    [ -n "$ROW" ] || continue
    F="${ROW%%|*}"
    RES="$(rotate_file "$F" "${ROW##*|}")"
    if [ "$?" -ne 0 ]; then
        echo "ERROR|$F"
        ERRORS=$((ERRORS + 1))
        continue
    fi
    echo "$RES"
    ROTATED=$((ROTATED + 1))
done
IFS="$OLDIFS"

# The two copies an older VWARD kept next to each journal (name.1.gz, name.2.gz) join the
# archive under the time they were made.
for PF in $POLICY; do
    PF="$R${PF%%|*}"
    for PN in 1 2; do
        [ -f "$PF.$PN.gz" ] || continue
        mkdir -p "$ARCHIVE" && mv "$PF.$PN.gz" "$ARCHIVE/${PF##*/}.$(date -r "$PF.$PN.gz" '+%Y%m%d-%H%M%S' 2>/dev/null || echo 0)-$PN.gz"
    done
done

echo "$(date '+%Y-%m-%d %H:%M:%S')|rotated=$ROTATED|errors=$ERRORS" >> "$HOUSE_LOG"

echo "Rotated=$ROTATED Errors=$ERRORS"

# ============================================================
# VWARD STORAGE RETENTION
# ============================================================
# BusyBox find has no -printf: ages come from "ls -t" (newest first).

# newest_first DIR f|d [PATTERN]: names of files (f) or folders (d) in DIR that
# match PATTERN, newest first; links are never listed.
newest_first()
{
    ls -1t "$1" 2>/dev/null | while IFS= read -r nf_name; do
        case "$nf_name" in ${3:-*}) ;; *) continue ;; esac
        [ ! -L "$1/$nf_name" ] || continue
        case "$2" in
            f) [ -f "$1/$nf_name" ] || continue ;;
            d) [ -d "$1/$nf_name" ] || continue ;;
        esac
        printf '%s\n' "$nf_name"
    done
}

dir_kb()
{
    [ -d "$1" ] || {
        echo 0
        return
    }

    du -sk "$1" 2>/dev/null | awk '{print $1}'
}

# cap_dir DIR f|d LIMIT_KB: the oldest files or folders go while DIR is over
# LIMIT_KB; the newest one always stays.
cap_dir()
{
    [ -d "$1" ] || return 0

    while :; do
        SIZE="$(dir_kb "$1")"

        case "$SIZE" in
            ''|*[!0-9]*) return 1 ;;
        esac

        [ "$SIZE" -le "$3" ] && break

        LIST="$(newest_first "$1" "$2")"
        [ "$(printf '%s\n' "$LIST" | grep -c .)" -gt 1 ] || {
            [ "$2" != d ] || echo "RETENTION_FORENSIC_LIMIT_EXCEEDED|size_kb=$SIZE|kept_latest=1"
            break
        }

        OLD="$(printf '%s\n' "$LIST" | tail -n 1)"
        [ -n "$OLD" ] || break

        echo "RETENTION_DELETE|$1/$OLD"
        rm -rf "${1:?}/${OLD:?}" || return 1
    done

    return 0
}

# keep_newest DIR f|d KEEP [PATTERN]: only the newest KEEP matching entries stay.
keep_newest()
{
    [ -d "$1" ] || return 0

    newest_first "$1" "$2" "${4:-*}" | tail -n +$(($3 + 1)) | while IFS= read -r KN_OLD; do
        echo "RETENTION_DELETE|$1/$KN_OLD"
        rm -rf "${1:?}/${KN_OLD:?}"
    done

    return 0
}


RETENTION_ERRORS=0
B="$R/opt/var/backups/vward"

# Диагностические отчёты: максимум 2 МБ.
cap_dir "$R/opt/var/log/vward/diagnostics" f 2048 ||
RETENTION_ERRORS=$((RETENTION_ERRORS + 1))

# Forensic-инциденты: максимум 12 МБ суммарно.
# Самый новый инцидент всегда сохраняется.
cap_dir "$B/forensics" d 12288 ||
RETENTION_ERRORS=$((RETENTION_ERRORS + 1))

# Старые пакеты исходников: максимум 4 МБ.
cap_dir "$B/legacy-scripts" d 4096 ||
RETENTION_ERRORS=$((RETENTION_ERRORS + 1))

# Конфигурационные rollback-копии.
keep_newest "$B/log-policy" f 5
keep_newest "$B/housekeeping" f 5

# A copy of update.conf before every save of the Updates settings.
keep_newest "$B" f 10 'update.conf.console-*'

# Ad filter copies before each manual rule, setting, source change and publish.
keep_newest "$B/ads-privacy-guard" d 10 'publish-*'
for KD in manual settings source-settings; do
    keep_newest "$B/ads-privacy-guard/$KD" d 20
done

# Copies of packages before an update from «Обновления» (AdGuard Home is ~30 MB).
keep_newest "$B/ext-update" d 3

# Keenetic's request counter for «Стабильность» (RAM): a day is enough.
find "${VWARD_RCI_CALLS:-$R/tmp/vward-rci-calls}" -type f -mmin +1500 -exec rm -f {} + 2>/dev/null

# A tunnel .conf holds its private key: uploads now live in RAM only, and
# those an older version kept on the USB drive go.
rm -f "$R/opt/var/run/vward/console-tunnel/upload."* 2>/dev/null
rmdir "$R/opt/var/run/vward/console-tunnel" 2>/dev/null

# Technical journals: archived ones older than the owner's term go; then, while the archive and
# the live journals together are over the size limit, the oldest archived one.
if [ -d "$ARCHIVE" ]; then
    find "$ARCHIVE" -type f -name '*.gz' -mtime +$((KEEP_DAYS - 1)) 2>/dev/null | while IFS= read -r JOLD; do
        echo "RETENTION_DELETE|$JOLD"
        rm -f "$JOLD"
    done
    if [ "$MAX_MB" -gt 0 ]; then
        LIVE_KB=$(for LD in "$R/opt/var/log" "$R/opt/var/log/vward"; do [ -d "$LD" ] && { echo "$LD:"; ls -ln "$LD" 2>/dev/null; }; done |
            POLICY="$POLICY" R="$R" awk '
                BEGIN {n = split(ENVIRON["POLICY"], rows, "\n"); for (i = 1; i <= n; i++) if (split(rows[i], f, "|") == 2) p[ENVIRON["R"] f[1]] = 1}
                /:$/ {dir = substr($0, 1, length($0) - 1); next}
                /^-/ {name = $0; for (i = 1; i <= 8; i++) sub(/^[^ ]+ +/, "", name); if ((dir "/" name) in p) s += $5}
                END {print int(s / 1024)}')
        cap_dir "$ARCHIVE" f $((MAX_MB * 1024 - ${LIVE_KB:-0})) || RETENTION_ERRORS=$((RETENTION_ERRORS + 1))
    fi
fi

# Locks whose owner is gone (killed, power cut) would hold back the updater.
vward_locks_sweep

# ---------- Crontab folder ----------
# BusyBox crond takes every file in its folder for a user's crontab and skips
# the ones without a user: hand-made copies (root.bak-*, root.before-*) are
# only clutter there.  They move to the backups, once.
CRON_DIR=${VWARD_CRON_DIR:-$R/opt/var/spool/cron/crontabs}
CRON_OLD="$B/cron-old"
for CRON_F in "$CRON_DIR"/root.*; do
    [ -f "$CRON_F" ] && [ ! -L "$CRON_F" ] || continue
    mkdir -p "$CRON_OLD" && mv -f "$CRON_F" "$CRON_OLD/" &&
        echo "$(date '+%Y-%m-%d %H:%M:%S')|cron_copy_moved=${CRON_F##*/}" >> "$HOUSE_LOG"
done

# The old agh-keenetic-clients-sync.sh rewrote AdGuardHome.yaml and restarted
# AdGuard Home whenever a device came or went.  VWARD names the devices through
# AdGuard Home's API (vward-ads-privacy-clients.sh), which waits while the old
# line is in cron.  Once AdGuard Home is connected to VWARD the line is
# commented out; the crontab before the change stays in cron-old.
OLD_SYNC=agh-keenetic-clients-sync.sh
CRON_ROOT="$CRON_DIR/root"
ADS_ETC_DIR=${VWARD_ADS_ETC:-$R/opt/etc/vward/ads-privacy-guard}
if [ -s "$ADS_ETC_DIR/agh-api.auth" ] && [ ! -e "$ADS_ETC_DIR/clients-sync.disabled" ] &&
   [ -x "${VWARD_ADS_CLIENTS_SYNC:-$R/opt/bin/vward-ads-privacy-clients.sh}" ] &&
   grep -v '^[[:space:]]*#' "$CRON_ROOT" 2>/dev/null | grep -Fq "$OLD_SYNC"; then
    CRON_NEW="$R/tmp/vward-housekeeping-crontab.$$"
    if mkdir -p "$CRON_OLD" && cp -p "$CRON_ROOT" "$CRON_OLD/root.before-clients-sync" &&
       awk -v s="$OLD_SYNC" '!/^[[:space:]]*#/ && index($0, s) {print "# off: VWARD names devices through the AdGuard Home API # " $0; next} {print}' \
           "$CRON_ROOT" > "$CRON_NEW" &&
       "${VWARD_CRONTAB:-crontab}" -c "$CRON_DIR" "$CRON_NEW" >/dev/null 2>&1; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|old_clients_sync=off" >> "$HOUSE_LOG"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S')|old_clients_sync=kept" >> "$HOUSE_LOG"
    fi
    rm -f "$CRON_NEW"
fi

# ---------- One-time move to Update Engine 2 ----------
# Engine 1 cannot read the per-file feed and cannot replace itself.  This hourly
# job moves it over once, without a command: the signed v2 manifest is checked
# with the router's own update key, each engine file against its signed sha256,
# and the new engine then installs itself into the other slot (--engine-adopt:
# updater lock, trusted sequence, self-test, atomic switch; slot A/B kept).
engine_move()
{
    EM_ROOT=$R/opt/share/vward/updater
    [ -r "$EM_ROOT/current/vward-update-common-base.sh" ] || return 0
    # Engine 2 that fell behind its release: an engine that once replaced itself left «already
    # replaced» to crond, and every later run skipped the newer engine (Viva 2026-10-12: 2.0.7
    # after fix.26). Checked every 6 hours; the same signed move, only when the release's engine
    # is newer.
    EM_CUR=$(sed -n 's/^VU_ENGINE_VERSION=//p' "$EM_ROOT/current/vward-update-common-base.sh" | head -n 1)
    EM_STAMP=$R/opt/var/lib/vward/engine-catchup.stamp
    # curl crashed on HTTPS within the hour: no download now (the HTTPS repair below comes first),
    # the check waits for the next hour.
    EM_TLS_FLAG=${VWARD_TLS_BROKEN_FLAG:-/tmp/vward-curl-tls.broken}
    [ -z "$(find "$EM_TLS_FLAG" -mmin -60 2>/dev/null)" ] || [ -n "${VWARD_ENGINE_MOVE_SOURCE:-}" ] || return 0
    if [ -n "$EM_CUR" ]; then
        [ -z "$(find "$EM_STAMP" -mmin -360 2>/dev/null)" ] || return 0
    fi
    EM_CONF=${VWARD_UPDATE_CONFIG:-$R/opt/etc/vward/update.conf}
    em_get() { sed -n "s/^$1=//p" "$EM_CONF" 2>/dev/null | tail -n 1 | tr -d '"'; }
    [ "$(em_get update_enabled)" = 1 ] || return 0
    EM_KEY=$(em_get public_key_file); [ -n "$EM_KEY" ] || EM_KEY=$R/opt/etc/vward/update-public.pem
    EM_CHANNEL=$(em_get channel); [ -n "$EM_CHANNEL" ] || EM_CHANNEL=dev
    EM_URL=$(em_get manifest_url)
    case "$EM_URL" in https://*/update-manifest.json) EM_URL=${EM_URL%/update-manifest.json}/v2/manifest.json ;; *) return 0 ;; esac
    EM_T=$(mktemp -d /tmp/vward-engine-move.XXXXXX) || return 0
    (
        em_fetch() {
            # em_fetch URL|NAME OUTPUT MAX_BYTES
            if [ -n "${VWARD_ENGINE_MOVE_SOURCE:-}" ]; then cp "$VWARD_ENGINE_MOVE_SOURCE/$1" "$2"; return; fi
            # One agent tries a curl not known to work first (vward_tls_take); a crash noted there stops here.
            ! command -v vward_tls_take >/dev/null 2>&1 || vward_tls_take || exit 3
            curl --http1.1 -fsS --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 120 --max-filesize "$3" -o "$2" "$1" 2>/dev/null
            em_rc=$?
            ! command -v vward_tls_done >/dev/null 2>&1 || vward_tls_done "$em_rc"
            # A crash (a signal of curl's own fault) is remembered for the HTTPS repair and stops
            # the rest of the move.
            case "$em_rc" in 132|134|135|136|139) : > "$EM_TLS_FLAG" 2>/dev/null; exit 3 ;; esac
            return "$em_rc"
        }
        if [ -n "${VWARD_ENGINE_MOVE_SOURCE:-}" ]; then src=manifest.json; else src=$EM_URL; fi
        em_fetch "$src" "$EM_T/manifest.json" 262144 || exit 3
        jq -cS '.signed' "$EM_T/manifest.json" > "$EM_T/signed" &&
            jq -r '.signature' "$EM_T/manifest.json" | openssl base64 -d -A > "$EM_T/sig" &&
            openssl pkeyutl -verify -pubin -inkey "$EM_KEY" -rawin -in "$EM_T/signed" -sigfile "$EM_T/sig" >/dev/null 2>&1 || exit 4
        jq -e --arg ch "$EM_CHANNEL" '.signed.schema == 2 and .signed.channel == $ch' "$EM_T/manifest.json" >/dev/null || exit 4
        if [ -n "$EM_CUR" ]; then
            em_new=$(jq -r '.signed.engine.version // empty' "$EM_T/manifest.json")
            case "$em_new" in [0-9]*.[0-9]*.[0-9]*) ;; *) exit 6 ;; esac
            [ "$em_new" != "$EM_CUR" ] && [ "$(printf '%s\n%s\n' "$EM_CUR" "$em_new" | sort -t. -k1,1n -k2,2n -k3,3n | tail -n 1)" = "$em_new" ] || exit 6
        fi
        base=$(jq -r '.signed.files_base' "$EM_T/manifest.json")
        case "$base" in https://*/) ;; *) exit 4 ;; esac
        jq -r '.signed.engine.files[] | [.name, .sha256, (.size | tostring)] | @tsv' "$EM_T/manifest.json" |
        while IFS="$(printf '\t')" read -r name sha size; do
            case "$name" in ''|*[!A-Za-z0-9._-]*) exit 4 ;; esac
            if [ -n "${VWARD_ENGINE_MOVE_SOURCE:-}" ]; then src=files/$sha; else src=$base$sha; fi
            em_fetch "$src" "$EM_T/$name" "$((size + 1))" || exit 3
            [ "$(wc -c < "$EM_T/$name" | tr -d ' ')" = "$size" ] && [ "$(sha256sum "$EM_T/$name" | awk '{print $1}')" = "$sha" ] || exit 4
        done || exit $?
        unset VWARD_ENGINE_SWITCHED
        sh "$EM_T/vward-update.sh" --engine-adopt "$EM_T" "$EM_T/manifest.json" >/dev/null 2>&1 || exit 5
    )
    EM_RC=$?
    # Checked: the next check in 6 hours. Not downloaded (the network, curl): the next hour
    # (Viva 2026-10-13: the first check after fix.27 met curl 77 and then waited 6 hours).
    if [ -n "$EM_CUR" ] && [ "$EM_RC" != 3 ]; then
        mkdir -p "${EM_STAMP%/*}" 2>/dev/null; : > "$EM_STAMP" 2>/dev/null
    fi
    rm -rf "${EM_T:?}"
    case "$EM_RC" in
        0) echo "ENGINE_MOVED|v2"; echo "$(date '+%Y-%m-%d %H:%M:%S')|engine_move=done${EM_CUR:+ from=$EM_CUR}" >> "$HOUSE_LOG" ;;
        3|6) : ;;
        *) echo "$(date '+%Y-%m-%d %H:%M:%S')|engine_move=failed rc=$EM_RC" >> "$HOUSE_LOG" ;;
    esac
    return 0
}
engine_move

# Daily snapshot of VWARD's settings (the helper skips it when one is younger than a day).
# The day already handled is kept in RAM, so the other 23 hourly runs start nothing.
BACKUP_HELPER=${VWARD_CONSOLE_CONFIG_BIN:-/opt/bin/vward-console-config.sh}
BACKUP_DAY_FILE=${VWARD_BACKUP_DAY_FILE:-/tmp/vward-backup-day}
if [ -x "$BACKUP_HELPER" ]; then
    BACKUP_NOW="$(date '+%Y-%m-%d %H:%M:%S')"
    BACKUP_DAY=""
    [ ! -r "$BACKUP_DAY_FILE" ] || read -r BACKUP_DAY < "$BACKUP_DAY_FILE" || :
    if [ "$BACKUP_DAY" != "${BACKUP_NOW%% *}" ]; then
        BACKUP_RESULT="$("$BACKUP_HELPER" backup-create auto 2>/dev/null | tail -n 1)"
        echo "$BACKUP_NOW|snapshot=${BACKUP_RESULT:-none}" >> "$HOUSE_LOG"
        case "$BACKUP_RESULT" in result=*) echo "${BACKUP_NOW%% *}" > "$BACKUP_DAY_FILE" 2>/dev/null || : ;; esac
    fi
fi

# Entware programs VWARD runs all the time: one that crashes (a signal) twice on a plain local
# task gets its package reinstalled - a damaged copy (Viva 2026-10-11: curl crashed 10 times of
# 10 on a plain HTTP request to the router while its file on the USB stick was sound; the
# reinstall cured it, openssl too). At most once in 6 hours a program; one log line each.
REPAIR_DIR=${VWARD_REPAIR_DIR:-$R/opt/var/lib/vward/repair}
OPKG=${VWARD_OPKG_BIN:-opkg}
# crash_rc RC: the program died of its own fault (132 illegal instruction, 134 abort, 135 bus
# error, 136 arithmetic, 139 memory). 137 and 143 are a stop from outside (a time limit), 141 a
# closed pipe: no crash.
crash_rc() { case "$1" in 132|134|135|136|139) return 0 ;; esac; return 1; }
repair_if_crashing()
{
    rp_name=$1 rp_pkgs=$2
    shift 2
    [ -x "$1" ] || return 0
    rp_try=0
    while [ "$rp_try" -lt 2 ]; do
        "$@" </dev/null >/dev/null 2>&1
        rp_rc=$?
        crash_rc "$rp_rc" || return 0
        rp_try=$((rp_try + 1))
    done
    rp_now=$(date +%s) rp_last=0
    [ ! -r "$REPAIR_DIR/$rp_name" ] || read -r rp_last < "$REPAIR_DIR/$rp_name" || :
    case "$rp_last" in ''|*[!0-9]*) rp_last=0 ;; esac
    if [ $((rp_now - rp_last)) -lt 21600 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|repair=$rp_name|crash=$rp_rc|next_try_later" >> "$HOUSE_LOG"
        return 0
    fi
    # Observation mode of the maintenance agent (fix.28.2): proposed, not reinstalled.
    vward_agent_acts maintenance "repair:$rp_name" "$rp_name падает (код $rp_rc): переустановить $rp_pkgs" || return 0
    mkdir -p "$REPAIR_DIR" && echo "$rp_now" > "$REPAIR_DIR/$rp_name"
    # shellcheck disable=SC2086
    "$OPKG" install --force-reinstall $rp_pkgs </dev/null >/dev/null 2>&1
    rp_opkg=$?
    "$@" </dev/null >/dev/null 2>&1
    echo "$(date '+%Y-%m-%d %H:%M:%S')|repair=$rp_name|crash=$rp_rc|reinstalled=$(echo $rp_pkgs | tr ' ' ',')|opkg=$rp_opkg|after=$?" >> "$HOUSE_LOG"
}
REPAIR_CURL=${VWARD_REPAIR_CURL:-/opt/bin/curl}
REPAIR_JQ=${VWARD_REPAIR_JQ:-/opt/bin/jq}
REPAIR_OPENSSL=${VWARD_REPAIR_OPENSSL:-/opt/bin/openssl}
repair_if_crashing curl curl "$REPAIR_CURL" -s -o /dev/null --noproxy '*' --connect-timeout 3 --max-time 5 http://127.0.0.1:79/rci/show/version
# curl noted as crashing on HTTPS within the hour (vward_fetch, the probes - only a real crash is
# noted since fix.28.1: a stop from outside or a DoH client's trouble marked a working curl and it
# was reinstalled every 6 hours, Viva 2026-10-17): the crash was in libnghttp2, the HTTP/2 library
# (Viva 2026-10-12: 81 crashes in two hours), which the local check above never loads. The crash
# is already seen, so no test run first (each is one more crash): its packages and the
# certificates are reinstalled at once, at most once a day, and HTTPS is tried once after, with
# the certificates (77 after a reinstall, Viva 2026-10-15); when it works, curl is trusted again.
REPAIR_TLS_FLAG=${VWARD_TLS_BROKEN_FLAG:-/tmp/vward-curl-tls.broken}
REPAIR_DOH_FLAG=${VWARD_DOH_BROKEN_FLAG:-/tmp/vward-doh.broken}
https_try()
{
    ht_ca=
    for ht_f in ${VWARD_CA_BUNDLE:-/opt/etc/ssl/certs/ca-certificates.crt /opt/etc/ssl/cert.pem}; do
        [ -s "$ht_f" ] && { ht_ca=$ht_f; break; }
    done
    "$REPAIR_CURL" -s -o /dev/null --connect-timeout 5 --max-time 10 ${ht_ca:+--cacert "$ht_ca"} \
        "${VWARD_REPAIR_HTTPS_URL:-https://raw.githubusercontent.com/}" </dev/null >/dev/null 2>&1
}
# repair_due NAME: the last reinstall of NAME was a day ago or more (and now is noted).
repair_due()
{
    rd_now=$(date +%s) rd_last=0
    [ ! -r "$REPAIR_DIR/$1" ] || read -r rd_last < "$REPAIR_DIR/$1" || :
    case "$rd_last" in ''|*[!0-9]*) rd_last=0 ;; esac
    [ $((rd_now - rd_last)) -ge 86400 ] || return 1
    mkdir -p "$REPAIR_DIR" && echo "$rd_now" > "$REPAIR_DIR/$1"
}
if [ -x "$REPAIR_CURL" ] && [ -n "$(find "$REPAIR_TLS_FLAG" -mmin -60 2>/dev/null)" ] &&
   vward_agent_acts maintenance repair:curl-https "curl падает на HTTPS: переустановить libnghttp2, libcurl, curl и сертификаты" && repair_due curl-https; then
    "$OPKG" install --force-reinstall libnghttp2 libcurl curl ca-bundle </dev/null >/dev/null 2>&1
    rh_opkg=$?
    https_try
    rh_after=$?
    crash_rc "$rh_after" || rm -f "$REPAIR_TLS_FLAG"
    echo "$(date '+%Y-%m-%d %H:%M:%S')|repair=curl-https|reinstalled=libnghttp2,libcurl,curl,ca-bundle|opkg=$rh_opkg|after=$rh_after" >> "$HOUSE_LOG"
fi
# pkg_damaged PKG...: the installed packages whose files differ from the same version in the
# Entware feed (downloaded into RAM, checked byte for byte). The USB stick spoils files: on the
# Viva 2026-10-17 libcares of Smart DNS's client differed from its package and the client died
# at start (SIGILL, then SIGSEGV) for hours; reinstalling everything blindly once a day missed
# it (libcares was not on the list). Settings under /opt/etc are the owner's: not compared.
# PKG_UNCHECKED: the packages that could not be checked (no download, another version).
PKG_TMP=${VWARD_PKG_TMP:-$R/tmp/vward-pkgcheck}
pkg_damaged()
{
    PKG_UNCHECKED=
    for pd_p in "$@"; do
        pd_v=$("$OPKG" list-installed "$pd_p" 2>/dev/null | awk -v p="$pd_p" '$1 == p {print $3; exit}')
        [ -n "$pd_v" ] || continue
        pd_d=$PKG_TMP/$pd_p
        rm -rf "${pd_d:?}"; mkdir -p "$pd_d/x/d" || continue
        ( cd "$pd_d" && "$OPKG" download "$pd_p" </dev/null >/dev/null 2>&1 )
        pd_ipk=$(ls "$pd_d"/*.ipk 2>/dev/null | head -n 1)
        # A newer version in the feed tells nothing about the installed files.
        case "${pd_ipk##*/}" in "${pd_p}_${pd_v}_"*) ;; *) PKG_UNCHECKED="$PKG_UNCHECKED $pd_p"; rm -rf "${pd_d:?}"; continue ;; esac
        if ! tar -xzf "$pd_ipk" -C "$pd_d/x" 2>/dev/null || ! tar -xzf "$pd_d/x/data.tar.gz" -C "$pd_d/x/d" 2>/dev/null; then
            PKG_UNCHECKED="$PKG_UNCHECKED $pd_p"; rm -rf "${pd_d:?}"; continue
        fi
        pd_bad=
        ( cd "$pd_d/x/d" && find . -type f ) > "$pd_d/files" 2>/dev/null
        while IFS= read -r pd_f; do
            pd_f=${pd_f#.}
            case "$pd_f" in /opt/etc/*) continue ;; esac
            [ "$(md5sum < "$pd_d/x/d$pd_f" 2>/dev/null)" = "$(md5sum < "$R$pd_f" 2>/dev/null)" ] || { pd_bad=1; break; }
        done < "$pd_d/files"
        rm -rf "${pd_d:?}"
        [ -z "$pd_bad" ] || echo "$pd_p"
    done
    rmdir "$PKG_TMP" 2>/dev/null || :
}
# pkg_repair TAG PKG...: the damaged packages reinstalled from Entware, a copy of their files
# first. Never a loop of reinstalls: a package once a day at most; one spoiled again after 2
# reinstalls within 7 days is left alone (the stick does not keep it, the owner is told to
# replace it); 3 reinstalls a day on the whole router at most. PR_DONE - reinstalled, PR_HELD -
# left alone, PR_STILL - still damaged after it, PR_COPY - the copy, PR_OPKG - opkg's answer.
PKG_BOOK=${VWARD_PKG_REPAIRS:-$REPAIR_DIR/packages.tsv}
pkg_repair()
{
    PR_DONE= PR_HELD= PR_STILL= PR_COPY= PR_OPKG=
    pr_tag=$1; shift
    pr_now=$(date +%s)
    mkdir -p "$REPAIR_DIR" 2>/dev/null || return 0
    touch "$PKG_BOOK"
    for pr_p in "$@"; do
        pr_last=$(awk -v p="$pr_p" '$2 == p {t = $1} END {print t + 0}' "$PKG_BOOK")
        pr_week=$(awk -v p="$pr_p" -v n="$pr_now" '$2 == p && $1 + 604800 > n {c++} END {print c + 0}' "$PKG_BOOK")
        pr_day=$(awk -v n="$pr_now" '$1 + 86400 > n {c++} END {print c + 0}' "$PKG_BOOK")
        pr_n=$(echo $PR_DONE | wc -w)
        if [ $((pr_now - pr_last)) -lt 86400 ] || [ "$pr_week" -ge 2 ] || [ $((pr_day + pr_n)) -ge 3 ]; then
            PR_HELD="$PR_HELD $pr_p"
        else
            PR_DONE="$PR_DONE $pr_p"
        fi
    done
    PR_DONE=${PR_DONE# } PR_HELD=${PR_HELD# }
    [ -n "$PR_DONE" ] || return 0
    PR_COPY=$REPAIR_DIR/$pr_tag-$(date +%Y%m%d-%H%M%S).tar.gz
    # shellcheck disable=SC2086
    pr_files=$(for pr_p in $PR_DONE; do "$OPKG" files "$pr_p" 2>/dev/null; done | grep '^/opt/' | grep -v '^/opt/etc/')
    # shellcheck disable=SC2086
    ( cd "$R/" && tar -czf "$PR_COPY" $(printf '%s\n' $pr_files | sed 's#^/##') ) 2>/dev/null || PR_COPY=
    ls -t "$REPAIR_DIR"/*-2*.tar.gz 2>/dev/null | tail -n +4 | while IFS= read -r pr_old; do rm -f "$pr_old"; done
    # shellcheck disable=SC2086
    "$OPKG" install --force-reinstall $PR_DONE </dev/null >/dev/null 2>&1
    PR_OPKG=$?
    for pr_p in $PR_DONE; do echo "$pr_now $pr_p $pr_tag"; done >> "$PKG_BOOK"
    awk -v n="$pr_now" '$1 + 2592000 > n' "$PKG_BOOK" > "$PKG_BOOK.$$" && mv -f "$PKG_BOOK.$$" "$PKG_BOOK"
    pr_out=$R/tmp/vward-pkg-still.$$
    # shellcheck disable=SC2086
    pkg_damaged $PR_DONE > "$pr_out"
    PR_STILL=$(tr '\n' ' ' < "$pr_out"); PR_STILL=${PR_STILL% }; rm -f "$pr_out"
}
# pkg_repair_text: what pkg_repair did, for the owner.
pkg_repair_text()
{
    pt=
    [ -z "$PR_DONE" ] || pt="VWARD переустановил из Entware: $(echo $PR_DONE | sed 's/ /, /g')${PR_COPY:+ (прежние файлы сохранены)}."
    [ -z "$PR_STILL" ] || pt="$pt Не помогло: $(echo $PR_STILL | sed 's/ /, /g')."
    [ -z "$PR_HELD" ] || pt="$pt Не переустановлены, чтобы не повторять по кругу: $(echo $PR_HELD | sed 's/ /, /g')."
    echo "$pt Проверьте флешку на компьютере или замените её: повреждения будут повторяться."
}
# Smart DNS's DoH client (https-dns-proxy) restarted three times within 6 hours (the components
# agent noted it): its packages are checked against Entware and only the damaged ones are
# reinstalled, with a copy of their files first, at most once a day; the owner is told the
# stick spoils files. Intact files: nothing reinstalled (it would not help). curl is not touched.
DOH_PKGS=${VWARD_DOH_PKGS:-https-dns-proxy libcares libev libnghttp2 libcurl libopenssl}
if [ -n "$(find "$REPAIR_DOH_FLAG" -mmin -360 2>/dev/null)" ] &&
   vward_agent_acts maintenance repair:doh "Клиент DoH Smart DNS перезапускался 3 раза: сверить его пакеты с Entware и переустановить испорченные" && repair_due doh; then
    rm -f "$REPAIR_DOH_FLAG"
    rd_out=$R/tmp/vward-doh-damaged.$$
    # shellcheck disable=SC2086
    pkg_damaged $DOH_PKGS > "$rd_out"
    rd_bad=$(tr '\n' ' ' < "$rd_out"); rd_bad=${rd_bad% }; rm -f "$rd_out"
    if [ -z "$rd_bad" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S')|repair=doh|files=intact|unchecked=$(echo $PKG_UNCHECKED | tr ' ' ',')" >> "$HOUSE_LOG"
    else
        pkg_repair doh $rd_bad
        echo "$(date '+%Y-%m-%d %H:%M:%S')|repair=doh|damaged=$(echo $rd_bad | tr ' ' ',')|reinstalled=$(echo $PR_DONE | tr ' ' ',')|held=$(echo $PR_HELD | tr ' ' ',')|opkg=$PR_OPKG|still_damaged=$(echo $PR_STILL | tr ' ' ',')|copy=${PR_COPY:-none}" >> "$HOUSE_LOG"
        command -v vward_note >/dev/null 2>&1 ||
            { [ ! -r "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}" ] || . "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}"; } 2>/dev/null
        ! command -v vward_note >/dev/null 2>&1 || vward_note warn "Флешка портит файлы программ" \
            "Повреждены файлы пакетов: $(echo $rd_bad | sed 's/ /, /g'). Из-за этого не запускался клиент Smart DNS. $(pkg_repair_text)" system
    fi
fi
repair_if_crashing jq jq "$REPAIR_JQ" -n 1
repair_if_crashing openssl "libopenssl openssl-util" "$REPAIR_OPENSSL" version

# The USB stick (fix.28.2): file system and read/write errors in the kernel's messages. A damaged
# directory on the stick (Viva 2026-10-17: 10 «EXT4-fs error» on one inode, Keenetic's own
# usb.d) went unseen until the owner looked by hand. Every hour, only what is new since the last
# look (the messages live in RAM until a reboot): one journal line, the bell once a day with the
# damaged place (an inode's path is looked for once) and what to do. Only looks; repairs nothing.
FLASH_STATE=${VWARD_FLASH_STATE:-$R/tmp/vward-flash}
FLASH_DMESG=${VWARD_DMESG_BIN:-dmesg}
flash_watch()
{
    # The quiet hour costs one program: the kernel's messages that matter, compared by their
    # length with the last look (CI budget: the maintenance agent runs 24 times a day).
    fw_raw=$("$FLASH_DMESG" 2>/dev/null) fw_all=
    while IFS= read -r fw_l; do
        case "$fw_l" in
            *"EXT4-fs error"*|*"EXT4-fs warning"*|*"EXT2-fs error"*|*"EXT3-fs error"*|*"I/O error"*|*"Buffer I/O"*|\
            *"FAT-fs ("*"): error"*|*"blk_update_request: critical medium"*|*"blk_update_request: I/O"*) fw_all="$fw_all$fw_l
" ;;
        esac
    done <<EOF_DMESG
$fw_raw
EOF_DMESG
    fw_raw=
    fw_sig=${#fw_all} fw_old=
    [ ! -r "$FLASH_STATE/sig" ] || read -r fw_old < "$FLASH_STATE/sig" || :
    [ "$fw_sig" != "${fw_old:-0}" ] || return 0
    [ -d "$FLASH_STATE" ] || mkdir -p "$FLASH_STATE" 2>/dev/null || return 0
    printf '%s\n' "$fw_sig" > "$FLASH_STATE/sig"
    printf '%s\n' "$fw_all" | sed 's/^\[[ 0-9.]*\] *//' | grep . | sort -u > "$FLASH_STATE/now" 2>/dev/null
    touch "$FLASH_STATE/seen"
    grep -vxF -f "$FLASH_STATE/seen" "$FLASH_STATE/now" > "$FLASH_STATE/new" 2>/dev/null
    mv -f "$FLASH_STATE/now" "$FLASH_STATE/seen"
    fw_n=$(grep -c . "$FLASH_STATE/new" 2>/dev/null)
    case "$fw_n" in ''|*[!0-9]*|0) rm -f "$FLASH_STATE/new"; return 0 ;; esac
    fw_io=$(grep -cE 'I/O error|Buffer I/O|critical medium' "$FLASH_STATE/new")
    fw_dev=$(sed -n 's/.*(device \([a-z0-9]*\)).*/\1/p; s/.* dev \([a-z0-9]*\)[ ,].*/\1/p' "$FLASH_STATE/new" | head -n 1)
    fw_paths=
    for fw_ino in $(sed -n 's/.*inode #\([0-9]*\).*/\1/p' "$FLASH_STATE/new" | sort -u | head -n 3); do
        fw_p=
        [ ! -r "$FLASH_STATE/inode.$fw_ino" ] || read -r fw_p < "$FLASH_STATE/inode.$fw_ino"
        if [ -z "$fw_p" ]; then
            fw_p=$(find "$R/opt" -xdev -inum "$fw_ino" 2>/dev/null | head -n 1)
            fw_p=${fw_p#"$R"}
            printf '%s\n' "${fw_p:-?}" > "$FLASH_STATE/inode.$fw_ino"
        fi
        fw_paths="$fw_paths${fw_paths:+, }${fw_p:-inode $fw_ino}"
    done
    echo "$(date '+%Y-%m-%d %H:%M:%S')|flash_errors=$fw_n|io=$fw_io|device=${fw_dev:-?}|where=${fw_paths:-?}" >> "$HOUSE_LOG"
    sed -n '1,5p' "$FLASH_STATE/new" | sed "s/^/$(date '+%Y-%m-%d %H:%M:%S')|flash|/" >> "$HOUSE_LOG"
    rm -f "$FLASH_STATE/new"
    # The bell: once a day; read/write errors are the stick itself, the others its file system.
    [ -z "$(find "$FLASH_STATE/told" -mmin -1440 2>/dev/null)" ] || return 0
    : > "$FLASH_STATE/told"
    command -v vward_note >/dev/null 2>&1 ||
        { [ ! -r "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}" ] || . "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}"; } 2>/dev/null
    command -v vward_note >/dev/null 2>&1 || return 0
    if [ "$fw_io" -gt 0 ]; then
        vward_note err "Флешка: ошибки чтения и записи" \
            "Ядро роутера сообщило об ошибках чтения или записи USB-накопителя${fw_dev:+ ($fw_dev)}: $fw_io. Накопитель может выходить из строя: сохраните копию настроек VWARD (Система → Копия настроек) и замените его."
    else
        vward_note warn "Флешка: ошибки файловой системы" \
            "Ядро роутера нашло ошибки файловой системы USB-накопителя${fw_dev:+ ($fw_dev)}: $fw_n${fw_paths:+; повреждено: $fw_paths}. Ошибок чтения и записи нет. Повреждённый каталог можно переименовать и создать заново; полная проверка (fsck) - на компьютере."
    fi
}
flash_watch

# File integrity (fix.28.3): once a day, at night, every program file of Entware and VWARD -
# size, time of change, checksum - against yesterday's. A program that writes a file changes
# its time; the stick that spoils one changes only the contents (Viva 2026-10-17: libcares of
# Smart DNS's client spoiled, its time as installed). Journal: SPOILED (contents changed, time
# the same), WRITTEN by=opkg:PKG | vward-update | unknown, ADDED, REMOVED, and a summary. A
# spoiled file of a package is checked against the same version in Entware and the package
# reinstalled (pkg_repair: never in a loop); a spoiled file of VWARD itself is told. Files the
# owner or another program wrote are only written down.
INTEG_DIR=${VWARD_INTEGRITY_DIR:-$R/opt/var/lib/vward/integrity}
INTEG_LOG=${VWARD_INTEGRITY_LOG:-$R/opt/var/log/vward-integrity.log}
INTEG_ROOTS=${VWARD_INTEGRITY_ROOTS:-/opt/bin /opt/sbin /opt/lib /opt/share/vward}
INTEG_UPDATER_LOG=${VWARD_INTEGRITY_UPDATER_LOG:-$R/opt/var/log/vward/updater.log}
# integrity_clock: IC_NOW (seconds) and IC_HOUR (local, two digits) without a program each hour
# (CI budget): the wall clock is asked once per boot and then counted on from /proc/uptime.
integrity_clock()
{
    ic_up=; read -r ic_up _ < "${VWARD_UPTIME_FILE:-/proc/uptime}" 2>/dev/null || :
    ic_up=${ic_up%%.*}
    case "$ic_up" in ''|*[!0-9]*) return 1 ;; esac
    ic_e= ic_u= ic_off=
    [ ! -r "$INTEG_DIR/clock" ] || read -r ic_e ic_u ic_off < "$INTEG_DIR/clock" || :
    case "$ic_e$ic_u$ic_off" in *[!0-9-]*|'') ic_u= ;; esac
    # Asked again after a reboot and once a week (the clock may have been set meanwhile).
    if [ -z "$ic_u" ] || [ "$ic_up" -lt "$ic_u" ] || [ $((ic_up - ic_u)) -gt 604800 ]; then
        # shellcheck disable=SC2046
        set -- $(date '+%s %z')
        case "$1" in ''|*[!0-9]*) return 1 ;; esac
        # A date without %z (or an odd answer): UTC, an hour off at worst.
        case "${2:-}" in [+-][0-9][0-9][0-9][0-9]) ic_z=$2 ;; *) ic_z=+0000 ;; esac; ic_s=${ic_z%"${ic_z#?}"}; ic_z=${ic_z#?}
        ic_hh=${ic_z%??} ic_mm=${ic_z#??}; ic_hh=${ic_hh#0} ic_mm=${ic_mm#0}
        ic_off=$(( (${ic_hh:-0} * 3600 + ${ic_mm:-0} * 60) * (${ic_s}1) ))
        ic_e=$1 ic_u=$ic_up
        [ -d "$INTEG_DIR" ] || mkdir -p "$INTEG_DIR" 2>/dev/null || return 1
        printf '%s %s %s\n' "$ic_e" "$ic_u" "$ic_off" > "$INTEG_DIR/clock"
    fi
    IC_NOW=$((ic_e + ic_up - ic_u))
    ic_h=$(( ((IC_NOW + ic_off) / 3600) % 24 ))
    IC_HOUR=$(printf '%02d' "$ic_h")
}
integrity_due()
{
    [ "${VWARD_INTEGRITY_NOW:-0}" = 1 ] && return 0
    # One program for the hourly question (CI budget): the time; the rest from the state file.
    id_at= id_skip= id_first=
    [ ! -r "$INTEG_DIR/state" ] || while IFS='=' read -r id_k id_v; do
        case "$id_k" in at) id_at=$id_v ;; skipped) id_skip=$id_v ;; first) id_first=$id_v ;; esac
    done < "$INTEG_DIR/state"
    integrity_clock || return 1
    set -- "$IC_NOW" "$IC_HOUR"
    case "$id_skip" in ''|*[!0-9]*) ;; *) [ $(( $1 - id_skip )) -ge 86400 ] || return 1 ;; esac
    # Never looked: the first look (the heaviest) waits for the night too; the time VWARD first
    # asked is kept, so it comes within two days whatever the hours the router is on.
    if [ ! -s "$INTEG_DIR/snapshot.tsv" ]; then
        case "$id_first" in
            ''|*[!0-9]*) [ -d "$INTEG_DIR" ] || mkdir -p "$INTEG_DIR" 2>/dev/null || return 1
                printf 'first=%s\n' "$1" >> "$INTEG_DIR/state"; return 1 ;;
        esac
        id_at=$((id_first - 72000))
    fi
    case "$id_at" in ''|*[!0-9]*) return 0 ;; esac
    # Older than 2 days: whatever the hour; else once a day, between 02:00 and 06:00.
    [ $(( $1 - id_at )) -lt 172800 ] || return 0
    [ $(( $1 - id_at )) -ge 72000 ] || return 1
    case "$2" in 02|03|04|05) return 0 ;; esac
    return 1
}
integrity_snapshot()
{
    is_roots=
    for is_r in $INTEG_ROOTS; do [ ! -d "$R$is_r" ] || is_roots="$is_roots $R$is_r"; done
    [ -n "$is_roots" ] || return 1
    # Each file: the time of change («date -r»: Keenetic's BusyBox has no stat with a format)
    # and the checksum. The size is not needed: the time and the contents tell it all.
    # shellcheck disable=SC2086
    find $is_roots -xdev -type f ! -path '*/opt/lib/opkg/*' ! -name '*.pyc' 2>/dev/null > "$INTEG_DIR/list.$$"
    while IFS= read -r is_f; do
        is_m=$(date -r "$is_f" +%s 2>/dev/null) || continue
        is_h=$(md5sum < "$is_f" 2>/dev/null) || continue
        printf '%s\t-\t%s\t%s\n' "${is_f#"$R"}" "$is_m" "${is_h%% *}"
    done < "$INTEG_DIR/list.$$" | sort > "$1"
    rm -f "$INTEG_DIR/list.$$"
    [ -s "$1" ]
}
integrity_watch()
{
    integrity_due || return 0
    mkdir -p "$INTEG_DIR" 2>/dev/null || return 0
    iw_t0=$(date +%s)
    iw_prev_at=0
    [ ! -s "$INTEG_DIR/snapshot.tsv" ] || iw_prev_at=$(date -r "$INTEG_DIR/snapshot.tsv" +%s 2>/dev/null || echo 0)
    if ! integrity_snapshot "$INTEG_DIR/snapshot.new"; then
        # No stat or md5sum on this router: said once, the look waits a day.
        rm -f "$INTEG_DIR/snapshot.new"
        echo "$(date '+%Y-%m-%d %H:%M:%S')|SKIPPED|no_tools" >> "$INTEG_LOG"
        { [ ! -r "$INTEG_DIR/state" ] || grep -v '^skipped=' "$INTEG_DIR/state"; echo "skipped=$(date +%s)"; } > "$INTEG_DIR/state.$$" && mv -f "$INTEG_DIR/state.$$" "$INTEG_DIR/state"
        return 0
    fi
    iw_now=$(date '+%Y-%m-%d %H:%M:%S')
    if [ ! -s "$INTEG_DIR/snapshot.tsv" ]; then
        mv -f "$INTEG_DIR/snapshot.new" "$INTEG_DIR/snapshot.tsv"
        iw_n=$(grep -c . "$INTEG_DIR/snapshot.tsv")
        echo "$iw_now|SUMMARY|files=$iw_n|first=1|seconds=$(( $(date +%s) - iw_t0 ))" >> "$INTEG_LOG"
        printf 'at=%s\nfiles=%s\nspoiled=0\nwritten=0\nunknown=0\n' "$(date +%s)" "$iw_n" > "$INTEG_DIR/state"
        return 0
    fi
    # The VWARD update installed since the last look (its own journal): VWARD's files it wrote.
    iw_upd=0
    awk -v t="$(date -u -d "@$iw_prev_at" '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || echo 0)" '/committed/ && substr($0, 1, 19) >= t {f = 1} END {exit !f}' "$INTEG_UPDATER_LOG" 2>/dev/null && iw_upd=1
    awk -F '\t' 'FNR == NR {s[$1] = $2; m[$1] = $3; h[$1] = $4; next}
        !($1 in s) {print "ADDED\t" $1; next}
        {seen[$1] = 1}
        m[$1] == $3 && s[$1] == $2 && h[$1] != $4 {print "SPOILED\t" $1; next}
        m[$1] != $3 || s[$1] != $2 || h[$1] != $4 {print "WRITTEN\t" $1}
        END {for (f in s) if (!(f in seen)) print "REMOVED\t" f}' "$INTEG_DIR/snapshot.tsv" "$INTEG_DIR/snapshot.new" > "$INTEG_DIR/diff"
    iw_sp=0 iw_wr=0 iw_un=0 iw_vw= iw_pk=
    iw_add=$(grep -c '^ADDED' "$INTEG_DIR/diff") iw_rem=$(grep -c '^REMOVED' "$INTEG_DIR/diff")
    while IFS="$(printf '\t')" read -r iw_k iw_f; do
        iw_pkg=$(grep -lx -- "$iw_f" "$R"/opt/lib/opkg/info/*.list 2>/dev/null | head -n 1)
        iw_pkg=${iw_pkg##*/}; iw_pkg=${iw_pkg%.list}
        case "$iw_k" in
            SPOILED)
                iw_sp=$((iw_sp + 1))
                echo "$iw_now|SPOILED|$iw_f|pkg=${iw_pkg:-vward}" >> "$INTEG_LOG"
                if [ -n "$iw_pkg" ]; then case " $iw_pk " in *" $iw_pkg "*) ;; *) iw_pk="$iw_pk $iw_pkg" ;; esac
                else iw_vw="$iw_vw${iw_vw:+, }$iw_f"; fi ;;
            WRITTEN)
                iw_wr=$((iw_wr + 1))
                iw_by=unknown
                # opkg rewrites the package's file list when it installs it.
                if [ -n "$iw_pkg" ] && [ "$(date -r "$R/opt/lib/opkg/info/$iw_pkg.list" +%s 2>/dev/null || echo 0)" -ge "$iw_prev_at" ]; then iw_by=opkg:$iw_pkg
                elif [ -z "$iw_pkg" ] && [ "$iw_upd" = 1 ]; then iw_by=vward-update
                fi
                [ "$iw_by" != unknown ] || iw_un=$((iw_un + 1))
                [ "$iw_wr" -gt 50 ] || echo "$iw_now|WRITTEN|$iw_f|by=$iw_by" >> "$INTEG_LOG" ;;
            ADDED) [ "$iw_add" -gt 20 ] || echo "$iw_now|ADDED|$iw_f" >> "$INTEG_LOG" ;;
            REMOVED) [ "$iw_rem" -gt 20 ] || echo "$iw_now|REMOVED|$iw_f" >> "$INTEG_LOG" ;;
        esac
    done < "$INTEG_DIR/diff"
    mv -f "$INTEG_DIR/snapshot.new" "$INTEG_DIR/snapshot.tsv"
    rm -f "$INTEG_DIR/diff"
    iw_n=$(grep -c . "$INTEG_DIR/snapshot.tsv")
    iw_pk=${iw_pk# }
    PR_DONE= PR_HELD= PR_STILL= PR_COPY= PR_OPKG=
    if [ -n "$iw_pk" ] && vward_agent_acts maintenance repair:integrity "Испорченные флешкой файлы пакетов ($iw_pk): сверить с Entware и переустановить"; then
        iw_out=$R/tmp/vward-integ-damaged.$$
        # shellcheck disable=SC2086
        pkg_damaged $iw_pk > "$iw_out"
        iw_conf=$(tr '\n' ' ' < "$iw_out"); iw_conf=${iw_conf% }; rm -f "$iw_out"
        # shellcheck disable=SC2086
        [ -z "$iw_conf" ] || pkg_repair integrity $iw_conf
        echo "$iw_now|REPAIR|spoiled=$(echo $iw_pk | tr ' ' ',')|confirmed=$(echo $iw_conf | tr ' ' ',')|reinstalled=$(echo $PR_DONE | tr ' ' ',')|held=$(echo $PR_HELD | tr ' ' ',')|still=$(echo $PR_STILL | tr ' ' ',')|unchecked=$(echo $PKG_UNCHECKED | tr ' ' ',')" >> "$INTEG_LOG"
    fi
    echo "$iw_now|SUMMARY|files=$iw_n|spoiled=$iw_sp|written=$iw_wr|unknown=$iw_un|added=$iw_add|removed=$iw_rem|seconds=$(( $(date +%s) - iw_t0 ))" >> "$INTEG_LOG"
    echo "$iw_now|integrity=files:$iw_n|spoiled=$iw_sp|written=$iw_wr|unknown=$iw_un" >> "$HOUSE_LOG"
    printf 'at=%s\nfiles=%s\nspoiled=%s\nwritten=%s\nunknown=%s\nreinstalled=%s\nheld=%s\n' "$(date +%s)" "$iw_n" "$iw_sp" "$iw_wr" "$iw_un" "$PR_DONE" "$PR_HELD" > "$INTEG_DIR/state"
    [ "$iw_sp" -gt 0 ] || return 0
    command -v vward_note >/dev/null 2>&1 ||
        { [ ! -r "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}" ] || . "${VWARD_PROFILE_LIB:-/opt/lib/vward/vward-device-profile.sh}"; } 2>/dev/null
    command -v vward_note >/dev/null 2>&1 || return 0
    iw_txt="Испорчено файлов: $iw_sp: содержимое изменилось, хотя ни одна программа их не записывала.${iw_pk:+ Пакеты: $(echo $iw_pk | sed 's/ /, /g').}${iw_vw:+ Файлы VWARD: $iw_vw - их исправит переустановка обновления VWARD.}"
    [ -z "$iw_pk" ] || iw_txt="$iw_txt $(pkg_repair_text)"
    [ -n "$iw_pk" ] || iw_txt="$iw_txt Проверьте флешку на компьютере или замените её."
    vward_note err "Флешка портит файлы программ" "$iw_txt" system
}
integrity_watch

# VWARD switched off as a whole («Отключить VWARD»): logs, copies and VWARD's own updates go
# on (a fix may arrive), nothing else VWARD does starts.
if ! vward_off; then

# Updates of other software (Entware packages, AdGuard Home, Keenetic firmware):
# once a day, in the hour VWARD installs its own updates; the first check at
# once.  Detached: opkg may take minutes.  Builtins only until it is due.
EXT_DAY_FILE=${VWARD_EXT_DAY_FILE:-/tmp/vward-ext-update-day}
if [ -x "$BACKUP_HELPER" ]; then
    EXT_TODAY=${BACKUP_NOW%% *}; EXT_NOW_HOUR=${BACKUP_NOW#* }; EXT_NOW_HOUR=${EXT_NOW_HOUR%%:*}
    EXT_DAY=""
    [ ! -r "$EXT_DAY_FILE" ] || read -r EXT_DAY < "$EXT_DAY_FILE" || :
    EXT_HOUR=03
    if [ -r "${VWARD_UPDATE_CONFIG:-$R/opt/etc/vward/update.conf}" ]; then
        while IFS='=' read -r EXT_K EXT_V; do
            [ "$EXT_K" = safe_window_start ] && EXT_HOUR=${EXT_V%%:*}
        done < "${VWARD_UPDATE_CONFIG:-$R/opt/etc/vward/update.conf}"
    fi
    EXT_OP=
    if [ ! -e "${VWARD_EXT_UPDATE_STATE:-$R/opt/var/lib/vward/ext-update}/check.state" ]; then EXT_OP=ext-check
    elif [ "$EXT_DAY" != "$EXT_TODAY" ] && [ "$EXT_NOW_HOUR" = "$EXT_HOUR" ]; then EXT_OP=ext-daily
    fi
    if [ -n "$EXT_OP" ] && [ "$EXT_DAY" != "$EXT_TODAY" ]; then
        echo "$EXT_TODAY" > "$EXT_DAY_FILE" 2>/dev/null || :
        "$BACKUP_HELPER" "$EXT_OP" now </dev/null >/dev/null 2>&1 &
        echo "$BACKUP_NOW|ext_update=$EXT_OP" >> "$HOUSE_LOG"
    fi
fi

# The real-time watcher: its program for this processor (pinned SHA-256), and what it
# watches (tunnels come and go). Without it everything works as before.
SENTINEL_CTL=${VWARD_SENTINEL_CTL:-/opt/bin/vward-sentinel.sh}
if [ -x "$SENTINEL_CTL" ]; then
    { "$SENTINEL_CTL" install && "$SENTINEL_CTL" reload; } </dev/null >/dev/null 2>&1 &
fi

# Services catalog (iplist, rebuilt by VWARD's workflow every night): once a day
# from 06:00; the lists of services switched on follow it.  Detached.
SERVICES_DAY_FILE=${VWARD_SERVICES_DAY_FILE:-/tmp/vward-services-day}
if [ -x "$BACKUP_HELPER" ]; then
    SV_TODAY=${BACKUP_NOW%% *}; SV_HOUR=${BACKUP_NOW#* }; SV_HOUR=${SV_HOUR%%:*}
    SV_DAY=""
    [ ! -r "$SERVICES_DAY_FILE" ] || read -r SV_DAY < "$SERVICES_DAY_FILE" || :
    # A busy router: the next hour (at most 2 hours late).
    if [ "$SV_DAY" != "$SV_TODAY" ] && [ "$SV_HOUR" -ge 6 ] 2>/dev/null && ! vward_defer services-refresh; then
        echo "$SV_TODAY" > "$SERVICES_DAY_FILE" 2>/dev/null || :
        "$BACKUP_HELPER" services-refresh now </dev/null >/dev/null 2>&1 &
        echo "$BACKUP_NOW|services=refresh" >> "$HOUSE_LOG"
    fi
fi

# IP categories: cron updates them at 00:10. A router that was off or rebooting then waited
# a whole day: when the last update is over 26 hours old, once a day, in the background.
POLICY_SYNC_LOG="$R/opt/var/log/vward-policy-sync-sync.log"
POLICY_CATCHUP_FILE=${VWARD_POLICY_CATCHUP_FILE:-/tmp/vward-policy-catchup-day}
POLICY_CHAIN=${VWARD_POLICY_CHAIN_BIN:-/opt/bin/vward-policy-chain.sh}
POLICY_RECONCILE=${VWARD_POLICY_RECONCILE_BIN:-/opt/bin/vward-policy-reconcile.sh}
POLICY_SYNC=${VWARD_POLICY_SYNC_BIN:-/opt/bin/vward-policy-sync.sh}
if [ -x "$POLICY_CHAIN" ] && [ -f "$POLICY_SYNC_LOG" ]; then
    PC_NOW=${BACKUP_NOW:-$(date '+%Y-%m-%d %H:%M:%S')}
    PC_TODAY=${PC_NOW%% *}; PC_HOUR=${PC_NOW#* }; PC_HOUR=${PC_HOUR%%:*}
    PC_DAY=""
    [ ! -r "$POLICY_CATCHUP_FILE" ] || read -r PC_DAY < "$POLICY_CATCHUP_FILE" || :
    # Not in the hour of the scheduled run; a busy router: the next hour.
    if [ "$PC_DAY" != "$PC_TODAY" ] && [ "$PC_HOUR" != 00 ] && [ -n "$(find "$POLICY_SYNC_LOG" -mmin +1560 2>/dev/null)" ] &&
        ! vward_defer policy-catchup; then
        echo "$PC_TODAY" > "$POLICY_CATCHUP_FILE" 2>/dev/null || :
        { "$POLICY_CHAIN" && "$POLICY_RECONCILE"; } </dev/null >/dev/null 2>&1 &
        echo "$PC_NOW|policy=catchup" >> "$HOUSE_LOG"
    # Otherwise, every hour, the IP categories are matched again to the routed domains and to
    # Smart DNS without downloading anything: a category that now holds a Smart DNS address
    # leaves the tunnel within the hour, not at the next night's update.
    elif [ "$PC_HOUR" != 00 ] && [ -x "$POLICY_SYNC" ] && ! vward_defer policy-reconcile; then
        "$POLICY_SYNC" --reconcile </dev/null >/dev/null 2>&1 &
        echo "$PC_NOW|policy=reconcile" >> "$HOUSE_LOG"
    fi
fi

fi

echo "$(date '+%Y-%m-%d %H:%M:%S')|retention_errors=$RETENTION_ERRORS" \
    >> "$HOUSE_LOG"

[ "$ERRORS" -eq 0 ] && [ "$RETENTION_ERRORS" -eq 0 ]
