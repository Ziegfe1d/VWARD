#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "FAIL: common library not found" >&2; exit 1; }
. "$LIB"

VWARD_ADMISSION_LIB=${VWARD_ADMISSION_LIB:-/opt/lib/vward/vward-runtime-admission.sh}
[ -r "$VWARD_ADMISSION_LIB" ] || VWARD_ADMISSION_LIB="$SELF_DIR/../../runtime/lib/vward-runtime-admission.sh"
[ -r "$VWARD_ADMISSION_LIB" ] || { echo "VWARD runtime admission library is unavailable" >&2; exit 1; }
. "$VWARD_ADMISSION_LIB"
vward_component_gate ads-privacy-guard
vward_admission_enter ads-scheduler || exit $?
cleanup() { vward_admission_leave 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

ads_mkdirs || ads_die "cannot create component directories"
ads_load_config

ENABLED="${ENABLED:-1}"
RUN_MODE="${RUN_MODE:-scheduled}"
SCHEDULE_INTERVAL_MIN="$(ads_num "${SCHEDULE_INTERVAL_MIN:-10}" 10)"
DYNAMIC_MIN_INTERVAL_SEC="$(ads_num "${DYNAMIC_MIN_INTERVAL_SEC:-120}" 120)"
DYNAMIC_MAX_LOAD_PER_CPU_X100="$(ads_num "${DYNAMIC_MAX_LOAD_PER_CPU_X100:-80}" 80)"
DYNAMIC_MIN_MEM_AVAILABLE_KB="$(ads_num "${DYNAMIC_MIN_MEM_AVAILABLE_KB:-16384}" 16384)"
DYNAMIC_MIN_OPT_FREE_KB="$(ads_num "${DYNAMIC_MIN_OPT_FREE_KB:-32768}" 32768)"
DYNAMIC_MAX_CANDIDATES_PER_RUN="$(ads_num "${DYNAMIC_MAX_CANDIDATES_PER_RUN:-100}" 100)"
DYNAMIC_SCAN_TAIL_LINES="$(ads_num "${DYNAMIC_SCAN_TAIL_LINES:-5000}" 5000)"
AUTO_SOURCE_UPDATE="${AUTO_SOURCE_UPDATE:-1}"
SOURCE_UPDATE_INTERVAL_HOURS="$(ads_num "${SOURCE_UPDATE_INTERVAL_HOURS:-24}" 24)"

STATE_FILE="$ADS_STATE/scheduler.state"
SOURCE_RETRY_FILE="${VWARD_ADS_SOURCE_RETRY:-/tmp/vward-ads-source-retry}"
SOURCE_RETRY_SEC="$(ads_num "${SOURCE_RETRY_SEC:-3600}" 3600)"
STATUS_FILE="${VWARD_ADS_SCHEDULER_STATUS:-/tmp/vward-ads-scheduler.status}"
SCAN="${VWARD_ADS_SCANNER:-/opt/bin/vward-ads-privacy-guard.sh}"
[ -x "$SCAN" ] || SCAN="$SELF_DIR/vward-ads-privacy-guard.sh"
SOURCES="${VWARD_ADS_SOURCES_UPDATER:-/opt/bin/vward-ads-privacy-sources-update.sh}"
[ -x "$SOURCES" ] || SOURCES="$SELF_DIR/vward-ads-privacy-sources-update.sh"
JOB="${VWARD_ADS_JOB_WORKER:-/opt/bin/vward-ads-privacy-job.sh}"
[ -x "$JOB" ] || JOB="$SELF_DIR/vward-ads-privacy-job.sh"
QUERY_READER="${VWARD_ADS_QUERY_READER:-/opt/bin/vward-ads-privacy-query-read.sh}"
[ -x "$QUERY_READER" ] || QUERY_READER="$SELF_DIR/vward-ads-privacy-query-read.sh"

# Loads the persisted scheduler state into ST_SCAN, ST_SOURCE and ST_SIG.
state_load()
{
    ST_SCAN="" ST_SOURCE="" ST_SIG=""
    [ -r "$STATE_FILE" ] || return 0
    while IFS='=' read -r K V; do
        case "$K" in
            last_scan_epoch) [ -n "$ST_SCAN" ] || ST_SCAN=$V ;;
            last_source_epoch) [ -n "$ST_SOURCE" ] || ST_SOURCE=$V ;;
            last_query_signature) [ -n "$ST_SIG" ] || ST_SIG=$V ;;
        esac
    done < "$STATE_FILE"
}

