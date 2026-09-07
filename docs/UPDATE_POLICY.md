# Smart Updater v1 policy

Smart Updater v1 is implementation-stage code and is not deployed. It is disabled by default.

The feed assigns one of three priorities:

- ROUTINE: apply only inside the configured safe window and only when all safety gates pass.
- IMPORTANT: apply inside the safe window; operators may invoke a manual apply, but safety gates still apply.
- CRITICAL: may bypass the time window, but never signature, compatibility, free-space, activity or barrier checks.

The updater accepts only a higher semantic version and a strictly increasing signed sequence for the configured channel. This blocks downgrade and replay. A check or dry run may download and validate artifacts but cannot modify installed program files.

Local configuration, generated lists, runtime state, logs and backups are never package targets. Automatic apply remains unavailable until current VWARD mutating processes participate in the barrier protocol.
