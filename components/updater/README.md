# VWARD Update Engine v1.2

Движок устанавливает подписанные обновления после пройденной live-router приёмки
apply, rollback, runtime quiescing и возобновления служб.

## Выборочные обновления компонентов

- `affected_components` и component ID каждого package file нормализуются registry.
- Target должен принадлежать указанному компоненту; неизвестные IDs, duplicates,
  undeclared payload и несовпадение component sets отклоняются до runtime barrier.
- Legacy IDs принимаются как aliases, state записывается с canonical IDs.
- Backup/replace/rollback затрагивают только объявленные changed files.
- `components.json` хранит release, update, sequence, health и installed hashes.
- `update-engine` защищён slot installer и не заменяет сам себя обычным package.

## Безопасность жизненного цикла

- `committed.state` - установленная версия и update;
- `trust.state` - highest accepted signed sequence, не уменьшается при rollback;
- `quarantine.state` - запрет unattended retry known-bad update;
- `pending/` - verified update до apply, supersede или quarantine;
- stale locks/markers восстанавливаются только при доказанно мёртвом owner;
- malformed или foreign ownership обрабатывается fail-closed.

## Расписание

CRITICAL использует первую hard-safe точку. IMPORTANT предпочитает safe window и
эскалируется после deadline. ROUTINE предпочитает quiet window и имеет более длинный
deadline. Signature, integrity, compatibility, space и barrier checks обязательны.

## Команды

- `vward-update.sh --status`
- `vward-update.sh --status-components`
- `vward-update.sh --check`
- `vward-update.sh --dry-run`
- `vward-update.sh --apply`
- `vward-update.sh --apply-pending`
- `vward-update.sh --rollback`
- `vward-update.sh --recover`

Automatic apply требует `auto_apply=1`, соответствующего priority flag и
`barrier_integration_ready=1`. Quiescing останавливает supervisor, cron и Adaptive
Live, ждёт active jobs и возвращает только ранее работавшие службы.

Bootstrap устанавливает pinned Ed25519 public key, updater slot, сохраняет прежнюю
установку и добавляет signed-feed checks. Private signing key не хранится здесь или
на роутере.
