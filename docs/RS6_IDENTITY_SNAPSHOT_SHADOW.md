# RS-6 этап 2: постоянные идентификаторы, согласованный снимок, теневое сравнение

База: HEAD PR #20 `80f6ce9` (содержит RS-6 этап 1, код `960ded6`). Ветка и черновой PR —
см. журнал в `docs/AGENT.md`. Всё остаётся **audit/dry-run**: ни одного вызова ndmc/RCI,
DNS, AGH, VPN, исполнителей; новых демонов, таймеров и опросов нет; Панель, VERSION, feed,
подпись и пакеты не затронуты. Новые библиотеки не входят в package-map и не установлены.

## 1. Постоянные идентификаторы (`vward-routing-read.sh`)

Новый режим `vward_routing_read identity` (API `intents`/`snapshot` и лимиты RS5 прежние).
REF больше не позиционный (`m.1.2.3`), а хэш канонической записи:

| Запись | Канон (что входит в хэш) | Префикс |
|---|---|---|
| route (native) | группа, домен, scope, target, DNS | `r-` |
| intent M | `M`, группа, домен, scope, target, DNS | `m-` |
| intent S | `S`, **id сервиса**, домен, scope, target, DNS | `s-` |
| intent A | `A`, домен, scope, target, DNS | `a-` |
| контейнер | `G|группа` (native) или `V|сервис` | `g-`, `v-` |
| содержимое группы | сумма хэшей строк (коммутативная, **не зависит от порядка**) | `c-<16hex>.N` |
| маршрут | `T|scope|target|DNS` | `t-` |

Хэш — два независимых модуля в awk (точные doubles), 64 бита; два разных канона с одним ID
→ `rc 2` (нет частичного stdout). Порядок строк config/persist/enabled/categories и вставка
новой группы не меняют ни одного существующего ID (тест `check-identity.py`). Разные VPN и
прямой ISP дают разные `t-`/REF; одна и та же пара домен+группа на другом target — другая запись.

### Что различается (и не смешивается)

Строка identity: `REF KIND SOURCE CONTAINER CONTENT ROUTE LINK IDENTITY RIGHT`.

- **Идентичность ресурса**: `CONTAINER` (кто) и `IDENTITY`: `verified` — только если приватный
  файл `services/owned/GROUP` (владелец — вызывающий, режим 0600/0400, не symlink) совпадает с
  текущей группой точно; `reference-only` — доказательства владения не было (имя, номер,
  состав доменов, legacy-запись, каталог не доказательство); `unknown` — доказательство есть,
  но не подтверждается (содержимое изменено пользователем, **номер группы переиспользован**,
  небезопасный режим файла, дублирующее объявление группы, config unknown).
- **Содержимое**: `CONTENT` — отпечаток текущего состава; сменился → `verified` пропадает.
- **Источник ссылки**: `LINK` = `native-group` | `runtime-group` (AdaptiveAuto) | `service-link`
  | `adaptive-persist`. Persist/AdaptiveAuto всегда `reference-only`.
- **Право изменения**: `RIGHT` всегда `reference`. `verified` — не разрешение; запись
  по-прежнему требует перепроверки поколения/прав под блокировками (RS7, см. дизайн).

Автоматического присвоения пользовательских групп нет: `verified` возникает только из
уже существующего приватного proof, адаптер его не создаёт. Дублирующее
`object-group fqdn X` теперь делает `M` unknown (раньше молча сливалось).

## 2. Согласованный снимок (`vward-routing-snapshot.sh`)

`vward_routing_consistent_read OUTDIR` (OUTDIR: абсолютный, 0700, свой, не symlink).

1. Отпечаток каждого входа (CRC+размер, inode, mtime; без `stat -c`, которого нет в BusyBox Keenetic: `ls -di`, `date -r`) → **до** чтения.
2. Свежесть общего кэша: `VWARD_ROUTING_CACHE_AGE` (по умолчанию `VWARD_KEENETIC_AGE`=20 с);
   кэш **не обновляется** (никакого ndmc). Устаревший/отсутствующий → unknown.
3. Три проекции (`intents`, `snapshot`, `identity`) из одного набора файлов.
4. Отпечаток **после**; любое отличие (содержимое, inode-замена, удаление dirty-кэша) →
   `unknown changed-during-read`. Метка времени одна не доказательство; номер группы тоже.
5. Проекции сверяются между собой (одни и те же REF).
6. `generation` = хэш **только содержимого** (CRC+размер всех входов): после перезагрузки при
   тех же данных — тот же `g-<16 hex>`; смена данных — другой. В `snapshot` строка
   `snapshot g-… known` вместо `legacy-read unknown`; `generation` пишется **последним**
   (нет файла — нет снимка).

Любая причина невозможности (`config-cache-missing/stale`, `input-unreadable:LABEL` — symlink,
не-regular/FIFO (не открывается), >1 MiB, >256 записей каталога, `reader-failed:MODE`,
`output-oversize`, `timeout`, `changed-during-read`, `inconsistent-projections`) →
`stdout: unknown<TAB>REASON`, rc 3, **ни одного файла**. Повреждённый, но читаемый вход даёт
unknown *источник* внутри снимка (аудит затем даёт `unknown`), а не пустой known.
Пределы: размер/строки читателя (4096/1 MiB/1024 доменов), 256 записей на каталог; время
проверяется постфактум (`VWARD_ROUTING_READ_TIMEOUT`, 10 с: результат отбрасывается), потому
что читатель — функция sh, а не процесс; он ограничен размерами и FIFO-защитой. Память —
ограниченные буферы awk. Кэширование — существующий кэш; фоновых процессов нет.

