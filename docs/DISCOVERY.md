# VWARD Discovery

`VWARD Discovery` - read-only слой обнаружения фактической сетевой топологии. Он входит в `VWARD Runtime` и не является отдельным продуктом.

## Принцип

VWARD работает по цепочке:

`DISCOVER -> CLASSIFY -> VALIDATE -> SELECT BY ROLE -> PLAN -> GATE -> ACT -> VERIFY`

Компоненты не должны угадывать имена интерфейсов или использовать значения конкретной установки как обязательные runtime-константы.

## Сопоставление RCI и Linux

Для RCI-интерфейса Discovery сначала запрашивает штатное системное имя Keenetic через `show/interface/system-name?name=<RCI_ID>`. Если оно недоступно, допускается read-only fallback по фактическому IPv4-адресу из RCI и `ip addr`.

Имена вида `nwgN`, `ethN` и номера интерфейсов не конструируются из RCI ID. Если однозначное сопоставление невозможно, `linux_if` остаётся пустым и `mapping` получает значение `unresolved`.

## WireGuard inventory и роль Tunnel Guard

`vward-discovery.sh wireguard` читает полный RCI inventory и выбирает объекты по фактическому `type == "Wireguard"`, а не по имени `Wireguard0`, `Wireguard1` или номеру интерфейса.

`vward-discovery.sh tunnel-guard` использует fail-safe selection:
- 0 кандидатов -> `NOT_FOUND`;
- 1 кандидат -> `READY`, `single-candidate`;
- несколько кандидатов -> `REQUIRES_SELECTION`;
- сохранённый `tunnel_guard_rci_id` существует -> `READY`, `configured`;
- сохранённый ID исчез -> `STALE_MAPPING`.

Role mapping читается из `/opt/etc/vward/discovery.conf`. Discovery сам этот файл не изменяет.

## WAN inventory и роль WAN Guard

`vward-discovery.sh wan` строит список internet uplink по фактическим свойствам RCI, а не по имени `ISP` или Linux-интерфейсу.

Автоматическим WAN-кандидатом является интерфейс, у которого одновременно:
- `global == true`;
- `defaultgw == true`;
- `security-level == public`;
- роль `misc` отсутствует.

VPN с default route не должен становиться целью WAN Guard только из-за наличия default route.

Для WAN возвращаются фактические `rci_id`, `linux_if`, mapping, type, role, address, state, `defaultgw`, priority и security level. Для PPPoE и других логических подключений дополнительно сохраняются `via_rci_id`, `via_linux_if` и `via_mapping`.

`vward-discovery.sh wan-guard` поддерживает:
- `NOT_FOUND`;
- `READY`;
- `REQUIRES_SELECTION`;
- `STALE_MAPPING`;
- `INVALID_MAPPING`.

Явно выбранный WAN остаётся выбранным при временной потере `defaultgw`, чтобы recovery диагностировала назначенный uplink, а не самовольно переключалась на другой.

## Unified snapshot

`vward-discovery.sh snapshot` выполняет один discovery-проход и возвращает:
- `wireguard.interfaces`;
- `wan.interfaces`;
- `roles.tunnel_guard`;
- `roles.wan_guard`.

VWARD Console использует один snapshot на status request, что уменьшает повторные RCI/system-name обращения и сохраняет единый источник истины.

## Tunnel Guard health

В Beta `wg-health-watch.sh` использует роль `tunnel-guard` из VWARD Discovery. Он получает реальные `rci_id` и `linux_if`; при ambiguity, stale mapping или unresolved Linux mapping health становится `UNKNOWN` без guessed probes и mutation.

`wg-failopen-guard.sh` пока остаётся следующим high-risk этапом Zero-Hardcode refactor.

## WAN Guard health

`wan-health-watch.sh` - отдельный read-only observer. Он использует только discovered роль `wan-guard`, различает logical `PATH_IF` и physical `PHYSICAL_IF`, а probes привязывает к фактическому выбранному path.

Глобальный Keenetic Internet status используется только как дополнительный диагностический сигнал. Он не может самостоятельно сделать выбранный WAN `HEALTHY`, поэтому другой рабочий uplink не маскирует отказ наблюдаемой роли.

При `REQUIRES_SELECTION`, `STALE_MAPPING`, `INVALID_MAPPING`, unresolved Linux mapping или physical carrier down observer работает fail-safe и не запускает guessed/unbound probes.

State атомарно записывается в `/opt/var/lib/wan-health/state`, журнал - `/opt/var/log/wan-health.log`.

## WAN capability и recovery pipeline

Подробный authoritative контракт находится в `docs/WAN_RECOVERY_PIPELINE.md`.

Текущая Beta-цепочка:

`Discovery -> Observer -> Capability -> Planner -> Controller -> Actuator -> Observer post-check`

