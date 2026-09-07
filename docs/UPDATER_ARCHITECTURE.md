# Smart Updater v1 architecture

Smart Updater v1 is implemented for code audit but is not deployed or production ready. It is disabled by default and has neither an installer nor a production signing key.

The source of truth is a versioned release feed, not a mutable Git branch:

1. fetch a small signed manifest with conditional ETag requests and persist verified pending metadata;
2. validate schema, channel, version, sequence and compatibility;
3. verify the canonical signed object with a pinned Ed25519 public key;
4. enforce package-size and staging-space limits before downloading a content-addressed package;
5. verify package size, SHA-256 and every payload entry;
6. wait for the safe window and update barrier;
7. create a hash-verified targeted backup and persistent transaction journal;
8. write temporary sibling files and atomically rename each target;
9. run the selected component-aware health profile;
10. atomically replace the complete committed metadata snapshot or deterministically roll back files and metadata.

HTTP 304 means only that the feed is unchanged. The watcher still evaluates persistent pending state against the priority deadline, quiet window, per-priority automatic policy and hard safety gates. Verified pending artifacts are retained while deferred and removed after commit.

## Ownership boundaries

Package targets are allow-listed program locations. The updater rejects device-local configuration, generated hints, runtime state, logs, temporary data, backups and credentials. It does not use `git pull` or `git clone` in the installation tree.

## Barrier integration points

Before deployment, these mutating jobs must decline new work while `/tmp/vward-update-requested` or `/tmp/vward-update.lock` exists and must expose an active transaction marker while inside a critical section:

- adaptive-auto-maint and adaptive-housekeeping;
- agh-adaptive-live and adaptive-hints-update;
- vpn-domain-audit-chain and vpn-night-reconcile;
- wg-health-watch and wg-failopen-guard;
- crond-supervisor;
- wan-guardian.

The updater checks known legacy locks, but that is not a substitute for cooperative barrier support. Therefore `barrier_integration_ready` defaults to zero and unattended apply fails closed.

## Deployment gates

- review and publish a real Ed25519 public key with an offline signing procedure;
- confirm OpenSSL Ed25519 support and shell utility behavior on the target Entware build;
- integrate the barrier into current jobs without changing their routing behavior;
- define exact affected-service restart order and bounded health probes;
- validate backup pruning, permissions and ownership on a non-production router;
- provide a separate installer and A/B updater-slot activation procedure.

Until all gates pass, the code is for audit and filesystem simulation only.
