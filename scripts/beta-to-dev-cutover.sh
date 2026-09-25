#!/bin/sh
# One-time transition of a router running VWARD beta (branch `beta`, old
# script names like agh-adaptive-live.sh) to the VWARD 0.2 canonical layout
# (branch `dev`, vward-*.sh names) that the signed dev package installs.
#
# This script does NOT install VWARD 0.2 itself. It only clears the runway:
# it stops and retires beta's cron/init surface so the two lines cannot run
# side by side, and backs up everything it touches. Installing the signed
# dev package is a separate, already-tested step
# (components/update-engine/vward-update.sh --apply, driven by the normal
# feed poll once the router's update.conf points at the dev feed).
#
#   beta-to-dev-cutover.sh --check                 read-only report (default)
#   beta-to-dev-cutover.sh --apply                 perform the cutover
#   beta-to-dev-cutover.sh --list-backups           list saved snapshots
#   beta-to-dev-cutover.sh --rollback TIMESTAMP     undo one cutover
#
# Run as root on the router itself.

set -u

PATH=/opt/bin:/opt/sbin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

NDMC=${VWARD_NDMC:-ndmc}
CRONTAB_BIN=${VWARD_CRONTAB:-crontab}
CRONTAB_DIR=${VWARD_CRONTAB_DIR:-/opt/var/spool/cron/crontabs}
# BusyBox's crontab applet defaults to /var/spool/cron/crontabs at compile
# time; -c makes the Entware directory explicit regardless of that default.
crontab_cmd() { "$CRONTAB_BIN" -c "$CRONTAB_DIR" "$@"; }

UPDATER_STATE=/opt/var/lib/vward/updater
CUTOVER_STATE=/opt/var/lib/vward/cutover
DONE_MARK="$CUTOVER_STATE/done"
BACKUP_ROOT=/opt/var/backups/vward/cutover
LOG=/opt/var/log/vward/cutover.log

