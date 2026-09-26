#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
[ -r "$VWARD_ADMISSION_LIB" ] || { echo "VWARD runtime admission library is unavailable" >&2; exit 1; }
. "$VWARD_ADMISSION_LIB"
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
/opt/var/log/vward-route-discovery.log|262144
/opt/var/log/vward-ads-privacy-guard.log|524288
/opt/var/log/vward-wifi-client-guard.log|262144
/opt/var/log/vward-console-lighttpd.log|131072
/opt/var/log/vward/console-audit.log|262144
/opt/var/log/vward/updater-watch.log|262144
/opt/var/log/vward/updater-recovery.log|131072
"

ROTATE_KEEP=2

rotate_file()
{
    F="$1"
    SIZE="$2"

    rm -f "$F.$ROTATE_KEEP.gz"

    I=$((ROTATE_KEEP - 1))

    while [ "$I" -ge 1 ]; do
        J=$((I + 1))

        if [ -f "$F.$I.gz" ]; then
            mv "$F.$I.gz" "$F.$J.gz" || return 1
        fi

        I=$((I - 1))
    done

    TMP="$F.rotate.$$"

    cp "$F" "$TMP" || {
        rm -f "$TMP"
        return 1
    }

    gzip -1 "$TMP" || {
        rm -f "$TMP"
        return 1
    }

    mv "$TMP.gz" "$F.1.gz" || {
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
    POLICY="$POLICY" R="$R" awk '
        BEGIN {
            n = split(ENVIRON["POLICY"], rows, "\n")
            for (i = 1; i <= n; i++) if (split(rows[i], f, "|") == 2) limit[ENVIRON["R"] f[1]] = f[2] + 0
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

# Сам housekeeping не должен бесконечно логировать сам себя.
if [ -f "$HOUSE_LOG" ]; then
    HS="$(wc -c < "$HOUSE_LOG" 2>/dev/null)"

    case "$HS" in
        ''|*[!0-9]*) HS=0 ;;
    esac

    if [ "$HS" -ge 262144 ]; then
        tail -n 300 "$HOUSE_LOG" > "$HOUSE_LOG.tmp.$$" &&
        mv "$HOUSE_LOG.tmp.$$" "$HOUSE_LOG"
    fi
fi

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

# A tunnel .conf holds its private key: uploads now live in RAM only, and
# those an older version kept on the USB drive go.
rm -f "$R/opt/var/run/vward/console-tunnel/upload."* 2>/dev/null
rmdir "$R/opt/var/run/vward/console-tunnel" 2>/dev/null

# Locks whose owner is gone (killed, power cut) would hold back the updater.
vward_locks_sweep

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
    ! grep -q '^VU_ENGINE_VERSION=' "$EM_ROOT/current/vward-update-common-base.sh" || return 0
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
            curl -fsS --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 120 --max-filesize "$3" -o "$2" "$1" 2>/dev/null
        }
        if [ -n "${VWARD_ENGINE_MOVE_SOURCE:-}" ]; then src=manifest.json; else src=$EM_URL; fi
        em_fetch "$src" "$EM_T/manifest.json" 262144 || exit 3
        jq -cS '.signed' "$EM_T/manifest.json" > "$EM_T/signed" &&
            jq -r '.signature' "$EM_T/manifest.json" | openssl base64 -d -A > "$EM_T/sig" &&
            openssl pkeyutl -verify -pubin -inkey "$EM_KEY" -rawin -in "$EM_T/signed" -sigfile "$EM_T/sig" >/dev/null 2>&1 || exit 4
        jq -e --arg ch "$EM_CHANNEL" '.signed.schema == 2 and .signed.channel == $ch' "$EM_T/manifest.json" >/dev/null || exit 4
        base=$(jq -r '.signed.files_base' "$EM_T/manifest.json")
        case "$base" in https://*/) ;; *) exit 4 ;; esac
        jq -r '.signed.engine.files[] | [.name, .sha256, (.size | tostring)] | @tsv' "$EM_T/manifest.json" |
        while IFS="$(printf '\t')" read -r name sha size; do
            case "$name" in ''|*[!A-Za-z0-9._-]*) exit 4 ;; esac
            if [ -n "${VWARD_ENGINE_MOVE_SOURCE:-}" ]; then src=files/$sha; else src=$base$sha; fi
            em_fetch "$src" "$EM_T/$name" "$((size + 1))" || exit 3
            [ "$(wc -c < "$EM_T/$name" | tr -d ' ')" = "$size" ] && [ "$(sha256sum "$EM_T/$name" | awk '{print $1}')" = "$sha" ] || exit 4
        done || exit $?
        sh "$EM_T/vward-update.sh" --engine-adopt "$EM_T" "$EM_T/manifest.json" >/dev/null 2>&1 || exit 5
    )
    EM_RC=$?
    rm -rf "${EM_T:?}"
    case "$EM_RC" in
        0) echo "ENGINE_MOVED|v2"; echo "$(date '+%Y-%m-%d %H:%M:%S')|engine_move=done" >> "$HOUSE_LOG" ;;
        3) : ;;
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

echo "$(date '+%Y-%m-%d %H:%M:%S')|retention_errors=$RETENTION_ERRORS" \
    >> "$HOUSE_LOG"

[ "$ERRORS" -eq 0 ] && [ "$RETENTION_ERRORS" -eq 0 ]
