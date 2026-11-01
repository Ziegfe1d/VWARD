# P-7 + архитектура B: интеграционный кандидат 31.10.2026

## Основание и неизменяемые границы

Ветка `integrate-p7-b-20261030`, отдельный draft PR на dev, без merge.
P-7 #7→#8→#9: 5869f119f6f8c43f001d80c2d6d9da3c24daf9ec.
B #11→#12→#13→#14→#15→#16→#17: f58dd8c73278af4a57455c32f29fc9e46410f884.
Общая база: 9e99cbb52ffb09bc5beb3fb30b648cf1c18c881f.
CI #752 success на P-7; #753 success на aee436c625b53bbbb091f7bb6385b7946fe6a6e2;
#754 success на 98ae9fe194f2d71855ee88b1504a9c929e8c58aa.
У #753/#754 repository-consistency, updater-tests и resource-audit success,
включая эмуляцию, часовой stress, Панель и resource budget. Это результаты
исходных стеков, не доказательство приёмки объединённого кода. Повторов нет.
Новый штатный CI требуется из-за совместного runtime и новых отказных фиксов.

## Разрешение конфликтов и подтверждённые исправления

console-config.sh объединён на уровне функций: SV_TXN и SD_RECOVERY_DIR,
порядок cleanup/сохранения recovery, adds/dels/saved cleanup, EDIT для
services-refresh и smartdns-server/store. Целиком ours/theirs не выбирались.
Сохраняются owner signatures/все route tuples, repeated ownership check,
service durable journal/pending, update admission и CHANGE/EDIT locks.
AGENT объединён по секциям; проверена сохранность каждой исходной строки
журнала обоих HEAD. ROADMAP сохраняет оба набора решений; SHA256SUMS —
из окончательных байтов, не из одной стороны конфликта.

Новые RED→GREEN регрессии:
1. Retained smartdns recovery после POST+lost response не запрещал следующее
   изменение. Теперь routing_recovery_required/75 до dispatch и после CHANGE;
   тот же gate охватывает component/recover и создание/замену туннелей.
2. domain-list VPN take и bypass put регистрировали AGH undo после ответа API.
   Теперь private persistent reservation и inverse/evidence существуют до POST.
   Take восстанавливает точные пары через smartdns-restore, включая несколько
   upstream одного домена. После outage evidence и gate сохраняются.
3. Broad AGH-TAKE после put мог удалить сторонние строки того же домена.
   Такой автоматический inverse не применяется. До POST control сохраняет
   dns.before.json и dns.planned.json; при последующем отказе put считается
   неподтверждённым, возвращается rollback_incomplete и recovery сохраняется.
   Даже если put оказался no-op, неизвестный rollback консервативно блокируется.
   Направленное восстановление и проверка postimage — работа отдельного этапа;
   чужие DNS-изменения вслепую не переписываются.

Private recovery: operation, pairs.tsv, router.undo, при наличии saved.before,
а для put реальные dns.before.json/dns.planned.json. Подписки/пароли и сырые
снимки остаются на устройстве; тесты используют только synthetic значения.
Авто-replay, daemon, таймер и новая настройка не добавлены.

## Матрица совместных проверок

| Сценарий | Проверка / результат |
|---|---|
| AGH отказ/неподтверждённое изменение/откат | SMARTDNS_CLEAR: clear/remove, оба направления domain-list, outage, private recovery, повтор блокируется — PASS |
| API применил POST, ответ потерян | реальный AGH control + fake HTTP; exact restore или fail-closed put — PASS |
| TERM | SERVICE_FAULTS: EXIT compensation — PASS |
| SIGKILL / reboot model | SERVICE_FAULTS: volatile locks сброшены, durable pending сохраняется, повтор и конкуренция блокируются — PASS |
| Локальные stage/catalog/journal/state/restore faults | SERVICE_FAULTS + SERVICE_TRANSACTIONS — PASS |
| Owner edit / reused group / дополнительные маршруты | SERVICE_OWNERSHIP + TRANSACTIONS — PASS |
| Параллельная команда / повтор после сбоя | SERVICE_FAULTS; update barrier сохранён — PASS |
| Persist/DNS ledger rc0 error, mv/read failure | ROUTING_STATE_ERRORS — PASS |
| DNS binding и retry | AGH_BIND, DNS_BIND — PASS |
| Smart DNS + сохранённые возвраты | CONSOLE_DOMAIN_LISTS, CONSOLE_SMARTDNS, ADS_AGH_SMARTDNS, SMARTDNS_KEENETIC_FORMS — PASS |
| Сервисы и выбор туннеля | CONSOLE_SERVICES, TUNNEL_SERVICES — PASS |
| RS5 8 сочетаний/24 перехода, повтор/duplicates/conflicts/health | routing-audit simulations — PASS |
| RS5 bounded cost | BusyBox 64 domains/128 refs, 449454 bytes, 0.168s, прежний лимит 3s — PASS |
| Учёт измерений / route evidence | measurement unit 5/5, ROUTE_PROBE API/UI — PASS |
| sh/BusyBox syntax, ShellCheck error severity | изменённый runtime — PASS |
| Полный штатный локальный consistency | FAIL на check-console-security.py:76; полного локального PASS нет |

Функциональные тесты, требующие admission в этой PID namespace, запускались
через внешний /tmp-workspace harness: реальный admission сохранялся, заменялся
только недоступный PID-start oracle. Это не штатный CI и не доказательство
прохода security/admission на реальном хосте. Сам продукт и CI tests не ослаблены.
Проверки без harness перечислены выше; непройденные/пропущенные проверки
не считаются успешными. Playwright layout в локальном consistency SKIPPED:
зависимость не установлена. Штатный CI должен закрыть эти ограничения.

## Открытые риски и следующий шаг

Аппаратная потеря питания, fsync/носитель, настоящий reboot, live DNS/FQDN,
VPN/ISP и клиентский packet path не проверены. Модель reboot лишь удаляет
volatile locks; она не доказывает атомарность flash. При неизвестном AGH put
автоматическая полная компенсация не обещается, recovery/gate сохраняются.
RS6 идёт отдельным audit-only пакетом; реальный writer требует отдельного
согласования безопасности. Панель сохраняется целиком; будущие M/S/A —
привычные отдельные тумблеры. VERSION/feed/sign/release/dev/main/роутер неизменны.