fail() { echo "FAIL: $*" >&2; exit 1; }
info() { echo "$*"; }
log_line() { mkdir -p "$(dirname "$LOG")" 2>/dev/null; printf '%s|%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG" 2>/dev/null || :; }

# ------------------------------------------------------------
# Beta's on-router footprint (docs/INSTALLATION_MAP.md on branch beta).
# ------------------------------------------------------------

# Cron lines that must be gone before this router is safe for dev: matched
# by the script path each line invokes, exactly as beta's own
# config/cron/root.crontab spells them.
BETA_CRON_MARKERS='
/opt/bin/adaptive-auto-maint.sh
/opt/etc/init.d/S91adaptive-live
/opt/bin/vpn-domain-audit-chain.sh
/opt/bin/adaptive-hints-update.sh
/opt/bin/wg-health-watch.sh
/opt/etc/init.d/S92crond-supervisor
/opt/bin/wan-guardian.sh
/opt/bin/adaptive-housekeeping.sh
'

# dev's crontab, embedded so this single file works when copied to the
# router on its own. Must equal config/cron/root.crontab byte for byte;
# tests/repository/check-cutover-cron-parity.py enforces that in CI.
DEV_CRONTAB='*/5 * * * * /opt/bin/vward-route-reconciler.sh > /tmp/vward-route-reconciler-maint.cron.out 2>&1; RC=$?; date > /tmp/vward-route-reconciler-maint.cron.last; echo $RC > /tmp/vward-route-reconciler-maint.cron.rc; if [ $RC -eq 0 ]; then date > /tmp/vward-route-reconciler-maint.cron.ok; else date > /tmp/vward-route-reconciler-maint.cron.fail; fi
* * * * * /opt/etc/init.d/S91vward-route-engine start >/tmp/vward-route-engine-watchdog.cron.out 2>&1; RC=$?; date > /tmp/vward-route-engine-watchdog.cron.last; echo $RC > /tmp/vward-route-engine-watchdog.cron.rc; if [ $RC -eq 0 ]; then date > /tmp/vward-route-engine-watchdog.cron.ok; else date > /tmp/vward-route-engine-watchdog.cron.fail; fi
10 0 * * * /opt/bin/vward-policy-chain.sh > /tmp/vward-policy-chain.cron.out 2>&1 && /opt/bin/vward-policy-reconcile.sh > /tmp/vward-policy-reconcile.cron.out 2>&1; RC=$?; date > /tmp/vward-policy-chain.cron.last; echo $RC > /tmp/vward-policy-chain.cron.rc; if [ $RC -eq 0 ]; then date > /tmp/vward-policy-chain.cron.ok; else date > /tmp/vward-policy-chain.cron.fail; fi
25 4 * * * /opt/bin/vward-route-hints-update.sh > /tmp/vward-route-hints-update.cron.out 2>&1; RC=$?; date > /tmp/vward-route-hints-update.cron.last; echo $RC > /tmp/vward-route-hints-update.cron.rc; if [ $RC -eq 0 ]; then date > /tmp/vward-route-hints-update.cron.ok; else date > /tmp/vward-route-hints-update.cron.fail; fi
* * * * * /opt/bin/vward-tunnel-health.sh > /tmp/vward-tunnel-health-watch.cron.out 2>&1 && /opt/bin/vward-tunnel-guard.sh > /tmp/vward-tunnel-guard-guard.cron.out 2>&1; RC=$?; date > /tmp/vward-tunnel-health-chain.cron.last; echo $RC > /tmp/vward-tunnel-health-chain.cron.rc; if [ $RC -eq 0 ]; then date > /tmp/vward-tunnel-health-chain.cron.ok; else date > /tmp/vward-tunnel-health-chain.cron.fail; fi
* * * * * /opt/etc/init.d/S92vward-runtime start > /tmp/vward-cron-supervisor-watch.cron.out 2>&1; RC=$?; date > /tmp/vward-cron-supervisor-watch.cron.last; echo $RC > /tmp/vward-cron-supervisor-watch.cron.rc; if [ $RC -eq 0 ]; then date > /tmp/vward-cron-supervisor-watch.cron.ok; else date > /tmp/vward-cron-supervisor-watch.cron.fail; fi
* * * * * /opt/bin/vward-wan-guard.sh > /tmp/vward-wan-guard.cron.out 2>&1; RC=$?; date > /tmp/vward-wan-guard.cron.last; echo $RC > /tmp/vward-wan-guard.cron.rc
17 * * * * /opt/bin/vward-housekeeping.sh > /tmp/vward-housekeeping.cron.out 2>&1; RC=$?; date > /tmp/vward-housekeeping.cron.last; echo $RC > /tmp/vward-housekeeping.cron.rc; if [ $RC -eq 0 ]; then date > /tmp/vward-housekeeping.cron.ok; else date > /tmp/vward-housekeeping.cron.fail; fi
* * * * * /opt/bin/vward-ads-privacy-scheduler.sh > /tmp/vward-ads-scheduler.cron.out 2>&1; RC=$?; date > /tmp/vward-ads-scheduler.cron.last; echo $RC > /tmp/vward-ads-scheduler.cron.rc; if [ $RC -eq 0 ]; then date > /tmp/vward-ads-scheduler.cron.ok; else date > /tmp/vward-ads-scheduler.cron.fail; fi
*/5 * * * * /opt/bin/vward-wifi-client-scheduler.sh > /tmp/vward-wifi-client-guard.cron.out 2>&1; RC=$?; date > /tmp/vward-wifi-client-guard.cron.last; echo $RC > /tmp/vward-wifi-client-guard.cron.rc; if [ $RC -eq 0 ]; then date > /tmp/vward-wifi-client-guard.cron.ok; else date > /tmp/vward-wifi-client-guard.cron.fail; fi'

# Init scripts beta owns that dev replaces with differently-named ones and
# that must not run again after cutover. S90crond is untouched: both lines
# ship it and it is not VWARD-specific.
BETA_INIT_SCRIPTS='S91adaptive-live S92crond-supervisor S93keenetic-apps'

# Best-effort archive+remove list: everything else beta leaves on the
# router. Not required for correctness (nothing here can start on its own
# once the cron lines and init scripts above are gone); kept only so the
# router is not left with a confusing leftover footprint. A missing entry
# is skipped without failing the cutover.
BETA_LEGACY_PATHS='
/opt/bin/adaptive-2ip-test.sh
/opt/bin/adaptive-auto-maint.sh
/opt/bin/adaptive-hints-update.sh
/opt/bin/adaptive-housekeeping.sh
/opt/bin/adaptive-resolve4.sh
/opt/bin/adaptive-route.sh
/opt/bin/agh-adaptive-live.sh
/opt/bin/agh-adaptive-route.sh
/opt/bin/vpn-domain-audit-chain.sh
/opt/bin/vpn-domain-audit.sh
/opt/bin/vpn-night-reconcile.sh
/opt/bin/vpn-subnet-sync.sh
/opt/bin/wg-failopen-guard.sh
/opt/bin/wg-health-watch.sh
/opt/bin/wan-guardian.sh
/opt/bin/wan-recovery-actuator.sh
/opt/bin/crond-supervisor.sh
/opt/etc/keenetic-apps
/opt/share/keenetic-apps
/opt/etc/adaptive-route
/opt/var/lib/adaptive-live
/opt/var/lib/adaptive-discovery
/opt/var/lib/adaptive-hints
/opt/var/lib/adaptive-maint
/opt/var/lib/adaptive-route
/opt/var/lib/vpn-audit
/opt/var/lib/vpn-subnets
/opt/var/lib/wg-failopen
/opt/var/lib/wg-health
/opt/var/backups/adaptive-maint
/opt/var/backups/vpn-reconcile
/opt/var/log/adaptive-discovery.log
/opt/var/log/adaptive-hints-update.log
/opt/var/log/adaptive-housekeeping.log
/opt/var/log/adaptive-live-events.log
/opt/var/log/adaptive-route.log
/opt/var/log/agh-adaptive-live.log
/opt/var/log/crond-supervisor.log
/opt/var/log/vpn-audit-chain.log
/opt/var/log/vpn-audit-summary.log
/opt/var/log/vpn-audit.log
/opt/var/log/vpn-night-reconcile.log
/opt/var/log/vpn-subnet-sync.log
/opt/var/log/wan-guardian-recovery.log
/opt/var/log/wan-guardian.log
/opt/var/log/wg-failopen.log
/opt/var/log/wg-health.log
/opt/var/run/agh-adaptive-live.pid
/opt/var/run/crond-supervisor.pid
/opt/var/run/keenetic-apps-lighttpd.pid
'

# ------------------------------------------------------------
# Preflight
# ------------------------------------------------------------

need_root() {
    [ "$(id -u)" = 0 ] || fail "must run as root"
}

legacy_present() {
    [ -r /opt/etc/init.d/S91adaptive-live ] &&
        grep -q 'SCRIPT="/opt/bin/agh-adaptive-live.sh"' /opt/etc/init.d/S91adaptive-live 2>/dev/null
}

dev_present() {
    [ -e /opt/etc/init.d/S91vward-route-engine ]
}

updater_busy() {
    [ -r "$UPDATER_STATE/journal.state" ] || return 1
    phase=$(sed -n 's/^phase=//p' "$UPDATER_STATE/journal.state" | tail -n 1)
    case "$phase" in ''|IDLE|COMMITTED|ROLLED_BACK) return 1 ;; *) return 0 ;; esac
}

