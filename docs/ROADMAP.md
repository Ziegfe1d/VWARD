# Roadmap

## Current: 0.1.0-dev

- canonical source tree imported from the verified working installation;
- source/runtime/configuration boundaries documented;
- installation map and dependency inventory recorded;
- generated and device-local data excluded.

## Next stage

- parameterize device-specific values without changing working behavior;
- add an installer that detects safe Keenetic defaults and preserves local config;
- add shell/static validation suitable for the BusyBox/Entware environment;
- define health checks and fixtures that do not touch a production router;
- implement the staged, checksum-verified updater design in [UPDATER_ARCHITECTURE.md](UPDATER_ARCHITECTURE.md).

No automated update or remote deployment is part of the current migration.
