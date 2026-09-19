# Архитектура VWARD

VWARD - единая платформа из взаимодействующих POSIX shell-служб и локальной
lighttpd/CGI-панели для KeeneticOS с Entware.

## Исходники и установленная система

Репозиторий хранит программы, init-скрипты, примеры конфигурации и управляемое
расписание cron. В установленной системе данные разделены:

- `/opt/bin` и `/opt/etc/init.d` - программы и службы;
- `/opt/etc` - локальная конфигурация устройства;
- `/opt/var/lib` - постоянное состояние;
- `/opt/var/log` - журналы;
- `/opt/var/backups` - резервные копии;
- `/tmp` - временные locks, probes и статусы cron.

Обновление программы не должно заменять локальную конфигурацию или состояние.

## Компоненты

### VWARD Route Engine, Reconciler и Tools

Проверяют FQDN-группы Keenetic и DNS-активность, тестируют прямой и WireGuard-пути,
поддерживают группу `AdaptiveAuto`. `vward-route-engine.sh` наблюдает DNS-трафик,
`vward-route-reconciler.sh` перепроверяет ранее адаптированные домены.

### VWARD Policy Sync

Через `ndmc` читает активную конфигурацию Keenetic, проверяет цели маршрутизации,
сохраняет состояние и сверяет домены/подсети, направленные через выбранный туннель.
Внешние каталоги принимаются только после ограничения размера загрузки и preflight-
проверки архива: разрешены обычные файлы и каталоги с относительными безопасными
путями, а symlink, hardlink, специальные записи и выход через `..` отклоняются.

### VWARD Tunnel Guard

`vward-tunnel-health.sh` фиксирует здоровье туннеля. `vward-tunnel-guard.sh` использует
это состояние для защиты связи и при необходимости меняет состояние выбранного туннеля.

### VWARD WAN Guard

`vward-wan-guard.sh` выполняет ступенчатую диагностику и восстановление подключения
`ISP`/физического WAN. `vward-wan-recovery.sh` ограничен обновлением DHCP-клиента.

### VWARD Wi-Fi Client Guard

`vward-wifi-client-monitor.sh` читает только `show associations`, нормализует AP, RSSI,
скорость и uptime клиентов и сохраняет ограниченную историю в `/opt/var/lib/vward/wifi-client-guard`.
`vward-wifi-client-analyze.sh` считает переключения диапазонов и слабые 5 ГГц-сэмплы и
формирует рекомендацию без изменения конфигурации. `vward-wifi-client-control.sh`
принимает только allowlisted действия `bind-2g`, `bind-5g` и `auto`, валидирует MAC и
Bridge, создаёт backup, сохраняет Keenetic configuration и проверяет результат. В
0.2.0-dev.9 автоматическое применение и Console mutation для этого компонента отключены
до live read-only acceptance на целевом Keenetic.

### VWARD Runtime

Init-скрипты управляют crond, Adaptive Live, supervisor и веб-службой. Cron запускает
периодические задания и пишет временные результаты в `/tmp`.

### VWARD Console

lighttpd отдаёт `web/index.html`; `web/cgi-bin/api.cgi` собирает локальные статусы
через `jq`, RCI и runtime-файлы. API работает по allowlist и не выдаёт ключи VPN.

### VWARD Update Engine

Получает подписанный Ed25519 feed вместо изменяемого Git-дерева. Этапы: проверка
manifest, staging, target-specific backup, остановка принадлежащих VWARD процессов,
установка, health-check, commit либо rollback. `/opt/etc` и runtime data не входят
в allowlist целей пакета.

## Текущая зрелость

Runtime-компоненты и автоматическое обновление прошли приёмку на целевом
Keenetic/Entware. Переносимость на другие модели и автоматическое discovery всех
device-specific параметров остаются работой версии `0.x-dev`.