# ------------------------------------------------------------
# Reporting
# ------------------------------------------------------------

cmd_check() {
    echo "legacy (beta) footprint present : $(legacy_present && echo yes || echo no)"
    echo "dev (0.2) footprint present     : $(dev_present && echo yes || echo no)"
    echo "updater mid-transaction         : $(updater_busy && echo yes || echo no)"
    echo "cutover already applied         : $([ -r "$DONE_MARK" ] && echo yes || echo no)"
    if [ -r /opt/share/vward/VERSION ]; then
        echo "installed VERSION               : $(sed -n 1p /opt/share/vward/VERSION)"
    fi
    if legacy_present && ! dev_present && ! updater_busy && [ ! -r "$DONE_MARK" ]; then
        echo "ready for --apply                : yes"
    else
        echo "ready for --apply                : no"
    fi
}

cmd_list_backups() {
    [ -d "$BACKUP_ROOT" ] || { echo "no backups yet"; return 0; }
    ls -1 "$BACKUP_ROOT" 2>/dev/null
}

# ------------------------------------------------------------
# Apply
# ------------------------------------------------------------

backup_snapshot() {
    stamp=$(date '+%Y%m%d-%H%M%S')
    bk="$BACKUP_ROOT/$stamp"
    mkdir -p "$bk" || fail "cannot create backup directory"

    crontab_cmd -l > "$bk/root.crontab" 2>/dev/null || : > "$bk/root.crontab"
    "$NDMC" -c "show running-config" > "$bk/running-config.txt" 2>/dev/null || : > "$bk/running-config.txt"

    archive_list="$bk/legacy-files.txt"
    : > "$archive_list"
    for p in $BETA_LEGACY_PATHS; do
        [ -e "$p" ] && echo "$p" >> "$archive_list"
    done
    for s in $BETA_INIT_SCRIPTS; do
        [ -e "/opt/etc/init.d/$s" ] && echo "/opt/etc/init.d/$s" >> "$archive_list"
    done

    if [ -s "$archive_list" ]; then
        # BusyBox tar has no -T/--files-from: pass the paths directly.
        set --
        while IFS= read -r p; do
            [ -n "$p" ] || continue
            set -- "$@" "${p#/}"
        done < "$archive_list"
        tar -czf "$bk/legacy.tar.gz" -C / "$@" 2>>"$LOG" ||
            fail "backup archive failed, nothing was changed"
        tar -tzf "$bk/legacy.tar.gz" >/dev/null 2>&1 || fail "backup archive is unreadable, nothing was changed"
    fi

    {
        echo "stamp=$stamp"
        echo "installed_version=$(sed -n 1p /opt/share/vward/VERSION 2>/dev/null)"
        echo "archived_paths=$(wc -l < "$archive_list" | tr -d ' ')"
    } > "$bk/manifest.txt"

    printf '%s\n' "$stamp"
}

