# VWARD Discovery

`VWARD Discovery` - read-only слой обнаружения фактической сетевой топологии. Он входит
в `VWARD Runtime` и не является отдельным продуктом.

## Принцип

VWARD должна работать по цепочке:

`DISCOVER -> CLASSIFY -> VALIDATE -> SELECT BY ROLE -> ACT`

Компоненты не должны угадывать имена интерфейсов или использовать значения конкретной
установки как обязательные runtime-константы.

## Первый этап: WireGuard

`vward-discovery.sh wireguard` читает полный RCI inventory интерфейсов и выбирает
объекты по фактическому `type == "Wireguard"`, а не по имени `Wireguard0`,
`Wireguard1` или номеру интерфейса.

Для каждого найденного туннеля возвращаются:

- `rci_id` - фактический RCI ID;
- `description`;
- `index`;
- `address`;
- `link`, `connected`, `state`;
- `linux_if` - Linux-интерфейс, если его удалось однозначно сопоставить;
- `mapping` - способ сопоставления.

Linux-интерфейс сопоставляется по фактическому IPv4-адресу из RCI и `ip addr`.
Имя вида `nwgN` не конструируется из номера и не зашивается в код. Если безопасное
сопоставление невозможно, `linux_if` остаётся пустым.

## Выбор роли Tunnel Guard

`vward-discovery.sh tunnel-guard` не выбирает случайный туннель:

- 0 кандидатов -> `NOT_FOUND`;
- ровно 1 кандидат -> `READY`, `single-candidate`;
- несколько кандидатов -> `REQUIRES_SELECTION`;
- сохранённый `tunnel_guard_rci_id` существует -> `READY`, `configured`;
- сохранённый ID исчез -> `STALE_MAPPING`.

При `REQUIRES_SELECTION` и `STALE_MAPPING` управляющие компоненты должны работать
fail-safe и не выполнять mutation до валидного role mapping.

Конфигурация role mapping читается из `/opt/etc/vward/discovery.conf`.
VWARD Discovery сам не записывает этот файл и не меняет Keenetic.

Пример:

```text
tunnel_guard_rci_id=OfficeTunnel
```

## Интеграция Tunnel Guard health

В `0.2.0-beta.1` read-only health watcher уже использует роль `tunnel-guard` из
VWARD Discovery.

`wg-health-watch.sh`:

- не содержит фиксированного `WireguardN` для RCI;
- не содержит фиксированного `nwgN` для сетевых probe;
- получает `rci_id` и `linux_if` из discovery result;
- запрашивает RCI только по уже обнаруженному `rci_id`;
- выполняет network probe только через уже сопоставленный `linux_if`;
- связывает RCI cache с конкретным `RCI_ID`, чтобы не использовать cache другого туннеля;
- сохраняет discovery state и фактические IDs в health state для дальнейшей интеграции.

Если mapping неоднозначен, устарел, discovery недоступен или Linux interface не
сопоставлен, health state становится `UNKNOWN`. В таком состоянии watcher не делает
пробных запросов к предполагаемым интерфейсам и не выполняет mutation.

`wg-failopen-guard.sh` на этом этапе ещё не переведён на новый role contract и не
изменялся. Это намеренное разделение read-only наблюдения и high-risk mutation.

## Интеграция VWARD Console

В `0.2.0-beta.1` Console API также использует общий `VWARD Discovery` для WireGuard
inventory. `api.cgi` больше не выполняет отдельный полный `show/interface` и не
фильтрует интерфейсы по шаблону `WireguardN`.

Для совместимости с текущим frontend API сохраняет поле `name`, но его значение
формируется только как alias фактического `rci_id`, возвращённого Discovery.
Дополнительно в `wg.discovery` публикуются `provider` и `state`.

Если `/opt/bin/vward-discovery.sh` отсутствует, не исполняется или возвращает
некорректный контракт, Console работает fail-safe: `wg.discovery.state` становится
`UNAVAILABLE`, а `wg.interfaces` остаётся пустым. API не переключается на угадывание
имён и не создаёт второй источник истины.

## Совместимость Keenetic/Entware

Production-логика не должна зависеть от regex-функций `jq`
`test()`, `match()` или `sub()`, потому что целевой Entware `jq` может быть собран
без ONIGURUMA.

Скрипт использует обычные JSON-операции `jq` и POSIX/BusyBox-совместимые `sh`/`awk`.

## Тестируемые инварианты

Repository tests проверяют:

- отсутствие WireGuard;
- произвольный RCI ID WireGuard, не содержащий `WireguardN`;
- один туннель;
- несколько туннелей;
- явный role mapping;
- stale mapping;
- сопоставление Linux interface по адресу;
- healthy Tunnel Guard через произвольные `rci_id` и `linux_if`;
- отсутствие probe/RCI query при `REQUIRES_SELECTION` и `STALE_MAPPING`;
- read-only характер health watcher;
- Console использует `/opt/bin/vward-discovery.sh` как единственный WireGuard inventory provider;
- Console не содержит собственного `WireguardN`/`nwgN` hardcode;
- compatibility alias `name` в Console строится из discovered `rci_id`;
- отсутствие installation-specific `WireguardN`, `nwgN`, LAN subnet и policy-list ID
  в discovery provider;
- отсутствие зависимости от jq regex.

## Следующие этапы

1. Добавить динамическое обнаружение WAN/uplink и role selection.
2. После отдельного тестирования перевести `wg-failopen-guard.sh` на фактические
   Tunnel/WAN role IDs.
3. Затем переводить Policy Sync и Route Engine на общий role mapping.
4. После стабилизации discovery перейти к due-based/idle-aware Maintenance Coordinator.