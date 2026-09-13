# Канонические имена VWARD 0.2

Ветка `dev` использует только целевую структуру VWARD Platform. Переходные source
каталоги, legacy component IDs, aliases и wrappers из Beta сюда не переносятся.

## Каноническая структура компонентов

| Source path | Component ID | Пользовательское имя |
|---|---|---|
| `components/route-engine/` | `route-engine` | VWARD Route Engine |
| `components/route-reconciler/` | `route-reconciler` | VWARD Route Reconciler |
| `components/route-tools/` | `route-tools` | VWARD Route Tools |
| `components/tunnel-guard/` | `tunnel-guard` | VWARD Tunnel Guard |
| `components/wan-guard/` | `wan-guard` | VWARD WAN Guard |
| `components/policy-sync/` | `policy-sync` | VWARD Policy Sync |
| `components/runtime/` | `runtime` | VWARD Runtime |
| `components/update-engine/` | `update-engine` | VWARD Update Engine |
| `web/` | `console` | VWARD Console |

Каталог прежней адаптивной маршрутизации разделён между Route Engine, Route
Reconciler, Route Tools и Runtime по фактическому владельцу каждого файла.

## Следующий прямой проход

Runtime filenames, init names, cron entries, state paths и config keys будут
переименованы непосредственно в каноническую схему. Dev не обязан читать старые
Beta state или manifests. Рабочий роутер остаётся на Beta до отдельного завершённого
и протестированного выпуска новой линии.
