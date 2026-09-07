# Smart Updater state machine

Primary transaction phases are persisted in `journal.state`:

`IDLE -> CHECKING -> VERIFIED -> AVAILABLE/WAITING_WINDOW -> BACKING_UP -> INSTALLING -> VERIFYING -> COMMIT_PREPARED -> COMMITTED`

Failure/recovery paths use:

`ROLLING_BACK -> ROLLED_BACK` and `RECOVERY_REQUIRED`.

## Related state that is not the transaction phase

- **pending**: verified feed candidate waiting for policy/safe window.
- **trusted highest sequence**: monotonic anti-replay ledger, independent of installed version.
- **quarantined**: exact update that failed install/health and rolled back; automatic retry is suppressed.

## Barrier transition

Mutation is only allowed after:

`pre-safety-check -> update-requested(owner token) -> drain cooperative jobs -> update.lock(owner token) -> post-barrier conflict recheck -> backup/install`.

If the post-barrier recheck fails, no installed file may be changed.

## Recovery rules

- CHECKING / VERIFIED / BACKING_UP without mutation can return to IDLE.
- INSTALLING / VERIFYING / ROLLING_BACK / RECOVERY_REQUIRED use verified rollback state.
- COMMIT_PREPARED finalizes only when committed metadata already equals the candidate; otherwise it rolls back.
- COMMITTED is stable installed state.
- Highest trusted sequence is never decremented by rollback.
