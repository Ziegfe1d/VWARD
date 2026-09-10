# Машина состояний VWARD Update Engine

Обычный путь:

`IDLE → CHECKING → VERIFIED → AVAILABLE → STAGING → INSTALLING → VERIFYING → COMMITTED`

Восстановление:

`ROLLING_BACK → ROLLED_BACK` либо `RECOVERY_REQUIRED`.

`committed.state` заменяется атомарно только после успешного health-check.
`journal.state` хранит phase, candidate metadata и active backup. При
`COMMIT_PREPARED` recovery завершает новую транзакцию только когда committed snapshot
уже совпадает с candidate; иначе восстанавливает старые files/metadata.

`trust.state`, `quarantine.state` и `pending/` независимы от installed state, поэтому
rollback не открывает replay window и не повторяет unattended known-bad release.

Один mkdir-based process lock защищает updater. Координация runtime двухфазная:

1. создать owned `vward-update-requested` marker;
2. остановить VWARD-owned services и дождаться jobs;
3. захватить owned `vward-update.lock` barrier;
4. повторно проверить activity/conflict locks;
5. выполнить transaction и восстановить только ранее работавшие services.

Stale ownership восстанавливается только для доказанно мёртвого updater owner. Live,
malformed или foreign ownership блокирует транзакцию.
