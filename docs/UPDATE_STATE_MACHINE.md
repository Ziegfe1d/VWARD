# Smart Updater v1 state machine

The full protocol vocabulary is IDLE, CHECKING, AVAILABLE, WAITING_WINDOW, PREPARING, DOWNLOADING, VERIFYING, STAGED, BACKING_UP, INSTALLING, HEALTHCHECK, COMMITTING, COMMITTED, ROLLING_BACK, ROLLED_BACK, FAILED and RECOVERY_REQUIRED. The current implementation persists the transaction-relevant subset using atomic rename:

IDLE -> CHECKING -> VERIFIED -> AVAILABLE -> WAITING_WINDOW -> BACKING_UP -> INSTALLING -> VERIFYING -> COMMIT_PREPARED -> COMMITTED

PREPARING, DOWNLOADING and STAGED are transient in v1. AVAILABLE and WAITING_WINDOW are persistent because a deferred manifest must survive HTTP 304 and reboot. An install or health failure enters ROLLING_BACK and finishes at ROLLED_BACK. Startup recovery treats INSTALLING, VERIFYING, ROLLING_BACK and RECOVERY_REQUIRED as incomplete transactions and invokes rollback from the recorded backup.

State is split into three ownership domains. `pending/` stores the verified manifest, optional verified package, first-seen time and priority. `journal.state` records phase, candidate metadata, previous version and active backup. `committed.state` atomically stores installed version, installed update ID, highest accepted sequence, manifest hash and last successful health-check.

COMMIT_PREPARED is the decision boundary. Before the complete committed snapshot is atomically renamed, recovery restores old files and the backed-up committed snapshot. After that rename, recovery recognizes the matching candidate update ID and finalizes COMMITTED. Individual installed-version or sequence writes do not exist, preventing old files from being paired with partially new anti-replay metadata.

One tokenized mkdir-based process lock prevents concurrent apply, rollback and recovery. A live matching PID blocks; a dead or unrelated PID is recovered after owner recheck; malformed metadata fails conservatively. Internal rollback must present the exact active lock token and matching barrier PID, so an environment flag alone cannot bypass locking. The request marker and critical barrier live at `/tmp/vward-update-requested` and `/tmp/vward-update.lock`. Existing VWARD jobs do not yet cooperate with them, so production automatic apply is fail-closed behind barrier_integration_ready=0.
