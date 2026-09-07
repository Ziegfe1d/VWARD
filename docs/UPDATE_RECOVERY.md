# Smart Updater v1 recovery

Before replacement, the updater copies only affected existing program files and records whether each target previously existed and its mode. Each new file is written beside its destination and renamed atomically on the same filesystem.

Staging may be on another filesystem because staged files are never renamed directly into place. The final temporary sibling is copied completely, assigned its declared mode and renamed beside its target. A multi-file package is a journaled transaction, not one filesystem-atomic operation.

If installation or health verification fails, rollback restores the indexed files and removes targets that were newly introduced. The --recover command rolls back a transaction interrupted during installation, verification or rollback.

Backups live under /opt/var/backups/vward and state under /opt/var/lib/vward/updater. Neither is part of a release package. Backup pruning and service restart orchestration are designed but intentionally not active until component ownership and restart order are validated on a non-production router.

Updater self-replacement uses the stable vward-update-bootstrap.sh launcher and a current slot symlink. Slot creation and switching are not enabled by the current package installer; they require a separately verified updater health profile.
