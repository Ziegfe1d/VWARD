# RS-7: модель восстановления AGH и технический проект подключения исполнителей

Только проект и анализ. **Исполнители не подключены**, роутер, AGH, DNS, VPN и маршруты
не менялись. Подключение — после отдельного согласования безопасности владельцем.

## A. Проверка модели восстановления при неподтверждённом изменении AGH

Рассмотрены `vward-ads-privacy-control.sh agh smartdns-take|put|restore`, журнал
`vward-console-config.sh` (`AGH-RESTORE`, `AGH-UNCERTAIN`, `agh_recovery_reserve`,
`routing_recovery_check`, `cleanup`). Исполняемая проверка на фиктивном AGH-API:
`tests/repository/check-ads-agh-restore-safety.py`.

| # | Находка | Статус |
|---|---|---|
| A1 | Слепой откат: при несовпадении read-back скрипт безусловно отправлял в AGH **прежний** список (`dns.json`). Если между записью и проверкой пользователь изменил upstream, откат стирал его правку. RED: строка пользователя исчезла, был второй POST | **Исправлено** (`agh_guarded_back`): прежний список возвращается только пока AGH содержит ровно записанный нами план; иначе — ничего не пишется, pairs/`dns.before.json`/`dns.planned.json` сохраняются, rc≠0 |
| A2 | План строился по устаревшему чтению: правка пользователя между GET и POST терялась при записи | **Исправлено** (`agh_unchanged`): повторное чтение прямо перед POST; отличие → ничего не записано, `pairs` обнулён, `verification_failed`. Окно сократилось до одного HTTP-запроса; полностью закрыть без CAS/ETag в AGH API нельзя — остаточный риск R1 |
| A3 | `take`: POST упал/ответ потерян → ошибка `adguard_rejected`, хотя изменение могло применяться | Не менялось: безопасно, т.к. `AGH-RESTORE pairs.tsv` уже в журнале **до** POST, а `smartdns-restore` только добавляет отсутствующие пары (идемпотентно). Имя ошибки вводит в заблуждение → RS7: отдельный код `agh_result_unknown` |
| A4 | `put`: `AGH-UNCERTAIN` пишется до POST и всегда даёт `bad=1`; recovery-директория остаётся, `routing_recovery_check` блокирует любые следующие изменения (в т.ч. пустую резервацию после SIGKILL) | Корректно: приватные данные сохраняются, опасные повторы заблокированы. Читатель RS-6 видит `smartdns.*`/`pending` и делает источники unknown |
| A5 | `take`: `dns.before.json`/`dns.planned.json` не сохраняются (только `pairs.tsv` и `router.undo`) | RS7: писать оба в recovery-директорию до POST (как в `put`) |
| A6 | После «успешного» undo recovery-директория удаляется (`rm -rf`), хотя восстановление было аддитивным и итоговый список AGH мог отличаться от исходного из-за чужих правок | Остаточный риск R2: RS7 — удалять только после побитового совпадения с `dns.before.json` либо явной отметки владельца |

Принцип подтверждён тестом: **старое состояние не восстанавливается поверх нового**; при
неизвестном результате приватные данные остаются, повторные операции блокируются.

Остаточные риски (открыты): R1 — окно между повторным GET и POST (нет CAS в AGH);
R2 — удаление recovery после аддитивного undo; R3 — реальное поведение AGH на Keenetic
не проверялось (фиктивный API); R4 — `AGH-RESTORE` может вернуть строку, которую пользователь
сознательно удалил в окно между ошибкой и откатом (аддитивность — меньшее зло, но фиксируется).

## B. Проект подключения общего механизма к исполнителям (не выполнять сейчас)

Порядок и инварианты записи одного изменения (один исполнитель за раз, начиная с самого
узкого — Services/domain-list, затем reconciler, затем остальные):

1. **Права.** Намерение допускается только при `IDENTITY=verified` (`services/owned`) для
   изменяемой группы и `RIGHT` из явного разрешения исполнителя (сейчас везде `reference`).
   Manual/unknown/foreign — только наблюдение. Совпадение имени, номера, состава доменов,
   legacy-записи прав не даёт. Три источника — три отдельных тумблера (RS7 UI позже).
2. **Блокировки и admission.** Прежние: update/admission barrier (`vward-runtime-admission`),
   `CHANGE_LOCK`, `POLICY_STATE/lock`, `routing_recovery_check`. Новых демонов/таймеров нет.
3. **Снимок и поколение.** Под блокировкой: `vward_routing_consistent_read` → `generation G0`.
   Решение (audit) считается на этом G0. Непосредственно перед **каждой** мутацией —
   повторное `consistent_read` (кэш, помеченный dirty после предыдущей записи, перечитывается
   штатно) и сравнение с G0 **и** identity/content целевой группы; отличие → отказ без записи.
4. **Журнал до записи.** Приватный durable журнал (0600, рядом с `BACKUP-recovery`): запись
   плана (REF, G0, pre-image группы/маршрута/AGH), затем `PENDING`, затем мутация, затем
   `DONE`. fsync/mv-атомарность как в service-transactions. `PENDING` без `DONE` после
   перезагрузки = неизвестный результат: читатель делает источники unknown (уже реализовано).
5. **Точечная компенсация.** Откат только своих шагов в обратном порядке и только если
   текущий объект побитово равен нашему post-image (как `agh_guarded_back`). Чужое
   состояние → не трогать, оставить журнал и приватные данные, блокировать повторы.
6. **Потерянный ответ.** Любая ошибка транспорта после отправки мутации = «неизвестно»:
   перечитать и сравнить с pre- и post-image; совпало с post → завершить; с pre → снять
   `PENDING`; иначе → `agh_result_unknown`/`route_result_unknown`, recovery сохраняется,
   дальнейшие изменения заблокированы до решения владельца. Автоповтор запрещён.
7. **Проверка после.** `consistent_read` новой генерации; ожидаемое решение audit = covered.
   Затем `system configuration save` как сейчас; сбой сохранения — явная ошибка + компенсация.
8. **Тесты до подключения.** Lost reply, TERM/SIGKILL/reboot на каждом шаге, чужая правка
   между чтением и записью, перестановка строк, переиспользование номера группы, BusyBox.

Обязательные ворота: отдельное «Выпускаем»/согласование безопасности на каждый исполнитель;
аппаратная приёмка Keenetic; полный CI на конечном code HEAD.

Независимый аудит другим агентом (правило `AGENTS.md`: адресный) обязателен именно здесь — для
каждого подключаемого writer, переключения DNS и восстановления после сбоев.

