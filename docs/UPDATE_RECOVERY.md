# Smart Updater recovery

The updater treats program replacement as a multi-file transaction, not as one filesystem-atomic operation.

## Durable state

- `committed.state`: currently installed version/update metadata.
- `trust.state`: monotonic highest accepted signed sequence; never rolled back.
- `journal.state`: current transaction phase and active backup.
- `pending/`: verified deferred manifest/package cache.
- `quarantine.state`: update that failed unattended apply and was successfully rolled back.

Committed metadata is written as one atomic snapshot. Recovery therefore resolves to either old files + old committed metadata or new files + new committed metadata.

## Crash and power-loss handling

Before mutation the complete package is staged and verified and a targeted backup is created. Each replacement is written to a sibling temporary file, hashed, chmodded, synced and renamed. On restart, an interrupted INSTALLING/VERIFYING/ROLLING_BACK transaction uses the recorded backup; COMMIT_PREPARED is finalized only when the atomic committed snapshot already identifies the candidate, otherwise it is rolled back.

Updater process locks, `vward-update-requested` and `vward-update.lock` carry ownership tokens. Dead owners are recovered conservatively; live or malformed/foreign ownership is never silently removed.

Orphan `transaction.*` staging directories are removed only after updater mutual exclusion is acquired and only under the exact updater staging directory. Persistent pending cache is not part of that cleanup.