remove_cron_lines() {
    tmp=/tmp/vward-cutover-crontab.$$
    crontab_cmd -l > "$tmp" 2>/dev/null || : > "$tmp"
    for marker in $BETA_CRON_MARKERS; do
        # grep -v exits 1 once every remaining line has been filtered out;
        # that is a normal outcome here, not a failure, so the write must
        # not be skipped on it.
        grep -vF "$marker" "$tmp" > "$tmp.next"
        mv "$tmp.next" "$tmp" || fail "cannot update the working crontab copy"
    done
    crontab_cmd "$tmp" || fail "cannot update crontab (removing beta lines)"
    rm -f "$tmp"
}

add_dev_cron_lines() {
    tmp=/tmp/vward-cutover-crontab.$$
    crontab_cmd -l > "$tmp" 2>/dev/null || : > "$tmp"
    printf '%s\n' "$DEV_CRONTAB" | while IFS= read -r line; do
        [ -n "$line" ] || continue
        marker=$(printf '%s\n' "$line" | grep -oE '/opt/(bin|etc/init\.d)/[A-Za-z0-9_.-]+' | head -n 1)
        [ -n "$marker" ] || continue
        grep -qF "$marker" "$tmp" || printf '%s\n' "$line" >> "$tmp"
    done
    crontab_cmd "$tmp" || fail "cannot update crontab (adding dev lines)"
    rm -f "$tmp"
}

stop_legacy_daemons() {
    # The watchdog first, so it cannot restart what we are about to stop.
    [ -x /opt/etc/init.d/S92crond-supervisor ] && /opt/etc/init.d/S92crond-supervisor stop >>"$LOG" 2>&1
    [ -x /opt/etc/init.d/S91adaptive-live ] && /opt/etc/init.d/S91adaptive-live stop >>"$LOG" 2>&1
    [ -x /opt/etc/init.d/S93keenetic-apps ] && /opt/etc/init.d/S93keenetic-apps stop >>"$LOG" 2>&1
    return 0
}

retire_init_scripts() {
    for s in $BETA_INIT_SCRIPTS; do
        f="/opt/etc/init.d/$s"
        [ -e "$f" ] || continue
        rm -f "$f" || fail "cannot remove $f"
    done
}

