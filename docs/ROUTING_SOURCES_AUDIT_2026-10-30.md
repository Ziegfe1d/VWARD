# Источники маршрутизации VWARD: аудит и варианты решения

Дата: 2026-10-30, МСК. Автор: [Агент]. Пакет RS-AUDIT, продолжение ROADMAP 4.3d.
**Статус: статический аудит выполнен; варианты предложены, архитектура не согласована, продуктовый код не изменён.**

## 1. Основание и предел доказательств

- План: [PR #10](https://github.com/Ziegfe1d/VWARD/pull/10), HEAD `93644437eb6f6fe73e207262b671fc40b76752f9`; прочитаны docs/AGENT.md, docs/ROADMAP.md (4.3d), docs/ARCHITECTURE.md.
- Код: полный подготовленный стек P-7, [PR #9](https://github.com/Ziegfe1d/VWARD/pull/9), HEAD `5869f119f6f8c43f001d80c2d6d9da3c24daf9ec`, поверх PR #7 → #8. Это объект аудита, а не база новых продуктовых изменений.
- Общая база dev и P-7: `9e99cbb52ffb09bc5beb3fb30b648cf1c18c881f`; compare показывает 15 коммитов P-7. Блок service_adopt() отдельно сопоставлен с dev: текст совпадает.
- Отчёт находится в отдельной ветке от PR #10, без переносов продуктового кода P-7. PR #10 остаётся планом. Ничего не сливать.
- **Статически подтверждено** означает, что прослежены условия, вызовы, изменение состояния и обработка отказа в исходниках. Это не результат исполнения shell или Keenetic.
- Среда shell недоступна: exec-server не подключился. Функциональные регрессии, BusyBox ash, shellcheck, эмулятор, нагрузочные измерения в этой сессии **не запускались**. Для каждого дефекта ниже указан воспроизводящий сценарий будущего теста.
- Роутер недоступен. Текущий состав групп, фактический путь клиента, CPU/RAM/flash, IPv6/UDP и поведение FQDN на установленной прошивке не измерены.
- CI #752/run `41066075403` для P-7 проверяется отдельной существующей задачей в **18:23 МСК 30.10.2026**. При подготовке отчёта его итог не запрашивался. Долгие успешные проверки #750/#751 и прежние аудиты не повторялись.
- Данные старого аудита дублей 25.10 используются только как история. В журнале AGENT.md уже записана последующая ручная чистка: нельзя выдавать старые 28 групп и предложение удалить list1 за актуальную команду.

## 2. Как маршрутизация устроена сейчас

Единого решения для всех источников нет. Есть несколько принимающих решения контуров, частично использующих один writer. Общая блокировка отдельных операций не делает их одной логической транзакцией.

| Контур | Что читает и решает | Что меняет / где хранит состояние | Доказательство |
|---|---|---|---|
| Ручные списки Keenetic / Панель | FQDN-состав, текущий туннель, сохранённый маршрут и DNS | domain-list/list-domain меняют группу, маршрут и связанные DNS; снимки route=/doh=/agh= | [vward-console-config.sh:923–1022](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/console/scripts/vward-console-config.sh#L923-L1022) |
| «Сервисы» | Каталог, enabled.tsv, category pin, собственный pin | Создание, adoption, маршрутизация и удаление domain-listN; enabled.tsv из трёх колонок не хранит владение | [vward-console-config.sh:1034–1264](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/console/scripts/vward-console-config.sh#L1034-L1264) |
| services-refresh | Новый каталог и группы из enabled.tsv | Добавляет и удаляет include; сохраняет router config | [vward-console-config.sh:1267–1314](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/console/scripts/vward-console-config.sh#L1267-L1314) |
| Route Engine / Автоподбор | DNS-запросы, FQDN-снимок, Smart DNS, исключения, hints, пробы ISP/VPN | AdaptiveAuto, persist, per-domain AGH DNS-привязки; обход watch-групп может вызвать writer | [vward-route-engine.sh:1844–1939](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-engine/scripts/vward-route-engine.sh#L1844-L1939), [vward-route-engine.sh:1660–1814](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-engine/scripts/vward-route-engine.sh#L1660-L1814) |
| Route Reconciler | До 8 имён за проход, подтверждения доступности напрямую, tunnel health | Удаление из AdaptiveAuto, persist, hysteresis; отложенный save | [vward-route-reconciler.sh:24–46](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-reconciler/scripts/vward-route-reconciler.sh#L24-L46), [vward-route-reconciler.sh:435–592](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-reconciler/scripts/vward-route-reconciler.sh#L435-L592) |
| Policy Audit / Reconcile | Кандидаты, пробы, все группы на выбранном туннеле кроме AdaptiveAuto | Ночной reconcile удаляет memberships, имеет собственную проверку/откат | [vward-policy-reconcile.sh:346–374](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/policy-sync/scripts/vward-policy-reconcile.sh#L346-L374), [vward-policy-reconcile.sh:612–659](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/policy-sync/scripts/vward-policy-reconcile.sh#L612-L659) |
| Policy Sync | Домены маршрутизируемых групп → категории CIDR, Smart DNS exclusions | Динамические ip route; owned.dynamic.routes, owned.interface, last-good, shrink guard | [vward-policy-sync.sh:745–858](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/policy-sync/scripts/vward-policy-sync.sh#L745-L858), [vward-policy-sync.sh:975–1027](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/policy-sync/scripts/vward-policy-sync.sh#L975-L1027) |
| Tunnel Guard | Здоровье туннелей, fallback/return, потерянные модули | Вызовы helper domain-list/tunnel/tunnel-delete; собственные записи возврата | [vward-tunnel-guard.sh:174–278](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/tunnel-guard/scripts/vward-tunnel-guard.sh#L174-L278), [vward-tunnel-guard.sh:749–773](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/tunnel-guard/scripts/vward-tunnel-guard.sh#L749-L773) |
| Tunnel Quality / services() | enabled.tsv и pin=auto; доступные туннели; пробы сервиса | Перемещение сервисной группы через helper, state.tsv | [vward-tunnel-quality.sh:137–223](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/tunnel-guard/scripts/vward-tunnel-quality.sh#L137-L223) |
| AGH / Smart DNS control | API dns_info, условные upstream, точные пары домен/сервер | GET/POST с проверкой; API upstream_dns_file при мутации отклоняется | [vward-ads-privacy-control.sh:138–205](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/ads-privacy-guard/scripts/vward-ads-privacy-control.sh#L138-L205) |
| DNS guard | Цепочка Keenetic ↔ AGH, orphan/loop, ledger привязок | Снятие/возврат DNS/NAT, agh-bindings.txt, chain state | [vward-ads-privacy-dns-guard.sh:407–451](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/ads-privacy-guard/scripts/vward-ads-privacy-dns-guard.sh#L407-L451) |
| Route DNS | Маршрутизируемые группы и AGH API | Условные upstream AGH → Keenetic и клиент router; противоположное направление DNS | [vward-ads-privacy-route-dns.sh:117–168](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/ads-privacy-guard/scripts/vward-ads-privacy-route-dns.sh#L117-L168) |
| Ручной route-tool | Свой GROUP, пробы и счётчики | Прямые include/remove без общего writer в показанном блоке; вызываемость расписанием не доказана | [vward-route.sh:149–180](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-tools/scripts/vward-route.sh#L149-L180) |
| Глобальное «Отключить VWARD» | Снимок маршрутов/DNS, работающие службы | Отдельная аварийная процедура парковки/возврата; не эквивалент трём переключателям источников | [vward-off.sh:174–282](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/runtime/scripts/vward-off.sh#L174-L282) |
| Runtime / Sentinel / cron | Жизнь процессов, события интерфейсов/DNS, расписания | Перезапуски через агент компонентов; отдельные network/DNS действия сохраняются | [vward-sentinel-act.sh:61–107](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/runtime/scripts/vward-sentinel-act.sh#L61-L107), [root.crontab:1–10](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/config/cron/root.crontab#L1-L10) |

### Что уже защищено и должно сохраниться

1. Route Engine собирает **все** группы, кроме AdaptiveAuto, в MANUAL. Точное и родительское покрытие проверяются повторно перед добавлением. Поэтому тезис «Автоподбор всегда дублирует Сервисы» неверен: базовая дедупликация уже есть. Но признак MANUAL не отличает сервисную группу от пользовательской и не объясняет её маршрут. [vward-route-engine.sh:240–268](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-engine/scripts/vward-route-engine.sh#L240-L268), [vward-route-engine.sh:866–875](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-engine/scripts/vward-route-engine.sh#L866-L875).
2. Smart DNS имеет отдельный приоритет обхода VPN. agh_bind не строит обратную привязку при включённом Route DNS, сохраняя защиту от DNS-петли. [vward-route-engine.sh:1891–1907](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-engine/scripts/vward-route-engine.sh#L1891-L1907), [vward-route-engine.sh:1750–1758](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-engine/scripts/vward-route-engine.sh#L1750-L1758).
3. Падение VPN в reconciler не должно порождать массовое BROKEN; проверка состояния туннеля уже существует. [vward-route-reconciler.sh:510–571](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-reconciler/scripts/vward-route-reconciler.sh#L510-L571).
4. Кэш running-config уже есть, TTL по умолчанию 20 с, lock и dirty invalidation; классификатор уже резидентный, состояния обычных проб в /tmp. Создавать новый демон/кэш поверх них не обосновано. [vward-device-profile.sh:452–457](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/runtime/lib/vward-device-profile.sh#L452-L457), [vward-device-profile.sh:564–601](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/runtime/lib/vward-device-profile.sh#L564-L601), [vward-route-engine.sh:1271–1274](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-engine/scripts/vward-route-engine.sh#L1271-L1274).
5. Policy Sync различает owned и existing unmanaged CIDR; есть partial-config и shrink guards. Их нельзя обходить ради «единого применения». [vward-policy-sync.sh:815–852](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/policy-sync/scripts/vward-policy-sync.sh#L815-L852), [vward-policy-sync.sh:975–983](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/policy-sync/scripts/vward-policy-sync.sh#L975-L983).
6. P-7 уже сохраняет приватные пары восстановления Smart DNS при недоступном AGH API. Это не означает атомарности AGH и Keenetic или автоматического восстановления; новый пакет не должен переделывать уже проверявшуюся часть без новой причины.
7. Одновременные service-команды защищены edit_lock на входе. Гипотеза «два service on легко обходят друг друга» этим кодом не подтверждается. Runtime admission защищает обновление и учитывает активные операции; сам по себе он не является общей блокировкой всех изменений маршрутизации. [vward-console-config.sh:3641–3647](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/console/scripts/vward-console-config.sh#L3641-L3647), [vward-runtime-admission.sh:218–259](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/runtime/lib/vward-runtime-admission.sh#L218-L259).

## 3. Подтверждённые по исходникам проблемы

Ни один сценарий этой таблицы не объявлен воспроизведённым на устройстве или в shell этой сессии.

### RS-01. Подхват превращает чужую группу в управляемую без доказательства владения — высокий риск

Условие service_adopt(): достаточно одинакового нормализованного названия **или** 80% каталожных доменов. Проверки полного состава, текущего назначения VPN/ISP, пользовательского происхождения и права на мутацию нет. Уникальные пользовательские домены не мешают подхвату. Выбранная группа записывается в enabled.tsv, затем service_route меняет её маршрут и DNS.

service off вызывает bypass, снимает маршрут и выполняет `no object-group fqdn $G`. Проверяется наличие группы и результат удаления, а не право её удалить. services-refresh подгоняет состав той же группы под каталог. Автоматический выбор туннеля по enabled.tsv расширяет этот эффект на последующие фоновые проверки.

**Доказательства:** [vward-console-config.sh:1083–1102](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/console/scripts/vward-console-config.sh#L1083-L1102), [vward-console-config.sh:1198–1215](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/console/scripts/vward-console-config.sh#L1198-L1215), [vward-console-config.sh:1233–1241](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/console/scripts/vward-console-config.sh#L1233-L1241), [vward-console-config.sh:1303–1311](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/console/scripts/vward-console-config.sh#L1303-L1311), [vward-tunnel-quality.sh:157–205](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/tunnel-guard/scripts/vward-tunnel-quality.sh#L157-L205).

Существующий тест сам ожидает adoption и перепривязку группы из внешнего RUNNING; off/refresh после такого adoption на сохранность чужих данных не проверяет: [check-console-services.py:252–273](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/tests/repository/check-console-services.py#L252-L273).

**Сценарий регрессии:** пользовательская группа с названием сервиса, собственным ISP или другим VPN и дополнительным доменом → service on → off; отдельно → catalog refresh. Требование: байтово неизменны состав, описание, маршрут, DNS и saved state чужой группы; нет create/delete только ради отметки сервиса. Проверить и совпадение названия при нулевом совпадении доменов, 79/80/100%, несколько кандидатов, legacy enabled.tsv.

**Минимальная безопасная мера до новой архитектуры:** не считать эвристику доказательством владения; неизвестное происхождение — только чтение/объяснение. Не присваивать owned на основании имени, номера группы, enabled.tsv или повторной загрузки.

### RS-02. Записанная настройка сервиса опережает подтверждённый маршрут — средний риск

Для tunnel, повторного on и adoption service_state_set выполняется **до** service_route. При отказе helper функция завершается ошибкой, а новое состояние остаётся. Для category новый pin также записывается до перемещения всех сервисов, единой компенсации уже перемещённых групп нет.

**Доказательства:** [vward-console-config.sh:1191–1195](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/console/scripts/vward-console-config.sh#L1191-L1195), [vward-console-config.sh:1218–1241](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/console/scripts/vward-console-config.sh#L1218-L1241), [vward-console-config.sh:1157–1172](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/console/scripts/vward-console-config.sh#L1157-L1172). API services-data строит enabled по файлу, отдельно не подтверждает каждую физическую группу: [api.cgi:2487–2502](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/web/cgi-bin/api.cgi#L2487-L2502).

**Сценарий:** включённый сервис на T1; запрос T2; вложенный helper возвращает route_change_busy / router_rejected / AGH unavailable. Сравнить requested, enabled.tsv и реальную конфигурацию до/после. Для категории — сбой на втором сервисе. Проверить результат и после рестарта.

**Критерий:** подтверждённое состояние не сообщает применение T2; незавершённое намерение отделено от факта; причина видна. Минимальное исправление порядка записи/компенсации не требует выбора общей архитектуры.

### RS-03. services-refresh не является транзакцией состава — высокий риск

Новый catalog.json устанавливается до изменений групп. В refresh JOURNAL используется как имя временных файлов, но TXN=1 и undo-команды для include/remove не формируются. Ошибка после части команд или save не возвращает предыдущий состав; повторный refresh может довести его, но это не откат. Сначала добавляются все новые домены, затем удаляются старые, поэтому проверка размера **целевого** списка <=300 не гарантирует вместимость промежуточного.

**Доказательства:** [vward-console-config.sh:1291–1314](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/console/scripts/vward-console-config.sh#L1291-L1314), [vward-console-config.sh:106–114](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/console/scripts/vward-console-config.sh#L106-L114).

**Сценарии:** две группы, отказ на N-й add/remove/save; TERM после первого изменения; старая группа из 300 доменов, новый каталог тоже 300, из них один заменён. В последнем случае add-first упирается в лимит, хотя конечный набор допустим. Для foreign/reference группы refresh вообще не должен начинать запись (RS-01).

**Критерий:** preflight дельты и ёмкости, backup, проверка результата и видимый неполный откат; сохранение recovery при неуспехе. Не решать лимит удалением чужих доменов и не ослаблять проверку 300.

### RS-04. Ошибка свежего чтения может стать «домен уже удалён» — высокий риск

adaptive_names берёт конфигурацию и передаёт её через printf/sed/awk/sort без отдельного возврата ошибки чтения. В ветке после отказа удаления `! adaptive_names fresh | grep -Fxq "$H"` пустой вывод вследствие отказа RCI/ndmc неотличим от подтверждённого отсутствия. Тогда PTMP перемещается в PERSIST, пишется DIRECT_OK/already_gone. При следующем restore отсутствие в persist может стать основанием снять членство.

**Доказательства:** [vward-route-reconciler.sh:78–94](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-reconciler/scripts/vward-route-reconciler.sh#L78-L94), [vward-route-reconciler.sh:493–499](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-reconciler/scripts/vward-route-reconciler.sh#L493-L499), [vward-route-engine.sh:740–777](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-engine/scripts/vward-route-engine.sh#L740-L777).

**Сценарий:** имя есть в router и persist; первая выборка успешна, удаление отказано, оба способа свежего чтения не отвечают. Ожидание: persist и hysteresis не теряются, нет DIRECT_OK/already_gone. Отдельно успешное подтверждение отсутствия должно продолжать работать.

**Критерий:** три результата present / absent / unknown, как уже сделано в membership_state ночного reconcile: [vward-policy-reconcile.sh:156–178](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/policy-sync/scripts/vward-policy-reconcile.sh#L156-L178). Это независимый точечный fix, без изменения сроков Автоподбора.

### RS-05. DNS guard забывает владение правилами, которые мог не снять — высокий риск

agh_unbind считает успешные удаления, но затем безусловно удаляет весь agh-bindings.txt; ext/failed тоже исчезают. ns_release исключает из ledger все строки данного NS независимо от успеха каждой команды снятия. При отказе ndmc физическое правило может остаться без записи о происхождении. После восстановления agh_bind_one увидит его как существующее внешнее и запишет ext.

**Доказательства:** [vward-ads-privacy-dns-guard.sh:407–416](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/ads-privacy-guard/scripts/vward-ads-privacy-dns-guard.sh#L407-L416), [vward-ads-privacy-dns-guard.sh:435–449](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/ads-privacy-guard/scripts/vward-ads-privacy-dns-guard.sh#L435-L449), [vward-route-engine.sh:1784–1789](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-engine/scripts/vward-route-engine.sh#L1784-L1789).

**Сценарий:** ledger содержит две owned и одну ext-привязку; одна команда удаления отказана; отдельно rc=0 с текстом ошибки, обрыв и ошибка записи ledger. Требование: неподтверждённые owned-записи остаются для диагностики/повторной сверки, ext не превращается в owned, ложного успеха нет. Сохранение цепочки DNS при fail-open проверяется отдельно.

**Минимальный fix:** атомарно фиксировать только подтверждённые результаты снятия, сохранять неудачные записи и причину. Сначала существующая DNS-guard fixture и регрессия; не запускать новые таймеры.

### RS-06. Другие автоматы также могут менять пользовательские списки — несовместимость с новой границей владения

Tunnel Guard перечисляет маршрутизируемые группы, исключая только AdaptiveAuto и policy group; остальные может переводить при отказе туннеля. lost_sweep передаёт туннель в bulk move по признакам наличия локального модуля/линка. Policy Reconcile выбирает все группы на выбранном туннеле, кроме AdaptiveAuto, затем удаляет memberships кандидатов. Это существующее поведение; оно не доказывает текущий инцидент, но без ограничения прав нарушит требование reference-only даже после исправления services.

**Доказательства:** [vward-tunnel-guard.sh:253–268](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/tunnel-guard/scripts/vward-tunnel-guard.sh#L253-L268), [vward-tunnel-guard.sh:749–770](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/tunnel-guard/scripts/vward-tunnel-guard.sh#L749-L770), [vward-policy-reconcile.sh:346–374](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/policy-sync/scripts/vward-policy-reconcile.sh#L346-L374), [vward-policy-reconcile.sh:612–628](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/policy-sync/scripts/vward-policy-reconcile.sh#L612-L628).

**Сценарий:** ручная группа на T1 без разрешения управления; отказ T1, появился T2; ночной кандидат доступен напрямую. Ни один автомат не вправе менять состав/назначение такой группы. Повторить с явно делегированным управлением и подтвердить действующий fallback/return.

**Вывод:** маркер ownership только в services недостаточен. Для автоматического изменения нужны и принадлежность ресурса, и отдельное право управлять его маршрутом. Старые пользовательские настройки не переопределять молча.

### RS-07. Два разных значения «выключен» и неполная наблюдаемость — подтверждённый пробел модели

adaptive.disabled по текущему контракту запрещает новые добавления, но сохраняет ранее созданное покрытие и обслуживание. MANUAL включает сервисные группы. services-data выдаёт зарегистрированные сервисы и результаты проб, но не единую сводку прав, независимых источников, конфликтов и уникального покрытия.

**Доказательства:** [vward-route-engine.sh:25–45](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-engine/scripts/vward-route-engine.sh#L25-L45), [vward-route-engine.sh:852–856](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-engine/scripts/vward-route-engine.sh#L852-L856), [vward-route-engine.sh:1893–1908](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-engine/scripts/vward-route-engine.sh#L1893-L1908), [api.cgi:2471–2502](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/web/cgi-bin/api.cgi#L2471-L2502).

Это не повод объявить старый выключатель сломанным: его прежняя семантика прямо записана. Новые три тумблера требуют миграции без потери истории и ясного различения «использование разрешено», «данные есть», «маршрут применён», «внешнее правило продолжает работать». При всех 000 нельзя показывать «весь трафик напрямую», если действуют чужие правила.

## 4. Дубли, конфликты и лишняя работа

### Причины и то, что пока не доказано

- Историческая причина дублей Сервисов уже зафиксирована: пропало enabled.tsv после переустановки, новый on выделил новый номер без поиска покрытия. Нынешний adoption уменьшает этот риск, но заменяет его RS-01. Повторять ручную чистку старых групп нельзя.
- Равные строки в каталогах не равны двум физическим маршрутам. Дедупликация должна сравнивать имя/семантику покрытия, действительное назначение и DNS-политику; общий CDN IP не доказывает эквивалентность доменов.
- Текущее раннее исключение MANUAL предотвращает часть дублей, однако не отвечает, полезно ли покрытие: группа может быть без маршрута или иметь другое назначение. Нельзя автоматически исправлять это переносом чужой группы.
- Smart DNS и FQDN VPN — разные плоскости: DNS может вернуть прокси, а CIDR/FQDN направить адрес в туннель. Policy Sync уже удерживает блоки вокруг адресов Smart DNS и сохраняет DNS-кэш при отсутствии нового ответа; это защита, которую нужно учитывать при объяснении конфликта, не удалять. [vward-policy-sync.sh:630–708](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/policy-sync/scripts/vward-policy-sync.sh#L630-L708).
- IPv4 TCP-проба не доказывает фактический путь IPv6, UDP/QUIC или клиента с Private DNS. Отсутствие A-записи не разрешает удаление домена или перенос CDN.
- Конкуренция контуров вероятна по разным locks и снимкам, но конкретный race здесь не воспроизведён. Нельзя «лечить» его ещё одним guard. Нужны детерминированные interleaving-тесты.

### Блокировки и фоновая работа

| Механизм | Фактическая область | Следствие |
|---|---|---|
| console edit_lock | service/service-category и ряд настроек; services-refresh не включён в этот case | Не утверждать отсутствие защиты service-команд; отдельно проверить refresh против редактирования состояния |
| /tmp/vward-route-change.lock | domain-list writer, Route Engine mutations, route-reconciler | Общая часть есть; разбитые service-операции отпускают её между шагами |
| policy-sync STATE/lock | CIDR-sync и координация с частью console tunnel move | Отличается от /tmp/vward-policy-sync.lock ночного audit/reconcile |
| DNS guard lock, AGH binding lock | Разные пути управления DNS | Снятие DNS и создание привязки нуждаются в общей проверке поколений/прав, а не в блокировке на весь сетевой timeout |
| runtime admission | Барьер обновления, реестр активных работ | Сохранять: он не даёт сериализацию всех routing-решений |
| cron + Sentinel + supervisor | Запуск по расписанию, события, живучесть процессов | Совпадение наблюдений не доказывает лишний работающий процесс; измерять реальные вызовы |

Основания: [vward-console-config.sh:248–259](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/console/scripts/vward-console-config.sh#L248-L259), [vward-console-config.sh:1238–1257](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/console/scripts/vward-console-config.sh#L1238-L1257), [vward-console-config.sh:3643–3647](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/console/scripts/vward-console-config.sh#L3643-L3647), [vward-policy-sync.sh:23–70](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/policy-sync/scripts/vward-policy-sync.sh#L23-L70), [vward-policy-reconcile.sh:30–67](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/policy-sync/scripts/vward-policy-reconcile.sh#L30-L67), [vward-route-engine.sh:1763–1768](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-engine/scripts/vward-route-engine.sh#L1763-L1768), [vward-ads-privacy-dns-guard.sh:859–878](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/ads-privacy-guard/scripts/vward-ads-privacy-dns-guard.sh#L859-L878).

Cron каждые 5 минут запускает reconciler; цепочки здоровья и watchdog — каждую минуту; ночью audit → sync → reconcile. Уже есть spread reconciler=35 с и Wi-Fi=15 с, кэш и defer: старый пик нельзя повторно выдавать за неисправленную причину. В Policy Sync остаётся цикл route_line/grep по маршрутам, а ночной membership_state читает свежий config на проверку; это ранее запланированный ROADMAP пункт t, а не новая находка. [root.crontab:1–10](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/config/cron/root.crontab#L1-L10), [vward-route-reconciler.sh:15–22](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/route-reconciler/scripts/vward-route-reconciler.sh#L15-L22), [vward-policy-sync.sh:807–834](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/policy-sync/scripts/vward-policy-sync.sh#L807-L834), [vward-policy-reconcile.sh:160–178](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/components/policy-sync/scripts/vward-policy-reconcile.sh#L160-L178).

**План измерения без нового демона:** существующие счётчики CPU/slow-RCI, число ndmc/RCI/DNS/save, процессы и время в эмуляторе, на одинаковом fixture и одинаковых холодном/тёплом кэшах. Порог отсутствия регрессии — действующий resource budget; сначала измерить baseline, не менять лимиты теста для прохождения. На Viva затем отдельное окно 24 ч, по критериям AGENT.md. Новых чисел CPU/RAM/flash этот отчёт не содержит.

## 5. Три архитектурных варианта

Оценки сравнительные, инженерные, не измеренные на устройстве.

| Вариант | Сложность и миграция | Надёжность/риски | CPU/RAM/flash | Совместимость |
|---|---|---|---|---|
| A. Только защитные проверки в нынешних контурах | Низкая для RS-01…05; по мере добавления источников растёт число проверок | Быстро снижает риск, но правила выбора и ownership могут расходиться между guard, services, nightly и engine | Почти исходная; дубли вычислений остаются | Минимальный риск отдельного fix; не завершает требование единого решения |
| **B. Общая библиотека решений + существующий writer и сверка** | Средняя, поэтапная; адаптеры трёх источников и ограниченный реестр прав/ссылок, без новой службы | Один результат resolve/plan, проверка права перед мутацией, повторная сверка; нужна доказанная миграция legacy | В /tmp общий индекс/снимок; постоянные записи только при изменении intent/ownership/undo; ожидается меньше повторных вызовов, подтвердить замером | POSIX sh + существующие awk/jq; сохранить рабочие API/CLI и фоновые роли |
| C. Полная замена централизованным демоном/БД и новым управляющим API | Высокая; одновременная миграция контуров/состояний/Панели | Единый процесс, но крупный объём нового кода и новая точка отказа | Новый постоянный процесс и хранение, бюджет не доказан | Самый высокий риск BusyBox/MIPS/Entware и обновлений; оснований сейчас нет |

**Рекомендация агента: B.** Использовать A как ограниченные предварительные исправления. C отклонить на этом этапе: не показано, что существующие механизмы недостаточны. Это предложение, а не принятое владельцем решение.

### Границы B, предлагаемые для согласования

- Единой становится **логика решения** и право применения, а не новый монолит. Engine остаётся источником наблюдений/проб; reconciler — пересмотром; guard — здоровьем и событием; policy-sync — исполнителем CIDR по согласованному набору.
- Общий resolver возвращает domain/coverage, source refs, intended target, observed configured target, DNS policy, owner, permission, reason, freshness/generation. Packet-verified path — отдельное поле с временем/доказательством либо unknown; не выводить его из FQDN-конфига.
- Источники независимы. Каталог включён как источник — учитываются только выбранные сервисы, не весь каталог. Включённый пустой/отсутствующий manual — штатное состояние.
- Ownership ресурса и разрешение изменить его маршрут разделены. По умолчанию unknown/foreign/reference не мутируются; явная делегация — отдельная операция с копией и откатом. Номер domain-listN и похожее название доказательствами не являются. При reuse номера проверять идентичность, не переносить старые saved DNS.
- Сначала защищённый snapshot → расчёт/валидация плана → под общей договорённостью locks свежая сверка поколения/прав → delta apply → verification → commit. Сетевые пробы не держат блокировку изменения на весь timeout. Обновление сохраняет действующий runtime admission; порядок locks документируется и тестируется на deadlock.
- Keenetic и AGH не поддерживают одну физическую атомарную транзакцию: нужны журнал до внешней записи, компенсация, состояние pending/recovery и сохранение undo при неизвестном результате. Не заявлять «атомарно» после одного успешного POST.
- Совпадающее назначение можно использовать без новой физической группы; все источники сохраняют ссылку на намерение. При отключении одного требование остальных пересчитывается; не терять уже обнаруженный домен только потому, что раньше он был покрыт сервисом.
- Ключ покрытия включает домен/семантику exact/subdomain, назначение и DNS-контекст. Правила с разными VPN/ISP/DNS не склеиваются только по строке или общему IP.
- При конфликте чужого фактического правила и желаемого пути — объяснение и запрет автоматического переноса. Предлагаемый приоритет manual > service > adaptive не даёт права изменять чужое.
- Без доступного VPN сохранять intent и причину, не создавать маршрут в пустоту. Политика «только VPN» либо «разрешён ISP fallback» — явно заданная; существующий auto/fallback не переносить на все источники молча.
- FQDN wildcard/apex/subdomain, CNAME, IPv6 и ограничения прошивки проверять fixtures и отдельной live-приёмкой. Не переносить Python/SQL/new runtime dependency на роутер.
- Постоянное состояние хранит только намерения, доказательства принадлежности и recovery; вычисляемые индексы/счётчики в /tmp. Состояния меняются атомарной заменой, сравнение перед записью, ограниченный журнал. Никакого нового периодического обхода всей конфигурации.

## 6. Все восемь комбинаций

M/S/A — разрешение использования ручных списков / выбранных Сервисов / Автоподбора.
Во всех строках чужие правила наблюдаются, сохраняются и отображаются как внешние. Выключение источника не стирает его данные.

| M | S | A | Планируемое поведение |
|---|---|---|---|
| 0 | 0 | 0 | Не применять VWARD-доменные решения; снять только доказанно собственное покрытие без других ссылок; DNS/AGH и внешние правила остаются |
| 0 | 0 | 1 | Автоподбор подтверждённых новых доменов, уважая существующие внешние правила |
| 0 | 1 | 0 | Только отдельно включённые сервисы; manual и adaptive историю не удалять |
| 0 | 1 | 1 | Сервисы + подтверждённые непокрытые домены Автоподбора |
| 1 | 0 | 0 | Только разрешённое manual-покрытие; без автоматического присвоения групп |
| 1 | 0 | 1 | Manual + подтверждённые непокрытые домены Автоподбора |
| 1 | 1 | 0 | Manual и выбранные Сервисы; единый расчёт дублей/конфликтов |
| 1 | 1 | 1 | Все три источника, сохраняющие свои намерения без лишних физических правил |

Нужны не только 8 начальных состояний, но все 24 направленных перехода по одному тумблеру, повторное применение того же состояния, restart и rollback. Сохранённый adaptive-кандидат под покрытием сервиса должен быть доступен пересчёту после выключения сервиса, без искусственной задержки обнаружения.

## 7. Панель: точечный контракт

Сохранить целиком действующие HTML/CSS/JavaScript, навигацию, рабочие компоненты и телефонную вёрстку. Новый автономный макет не заменяет Панель.

Три отдельные строки через существующие `ctrlRow(..., sw(...))`, стандартные .switch; без dropdown/трёхпозиционного выбора источника. Основания: [vward-console.js:945–946](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/web/assets/vward-console.js#L945-L946), [vward-console.css:319–325](https://github.com/Ziegfe1d/VWARD/blob/5869f119f6f8c43f001d80c2d6d9da3c24daf9ec/web/assets/vward-console.css#L319-L325).

Для каждого источника показать:
- настройку разрешения; доступность и свежесть снимка; применение / pending / blocked / unknown;
- уникальные домены внутри источника и в объединении, отдельно пересечения; физические группы не суммировать как уникальные имена;
- желаемый путь, реально настроенный путь, подтверждённый клиентский путь либо «не проверен»;
- owner/право управления и причину отказа; внешние правила остаются видимыми при выключенном источнике;
- конфликты VPN/ISP/разных туннелей/DNS, ссылки на источник каждого решения.

Один логический сервис может ссылаться на несколько покрытий без нескольких одинаковых карточек. API отдаёт ограниченную сводку из имеющегося кэша, детали — по запросу. Ошибка записи откатывает вид тумблера либо показывает pending, но не ложный «применено». Секреты upstream и raw running-config в API/журнал не передавать.

## 8. Независимые исправления и план пакетами

В этом PR находятся **только отчёт и документация**, нижеприведённое — план, а не выполненные исправления. Каждый кодовый пакет — отдельная ветка и draft PR, минимальный diff, подтверждение причины тестом до fix. Длительный полный CI — один раз на собранный пакет; успешные долгие проверки без причины не повторять.

| Пакет | Зависимости | Что разрешено готовить независимо от архитектуры | Приёмка |
|---|---|---|---|
| RS-0: этот аудит | PR #10 как план; чтение P-7 без его изменения | Инвентаризация, доказательства, варианты, журнал | Ссылки на pinned code, полная матрица требований; различены static/runtime |
| RS-1: защита принадлежности services | RS-01; выбранная архитектура не нужна для запрета опасной мутации | Консервативный запрет auto-adopt для записи; foreign/legacy не менять при off/refresh/tunnel/category/auto-quality; read-only объяснение | Регрессии RS-01, existing managed-service lifecycle; unknown не становится owned после reboot/update; никаких удалений пользовательского |
| RS-2: сохранность состояния при отказах | RS-04 и RS-05; отдельные небольшие commits | unknown при ошибке чтения; сохранить неподтверждённые owned DNS-привязки | Отказ RCI и ndmc, rc=0 error, ошибка ledger write, repeated run/reboot; проверены позитивные ветки, DNS fail-open не сломан |
| RS-3: транзакции services | RS-1; тесты RS-02/03 | Запись state после подтверждения либо явный pending; backup/undo состава refresh, ёмкость промежуточной дельты | on/off/retarget/category/refresh, отказ на каждом шаге, 300→300, SIGTERM, повтор, write/save/AGH outage |
| RS-4: нагрузка | Ранее согласованный ROADMAP t; отдельный baseline | Пакетное сравнение CIDR без изменения wanted/owned/shrink/DNS semantics; устранение только измеренных повторных read | Полная эквивалентность планов на fixtures, те же guards; существующий resource budget без увеличения лимитов; реальные CPU отдельно |
| RS-5: общий resolver только audit/dry-run | **Выбор архитектуры владельцем**, RS-1/2 | Адаптеры M/S/A, owner/permission refs, объяснение конфликта и предложенной дельты | 8 состояний +24 перехода; нормализация, частичное покрытие, разные назначения; ноль мутаций в dry-run |
| RS-6: единое применение по частям | RS-3/5 | Подключать services → adaptive → guard/nightly → CIDR; единый порядок locks и generation check | Параллельные команды, отказ VPN/DNS/AGH/RCI, restart/update/power-loss points, чужие данные неизменны; повтор не увеличивает группы/DNS/маршруты |
| RS-7: существующая Панель | Стабильный read-only API из RS-5; запись из RS-6 | Три тумблера, сводки и причины, точечные модули | Текущие UI/security tests + мобильная проверка; все страницы/навигация сохранены, нет ложного off/applied |
| RS-8: сборка будущего кандидата | Принятые пакеты; без публикации | Совместимость API/callers, rollback/update allowlist, совместный CI/эмуляция | Результаты привязаны к HEAD; существующая конфигурация/состояние переживают обновление; неизменны VERSION/feed/signing/release |

Оптимизацию процессов, дефекты Панели и надёжность updater исправлять только при новом конкретном доказательстве; не начинать повторный полный аудит уже проверенных компонентов ради наполнения обновления.

### Минимальный набор сценариев для следующих PR

1. Чужая группа: только одинаковое название; 80% overlap с лишними доменами; маршрут ISP, другой VPN, несколько маршрутов; stale/legacy enabled.tsv; повторное использование номера группы.
2. Managed группа: create/on/off/refresh повторно; каталог исчез, невалиден, >300; добавление/удаление при заполнении 300; ошибка backup/state/save и потерянный ответ.
3. Источники: пустой manual; все восемь комбинаций и 24 перехода; покрытие точное/родительское/частичное; явный skip; новый домен немедленно проверяется, существующий нужный путь не дублируется.
4. Конфликт: manual ISP vs service VPN, разные VPN, Smart DNS proxy vs FQDN/CIDR; CNAME/shared CDN не даёт права менять чужое.
5. Сбой: неизвестный snapshot; AGH API down и POST applied/reply lost; VPN down без альтернативы и с явным fallback; заполнение DNS slots; недоступная флешка.
6. Конкурентность/восстановление: services-refresh vs on/off, guard vs manual, engine vs reconcile, DNS unbind vs agh_bind; TERM/reboot/update/rollback между шагами. Recovery сохраняет ownership и причины, повтор не плодит сущности.
7. Путь и бюджет: IPv4/IPv6, TCP/UDP, клиентский Private DNS; число процессов/вызовов/save/flash и время на одинаковом fixture, затем отдельная аппаратная приёмка.

## 9. Решение, которое требуется от владельца

Выбрать A/B/C. Рекомендован B с предварительными защитными исправлениями RS-1…RS-3. Приоритет manual > service > adaptive и явная политика fallback являются предложениями до окончательного согласования, а не разрешением молча переназначить действующие маршруты.

Разработка без доступа к Keenetic разрешена поручением 30.10. Отсутствие shell в этой сессии ограничило исполнение тестов, но не является основанием менять настройки устройства. До команды **«Выпускаем»** запрещены merge в dev/main, публикационный номер версии, подпись/release/feed, установка, изменения Keenetic/AGH/VPN и удаление пользовательских групп/маршрутов.

## 10. Проверка этого пакета

- Прочитаны и сопоставлены исходники, вызывающие функции и потребители состояния; все новые ссылки на код привязаны к одному HEAD P-7.
- В code-mode проверяются ссылки на реально прочитанные пути и диапазоны строк, 8 комбинаций/24 перехода, отсутствие секретов из устройства и границы diff.
- Контрольные суммы изменённых документов пересчитаны; перечень файлов и сохранённое содержимое проверяются через GitHub после записи.
- Shell/функциональные тесты/эмуляция/resource-audit не запускались: исполняемая среда недоступна. Ни один дефект RS не помечен исправленным.
- Для документационного пакета долгий CI не требуется; commits с [skip ci], workflow не изменяется, старые успешные runs не перезапускаются.
