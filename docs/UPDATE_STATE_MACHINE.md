# Smart Updater v1 state machine

Persistent transaction phases include:

`IDLE -> CHECKING -> VERIFIED -> AVAILABLE/WAITING_WINDOW -> BACKING_UP -> INSTALLING -> VERIFYING -> COMMIT_PREPARED -> COMMITTED`

Failure/recovery phases include:

`ROLLING_BACK -> ROLLED_BACK` and `RECOVERY_REQUIRED`.

`committed.state` is atomically replaced only after health success. `journal.state` records transaction phase, candidate metadata and active backup. Recovery from `COMMIT_PREPARED` finalizes the new transaction only when the atomic committed snapshot already matches the candidate; otherwise it restores the old files/metadata from backup.

`trust.state`, `quarantine.state` and `pending/` are independent from committed installation state so rollback cannot accidentally reopen replay windows or trigger repeated unattended installation of a known-bad release.

The updater owns one mkdir-based process lock. Update coordination is two-phase:

1. set owned `vward-update-requested` marker;
2. drain cooperative VWARD jobs;
3. acquire owned `vward-update.lock` barrier;
4. re-check activity/conflict locks under the barrier;
5. only then enter backup/install.

Stale request/barrier ownership is recovered only for a proven-dead updater owner. Live, malformed or foreign ownership blocks the transaction.