cleanup_legacy_files() {
    for p in $BETA_LEGACY_PATHS; do
        [ -e "$p" ] || continue
        rm -rf "${p:?}" 2>>"$LOG" || log_line "WARN|could not remove $p, left in place"
    done
}

cmd_apply() {
    need_root
    legacy_present || fail "no beta footprint found (nothing to cut over)"
    dev_present && fail "a dev (0.2) init script already exists; this router is not a clean beta cutover target"
    updater_busy && fail "Update Engine has a transaction in progress; resolve it first"
    [ -r "$DONE_MARK" ] && fail "cutover already applied ($(cat "$DONE_MARK" 2>/dev/null)); remove $DONE_MARK to re-run"

    mkdir -p "$CUTOVER_STATE" "$BACKUP_ROOT" "$(dirname "$LOG")" || fail "cannot create state directories"

    info "Backing up crontab, running-config and the beta footprint..."
    stamp=$(backup_snapshot) || exit 1
    info "Backup: $BACKUP_ROOT/$stamp"
    log_line "BACKUP|$stamp"

    info "Stopping beta services..."
    stop_legacy_daemons
    log_line "STOPPED|S91 S92 S93"

    info "Updating crontab..."
    remove_cron_lines
    add_dev_cron_lines
    log_line "CRON|updated"

    info "Retiring beta init scripts..."
    retire_init_scripts
    log_line "INIT|retired"

    info "Archiving remaining beta files..."
    cleanup_legacy_files
    log_line "CLEANUP|done"

    printf 'stamp=%s\n' "$stamp" > "$DONE_MARK"

    info ""
    info "Cutover complete. Backup: $BACKUP_ROOT/$stamp"
    info "Next steps (not done by this script):"
    info "  1. Point /opt/etc/vward/update.conf at the dev feed and switch the channel."
    info "  2. Let or trigger the signed 0.2 package apply: vward-update.sh --apply."
    info "  3. Verify: ps w | grep vward-route-engine; Console reachable; DNS/WAN/VPN working."
    info "  4. Only if something is wrong: $0 --rollback $stamp"
}

# ------------------------------------------------------------
# Rollback
# ------------------------------------------------------------

cmd_rollback() {
    need_root
    stamp=${1:-}
    [ -n "$stamp" ] || fail "usage: $0 --rollback TIMESTAMP (see --list-backups)"
    bk="$BACKUP_ROOT/$stamp"
    [ -d "$bk" ] || fail "no backup at $bk"
    mkdir -p "$(dirname "$LOG")" 2>/dev/null

    if dev_present; then
        fail "a dev (0.2) init script is present; run vward-update-rollback.sh first, then retry this rollback"
    fi

    info "Restoring crontab from $bk/root.crontab..."
    crontab_cmd "$bk/root.crontab" || fail "cannot restore crontab"

    if [ -r "$bk/legacy.tar.gz" ]; then
        info "Restoring beta files from $bk/legacy.tar.gz..."
        tar -xzf "$bk/legacy.tar.gz" -C / || fail "cannot restore beta files"
    fi

    info "Starting beta services..."
    [ -x /opt/etc/init.d/S90crond ] && /opt/etc/init.d/S90crond start >>"$LOG" 2>&1
    [ -x /opt/etc/init.d/S91adaptive-live ] && /opt/etc/init.d/S91adaptive-live start >>"$LOG" 2>&1
    [ -x /opt/etc/init.d/S92crond-supervisor ] && /opt/etc/init.d/S92crond-supervisor start >>"$LOG" 2>&1
    [ -x /opt/etc/init.d/S93keenetic-apps ] && /opt/etc/init.d/S93keenetic-apps start >>"$LOG" 2>&1

    rm -f "$DONE_MARK"
    log_line "ROLLBACK|$stamp"
    info "Rollback complete."
}

# ------------------------------------------------------------
# Entry point
# ------------------------------------------------------------

case "${1:---check}" in
    --check) cmd_check ;;
    --apply) cmd_apply ;;
    --list-backups) cmd_list_backups ;;
    --rollback) cmd_rollback "${2:-}" ;;
    *) fail "usage: $0 --check|--apply|--list-backups|--rollback TIMESTAMP" ;;
esac
