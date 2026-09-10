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

## WAN observer и recovery

WAN health и recovery намеренно разделены.

`wan.status` и `wan.class` Console читает из `/opt/var/lib/wan-health/state`, который
создаёт read-only `wan-health-watch.sh`. API маркирует источник как
`observer_source=wan-health-watch`. Вкладка журнала WAN читает
`/opt/var/log/wan-health.log`.

Observer state принимается только если он согласован с текущим Discovery snapshot:

- возраст не больше 180 секунд;
- текущий `wan-guard` role имеет `READY`;
- observer сам получил `DISCOVERY_STATE=READY`;
- observer `RCI_ID` совпадает с текущим `wan.rci_id`;
- при известном Linux mapping observer `LINUX_IF` совпадает с текущим `wan.linux_if`.

При нарушении этих условий Console возвращает `UNKNOWN` с классом
`OBSERVER_STALE`, `OBSERVER_ROLE_MISMATCH`, `OBSERVER_MAPPING_MISMATCH`,
`OBSERVER_DISCOVERY_MISMATCH` либо текущим Discovery failure. Старое `UP` после смены
uplink не сохраняется до следующего observer cycle.

`wan.action`, `recovery_count`, `recovery_stage` и `legacy_recovery_class` пока
поступают из существующего `wan-guardian.sh`. API явно маркирует это как
`recovery_source=legacy-wan-guardian`. Таким образом read-only observer уже переведён
на общий role contract, а high-risk recovery ещё нет.

Frontend определяет зелёный WAN по `wan.status == UP`. Глобальное поле `wan.internet`
остаётся диагностическим и больше не используется как источник здоровья WAN-карточки,
hero, настроек или session chart. Это важно при multi-WAN: другой рабочий uplink не
может скрыть отказ выбранной роли.

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

- `wan` -> read-only observer log `/opt/var/log/wan-health.log`;
- `recovery` -> legacy recovery log `/opt/var/log/wan-guardian-recovery.log`.

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
8. Проверить `wan.observer_source=wan-health-watch` и свежий `observer_age_seconds`.
9. Проверить, что `wan.status/class` совпадают с `/opt/var/lib/wan-health/state`.
10. Для PPPoE дополнительно сверить `via_rci_id` и `via_linux_if`.
11. Проверить, что `wan.recovery_source=legacy-wan-guardian`, пока recovery не мигрирован.
12. Проверить светлую и тёмную темы.
13. Проверить 320, 360, 768 и 1440 CSS px, portrait и landscape.
14. Увеличить масштаб до 200% и проверить keyboard focus.
15. Изменение updater-флагов проверять только в контролируемом окне с backup.

Source tests не заменяют проверку установленной Console. Если source и runtime hashes
различаются, сначала нужно определить установленный package/slot и причину расхождения.
