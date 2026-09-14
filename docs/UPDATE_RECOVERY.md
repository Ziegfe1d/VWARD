# Восстановление VWARD Update Engine

## Восстановление при загрузке

/opt/etc/init.d/S89vward-update-recovery start проверяет journal до запуска
cron и фоновых служб. Фазы CHECKING, VERIFIED, BACKING_UP, INSTALLING,
VERIFYING, COMMIT_PREPARED, ROLLING_BACK и RECOVERY_REQUIRED передаются
штатной команде vward-update.sh --recover.

Успешное восстановление удаляет старый failure marker. Ошибка сохраняется в
/opt/var/lib/vward/updater/boot-recovery.failed, а подробный вывод — в
/opt/var/log/vward/updater-recovery.log. Проверки подписи и целостности при
этом не отключаются.

До замены сохраняются только затрагиваемые program files. Backup index содержит path,
mode и SHA-256. Rollback проверяет index, metadata и payload перед восстановлением,
а затем проверяет восстановленные hashes/modes.

Файл записывается во временного sibling, проверяется, получает mode, синхронизируется
и переименовывается на target filesystem. Multi-file install - journaled transaction,
а не одна filesystem-atomic операция.

После потери питания используются `journal.state` и verified backup. Фазы
`INSTALLING`, `VERIFYING`, `ROLLING_BACK`, `RECOVERY_REQUIRED` ведут к rollback.
`COMMIT_PREPARED` завершает уже записанный committed snapshot либо возвращает старую
транзакцию.

Release после install/health failure и успешного rollback помещается в quarantine.
Trust sequence не откатывается. Stale staging очищается только под updater lock;
pending cache сохраняется. Request/barrier marker удаляется лишь для доказанно
мёртвого owner process.