# The scheduler runs every minute; the state on USB is rewritten only when a
# value changes, and the temporary copy is built in RAM.
state_write()
{
    LS="$1" LSO="$2" SIG="$3"
    [ "$LS|$LSO|$SIG" != "$ST_SCAN|$ST_SOURCE|$ST_SIG" ] || [ ! -r "$STATE_FILE" ] || return 0
    TMP="/tmp/vward-ads-scheduler-state.$$"
    {
        echo "last_scan_epoch=$LS"
        echo "last_source_epoch=$LSO"
        echo "last_query_signature=$SIG"
    } > "$TMP" || return 1
    ads_atomic_copy "$TMP" "$STATE_FILE" 0644
    rm -f "$TMP"
}

status_write()
{
    PHASE="$1" REASON="$2" NEXT="$3"
    TMP="/tmp/vward-ads-scheduler.status.$$"
    {
        echo "ts=$(ads_now)"
        echo "phase=$PHASE"
        echo "mode=$RUN_MODE"
        echo "reason=$REASON"
        echo "next_due_epoch=$NEXT"
    } > "$TMP"
    mv "$TMP" "$STATUS_FILE" 2>/dev/null || true
}

query_signature()
{
    # Dynamic mode must notice fresh AGH API data even while the persisted
    # querylog file is buffered.  Hash a small normalized allowed-query window;
    # query-reader itself falls back to the local files when QUERY_SOURCE=auto.
    if [ -x "$QUERY_READER" ]; then
        QS="$(QUERY_SOURCE="${QUERY_SOURCE:-auto}" "$QUERY_READER" 100 2>/dev/null | cksum 2>/dev/null | awk '{print $1 ":" $2}')"
        [ -n "$QS" ] && { printf 'query:%s' "$QS"; return 0; }
    fi
    for F in "$ADS_QUERYLOG_OLD" "$ADS_QUERYLOG"; do
        if [ -r "$F" ]; then
            SIZE="$(wc -c < "$F" 2>/dev/null | tr -d ' ')"
            TAIL="$(tail -c 512 "$F" 2>/dev/null | cksum 2>/dev/null | awk '{print $1 ":" $2}')"
            printf '%s:%s;' "${SIZE:-0}" "${TAIL:-0:0}"
        else
            printf '0:0:0;'
        fi
    done
}

resource_gate()
{
    CPU_COUNT="$(grep -c '^processor[[:space:]]*:' /proc/cpuinfo 2>/dev/null)"
    CPU_COUNT="$(ads_num "$CPU_COUNT" 1)"
    [ "$CPU_COUNT" -gt 0 ] || CPU_COUNT=1
    LOAD_X100="$(awk '{printf "%d", ($1+0)*100}' /proc/loadavg 2>/dev/null)"
    LOAD_X100="$(ads_num "$LOAD_X100" 0)"
    LIMIT=$((CPU_COUNT * DYNAMIC_MAX_LOAD_PER_CPU_X100))
    [ "$LOAD_X100" -le "$LIMIT" ] || { echo "load:${LOAD_X100}/${LIMIT}"; return 1; }

    MEM="$(awk '/^MemAvailable:/ {print $2+0; exit}' /proc/meminfo 2>/dev/null)"
    MEM="$(ads_num "$MEM" 0)"
    [ "$MEM" -ge "$DYNAMIC_MIN_MEM_AVAILABLE_KB" ] || { echo "memory:${MEM}"; return 1; }

    FREE="$(df -Pk /opt 2>/dev/null | awk 'NR==2 {print $4+0}')"
    FREE="$(ads_num "$FREE" 0)"
    [ "$FREE" -ge "$DYNAMIC_MIN_OPT_FREE_KB" ] || { echo "storage:${FREE}"; return 1; }

    return 0
}

