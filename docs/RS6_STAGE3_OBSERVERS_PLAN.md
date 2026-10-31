# RS-6 этап 3: реальные наблюдатели для теневого сравнения — план

Только анализ и план (HEAD кода `eece891`, PR #21). Код, исполнители, роутер, `dev`/`main`,
VERSION и feed не затронуты. Основа: `RS6_IDENTITY_SNAPSHOT_SHADOW.md` §3 (формат LEGACY).

## 1. Откуда каждый механизм берёт состояние и решает

| Механизм | Состояние (источник) | Решение | Право на изменение | Безопасно читать для LEGACY |
|---|---|---|---|---|
| route-engine (`is_manual_known`, `handle_adaptive`) | `$STATE_DIR/manual-domains.txt` (точное имя и `*.`-wildcard), `adaptive-domains.txt`, `adaptive-persist.txt`, `domain-lists.conf` (`watch.*`, `smartdns_guard`), общий кэш running-config; сам движок добавляет домены в `AdaptiveAuto` по **живым пробам** (curl) | manual-known ⇒ **не трогать** (skip); адаптивный домен ⇒ VPN-группа | пишет только в `AdaptiveAuto`; manual/чужие — нет | manual-domains (skip + wildcard-семантика), adaptive-domains/persist; **пробы и cooldown-state — нет** (живые/внутренние) |
| route-reconciler (`adaptive_names`, `classify_isp_vs_vpn`) | `AdaptiveAuto` в running-config (общий кэш), `force-vpn.conf` (wildcard), **пробы ISP vs VPN через curl/DNS** | какой домен остаётся в AdaptiveAuto (VPN) или уходит (ISP); `force_vpn_match` удерживает | пишет/удаляет только в `AdaptiveAuto` | состав AdaptiveAuto, `force-vpn.conf`; **результат проб — нельзя** (нужна сеть Keenetic) |
| «Сервисы» (`service_target`, `service_row`, `service_owned`) | `services/enabled.tsv`, `categories.tsv`, каталог (`SV_CAT`), `services/owned/GROUP`, `route-engine/domain-lists/GROUP`, running-config | целевой туннель: pin или категория; **не найдено ⇒ возвращает `vpn`** (= туннель профиля) | только группы с `service_owned` (приватный proof) | вся цепочка файлов — чистое чтение. Расхождение: `service_target` подменяет неизвестное на `vpn`, RS6 даёт unknown |
| tunnel-guard (`lists_best`, `lists_fallback`) | `vward-tunnel-quality.sh summary` (`/tmp/vward-tunnel-quality/samples`, RAM), `guard/lists-fallback` (`группа from to at`), `QUALITY_MAP`, режим MODE | при ≥2 сбоях списки переезжают на лучший живой туннель, возврат после серии успехов | перемещает **любые** списки через `helper domain-list` (кроме AdaptiveAuto/policy group) | `lists-fallback` (персистентно, главное: объясняет «настроено ≠ желаемо»), сводка quality — читаема, но это RAM и снимок во времени |
| policy-sync (`collect_vpn_domains`) | running-config (`route object-group … <туннель>` → группы → include), `excluded.categories`, `owned.dynamic.routes`, `owned.interface`, `smartdns.categories` | какие **IP-категории** маршрутизируются (ip route / CIDR) по доменам VPN-групп | собственные ip-маршруты (owned.*) | список доменов VPN-групп, excluded, owned.interface; **ip route/CIDR-план** — не FQDN, RS6 его не моделирует |

## 2. Что нормализуется в LEGACY (без вызова записи)

Новые читатели — чистое чтение файлов/кэша, **без source/eval и без запуска скриптов-демонов**
(как RS6 этап 1: извлечение логики, а не вызов).

- route-engine: `manual-domains.txt` → строки `route-engine DOMAIN - none - manual skip manual-list`;
  wildcard `*.x` разворачивается только на домены, уже присутствующие в снимке (иначе нет данных);
  adaptive-domains vs persist → расхождение «в памяти, но не сохранено» (`state`).
- reconciler: состав `AdaptiveAuto` из того же кэша → `CONFIGURED`; `force-vpn.conf` → `DESIRED VPN`
  (`BASIS state`); wildcard — как выше. Результат ISP/VPN-пробы → `unknown` (честно).
- services: ровно RS6 `intents S`, но **desired по логике `service_target`**, включая подмену
  `vpn` ← неизвестное (пометка `catalog-pin`, класс-расхождения `service-target-defaulted`);
  OWNERSHIP из `services/owned`.
- tunnel-guard: `lists-fallback` ⇒ строки по группе: `CONFIGURED` = `to`, `DESIRED` = `from`,
  `ACTION restore`, `BASIS guard-fallback` (легальное объяснение расхождения); сводка quality →
  интерфейс-уровневая строка (`DOMAIN -`) только если файл samples свежий (иначе unknown).
- policy-sync: домены VPN-групп → `observe cidr-plan`; CIDR/ip-route-состояние в LEGACY не входит
  (отдельное поле не вводим; заявление «IP-маршрут совпал» запрещено).

Открытый вопрос формата: LEGACY сейчас не имеет места для «группа» — нужна необязательная
колонка контекста? Решение: **не менять формат**; группа идёт в IDENTITY/REASON через ссылку на
REF, без новых полей. Новые BASIS (`service-target-defaulted`, `wildcard-unresolved`) — расширение
закрытого перечня + версия формата `legacy-v2` в строке `generation`.

## 3. Одно поколение для общего механизма и наблюдателей

1. Единый вход: **наблюдатель получает `OUTDIR` координатора**, не читает живые файлы заново.
   Расширить `vward_routing_consistent_read`: после успешной проверки отпечатков копировать
   входы наблюдателей (manual-domains, force-vpn.conf, lists-fallback, adaptive-domains,
   excluded.categories, owned.*) **в тот же отпечаток** (до/после) — они становятся частью `generation`.
2. Состояние в RAM (`quality samples`) входит в отпечаток как обычный файл; если читается
   только сводка за окно, окно фиксируется `now` координатора, а не вызывающего.
3. Наблюдатель пишет LEGACY **в OUTDIR последним перед `generation`-маркером** со строкой
   `generation G`; разные поколения ⇒ `generation-mismatch` ⇒ `unknown` (уже реализовано), а
   не расхождение. Если хотя бы один наблюдатель не смог (нечитаем, пусто там, где нужно) —
   его строки отсутствуют, а в выводе явная строка `MECH - … unknown legacy-state-unknown`;
   отсутствие строк не трактуется как «совпадение».
4. Окно между последним отпечатком и использованием остаётся (документировать, как в этапе 2).

## 4. План реализации

Файлы (все новые, не в package-map, не установлены):

- `components/runtime/lib/vward-routing-observe.sh` — `vward_routing_observe OUTDIR MECH`
  (`route-engine|route-reconciler|services|tunnel-guard|policy-sync`); одна публичная функция,
  загрузка инертна; выводит LEGACY-строки в stdout, ошибки → rc 2 без частичного вывода.
- Расширение `vward-routing-snapshot.sh`: список наблюдаемых входов в отпечаток (тот же формат,
  лимиты 256 записей/1 MiB), без новой логики записи.
- `tests/routing-readers/check-observe.py` — паритет с настоящими функциями (как RS6 этап 1) +
  отрицательные сценарии; подключение в `run-consistency-checks.sh` (sh + BusyBox).
- Документ-итог в `RS6_IDENTITY_SNAPSHOT_SHADOW.md` (добавить раздел) после реализации.

Ограничения ресурсов (не увеличивать существующие): ≤4096 строк/1 MiB на вход, ≤1024 домена,
≤256 записей каталога, wildcard разворачивается только по доменам снимка, ≤4096 строк LEGACY;
без фоновых процессов, сети, блокировок записи; время — постфактум-проверка координатора.

Критерии приёмки: (1) паритет с настоящими `is_manual_known`, `adaptive_names`, `service_target`,
`lists_best`, `collect_vpn_domains` на одном fixture; (2) перестановка строк и повтор — побайтово
одинаково; (3) изменение любого наблюдаемого файла между отпечатками ⇒ `unknown`, не расхождение;
(4) ни один вызов ndmc/curl/dig/ip/ipset/route-скриптов (ядовитые обёртки в PATH, как в `check-shadow.py`);
(5) wildcard/подмена `vpn`/`lists-fallback` дают документированные классы, не `review`-ложь;
(6) секреты/URL не проходят (закрытые токены); (7) shellcheck warning чист, sh+BusyBox PASS;
(8) полный CI один раз на конечном HEAD; (9) Панель, VERSION, feed, роутер не затронуты.

## 5. Что нельзя получить без реального Keenetic (не подменять успехом)

| Наблюдение | Почему | Что возвращаем |
|---|---|---|
| Результат ISP/VPN-проб reconciler/route-engine | живые curl/DNS с роутера | `unknown` (строки `legacy-state-unknown`) |
| Живое здоровье туннеля и DNS/AGH | RAM-сэмплы свежи только на устройстве; health в RS6 всегда unknown | unknown, `rs-health-unknown` |
| Реальный packet path клиента, ip route/CIDR policy-sync | ядро/ipset/fwmark | не моделируется; `PACKET_PATH unknown` |
| Поведение `service_target` на живом каталоге устройства, фактические маршруты `lists-fallback` после перезагрузки | зависит от установленного каталога и состояния | паритет-тест на fixture; на Viva — только после разрешённой read-only диагностики |
| Wildcard Keenetic/CNAME-семантика | нет в running-config как доменов | `wildcard-unresolved`, без догадок |
| Стоимость на MIPS, flash wear | нужен замер на Viva | остаётся открытым |

## 6. Риски

R1 расхождение копии логики и боевых функций (дрейф) — смягчается паритет-тестами на каждом PR
в затронутые скрипты; R2 RAM-состояние quality меняется между проверками — отпечаток ловит,
результат `unknown`; R3 расширение отпечатка увеличивает время (три чтения + больше файлов) —
мерить, лимиты не повышать; R4 wildcard-разворачивание даёт ложные совпадения — только по доменам
снимка, остальное unknown; R5 `lists-fallback` может устареть относительно кэша — проверка, что
группа и `to` реально в running-config, иначе `legacy-unknown`.

Следующий исполнитель: Claude Code или Codex — по очереди через GitHub; перед реализацией
независимый аудит этапа 2 (Codex) и отдельное подтверждение владельца на объём этапа 3.
