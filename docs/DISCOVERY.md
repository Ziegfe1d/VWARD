# VWARD Discovery

`VWARD Discovery` - read-only слой обнаружения фактической сетевой топологии. Он входит
в `VWARD Runtime` и не является отдельным продуктом.

## Принцип

VWARD должна работать по цепочке:

`DISCOVER -> CLASSIFY -> VALIDATE -> SELECT BY ROLE -> ACT`

Компоненты не должны угадывать имена интерфейсов или использовать значения конкретной
установки как обязательные runtime-константы.

## Сопоставление RCI и Linux

Для RCI-интерфейса Discovery сначала запрашивает штатное системное имя Keenetic через
`show/interface/system-name?name=<RCI_ID>`. Если оно недоступно, допускается read-only
fallback по фактическому IPv4-адресу из RCI и `ip addr`.

Имена вида `nwgN`, `ethN` и номера интерфейсов не конструируются из RCI ID. Если
однозначное сопоставление невозможно, `linux_if` остаётся пустым и `mapping` получает
значение `unresolved`.

## WireGuard inventory

`vward-discovery.sh wireguard` читает полный RCI inventory интерфейсов и выбирает
объекты по фактическому `type == "Wireguard"`, а не по имени `Wireguard0`,
`Wireguard1` или номеру интерфейса.

Для каждого найденного туннеля возвращаются `rci_id`, `linux_if`, `mapping`,
`description`, `index`, `address`, `link`, `connected` и `state`.

## Выбор роли Tunnel Guard

`vward-discovery.sh tunnel-guard` не выбирает случайный туннель:

- 0 кандидатов -> `NOT_FOUND`;
- ровно 1 кандидат -> `READY`, `single-candidate`;
- несколько кандидатов -> `REQUIRES_SELECTION`;
- сохранённый `tunnel_guard_rci_id` существует -> `READY`, `configured`;
- сохранённый ID исчез -> `STALE_MAPPING`.

Конфигурация role mapping читается из `/opt/etc/vward/discovery.conf`.
VWARD Discovery сам не записывает этот файл и не меняет Keenetic.

Пример:

```text
tunnel_guard_rci_id=OfficeTunnel
```

## WAN/uplink inventory

`vward-discovery.sh wan` строит read-only список интернет-uplink по фактическим
свойствам RCI, а не по имени `ISP` или Linux-интерфейсу.

Автоматическим WAN-кандидатом считается интерфейс, у которого одновременно:

- `global == true`;
- `defaultgw == true`;
- `security-level == public`;
- роль `misc` отсутствует.

Последнее правило принципиально: VPN-туннель с default route не должен становиться
целью WAN Guard. Оно применяется и к автоматическому выбору, и к явному mapping.

Для WAN возвращаются `rci_id`, `interface_name`, `linux_if`, `mapping`, тип,
роль, адрес, состояние, `defaultgw`, `priority` и `security_level`.

Для логических подключений, например PPPoE, дополнительно сохраняются `via_rci_id`,
`via_linux_if` и `via_mapping`. Это позволяет отличать логический uplink от нижнего
физического интерфейса и в дальнейшем выбирать recovery по типу подключения.

## Выбор роли WAN Guard

`vward-discovery.sh wan-guard` использует тот же fail-safe подход:

- 0 кандидатов -> `NOT_FOUND`;
- ровно 1 кандидат -> `READY`, `single-candidate`;
- несколько кандидатов -> `REQUIRES_SELECTION`;
- `wan_guard_rci_id` существует и является допустимым public/global uplink без роли
  `misc` -> `READY`, `configured`;
- сохранённый ID исчез -> `STALE_MAPPING`;
- сохранённый ID существует, но не является допустимым WAN target -> `INVALID_MAPPING`.

Явно выбранный WAN остаётся выбранным, даже если временно теряет `defaultgw`. Это нужно,
чтобы будущая recovery-логика могла диагностировать именно назначенный uplink во время
его отказа, не переключаясь самовольно на другой маршрут.

Пример:

```text
wan_guard_rci_id=GigabitEthernet1
```

На текущем этапе WAN discovery только читает данные. `wan-guardian.sh` и его recovery
commands ещё не переведены на этот role contract и не изменяются автоматически.

## Unified snapshot

`vward-discovery.sh snapshot` выполняет один discovery-проход и возвращает единый
machine-readable объект:

