# Installation status

There is currently no supported automated installer.

The repository records the working source layout and exact runtime destinations in [INSTALLATION_MAP.md](INSTALLATION_MAP.md). It does not authorize copying files to a production router without review.

Before a future installation process is implemented, it must:

1. validate KeeneticOS and Entware prerequisites;
2. discover or request device-specific interface, LAN, DNS and FQDN-group values;
3. install program files separately from local configuration and state;
4. preserve file modes from the installation map;
5. install the managed cron fragment without overwriting unrelated user cron entries;
6. validate syntax and dependencies;
7. start services only after explicit confirmation;
8. provide backup and rollback.

The current migration made no changes to the router.