NOW="$(ads_epoch)"
state_load
LAST_SCAN="$(ads_num "$ST_SCAN" 0)"
LAST_SOURCE="$(ads_num "$ST_SOURCE" 0)"
OLD_SIG=$ST_SIG

if ! ads_bool "$ENABLED"; then
    status_write disabled component_disabled 0
    echo "SCHEDULER=DISABLED"
    exit 0
fi

PAUSED=0
if [ -r "$ADS_CONTROL_STATE" ]; then
    PAUSED="$(awk -F= '$1=="paused" {print $2; exit}' "$ADS_CONTROL_STATE")"
fi
case "$PAUSED" in 1) ;; *) PAUSED=0 ;; esac
if [ "$PAUSED" -eq 1 ]; then
    status_write paused user_pause 0
    echo "SCHEDULER=PAUSED"
    exit 0
fi

# Console requests enqueue long operations. Process at most one queued job per
# scheduler tick, and only when the same low-load gate permits it.
if [ -x "$JOB" ] && [ -s "$ADS_STATE/jobs/queue" ]; then
    JOB_GATE="$(resource_gate)"
    if [ $? -eq 0 ]; then
        status_write job queued 0
        JOB_RC=0
        "$JOB" worker || JOB_RC=$?
        state_write "$LAST_SCAN" "$LAST_SOURCE" "$OLD_SIG" >/dev/null 2>&1 || true
        if [ "$JOB_RC" -eq 0 ]; then
            status_write idle job_complete 0
            echo "SCHEDULER=JOB_PASS"
            exit 0
        fi
        status_write error "job_rc_$JOB_RC" 0
        echo "SCHEDULER=JOB_FAIL"
        echo "JOB_RC=$JOB_RC"
        exit "$JOB_RC"
    fi
    status_write deferred "job_$JOB_GATE" 0
    echo "SCHEDULER=JOB_DEFERRED"
    echo "REASON=$JOB_GATE"
    exit 0
fi

# Source refresh is independent from scan mode, but still respects resource gates.
if ads_bool "$AUTO_SOURCE_UPDATE" && [ -x "$SOURCES" ]; then
    SOURCE_DUE=$((LAST_SOURCE + SOURCE_UPDATE_INTERVAL_HOURS * 3600))
    # A failed update is retried after SOURCE_RETRY_SEC, not on every tick:
    # without a network each attempt would download and rewrite files each minute.
    LAST_TRY=0
    [ ! -r "$SOURCE_RETRY_FILE" ] || read -r LAST_TRY < "$SOURCE_RETRY_FILE" 2>/dev/null
    LAST_TRY="$(ads_num "$LAST_TRY" 0)"
    if [ "$NOW" -ge "$SOURCE_DUE" ] && [ "$NOW" -ge $((LAST_TRY + SOURCE_RETRY_SEC)) ]; then
        GATE="$(resource_gate)"
        if [ $? -eq 0 ]; then
            status_write source-update due "$SOURCE_DUE"
            if "$SOURCES"; then
                LAST_SOURCE="$NOW"
                rm -f "$SOURCE_RETRY_FILE"
            else
                echo "$NOW" > "$SOURCE_RETRY_FILE" 2>/dev/null || true
                ads_log "SCHEDULER|source-update-failed|retry_after=${SOURCE_RETRY_SEC}s"
            fi
        else
            status_write deferred "source_$GATE" "$SOURCE_DUE"
        fi
    fi
fi