- `wireguard.interfaces`;
- `wan.interfaces`;
- `roles.tunnel_guard`;
- `roles.wan_guard`.

Snapshot нужен потребителям, которым одновременно требуются несколько частей topology.
В частности VWARD Console использует один snapshot на status request, а не запускает
отдельный полный RCI inventory для WireGuard и WAN. Это уменьшает число RCI/system-name
обращений и сохраняет один источник истины.

## Интеграция Tunnel Guard health

В `0.2.0-beta.1` read-only health watcher использует роль `tunnel-guard` из VWARD
Discovery.

`wg-health-watch.sh`:

- не содержит фиксированного `WireguardN` для RCI;
- не содержит фиксированного `nwgN` для network probe;
- получает `rci_id` и `linux_if` из discovery result;
- запрашивает RCI только по уже обнаруженному `rci_id`;
- выполняет network probe только через уже сопоставленный `linux_if`;
- связывает RCI cache с конкретным `RCI_ID`;
- сохраняет discovery state и фактические IDs в health state.

Если mapping неоднозначен, устарел, discovery недоступен или Linux interface не
сопоставлен, health state становится `UNKNOWN`. В таком состоянии watcher не делает
пробных запросов к предполагаемым интерфейсам и не выполняет mutation.

`wg-failopen-guard.sh` пока не переведён на новый role contract. Это намеренное
разделение read-only наблюдения и high-risk mutation.

## Интеграция VWARD Console

Console API использует общий `VWARD Discovery` через один вызов `snapshot`.
`api.cgi` больше не выполняет отдельный полный `show/interface`, не фильтрует
`WireguardN` и не запрашивает WAN через `show/interface?name=ISP`.

Для WireGuard compatibility-поле `name` сохранено как alias фактического `rci_id`.
В `wg.discovery` публикуются provider и state.

WAN выбирается через `roles.wan_guard`. API публикует `wan.discovery.state/selection`,
фактические `rci_id`, `linux_if`, `via_rci_id`, `via_linux_if` и тип uplink.
Если role mapping неоднозначен или недействителен, Console не угадывает `ISP`/`ethN`.

Поля `wan.class`, `wan.action` и recovery counters пока приходят из legacy
`wan-guardian.sh` и явно отмечены `observer_source=legacy-wan-guardian`. Это позволяет
перевести topology read-only раньше high-risk recovery mutations, не смешивая этапы.

Если `/opt/bin/vward-discovery.sh` отсутствует, не исполняется или возвращает
некорректный snapshot, Console работает fail-safe: общий `discovery.state=UNAVAILABLE`,
WireGuard inventory пуст, WAN role не подменяется guessed interface.

## Совместимость Keenetic/Entware

Production-логика не должна зависеть от regex-функций `jq` `test()`, `match()` или
`sub()`, потому что целевой Entware `jq` может быть собран без ONIGURUMA.

Скрипт использует обычные JSON-операции `jq` и POSIX/BusyBox-совместимые `sh`/`awk`.

## Тестируемые инварианты

Repository tests проверяют:

- 0/1/N WireGuard и произвольные RCI ID;
- explicit и stale Tunnel Guard mapping;
- системное Linux-имя с fallback по адресу;
- discovery-driven Tunnel Guard health без guessed probes;
- один WAN, несколько WAN и explicit WAN mapping;
- PPPoE `via` и нижележащий Linux-интерфейс;
- сохранение выбранной WAN-роли при временной потере `defaultgw`;
- `STALE_MAPPING` и `INVALID_MAPPING` для WAN;
- исключение VPN `misc` из WAN inventory и explicit mapping;
- Console выполняет ровно один Discovery snapshot на status request;
- Console не содержит собственного full interface inventory, `name=ISP` или
  installation-specific WireGuard hardcode;
- отсутствие installation-specific `WireguardN`, `nwgN`, LAN subnet и policy-list ID
  в самом discovery provider;
- отсутствие зависимости от jq regex.

## Следующие этапы

1. Разделить/перевести read-only диагностику WAN Guard на discovered role без recovery
   mutation.
2. После отдельного acceptance сделать type-aware WAN recovery и только затем убрать
   legacy `ISP`/`eth3` из mutating paths.
3. Перевести `wg-failopen-guard.sh` на фактические Tunnel/WAN role IDs.
4. Затем переводить Policy Sync и Route Engine на общий role mapping.
5. После стабилизации discovery перейти к due-based/idle-aware Maintenance Coordinator.