# Архитектура VWARD Update Engine

Update Engine использует подписанный production feed и собственный runtime. На
целевом роутере пройдены автоматическое применение, rollback и возобновление служб.

## Последовательность

1. Скачать manifest с ограничением размера и optional ETag.
2. Проверить schema, channel, SemVer, signature и compatibility.
3. Применить monotonic trust и quarantine policy.
4. Сохранить verified pending update.
5. Дождаться окна согласно приоритету.
6. Выполнить preflight activity/space.
7. Скачать package с signed size bound.
8. Проверить SHA-256, compressed/unpacked size и tar metadata.
9. Проверить каждый payload hash, target, owner и mode.
10. Остановить supervisor, cron и Adaptive Live; дождаться активных jobs.
11. Захватить owned barrier и повторить safety checks.
12. Создать verified targeted backup и заменить файлы sibling rename.
13. Выполнить component health profile.
14. Atomically commit metadata либо deterministically rollback.
15. Quarantine release после неудачной установки/health и успешного rollback.

## Границы владения

Разрешены только точные VWARD paths из installation map и VERSION target. Local
configuration, generated files, state, logs, backups и credentials запрещены.
Registry из активного updater slot определяет ownership. Update Engine проверяет
совпадение component set feed/package, зависимости и отсутствие undeclared payload.

Успешный commit обновляет `committed.state` и `components.json`. Update Engine нельзя
перезаписать обычным package: для него используется slot installer.

## Watcher

HTTP 304 без pending update - нормальный IDLE. Deferred, quarantined, safety,
verification, compatibility, install и health outcomes не запускают быстрый retry.
Короткие bounded retries разрешены только для явно transient network/HTTP ошибок.

## Следующие gates

- signed file removal только для реальной component consolidation;
- дальнейшая A/B-активация updater только после отдельной acceptance.
