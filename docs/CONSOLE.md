# VWARD Console

Console работает в локальной сети и использует CGI API с того же адреса. Она не
загружает шрифты, иконки или библиотеки из интернета.

## Разделы

- «Обзор»: состояние основных подсистем;
- «Платформа»: все 10 компонентов с machine ID, release и health;
- «Обновления»: состояние Update Engine и четыре разрешённых переключателя;
- «Защита WAN», «Защита VPN», «Маршрутизация», «Среда выполнения»: read-only данные;
- «Хранилище»: использование `/opt`;
- «Настройки»: общий read-only обзор устройства, сети, обновлений и диагностики;
- «Журналы»: последние 200 строк из фиксированного списка VWARD-файлов.

## Источник сетевой топологии

Console получает сетевую топологию через один вызов `/opt/bin/vward-discovery.sh snapshot`
на status request. Snapshot содержит WireGuard inventory, WAN inventory и role selection
для Tunnel Guard и WAN Guard. Это исключает второй самостоятельный RCI inventory в CGI
и повторный discovery-проход для разных карточек.

WireGuard API отдаёт фактический `rci_id`, `linux_if`, mapping и состояние туннеля.
Поле `name` сохранено как compatibility alias и всегда формируется из discovered
`rci_id`. Состояние provider публикуется как `wg.discovery.state`.

WAN API больше не запрашивает `show/interface?name=ISP`. Выбранный uplink берётся из
`roles.wan_guard` общего snapshot и публикуется вместе с фактическими `rci_id`,
`linux_if`, `via_rci_id`, `via_linux_if`, типом и способом mapping.

Если WAN role неоднозначна или mapping недействителен, `wan.discovery.state` сообщает
`REQUIRES_SELECTION`, `STALE_MAPPING`, `INVALID_MAPPING` или другое состояние, а CGI
не угадывает `ISP`/`ethN`.

Поля `wan.class`, `wan.action`, recovery counters и часть diagnostic detail пока
поступают из существующего `wan-guardian.sh`. API явно отмечает это как
`observer_source=legacy-wan-guardian`. Это переходное состояние: topology уже единая,
но high-risk WAN observer/recovery ещё не мигрирован.

Если общий Discovery недоступен или возвращает некорректный snapshot, Console работает
fail-safe: общий `discovery.state=UNAVAILABLE`, WireGuard inventory пуст, WAN role не
подменяется guessed interface. Такая деградация не вызывает сетевых mutation.

## Что можно изменять

Только `auto_apply`, `auto_critical`, `auto_important` и `auto_routine`. API принимает
POST только с заголовком `X-VWARD-Request: console`, ограничивает body, проверяет все
значения, блокирует запись во время updater transaction, создаёт backup, заменяет
config атомарно и проверяет результат.

WAN, WireGuard и маршрутизация доступны только для чтения. API не принимает команды
shell, произвольные paths или команды `ndmc`.

## Журналы

Разрешены только имена `wan`, `recovery`, `cron`, `routing`, `updater`, `tunnel`,
`policy`, `console`. Каждое имя жёстко связано со своим файлом в `api.cgi`.
Произвольный path передать нельзя. Содержимое не выходит за пределы LAN, но может
содержать локальные домены, поэтому его нельзя публиковать без проверки.

## Проверка после установки

1. Открыть каждый пункт бокового и нижнего меню.
2. Открыть каждую карточку Overview и вернуться назад.
3. Проверить все восемь вкладок журналов.
4. Обновить данные и убедиться, что ошибок API нет.
5. Проверить `discovery.state=READY`.
6. Проверить, что `wg.discovery.state=READY` и WireGuard IDs совпадают с Discovery.
7. Проверить, что `wan.discovery.state=READY` и `wan.rci_id/linux_if` совпадают с ролью `wan-guard`.
8. Для PPPoE дополнительно сверить `via_rci_id` и `via_linux_if`.
9. Проверить светлую и тёмную темы.
10. Проверить 320, 360, 768 и 1440 CSS px, portrait и landscape.
11. Увеличить масштаб до 200% и проверить keyboard focus.
12. Изменение updater-флагов проверять только в контролируемом окне с backup.

Source tests не заменяют проверку установленной Console. Если source и runtime hashes
различаются, сначала нужно определить установленный package/slot и причину расхождения.