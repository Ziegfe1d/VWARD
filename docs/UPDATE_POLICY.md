# Smart Updater v1 policy

Smart Updater v1 is implementation-stage code and is not deployed. It is disabled by default.

Priorities:

- **CRITICAL**: first hard-safe point; time window may be bypassed, but signature, compatibility, space, activity and barrier checks are mandatory.
- **IMPORTANT**: first safe window; after the configurable default two-hour delay, first hard-safe point outside the preferred clock window is allowed.
- **ROUTINE**: prefers the quiet window; after the configurable default 24-hour delay, first hard-safe point is allowed.

`auto_apply` is the master switch. `auto_critical`, `auto_important` and `auto_routine` independently control unattended application. All default to zero.

A verified deferred update remains pending across watcher cycles and reboot. HTTP 304 with no pending update is a normal no-update state. Exact already-installed manifests received with HTTP 200 are also treated as no-update.

## Trust and replay policy

Installed state and trust state are separate:

- `committed.state` = what is installed;
- `trust.state` = highest signed sequence already accepted.

The highest trusted sequence never decreases on rollback. A lower sequence is rejected. Reuse of the exact same highest sequence is allowed only when both update ID and canonical signed-manifest hash match. Same sequence with changed signed content is rejected.

An update that fails install or health-check and is rolled back successfully is persisted in `quarantine.state`; unattended watcher runs do not retry that exact update. A newer sequence may proceed.
