# Выпуск VWARD 0.2.0

Этапы: **RC1 → RC2 → RP1 → RP2 → RETAIL**. Условия каждого этапа описаны в
[`MASTER_PLAN_0.2_TO_FINAL.md`](MASTER_PLAN_0.2_TO_FINAL.md). Здесь описан порядок
выпуска и приёмки на роутере.

| Этап | VERSION | Что меняется |
|---|---|---|
| RC1 | `0.2.0-rc.1` | feature complete, новые функции больше не добавляются |
| RC2 | `0.2.0-rc.2` | только исправления RC1 с regression-тестами |
| RP1 | `0.2.0-rp.1` | code freeze, репетиция выпуска на роутере |
| RP2 | `0.2.0-rp.2` | только исправления RP1 и документация |
| RETAIL | `0.2.0` | тот же код, что RP2, кроме VERSION/metadata |

## Состояние RC1

Готово в репозитории:

- VERSION `0.2.0-rc.1`, совпадает с metadata компонентов;
- release rehearsal `tests/updater/run-release-rehearsal.sh` (запускается в CI и перед
  подписью в `build-dev-release.yml`):
  - настоящий candidate подписывается штатным `prepare-dev-release.sh` одноразовым ключом;
  - candidate ставится поверх файлов из настоящих signed beta-пакетов (`origin/beta`) с
    `0.1.9-beta`/`sequence 2026091701`;
  - после установки проверяются подписанные digest и mode всех целей и full health;
  - затем выполняется rollback до побайтно исходного состояния;
- rehearsal нашёл и закрыл два дефекта, из-за которых updater отклонял бы любой
  настоящий пакет 0.2: шаблон lighttpd лежал в локальной конфигурации `/opt/etc/vward`,
  а профиль `full` из release script не принимался проверкой пакета.

## Переход beta → 0.2 на установленном роутере

`beta` и `dev` используют разные имена runtime-файлов, init-скриптов и cron-заданий
(например, `agh-adaptive-live.sh` в beta и `vward-route-engine.sh` в dev). Signed-пакет
0.2 ставит только свои канонические цели и не трогает файлы, cron и init других веток —
значит, поверх работающей beta он просто добавит вторую, независимую копию контура.

Для перехода на роутере, где уже установлена beta, есть отдельный шаг:
`scripts/beta-to-dev-cutover.sh`. Он не ставит саму 0.2, а только готовит роутер к
обычной установке signed-пакета Update Engine:

- бэкапит crontab, `show running-config` и весь runtime-набор beta (программы,
  init-скрипты, `web/`, локальные конфиги и состояние) в
  `/opt/var/backups/vward/cutover/<метка времени>`;
- останавливает три демона beta через их же `init.d stop` (сначала watchdog, чтобы он
  не перезапустил то, что уже остановлено);
- убирает 8 cron-строк beta и добавляет 10 cron-строк dev (совпадают с
  `config/cron/root.crontab` побайтно — это проверяет
  `tests/repository/check-cutover-cron-parity.py`);
- убирает три init-скрипта beta (`S91adaptive-live`, `S92crond-supervisor`,
  `S93keenetic-apps`); `S90crond` не трогает - он общий для обеих линий;
- архивирует и убирает остальные файлы beta (best-effort: не нужно для корректности,
  только чтобы не путал набор двух версий на диске).

Режимы: `--check` (по умолчанию, ничего не меняет), `--apply`, `--list-backups`,
`--rollback МЕТКА`. `--rollback` отказывает, если на роутере уже есть init-скрипт dev
(`S91vward-route-engine`) — сначала `vward-update-rollback.sh`, потом эта команда.

Проверено на эмуляторе роутера (`tests/perf/check-cutover-emulated.py`, в CI под
`sudo`): `--apply` на настоящих файлах beta (`origin/beta`), затем настоящий
signed-кандидат 0.2 через обычный `vward-update.sh --apply` — приходит к здоровому
состоянию без единого процесса beta; отдельно `--rollback` восстанавливает crontab,
init-скрипты и программы побайтно, демоны beta запускаются заново.

