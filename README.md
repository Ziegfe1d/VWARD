# VWARD

**VWARD** - единая локальная платформа для маршрутизации, контроля VPN и WAN,
автоматического восстановления, диагностики и безопасных обновлений на роутерах
Keenetic с Entware.

Текущая Beta-линия: **0.2.0-beta.1**. Это тестовая ветка глубокой универсализации
VWARD. Стабильная/переходная линия 0.1.x развивается отдельно в `main`.

VWARD работает на самом роутере и объединяет несколько согласованных компонентов.
Часть компонентов наблюдает за сетью, часть может менять маршрутизацию, WireGuard или
WAN. В Beta начат переход к модели Discovery First: компоненты должны определять
фактические интерфейсы и роли во время выполнения, а не зависеть от имён конкретной
домашней установки.

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
| VWARD Runtime | Cron, discovery, init-скрипты и фоновые процессы |
| VWARD Console | Локальная веб-панель, журналы и безопасные настройки |
| VWARD Update Engine | Подписанные компонентные обновления и rollback |

Канонические ID, названия, зависимости и runtime-targets заданы в
[`config/components/component-registry.json`](config/components/component-registry.json).
Старые имена каталогов и скриптов пока сохранены для совместимости; это не отдельные
продукты. План унификации: [`docs/NAMING_MIGRATION.md`](docs/NAMING_MIGRATION.md).

## Discovery First

В Beta-линии вводится общий read-only слой `VWARD Discovery`, который входит в
`VWARD Runtime`. Первый этап обнаруживает WireGuard по фактическому типу RCI, а не по
имени или номеру интерфейса, и не выбирает случайный туннель при неоднозначности.

Архитектура и fail-safe правила: [`docs/DISCOVERY.md`](docs/DISCOVERY.md).

## Поддерживаемая среда

- KeeneticOS с `ndmc` и локальным RCI;
- Entware на USB-накопителе, смонтированном как `/opt`;
- POSIX `sh`/BusyBox и [зависимости VWARD](docs/DEPENDENCIES.md);
- локальный доступ к VWARD Console через LAN.

Production-профиль 0.1.x проверен на текущем Keenetic/Entware-устройстве автора.
Beta 0.2.x пока не заявляется как production-ready.

## Установка

1. Подготовьте USB и Entware.
2. Определите параметры своего роутера; не используйте значения примера вслепую.
3. Установите зависимости.
4. Выполните первичную установку.
5. Проверьте процессы, cron, Console и сетевое поведение.
6. Только после этого разрешайте автоматическое применение обновлений.

Полный путь, команды проверки, recovery и удаление: [`docs/INSTALL.md`](docs/INSTALL.md).
Карта source -> runtime: [`docs/INSTALLATION_MAP.md`](docs/INSTALLATION_MAP.md).

## Параметры конкретного роутера

В legacy runtime-коде 0.1.x ещё встречаются значения конкретной установки, включая
имена WAN/VPN-интерфейсов, локальные подсети и ID policy groups. В 0.2.x они должны
постепенно заменяться discovery/role mapping без массового небезопасного search/replace.

Перенос на другую установку пока требует проверки по
[`docs/INSTALLATION_MAP.md`](docs/INSTALLATION_MAP.md).

## Обновления

VWARD Update Engine получает подписанный Ed25519 manifest и устанавливает только
разрешённые цели из компонентного пакета. Используются staging, backup, health-check,
атомарная активация слота и rollback.

Целевая модель каналов:
- `main` - Stable;
- `beta` - Beta;
- `CRITICAL` - приоритет доставки, а не отдельный канал.

Production private signing key не хранится в репозитории. Пока ключ недоступен,
новые Beta-пакеты можно собирать и тестировать, но нельзя публиковать как доверенные
автоматические обновления.

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
- `updates/` - опубликованные подписанные feeds и пакеты;
- `tests/` - repository и Update Engine simulations;
- `docs/` - установка, архитектура, эксплуатация и recovery.

## Документация

- [Установка, проверка, восстановление и удаление](docs/INSTALL.md)
- [Архитектура](docs/ARCHITECTURE.md)
- [Discovery First и role mapping](docs/DISCOVERY.md)
- [Модель компонентов](docs/COMPONENT_MODEL.md)
- [Карта установки](docs/INSTALLATION_MAP.md)
- [Зависимости](docs/DEPENDENCIES.md)
- [Миграция названий](docs/NAMING_MIGRATION.md)
- [VWARD Console и безопасные настройки](docs/CONSOLE.md)
- [Политика обновлений](docs/UPDATE_POLICY.md)
- [Безопасность обновлений](docs/UPDATE_SECURITY.md)
- [Дорожная карта](docs/ROADMAP.md)

## Лицензия

MIT. См. [`LICENSE`](LICENSE).
