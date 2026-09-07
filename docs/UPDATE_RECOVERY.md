# Smart Updater v1 recovery

Before replacement, only affected existing program files are backed up. Backup metadata records original path, mode and SHA-256; rollback verifies the backup index, committed metadata backup and every payload before restoration, then verifies restored hashes/modes.

Each replacement is written as a temporary sibling beside the destination, verified, chmodded, synced and renamed on the target filesystem. Multi-file installation is a journaled transaction, not one filesystem-atomic operation.

Power-loss recovery uses `journal.state` plus the verified backup. `INSTALLING`, `VERIFYING`, `ROLLING_BACK` and `RECOVERY_REQUIRED` recover through rollback. `COMMIT_PREPARED` either finalizes the already-written atomic committed snapshot or restores the old transaction.

A successful rollback after install/health failure quarantines that exact signed update so the watcher does not immediately reinstall it. Trust sequence state is intentionally not rolled back.

Stale `transaction.*` staging directories are removed only after the updater process lock is acquired; persistent pending cache is preserved. Stale request/barrier markers are removed only when their owner token is valid and the owner process is proven dead.

Backup pruning, service restart orchestration and A/B updater-slot activation remain deployment gates.
