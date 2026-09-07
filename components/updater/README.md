# VWARD Smart Updater v1

This directory contains an implementation-stage updater. It is not deployed and is disabled by default.

The updater persists a verified pending manifest, downloads a content-addressed tar package only after scheduling and staging-space preflight, creates a hash-verified targeted backup, replaces only allow-listed program files, runs a health profile and rolls back on failure. It never installs configuration, state, logs or backups.

## Commands

- vward-update.sh --status
- vward-update.sh --check
- vward-update.sh --dry-run
- vward-update.sh --apply
- vward-update.sh --rollback
- vward-update.sh --recover
- vward-update-watch.sh --once

Exit codes are grouped by outcome: 0 success, 10 no update, 20 deferred, 30-33 validation/safety failures, and 40-42 install/health/rollback failures.

## Production gate

Automatic apply requires the `auto_apply` master switch, the matching `auto_critical`, `auto_important` or `auto_routine` switch, and `barrier_integration_ready=1`. All default to zero. The barrier flag must remain zero until existing mutating VWARD jobs honor the shared update barrier. The repository currently provides no installer for this subsystem and no production signing key.

Committed anti-replay metadata is stored as one atomic snapshot. Transaction journal and pending feed state are separate, so recovery can choose deterministically between finalizing the new commit and restoring both old files and old metadata. Standalone rollback/recovery acquire the same stale-aware lock and barrier as apply; an internally triggered rollback reuses ownership to avoid deadlock.

Configuration examples and the JSON Schema live under `config/updater/`. See the updater documents under `docs/` for policy, state transitions, recovery and signing details.