## C. RS-7 этап 1 — реализовано (read-only, без записи)

**Статус 31.10.2026:** пункты 1, 3 и 4 ниже выполнены в `components/runtime/lib/vward-routing-plan.sh`
(`vward_routing_plan`, `vward_routing_plan_log`) и `tests/routing-readers/check-plan.py` (sh и BusyBox).
Пункт 2 (журнал-до-записи) остаётся этапом 2: схема и валидатор без записи на роутере.

Программная приёмка RS-6 (audit/dry-run) закрыта этапом 3. RS-7 начинается с чистого планировщика:

1. `components/runtime/lib/vward-routing-plan.sh` — `vward_routing_plan GENERATION AUDIT IDENTITY SHADOW`
   → TSV «предлагаемое действие» на домен/группу: `none | add | move | remove | restore`, причина,
   **необходимые права** (`identity=verified` + явное разрешение исполнителя), pre-image и ожидаемый
   post-image. Только текст; ни одного вызова исполнителя, ndmc, DNS, AGH. Любой `unknown`,
   `reference-only`, конфликт, расхождение класса `review` или `service-target-defaulted` ⇒ действие
   `none` с причиной (план никогда не угадывает).
2. Журнал-до-записи как формат и проверка (без записи на роутере): схема приватной записи
   `PLAN/PENDING/DONE`, валидатор и восстановление из журнала на fixture (TERM/SIGKILL/потерянный ответ
   смоделированы подставным исполнителем в тесте).
3. Проверка поколения как чистая функция: `vward_routing_plan_still_valid` сравнивает `generation`
   плана с новым `consistent_read` и identity/content группы.
4. Режимы DNS из PR #22 (`agh` / `dnsmasq` / `native`, взаимоисключающие) входят в планировщик как
   предусловие: план DNS-переключения невозможен при неизвестном текущем режиме и отдаёт `none`.
5. Тесты: все 8 комбинаций источников и 24 перехода на планах, перестановка, чужие/unknown группы,
   лимиты, BusyBox; затем адресный независимый аудит (рискованная часть — запись).

Не входит и требует отдельного разрешения: подключение любого writer, DNS-переключение, изменение
Keenetic/AGH/VPN, выпуск. Последовательность общего выпуска (fix.36 после перенумерации 01.11.2026): RS-7 → прежние fix.34.2 / 34.2b / 34.3 →
журналы прежнего fix.35 → Панель и dnsmasq → интеграционная приёмка.

### C.1. Контракт планировщика (как реализовано)

`vward_routing_plan GENERATION AUDIT IDENTITY SHADOW CONTEXT` → строки
`DOMAIN ACTION TARGET DNS ELIGIBLE PERMIT NEEDS REASON GENERATION`. ACTION — только `none|add`
(остальное — следующие этапы). `PERMIT` — `denied:writers-disabled` либо `requires-approval`,
**никогда `granted`**. `NEEDS` — что будущий writer обязан сделать сам:
`recheck-generation,owner-proof,change-lock,journal-before-write`. CONTEXT (`dns_mode`
`agh|dnsmasq|native|both|unknown`, `agh_recovery`, `writers`, `age`, `max_age`) передаёт вызывающий:
планировщик не читает часы, файлы роутера и состояние DNS. Блокировки (reason): `snapshot-or-source-unknown`,
`dependency-unknown/unavailable`, `conflicting-target-or-dns` (без скрытого приоритета),
`ambiguous-wanted`, `service-target-defaulted`, `shadow-<class>`/`shadow-unknown`,
`ownership-unproven|unknown` (худшее среди **активных** ref, а не имя группы), `snapshot-age-unknown|stale`,
`dns-mode-unknown`, `dns-modes-conflict` (AGH и dnsmasq активны вместе — запрещено), `agh-recovery-pending|unknown`
(неподтверждённое восстановление AGH блокирует любое DNS-зависимое действие), `domain-not-in-snapshot`
(wildcard-расширенный домен, неизвестный снимку, только отражается). Поколение не совпало — rc 3,
`unknown generation-mismatch`. Сегодня все планы `ELIGIBLE=no` (health DNS/AGH/VPN всегда unknown);
положительный путь проверен на синтетическом снимке с health `available`.
`vward_routing_plan_log` печатает ограниченные строки `PLAN|домен|действие|eligible|permit|reason|generation`
для существующего журнала событий (время и запись добавляет вызывающий).

## D. RS-7 этап 2 — журнал будущих операций (реализовано, только тестовые данные)

`components/runtime/lib/vward-routing-journal.sh`. Исполнители **не подключены**; журнал ничего не делает
с Keenetic/AGH/VPN/DNS, он фиксирует намерение и доказательства.

| Запись | Когда | Содержит |
|---|---|---|
| `plan` | `vward_journal_plan` из строки `vward_routing_plan` | opid, generation, source, owner, identity, action, domain, target, dns, eligible, permit, needs, reason |
| `pending` + `pre` | `vward_journal_begin` — **до** любого изменения | generation, sha256 pre-image и ожидаемого post-image, checks; приватная копия pre-image |
| `done` | `vward_journal_finish`: текущее = ожидаемому post | хэш текущего, reason |
| `failed` | текущее = pre-image (изменение доказанно не применено) | то же |
| `unknown` | всё прочее; `vward_journal_unknown` (потерянный ответ API, TERM) | reason |
| `resolved` | позднее доказательство для unknown (`vward_journal_recover`) | done/failed + хэш |

Инварианты (каждый — тест в `check-journal.py`, sh и BusyBox; ключевые проверены мутациями):
- Запись атомарна (tmp → rename → `sync`); сбой записи оставляет прежнее состояние; без `pending` вызывающий
  **не имеет права** менять (тест: отказ записи ⇒ мутация не выполнена). Ложный `done` невозможен: при сбое записи
  остаётся `pending`/`unknown`.
- `begin` пропускает только план `eligible=yes`, с тем же `generation`, `identity=verified`, `owner=vward`,
  действием ≠ none и pre ≠ post. Ручные/чужие/unknown правила, wildcard-домены вне снимка и подмена цели на `vpn`
  (`service-target-defaulted`) отклоняются.
- Любая операция в `pending`/`unknown` закрывает шлюз для всех новых (`vward_journal_gate`, rc 75).
- Идентификатор операции используется один раз: повтор `plan`/`begin`/`finish` после любого результата — отказ.
  Восстановление **никогда** не повторяет действие и не компенсирует: только классифицирует по текущему образу,
  который перечитал вызывающий (`CURDIR/<opid>`). Нет образа ⇒ остаётся `unknown`.
