# Участие в разработке

1. Начинайте от актуальной `main` и проверяйте `VERSION`/component registry.
2. Не публикуйте local config, state, logs, router dumps, credentials или private keys.
3. Не меняйте runtime path/ID без dependency map и совместимой migration.
4. Сохраняйте POSIX `sh`/BusyBox compatibility; выполняйте `sh -n` и тесты.
5. Обновляйте документацию и `SHA256SUMS` вместе с изменением source.
6. Не изменяйте signed feed/package без release-процедуры и signing authority.
7. Делайте небольшие атомарные commits; не смешивайте docs, runtime и security fixes.

Перед отправкой выполните:

```sh
tests/repository/run-consistency-checks.sh
tests/updater/run-simulations.sh
sha256sum -c SHA256SUMS
```
