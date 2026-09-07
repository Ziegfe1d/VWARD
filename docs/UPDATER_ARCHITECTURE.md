# Smart Updater v1 architecture

Smart Updater v1 is implemented for code audit and filesystem simulation but is not deployed or production-ready.

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
10. pre-check activity and cumulative backup/target filesystem space;
11. request update barrier, drain jobs, acquire barrier and re-check activity;
12. create targeted verified backup and install via sibling-file atomic rename;
13. run bounded health check;
14. atomically commit installation metadata or deterministically roll back;
15. quarantine an update that failed install/health after successful rollback.

## Ownership boundaries

Only exact VWARD runtime paths from `docs/INSTALLATION_MAP.md` plus the planned `/opt/share/vward/VERSION` bootstrap target are installable. Device-local configuration, generated files, state, logs, backups and credentials are never payload targets.

## Watcher behavior

HTTP 304 with no pending update is a normal idle state. Deferred/quarantined/safety/verification/compatibility/install/health outcomes are not fast-retried. Only explicitly transient network/HTTP conditions use short bounded retries; all other outcomes wait for the normal watcher interval or a new/manual action.

## Deployment gates

- production Ed25519 key and reviewed offline signing process;
- target Entware validation for OpenSSL Ed25519, curl `--max-filesize`, tar listing format and shell utilities;
- cooperative barrier integration in current VWARD jobs;
- service restart order and bounded component health probes;
- backup pruning and A/B updater activation;
- non-production Keenetic test before any live-router deployment.
