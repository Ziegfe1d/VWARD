# Модель компонентов VWARD

VWARD Platform - один продукт с независимо обновляемыми логическими компонентами.
Component ID - стабильное машинное имя для signed manifests, package metadata,
state и API. Пользовательское имя берётся из component registry.

| ID | Каноническое имя | Ответственность |
|---|---|---|
| `platform-core` | VWARD Platform Core | Версия и общие metadata платформы |
| `route-engine` | VWARD Route Engine | Адаптивная маршрутизация по DNS |
| `route-reconciler` | VWARD Route Reconciler | Сверка DIRECT и очистка маршрутов |
| `route-tools` | VWARD Route Tools | Пробы, resolve, hints и разовые операции |
| `tunnel-guard` | VWARD Tunnel Guard | Здоровье WireGuard и fail-open |
| `wan-guard` | VWARD WAN Guard | Диагностика и ограниченное восстановление WAN |
| `policy-sync` | VWARD Policy Sync | Аудит и синхронизация VPN-политик |
| `runtime` | VWARD Runtime | Init, cron supervision и housekeeping |
| `console` | VWARD Console | Web UI, CGI API и lighttpd |
| `update-engine` | VWARD Update Engine | Подписанные транзакции и rollback |

Authoritative mapping: `config/components/component-registry.json`.

## Совместимость

- Runtime filenames, init names, cron commands и paths не меняются без миграции.
- `legacy_ids` принимаются для опубликованных manifests/state и migration tooling.
- Новые packages используют канонические IDs.
- Одна runtime-цель принадлежит ровно одному компоненту.
- Local config, state, logs, backups и secrets не являются update payload.
- `update-engine` обновляется slot installer, а не обычным package.

## Версии и выборочные обновления

Платформа хранит один SemVer в `VERSION`. Компонент наследует release, который
последним изменил его; неизменённый файл не переписывается ради номера версии.
Feed объявляет `affected_components`, а каждый файл package - matching component ID.
Backup, replace, health и rollback касаются только объявленных целей.

Update Engine требует точного совпадения component set в feed и package, проверяет
ownership, mode, уникальность source/target, зависимости, SHA-256 и отсутствие
необъявленных payload-файлов. Component state и platform committed state фиксируются
транзакционно.