- TERM/SIGKILL после `pending`, «перезагрузка» (новый процесс), разорванная запись (`*.tmp.*`), повреждённая/подделанная/
  перенесённая запись, `done` без `pending`, мусорный каталог ⇒ `unknown`/классификация по доказательству, шлюз закрыт.
- Блокировка `JDIR/.lock` (mkdir + pid): живой владелец ⇒ занято; владелец убит ⇒ блокировка снимается. Два писателя
  одновременно ⇒ ровно один `pending`.
- Значения — закрытые токены без пробелов, кавычек и `//`: URL и токены не попадают в журнал (тест нашёл, что ранняя
  версия пропускала `https://…` — исправлено до коммита).

### Открытые риски — состояние после этапа 2

| Риск | Состояние | Доказательство |
|---|---|---|
| R1 окно AGH между проверкой и записью | **сужено, не закрыто**: повторное чтение перед POST, охранный откат; в AGH API нет CAS | `check-ads-agh-restore-safety.py`; журнал классифицирует чужое изменение как `unknown`, а не `failed` |
| R2 удаление recovery после аддитивного отката | **исправлено**: take пишет `dns.before.json`/`dns.planned.json` до POST (A5); restore сообщает `RESTORE_EXACT`; неточный откат оставляет recovery и закрывает шлюз маршрутизации | RED→GREEN в `check-smartdns-clear.py` |
| Подтверждение принадлежности маршрутов | только `identity=verified` (приватный exact-proof) + `owner=vward` допускаются к `begin` | `check-journal.py`, `check-identity.py` |
| Конфликт ручных и автоматических правил | конфликт ⇒ план `none`; owner manual/unknown ⇒ `begin` отказ | `check-plan.py`, `check-journal.py` |
| Wildcard и подмена цели на `vpn` | планировщик блокирует (`domain-not-in-snapshot`, `service-target-defaulted`), журнал не начинает | `check-plan.py`, `check-journal.py` |

## E. RS-7 этап 3 — сухой исполнитель (реализовано 31.10.2026, запись не включена)

Исходная постановка:

«Сухой исполнитель» (dry-run executor) для **одного** узкого пути — сервисной группы с exact-proof: полный цикл
`plan → begin → (подставной исполнитель) → finish/unknown → recover` на эмуляторе маршрутизатора CI, с подставными ndmc и
AGH API, потерянными ответами и SIGKILL на каждом шаге. Реального исполнителя не вызывать; выключатель по умолчанию off;
перед включением — адресный независимый аудит и отдельное разрешение владельца.

### E.1. Как реализовано

`components/runtime/lib/vward-routing-dryrun.sh`: `vward_routing_dryrun_add JDIR OPID GENERATION GROUP DOMAIN`
и `vward_routing_dryrun_recover JDIR`. Один узкий путь — добавить домен в сервисную FQDN-группу с доказанным
владением. Цикл: шлюз журнала → идентификатор в состоянии PLAN → канонический образ группы (отсортированные
`include`, дубль/отсутствие группы = нет образа) → `begin` (PENDING) → **одна** запись → повторное чтение →
`finish` (DONE/FAILED/UNKNOWN). Ошибка транспорта после записи — возможный потерянный ответ: решает повторное
чтение; нечитаемое — UNKNOWN. Повтора и компенсации нет; восстановление только перечитывает и классифицирует.

Безопасность (исправлено по замечанию владельца 31.10.2026): исполнитель **ничего не запускает**. Ранняя версия
вызывала исполняемый stand-in из `VWARD_DRYRUN_NDMC`, проверяя маркер в первых 256 байтах — любой файл с таким
маркером мог бы выполниться. Теперь «роутер» — встроенный эмулятор (функции sh/awk), который читает и правит
**файл данных** `JDIR/.emu/running.cfg` в приватном каталоге журнала. Каталог журнала, `.emu` и файл должны быть
настоящими (не symlink), принадлежать вызывающему и иметь права без доступа группы/прочих; правка идёт через tmp
под `umask 077` и rename. Путь к исполняемому файлу из окружения не принимается вовсе: заданная
`VWARD_DRYRUN_NDMC` (даже пустая) — отказ. Подмены файла, symlink и гонки «проверка → запуск» нет, потому что
нет запуска; данные доступны только владельцу каталога. Выключатель `VWARD_RS7_DRYRUN=1` по умолчанию выключен.

Проверено (`tests/routing-readers/check-dryrun.py`, sh и BusyBox): выключатель выключен или задан
`VWARD_DRYRUN_NDMC` → отказ без каких-либо действий; DONE; повтор того же opid → отказ; уже присутствующий домен → без записи; отказ роутера → FAILED;
потерянный ответ с применённой записью → DONE; потерянный ответ + нечитаемое состояние → UNKNOWN, шлюз закрыт,
исполнитель не читает роутер, позже восстановление → DONE; чужая правка той же группы → UNKNOWN, правка
пользователя не откатывается; SIGKILL всей группы процессов до/после применения → FAILED/DONE по
восстановлению, остатки временных образов удаляются; два исполнителя
одновременно → ровно одна запись; reference-only/manual/старое поколение/нет группы/дубль группы/инъекция
в имени → отказ до записи. Шаг AGH: реальный `vward-ads-privacy-control.sh smartdns-take` против фиктивного API
внутри журнала — без чужих правок DONE; с правкой пользователя после POST — UNKNOWN, строка пользователя
сохранена, улики recovery на месте, шлюз закрыт. Регрессии безопасности: исполняемый файл с маркером stand-in из
окружения не запускается (след не появляется), symlink/чужой владелец/общие права у данных эмулятора — отказ.
Мутации семи защит (выключатель, запрет окружения, права, владелец, шлюз, очистка остатков, сверка
повторным чтением) роняют тест.

Приватный образ `pre` (0600 в каталоге 0700) может содержать URL upstream — как существующий `dns.before.json`;
записи журнала — только закрытые токены.

### E.2. Следующий безопасный этап (без включения записи)

Наблюдаемый «теневой» прогон сухого исполнителя на эмуляторе CI (`tests/perf`) поверх реальных снимков
`vward_routing_consistent_read` и решений `vward_routing_plan`, плюс read-only проверка FQDN-маршрутизации
Supercell на устройстве (`DIAGNOSTICS_SUPERCELL_2026-10-31.md` §5). Включение настоящей записи — только после
адресного независимого аудита и отдельного разрешения владельца.

