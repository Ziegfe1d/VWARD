# VWARD Smart Updater v1

Smart Updater v1 is implementation-stage code. It is **not deployed** and remains disabled by default.

The updater consumes a signed manifest, persists verified pending updates, waits according to CRITICAL / IMPORTANT / ROUTINE policy, stages and verifies the package, creates a targeted hash-verified backup, enters the cooperative update barrier, replaces only exact VWARD-owned runtime paths, runs a bounded health check and rolls back on failure.

## Safety model

- Ed25519 authenticates the canonical `.signed` manifest; SHA-256 protects package/payload integrity.
- `trust.state` records the monotonic highest signed sequence ever accepted. Rollback never lowers it.
- `quarantine.state` suppresses unattended retries of an update that already failed install/health and was rolled back.
- `committed.state` describes what is installed; it is deliberately separate from trust state.
- HTTP 304 with no pending update is a normal idle condition.
- Only transport/network failures receive short fast retries. Deferred, invalid, incompatible, quarantined, install, health and rollback failures wait for the normal watcher cycle or operator action.
- Request/barrier markers and the updater process lock carry ownership tokens and have conservative stale-owner recovery.
- Apply uses a two-phase handshake: pre-check -> update-requested -> drain -> barrier -> post-barrier recheck -> backup/install.

## Package limits

The signed package declares both compressed `size` and `unpacked_size`. Local configuration separately caps manifest, package and unpacked sizes. Downloads are bounded during transfer and checked again afterward. Target free-space accounting is cumulative per filesystem.

## Production gate

Automatic apply also requires `barrier_integration_ready=1`. This must stay `0` until all mutating VWARD jobs honor the shared barrier protocol. No production signing key is stored in this repository, no installer is enabled, and no router deployment is performed by this branch.
