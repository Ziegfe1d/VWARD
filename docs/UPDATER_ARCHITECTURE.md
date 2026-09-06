# Future updater architecture

No updater is implemented in this migration.

A future updater must treat GitHub as source and the router as an installed copy:

1. read a versioned manifest;
2. download into a staging directory;
3. verify SHA-256 for every payload;
4. check KeeneticOS, Entware, schema and free-space compatibility;
5. back up the current program files and record local configuration/state ownership;
6. install with same-filesystem atomic replacement;
7. restore declared modes and ownership;
8. restart only affected services in dependency order;
9. run bounded health checks;
10. mark success and prune old backups.

On any failure, restore the backup, restore service state and report a clear error.

The updater must never overwrite device-local configuration, `/opt/var/lib` state, logs or backups. It must not use `git pull` or `git clone` inside the production tree.