## F. Уточнение 04.11.2026: единое намерение и первый writer

**Статус: проект/чистая тестовая модель, live execution выключено.** Основание — поручение
владельца Unified Routing/DNS от04.11; база dev3f4802b, PR37 слит, fix35.6 опубликован отдельно.
Это уточнение B и разделов B–E выше, не разрешение подключить общий writer или выпустить пакет.
Критические поправки PR37 не копируются; VERSION/feed/package-map/активные настройки не меняются.

### F.1. Дельта и выбор пути

| Уже есть | Точка кода | Разрыв / следующий шаг |
|---|---|---|
| Pure M/S/A audit | vward-routing-audit.sh / vward_routing_audit | Нет явного service mode и различия off/ISP; v1 остаётся совместимым |
| Native read/identity/snapshot | vward-routing-read.sh / vward_routing_read, vward-routing-snapshot.sh / vward_routing_consistent_read | Health/client path unknown; новый choice state ещё не входит в fingerprint/stage |
| Пять observers/shadow | vward-routing-observe.sh / vward_routing_observe, vward-routing-shadow.sh | Отражают legacy решения, не согласуют их; CIDR фактических policy/mark не моделируется |
| Planner/journal/file emulator | vward-routing-plan.sh / vward_routing_plan, journal/dryrun | Только none/add, permit никогда granted; не DNS/move/remove/restore executor |
| Service/DNS исполнители | console-config.sh: op_service, op_domain_list, op_ai, smartdns helpers | Каждый защищает свою дельту; op_ai не объединяет M/A/persist/IP-источники |
| Auto/persist/reconciler | route-engine: handle_adaptive/add_adaptive/restore_adaptive_from_persist; reconciler: adaptive_names/remove_adaptive | Не потребляют единый явный выбор, могут восстановить старое намерение |
| UI configuration evidence | api.cgi ai-data; console.js aiPage | Уже selected/effective/coverage/storage, ещё нет общего operation state всех источников |

| Категория дельты | Состояние этого этапа |
|---|---|
| Готово в изолированном коде | Canonical choice и policy **одного подготовленного atom**; v1 audit не изменён |
| Только dry-run | Legacy snapshot/shadow/none-add plan/журнал/эмулятор, без новых форматов и live permission |
| Отсутствует | Stage binding/epochs, общий typed delta, per-operation health, migration, live coordinator, Auto/restore/policy wiring, shared API/UI |
| Нужна Keenetic-приёмка | Новые переходы/повторы/persist/restart, IPv6/client policy/DNS lifecycle и MIPS стоимость; Claude IPv4 08:30 уже подтверждён отдельно |

Рассмотрены: локальные заплаты каждому writer (сохраняют рассогласование/многократные reads),
новый независимый controller (дублирует исполнителей/locks/истину), продолжение B (выбрано
владельцем). Минимальный B-путь: один сервисный выбор → нормализованные вклады/конфликты →
план/прежние executors → readback. Никакого daemon/timer/poller или третьего набора writers.

### F.2. Данные и операции

Формат CHOICES и pure API — ROUTING_AUDIT_CONTRACT.md. Это один service-intent, а не
второй enabled.tsv: будущие legacy registry/сегменты/тумблеры — проекции принятого состояния.
До подключения authoritative choice **не сохраняется на устройстве** и не влияет на legacy.

| Действие | Изменение service choice | Что сохраняется |
|---|---|---|
| on / явно VPN | mode=vpn, выбранный tunnel, DNS default | M/A происхождение и совместимые references, данные возврата в operation journal |
| off при VPN | mode=auto, только S VPN-вклад снимается | Независимые M/A остаются, off не ISP-pin |
| off при DNS/ISP/auto | no-op | DNS/ISP choice не стирается от программного отображения VPN-off |
| явно DNS | mode=dns, ISP+поддержанный DNS policy ID | Desired отдельно от applied; history Auto сохраняется, активный конфликт требует safe delta |
| явно ISP | mode=isp, ISP/default | Auto не переопределяет pin, соседние ручные правила не удаляются |
| вернуть Auto | mode=auto, clear pin | Если ранее DNS/ISP — AUTO_FLOOR повышен, старый persist не становится новым положительным доказательством |

Дополнение M/S/A: 8/24 относятся к наличию VPN-вкладов, не к четырём значениям service mode.
MODE=dns имеет выключенный VPN-тумблер, но действующее service DNS-намерение. Глобально
недоступный источник с сохранённым pin даёт blocked/unknown, а не разрешение Auto/ISP fallback.
Новые подтверждённые собственные домены получают прежний mode без предварительного Auto-add.
Membership/revision ресурса отделяется от стабильного service ID; каталог/shared-host не proof.

Для новой policy-проекции: BINDINGS связывает стабильный service scope с нормализованными
S-ref и подтверждённой атрибуцией домена; A evidence различает observed-active, новую positive
probe и history. При DNS/ISP A-вклад suppressed; при VPN несовместимый A suppressed, совместимый
может использовать ту же запись. History/unknown не разрешают restore/add. После выхода из
DNS/ISP active evidence должно быть не старше AUTO_FLOOR, новая probe — текущей REV.
Противоречащие явные M/S choices → unresolved независимо от порядка. Внешние маршруты не
исчезают из observed coverage из-за suppression desired: до точного удаления/readback переход
не применён. Legacy/unknown AdaptiveAuto не получает ownership от имени группы/persist.

### F.3. Первый предлагаемый live путь — только после отдельного GO

Один сервис → VPN **в чистой области** или reuse полностью совместимого покрытия.
Предусловия: verified snapshot/generation/identity, однозначный tunnel, отсутствие DNS/ISP
pin/внешнего конфликта/recovery/неизвестного CIDR или client policy; подтверждённый own scope.
Нет права на существующую группу — reference либо отказ; новый собственный ресурс можно
создать только прежним writer с durable creation proof. Legacy/manual/AdaptiveAuto не усыновляются.
Smart DNS-сервер/AGH не являются зависимостью этого VPN-only пути.

Lock order проектируется по фактическому console пути: existing admission → EDIT → CHANGE,
затем приватный journal lock, без удержания parent EDIT при вложенном CLI, который берёт EDIT
сам. Выбор: один внешний coordinator удерживает операционные locks, внутренний worker вызывается
как функция через проверенный internal API; произвольный флаг «пропустить locks» не вводится.
До такого refactor первый live caller не подключается. Update/recovery barrier не меняется.

