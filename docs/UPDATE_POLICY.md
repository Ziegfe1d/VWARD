# Smart Updater v1 policy

Smart Updater v1 is implementation-stage code and is not deployed. It is disabled by default.

The feed assigns one of three priorities:

- ROUTINE: prefers the quiet window and becomes eligible at the first hard-safe point after the configurable 24-hour default maximum delay.
- IMPORTANT: uses the first safe window and becomes eligible at the first hard-safe point after the configurable two-hour default deadline.
- CRITICAL: may bypass the time window, but never signature, compatibility, free-space, activity or barrier checks.

`auto_apply` is the master unattended switch. `auto_critical`, `auto_important` and `auto_routine` independently enable each class. All four default to zero.

The updater accepts only a higher SemVer 2.0 version, including prerelease precedence, and a strictly increasing signed sequence for the configured channel. This blocks downgrade and replay. A verified deferred manifest, its first-seen time and priority remain pending across watcher cycles and reboot; HTTP 304 triggers reevaluation of that pending update. Dry-run validates a package using isolated runtime paths and cannot modify updater production state.

Local configuration, generated lists, runtime state, logs and backups are never package targets. Automatic apply remains unavailable until current VWARD mutating processes participate in the barrier protocol.
