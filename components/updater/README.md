# VWARD Smart Updater v1

Smart Updater v1 includes a check-only production bootstrap. Automatic
installation remains disabled until live-router rollback and service-quiescing
acceptance has passed.

The updater uses a signed feed manifest, a versioned tar.gz package, exact VWARD target ownership, targeted hash-verified backups, transaction journaling, per-file sibling replacement, health checks and deterministic rollback.

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
- `vward-update.sh --check`
- `vward-update.sh --dry-run`
- `vward-update.sh --apply`
- `vward-update.sh --apply-pending`
- `vward-update.sh --rollback`
- `vward-update.sh --recover`

Automatic apply requires `auto_apply=1`, the matching per-priority flag, and `barrier_integration_ready=1`. The latter must remain zero until existing VWARD mutating jobs implement the shared barrier protocol.

The bootstrap installer pins the production Ed25519 public key, installs the
updater in slot A, preserves any previous installation, and schedules signed
feed checks. The private signing key is never stored in this repository or on
the router.
