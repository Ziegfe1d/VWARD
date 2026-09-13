# VWARD

**VWARD** - единая локальная платформа для маршрутизации, контроля VPN и WAN,
автоматического восстановления, диагностики и безопасных обновлений на роутерах
Keenetic с Entware.

Текущая версия ветки `dev`: **0.2.0-dev.1**. Это активная версия для глубокой
разработки и несовместимых изменений, а не beta или стабильный релиз.

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
| VWARD Policy Sync | Сверка доменных и сетевых политик VPN |
| VWARD Runtime | Cron, init-скрипты и фоновые процессы |
| VWARD Console | Локальная веб-панель, журналы и безопасные настройки |
| VWARD Update Engine | Подписанные компонентные обновления и rollback |

Канонические ID, названия, зависимости и runtime-targets заданы в
[`config/components/component-registry.json`](config/components/component-registry.json).
Старые имена каталогов и скриптов пока сохранены для совместимости; это не отдельные
продукты. План унификации: [`docs/NAMING_MIGRATION.md`](docs/NAMING_MIGRATION.md).

## Поддерживаемая среда

- KeeneticOS с `ndmc` и локальным RCI;
- Entware на USB-накопителе, смонтированном как `/opt`;
- POSIX `sh`/BusyBox и [зависимости VWARD](docs/DEPENDENCIES.md);
- локальный доступ к VWARD Console через LAN.

Production-профиль проверен на текущем Keenetic/Entware-устройстве автора.
Автоматическая переносимость на любые модели Keenetic пока не заявлена.

## Установка

1. Подготовьте USB и Entware.
2. Определите параметры своего роутера; не используйте значения примера вслепую.
3. Установите зависимости.
4. Выполните первичную установку.
5. Проверьте процессы, cron, Console и сетевое поведение.
6. Только после этого разрешайте автоматическое применение обновлений.

Полный путь, команды проверки, recovery и удаление: [`docs/INSTALL.md`](docs/INSTALL.md).
Карта source → runtime: [`docs/INSTALLATION_MAP.md`](docs/INSTALLATION_MAP.md).

## Параметры конкретного роутера

В текущем профиле ещё встречаются `192.168.1.1`, `192.168.1.0/24`, `eth3`, `ISP`,
`nwg1`, `Wireguard0`, `Wireguard1` и `domain-list22`. Это значения одной рабочей
установки, не универсальные defaults. Перед установкой сопоставьте их со своим
устройством по [`docs/INSTALLATION_MAP.md`](docs/INSTALLATION_MAP.md).

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
- `web/` - VWARD Console, CGI API и lighttpd;
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
- [VWARD Console и безопасные настройки](docs/CONSOLE.md)
- [Политика обновлений](docs/UPDATE_POLICY.md)
- [Безопасность обновлений](docs/UPDATE_SECURITY.md)
- [Идентификация и восстановление ключа подписи](docs/SIGNING_KEY_RECOVERY.md)
- [Дорожная карта](docs/ROADMAP.md)

## Лицензия

MIT. См. [`LICENSE`](LICENSE).
