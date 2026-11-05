# RS-5: нормализованный audit-контракт v1

## Уточнение 04.11.2026: проект явного намерения, без live wiring

База продолжения — dev `3f4802b` после выпущенного fix.35.6 / PR #37.
Контракт v1 и `vward_routing_audit INTENTS SNAPSHOT` ниже сохраняются. Они не описывают
явный DNS/ISP/VPN pin, выключение VPN-вклада и его отличие от выбора Провайдера.
Новые чистые проекции — продолжение этой библиотеки, не второй контроллер/хранилище UI.
Проект первого подключения и план — [RS7_EXECUTOR_WIRING_DESIGN.md, F](RS7_EXECUTOR_WIRING_DESIGN.md#f-уточнение-04112026-единое-намерение-и-первый-writer).

### Один сервис — одно намерение

Предлагаемый формат CHOICES v1 (ещё **не создаётся в /opt**): строка `schema<TAB>1`,
затем `service SID REV MODE TARGET DNS AUTO_FLOOR` (7 полей TSV).
SID — стабильный catalog service ID; это не group ID и не ownership proof.
REV — целое 0..2147483647; ревизия меняется только при семантическом изменении.
MODE=`auto|vpn|dns|isp`. VPN-тумблер выводится из `MODE==vpn`, не хранится отдельно.
TARGET/DNS: auto=`-/-`, vpn=`VPN:INTERFACE/default`, dns=`ISP/POLICY_ID`, isp=`ISP/default`.
POLICY_ID — непрозрачный ID без URL/host/token, не доказательство доступности сервера.
AUTO_FLOOR — ревизия последнего выхода из DNS/ISP-pin в auto **или VPN**, 0 до такого события.
Она запрещает оживлять старую историю Auto при возврате в Авто. Активная независимая
Auto-ссылка после обычного service-off сохраняется; положительная новая проба относится
к текущей ревизии выбора. Полная семантика active/history/probe указана в F.

Чистая `vward_routing_choice LEDGER SID ACTION TARGET DNS EXPECTED_REV` возвращает новый
канонический LEDGER на stdout. ACTION=`on|off|vpn|dns|isp|auto`; expected revision — CAS
над **входным снимком**, не lock/CAS над роутером. `off` меняет только vpn→auto;
off при dns/isp/auto — no-op. Явный `auto` снимает любое закрепление. on/vpn заменяет
старый DNS/ISP pin тем же сервисным VPN-намерением. Повтор не увеличивает REV.
Отсутствие SID в корректном ledger означает auto/rev0, нечитаемый/отсутствующий/повреждённый
ledger — ошибка, не пустое состояние. Повтор SID и неизвестная schema отвергаются.
Старый audit не читает новый формат; будущая миграция/rollback требуют отдельного gate.
LEDGER — абсолютный путь к читаемому обычному файлу, не symlink/FIFO. Ошибка формата —
rc2, stale REV — rc3; оба без частичного stdout. Другие сервисы сохраняются, SID сортируются.

### Чистая модель политики одной области

`vward_routing_service_policy MODE TARGET DNS REV AUTO_FLOOR EVIDENCE` реализует только
сведение намерений **одного заранее нормализованного domain/scope atom**. Первые пять
аргументов — поля канонического choice; это не installed reader/CAS. Функция не определяет
принадлежность домена, пересечения/исключения, свежесть пробы или источник глобального toggle.
Будущий stage adapter обязан подтвердить область, membership и epoch; простая строка `bound`
не даёт права менять ресурс. Каталог/совпадение имени не заменяет эту проверку.

EVIDENCE — абсолютный обычный файл (не symlink/FIFO), header `schema<TAB>1`, далее 8 полей TSV:
`SOURCE REF TARGET DNS SELECTED EVIDENCE EPOCH MEMBERSHIP`.
M/S означают **независимые peer** явные вклады, EVIDENCE=`explicit`, EPOCH=0, MEMBERSHIP=`peer`.
Вклад выбранного сервиса не дублируется во входе: при mode!=auto он создаётся как `S:choice`
(это имя запрещено peer S). A: EVIDENCE=`active|positive|history|unknown`, MEMBERSHIP=
`bound|excluded|unknown`, EPOCH=ревизия выбора при получении доказательства, не wall clock.
SELECTED=0/1 — уже нормализованная активность источника/вклада, не включение каталога целиком.
Дубликаты SOURCE:REF, неизвестная schema, future epoch, URL вместо DNS ID — rc2 без stdout.

Выход: `policy 1 VERDICT denied unknown` (5 TSV полей), затем отсортированные строки
`contribution SOURCE REF TARGET DNS STATE REASON` (7 полей). VERDICT=`inactive|desired|unknown|unresolved`.
STATE=`active|inactive|suppressed|unknown`. `desired` означает только совместимые намерения;
даже `inactive` не означает подтверждённый Провайдер. Последние поля header всегда permission
`denied` и packet-path `unknown`. До 1024 входных вкладов + один выводимый S:choice.

- DNS/ISP suppress только подтверждённый bound A, не M/S peer. VPN suppress несовместимый A;
  совместимый сохраняется как самостоятельное основание для reuse без новой физической записи.
- history всегда inactive. positive допустим только при EPOCH==REV, active — EPOCH>=AUTO_FLOOR;
  будущая epoch запрещена. Выход DNS/ISP→VPN→off тоже повышает floor и не оживляет старый persist.
- excluded A не относится к области; unknown membership/evidence даёт unknown, не suppression
  и не право применить pin. Несовместимые активные M/S остаются unresolved независимо от порядка.
- Обычный VPN-off без предыдущего DNS/ISP-pin сохраняет независимое активное A; explicit Auto
  после pin требует новой положительной проверки/доказанного текущего active. History не становится active.

Это **модель намерений**, не полный planner: configured routes остаются в исходном snapshot,
suppressed не удаляет их и не означает applied. Новый stream намеренно несовместим с v1 INTENTS;
старый audit отвергает его. Health/storage/capacity/coverage/identity и физический diff ещё не
подключены. Writer, journal replay и Панель не вызывают новую функцию. Schema v1 ledger — проект,
не обещание совместимости данных при downgrade; состояние на устройстве этим пакетом не создаётся.

### Приоритет выбора и равноправие источников

Явный режим выше **автоматического обнаружения**, не выше независимого явного manual pin.
Совместимые M/S/A сохраняют ссылки на одно эффективное покрытие. Несовместимый M или
другой явный service pin — unresolved, до первой записи требуется точный согласованный
план. Ни порядок файлов, ни более длинное имя, ни время строки не выбирают победителя.
Совместимый внешний ресурс — reference, никогда не приобретает managed/owned от совпадения.
Suppress intent Auto не означает удалить наблюдаемую группу или объявить переход выполненным.
Наблюдаемый конфликт остаётся до разрешённой дельты и readback.

Чистая policy-проекция возвращает desired, active/suppressed/history/unknown contributions;
согласованный snapshot и health/coverage issues добавляются следующим stage adapter. Передать
только desired в старый planner недостаточно.
Смешанный вывод новой проекции не является v1 INTENTS/PLAN и не принимается dryrun/journal.
Все новые планы всё ещё denied/require approval, permission никогда не granted.

Нормализация/границы: exact/subtree только из доказанных возможностей; wildcard/exclude/CNAME,
shared CDN/IP, IPv6/UDP и client policy не выводятся из простого совпадения FQDN. Неизвестное
разделение — partial/unknown, не «сервис применён». v1 global health не разрешает объявить
AGH обязательным для VPN без Smart DNS: зависимости уточняются отдельно по операции/backend.
Новые pure-функции не читают роутер, часы, сеть или конфигурационные пути и не пишут файлы.
Лимиты не расширяются: 4096 строк/1 MiB на input, 1024 service/domain keys; awk/sh без
предположений о comm/cksum на устройстве. Live вызовов и package-map wiring нет.

---

Исходный API `components/runtime/lib/vward-routing-audit.sh` —
`vward_routing_audit INTENTS SNAPSHOT`. Его v1 поведение не изменено. Загрузка через `.` ничего не запускает,
не создаёт файлов и не меняет переменных вызывающего shell. Вызов читает два
явно заданных обычных файла и пишет TSV в stdout; ошибки — в stderr, rc=2,
без частичного stdout. Валидный аудит, включая конфликт/unknown, возвращает 0.
Никаких ndmc/RCI/DNS/AGH-запросов, записи, locks, state, daemon или интеграции.

## Вход: TSV, без заголовков, комментариев и пустых строк

INTENTS: `SOURCE REF DOMAIN SCOPE TARGET DNS SELECTED` (7 полей).
SOURCE=M/S/A; REF — безопасный идентификатор; SELECTED=0/1: отдельно выбранный
сервис, подтверждённый adaptive-кандидат или разрешённая manual-запись.
Глобальный тумблер не включает невыбранные строки каталога.

SNAPSHOT содержит ровно одну строку `snapshot GENERATION known|unknown`,
ровно три `source M|S|A 0|1 known|unknown`, ровно по одной
`health DNS available|unavailable|unknown` и `health AGH STATE`.
Дополнительно: `health VPN:INTERFACE STATE` и
`route REF DOMAIN SCOPE TARGET DNS OWNER PERMISSION` (8 полей).
OWNER=vward/manual/unknown; PERMISSION=managed/reference. `managed` разрешён
только с owner=vward; это **утверждение адаптера**, а не доказанное библиотекой
право. Manual и unknown всегда reference; совпадение имени не даёт владения.
Одна REF обозначает одну запись; одинаковая повторная строка допустима,
противоречивое повторное определение REF отклоняется.

DOMAIN — уже нормализованный lowercase ASCII FQDN, без точки в конце,
меток >63 или имени >253; минимум две метки. SCOPE=exact либо subtree
(apex + потомки). Это явная семантика подготовленного снимка, а не заявление
о Keenetic wildcard/FQDN/CNAME. TARGET=ISP или VPN:INTERFACE; DNS — безопасный
непрозрачный идентификатор политики без секрета (например default/smartdns).
Идентификаторы: 1–64 ASCII символов `[A-Za-z0-9_.:-]`, первая буква/цифра.
Неизвестная live-конфигурация должна передаваться `snapshot ... unknown`,
а не пустым known-снимком. Отсутствие VPN-health означает unknown.
Лимиты каждого файла: 4096 строк, 1 MiB; объединения: 1024 уникальных домена.

## Выход: одна строка на домен из любого входа

Поля TSV (без заголовка): `DOMAIN SOURCES ACTIVE WANTED CONFIGURED RIGHTS
DUPLICATES DECISION REASON ISSUES GENERATION PACKET_PATH`.
Пустое множество обозначается `-`; элементы множеств разделены запятой и
отсортированы в C locale. SOURCES/ACTIVE: `SOURCE:REF`; WANTED:
`SCOPE@TARGET@DNS`; CONFIGURED: `REF@SCOPE@TARGET@DNS`; RIGHTS:
`REF@OWNER@PERMISSION`. CONFIGURED включает все покрывающие route-записи,
включая subtree-родителей; SOURCES содержит ссылки точного DOMAIN, ACTIVE —
только выбранные записи разрешённых источников. DUPLICATES — лишние активные
ссылки с одинаковыми SCOPE/TARGET/DNS (повтор строки с той же REF не считается).
Потомок с родительским intent входит в WANTED и ACTIVE с исходной ссылкой.
Поддерево нельзя считать полностью покрытым exact-правилом apex.

DECISION/REASON:
- `unresolved / conflicting-target-or-dns`: несколько TARGET/DNS среди активных
  намерений и наблюдаемых покрытий. Никакого manual>service>adaptive приоритета.
- `unknown / snapshot-or-source-unknown`: снимок или включённый источник unknown.
- `inactive / no-active-intent`: нет активных намерений; внешние правила видны.
- `blocked / dependency-unavailable`: требуемый VPN, DNS или AGH недоступен.
- `unknown / dependency-unknown`: требуемая проверка unknown/не задана.
- `covered / reuse-existing-coverage`: каждый scope намерения уже покрыт
  совместимым route. Reference-правило можно только наблюдать/использовать.
- `review / new-coverage-needed`: совместимого полного покрытия нет.

ISSUES содержит все известные проблемы зависимостей, например
`AGH:unavailable,DNS:unknown,VPN:tun1:unknown,source:A:unknown,snapshot:unknown`,
либо `-`. Для VPN/DNS/AGH учитываются зависимости активных намерений.
Конфликт показывается даже при неизвестном снимке; неполнота остаётся видна
в ISSUES. REASON — главная причина, не live-вердикт.
PACKET_PATH всегда `unknown`: configured target не доказывает путь пакета.
Все решения — объяснения; даже review не разрешает запись или ISP fallback.
Неполное покрытие, неактивный источник и отсутствие намерений не разрешают
удалять группу. История, intent и ручные настройки остаются во входных файлах.

## Границы

Нет inventory-адаптеров, live-счётчиков, freshness-проверки часов, миграции,
ownership-proof, proposed destructive delta, writer API, snapshot generation
recheck, перезапуска/rollback или аппаратной приёмки. GENERATION — непрозрачный
токен вызывающей стороны, не гарантия свежести. Кандидаты и смена тумблеров
пересчитываются из сохранённых входов без потери данных. Подключение существующих
writer/engine/reconcile/guard/CIDR и UI — только RS-6/RS-7.


## Ограниченная проверка стоимости расчёта

Внутри домена routes обходятся один раз: индекс TARGET/DNS/SCOPE затем
используется для каждого intent без повторного сканирования routes. Порядок
всех ключей доказательств вычисляется merge sort один раз на вход; вывод
подмножеств проходит по этому порядку. Расчёт покрытия и сбор доказательств
имеют стоимость O(D × (I + R)), предварительная сортировка — O(N log N).
Это сокращает повторную работу, сохраняя полный детерминированный вывод.

`python3 tests/routing-audit/check-bounded-cost.py --busybox /path/to/busybox`
проверяет BusyBox ash/awk на 64 доменах, 128 отдельных subtree-intent и
128 отдельных route-ссылках одинакового назначения. Каждый байт ожидаемого
вывода, 64 строки, 449454 байта, duplicate=127, covered и reference-права
проверяются независимо; неизменный timeout — 3 секунды на весь процесс.
До оптимизации этот fixture превысил 3 секунды; после — 0.180 секунды в
доступной host-среде. Полные предельные объёмы не прогонялись; это регрессия
конкретной лишней работы, а не измерение бюджета Keenetic/MIPS или live-нагрузки.
Python нужен только host-тесту; runtime по-прежнему использует sh и awk.

## RS6, этап 1 (31.10.2026)

Отдельная native read библиотека vward-routing-read.sh выводит тот же TSV,
не меняя RS5 API и пределы. Источники, truth/unknown, snapshot-local REF,
сравнения legacy и следующий shadow этап — [RS6_READ_ADAPTERS.md](RS6_READ_ADAPTERS.md).
Она не подключена к writer/Панели, health/packet-path unknown; rights всегда reference.

## Продолжение PR38: согласованный stage и типизированная подготовка v2 (live OFF)

`vward_routing_consistent_read2 OUT INPUTDIR` — тот же native snapshot плюс обязательные
`version/choices/bindings/evidence/policies/saved/queue/tombstones/context/resources/proofs.tsv`.
INPUTDIR/OUT — разные приватные owned0700 каталоги, без symlink. Версия данных — строка
`routing-state<TAB>2`. Canonical choices сохраняют schema1 и смысл предыдущего раздела.
SHA256/size/inode/mtime до/после охватывают **и** native inputs, **и** decision inputs;
generation зависит от содержимого. `cksum`/`comm` не нужны. Staged bytes проверяются повторно.
V1 OUT без новых входов сохраняет прежние пять файлов; v2 дополнительно даёт inventory.tsv,
groups.tsv и private decision copies. Seal связывает все подготовленные outputs и generation;
generation публикуется последним. Несогласованный/изменённый stage не используется повторно.
Seal доказывает целостность снимка, не истинность внешнего health-факта и не право владения.

Native `inventory` reader: 13 TSV полей `resource REF GROUP DOMAIN SCOPE TARGET DNS OWNER
CONTENT IDENTITY reference CONTAINER STABLE_RESOURCE_ID`. Native имя, стабильный u-ID/container,
изменяемые REF/content и exact proof разделены. Target/content change не меняет stable ID,
но лишает stale proof действительности. Rights по-прежнему reference. Это не adoption по имени.

Нормализованные v2 inputs (предварительный формат, не installed state):

| Файл | Поля TSV |
|---|---|
| bindings | SID DOMAIN exact/subtree confirmed/excluded/shared/unknown ipv4/dual/unknown known/unknown(client-policy) |
| evidence | SOURCE REF DOMAIN SCOPE TARGET DNS SELECTED explicit/active/positive/history/unknown EPOCH ORIGIN_SID/- |
| context | KEY VALUE; source:M/S/A, VPN:IF, storage:keenetic/agh, probe:REF=fresh, scope:subtree=available |
| policies | ID keenetic/agh available/unavailable/unknown active/inactive/unknown none/supported/unsupported(upstream-file) REV URL_KEY |
| resources | KIND RID NATIVE DOMAIN SCOPE TARGET DNS BACKEND OWNER BIRTH CONSUMERS |
| proofs | первые 10 полей resource, затем CONTENT_REV вместо consumers; exact private receipt |
| tombstones | POLICY REV deleted |

KIND пока route/dns; NATIVE — `group:NAME` либо `upstream:OPAQUE_KEY`, не resource ID/URL.
CONSUMERS — множество `M:REF,S:REF,A:REF` либо `-`. Backend native/keenetic/agh.
OWNER=vward не выдаёт право: нужны exact private receipt и verified native identity; незарегистрированное
наблюдаемое покрытие остаётся reference. Для saved/queue, миграции и actual backend receipts формат
ещё уточняется в связанной реализации; не подавать эти данные старому live writer.

`vward_routing_project2 STAGE SID NEXT_CHOICES OUT` соединяет **настоящие** choice/policy из audit
с membership, native manual intents, peer choices и freshness/epochs. NEXT_CHOICES пересчитывается
из staged ledger общим transition: нельзя подменить REV/floor либо изменить второй сервис.
Сохраняет atoms.tsv/policy.tsv/choices.tsv/service и seal; неизвестный native source/peer membership
не превращается в ISP. Новый подтверждённый child наследует pin; shared/excluded не приобретают ownership.
Программный VPN-off при DNS остаётся no-op. Loading/read не вызывает transport/background repairs.

`vward_routing_plan2 STAGE PROJECT OPID` возвращает только текст:

```
routing-plan<TAB>2<TAB>GEN<TAB>denied
step SEQ ACTION KIND RID PRE POST PROOF CONSUMERS CHECKS INVERSE
```

Все step-поля TSV. PRE/POST — canonical resource/choice row с `|` вместо TAB; `-` значит отсутствие.
ACTION=create/add/remove/move; claims — только local consumer metadata. Конкретные native ref/scope,
identity и собственная обратная дельта сохраняются в row, исходный native snapshot не исчезает.
При любом `hold DOMAIN REASON` **ни одной** step/choice-commit строки не возвращается.
Весь переход проверяет Keenetic8, active backend/upstream-file/tombstone, совместимость references
и только необходимые зависимости. Чистый VPN не проверяет Smart DNS/AGH; реальное снятие AGH требует
известного AGH storage. Переход off/auto сохраняет внешний VPN, совместимый ISP не конфликт.
Поддерево требует доказанной backend capability; отсутствие доказательства — hold, не расширение scope.
4096 строк/1MiB на input и расширенный output, до1024 domains/4096 resources; границы не увеличены.

Parent journal v2 хранит immutable plan+SHA, generation Gi и private per-step pre/post/observed.
BEGIN только в порядке шагов, до write; FINISH сравнивает post/pre/other. Новый Gi записывается
после доказанного собственного результата, следующий шаг с прежним G0 отвергается. Commit требует
всех readbacks и обязательного save. Used OPID не повторяется. Старый v1 journal отвергает v2 plan
и считает такой active каталог unknown; downgrade требует версионированной миграции.
Компенсация — только по immutable postimage либо записанному **до write** group/DNS-scope prefix;
чужой образ не разрешает inverse. Abort проверяет earliest preimage каждого своего scope и baseline
save, хранит resolution receipt. Метка committed/compensated сама по себе не заменяет доказательства.
Все эти функции только записывают свидетельства; executor/coordinator/recovery и полный chained
fixture ещё должны быть соединены. Это не разрешение live и не claim аппаратной приёмки.


Дополнение05.11.2026 (PR38 G4, OFF): coordinator/locked workers соединены на fixed DATA
с J2, state-set migration, DNS lifecycle и общим configuration outcome. Dispatch scope
receipt, native boot/deadline и actual publisher lifetime не заменяются matching image,
PID-only или cached freshness. Чужой matching post не присваивается и не компенсируется.
Живое исполнение не подключено: legacy eligibility/updater bridge только подготовлены,
normal callers/actions/новые libs не установлены. Актуальные gates и конкретная следующая
VPN-only граница — RS7_EXECUTOR_WIRING_DESIGN.md §G.4; исторические описания выше сохранены.


Уточнение05.11.2026 (PR38 private-mode/lifetime CI correction): shared lock metadata
пишет elected owner, не unleased shell-child. Private constructors задают свои modes,
восстанавливая caller umask; permissive fixture не повод ослабить ownership/read gate.
Healthy lock observation не создаёт USB election; deletion всё равно требует fresh stale
check внутри SAME election и leased utility. Адресные проверки не заменяют exact CI budget;
CI42000841257 был FAIL, следующий HEAD требует собственных ворот. Live по-прежнему OFF.
