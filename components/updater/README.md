# VWARD Smart Updater v1

Smart Updater v1 uses signed automatic installation after live-router rollback
and updater-owned service-quiescing acceptance passed.

The updater uses a signed feed manifest, a versioned tar.gz package, exact VWARD target ownership, targeted hash-verified backups, transaction journaling, per-file sibling replacement, health checks and deterministic rollback.

## Component-aware selective updates

- `affected_components` in the signed feed and `component` in every package file are normalized through the bundled component registry.
- Every target must belong to that exact component; unknown components, duplicate targets/sources, undeclared payload files and component-set mismatches fail before the runtime barrier.
- Legacy component IDs remain accepted as aliases, while installed state is always written with canonical IDs.
- Only declared files participate in backup, replacement and rollback. Byte- and mode-identical files are not rewritten.
- `/opt/var/lib/vward/updater/components.json` records the release, update, sequence, health result and installed hashes for components changed by successful transactions. Rollback restores this state atomically.
- `update-engine` remains isolated behind the accepted slot installer; a regular signed package cannot overwrite the updater that is executing it.

## Lifecycle safety

- `committed.state` records the actually installed version/update.
- `trust.state` records the highest signed sequence ever accepted. Rollback never lowers it.
- `quarantine.state` blocks unattended retry of an update that failed install/health and was rolled back successfully.
- `pending/` survives watcher cycles and 304 responses until the update is applied, superseded or quarantined.
- stale updater process locks and stale request/barrier markers are recovered only when ownership can be proven dead; malformed/foreign ownership fails closed.

## Scheduling

`CRITICAL` uses the first hard-safe point. `IMPORTANT` prefers the safe window and escalates after its configurable deadline. `ROUTINE` prefers the quiet window and escalates after its longer configurable deadline. Hard safety, signature, integrity, space and barrier checks are never bypassed.

## Commands

- `vward-update.sh --status`
- `vward-update.sh --status-components`
- `vward-update.sh --check`
- `vward-update.sh --dry-run`
- `vward-update.sh --apply`
- `vward-update.sh --apply-pending`
- `vward-update.sh --rollback`
- `vward-update.sh --recover`

Automatic apply requires `auto_apply=1`, the matching per-priority flag, and
`barrier_integration_ready=1`. The updater-owned runtime quiescing path stops
the cron supervisor, cron and Adaptive Live, drains active jobs, and restores
only services that were running before the transaction. The production policy
enables these switches after the live-router acceptance completed successfully.

The bootstrap installer pins the production Ed25519 public key, installs the
updater in slot A, preserves any previous installation, and schedules signed
feed checks. The private signing key is never stored in this repository or on
the router.
