# Установка

## Сейчас

Текущий snapshot рассчитан на уже работающий локальный web-сервис проекта:

- document root: `/opt/share/keenetic-apps/www`
- UI: `/opt/share/keenetic-apps/www/index.html`
- порт панели: `8088`

Для обновления только HTML после публикации репозитория:

```sh
/opt/bin/wget -qO-   https://raw.githubusercontent.com/Ziegfe1d/VWARD/main/scripts/update-ui.sh   | /opt/bin/sh
```

## Что будет в public v1.0

Планируется один installer, который:

1. проверит Keenetic/Entware;
2. определит LAN IP;
3. поставит нужные Entware-пакеты;
4. не затронет системный nginx Keenetic;
5. поднимет отдельный lighttpd только на LAN;
6. установит frontend/backend;
7. создаст сервис и updater;
8. выполнит health-check;
9. при ошибке откатит изменения.

До завершения этого этапа `0.1.0-dev` нельзя считать универсальным one-click installer.
