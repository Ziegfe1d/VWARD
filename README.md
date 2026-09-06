# VWARD

**VPN · WAN · Automation · Recovery · Diagnostics**  
*Pronounced: V-ward / «Ви-вард»*

Локальная платформа сетевых утилит для роутеров; первый поддерживаемый адаптер — Keenetic/Entware: единая точка входа для собственных сервисов,
диагностики WAN, WireGuard, AdGuard Home и будущих модулей управления.

> Проект находится в стадии подготовки к публичному релизу. Название VWARD не привязано к конкретному производителю роутеров. Текущая ветка — development snapshot.

## Что уже есть

- мобильный web-интерфейс;
- live-статусы через локальный backend;
- карточки WAN Guardian, WireGuard и сервисов;
- ссылки на Keenetic и AdGuard Home;
- локальная работа без облака;
- безопасная схема обновления HTML с backup;
- архитектура, в которой AdGuard Home и системный web-сервер Keenetic не модифицируются.

## Тестовая платформа

Разработка и проверка сейчас ведутся на:

- Keenetic Viva KN-1913;
- KeeneticOS 5.1.x;
- Entware на USB-накопителе;
- lighttpd из Entware;
- AdGuard Home как отдельный сервис.

Поддержка других моделей будет расширяться после тестирования.

## Архитектура

```text
Keenetic
├── системный web UI Keenetic        :80 / :443   (не трогаем)
├── AdGuard Home                     :3001        (не трогаем)
└── VWARD             :8088
    ├── web/index.html
    └── cgi-bin/api.cgi              (локальный backend)
```

## Быстрое обновление только интерфейса

После публикации репозитория HTML можно будет обновлять на роутере одной командой:

```sh
/opt/bin/wget -qO-   https://raw.githubusercontent.com/Ziegfe1d/VWARD/main/scripts/update-ui.sh   | /opt/bin/sh
```

Скрипт сначала скачивает файл во временное место, проверяет его и делает backup.
При ошибке текущая рабочая страница не заменяется.

## Важное по безопасности

В репозитории **не должно быть**:

- PrivateKey / PresharedKey WireGuard;
- токенов GitHub;
- паролей;
- startup-config роутера;
- диагностик с приватными данными;
- персональных IP/учётных данных, если они не нужны проекту.

Подробнее: [SECURITY.md](SECURITY.md).

## Статус компонентов

| Компонент | Статус |
|---|---|
| Frontend v28 | рабочий snapshot |
| Live backend | работает локально, готовится к универсализации |
| WAN Guardian | работает локально, готовится к отдельному публичному модулю |
| UI updater | готов |
| Full installer | в разработке |
| Multi-model Keenetic support | запланировано |

## Документация

- [Установка](docs/INSTALL.md)
- [Архитектура](docs/ARCHITECTURE.md)
- [План развития](docs/ROADMAP.md)
- [Чек-лист публичного релиза](docs/PUBLISHING_CHECKLIST.md)

## Лицензия

MIT. Проект не является официальным продуктом Keenetic и не связан с Keenetic Ltd.