case "$RUN_MODE" in
    manual)
        # Keep the signature of the last successfully analysed snapshot.  Query
        # activity accumulated while manual mode is selected should become
        # eligible if the user later switches to dynamic mode.
        state_write "$LAST_SCAN" "$LAST_SOURCE" "$OLD_SIG" >/dev/null 2>&1 || true
        status_write idle manual_mode 0
        echo "SCHEDULER=MANUAL_IDLE"
        exit 0
        ;;
    scheduled)
        DUE=$((LAST_SCAN + SCHEDULE_INTERVAL_MIN * 60))
        [ "$NOW" -ge "$DUE" ] || {
            # Do not mark unanalysed query-log changes as consumed.
            state_write "$LAST_SCAN" "$LAST_SOURCE" "$OLD_SIG" >/dev/null 2>&1 || true
            status_write idle waiting_schedule "$DUE"
            echo "SCHEDULER=WAIT"
            echo "NEXT_DUE_EPOCH=$DUE"
            exit 0
        }
        ;;
    dynamic)
        DUE=$((LAST_SCAN + DYNAMIC_MIN_INTERVAL_SEC))
        # Only dynamic mode needs the query-log signature before a scan.
        NEW_SIG="$(query_signature)"
        [ "$NEW_SIG" != "$OLD_SIG" ] || {
            state_write "$LAST_SCAN" "$LAST_SOURCE" "$NEW_SIG" >/dev/null 2>&1 || true
            status_write idle no_new_querylog "$DUE"
            echo "SCHEDULER=NO_CHANGE"
            exit 0
        }
        [ "$NOW" -ge "$DUE" ] || {
            state_write "$LAST_SCAN" "$LAST_SOURCE" "$OLD_SIG" >/dev/null 2>&1 || true
            status_write idle dynamic_backoff "$DUE"
            echo "SCHEDULER=BACKOFF"
            echo "NEXT_DUE_EPOCH=$DUE"
            exit 0
        }
        ;;
    *)
        status_write error invalid_run_mode 0
        echo "SCHEDULER=FAIL"
        echo "REASON=invalid_run_mode"
        exit 2
        ;;
esac

GATE="$(resource_gate)"
if [ $? -ne 0 ]; then
    state_write "$LAST_SCAN" "$LAST_SOURCE" "$OLD_SIG" >/dev/null 2>&1 || true
    status_write deferred "$GATE" "$DUE"
    echo "SCHEDULER=DEFERRED"
    echo "REASON=$GATE"
    exit 0
fi

status_write scanning due "$DUE"
RC=0
if [ "$RUN_MODE" = dynamic ]; then
    VWARD_ADS_SCAN_TAIL_OVERRIDE="$DYNAMIC_SCAN_TAIL_LINES" \
    VWARD_ADS_MAX_CANDIDATES_OVERRIDE="$DYNAMIC_MAX_CANDIDATES_PER_RUN" \
    "$SCAN" scan || RC=$?
else
    "$SCAN" scan || RC=$?
fi

if [ "$RC" -eq 0 ]; then
    LAST_SCAN="$NOW"
    NEW_SIG="$(query_signature)"
    state_write "$LAST_SCAN" "$LAST_SOURCE" "$NEW_SIG" >/dev/null 2>&1 || true
    NEXT=0
    [ "$RUN_MODE" = scheduled ] && NEXT=$((LAST_SCAN + SCHEDULE_INTERVAL_MIN * 60))
    [ "$RUN_MODE" = dynamic ] && NEXT=$((LAST_SCAN + DYNAMIC_MIN_INTERVAL_SEC))
    status_write idle scan_complete "$NEXT"
    echo "SCHEDULER=PASS"
    exit 0
fi

state_write "$LAST_SCAN" "$LAST_SOURCE" "$OLD_SIG" >/dev/null 2>&1 || true
status_write error "scan_rc_$RC" "$DUE"
echo "SCHEDULER=FAIL"
echo "SCAN_RC=$RC"
exit "$RC"