Честные границы: снимок доказывает согласованность файлов и общего кэша, из которых строятся
проекции; он не доказывает живое состояние роутера (health DNS/AGH/VPN по-прежнему unknown,
packet path unknown). Окно между последним отпечатком и использованием закрывает только
повторная проверка поколения непосредственно перед записью (RS7).

Стоимость (хост, не Keenetic/MIPS): 400 доменов, 161 KiB результата — 0,22 с (sh), 0,42–0,58 с
(BusyBox ash), три чтения читателя + два отпечатка. Лимиты не увеличивались.

## 3. Теневое сравнение (`vward-routing-shadow.sh`)

`vward_routing_shadow GENERATION AUDIT IDENTITY LEGACY` — чистая функция трёх файлов. Не
вызывает route-engine, reconciler, «Сервисы», tunnel-guard, policy-sync, ndmc, DNS, AGH
(тест подменяет все такие команды в PATH «ядовитыми» и проверяет отсутствие вызова).

LEGACY — нормализованные наблюдения `MECH DOMAIN CONFIGURED DESIRED DNS OWNERSHIP ACTION
BASIS` со строкой `generation G`, равной поколению снимка (иначе rc 3 `generation-mismatch`:
входы не один набор). Все поля — закрытые токены/безопасные идентификаторы; URL и секреты
не пройдут (rc 2, без stdout). Лимиты: 4096 строк/1 MiB на вход, ≤4096 строк результата.

Вывод: `DOMAIN MECH VERDICT CLASS SEVERITY CONFIDENCE SOURCES IDS CONFIGURED DESIRED DNS
OWNERSHIP ACTION REASON`, пары `rs=…|legacy=…`; `ACTION` всегда `rs=observe-only`.

| Класс | Смысл | Severity |
|---|---|---|
| `match`, `observe-agrees` | решения совпали (в т.ч. RS наблюдает, legacy пропускает) | info |
| `expected-guard`, `guard-owned-switch` | защитный fallback tunnel-guard / его смена туннеля; у RS нет health | info |
| `source-inactive` | источник выключен для RS, legacy действует | info |
| `rs-unknown`, `legacy-unknown` | снимок/источник/состояние legacy неизвестны | info, conf low |
| `rs-conflict-legacy-picks` | RS хранит конфликт VPN/ISP/DNS, legacy выбирает молча | review |
| `target-mismatch`, `configured-mismatch`, `dns-mismatch` | реальное расхождение маршрута/конфига/DNS | review |
| `rs-no-intent`, `legacy-only-domain` | legacy видит то, чего нет у RS (wildcard/legacy-семантика) | review |

Различие не считается ошибкой, пока оно не объяснено защитным правилом, состоянием VPN и
назначением механизма: route-engine сравнивается по M, reconciler по A, Services по S,
policy-sync по настроенным маршрутам, tunnel-guard — на уровне интерфейса. Если источник M
unknown, маршрутные сравнения не делаются (нет ложных `configured-mismatch`).
Наблюдатели legacy в тесте — **настоящие функции**, извлечённые из исходников
(`is_manual_known`, `adaptive_names`, `service_target`, `collect_vpn_domains`, `lists_best`);
рантайм-наблюдатели для установленных роутеров — задача следующего этапа, здесь не подключены.

## 4. Проверки (хост sh и BusyBox ash 1.36.1; ShellCheck 0.9.0, уровень warning)

| Проверка | Результат |
|---|---|
| `check-identity.py` (перестановка, вставка, VPN≠ISP, reuse номера, чужая группа, дополнительные домены, дубль, небезопасный proof, пропавший config) | PASS sh + BusyBox |
| `check-snapshot.py` (generation, ABA/replace/delete во время чтения, stale/missing/FIFO/symlink/oversize/toomany, pending recovery, лимит, 8 комбинаций/24 перехода, неизменность входов, инертная загрузка) | PASS sh + BusyBox |
| `check-shadow.py` (все классы, детерминизм, перестановка, секреты, лимиты, отсутствие вызовов исполнителей) | PASS sh + BusyBox |
| `check-readers.py`, `run-simulations.sh`, `check-bounded-cost.py` (RS5/RS6 этап 1) | PASS, без изменений ожиданий |
| `check-ads-agh-restore-safety.py` (RED→GREEN, см. RS7_EXECUTOR_WIRING_DESIGN.md §A) | PASS |

RED→GREEN: (1) REF меняется при перестановке строк на старом читателе (`False`) → стабилен;
(2) мутация: отключение сравнения отпечатков → `changed-during-read` не срабатывает → вернуто;
(3) AGH: откат затирал свежую правку пользователя и план строился по устаревшему списку → оба
случая исправлены (охранный откат + проверка неизменности перед POST).

Не проверялось: Keenetic Viva/MIPS (стоимость, flash wear), живой роутер, клиентский путь
пакетов. Полный CI запускается только на конечном HEAD пакета.

## 5. Этап 3 (31.10.2026)

Рантайм-наблюдатели LEGACY реализованы: `vward-routing-observe.sh`, `legacy.tsv` в OUTDIR
координатора, проверенные копии входов (stage), mechanism-level `unknown`, новые BASIS
`force-vpn` и `service-target-defaulted`. Подробности, паритет и результаты —
[RS6_STAGE3_OBSERVERS_PLAN.md](RS6_STAGE3_OBSERVERS_PLAN.md). Исполнители по-прежнему не подключены.
