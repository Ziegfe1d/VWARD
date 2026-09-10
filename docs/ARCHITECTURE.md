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
поддерживают группу `AdaptiveAuto`. `agh-adaptive-live.sh` наблюдает DNS-трафик,
`adaptive-auto-maint.sh` перепроверяет ранее адаптированные домены.

### VWARD Policy Sync

Через `ndmc` читает активную конфигурацию Keenetic, проверяет цели маршрутизации,
сохраняет состояние и сверяет домены/подсети, направленные через `Wireguard1`.

### VWARD Tunnel Guard

`wg-health-watch.sh` фиксирует здоровье туннеля. `wg-failopen-guard.sh` использует
это состояние для защиты связи и при необходимости меняет состояние `Wireguard1`.

### VWARD WAN Guard

`wan-guardian.sh` выполняет ступенчатую диагностику и восстановление подключения
`ISP`/физического WAN. `wan-recovery-actuator.sh` ограничен обновлением DHCP-клиента.

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