Конкретные границы refactor (проект, код пока прежний): console `op_service on ID TUNNEL`
после валидации ID/catalog/profile/pending-check передаёт подготовленный план coordinator.
Existing `service_txn_new_group`, `service_claim`, `service_state_set` и часть `service_route`
выделяются в internal locked workers **того же скрипта**, не новый executable. Нынешний
`op_service` отпускает CHANGE перед `service_route`, а helpers берут его сами; такую цепочку
нельзя просто вызвать под внешним CHANGE. Workers не получают флаг обхода locks от API/env:
locked context создаёт только coordinator после admission/EDIT/CHANGE и сверки snapshot.
Обычный legacy CLI продолжает брать locks через wrapper. Create/route/save/local-registry шаги
получают один parent journal, а не два независимо committed перехода. Перед wiring нужны
fixture конкуренции обоих wrappers, отказа save, killed parent/worker и freshness Gi.

Порядок: snapshotG0 → validate/no-write plan → journal pre+expected post → write → invalidate
cache → fresh readbackG1 → verify/save → journal commit и projection. Следующий шаг сравнивается
с доказанным Gi, не с неизменным G0 (исправляет формулировку B.3 для многосоставной операции).
Generation не даёт права: identity/content/ownership и delta всегда перепроверяются.

Компенсация: только обратная собственная delta при совпавшем expected post-image. Lost reply
→ readback pre/post/other; TERM/SIGKILL/reboot → reconcile journal без слепого replay; foreign
edit сохраняется. Новую пустую группу удалять лишь при creation proof и отсутствии иных ссылок.
При сбое commit локальных choice/registry их postimage сверяется перед возвратом; unknown
не закрывает recovery. Совместное состояние next code + state version проверяется перед downgrade.

Первый путь НЕ включает DNS/ISP, потому что эти режимы нельзя честно включить, пока restore,
reconciler/Auto/force-VPN/policy-sync/guard способны вернуть конфликт. После review первого
writer требуется конкретный GO владельца, аппаратная проверка и отдельное решение о выпуске.

### F.4. Следующие связанные пакеты и критерии

- [x] **Контракт/модель (сейчас, одна подготовленная область):** canonical choice transition; 8/24 и повтор; off не ISP;
  DNS/ISP projection не service-on; peer conflict и suppress-history модель; poison paths,
  input immutable, bounds, BusyBox. Runtime вызовов/нового persistent state нет.
- [ ] **Read adapters/coordinator:** choice/membership/Auto evidence входят в stage/fingerprint/
  generation; одна сборка на operation, не полный config на каждую строку. Versioned state
  migration и rollback до прежнего формата сначала на fixture. Missing tool → unknown;
  comm/cksum на Keenetic не предполагаются.
- [ ] **Planner v2/dryrun:** typed add/remove/move/DNS/hold delta, physical refs и dependents,
  scope/exclude/shared IP conflicts, per-backend dependencies/capacity. Старый journal не
  принимает новый plan как granted; новая схема/валидатор и postimage recovery проверяются.
- [ ] **Первый VPN writer:** проект F.3, тесты отказа/потерянного ответа/поколения/конкуренции,
  независимый адресный audit, затем отдельный GO. UI до подключения не обещает общего apply.
- [ ] **DNS/list transition:** Keenetic8 + AGH API/readback/upstream_dns_file/unknown POST;
  URL-wide removal учитывает соседей; deletion/migration server — явный plan и возврат,
  old URL tombstone согласован с saved/proofs/queue. dnsmasq writer не выдумывается.
- [ ] **Auto/restore/reconciler затем policy/guard/CIDR:** все пути потребляют принятую REV/
  suppression, не воскрешают withdrawn history; совместимые refs не плодят physical rules.
  Промежуточная частичная цепочка остаётся выключенной, без hidden ISP fallback/global kill switch.
- [ ] **API/UI:** один operation outcome и desired/configured/client-verified со source/coverage,
  partial/mixed/unknown и причиной; busy конечен, batch по каждому сервису. Существующий storage
  selector сохранён, технические группы в details, длинные статусы без обрезания/дублирующего403.
- [ ] **Admission:** адресные RED→GREEN → штатный CI exactHEAD → согласованный Keenetic test →
  отдельное решение по архитектурному выпуску. VERSION/sequence сейчас не назначаются.

Стоимость: pure модель — только bounded awk/sh, 0 ndmc/RCI/DNS/AGH и 0 writes. Для wiring
измеряются config reads, elapsed/CPU/RAM/flash по operation; budgets/timeout не увеличиваются.
Cross-system Keenetic+AGH atomicity не обещается. Доказательство client IPv4 Claude наfix35.5
04.11 08:30 уже получено; оно не доказывает IPv6/весь каталог и не повод повторять сетевой аудит.

Связанная правка Панели этого этапа: фактический aiPage row оставлял статус в той же flex
строке, что кнопку; теперь статус — отдельный полноширинный ребёнок header. RED→GREEN
реального template/DOM в check-console-diag-ui.py, прежние status/DNS guard/spinner assertions
сохранены. Responsive/storage/evidence проверки PASS; визуальный Chromium локально SKIP
(playwright отсутствует), требуется штатный CI. Это не новый shared API/apply.

Локальный полный consistency выполнен однократно: **FAIL** на старом check-dryrun.py:199,
ожидалось done, получено failed. Адресное чтение stderr того же fixture подтвердило
`mkdir: cannot create directory /opt/var: Read-only file system`, затем отказ создания component
directories. Production dryrun/control этим этапом не менялись; ограничения host не обходились,
assertions не ослаблялись. Пройденная до отказа часть включает новый model, прежние identity/
snapshot/shadow/observers/planner/journal и каталог AI. Остаток полного local suite не проверен;
точный final HEAD требует своих штатных repository-consistency/updater-tests/resource-audit.

### F.5. Границы DNS и данных до проекта подключения

Общий результат операции включает две оси target+DNS policy. ID policy не хранит URL/token;
выбранный сервер и подтверждённое фактическое размещение учитываются отдельно. Недоступный
выбранный сервер → blocked/unknown с сохранением pin, без молчаливого ISP fallback.
VPN-only не зависит от истёкшего Smart DNS и не пробует его. Pure policy выше не проверяет health.

Keenetic plan считает **все** занятые HTTPS upstream строки и весь delta до первой записи
(8 — предел устройства, две NextDNS и чужие записи не вытесняются). AGH допускается только
при поддержанном active handler/API/readback; installed не значит active. При upstream_dns_file
нынешний writer отказывает: до отдельной реализации нельзя обходить это переносом в API.
Неизвестный POST удерживает private before/planned и barrier до сверки; blind replay запрещён.
dnsmasq не является Smart DNS backend без проверенного writer.

