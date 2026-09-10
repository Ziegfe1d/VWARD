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

При `REQUIRES_SELECTION` и `STALE_MAPPING` будущие управляющие компоненты должны
работать fail-safe и не выполнять mutation до валидного role mapping.

Конфигурация role mapping читается из `/opt/etc/vward/discovery.conf`.
На этом этапе VWARD Discovery не записывает этот файл и не меняет Keenetic.

Пример:

```text
tunnel_guard_rci_id=OfficeTunnel
```

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
- отсутствие installation-specific `WireguardN`, `nwgN`, LAN subnet и policy-list ID
  в самом discovery provider;
- отсутствие зависимости от jq regex.

## Следующие этапы

После отдельного acceptance этого read-only слоя:

1. перевести VWARD Console на общий discovery provider;
2. перевести read-only часть Tunnel Guard;
3. добавить динамическое обнаружение WAN/uplink;
4. только после тестов переводить fail-open mutations;
5. затем переводить Policy Sync и Route Engine на role mapping.
