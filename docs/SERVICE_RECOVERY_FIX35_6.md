# Сервисы и Smart DNS: критическая поправка fix.35.6

База: `dev` / `385ecd457502748a2bf6bd00d2f845a67ef0a383` (подписанный fix.35.5 / 2026110302).
Ветка: `fix/service-recovery-20261103`. Поручение владельца от 03.11 разрешает этот пакет, PR,
полный CI и критическую публикацию только в dev. fix.36 остаётся отдельным приёмочным выпуском.
Роутер не подключался, установки и изменения конфигурации выполняет владелец.

## Итог выпуска: опубликовано и публично проверено 04.11.2026

**0.2.0-rc.2.fix.35.6 / sequence 2026110401 / IMPORTANT**, только dev.

| Ворота | Фактический результат |
|---|---|
| [CI 41778782842](https://github.com/Ziegfe1d/VWARD/actions/runs/41778782842) | repository-consistency, updater-tests, resource-audit SUCCESS на `f142f567ec13fe28c1c35321fbdb9a28a1b9cb25`; main-only dispatch-transition SKIPPED |
| [PR #37](https://github.com/Ziegfe1d/VWARD/pull/37) | merge `ce767ebfecf3af6fd9b525e3b2b8c11e8e0ea895`, expected_head_sha и `[skip ci]`; tree `86d6d63d29a0b249c9ff95874b65fa3c91c0ec92` полностью равен проверенному |
| [Release workflow 41788816630](https://github.com/Ziegfe1d/VWARD/actions/runs/41788816630) | SUCCESS на source merge ce767eb: validate, reproducible build, release rehearsal, production-sign/stage, staged validation, publish и artifact upload |
| Publish commit | `aa355211f1cdc4130912bd7cff7deb9be8d10c09`, 04.11 10:38:16 МСК; diff с tested f142 — только updates/dev и SHA256SUMS, дополнительного runtime нет |
| Публичные v1/v2 подписи | PASS немодифицированным updater `--self-test`, доверенный production **public** key; private key используется только в workflow |
| Пакет | 643001 байт; SHA-256 `7348515377b845a8441c7cd9d9d096454456791a41d74b7d28a9758721c60f24` |
| Полнота | Все 78 targets, payload SHA/mode и source map совпали с tested f142; v2 map совпал; все 88 уникальных публичных v2/engine blobs проверены по SHA/размеру |

Публично проверены [v1 manifest](https://raw.githubusercontent.com/Ziegfe1d/VWARD/dev/updates/dev/update-manifest.json),
[v2 manifest](https://raw.githubusercontent.com/Ziegfe1d/VWARD/dev/updates/dev/v2/manifest.json) и
[package](https://raw.githubusercontent.com/Ziegfe1d/VWARD/dev/updates/dev/packages/vward-0.2.0-rc.2.fix.35.6.tar.gz).
Параметры подписей: channel dev, sequence 2026110401, priority IMPORTANT, min_vward 0.1.9-beta,
health full, automatic rollback, requires_reboot=false. Это результат проверки опубликованных файлов,
а не вывод из dispatch. Main не менялся. Откат: ранее local13/13 на подписанном fix.35.5 и
exact official rehearsal CI/release SUCCESS; это не аппаратная приёмка Viva. Локальный полный
consistency по-прежнему не объявляется PASS из-за прежнего read-only host /opt/var.

## Установка владельцем и известная граница pending

[Одна команда установки](../tools/termius/install-fix35-6.txt) делает приватные backups VWARD/AGH
и running-config, вызывает штатные signed `--check`/`--apply-pending`, оставляет updater-lock,
barrier/подпись/anti-replay/health/rollback в штатном engine. Nohup job переживает обрыв SSH;
проверяются VERSION/sequence/committed.state и сохранность agent/Smart DNS/service preferences,
NextDNS/OpkgTun4 DNS. Никаких отдельных команд изменения туннелей, маршрутов или режимов агентов.
Резервные копии/полный лог остаются приватно на USB, в репозиторий данные не переносить.

**Открытая граница, выявленная адресным review команды:** native pending не имеет атомарной
проверки expected version/sequence внутри updater-lock. Внешний precheck проверяет только снимок;
конкурирующий `--check` может заменить pending до apply. Команда это явно предупреждает, проверяет
кандидат до/результат после, отказывает при неизвестном feed binding, но **не обещает immutable pin**.
Используется предпочитаемый владельцем штатный pending workflow; env manifest/config override,
новый updater writer или обход lock не добавлены. Поддержка атомарного expected-target — отдельный
пункт ROADMAP, не скрытое свойство этого выпуска. Если требуется строго фиксированная версия,
этот native workflow такой гарантии не предоставляет.

Команда проверена BusyBox syntax/ASCII/строки ≤60/shellcheck; 8 синтетических wrapper-сценариев
PASS: success, busy, wrong version, missing feed, apply failure, protected DNS change, HUP,
live owner lock. Это проверки оболочки с fake updater, не повтор official rollback/работа роутера.
На устройстве команда **не выполнялась**. Прежние подробности/отказы ниже — история подготовки;
финальный опубликованный статус определяется этим разделом. Режимы агентов остаются выбранными
владельцем, клиентские маршруты/приложения/реальный persist и A1/A6/A7/A10 не объявлены принятыми.

## Первичные данные и причины

03.11 владелец подтвердил установленный fix.35.5; SHA-256 console-config:
`e3125936bbf38570ff1ad7312d80426c0e9991fe15b27782d4b10f55a6823eea`.
В 18:31 отсутствующий `comm` дал ложные нулевые diff и `checked`. Старый журнал без PID/op
вызывал ошибки чтения; исчезновение `/proc/PID/cmdline` — нормальная гонка.
В 18:40 ручные domain-list/list-mode для списка 24 успешно применили VPN; параметр `auto`
маршрута Keenetic не является режимом Автоподбора списка.
В 19:05 подтверждена разница `description "ChatGPT"` / `description ChatGPT` при совпадении
всех 10 доменов. Она достаточна для ложного foreign/ownership mismatch; первоначальная причина
прерывания 01.11 не установлена. Владелец архивировал операцию accept: DNS/FQDN до и после
совпали, pending отсутствовал. Содержимое приватных резервных копий сюда не перенесено.
В 19:05 явная VPN-ветка вызвала валидатор до загрузки; это не причина обычной VPN-кнопки.
В 19:10 обычная ветка отказала `service_reference_only`: найден существующий список, но нет
регистрации. Сходство каталога само по себе не даёт права присвоить ресурс.

## Изменения и границы

1. Разность множеств — POSIX awk с проверкой входов и корректными пустыми файлами; все вызовы
   comm в helper заменены. Ошибка чтения не превращается в нулевые счётчики/checked.
2. Канонизация только полных внешних кавычек description без вложенных кавычек/escape.
   Исторические образы для обратных команд сохраняют исходное представление. Смена значения,
   include/exclude, маршрута и изменённое повторное использование ID остаются значимыми.
3. Обычное действие завершает доказанную собственную компенсацию; unknown/live сохраняют барьер.
   При неудаче исходные доказательства не переписываются рабочими файлами recovery.
4. Восстановление связи использует приватный accepted creation journal, authoritative after.enabled,
   точный состав/описание, непротиворечивый маршрут и безопасные данные возврата. При неподтверждённых
   saved DNS или маршруте — отказ до claim/регистрации. Название и процент совпадения не являются proof.
5. Отдельная явная read-only reference после точного предпросмотра связывает уже применённый полный
   маршрут ручного списка, не создавая claim и не выдавая права его менять/удалять. Старый claim
   без доказанной связи не заимствуется. Изменившийся preview отклоняется.
6. У составного AI-перехода есть приватный intent/checkpoint. Проверенный шаг можно повторить
   идемпотентно; retained inflight запрещает автоматический replay даже при совпавшем снимке.
   Живые дочерние helper и возможные ndmc/HTTP writers удерживают защиту. Вывод ребёнка идёт в
   приватный файл, чтобы смерть родителя не убила его cleanup через SIGPIPE.
7. Неопределённость показывается в результате конкретного действия: сравнение списков и DNS,
   явное решение оставить текущее состояние без изменения настроек; доказательства архивируются.
   Общего блока «Незавершённая операция сервисов» при открытии страниц больше нет.
8. Smart DNS требует настроенный отвечающий DoH. Выбранный режим отделён от наблюдаемых путей:
   пересекающиеся ручные списки показываются, отсутствие регистрации не доказывает Provider.
9. Единый блок «Хранилище Smart DNS»: существующий choiceSlider Авто/Роутер/AdGuard Home,
   явное предпочтение сохраняется и без сервера/компонента; фактические счётчики раздельны.
   Авто остаётся Авто, вычисленная цель показана отдельно. Смена предпочтения не переносит данные.
   Доступность определяется существующим DNS-mode и поддержанным writer; dnsmasq writer не добавлен.

## Проверки и независимый аудит

Адресные проверки выполняются до полного CI. Данные тестов синтетические, сеть не используется.
`SERVICE_PORTABLE` прошёл: пустые множества, missing input, quoted/unquoted readback, явный VPN,
реальные изменения, lost registry, запрет stale saved DNS; отдельный fixture владельца — ChatGPT,
списки 3/24, пять остальных регистраций, старый журнал без PID/op.
`AI_INTERRUPTIONS` прошёл: checkpoint после очереди, TERM/SIGKILL, живой потомок, сброс volatile locks
как модель reboot, повтор, обнаружение неподтверждённой DNS-записи и explicit keep без изменения DNS.
Итоговый локальный `AI_CATALOG_CYCLE=PASS`: все 17 сервисов × 2 хранилища и групповое
VPN/DNS/Provider. Финальный assert ранней итерации обращался к удалённому tmp; исправлен,
тот ранний выход не был объявлен PASS. Штатный CI и публикация пока не завершены.

Адресный независимый review выявил два воспроизведённых Important: непроверенный saved DNS при
reconnect и checkpoint до изменения очереди. Добавлены отказы/регрессии. Последующая проверка
нового concurrency diff выявила inflight после смерти shell при ещё живом внешнем writer;
автоматический replay такого состояния запрещён. Гонка замены сервера с возвратом saved DNS
закрыта сериализацией EDIT → CHANGE и SMARTDNS_SET_RACE. Новые saved-образы фиксируют SHA
выбранного сервера: после удаления/замены выбора образ не пробуется и не восстанавливается.
Legacy-образ без marker и без настроенного сервера сохраняет прежнюю проверку liveness;
отсутствие marker не доказывает удаление сервера. Пустой, повреждённый, повторный marker
и ошибка чтения дают `saved_state_unknown` до пробы. AI Provider/DNS не возвращает старый DNS
перед его снятием.
AGH put на другой URI больше не выдаёт успех; потерянный ответ после POST оставляет before/planned
private recovery и ошибку вместо слепой компенсации. UI проверяет результат повторным чтением,
показывает неполное покрытие и пересечения путей. Итоговый review выявил ещё два Important:
поздний owner-edit первого сервиса мог стать ложным composite success, а ошибка чтения нового
marker — понизиться до legacy permission. Оба воспроизведены RED→GREEN: итоговый fresh snapshot
проверяет все завершённые ID, сохраняет owner-edit и сообщает `ai_verification_failed`;
повреждённый proof отказывает. Независимый повторный просмотр закрыл findings без новых
Important/Critical. Ранее пройденные тесты не выданы за текущий полный CI. Проверки повторяются только после изменения
затронутого кода. Production-ключи не читаются, workflow и защиты не ослабляются.

## Выпуск и остаточная приёмка

### CI 41732954957: полный результат и поправка проверки рендера

На точном HEAD `034ad1af98c0580797cd30c0db98aeb9c1fa6123`
[run 41732954957](https://github.com/Ziegfe1d/VWARD/actions/runs/41732954957)
завершён FAILURE: **updater-tests SUCCESS**, **resource-audit SUCCESS**,
**repository-consistency FAILURE**, main-only dispatch-transition SKIPPED.
Штатный release rehearsal, часовой stress, Chromium crawl и resource budget — SUCCESS
в соответствующих jobs; их не запускали повторно на этом дереве.

Конкретный отказ [job 126254734416](https://github.com/Ziegfe1d/VWARD/actions/runs/41732954957/job/126254734416):
`check-console-diag-ui.py` искал буквальные строки `Smart DNS · сервер не отвечает`
и `Smart DNS: сервер не отвечает` в исходнике. Теперь UI собирает их из `sdReason`/`dnsWhy`,
чтобы различать отсутствие сервера, отказ и неизвестный ответ. Отказ воспроизведён локально;
производственный рендер уже выдавал требуемый результат.

Коммит `cf91cf99ef6cdd9edca5ee5d9ad05b213b1c750c` меняет только тест и SHA256SUMS:
вместо проверки наличия исходных литералов исполняет реальные status/aiSlider в Node.
Проверяются «VPN · не проверен», busy-pill/spinner, точная причина Smart DNS, disabled/title
недоступного DNS и доступность VPN/Provider; текущий выбранный DNS не блокируется слепо.
Остальные проверки diagnostics/components сохранены. Локально CONSOLE_DIAG_UI,
SMARTDNS_STORAGE_UI и AI_ROUTING_FINDINGS PASS. Отрицательные mutation controls подтвердили,
что удаление DNS guard, причины отказа или spinner приводит к FAIL; тест не ослаблен.

Production runtime/tree targets не изменены относительно 034ad1a. Но новое конечное дерево
с тестом и журналом требует собственного штатного CI; прежние SUCCESS не переносятся на
другой HEAD. Публикации нет. Локальный полный consistency/аппаратная приёмка не объявлены PASS.

### Новые сведения владельца 04.11 и второй отказ CI

На HEAD `37742c9a77580614a1f7974c2af50eb9f589cc6a`:
[CI 41723677202](https://github.com/Ziegfe1d/VWARD/actions/runs/41723677202) —
updater-tests **SUCCESS**, repository-consistency **FAILURE**
([job 126222735366](https://github.com/Ziegfe1d/VWARD/actions/runs/41723677202/job/126222735366)),
resource-audit при последнем чтении in_progress. Причина воспроизведена: старый тест
domain lists сравнивал все строки после route только с DNS-строками и отвергал новый
`smartdns_config`. Сам marker был корректным SHA-256 пустого выбора сервера.
Проверка не ослаблена: теперь требует точный route, один правильный SHA выбора и ровно
сохранённые DNS/AGH-строки; есть отрицательные варианты missing/empty/wrong/duplicate proof,
лишние ключи и повтор route. Данные fixture переведены на нейтральный `.example.test`.
Отмена этого красного run была отклонена автоматической проверкой как остановка единственного
штатного запуска текущего remote HEAD; обход не предпринимался, run оставлен выполняться.
Новый code HEAD требует собственного зелёного CI, прежний SUCCESS ему не приписывается.

Сводка владельца не содержит установленной версии, окна времени и всех точных FQDN/IP;
результаты ниже **сообщены владельцем, но ещё не коррелированы с установленным кодом**:

| Наблюдение | Что доказано / что остаётся неизвестным |
|---|---|
| Claude: local `ip route get` → eth3; claude.ai в AdaptiveAuto/VPN, два MCP-имени в manual domain-list4 | Локальный lookup и конфигурационные правила — разные факты; MCP-имена не покрывают claude.ai. Клиентская policy/mark и поток не проверены. |
| Cursor: local lookup → eth3; VPN-привязка и регистрация не найдены в проверенной выборке | Полнота выборки неизвестна, Provider по отсутствию registry не доказан. Подготовлен обычный защищённый VPN-переход; на роутере его выполняет владелец. |
| Gemini: DNS RC=143 после ограничения 10 с | Процесс прерван, точный запрос/резолвер/частичный ответ неизвестны; маршрут неизвестен. Gemini не отождествляется с AI Studio. |
| ChatGPT/Perplexity/Grok: одинаковый ответ 8.47.69.0 | Наблюдение сохранено. Источник, CNAME/TTL/кэш/rewrites не установлены; смысл и принадлежность ответа не предполагаются. |

Адресная проверка текущего read-only `ai-data` воспроизвела отдельный дефект: `exclude`
игнорировался, полное VPN-покрытие и eligibility reference завышались. Код `4066ba9` учитывает
исключения в overlap/полном покрытии, не предлагает reference для AdaptiveAuto или excluded
группы; явно возвращает `evidence=configuration`, `client_path_verified=false`. Панель отличает
неполное покрытие от конфликта DNS/маршрутов. Это **дефект отображения, не установленная причина
eth3 на устройстве**. Независимый адресный просмотр JQ/eligibility не обнаружил новых
Important/Critical. Производственные writers, владение и recovery не изменялись.

Новые адресные PASS: Claude через другой источник без registry; неполное и excluded покрытие;
unknown при недоступном снимке; Cursor VPN без обращения к настроенному истёкшему DoH,
идемпотентный повтор, сохранность manual domain-list4 и компенсация отказа save; resolver RC143
не создаёт IP/kernel route или подтверждение клиентского пути. Связанные ai-data/reference,
route-probe/UI, storage UI и icon-system PASS. Marker authorization и server-set race PASS.
В bundled-каталоге этой ветки нет отдельного Gemini ID; `aistudio.google.com` — другой сервис.
Для кнопки проверки API выбирает первый домен каталога (Claude: anthropic.com,
Cursor: cursor-cdn.com); фактический fetched-каталог устройства ещё не прочитан.

Подготовлена одна owner-run read-only диагностика: установленная VERSION/hash/время,
ограниченные registry/claim/saved/persist и ai-data без DoH health probe, рабочий DNS без
внешнего fallback, A/AAAA и доступные CNAME/TTL, условная проверка подтверждённого локального
handler, один клиентский поток по LAN/туннелю/WAN с conntrack/mark и заголовками без payload
в выводе. Недоступные утилиты/chain linkage отмечаются SKIP, не подменяются догадкой.
Приватные адреса клиента и результат команды не помещены в репозиторий. Синтаксис BusyBox,
ASCII, строки ≤60 и shellcheck error-level проверены; **на устройстве команда ещё не выполнялась**.
A1/A6/A7/A10, физический persist/reboot и клиентская приёмка остаются открытыми.

### Отказ первого CI и точечная поправка иконки

PR [#37](https://github.com/Ziegfe1d/VWARD/pull/37), исходный code/docs HEAD
`4b0a3f9b4fc9adb63322eb200bf3d5741969e00d`. Штатный
[CI 41720844865](https://github.com/Ziegfe1d/VWARD/actions/runs/41720844865)
не прошёл: **repository-consistency FAILURE и updater-tests FAILURE**, одна первая причина —
`check-console-icon-system.py:17`, `icons used but not declared: link`.
resource-audit на момент чтения ещё выполнялся; устаревший красный run остановлен,
чтобы не продолжать длительные проверки дерева, уже требующего исправления.
Пропущенные после отказа шаги updater-tests не являются PASS.

Иконка кнопки явной read-only связи использовалась без записи в `ICON_PATHS`.
Коммит `ec7fcaa85d3dc53e39906630512a2793a5bada88` добавил полноценную SVG-цепочку в
существующий реестр; действие, подпись и классы кнопки не изменены. Assert, тест и
workflow сохранены. Локально RED→GREEN: CONSOLE_ICON_SYSTEM; дополнительно PASS —
Node syntax, SMARTDNS_STORAGE_UI, CONSOLE_BINDINGS, CONSOLE_RESPONSIVE.
SHA256SUMS пересчитан штатным скриптом. Новый штатный CI конечного docs HEAD обязателен;
первый отказ на иконке не доказывает исправность остального набора. Точные результаты
нового CI/публикации будут добавлены после ворот; выпуск пока не выполнен.

Большие локальные прогоны и прежний успешный файловый rollback ниже не повторялись
ради одной SVG-записи. Штатный CI и release rehearsal должны проверить новый пакет.

Код сохранён как `755a69e97dfe0f5768a36fa1d315dff1df4d5389`; последующий docs HEAD будет
точкой штатного CI. Локальный откат этого runtime: **13/13 PASS** поверх реально подписанного
fix.35.5 / 2026110302, full health, signed target digest/mode, сохранность чужих файлов,
запрет replay и побайтовое восстановление всех baseline-файлов. Для кандидата использован
только временный rehearsal-ключ; production baseline проверен публичным Ed25519-ключом и
SHA-256 `46d86f008951cfcb3e283cdd56969b00883c02825fef0b3869fed5e7af287f31`.
Target set остаётся 78, package-map и workflow не изменены.

Локальные адресные PASS: portable/reference/transactions/faults/recover/interruption,
AI final verification, transitions/console-ai/ai-data, saved authorization/set race,
storage UI/contract, domain lists/list DNS, AGH control, clear/orphan clear/URL removal;
версия, отсутствие персональных данных, Node/BusyBox ash syntax и shellcheck error-level.
Старый clear fixture локально требовал `VWARD_ADS_BACKUP_ROOT` в temp: default `/opt/var`
на этом host read-only; после явного пути тот же тест PASS. Полный локальный consistency
не объявлен PASS: исторический RS7 dry-run также упирался в `/opt/var` этого host.
Допуск определяет обязательный штатный CI конечного HEAD; защиты/тесты не ослаблены.

Неопределённый AGH POST сохраняет existing private before/planned recovery и общий барьер.
Автоматический AGH replay/новый RS7 live writer не включены; это отдельная архитектурная
граница, а не доказанный успешный откат DNS/AGH.

Кандидат ещё не опубликован: точные HEAD/PR/CI/release run/sequence и публичная проверка будут
записаны после завершения ворот. Откат пакета и откат операции — разные проверки: файловый
updater rollback не доказывает возврат DNS/AGH. Аппаратная потеря питания не моделировалась.
A1/RS7 writer, A6 (AGH writer режима DNS списка), A7 (единое решение по ручным источникам),
A10 (покрытие за пределами ai_main), перенос привязок при замене сервера остаются отдельными
пакетами. Они не закрываются успехом ChatGPT или тестом конфигурации.

После установки владельцем: обычный ChatGPT → VPN из Панели, явный туннель, остальные сервисы
и допустимые обратные переходы; actual route/registry/claim, повтор и перезапуск, отсутствие старого
DNS/блокировки, сохранность ручных списков и других сервисов. Внешние приложения и сайты с клиента,
Ozon/Wildberries, Lampa TV, экраны и ночной IP-скан — отдельная аппаратная приёмка.
Режимы агентов, NextDNS, восемь ручных Google-подсетей и 16 DNS-правил OpkgTun4 не изменялись.