Удаление/смена сервера — один явный план собственных точных строк, всех dependents и saved/proofs/
queue/persist/cache. Deleted policy получает tombstone/revision; restore проверяет её перед записью,
чужие upstream остаются. Migration storage не происходит от переключения selector. Сначала
fixture обоих backend, заполнения 8 слотов, отказов по шагам и lost reply; затем отдельное GO.

До live требуется схема BINDINGS (exact/subtree, excludes, unknown attribution, CNAME/family/
client-policy evidence), staged fingerprints без предположения comm/cksum, referential checks и
state-version migration. Нынешняя pure projection принимает только подготовленный atom, не
доказывает wildcard/IPv6/QUIC/CDN scope. Тесты downgrade должны покрыть следующий code+state,
старый code+restored state и refusal несовместимого состояния. Файловый rollback updater отдельно.
Промежуточный pipeline не включается в API/Панель, пока persist/restore/policy/guard могут его отменить.

## G. Программное продолжение PR38 (поручение 04.11, исполнение только на fixtures)

База `8ab46d5`; CI модели на479f268 уже принят. Это продолжение F, без нового live caller,
пакета/VERSION/feed/merge. Один исполнитель; адресный review coordinator/ownership/recovery
проводится после сквозных регрессий, до проекта первого включения. Никакого повторного общего аудита.

### План связанных изменений

- [ ] **Согласованный stage v2.** В existing snapshot library добавить проверенную копию choices,
  bindings/excludes, Auto evidence/epochs, схем, native resource view и exact identity proofs.
  SHA256 + bytes/inode/mtime до/после; generation по content, без comm/cksum. Версия/пределы,
  недостающий/изменившийся/неполный input → unknown; один stage на операцию и fresh Gi после записи.
- [ ] **Связанная policy/typed plan v2.** Использовать реальный canonical choice и service policy
  из audit, не отдельную копию приоритетов. Desired и все observed resources сохраняются;
  compatible references переиспользуются, один effective rule имеет несколько consumers.
  План хранит конкретный resource ID/scope/proof/consumers/pre/post/check/own inverse;
  create/add/remove/move/hold, local states и server deletion/migration. Формат v2 старым journal
  не принимается. Только зависимости затронутого backend (VPN не проверяет Smart DNS).
- [ ] **Версионированные данные.** Приватная backup/migration/version guard/downgrade; old code
  читает только восстановленную old schema. Tombstone/epochs и withdrawn saved/queue не возвращают
  удалённый сервер/Auto. Совместимость кода и данных проверяется отдельно от updater file rollback.
- [ ] **Parent journal/coordinator/locked workers.** Журнал pre/post до write, фиксированный
  порядок admission→EDIT→CHANGE→journal, без child CLI, повторно берущего эти locks. Никаких
  API/env bypass flags или выбираемого исполняемого файла. Default/live OFF; встроенный emulator
  и существующие native writer fixtures — единственный исполняемый путь на этом этапе.
  Потерянный ответ классифицируется readback, Gi обновляется после собственного шага;
  save/local commit обязательны; компенсация CAS только своей resource delta, foreign edit сохраняется.
- [ ] **Сквозная регрессия на одних входах.** 8/24/repeat, all mode transitions, M/A/shared refs,
  new names/excludes/subtree/unknown, both DNS stores/capacity8/URL dependents, delete/replace,
  stale epochs/reboot, migration/downgrade, fault each significant step/save/local write/lost reply,
  TERM/SIGKILL/competition/reused ID. Реальные существующие executor functions проверяются с
  подставными ndmc/AGH в той же цепочке, не только эмуляция результата planner.
- [ ] **Адресный review, финальные ворота и передача.** Только новый конечный code HEAD получает
  один полный штатный CI; source-модель и её старый CI повторно не прогоняются ради отчёта.
  Измеряются reads/transports/writes/elapsed, не увеличиваются бюджеты. Затем конкретный готовый
  VPN-only проект подключения/выключения/отката/одна owner acceptance с остаточными рисками.

В этом плане off-worker не является разрешением live wiring; общий pipeline нельзя объявить
выпущенным обновлением. Пока не закрыты все связанные backwriters/restore/reconciler/policy/guard,
DNS/полный режим не включаются пользователю. Исторический local full FAIL read-only /opt/var
и local Chromium SKIP сохраняются; новый программный пакет требует собственных доказательств.

### G.1. Текущий программный checkpoint (продолжение, не финал)

| Категория | Состояние |
|---|---|
| Закрыто кодом в подготовке | Stage v2 со всеми decision inputs под native generation/SHA seal; native inventory stable ID/content/proof; настоящий choice→policy→typed plan; parent journal v2/Gi/save/CAS inverse |
| Подтверждено адресно | sh/BusyBox1.37 ash+awk: stage copies/изменение inputs/missing/FIFO/symlink; native manual conflict; peers/history/freshness/excludes/new subtree child; typed preview/foreign reference/Keenetic8/AGH-file/tombstone; format rejection старым journal; parent child readback/Gi/save/replay/corruption/own inverse |
| Блокирует подключение | Coordinator+locked native workers, связанные migration/downgrade и server lifecycle, весь chained fault fixture и targeted review ещё не завершены |
| До рабочего обновления | Общий outcome/API/UI + backwriter fences, конечный CI нового code HEAD, конкретный готовый VPN-only activation проект и отдельное согласование владельца; hardware приёмка отдельно |

Уже зелёный CI41815122230 относится к479f268 и не покрывает это новое продолжение. Новых
часовых/full CI на каждый внутренний модуль нет; один штатный прогон после связанной подготовки.

### G.2. Сквозной OFF checkpoint (продолжение, не разрешение live)

`vward-routing-workers.sh` по typed route atoms компилирует один physical group step и
отдельные native proof / resources / content proof / choice / legacy registry steps.
Pre/post sidecars и закрытый command set закреплены SHA в immutable parent plan. Все
предсказуемые intermediate group images записаны **до** первой команды. Перенос tunnel
сохраняет resource ID и creation origin; меняются native placement и content revision.
Неизвестный body/exclude/options или неполное покрытие группы не перезаписываются.

