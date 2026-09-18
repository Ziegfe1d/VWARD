#!/bin/sh

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
LIB="${VWARD_ADS_LIB:-/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh}"
[ -r "$LIB" ] || LIB="$SELF_DIR/../lib/vward-ads-privacy-common.sh"
[ -r "$LIB" ] || { echo "FAIL: common library not found" >&2; exit 1; }
. "$LIB"

MODE="${1:-dry-run}"
CONFIRM="${2:-}"
case "$MODE" in dry-run|apply) ;; *) echo "Usage: $0 {dry-run|apply [--confirm]}" >&2; exit 2 ;; esac

ads_mkdirs || ads_die "cannot create component directories"
ads_require "$ADS_JQ"
ads_require "$ADS_CURL"
ads_load_config

RULES="$ADS_STATE/generated/vward-ads-privacy-guard.rules"
[ -r "$RULES" ] || ads_die "generated rules not found: $RULES"

PUBLISH_MODE="${PUBLISH_MODE:-staged}"
AUTO_PUBLISH="${AUTO_PUBLISH:-0}"
case "$PUBLISH_MODE" in staged|user_rules_api) ;; *) ads_die "unsupported publish mode in v5: $PUBLISH_MODE" ;; esac

RULE_COUNT="$(awk 'NF && $0 !~ /^[!#]/ {n++} END{print n+0}' "$RULES")"
echo "PUBLISH_MODE=$PUBLISH_MODE"
echo "RULE_COUNT=$RULE_COUNT"

if [ "$PUBLISH_MODE" = staged ]; then
    echo "PUBLISH_STATUS=STAGED_ONLY"
    exit 0
fi

WORK="$ADS_STATE/work/publish.$$"
LOCK="$ADS_STATE/publish.lock"
mkdir -p "$WORK" || ads_die "cannot create publish work directory"
if ! ads_lock_acquire "$LOCK" "${PUBLISH_LOCK_STALE_SEC:-300}"; then
    rm -rf "$WORK"
    echo "PUBLISH_STATUS=ALREADY_RUNNING"
    exit 0
fi
cleanup(){ rm -rf "$WORK"; ads_lock_release "$LOCK"; }
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

STATUS_JSON="$WORK/filtering-status.json"
ads_agh_api_get "filtering/status" "$STATUS_JSON" || ads_die "AdGuard Home filtering/status API unavailable"
"$ADS_JQ" -e '.user_rules | type=="array"' "$STATUS_JSON" >/dev/null 2>&1 || ads_die "AdGuard Home filtering/status missing user_rules"

"$ADS_JQ" -r '.user_rules[]' "$STATUS_JSON" > "$WORK/user-rules.before"
cp "$WORK/user-rules.before" "$WORK/user-rules.base"

# Remove only the previous VWARD-owned marker block. Every unrelated/manual AGH
# rule is preserved byte-for-byte as a line in the ordered user_rules array.
awk '
  $0=="! VWARD ADS & PRIVACY GUARD BEGIN" {inside=1; next}
  $0=="! VWARD ADS & PRIVACY GUARD END" {inside=0; next}
  !inside {print}
' "$WORK/user-rules.before" > "$WORK/user-rules.unmanaged"

{
    cat "$WORK/user-rules.unmanaged"
    echo "! VWARD ADS & PRIVACY GUARD BEGIN"
    awk 'NF && $0 !~ /^[!#]/ {print}' "$RULES"
    echo "! VWARD ADS & PRIVACY GUARD END"
} > "$WORK/user-rules.after"

# set_rules is a wholesale replacement API; build the complete array only after
# preserving all non-VWARD entries. This is the ownership boundary.
"$ADS_JQ" -R -s '{rules:(split("\n") | map(select(length>0)))}' "$WORK/user-rules.after" > "$WORK/set-rules.json" || ads_die "cannot build set_rules payload"

if [ "$MODE" = dry-run ]; then
    echo "PUBLISH_STATUS=DRY_RUN_PASS"
    echo "PRESERVED_RULES=$(wc -l < "$WORK/user-rules.unmanaged" | tr -d ' ')"
    echo "CONFIG_CHANGED=NO"
    exit 0
fi

