# Зависимости

Список основан на фактических вызовах команд и составе рабочей установки.

## KeeneticOS

- `ndmc` и Keenetic RCI на `127.0.0.1:79`;
- команды интерфейсов и FQDN object groups, используемые скриптами;
- совместимая BusyBox-среда с POSIX `sh` и базовыми утилитами.

## Обязательные пакеты Entware

- `busybox` - shell, crond и базовые команды;
- `curl` - HTTP/RCI probes и загрузки;
- `jq` - JSON в CGI и updater;
- `tcpdump` - наблюдение DNS;
- `lighttpd`, `lighttpd-mod-cgi` - VWARD Console;
- `ca-bundle` - проверка HTTPS;
- `openssl-util` - проверка Ed25519-подписей;
- `tar` с gzip - распаковка update packages.

Транзитивные библиотеки Entware не являются отдельными целями VWARD.

## Условные интеграции

- `adguardhome-go` нужен только для query-log discovery; VWARD не включает его binary
  и database.
- `opt-ndmsv2` обеспечивает интеграцию Entware/Keenetic на рабочем устройстве.

`wget` не требуется. Устаревший `scripts/update-ui.sh` удалён. VWARD Update Engine
развёрнут на целевом роутере; автоматическое применение определяется локальными
allowlisted-флагами.