`vward-routing-pipeline.sh` исполняется только над приватным DATA emulator `JDIR/.emu`,
под прежним default-OFF gate. Реальные console `group_set` и internal worker проверены
на fixed emulator ndm; исполняемый файл из env/API не выбирается. Единственный envelope —
existing admission → EDIT → CHANGE → краткий journal lock; вложенного console CLI нет.
Worker lease сохраняется до последнего возможного rename; pending/unknown не допускают
forward replay. Новый snapshot после каждой logical delta даёт Gi, обязательны save и
проверенная local registration. `committed` означает только конфигурацию fixture,
client-path остаётся `false`; router/RPC/DNS/AGH calls этим checkpoint не выполняются.

Explicit OFF compensation разрешена только из exact own postimage либо заранее sealed
prefix. Inspect ничего не повторяет. Foreign edit удерживает barrier и свои байты;
baseline closure требует отдельного rollback-save и проверенных исходных scopes.
Частичный native отказ и save failure воспроизведены в одной цепочке с readback.

`vward-routing-migrate.sh` проверяет пару code/state version, private before/after seal,
переводит старое activity в history и восстанавливает baseline побайтово только из своих
неизменённых images. Новый принятый choice/foreign data запрещает downgrade до первой
записи. Это **fixture state migration**, не доказательство миграции всех installed
legacy return states или отката пользовательских данных updater на устройстве.

Адресные sh/BusyBox1.37 checkpoint-тесты прошли для начальной цепочки on/repeat/off,
private migration/downgrade, partial prefix и отказа save; последующие stable move,
новое имя, foreign edit, SID `@`, literal-IP refusal и A-only withdrawal проверяются
отдельно. SHA/owner/mode участвуют в snapshot fingerprint; изменение прав proof между
проекциями воспроизведено RED→GREEN. Context boolean не создаёт отсутствующий в native
profile VPN target. Повтор native M для точно доказанного common-owned resource не
становится новым ручным основанием; неизвестный origin не подавляет native manual.

**Ещё не закрыто:** общий DNS physical compiler/оба backend и server lifecycle; полный
legacy migration и tombstone/backwriter fences; связанный 8/24 и TERM/KILL/concurrency
matrix; общий API/UI outcome и один адресный review; новый конечный CI. Новые библиотеки
не добавлены в signed targets, callers/UI не подключены. Старый CI479f268 не покрывает
этот код. Работа продолжается в той же ветке без промежуточного merge/release/GO.

### G.3. Связанные DNS и server lifecycle на DATA (продолжение, live OFF)

Один lowerer и `vrb_execute2` теперь используют те же stage/choice/policy/plan/J2/Gi для
VPN и DNS. Keenetic: whole HTTPS scope, фактический лимит8 со всеми global/foreign строками,
sealed URL-wide commands и prefix images, существующий `doh_remove_url`. AGH: существующий
`ads_smartdns_locked` сначала на приватной копии для компиляции, затем на DATA API под настоящим
component lock; отдельный точный take-pairs сохраняет другие URI и соседей shared row. Это
не HTTP/NDMC, не новый transport и не установленный caller. Plain DNS/dnsmasq не объявлены backend.
URI связывается SHA256/192 с opaque container, не mutable URL alias. Own DNS proof содержит
revision + content witness; чтение конфигурации остаётся reference без права присвоения.

Parent suffix агрегирует совместимых consumers, exact child наследует подтверждённый parent;
excluded/conflicting child удерживает весь план. Native include остаётся exact даже при subtree
принадлежности сервиса: новая подтверждённая запись наследует намерение отдельно. Выключенный
S снимает вклад, сохраняя accepted choice; legacy enabled выводится из действительных собственных
S claims при каждом изменении. Foreign registration collision удерживает запись. Неизменённый
DNS backend не проверяется и его evidence не освежается ради чистого VPN другого сервиса.

`vward-routing-lifecycle.sh` переносит свои DNS resources на новый endpoint с прежними RID/birth
и очищает dependents обоих хранилищ, saved/queue, Auto activity и accepted DNS choices при delete.
Политики одного location key учитываются вместе. Withdrawal SHA закреплён в immutable plan
до backend write; tombstone монотонен. Подстановка старого ledger/downgrade не отменяет withdrawal.
Это unpublished state2 bookkeeping, **не** импорт всех installed legacy saved/queue. Unknown
server operation не разрешает inverse, возвращающий отозванный endpoint; нужен отдельный
проверенный шаг восстановления, а не blind replay. Потерянный AGH POST оставляет before/planned,
request.pending и parent barrier даже при совпадении postimage; автоматического восстановления нет.

Уточнение прежнего G.2: одного outer worker PID недостаточно. Финальный DATA publisher теперь
сам exec-процесс с durable PID/start/boot/SHA lease; quiet gate и повторная проверка живого
владельца действуют до exec. Это доказывает DATA publication, не завершение будущего NDMC/HTTP.
Существующие EDIT/CHANGE пути и реальный console `dir_lock` общие для legacy/B fixtures;
empty/unproven holder не отбирается. Остаточные stale-lock/reboot/legacy backwriter границы
подлежат полному fault matrix и одному адресному review до проекта подключения.

Локальные file modes/UID берутся из sealed inputs.fp, SHA attrs включён в plan. Registry0644
разрешён только по его точному пути; private400/600 сохраняются, новые private leaf600.
Свежий tmp + leased rename/unlink не следует symlink/hardlink; чужой chmod не становится own Gi
и не перетирается компенсацией. Save нужен только для native group/Keenetic; AGH/local-only
не сохраняет посторонний running-config.

Адресно проверено: sh connected native/DNS cycles/repeat/local failure/CAS inverse;
BusyBox1.37 ash+awk — plan/subtree/shared/exclude, реальный AGH helper, native Gi/foreign edit/
save/legacy barrier, file modes/chmod и server replace/delete. BusyBox отказ `$6++` воспроизведён
минимально и заменён на `$6=$6+1`, без ослабления assertions. Sh connected cube прошёл
8 состояний/24 направленных перехода/8 повторов: 24 native DATA calls, host377.33s, не MIPS.
SIGKILL actual final publisher / orphan, hardlink и реальные legacy lock contenders проверены
адресно. Это разные локальные checkpoints, **не** единый финальный exact-tree CI.

**Следующее в той же подготовке:** реальный legacy import/downgrade и eligibility/fences для
старых raw saved/persist/queues; полный fault/TERM/KILL/reboot/reused-ID matrix; общий structured
outcome/API/UI (desired/configured/client-verified=false); один адресный review, регистрация новых
tests и один штатный CI конечного нового HEAD. До этих ворот нет live GO/merge/release и нет
аппаратной приёмки. Старый CI41815122230 не относится к новому коду; исторические local full
FAIL read-only /opt/var и Chromium local SKIP не меняются.

