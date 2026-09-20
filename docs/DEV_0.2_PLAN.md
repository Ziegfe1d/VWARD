# План разработки VWARD 0.2.0-dev

Канонический порядок gates: [`MASTER_PLAN_0.2_TO_FINAL.md`](MASTER_PLAN_0.2_TO_FINAL.md).

## 1. Прямая канонизация структуры

- переименовать source-каталоги, component IDs и все внутренние ссылки без aliases,
  wrappers и переходных мостов;
- разделить прежний общий каталог адаптивной маршрутизации по владельцам компонентов;
- затем напрямую переименовать runtime-файлы, init, cron и state paths.

## 2. Прямая параметризация устройства

- определить LAN address и subnet, физический WAN, RCI WireGuard-интерфейсы,
  системные имена туннелей и локальные policy groups;
- передавать найденные значения компонентам через единую каноническую конфигурацию;
- не сохранять legacy fallback и имена Beta внутри Dev;
- проверять конфигурацию до запуска компонентов.

## 3. Удаление жёстких привязок

- [x] заменить фиксированные LAN, WAN, DNS, tunnel и policy group значениями
  единого Device Profile;
- менять компоненты по одному с отдельными тестами, health-check и rollback;
- не менять одновременно Route Engine, Tunnel Guard и Policy Sync.

## 4. Единая компонентная модель

- завершить переход от legacy display names к каноническим именам VWARD;
- использовать только канонические source/runtime names новой линии;
- не поддерживать чтение старых Dev manifests и state.

## 5. VWARD Console

- завершить обработчики, действия и корректные disabled states;
- подключить discovery/profile и фактические каталоги маршрутизации;
- унифицировать карточки, журналы, настройки и диагностику без новых лишних разделов;
- после функциональной готовности выполнить финальную адаптивную полировку.

## 6. VWARD Wi-Fi Client Guard

- [x] добавить канонический component ID, package ownership и updater allowlist;
- [x] заложить read-only мониторинг `show associations`, bounded history и анализ переключений;
- [x] заложить отдельный allowlisted control с backup, acceptance и rollback;
- [ ] провести read-only acceptance на KN-1913 без изменения Wi-Fi конфигурации;
- [x] добавить read-only карточку и список клиентов в Console;
- [x] подключить guarded ручное `2.4 / 5 / Auto` через Console; локальный control
  остаётся выключенным до hardware acceptance;
- [ ] автоматическое исправление оставить opt-in для конкретных устройств и включать
  только после отдельного регрессионного цикла.

## Контрольные ворота

Каждый проход: repository consistency, POSIX/BusyBox syntax, updater simulations,
security review, package ownership, upgrade/downgrade и rollback. Рабочий Beta-роутер
не используется как среда для незавершённого Dev-кода.
