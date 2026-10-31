# RS-6: native read adapters, этап 1 / audit-only

База: интеграционный merge 656c38e02fc896a4482e644c56e284247c133baa, PR #18.
Отдельная ветка rs6-read-only-adapters-20261030. Новый файл
components/runtime/lib/vward-routing-read.sh определяет ровно одну публичную
функцию `vward_routing_read intents|snapshot`; загрузка ничего не делает.
Результаты — два TSV формата RS5, только stdout. Их записывает вызывающая
сторона в явно выбранное временное место и передаёт vward_routing_audit.
Нет live callers, установки в package-map, writer или UI wiring.

## Существующие источники чтения

| Вход | Что читается / как интерпретируется |
|---|---|
| VWARD_KCACHE/running-config | существующий общий кэш vward_keenetic_config; только чтение готового файла, без refresh/ndmc/RCI |
| VWARD_DEVICE_CONFIG | простые известные ключи профиля, без source/eval; нет secret выводов |
| VWARD_DEVICE_MAP_CACHE | существующие I-строки карты; VPN types соответствуют vward_map_vpns, WAN исключён |
| VWARD_CONSOLE_ETC/services/enabled.tsv | выбранные сервисы; ID/GROUP/PIN, каталог целиком не включается |
| services/categories.tsv | auto pin категории; иначе выбранный tunnel профиля |
| VWARD_SERVICES_FETCHED / BUNDLED | fetched→bundled, JSON shape validation и прежний размер 512KiB, без fetch |
| running-config manual FQDN groups | include + все route tuples; mapped service groups и AdaptiveAuto отдельно |
| VWARD_ROUTE_STATE/adaptive-persist.txt | подтверждённые сохранённые intent A, даже если runtime-группа после reboot ещё пуста |
| route-engine/adaptive.disabled | существующий флаг A; нет нового переключателя/настройки |
| VWARD_ROUTING_AGH_DOMAINS | явно подготовленный результат существующего vward_agh_smartdns_domains, одна строка на домен; без него DNS policy unknown |
| route-engine/domain-lists/GROUP | deferred route/DNS evidence читается и проверяется; не выдаётся за действующий маршрут |
| services/owned/GROUP | private owner/file-mode + точный состав и все route tuples; лишь vward/reference, никогда managed |
| BACKUP/service-transactions/*/pending и BACKUP-recovery/smartdns.* | незавершённый recovery делает источники unknown; никакого replay |

ETC/STATE/BACKUP — существующие VWARD_CONSOLE_ETC, VWARD_ROUTE_STATE,
VWARD_CONSOLE_BACKUP_DIR с прежними router defaults. Пути должны быть absolute.
AGH_DOMAINS не новая служба/кэш: это вход текущего вызова из существующего
reader; адаптер сам не создаёт и не обновляет такой файл. YAML/server URL не
выводятся. При неизвестном AGH-source DNS policy имеет opaque ID unknown;
настроенные per-domain строки получают smartdns без upstream/token.

## Гарантии и консервативные ограничения

- Существующие настройки и ручные исключения читаются без изменения; каталожные
  совпадения не превращаются во владение. Источник M здесь — наблюдаемые native
  группы; соответствие legacy enabled.tsv не даёт права на управление.
- Неатомарные раздельные legacy reads не доказывают generation/freshness:
  snapshot legacy-read unknown ВСЕГДА. Health DNS/AGH/VPN ВСЕГДА unknown;
  наличие interface/route не означает доступность или реальный packet path.
- Health evidence от DNS/AGH/tunnel-guard не подключено преждевременно.
  Общий resolver поэтому возвращает unknown, unresolved либо inactive;
  review/covered не используются как разрешение на запись.
- Source M/S — 1, если нет нового глобального выключателя в legacy формате;
  это наблюдаемые источники, не новые пользовательские настройки. A читает
  существующий adaptive.disabled. Симуляции всех 8 состояний меняют только
  нормализованный тестовый snapshot, не device settings.
- Только top-level FQDN declaration. Вложенная поддельная группа не создаёт
  строки; unsupported/wildcard/неизвестный target/неполный input → unknown.
  Scope exact — консервативное наблюдение apex, не обещание subtree/CNAME.
- Для обычных файлов применяется preflight regular/readable/non-symlink;
  FIFO не открывается и не блокирует процесс. Ограниченный native parse:
  4096 строк/1MiB на файл. Expand имеет лимиты RS5: 4096 строк/1MiB и 1024
  уникальных домена в объединении обеих проекций. Превышение → rc2, stderr, НЕТ partial stdout.
  До stdout результат буферизуется ограниченно и сортируется O(N log N).
- REF пока уникальны только внутри конкретного чтения: positional native
  records, не persistent identity и не ownership token. Review minor о
  стабильности REF отложен: до live wiring нужен canonical stable ID и
  согласованный snapshot generation; иначе нельзя сопоставлять REF между
  вызовами после перестановки catalog/native строк. Цена отсрочки — пока
  сравнивать межзапусковые решения по domain/source/target, не по REF.
- Missing services/categories консервативно unknown, хотя старый writer может
  выбрать default tunnel. Unknown не подменяется отсутствием/ISP fallback.

## Исполняемые проверки

`python3 tests/routing-readers/check-readers.py`: PASS на host sh.
`RS6_BUSYBOX=/path/busybox python3 ...`: PASS на BusyBox ash; дополнительно
локально awk заменён на BusyBox awk через внешний PATH fixture — PASS.

Проверены M/S/A и overlap/partial overlap, выбранные/невыбранные service rows,
категория/другой VPN и ISP/VPN conflict, отсутствующие/пустые ручные списки,
нет cache/map/VPN/DNS/AGH/catalog/persist, rc0 error snapshot, смена состава/
mode owner proof, saved state, неизменность inputs/exceptions, повторные reads,
потеря volatile cache как модель reboot, все 8/24 состояния и повтор.
Нет создания групп/маршрутов и нет transport вызовов. Проверки подключены к
штатному repository consistency. Полный CI нового HEAD ещё обязателен.

Review RED→GREEN: (1) вложенная phantom group, (2) 300 includes×14 targets,
ранее возвращавшие >4096 строк, теперь rc2 без stdout. Дополнительный RED
FIFO timeout 3s→GREEN unknown. Дополнительная union-регрессия: по 900 разных runtime/persist доменов, каждая проекция <1024, но union >1024, RED→GREEN rc2 без stdout. Независимое review нашло 4 Important в общем
кандидате (2 integration, 2 adapter); все закрыты регрессиями в одном fix pass.
Второе review не проводилось; результаты fixes подтверждаются тестами.

## Сравнение с действующими механизмами на одном fixture

Тест извлекает настоящие функции (не выполняет целые daemons), запускает
их на тех же synthetic native данных, затем сопоставляет адаптер и RS5.

| Механизм | Фактическое сравнение / расхождение |
|---|---|
| route-engine / is_manual_known | x.example найден обоими; wildcard legacy требует отдельной семантики, адаптер не выдумывает subtree |
| reconciler / adaptive_names | runtime AdaptiveAuto содержит x.example; persist intent ещё a.example. RS6 сохраняет a.example как intent, не объявляет configured |
| policy-sync / collect_vpn_domains | configured x.example/s.example/smart.example совпадают; a.example из persist не считается существующим FQDN route. CIDR plan не заменён |
| tunnel-guard / lists_best | старый quality fixture выбирает Wireguard1; RS6 видит interface, но health unknown и общего переключения не предлагает. Freshness/quality path пока не соединён |
| services / service_target | категория auto→Wireguard0 совпадает; смена на Wireguard1 видна как конфликт с текущими маршрутами/другими источниками, без скрытого приоритета |

Старые автоматы по-прежнему используют собственные решения/запись;
эквивалентность всей state machine не заявляется. Это точечный executable
comparison, а не параллельный запуск всех daemons или proof live policy.

## Стоимость на одинаковом входе

На неизменном fixture 833 bytes нормализованных входов, три повтора:
RS5 audit-only примерно 2–4ms; read двух проекций+audit примерно 18–29ms
на доступном host. Байты результата каждого сравнения совпадают.
Повторы в sh и BusyBox подтверждены; это НЕ измерение Keenetic Viva/MIPS,
CPU в простое/flash wear/максимального рабочего набора. Native parse и output
expansion ограничены; предельная конфигурация больше лимита явно отклоняется.
Новые daemon/guard/timer/poll нет. Ресурсные бюджеты/timeout не увеличены.

## Следующий безопасный пакет (без разрешения на live write)

1. Согласованный read-only coordinator в существующем вызове: один cached
   snapshot + metadata age/generation; no new poller. При пропуске/смене
   поколения обе проекции unknown, без plan apply.
2. Canonical stable source/group/domain/route identity; отдельное сравнение
   legacy group semantics/wildcards, saved source links и внешних edits.
3. Только shadow comparison с route-engine/reconciler/policy-sync/tunnel-guard/
   service_target: логировать bounded differences, не вызывать writers.
4. Измерить same-input на допустимых small/large native fixtures и отдельно
   на Viva после разрешённой read-only диагностики. Не менять лимиты.
5. Отдельный security design live writer: перед записью generation+ownership+
   permission recheck под прежними locks/admission, durable journal BEFORE
   mutation, exact postimage compensation, unknown→pending+gate. API lost reply,
   local write/save fault, TERM/SIGKILL/reboot и чужой edit обязательны.
6. Только после отдельного согласования безопасности подключать по одному
   существующему writer path; Панель/три тумблера — позднее RS7.

До «Выпускаем» нет dev/main merge, VERSION/feed/sign/release, установки или
изменений Keenetic/VPN/AGH. Audit read не даёт права менять пользовательские
группы и не подтверждает клиентский packet path.
