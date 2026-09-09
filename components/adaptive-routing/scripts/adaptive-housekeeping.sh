#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

HOUSE_LOG="/opt/var/log/adaptive-housekeeping.log"

# Формат:
# файл|максимальный_размер_байт
POLICY="
/opt/var/log/crond.log|524288
/opt/var/log/adaptive-live-events.log|524288
/opt/var/log/agh-adaptive-live.log|262144
/opt/var/log/wg-health.log|262144
/opt/var/log/wg-failopen.log|262144
/opt/var/log/wan-guardian.log|262144
/opt/var/log/wan-guardian-recovery.log|262144
/opt/var/log/vpn-audit.log|524288
/opt/var/log/vpn-audit-summary.log|262144
/opt/var/log/vpn-audit-chain.log|262144
/opt/var/log/vpn-night-reconcile.log|262144
/opt/var/log/vpn-subnet-sync.log|262144
/opt/var/log/adaptive-hints-update.log|262144
/opt/var/log/adaptive-route.log|262144
/opt/var/log/crond-supervisor.log|262144
"

KEEP=2

rotate_file()
{
    F="$1"
    LIMIT="$2"

    [ -f "$F" ] || return 0

    SIZE="$(wc -c < "$F" 2>/dev/null)"

    case "$SIZE" in
        ''|*[!0-9]*)
            return 1
            ;;
    esac

    [ "$SIZE" -lt "$LIMIT" ] && return 0

    rm -f "$F.$KEEP.gz"

    I=$((KEEP - 1))

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

    echo "ROTATED|$F|bytes=$SIZE|limit=$LIMIT"
    return 0
}

ROTATED=0
ERRORS=0

OLDIFS="$IFS"
IFS='
'

for ROW in $POLICY; do

    [ -n "$ROW" ] || continue

    F="${ROW%%|*}"
    LIMIT="${ROW##*|}"

    RES="$(rotate_file "$F" "$LIMIT")"
    RC=$?

    if [ "$RC" -ne 0 ]; then
        echo "ERROR|$F"
        ERRORS=$((ERRORS + 1))
        continue
    fi

    if [ -n "$RES" ]; then
        echo "$RES"
        ROTATED=$((ROTATED + 1))
    fi
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

[ "$ERRORS" -eq 0 ]

# ============================================================
# VWARD STORAGE RETENTION
# ============================================================

dir_kb()
{
    D="$1"

    [ -d "$D" ] || {
        echo 0
        return
    }

    du -sk "$D" 2>/dev/null | awk '{print $1}'
}


cap_files_dir()
{
    D="$1"
    LIMIT="$2"

    [ -d "$D" ] || return 0

    while :; do

        SIZE="$(dir_kb "$D")"

        case "$SIZE" in
            ''|*[!0-9]*) return 1 ;;
        esac

        [ "$SIZE" -le "$LIMIT" ] && break

        COUNT="$(
            find "$D" -maxdepth 1 -type f 2>/dev/null |
            wc -l
        )"

        # Всегда сохраняем хотя бы один, самый новый файл.
        [ "$COUNT" -le 1 ] && break

        OLD="$(
            find "$D" -maxdepth 1 -type f \
                -printf '%T@|%p\n' 2>/dev/null |
            sort -n |
            head -1 |
            cut -d'|' -f2-
        )"

        [ -n "$OLD" ] || break

        echo "RETENTION_DELETE|$OLD"
        rm -f "$OLD" || return 1
    done

    return 0
}


cap_incident_dirs()
{
    D="$1"
    LIMIT="$2"

    [ -d "$D" ] || return 0

    while :; do

        SIZE="$(dir_kb "$D")"

        case "$SIZE" in
            ''|*[!0-9]*) return 1 ;;
        esac

        [ "$SIZE" -le "$LIMIT" ] && break

        COUNT="$(
            find "$D" -mindepth 1 -maxdepth 1 -type d 2>/dev/null |
            wc -l
        )"

        # Последний / самый новый инцидент автоматически не удаляем.
        [ "$COUNT" -le 1 ] && {
            echo "RETENTION_FORENSIC_LIMIT_EXCEEDED|size_kb=$SIZE|kept_latest=1"
            break
        }

        OLD="$(
            find "$D" -mindepth 1 -maxdepth 1 -type d \
                -printf '%T@|%p\n' 2>/dev/null |
            sort -n |
            head -1 |
            cut -d'|' -f2-
        )"

        [ -n "$OLD" ] || break

        echo "RETENTION_DELETE_INCIDENT|$OLD"
        rm -rf "$OLD" || return 1
    done

    return 0
}


keep_newest_files()
{
    D="$1"
    KEEP="$2"

    [ -d "$D" ] || return 0

    TMP="/tmp/vward-retention.$$"

    find "$D" -maxdepth 1 -type f \
        -printf '%T@|%p\n' 2>/dev/null |
    sort -nr > "$TMP"

    N=0

    while IFS='|' read -r MT F; do

        [ -n "$F" ] || continue

        N=$((N + 1))

        if [ "$N" -gt "$KEEP" ]; then
            echo "RETENTION_DELETE_BACKUP|$F"
            rm -f "$F"
        fi

    done < "$TMP"

    rm -f "$TMP"

    return 0
}


RETENTION_ERRORS=0

# Диагностические отчёты: максимум 2 МБ.
cap_files_dir \
    /opt/var/log/vward/diagnostics \
    2048 ||
RETENTION_ERRORS=$((RETENTION_ERRORS + 1))

# Forensic-инциденты: максимум 12 МБ суммарно.
# Самый новый инцидент всегда сохраняется.
cap_incident_dirs \
    /opt/var/backups/vward/forensics \
    12288 ||
RETENTION_ERRORS=$((RETENTION_ERRORS + 1))

# Старые пакеты исходников: максимум 4 МБ.
cap_incident_dirs \
    /opt/var/backups/vward/legacy-scripts \
    4096 ||
RETENTION_ERRORS=$((RETENTION_ERRORS + 1))

# Конфигурационные rollback-копии.
keep_newest_files \
    /opt/var/backups/vward/log-policy \
    5 ||
RETENTION_ERRORS=$((RETENTION_ERRORS + 1))

keep_newest_files \
    /opt/var/backups/vward/housekeeping \
    5 ||
RETENTION_ERRORS=$((RETENTION_ERRORS + 1))

echo "$(date '+%Y-%m-%d %H:%M:%S')|retention_errors=$RETENTION_ERRORS" \
    >> "$HOUSE_LOG"

[ "$RETENTION_ERRORS" -eq 0 ]
