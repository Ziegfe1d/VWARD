# RS-5: нормализованный audit-контракт v1

`components/runtime/lib/vward-routing-audit.sh` определяет только функцию
`vward_routing_audit INTENTS SNAPSHOT`. Загрузка через `.` ничего не запускает,
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