На реальном роутере это ещё не проверялось: сценарий даёт то, что можно доказать без
устройства. Соответствие имён параметров (`VWARD_WAN_INTERFACE` и т. п.) при первом
запуске dev на этом роутере после cutover проверяет Device Profile, как на чистой
установке.

## Как публикуется этап

Публикация подписанного feed выполняется только после GO владельца.

1. VERSION и metadata этапа закоммичены в `dev`, CI зелёный (включая rehearsal).
2. Actions → «Build VWARD dev candidate» → Run workflow на `dev`:
   - `sequence` — больше любого опубликованного ранее (beta: `2026091701`), формат
     `ГГГГММДДNN`, например `2026092301`;
   - `min_vward` — наименьшая установленная версия, с которой разрешён переход
     (для RC1 — `0.1.9-beta`, для RC2 — `0.2.0-rc.1` и т. д.).
3. Workflow повторяет проверки и rehearsal и подписывает пакет production-ключом из
   secret. Затем он коммитит `updates/dev/` и `SHA256SUMS` в `dev`.
4. Роутеры, у которых `manifest_url` указывает на feed ветки `dev`, получат обновление.
   При `auto_apply=1` оно установится в safe window или сразу, если выбрано
   `apply_window=any`. Роутеры на beta читают feed ветки `main` и сами на `dev` не
   переходят. На установленной 0.2 канал выбирается в Console («Обновления → Канал»,
   подтверждение `UPDATE_FEED_DEV`).

Проверка подписи без роутера:

```sh
jq -cS .signed updates/dev/update-manifest.json > /tmp/signed.json
jq -r .signature updates/dev/update-manifest.json | openssl base64 -d -A > /tmp/signature.bin
openssl pkeyutl -verify -pubin -inkey config/updater/update-public.pem -rawin \
  -in /tmp/signed.json -sigfile /tmp/signature.bin
```

## Приёмка на роутере

До установки:

```sh
mkdir -p /opt/var/backups/vward/rc-preflight
crontab -l > /opt/var/backups/vward/rc-preflight/root.crontab
ndmc -c 'show running-config' > /opt/var/backups/vward/rc-preflight/running-config.txt
tar -czf /opt/var/backups/vward/rc-preflight/opt-vward.tar.gz /opt/etc/vward /opt/share/vward 2>/dev/null
/opt/share/vward/updater/current/vward-update.sh --status
```

После установки:

- `sed -n 1p /opt/share/vward/VERSION` показывает версию этапа;
- `vward-update.sh --status`: `phase=COMMITTED`;
- Console открывается из LAN, `api.cgi?action=ping` отвечает `ok:true`;
- DNS, обычный интернет, VPN-маршруты и прямые исключения работают;
- `crontab -l` содержит только ожидаемые задания, нет двойного запуска старых и новых;
- после перезагрузки службы и Console вернулись;
- журналы updater, route engine, WAN Guard и Tunnel Guard без новых ошибок;
- наблюдение: RC1 — 24–48 часов, RC2 — 3–7 суток, RP1 — 7 суток.

## Откат

- Автоматически: при неуспешном health updater откатывает транзакцию сам.
- Вручную: `/opt/share/vward/updater/current/vward-update-rollback.sh` возвращает файлы
  последней транзакции из backup.
- Если откат не завершён (`RECOVERY_REQUIRED`), действуйте по
  [`UPDATE_RECOVERY.md`](UPDATE_RECOVERY.md). Lock и journal не удаляйте, пока не
  определена активная транзакция.
- Cron и Keenetic-конфигурация восстанавливаются из `rc-preflight`.
- Новый этап всегда выпускается с большим `sequence`. Опубликованный manifest не
  переподписывается и не заменяется более старым: updater отклонит повтор и понижение.
