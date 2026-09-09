# Smart Updater v1 architecture

Smart Updater v1 has a signed production feed and updater-owned runtime
quiescing. Automatic application was enabled after live-router apply, rollback
and service-resume acceptance passed.

Flow:

1. fetch a small signed manifest with bounded size and optional ETag;
2. verify structure, channel, SemVer, signature and compatibility;
3. enforce monotonic trust (`trust.state`) and quarantine policy;
4. persist a verified pending update;
5. wait according to CRITICAL/IMPORTANT/ROUTINE scheduling policy;
6. preflight compressed/unpacked staging size;
7. download the package with a signed-size transport bound;
8. verify package SHA-256/size and tar declared unpacked size;
9. extract and verify actual unpacked bytes plus every payload hash/target/mode;
10. quiesce the cron supervisor, cron and Adaptive Live, then drain active jobs;
11. pre-check activity and space, acquire the owned barrier and re-check activity;
12. create targeted verified backup and install via sibling-file atomic rename;
13. run bounded health check;
14. atomically commit installation metadata or deterministically roll back;
15. quarantine an update that failed install/health after successful rollback.

## Ownership boundaries

Only exact VWARD runtime paths from `docs/INSTALLATION_MAP.md` plus the planned `/opt/share/vward/VERSION` bootstrap target are installable. Device-local configuration, generated files, state, logs, backups and credentials are never payload targets.

The active updater slot contains the authoritative component registry. Before
quiescing runtime, Smart Updater 1.1 verifies the exact signed/package component
set, canonical target ownership, permitted mode, unique sources and targets,
declared dependencies, every payload SHA-256 and the absence of undeclared
archive files.

Successful commit writes both platform-wide `committed.state` and selective
`components.json`. Both are transactionally backed up and restored. Update
Engine itself remains protected from normal packages and uses slot installation.

## Watcher behavior

HTTP 304 with no pending update is a normal idle state. Deferred/quarantined/safety/verification/compatibility/install/health outcomes are not fast-retried. Only explicitly transient network/HTTP conditions use short bounded retries; all other outcomes wait for the normal watcher interval or a new/manual action.

## Future extension gates

- signed file removal, only when a real component consolidation requires it;
- A/B updater activation beyond the accepted slot installer.