`wan-capability.sh` является read-only Capability Provider. Он повторно подтверждает текущую роль `wan-guard`, читает `show running-config`, но не публикует сам конфиг. DHCP считается подтверждённым только при фактическом `ip address dhcp` в блоке выбранного интерфейса. Тип Ethernet сам по себе не является доказательством DHCP.

`wan-recovery-plan.sh` остаётся `dryrun` и всегда возвращает `EXECUTED=NO`. Он требует свежий observer state, повторную проверку WAN role/mapping и заданное число подтверждённых ошибок.

Допустимые планы:
- logical/session failure -> `SESSION_RECONNECT`;
- confirmed physical path failure -> `INTERFACE_RECONNECT`;
- physical `ADDRESS_FAILURE` + подтверждённый DHCP -> `DHCP_RENEW`.

Static/unknown capability, DNS-only failure, physical carrier down, ambiguity, stale/mismatch и недостаточное число подтверждений не дают права на mutation.

`wan-recovery-controller.sh` является единственным Execution Gate. Default `VWARD_WAN_RECOVERY_EXECUTION_ENABLED=0`, Controller не включён в cron. При default-off он только валидирует Planner -> Actuator handoff и не пишет recovery state.

Если execution явно включён, Controller перед Actuator блокирует конфликт с Update Engine, legacy WAN recovery и Tunnel Guard mutation, применяет cooldown/rate-limit, резервирует attempt в persistent state и пишет audit record.

`wan-recovery-actuator.sh` содержит exact operations, но live path требует одновременно execution enable и внутренний Controller authorization. Actuator повторно валидирует роль/mapping и, для DHCP, capability непосредственно перед mutation.

Exact operations используют только discovered RCI ID:
- `DHCP_RENEW` -> `interface <rci-id> ip dhcp client renew`;
- physical reconnect -> `interface <rci-id> down/up`;
- logical/session reconnect -> `down/up` логического RCI interface, а не physical `via`.

После успешной mutation Controller повторно запускает WAN Observer. Recovery становится `SUCCESS` только при свежем `UP/HEALTHY` для тех же RCI/Linux IDs; иначе результат остаётся `RECOVERY_UNCONFIRMED`.

Новый stack по-прежнему не является production path: execution на рабочем роутере не включён, Controller не стоит в cron, legacy `wan-guardian.sh` продолжает выполнять текущий recovery.

## Интеграция VWARD Console

Console API использует один `vward-discovery.sh snapshot`. CGI больше не поддерживает отдельный full interface inventory, не фильтрует `WireguardN` и не запрашивает WAN через `show/interface?name=ISP`.

Для WireGuard compatibility-поле `name` остаётся alias фактического `rci_id`. WAN API публикует discovery state и фактические RCI/Linux IDs.

`wan.status` и `wan.class` приходят из `/opt/var/lib/wan-health/state`. Stale observer state, другой RCI/Linux mapping или текущий не-READY `wan-guard` переводят отображаемое состояние в `UNKNOWN`.

Legacy recovery telemetry пока явно маркируется `recovery_source=legacy-wan-guardian`. Frontend определяет здоровье WAN по `wan.status`, а не по глобальному `internet=true`.

## Совместимость Keenetic/Entware

Production-логика не должна зависеть от regex-функций `jq` `test()`, `match()` или `sub()`, потому что целевой Entware `jq` может быть собран без ONIGURUMA.

Скрипты должны оставаться POSIX/BusyBox-совместимыми. Desktop Linux acceptance сам по себе не заменяет проверку целевого Keenetic runtime.

## Тестируемые инварианты

Repository tests покрывают:
- 0/1/N WireGuard и произвольные RCI IDs;
- explicit/stale role mapping;
- RCI -> Linux mapping;
- WAN Ethernet/PPPoE и `via`;
- несколько uplink и исключение VPN `misc`;
- observer selected-path isolation;
- DHCP/static/logical capability без утечки running-config credentials;
- Planner typed actions;
- Actuator default-off и Controller authorization;
- exact mock recovery operations;
- TOCTOU смены WAN role и DHCP capability;
- Controller lock, cooldown, rate-limit и mutating-component conflict;
- persistent recovery state/audit;
- post-check success/failure и target matching;
- отсутствие `ISP`, `eth3`, guessed WireGuard IDs и jq ONIGURUMA-зависимости в новом Discovery-driven path.

## Следующие этапы

1. Выполнить read-only preflight нового gated WAN recovery stack на целевом Keenetic.
2. Провести одну контролируемую live mutation с немедленным post-check и планом отката.
3. Только после live acceptance решать вопрос о замене legacy `wan-guardian.sh` и scheduling Controller.
4. Затем перевести `wg-failopen-guard.sh` на Tunnel/WAN roles.
5. После этого переводить Policy Sync и Route Engine на общий role contract.
6. Затем переходить к due-based/idle-aware Maintenance Coordinator.