### G.4. OFF migration, lifetime, final dispatch и общий outcome (05.11.2026)

| Категория | Текущий факт |
|---|---|
| Закрыто кодом подготовки | Consistent bootstrap0→legacy import2; normalized1→2/downgrade; version-last state-set в J2; actual console/AGH workers на fixed DATA; saved/proofs/profile prune; common outcome/API serializer/optional gray UI |
| Safety | PID/start/**boot** final leases; cooperative lock election/release включая v1; per-publisher dispatch scope receipt; full-content CAS + owner/mode + ancestry; probe native boot/deadline≤55s; unknown AGH POST persistent barrier |
| Подтверждено адресно | Native/DNS cycles, both stores/capacity8, cube8/24/repeat, migrate/downgrade, foreign chmod/edit, stale/ABA/orphan/zombie/reboot, source lifetime, API/UI и отрицательные controls на разных локальных checkpoints; один addressed review без оставшихся Important в его OFF scope |
| Ещё ворота | Финальный связанный повтор, регистрация32 новых cases в штатном CI и один новый exact-tree полный CI; старые local full FAIL/Chromium SKIP не переписаны в PASS |
| Не подключено | Новые libs не в package-map/signed targets; обычные legacy/updater callbacks не вызывают подготовленные eligibility/reconcile functions; API endpoint/actions не включены; никакого router/NDMC/HTTP |

`vward-routing-state.sh` агрегирует12 local leaves в один sealed physical state scope и
компилирует все forward/inverse prefixes до BEGIN. Это устраняет50 повторных stage reads
на каждую leaf, а не увеличивает45s budget. Импорт архивирует старые return/Dproof как opaque
данные, proof не присваивается по имени. Downgrade требует exact postimages/content/mode/UID
всех baseline inputs и не опускает withdrawal floor. Saved/queue/history не оживляют server.

`vward-routing-dispatch.sh` отделяет issued attempt от одного matching image. Final DATA
publisher после preflight пишет receipt, связанный с OP/step/plan/scope SHA и собственной
lease; после flush снова проверяет owner/barriers/ancestry/full CAS. Known late refusal
снимает новую receipt. Forward replay запрещён, явная inverse принимает только собственный
issued post/prefix и exact CAS; unknown AGH POST не разрешается matching body. Receipt —
свидетельство authorized attempt, не ACK hardware и не проверка клиентского пакета.

Общий outcome выводится из свежей projection и J2: desired отдельно от configured,
M/S/A являются источниками, не режимами агентов. Нет или устарела evidence — unknown/history,
partial/mixed показаны отдельно. `activation=off`, `client_path_verified=false` неизменно.
Serializer принимает bounded owned JSON+SHA и разрешённые presentation fields; endpoint
не добавлен, optional UI note не меняет действия старой Панели.

**Один конкретный следующий этап VPN-only (§F.3), ещё без разрешения live.** После зелёного
exact CI предложить только переход одного доказанного service-owned native FQDN scope
между подтверждёнными VPN targets, с неизменным RID и private registration/proof. Entry point —
отдельный B service action, тот же admission→EDIT→CHANGE→J2; internal group worker без child
CLI. До первой записи все пересекающиеся console/list, Auto/restore, reconciler/policy/guard
callbacks обязаны вызывать scoped eligibility, а updater — pending/unknown + publisher
quiescence; старый код предварительно quiesce. Handoff в common reconcile после выхода из
старого lock, не вложенный CLI. Prepared bridge **сейчас не wired** и один shared lock этого
не заменяет. Native transport должен иметь собственную завершённость/lease/readback/save,
не полагаться на DATA rename receipt. Package-map/admission integration — только в этом
отдельном согласованном этапе, не в текущем PR38 checkpoint.

DNS/ISP/Auto writes, manual/unknown/shared conflict, migration server и clear/adopt не входят
в первый live action; при неизвестной области отказ до write. Выключение закрывает новые
entry points, сохраняет private pending и inspection; при unknown не fallback к старому
writer. Откат к old code только после quiescence и доказанной собственных CAS compensation,
baseline save и совместимости state schema; не blind replay и не восстановление удалённого
endpoint. Одна owner acceptance: один service-owned VPN move→repeat→обратно, actual native
route/registry/claim и сохранность ручных правил; отдельно TERM/restart/persist. Остаточные
риски — настоящие NDMC latency/orphan, все legacy entry points, power loss и клиентский путь.
Это проект границы следующего GO, не выполненное подключение/установка или выпуск.


Дополнение G.4 (тот же финальный пакет): выявленный native move timeout45 не обойдён.
Профиль показал повторный `vrj2_step_valid` каждого terminal history leaf в одном gate.
Первый проход теперь также проверяет committed→done, cardinality совпадает с sequential
unique plan; exact row/seq исключают alias/extra, число исключает missing. Ни один leaf
не пропущен, hash/schema/save/resolved guards прежние. Cost RED→GREEN + отрицательные
missing/alias/non-done checks sh/BusyBox PASS; адресный review подтвердил эквивалентность.
Connected native suite sh PASS260.64s при прежних45s каждого invoke. Это host fixture,
не замер latency реального NDMC. Старый fault hook foreign-after скорректирован на внешний
edit ПОСЛЕ own DATA publication: собственный planned candidate остаётся sealed, чужой edit
не получает receipt, не принимается как свой Gi и сохраняется при отказе inverse.


Финальный адресный повтор runtime `a5814b391a1f85345d2de99e798948221d12bc58`:
sh native PASS260.64s; BusyBox1.37 ash+awk DNS PASS339.94s; TERM/SIGKILL PASS44.80s.
Сигналы введены после настоящего native post и поздней local metadata соответственно;
после смерти PID pending сохраняется, inspect не replay, explicit own compensation
восстанавливает byte-exact baseline. Это уточняет pending строки G.4, не переписывает
исторические checkpoint результаты. Регистрация32 новых cases в обеих shell ветках и
один полный exact-HEAD CI — следующие ворота; legacy live wiring по-прежнему отсутствует.


CI42000443090 на77dc027 (05.11.2026): repository-consistency FAILURE до новых suites —
compatibility grep сопоставил запрещённый option literal в комментарии legacy library:56.
Выполняемый metadata reader использует ls -ldn; правится только wording, не guard/code.
Updater/resource jobs при первом чтении ещё IN_PROGRESS; не отменены. Остаток не доказан,
новый конечный HEAD требует своего CI; ни live GO, ни публикации нет.
