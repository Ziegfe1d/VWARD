# VWARD Smart Updater v1

This directory contains an implementation-stage updater. It is not deployed and is disabled by default.

The updater downloads a signed JSON feed and a content-addressed tar package into local staging, validates both, creates a targeted backup, replaces only allow-listed program files, runs a health profile and rolls back on failure. It never installs configuration, state, logs or backups.

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

Automatic apply requires both auto_apply=1 and barrier_integration_ready=1. The latter must remain zero until the existing mutating VWARD jobs honor the shared update barrier. The repository currently provides no installer for this subsystem and no production signing key.

Configuration examples and the JSON Schema live under `config/updater/`. See the updater documents under `docs/` for policy, state transitions, recovery and signing details.