if [ "$CONFIRM" != "--confirm" ] && ! ads_bool "$AUTO_PUBLISH"; then
    ads_die "apply requires --confirm unless AUTO_PUBLISH=1"
fi

STAMP="$(date '+%Y%m%d-%H%M%S')"
BACKUP_DIR="$ADS_BACKUP_ROOT/publish-$STAMP"
mkdir -p "$BACKUP_DIR" || ads_die "cannot create backup directory"
chmod 0700 "$BACKUP_DIR" || ads_die "cannot protect backup directory"
cp "$WORK/user-rules.before" "$BACKUP_DIR/user-rules.before.txt" || ads_die "user rules backup failed"
cp "$RULES" "$BACKUP_DIR/vward-rules.txt" || ads_die "managed rules backup failed"
cp "$STATUS_JSON" "$BACKUP_DIR/filtering-status.before.json" || true
chmod 0600 "$BACKUP_DIR"/* 2>/dev/null || true
echo "BACKUP_DIR=$BACKUP_DIR"

ROLLBACK_JSON="$WORK/rollback.json"
"$ADS_JQ" -R -s '{rules:(split("\n") | map(select(length>0)))}' "$WORK/user-rules.before" > "$ROLLBACK_JSON" || ads_die "cannot build rollback payload"

rollback()
{
    echo "ROLLBACK=START"
    if ! ads_agh_api_post "filtering/set_rules" "$ROLLBACK_JSON" "$WORK/rollback.out" >/dev/null 2>&1; then
        echo "ROLLBACK=FAILED"
        return 1
    fi
    if ! ads_agh_api_get "filtering/status" "$WORK/rollback-status.json" >/dev/null 2>&1; then
        echo "ROLLBACK=FAILED"
        return 1
    fi
    if ! "$ADS_JQ" -e --slurpfile expected "$ROLLBACK_JSON" \
        '.user_rules == $expected[0].rules' "$WORK/rollback-status.json" >/dev/null 2>&1; then
        echo "ROLLBACK=FAILED"
        return 1
    fi
    echo "ROLLBACK=VERIFIED"
    return 0
}

# filtering/set_rules replaces the complete array. Abort rather than overwrite
# any manual or external change made since our initial snapshot.
PREAPPLY_JSON="$WORK/filtering-status.preapply.json"
ads_agh_api_get "filtering/status" "$PREAPPLY_JSON" || ads_die "cannot recheck AdGuard Home rules before publish"
"$ADS_JQ" -e --slurpfile before "$STATUS_JSON" \
    '.user_rules == $before[0].user_rules' "$PREAPPLY_JSON" >/dev/null 2>&1 || \
    ads_die "AdGuard Home user_rules changed during publish; retry required"

if ! ads_agh_api_post "filtering/set_rules" "$WORK/set-rules.json" "$WORK/set-rules.out"; then
    rollback || ads_die "AdGuard Home set_rules failed and rollback could not be verified"
    ads_die "AdGuard Home set_rules failed; previous user rules restored"
fi

VERIFY_JSON="$WORK/filtering-status.after.json"
if ! ads_agh_api_get "filtering/status" "$VERIFY_JSON"; then
    rollback || ads_die "publish verification failed and rollback could not be verified"
    ads_die "cannot verify AdGuard Home rules after publish; previous user rules restored"
fi

"$ADS_JQ" -e --slurpfile expected "$WORK/set-rules.json" '
  (.user_rules | type=="array") and
  (.user_rules | index("! VWARD ADS & PRIVACY GUARD BEGIN") != null) and
  (.user_rules | index("! VWARD ADS & PRIVACY GUARD END") != null) and
  (($expected[0].rules - .user_rules) | length == 0)
' "$VERIFY_JSON" >/dev/null 2>&1 || {
    rollback || ads_die "publish verification failed and rollback could not be verified"
    ads_die "verification failed; previous user rules restored"
}

ads_log "PUBLISH_OK|mode=user_rules_api|rules=$RULE_COUNT|backup=$BACKUP_DIR"
echo "PUBLISH_STATUS=PASS"
echo "OWNERSHIP=VWARD_MARKER_BLOCK_ONLY"
echo "ADGUARD_RESTART=NO"
exit 0
