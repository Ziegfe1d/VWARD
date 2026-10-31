# Архитектура B: первые защитные пакеты

Утверждена владельцем 30.10.2026. Основание: PR #11 и
ROUTING_SOURCES_AUDIT_2026-10-30.md. Выполнение самостоятельное, без выпуска.
Изолированная база: b0bffcc (документы RS-0, продуктовый код dev 9e99cbb).
P-7 не переносится; совместимость с ним проверяется отдельно.

## Контракты и проверка

- POSIX shell, BusyBox/Entware; существующие CLI/API и службы сохраняются.
- Три источника/8 комбинаций/24 перехода относятся к RS-5…7; здесь нет новых
  тумблеров с частично работающей логикой и нет новых демонов.
- Неизвестная принадлежность не разрешает изменять пользовательскую группу.
- Новый тест сначала падает на старом коде по ожидаемой причине; после fix
  проходит вместе с существующими сценариями. Защиты admission не меняются.
- Каждому пакету отдельная ветка/draft PR; зависимые пакеты складываются
  поверх предыдущего без merge. Контрольные суммы обновляются вместе с кодом.

## RS-1: владение сервисными группами

Файлы: console-config.sh, tunnel-quality.sh, тесты console-services и новые
service-ownership; только необходимые сообщения Панели.

- [x] RED: совпадающее имя/80% покрытия не разрешают менять чужую группу;
  legacy enabled.tsv не разрешает off/refresh/retarget/category.
- [x] GREEN: отдельное приватное доказательство созданного VWARD состава,
  сравнение с текущей группой перед мутацией; потерянное/несовпавшее
  доказательство означает reference-only, без автоматической миграции.
- [x] Прежние 3 колонки enabled.tsv сохраняются. Явное управление ручным
  списком через существующий API не становится автоматическим adoption.
- [x] Автоматический подбор туннеля передаёт service ID writer-у, который
  проверяет принадлежность. Новые собственные группы проходят on/off/refresh.

## RS-2: неизвестный снимок и неподтверждённое снятие DNS

Файлы: route-reconciler.sh, ads-privacy-dns-guard.sh, новые отказные тесты.

- [x] RED: refused remove + failed config read стирает persist; refused
  DNS removal стирает запись владения.
- [x] GREEN: чтение возвращает unknown отдельно от absent; persist не
  меняется. DNS ledger сохраняет неподтверждённые строки атомарно.
- [x] Подтверждённое отсутствие/успешное снятие и сохранение ext/failed
  проверены новым отказным тестом и существующим DNS guard test.
- [x] Bounded матрица rc=0 error-text, persist commit/mv failure,
  ledger mv failure и повтор снятия DNS проверена без PID fixture.

## RS-3: транзакции сервисов

Файлы: console-config.sh, service transaction tests; зависит от RS-1.

- [x] RED: неуспешный retarget меняет pin; refresh ломает состав при N-й
  ошибке и при допустимом конечном наборе 300→300.
- [x] GREEN: commit настройки после подтверждения, undo/backup до записи,
  проверка ёмкости дельты, восстановление состава и каталога при отказе.
- [x] Сбой отката видим, recovery не теряется. Save failure, повторное
  применение, чужая группа, ручной edit между снимками и потерянный
  ответ применения маршрута покрыты отдельными регрессиями.
- [x] TERM, SIGKILL с сохранением recovery/сбросом volatile locks,
  повтор/конкуренция, staging/catalog/journal/state/restore write failures
  покрыты SERVICE_FAULTS. Локальный owner edit проверяется по postimage.
- [ ] Реальная потеря питания/повреждение носителя и аппаратная перезагрузка
  не заменены моделированием; совместный P-7 кандидат ещё не принят.

## Последующие пакеты

RS-4: только измеренные оптимизации с одинаковым baseline. RS-5: библиотека
resolve/plan в read-only audit, ownership/permissions и ссылки M/S/A.
RS-6: подключение writer/engine/reconcile/guard/CIDR по частям. RS-7:
существующая Панель целиком, стандартные тумблеры. RS-8: проверка кандидата
без VERSION/feed/sign/release/установки.

Особое внимание review: reused group ID, ручное изменение состава после
создания, ошибочный/потерянный ответ API, сохранение recovery после TERM,
пересечение locks и state между refresh и service off.

Проверка RS-1: SERVICE_OWNERSHIP, CONSOLE_SERVICES, TUNNEL_SERVICES PASS в отдельной ветке; RED на прежнем коде: adoption/off/retarget/category/refresh/auto-writer/edited-owned. Дополнительные RED→GREEN: ручной маршрут, mode=0666, дополнительный ISP-маршрут и edit во время bypass. Проверка ash/sh syntax и ShellCheck error severity PASS на собранном стеке.

Проверка RS-2: ROUTING_STATE_ERRORS: RED unknown lost persist / unbind discarded ledger / ns_release discarded ledger → PASS. Полный существующий ADS_DNS_GUARD PASS с локальным PID-oracle fixture, позитивные absent/present и снятие успешных правил проверены. Пути resolver/backup только в тестовой извлечённой функции перенаправлены в TemporaryDirectory, тест не требует записи в /opt.

