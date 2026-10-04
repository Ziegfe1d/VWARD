# VWARD

**VWARD** - единая локальная платформа для маршрутизации, контроля VPN и WAN,
автоматического восстановления, диагностики и безопасных обновлений на роутерах
Keenetic с Entware.

Текущая версия ветки `dev`: **0.2.0-rc.2.fix.4** (RC2: стабильность и исправления). Этапы выпуска:
RC1 → RC2 → RP1 → RP2 → RETAIL, см. [`docs/RELEASE_0.2.0.md`](docs/RELEASE_0.2.0.md).
Это ещё не стабильный релиз.

VWARD работает на самом роутере и объединяет несколько согласованных компонентов.
Часть компонентов наблюдает за сетью, часть может менять маршрутизацию, WireGuard или
WAN. Перенос на другой роутер требует проверки локальных имён интерфейсов, адресов и
политик - копировать файлы в `/opt` вслепую нельзя.

## Компоненты

| Компонент | Назначение |
|---|---|
| VWARD Platform Core | Версия платформы и общая модель компонентов |
| VWARD Route Engine | Адаптивная маршрутизация по DNS-активности |
| VWARD Route Reconciler | Периодическая сверка адаптивных маршрутов |
| VWARD Route Tools | Диагностика и инструменты маршрутизации |
| VWARD Tunnel Guard | Контроль WireGuard и fail-open защита |
| VWARD WAN Guard | Диагностика и ступенчатое восстановление WAN |
| VWARD Wi-Fi Client Guard | Анализ стабильности Wi-Fi клиентов и безопасные рекомендации по диапазону |
| VWARD Policy Sync | Сверка доменных и сетевых политик VPN |
| VWARD Runtime | Cron, init-скрипты и фоновые процессы |
| Панель VWARD | Локальная веб-панель, журналы и безопасные настройки |
| VWARD Update Engine | Подписанные компонентные обновления и rollback |
| VWARD Ads & Privacy Guard | Защита от рекламы и трекинга |

Канонические ID, названия, зависимости и runtime-targets заданы в
[`config/components/component-registry.json`](config/components/component-registry.json).
Runtime-файлы, init-скрипты и управляемые пути используют каноническое пространство
имён VWARD без переходных aliases и wrappers. Сводка унификации:
[`docs/NAMING_MIGRATION.md`](docs/NAMING_MIGRATION.md).

## Поддерживаемая среда

- KeeneticOS с `ndmc` и локальным RCI;
- Entware на USB-накопителе, смонтированном как `/opt`;
- POSIX `sh`/BusyBox и [зависимости VWARD](docs/DEPENDENCIES.md);
- локальный доступ к Панели VWARD через LAN.

Production-профиль проверен на Keenetic автора; установка на чистый роутер проверена
на эмуляторе.

## Установка

Нужны: Keenetic с KeeneticOS 5.0 или новее (на 3.x и 4.x VWARD не ставится), флешка с Entware и VPN-подключение в Keenetic.
Подготовка роутера и Entware - в [`docs/INSTALL.md`](docs/INSTALL.md). Затем по SSH:

```sh
opkg update && opkg install curl
curl -fsSL https://raw.githubusercontent.com/Ziegfe1d/VWARD/dev/install.sh -o /tmp/vward-install.sh
sh /tmp/vward-install.sh
```

Полный путь, команды проверки, recovery и удаление: [`docs/INSTALL.md`](docs/INSTALL.md).
Карта source → runtime: [`docs/INSTALLATION_MAP.md`](docs/INSTALLATION_MAP.md).

## Параметры конкретного роутера

Параметры LAN, DNS, WAN, VPN, policy group и порта Панели VWARD сведены в единый
`/opt/etc/vward/device.conf`. Пустые сетевые значения безопасно обнаруживаются;
при нескольких кандидатах VWARD останавливается и требует явной настройки. Перед
установкой проверьте профиль по [`docs/INSTALLATION_MAP.md`](docs/INSTALLATION_MAP.md).

## Обновления

VWARD Update Engine получает подписанный Ed25519 manifest и устанавливает только
разрешённые цели из компонентного пакета. Используются staging, backup, health-check,
атомарная активация слота и rollback. Механизм прошёл live-router
apply/rollback/service-resume acceptance на целевом устройстве.

Не клонируйте Git-репозиторий прямо в `/opt` и не заменяйте им локальную конфигурацию.
См. [`docs/UPDATER_ARCHITECTURE.md`](docs/UPDATER_ARCHITECTURE.md),
[`docs/UPDATE_POLICY.md`](docs/UPDATE_POLICY.md) и
[`docs/UPDATE_RECOVERY.md`](docs/UPDATE_RECOVERY.md).

## Что не публикуется

- приватные и preshared-ключи WireGuard, пароли, токены и signing private key;
- router/self-test dumps, персональные DNS/query-журналы и локальные политики;
- `/opt/etc`, `/opt/var/lib`, `/opt/var/log`, PID/lock-файлы и backup-копии;
- сгенерированный `hints.conf`.

Подробнее: [`docs/SOURCE_CLASSIFICATION.md`](docs/SOURCE_CLASSIFICATION.md) и
[`SECURITY.md`](SECURITY.md).

## Структура

- `components/` - исходники компонентов;
- `config/` - схемы, примеры конфигурации и управляемый cron;
- `web/` - Панель VWARD, CGI API и lighttpd;
- `updates/` - подписанные каналы обновлений и опубликованные пакеты;
- `tests/` - симуляции VWARD Update Engine;
- `docs/` - установка, архитектура, эксплуатация и recovery.

## Документация

- [Установка, проверка, восстановление и удаление](docs/INSTALL.md)
- [Архитектура](docs/ARCHITECTURE.md)
- [Модель компонентов](docs/COMPONENT_MODEL.md)
- [Карта установки](docs/INSTALLATION_MAP.md)
- [Зависимости](docs/DEPENDENCIES.md)
- [Миграция названий](docs/NAMING_MIGRATION.md)
- [Панель VWARD и безопасные настройки](docs/PANEL.md)
- [Политика обновлений](docs/UPDATE_POLICY.md)
- [Безопасность обновлений](docs/UPDATE_SECURITY.md)
- [Идентификация и восстановление ключа подписи](docs/SIGNING_KEY_RECOVERY.md)
- [Политика веток и версий](docs/BRANCH_POLICY.md)
- [Единый план от Dev до Final](docs/MASTER_PLAN_0.2_TO_FINAL.md)
- [План разработки 0.2.0-dev](docs/DEV_0.2_PLAN.md)
- [Дорожная карта](docs/ROADMAP.md)

## Лицензия

MIT. См. [`LICENSE`](LICENSE).
