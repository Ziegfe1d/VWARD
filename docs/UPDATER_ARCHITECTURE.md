# VWARD Smart Updater architecture

The production router must never `git pull` into live `/opt`. GitHub is canonical source; the router is an installed working copy.

Smart Updater uses a small signed feed plus a versioned package:

`feed check -> signature/policy/trust -> pending scheduler -> bounded download -> staging -> package/payload verification -> preflight -> barrier handshake -> targeted backup -> sibling atomic replacements -> health -> atomic commit or rollback`.

## Scheduler

CRITICAL, IMPORTANT and ROUTINE share hard safety gates but differ in when they become eligible. Deferred updates remain pending and are reconsidered on later watcher cycles even when the HTTP feed returns 304.

## Lifecycle safety

The updater separates installed state, monotonic trust state, transaction journal, pending cache and failed-update quarantine. This prevents rollback from reopening replay windows and prevents a bad unattended release from entering a rapid install/rollback loop.

## Resource safety

The manifest signs compressed and unpacked package sizes. Transport is byte-bounded; staging preflight accounts for compressed + unpacked bytes; backup space is cumulative; target temporary-replacement space is accumulated per target filesystem.

## Ownership

Install targets are an exact list of VWARD runtime files from `docs/INSTALLATION_MAP.md` plus the planned `/opt/share/vward/VERSION` bootstrap file. Local config, generated lists, runtime state, logs and backups are never package targets.

## Deployment status

This branch remains implementation-stage. Existing VWARD mutating jobs are not yet barrier-integrated, service restart orchestration/installer/signing-key provisioning still require separate work, and validation on a non-production Keenetic/Entware device is required before any live deployment.
