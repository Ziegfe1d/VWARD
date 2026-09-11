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

`DISCOVER -> CLASSIFY -> VALIDATE -> SELECT BY ROLE -> PLAN -> ACT`

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

WAN Guard разделён на независимые слои обнаружения, наблюдения, capability,
планирования, validation и будущего выполнения recovery.

`VWARD Discovery` определяет WAN/uplink по фактическим свойствам RCI и роль
`wan-guard`. VPN-role `misc` исключается из WAN target. Для PPPoE и других логических
подключений сохраняются logical uplink и нижележащий `via` interface.

`wan-health-watch.sh` - read-only observer. Он получает только discovered роль,
привязывает network probes к фактическому `PATH_IF`, отдельно отслеживает физический
`PHYSICAL_IF` и атомарно пишет `/opt/var/lib/wan-health/state`. Для PPPoE path probe
идёт через логический интерфейс, а physical carrier проверяется через `via_linux_if`.

Глобальный Keenetic Internet status не может самостоятельно дать observer класс
`HEALTHY`: нужен успешный probe через выбранный WAN. При ambiguity, stale mapping,
unresolved Linux mapping или physical carrier down observer не делает guessed/unbound
probes. Observer не содержит `ndmc`, DHCP renew или interface down/up.

`wan-capability.sh` - отдельный read-only Capability Provider. Он повторно получает
текущую роль `wan-guard` и читает `show running-config`, но наружу возвращает только
нормализованные признаки capability. Для физического WAN DHCP считается доказанным
только при фактическом `ip address dhcp`; сам тип Ethernet не является достаточным
основанием. Содержимое running-config, логины и пароли в результат не публикуются.

`wan-recovery-plan.sh` - type-aware Recovery Planner в режиме `dryrun`.
Перед любым планом он требует свежий observer state, повторно читает текущую роль
`wan-guard`, сверяет `rci_id` и `linux_if` и ждёт заданное число подтверждённых
ошибок. Результат ограничен решениями `HOLD`, `DEFER`, `BLOCKED` и `PLAN`; фактическое
выполнение всегда `EXECUTED=NO`.

Planner различает logical session и physical path. Подтверждённый PPPoE/логический
session failure может дать план `SESSION_RECONNECT`, подтверждённый физический path
failure - `INTERFACE_RECONNECT`. Физический `ADDRESS_FAILURE` может дать
`DHCP_RENEW` только после положительной проверки Capability Provider. `PHY_DOWN`,
DNS-only failure, ambiguity, stale/mismatch, static/unknown addressing не разрешают
такой DHCP action.

`wan-recovery-actuator.sh` использует тот же Discovery/role contract и остаётся
`dryrun`. Он принимает только типизированные действия `SESSION_RECONNECT`,
`INTERFACE_RECONNECT` или `DHCP_RENEW` вместе с ожидаемыми RCI/Linux IDs, затем
самостоятельно повторяет `wan-guard` discovery. Для `DHCP_RENEW` он дополнительно
повторно вызывает Capability Provider. Любая смена роли, mapping или DHCP-capability
между PLAN и ACT приводит к `BLOCKED`.

Actuator не принимает shell-команду, не использует `eval`, не содержит legacy `ISP`
или заранее сформированных `ndmc` command strings. После успешной проверки он
возвращает только тип будущей RCI-операции и `EXECUTED=NO`.

`wan-recovery-controller.sh` - единая Execution Gate точка нового recovery stack.
Controller получает решение только от Planner, блокирует неподдерживаемые действия,
использует отдельный lock, вызывает Actuator только для валидного `PLAN` и требует,
чтобы Planner и Actuator оставались `dryrun` с `EXECUTED=NO`. Controller сам не
содержит network mutation и не запускается из cron.

Repository tests проверяют Observer/Capability/Planner/Controller/Actuator отдельно и
полную цепочку Planner -> Actuator, включая TOCTOU-защиту при смене WAN role и при
смене DHCP addressing между планированием и validation.

`wan-guardian.sh` остаётся отдельным legacy mutating recovery path с существующими
cooldown/rate-limit и installation-specific моделью. Новый recovery stack к нему
пока не подключён и реальные сетевые действия через Controller не разрешены.

Update Engine дополнен отдельным `vward-update-runtime-policy.sh`, который разрешает
установку новых WAN runtime targets и учитывает observer/controller locks при
quiescing. Это не меняет базовый updater contract и позволяет держать target policy
маленькой и проверяемой.

Подробный authoritative контракт нового WAN recovery stack описан в
`docs/WAN_RECOVERY_PIPELINE.md`.

Такое разделение позволяет принять discovery, observer, capability, decision и
validation layers раньше high-risk mutation и не выдавать dry-run готовность за уже
завершённую миграцию восстановления.

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
`recovery_source=legacy-wan-guardian`. Frontend определяет здоровье WAN по
`wan.status`, а не по глобальному Internet status. Новый Recovery Planner/Controller/
Actuator пока не являются управляющим источником Console и не инициируют действий.

### VWARD Update Engine

Получает подписанный Ed25519 feed вместо изменяемого Git-дерева. Этапы: проверка
manifest, staging, target-specific backup, остановка принадлежащих VWARD процессов,
установка, health-check, commit либо rollback. `/opt/etc` и runtime data не входят
в allowlist целей пакета.

Runtime target policy расширена отдельным post-hardening слоем, чтобы новые Discovery-
driven WAN файлы были installable и участвовали в quiescing без опасного массового
редактирования базовой updater library.

## Текущая зрелость

Runtime-компоненты и автоматическое обновление прошли приёмку на целевом
Keenetic/Entware. В Beta `0.2.x` выполняется Discovery First и Zero-Hardcode refactor.
WireGuard discovery, Tunnel Guard health, Console network topology, WAN role discovery,
WAN read-only observer, Capability Provider, Recovery Planner, dry-run Execution Gate и
Discovery-validated dry-run Actuator уже используют общий role contract. Переносимость
не считается завершённой, пока реальные WAN mutations, fail-open, Policy Sync и Route
Engine не используют тот же контракт.
