# Smart Updater v1 state machine

The full protocol vocabulary is IDLE, CHECKING, AVAILABLE, WAITING_WINDOW, PREPARING, DOWNLOADING, VERIFYING, STAGED, BACKING_UP, INSTALLING, HEALTHCHECK, COMMITTING, COMMITTED, ROLLING_BACK, ROLLED_BACK, FAILED and RECOVERY_REQUIRED. The current implementation persists the transaction-relevant subset using atomic rename:

IDLE -> CHECKING -> VERIFIED -> BACKING_UP -> INSTALLING -> VERIFYING -> COMMITTED

AVAILABLE, WAITING_WINDOW, PREPARING, DOWNLOADING and STAGED are transient in v1; failure details are logged and represented by stable exit codes rather than a second persistent transition. An install or health failure enters ROLLING_BACK and finishes at ROLLED_BACK. Startup recovery treats INSTALLING, VERIFYING and ROLLING_BACK as incomplete transactions and invokes rollback from the recorded backup.

The journal records installed version, installed update ID, highest accepted sequence, signed manifest hash, previous version, pending update, current phase, active backup and last successful health-check. Each key update rewrites a mode-0600 temporary file, renames it over the state file and calls sync.

One mkdir-based process lock prevents concurrent updater transactions. The request marker and critical barrier live at `/tmp/vward-update-requested` and `/tmp/vward-update.lock`. Existing VWARD jobs do not yet cooperate with them, so production automatic apply is fail-closed behind barrier_integration_ready=0.