Проверка RS-3: SERVICE_TRANSACTIONS: RED failed retarget pin, partial refresh/save, 300→300/idempotency и missing recovery → PASS. Review RED owner edit on third snapshot / applied route with lost reply → PASS. SERVICE_OWNERSHIP, CONSOLE_SERVICES, TUNNEL_SERVICES, CONSOLE_DOMAIN_LISTS и ROUTING_STATE_ERRORS PASS на итоговом коде. BusyBox ash/sh -n и ShellCheck -s sh -S error для четырёх изменённых shell-файлов PASS. Один штатный run-consistency-checks остановился на известном check-console-security.py:76, полный локальный PASS НЕ заявляется.

## Ограничения готовности и интеграции

Пакеты подготовлены для review/CI, не для установки. Проверка
`git merge-tree --write-tree` с P-7 `5869f119f6f8c43f001d80c2d6d9da3c24daf9ec`
(без изменения ref/worktree) выявила конфликты в console-config.sh,
SHA256SUMS, docs/AGENT.md и docs/ROADMAP.md. Интеграционный кандидат
потребует отдельного разрешения конфликтов и регрессий в RS-8;
совместимость двух стеков сейчас не заявляется.

Одно независимое review выявило три важных отказных пути: проверялся
только первый маршрут, off не перепроверял владение после bypass,
компенсация могла перезаписать ручной edit между снимками. Все три
закрыты RED→GREEN регрессиями; полная компенсация также проверяет
случай команды, применённой устройством с потерянным ответом.
Внешнее изменение оставляет pending/recovery и блокирует следующие
сервисные операции; автоматического replay после перезагрузки нет.

Исходный полный локальный run-consistency-checks остановился на
check-console-security.py:76: окружение /proc не даёт штатному
admission подтвердить PID-start. Защиты продукта/CI не менялись;
внешний локальный harness подменял только PID oracle для выборочных
функциональных тестов. Полный локальный PASS не заявляется.
Конечный стек должен пройти штатный CI без этой подмены.

## Продолжение RS-123: уточнение гарантий rollback

Первое on/off теперь используют durable inverse до создания/удаления группы.
Unknown/rc0 error text в любом console snapshot и rollback snapshot не
разрешает компенсирующую запись. Global local files восстанавливаются только
после собственной записи и совпадения ожидаемого postimage, поэтому rollback
не стирает чужой categories edit или добавленную manual строку enabled.tsv.

Успешный дочерний bypass может вернуть DNS/AGH, тогда как последующий parent
commit не состоится. Пока P-7 не интегрирован, проверенная компенсация
группы/маршрутов/файлов не доказывает восстановление внешнего DNS. Private
dns-risk marker и before/after остаются с pending, ответ rollback_incomplete.
Следующие сервисные операции блокируются; широкого AGH retake/авто-replay нет.
Этот отказный путь теперь воспроизведён отдельной регрессией с AGH put.

Полная матрица и границы — ROUTING_B_NEXT_PACKAGES.md; будущая интеграция —
P7_B_INTEGRATION_PLAN.md. На начало продолжения CI #753 для aee436c: repository-
consistency и updater-tests success, resource-audit in_progress. Финальный
результат пока не заявляется; назначенная разовая проверка остаётся отдельно.

## RS-4 и RS-5: подготовлено без применения

RS-4: ограниченные сравнительные измерения четырёх routing hot paths, данные
и ограничения — ROUTING_HOST_MEASUREMENTS_2026-10-30.md. Нет подтверждённого
снижения нагрузки Viva и нет изменения бюджета; production оптимизации отложены.

RS-5: чистая библиотека vward_routing_audit, нормализованные явные inputs,
только stdout. Контракт — ROUTING_AUDIT_CONTRACT.md. Все 8 комбинаций/24
перехода, ownership/conflicts/duplicates/unknown, immutable inputs и отсутствие
записей проверены. Независимый review подтвердил избыточное вложенное сканирование;
после RED >3s bounded BusyBox случай проходит за 0.16–0.21s с теми же
449454 bytes. Сортировка evidence выполняется один раз, coverage индексируется.
Это измерение конкретного synthetic input на хосте; максимум допустимого входа
и работа на Viva пока не приняты. Адаптеров live config/caller-ов нет, реальный
packet path unknown. Следующий этап — RS-6 отдельными read-only адаптерами
с совместными отказными регрессиями, затем поэтапное подключение writer.

План P-7 сохранён отдельно, физический объединённый кандидат не создан.

## Checkpoint 31.10.2026: интеграция и RS6 stage 1

P-7 и B физически объединены merge 656c38e02fc896a4482e644c56e284247c133baa
в отдельном draft #18. Историческое «не объединён» выше superseded этим
checkpoint; приёмка общего CI ещё открыта. CI #753/#754 окончательно success
на точных исходных HEAD; повторов длительных jobs нет. Матрица новых AGH
отказов/фиксов — P7_B_INTEGRATION_2026-10-31.md.

RS6 stage 1: native configuration/cache → RS5 inputs, audit-only. Никаких
реальных writer callers/новых служб/UI. Контракт, tests/measurements и план
shadow coordinator до отдельно согласуемого live writer — RS6_READ_ADAPTERS.md.
