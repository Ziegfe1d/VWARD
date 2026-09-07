# Smart Updater v1 policy

Smart Updater v1 is not production-deployed.

## Priorities

- **CRITICAL**: bypasses the preferred clock window and uses the first hard-safe point. Integrity, authenticity, compatibility, disk, barrier and rollback requirements are never bypassed.
- **IMPORTANT**: prefers the safe window; after the configurable default 2-hour deadline it may use the first hard-safe point outside that clock window.
- **ROUTINE**: prefers the quiet window; after the configurable default 24-hour delay it becomes eligible at the first hard-safe point.

`auto_apply` is the master unattended switch. `auto_critical`, `auto_important` and `auto_routine` independently control each class; all default to zero.

## Pending, idle and retry semantics

A verified deferred update remains pending across watcher cycles and reboot. HTTP 304 means only that the feed is unchanged: pending is re-evaluated, while 304 with no pending update is normal idle success. An exact already-installed signed update received via HTTP 200 is also a normal no-update condition.

Only transient transport/network failures use short bounded fast retries. Deferred/safety states, signature/hash failures, incompatibility/replay, quarantine, install/health failures and rollback failures do not spin in immediate retry loops.

## Trust and quarantine

`committed.state` records installed version/update/sequence. `trust.state` separately records the highest signed sequence ever accepted. Lower sequences are rejected even after rollback; an equal sequence is accepted only for the identical update ID and canonical signed-manifest hash.

When install or health-check fails and automatic rollback succeeds, that exact update is persisted in `quarantine.state`. The unattended watcher will not retry it. A higher signed sequence may proceed normally.
