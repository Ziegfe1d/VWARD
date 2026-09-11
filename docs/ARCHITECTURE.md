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

`DISCOVER -> CLASSIFY -> VALIDATE -> SELECT BY ROLE -> PLAN -> GATE -> ACT -> VERIFY`

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

Новый WAN recovery stack разделён на:

`Discovery -> Observer -> Capability -> Planner -> Controller -> Actuator -> Observer post-check`

`VWARD Discovery` определяет WAN/uplink по фактическим свойствам RCI и роль
`wan-guard`. VPN-role `misc` исключается из WAN target. Для PPPoE и других логических
подключений сохраняются logical uplink и нижележащий `via` interface.

`wan-health-watch.sh` - read-only observer. Он привязывает network probes к
фактическому `PATH_IF`, отдельно отслеживает физический `PHYSICAL_IF` и атомарно пишет
`/opt/var/lib/wan-health/state`. Глобальный Internet status не может самостоятельно
дать класс `HEALTHY`.

`wan-capability.sh` - read-only Capability Provider. Он повторно получает роль
`wan-guard` и читает `show running-config`, но наружу возвращает только нормализованные
признаки capability. DHCP считается доказанным только при фактическом
`ip address dhcp`; тип Ethernet не является достаточным основанием. Содержимое
running-config и credentials не публикуются.

`wan-recovery-plan.sh` всегда остаётся `dryrun`. Он требует свежий observer state,
повторно проверяет роль/mapping, ждёт подтверждённое число ошибок и выдаёт только
`HOLD`, `DEFER`, `BLOCKED` или `PLAN`. Допустимые typed actions:
`SESSION_RECONNECT`, `INTERFACE_RECONNECT`, capability-gated `DHCP_RENEW`.

`wan-recovery-controller.sh` - единственный Execution Gate. По умолчанию
`VWARD_WAN_RECOVERY_EXECUTION_ENABLED=0`, поэтому никакая mutation нового stack не
выполняется. Controller не включён в cron.

При явном enable Controller до Actuator проверяет собственный lock, активность Update
Engine, legacy WAN recovery и Tunnel Guard mutation, затем применяет cooldown и
rate-limit. Каждая live attempt резервируется в persistent state и audit log до
Actuator call.

`wan-recovery-actuator.sh` - единственный новый слой с exact network operations.
Прямой live-вызов требует одновременно execution enable и внутренний Controller auth.
Actuator непосредственно перед действием повторно валидирует discovered WAN; для
DHCP дополнительно повторяет Capability Provider.

Exact operations используют только фактический RCI ID:

- `DHCP_RENEW` -> `interface <rci-id> ip dhcp client renew`;
- `INTERFACE_RECONNECT` -> `interface <rci-id> down`, затем `up`;
- `SESSION_RECONNECT` -> `down/up` логического RCI interface, а не physical `via`.

`ndmc` запускается с очищенным `LD_LIBRARY_PATH`. `eval`, произвольный command text,
installation-specific WAN name и `system configuration save` не используются. При
ошибке первого `up` Actuator делает один best-effort повтор `up`.

После `EXECUTED=YES` Controller повторно запускает WAN Observer. Recovery считается
`SUCCESS` только если свежий state показывает тот же RCI/Linux target и
`STATUS=UP`, `CLASS=HEALTHY`. Иначе факт mutation сохраняется, но результат остаётся
`RECOVERY_UNCONFIRMED`.

Policy defaults Controller: cooldown 300 секунд, окно 3600 секунд, максимум 3 попытки,
3 post-check с интервалом 3 секунды. Это изменяемые policy defaults, не свойства
конкретной установки.

`wan-guardian.sh` остаётся отдельным legacy mutating production path. Новый stack не
заменяет его автоматически и до live-приёмки не запускается по расписанию.

Update Engine допускает установку новых WAN runtime targets и учитывает controller
lock при quiescing. Controller в обратную сторону блокирует live mutation при
updater lock/barrier/request.

Authoritative контракт: `docs/WAN_RECOVERY_PIPELINE.md`.

### VWARD Runtime

Init-скрипты управляют crond, Adaptive Live, supervisor и веб-службой. Cron запускает
периодические задания и пишет временные результаты в `/tmp`.

`vward-discovery.sh` является общим read-only provider фактической сетевой топологии.
В Beta он определяет WireGuard inventory, роль Tunnel Guard, WAN inventory и роль
WAN Guard без изменения конфигурации Keenetic.

Команда `snapshot` собирает эти данные одним проходом и предназначена для потребителей,
которым нужны несколько частей topology одновременно. Это уменьшает повторные RCI и
system-name запросы.

### VWARD Console

lighttpd отдаёт `web/index.html`; `web/cgi-bin/api.cgi` собирает локальные статусы
через `jq`, RCI, VWARD Discovery и runtime-файлы. API работает по allowlist и не
выдаёт ключи VPN.

Console выполняет один `vward-discovery.sh snapshot` на status request. WireGuard и
WAN topology берутся из этого общего snapshot. Собственная логика полного
`show/interface`, фильтрация `WireguardN` и прямой `show/interface?name=ISP` удалены.

Для WAN API публикует discovery state и фактические RCI/Linux IDs. `wan.status` и
`wan.class` берутся из read-only `/opt/var/lib/wan-health/state`. State старше 180
секунд, состояние от другого `rci_id` или другой Linux-привязки, а также текущий
не-READY `wan-guard` role переводят Console в `UNKNOWN`.

Legacy recovery телеметрия остаётся отдельной: `wan.action`, recovery counters и
legacy class читаются из `wan-guardian.sh` и маркируются
`recovery_source=legacy-wan-guardian`. Новый gated recovery stack пока не является
production управляющим источником Console.

### VWARD Update Engine

Получает подписанный Ed25519 feed вместо изменяемого Git-дерева. Этапы: проверка
manifest, staging, target-specific backup, остановка принадлежащих VWARD процессов,
установка, health-check, commit либо rollback. `/opt/etc` и runtime data не входят
в allowlist целей пакета.

Runtime target policy расширена отдельным post-hardening слоем, чтобы новые Discovery-
driven WAN файлы были installable и участвовали в quiescing без массового изменения
базовой updater library.

## Текущая зрелость

В Beta `0.2.x` уже реализованы общий Discovery contract, WireGuard/Tunnel health,
Console network topology, WAN Observer, Capability Provider, Planner, gated Controller,
exact-operation Actuator и post-check logic. Код real WAN operations существует, но
execution default остаётся `0`, Controller не стоит в cron и live-приёмка на целевом
Keenetic ещё не выполнена.

Переносимость не считается завершённой, пока новый WAN stack не пройдёт live acceptance,
а fail-open, Policy Sync и Route Engine не используют тот же Zero-Hardcode role mapping.
