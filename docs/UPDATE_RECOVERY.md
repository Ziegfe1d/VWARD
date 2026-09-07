# Smart Updater v1 recovery

Before replacement, the updater copies only affected existing program files and records target, existence, mode, original SHA-256 and backup SHA-256. It also saves the previous complete committed-state snapshot. All backup payloads are validated before rollback touches any installed file; every restored hash and mode is checked afterward.

Staging may be on another filesystem because staged files are never renamed directly into place. The final temporary sibling is copied completely, assigned its declared mode and renamed beside its target. A multi-file package is a journaled transaction, not one filesystem-atomic operation.

If installation or health verification fails, internal rollback reuses the apply lock and barrier without reacquiring them. Standalone rollback and recovery acquire both before touching installed files. The --recover command rolls back an incomplete transaction or finalizes a COMMIT_PREPARED transaction whose atomic committed snapshot already matches the candidate.

Backups live under /opt/var/backups/vward and state under /opt/var/lib/vward/updater. Neither is part of a release package. Backup pruning and service restart orchestration are designed but intentionally not active until component ownership and restart order are validated on a non-production router.

Updater self-replacement uses the stable vward-update-bootstrap.sh launcher and a current slot symlink. Slot creation and switching are not enabled by the current package installer; they require a separately verified updater health profile.
