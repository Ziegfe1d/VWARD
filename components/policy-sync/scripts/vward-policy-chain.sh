#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin

AUDIT="/opt/bin/vward-policy-audit.sh"
SUBNET="/opt/bin/vward-policy-sync.sh"

SUMMARY="/opt/var/log/vward-policy-audit-summary.log"
LOG="/opt/var/log/vward-policy-audit-chain.log"

WAIT_STEP=2
MAX_WAIT=60

log() {
    printf '%s %s\n' \
        "$(date '+%Y-%m-%d %H:%M:%S')" \
        "$*" >> "$LOG"
}

# Ограничиваем размер журнала.
if [ -f "$LOG" ]; then
    SIZE="$(wc -c < "$LOG" 2>/dev/null)"
    [ -n "$SIZE" ] || SIZE=0

    if [ "$SIZE" -gt 524288 ]; then
        tail -n 1500 "$LOG" > "$LOG.tmp"
        mv "$LOG.tmp" "$LOG"
    fi
fi

BEFORE_SUMMARY="$(tail -n 1 "$SUMMARY" 2>/dev/null)"

log "===== AUDIT_CHAIN_START ====="
log "SUMMARY_BEFORE=$BEFORE_SUMMARY"

# =========================================================
# 1. Ночной аудит
# =========================================================

"$AUDIT" "$@"
AUDIT_RC=$?

log "AUDIT_PROCESS_FINISHED rc=$AUDIT_RC"

if [ "$AUDIT_RC" -ne 0 ]; then
    log "CHAIN_ABORT audit_rc=$AUDIT_RC"
    exit "$AUDIT_RC"
fi

# =========================================================
# 2. Подтверждаем, что появился НОВЫЙ полный summary
# =========================================================

WAITED=0
COMPLETE=0
AFTER_SUMMARY=""

while [ "$WAITED" -le "$MAX_WAIT" ]; do

    AFTER_SUMMARY="$(tail -n 1 "$SUMMARY" 2>/dev/null)"

    if [ -n "$AFTER_SUMMARY" ] &&
       [ "$AFTER_SUMMARY" != "$BEFORE_SUMMARY" ]
    then

        TARGETS="$(
            echo "$AFTER_SUMMARY" |
            sed -n 's/.*|targets=\([0-9][0-9]*\).*/\1/p'
        )"

        CHECKED="$(
            echo "$AFTER_SUMMARY" |
            sed -n 's/.*|checked=\([0-9][0-9]*\).*/\1/p'
        )"

        if [ -n "$TARGETS" ] &&
           [ -n "$CHECKED" ] &&
           [ "$TARGETS" -gt 0 ] 2>/dev/null &&
           [ "$CHECKED" -eq "$TARGETS" ] 2>/dev/null
        then
            COMPLETE=1
            break
        fi
    fi

    sleep "$WAIT_STEP"
    WAITED=$((WAITED + WAIT_STEP))
done

if [ "$COMPLETE" -ne 1 ]; then
    log "CHAIN_ABORT audit_summary_not_confirmed"
    log "SUMMARY_AFTER=$AFTER_SUMMARY"
    exit 124
fi

log "AUDIT_CONFIRMED waited=${WAITED}s"
log "SUMMARY_AFTER=$AFTER_SUMMARY"

# Небольшой технический зазор.
sleep 2

# =========================================================
# 3. Сразу после полного аудита обновляем CIDR
# =========================================================

log "SUBNET_SYNC_START"

"$SUBNET" >> "$LOG" 2>&1
SUBNET_RC=$?

log "SUBNET_SYNC_FINISHED rc=$SUBNET_RC"
log "===== AUDIT_CHAIN_END ====="

if [ "$SUBNET_RC" -ne 0 ]; then
    log "SUBNET_WARNING rc=$SUBNET_RC reconcile_will_continue"
fi

# Audit completed successfully. Subnet failure must not block
# the existing nightly reconcile connected by cron with &&.
exit 0
