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

## Базовый принцип Discovery First

Сетевые компоненты VWARD постепенно переводятся на единый read-only слой
`VWARD Discovery` в составе `VWARD Runtime`.

Цепочка принятия решений:

`DISCOVER -> CLASSIFY -> VALIDATE -> SELECT BY ROLE -> ACT`

Компоненты не должны конструировать имена `WireguardN`, `nwgN`, `ethN` или другие
installation-specific идентификаторы. Если роль нельзя определить однозначно,
управляющая логика должна останавливаться до валидного mapping.

RCI ID сопоставляется с Linux-интерфейсом через штатный `system-name` Keenetic.
Fallback по фактическому IPv4-адресу используется только для read-only discovery,
если system-name недоступен.

## Компоненты

### VWARD Route Engine, Reconciler и Tools

Проверяют FQDN-группы Keenetic и DNS-активность, тестируют прямой и WireGuard-пути,
поддерживают группу `AdaptiveAuto`. `agh-adaptive-live.sh` наблюдает DNS-трафик,
`adaptive-auto-maint.sh` перепроверяет ранее адаптированные домены.

Эти компоненты пока не полностью переведены на общий role mapping и относятся к
следующим этапам Zero-Hardcode refactor.

### VWARD Policy Sync

Через `ndmc` читает активную конфигурацию Keenetic, проверяет цели маршрутизации,
сохраняет состояние и сверяет домены/подсети. В текущем legacy runtime ещё остаются
installation-specific tunnel targets; их перевод на общий role mapping выполняется
после Tunnel Guard и WAN.

### VWARD Tunnel Guard

`wg-health-watch.sh` фиксирует здоровье туннеля и в Beta использует роль
`tunnel-guard` из общего VWARD Discovery. Он получает фактические `rci_id` и
`linux_if`, а при неоднозначности возвращает `UNKNOWN` без mutation.

`wg-failopen-guard.sh` использует health state для защиты связи, но его high-risk
mutation-часть пока не переведена на общий role contract. Она изменяется только после
отдельного WAN/tunnel role acceptance.

### VWARD WAN Guard

VWARD Discovery уже умеет определять WAN/uplink по фактическим свойствам RCI и роль
`wan-guard`. VPN-role `misc` исключается из WAN target. Для PPPoE и других логических
подключений сохраняются сам logical uplink и нижележащий `via` interface.

Сам `wan-guardian.sh` пока выполняет диагностику и восстановление через legacy WAN
модель. Его read-only observer и recovery actuator будут переводиться отдельно, чтобы
не смешивать обнаружение с сетевыми mutation. `wan-recovery-actuator.sh` пока остаётся
в текущем безопасном объёме.

### VWARD Runtime

Init-скрипты управляют crond, Adaptive Live, supervisor и веб-службой. Cron запускает
периодические задания и пишет временные результаты в `/tmp`.

`vward-discovery.sh` является общим read-only provider фактической сетевой топологии.
В Beta он определяет WireGuard inventory, роль Tunnel Guard, WAN inventory и роль
WAN Guard без изменения конфигурации Keenetic.

### VWARD Console

lighttpd отдаёт `web/index.html`; `web/cgi-bin/api.cgi` собирает локальные статусы
через `jq`, RCI, VWARD Discovery и runtime-файлы. API работает по allowlist и не
выдаёт ключи VPN.

WireGuard inventory Console получает только из общего `vward-discovery.sh`. Собственная
логика полного `show/interface` и фильтрация `WireguardN` из Console удалены. При
недоступном Discovery API возвращает read-only состояние `UNAVAILABLE`, а не угадывает
имя интерфейса.

WAN-блок Console пока использует legacy RCI `ISP` и является следующим read-only
consumer для общего `wan-guard` contract.

### VWARD Update Engine

Получает подписанный Ed25519 feed вместо изменяемого Git-дерева. Этапы: проверка
manifest, staging, target-specific backup, остановка принадлежащих VWARD процессов,
установка, health-check, commit либо rollback. `/opt/etc` и runtime data не входят
в allowlist целей пакета.

## Текущая зрелость

Runtime-компоненты и автоматическое обновление прошли приёмку на целевом
Keenetic/Entware. В Beta `0.2.x` выполняется Discovery First и Zero-Hardcode refactor.
WireGuard discovery, Tunnel Guard health, Console WireGuard inventory и read-only WAN
role discovery уже переведены. Переносимость не считается завершённой, пока WAN
observer/recovery, fail-open, Policy Sync и Route Engine не используют общий role
mapping.