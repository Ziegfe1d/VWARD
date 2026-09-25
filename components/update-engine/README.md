# VWARD Update Engine 2.0

Движок устанавливает подписанные обновления после пройденной live-router приёмки
apply, rollback, runtime quiescing и возобновления служб (1.x). Версия 2.0 скачивает
и заменяет только изменившиеся файлы и обновляет сама себя; на роутере 2.0 ещё не
проверена.

## Пофайловые обновления (схема 2)

- Лента: `updates/<канал>/v2/manifest.json` - подписанный Ed25519 список всех файлов
  (путь, SHA-256, размер, права, компонент) и файлов движка; сами файлы лежат в
  `v2/files/<sha256>`.
- Движок одним вызовом `sha256sum` сравнивает список с роутером. Скачиваются,
  проверяются, копируются в резервную копию и заменяются только отличающиеся файлы
  (другое содержимое или права). Если ничего не изменилось, версия просто фиксируется.
- Каждый скачанный файл сверяется с размером и SHA-256 из подписанного списка.
  Разрешены только пути VWARD: `/opt/bin/vward-*`, `/opt/lib/vward/`, `/opt/share/vward/`
  (кроме `updater/`), `/opt/etc/init.d/S??vward-*`, `S90crond`; права 0644 или 0755.
- Перезапускаются только компоненты с изменёнными файлами. Итог (сколько файлов
  заменено и скачано байт) пишется в `last-apply.state` и показывается в консоли.
- Лента схемы 1 (один архив) продолжает публиковаться для движков 1.x; движок 2
  берёт v2 и переходит на v1, только если v2 нет (404).

## Самообновление движка

- Если в ленте версия движка новее установленной, новые файлы сначала проверяются
  (`sh -n`, `--self-test` должен сообщить ту же версию), затем пишутся в неактивный
  слот A/B, и ссылка `current` переключается атомарно. Прежний слот записывается в
  журнал; обновление продолжает уже новый движок.
- Сломанный движок не активируется. `--engine-revert` возвращает прежний слот.
- Переход с 1.x без команд: почасовое обслуживание (из следующего пакета v1) один раз
  скачивает ленту v2, проверяет подпись ключом роутера и выполняет `--engine-adopt`.

## Выборочные обновления компонентов

- `affected_components` и component ID каждого package file нормализуются registry.
- Target должен принадлежать указанному компоненту; неизвестные IDs, duplicates,
  undeclared payload и несовпадение component sets отклоняются до runtime barrier.
- Legacy IDs принимаются как aliases, state записывается с canonical IDs.
- Backup/replace/rollback затрагивают только объявленные changed files.
- `components.json` хранит release, update, sequence, health и installed hashes.
- `update-engine` не заменяется обычным пакетом: только через слоты (см. выше).

## Безопасность жизненного цикла

- `committed.state` - установленная версия и update;
- `trust.state` - highest accepted signed sequence, не уменьшается при rollback;
- `quarantine.state` - запрет unattended retry known-bad update;
- `pending/` - verified update до apply, supersede или quarantine;
- stale locks/markers восстанавливаются только при доказанно мёртвом owner;
- reclaim gate содержит `boot_id` и после аварийного завершения снимается только
  boot-recovery при доказанном переходе между загрузками;
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
- `vward-update.sh --self-test MANIFEST`
- `vward-update.sh --engine-adopt DIR MANIFEST`
- `vward-update.sh --engine-revert`

Automatic apply требует `auto_apply=1`, соответствующего priority flag и
`barrier_integration_ready=1`. Quiescing останавливает supervisor, cron и Adaptive
Live, ждёт active jobs и возвращает только ранее работавшие службы.

Bootstrap устанавливает pinned Ed25519 public key, updater slot, сохраняет прежнюю
установку и добавляет signed-feed checks. Private signing key не хранится здесь или
на роутере.
