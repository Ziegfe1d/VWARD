# План разработки VWARD 0.2.0-dev

## 1. Device discovery и профиль

- определить LAN address и subnet, физический WAN, RCI WireGuard-интерфейсы,
  системные имена туннелей и локальные policy groups;
- хранить подтверждённые значения в локальном profile, не включаемом в update payload;
- сохранить текущие значения как совместимый fallback для KN-1913;
- добавить read-only диагностику discovery до любых runtime-изменений.

## 2. Удаление жёстких привязок

- заменить `eth3`, `192.168.1.1`, `192.168.1.0/24`, `Wireguard1`, `nwg1` и
  `domain-list22` значениями профиля;
- менять компоненты по одному с отдельными тестами, health-check и rollback;
- не менять одновременно Route Engine, Tunnel Guard и Policy Sync.

## 3. Единая компонентная модель

- завершить переход от legacy display names к каноническим именам VWARD;
- подготовить совместимые source/runtime migrations с aliases или wrappers;
- сохранить чтение старых manifests и state до завершения downgrade window.

## 4. VWARD Console

- завершить обработчики, действия и корректные disabled states;
- подключить discovery/profile и фактические каталоги маршрутизации;
- унифицировать карточки, журналы, настройки и диагностику без новых лишних разделов;
- после функциональной готовности выполнить финальную адаптивную полировку.

## Контрольные ворота

Каждый проход: repository consistency, POSIX/BusyBox syntax, updater simulations,
security review, package ownership, upgrade/downgrade и rollback. Рабочий Beta-роутер
не используется как среда для незавершённого Dev-кода.
