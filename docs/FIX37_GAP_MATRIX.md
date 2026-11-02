# fix.37: незакрытое после fix.36 — матрица, разбор диагностики 02.11, первые исправления

Рабочий документ ветки `claude/new-session-kl9ijw` (draft PR #33 в `dev`). Это **не** выпуск и не разрешение
выпуска: `VERSION`, лента, подпись и роутер не менялись. Личные данные самотеста (адреса провайдера, MAC,
URL Smart DNS, имена устройств) сюда не переносятся — только обезличенные счётчики и метки времени.

## 0. Контрольный снимок (перепроверен 02.11.2026 после замечаний владельца)

| Объект | Состояние |
|---|---|
| `dev` | `dd4fb94e21adced28b6424eaccbbeecafe9a4b8d` — подписанный кандидат fix.35.1 (2026110102) |
| PR #32 `fix/fix36-20261102` | draft, HEAD **`ca1595d9d913df73dd289b0b30d49c2eae498c73`** (было `c0cc511` при первом снимке): `99af534` разделяет `trap - EXIT` и `trap - HUP INT TERM` в `vward-route-engine.sh`, `ca1595d` — документы. Оба коммита `[skip ci]` |
| CI PR #32 | CI #789 (run 41416501880) относится **только к `c0cc511`**: `updater-tests` и `resource-audit` SUCCESS, `repository-consistency` FAILURE (`check-terminating-signal-traps.sh`). На `99af534`/`ca1595d` штатный CI **не запускался**; прежние SUCCESS новому SHA не приписываются. Решение о новом полном CI — за владельцем (запись PR #32 в `docs/AGENT.md`) |
| Совместимость PR #33 с `ca1595d` | `git merge-tree`: код (`vward-device-profile.sh`, `api.cgi`) сливается автоматически, конфликт только в `SHA256SUMS`. Пробное слияние во временном worktree с пересчётом `SHA256SUMS`: `check-console-diagnostics-dns`, `check-ads-dns-guard`, `check-list-smartdns-mode`, `check-keenetic-cache-owner`, `check-route-engine-bind-workers` PASS, `sha256sum -c` PASS. Это локальная проба, не CI |
| CI PR #33 | #790 на `3500a04`: `repository-consistency` SUCCESS, `updater-tests` FAILURE (манифест, §3.1), `resource-audit` в работе на момент проверки. Новый HEAD требует своего CI |
| Установленная версия на Keenetic | самотест 02.11 12:48 доказывает только KeeneticOS 5.1.8; версия VWARD им **не доказана**. fix.36 на момент самотеста не установлен — события 02.11 ему не приписываются |
| BusyBox на Keenetic | **v1.37.0** (Entware; со слов владельца, баннер Termius). Проверки этой ветки — BusyBox 1.36.1 и dash; 1.37.0 не проверялась |

Статусы: **подтверждено / вероятно / не проверено / опровергнуто**. «Есть код» ≠ «принято на Keenetic».

## 1. Полный цикл против фактического PR #32 — конфликт решений не разрешён

В `dev` (`docs/ROADMAP.md` §7, «31.10.2026, полный цикл»; `ROUTING_VPN_DNS_FULL_CYCLE_20261031.md`) fix.36 —
**весь** общий цикл: прежние fix.34.2, 34.2b, 34.3, журналы, dnsmasq с тремя взаимоисключающими режимами,
sing-box, Панель. В draft PR #32 позднее добавлена запись «Уточнение состава fix.36 — поручение владельца
02.11.2026» о сокращении состава. **Это конфликт двух решений; владелец подтвердит его отдельно.** До этого ниже
весь незакрытый объём числится за fix.36 по `dev`. Перенос в fix.37 не объявлен и не выполнен.

| Требование (источник) | dev `dd4fb94` | PR #32 `ca1595d` | CI | Keenetic | Осталось | Статус |
|---|---|---|---|---|---|---|
| Orphan DNS-работы движка, второй корень (fix.35.1, открытое) | — | дети Live, ожидание при выходе; trap-reset разделён (`99af534`) | на `ca1595d` нет | нет | полный CI, приёмка | код есть, CI нет |
| Lease общей копии конфигурации, ABA | — | `vward_keenetic_config` | на `ca1595d` нет | нет | приёмка времени старта | код есть, CI нет |
| Один владелец запуска движка (cron-watchdog / supervisor / S91) | два вызывающих `S91 start` | описан, сериализация CONTROL_LOCK; один владелец **не введён** | — | нет | решение владельца | не сделано |
| Режим «DNS» списка, лимит 8, ownership, откат | сегмент скрыт | транзакция в `vward-console-config.sh` + Панель | на `ca1595d` нет | нет | CI, приёмка | код есть, CI нет |
| Установка dnsmasq/sing-box/Xray из Панели без включения | нет | есть | на `ca1595d` нет | нет | CI, приёмка; удаление/сброс не делались | код есть, CI нет |
| **Три взаимоисключающих DNS-режима AGH / dnsmasq / native, переключение, recovery** | только чтение/рендер/план (`vward-dns-mode.sh`: «no DNS writer is connected») | нет | — | нет | writer, селектор, эмулятор `agh→dnsmasq→native→agh` | **не сделано, обязательство fix.36 по dev** |
| sing-box как выключенный альтернативный движок, подтверждение протоколов | установка пакета | установка без запуска | — | нет | движок, протоколы, Панель | не сделано, fix.36 по dev |
| fix.34.2: YouTube/подсети Google с владением, сверка без процесса на маршрут, пакетное «Всё в Smart DNS» | частично (PACKAGE_F) | нет | — | нет | всё перечисленное | не сделано, fix.36 по dev |
| fix.34.2 `a2` — только WOULD_ADD | наблюдение `WOULD_ADD` в коде | нет | — | нет | 24–48 ч данных + согласие | запись запрещена |
| fix.34.2b: резерв/возврат туннеля, третий независимый контроль, защита VLESS, ИИ при потере туннелей, нагрузка Xray/AGH | частично | нет | — | нет | третий контроль (обе пробы сейчас Cloudflare 1.1.1.1/1.0.0.1) | не сделано, fix.36 по dev |
| fix.34.3: дубли FQDN-групп, номер группы, независимые пути DNS/ISP/VPN для «Проверить сайт»/ИИ, DNS через VPN без петли | дубли — показ; `svc_open` есть | нет | — | нет | независимые резолверы, «DNS через VPN» | частично, fix.36 по dev |
| Журналы полного раздела (события решений, время RCI/ndmc, источники) | «Важное/Все», TXT/копировать/поделиться | START_PHASE | — | нет | время RCI/ndmc, единые причины | частично, fix.36 по dev |
| Доменные списки: 0/1/N, массовые, **отмена удаления**, импорт/создание | список, режимы, удаление с копией | DNS-режим | — | нет | «Отменить» удаление (в коде нет) | частично |
| «Реклама и трекеры»: порядок, честные статусы, малый процент | `blockedShare`, порядок | — | зелёный в fix.35.1 | нет | приёмка 320/390 px | код есть |
| RS-6/RS-7 | audit/dry-run | без writer | — | нет | writer только по решению | заблокировано (верно) |
| TTL `smartdns.resolved` (Н) | 16 адресов без срока | — | — | нет | после подтверждения поведения | не сделано |
| Предупреждение «описание группы ≠ фактический путь» (02.11, P1) | `lists-data` отдаёт `description` и `via` | экран и jq переписаны | — | нет | реализация поверх PR #32 после интеграции | не сделано |

## 2. Диагностика Keenetic 02.11 12:48 (окно ndm-журнала ≈ 01.11 23:51 – 02.11 12:48)

### 2.1 P0 DNS: 10:51:03–10:51:05

**Факты (из самотеста):** три строки `ndnproxy: proxy loop detected: 192.168.1.1 <-> 192.168.1.1, request dropped`
и три `DNS server 192.168.1.1 inactivated` за 2 с. Счётчики ndnproxy для `192.168.1.1:65053` на 12:48:
`R.Sent=55, A.Rcvd=6, NX.Rcvd=21, Avg.Resp≈926 мс`; окно счётчиков неизвестно.

**Не установлено:** какой процесс отправил запросы, какое имя, через какой путь, длилось ли состояние дольше 2 с,
когда сервер снова стал активным. Три события не доказывают ни кратковременную петлю, ни путь через
bootstrap/PTR.

**Гипотезы (все — не проверено):**

| # | Гипотеза | За | Против / что проверить |
|---|---|---|---|
| H1 | Настройка AGH возвращает запрос на :53 роутера (`upstream_dns`, `fallback_dns`, `bootstrap_dns` при upstream-именах, PTR, доменная строка без своего клиента роутера) | так устроен классический loop ndnproxy ↔ AGH | при `upstream_dns` → роутер петля была бы постоянной; остальное условно. Проверка: ключи AGH (счётчики) и класс `Upstream` в журнале запросов AGH за 07:50:50–07:51:09 UTC (10:51 МСК) |
| H2 | Keenetic считает петлёй запрос, пришедший с адреса роутера, который он сам переслал бы на сервер с тем же адресом (192.168.1.1:65053) | VWARD по умолчанию спрашивает DNS роутера с его LAN-адреса: `VWARD_DNS_SERVER=$VWARD_LAN_ADDRESS` (`vward-device-profile.sh`); такие запросы делают движок (`agh_bind; nslookup`), reconcile, Панель (`api.cgi`, проверочный запрос) | таких запросов много, а событий три; возможно, петлёй считаются только запросы, не найденные в кэше Keenetic. Проверка: запросы с адреса роутера в журнале AGH в то же окно |
| H3 | Keenetic сам вывел сервер из работы: `inactivated` — его реакция на отброшенные запросы или на собственные тайм-ауты, без настройки-петли | Avg.Resp≈926 мс у AGH | порядок строк loop/inactivated и соседние сообщения ndm (контекст 10:50–10:51) |
| H4 | Перезапуск или переподключение AGH в этот момент (обновление фильтров, страж DNS, ручной вывод владельца около 10:50) | совпадение по времени с read-only выводом владельца (FIX36_REPORT) | события VWARD 10:45–10:55 (`DNS_CHAIN_*`, `WOULD_TAKE_OUT`, перезапуски AGH) |
| H5 | Функция `route-dns` (по умолчанию выключена) включена | пишет `[/домен/]роутер:53` в AGH; при сбое клиента роутера — петля | наличие `route-dns.enabled` и статус |

Сама проверка в диагностике (§5) ничего не отправляет в DNS и не меняет. Активный опыт (отправить запрос с
адреса роутера и смотреть журнал) может снова отключить AGH в Keenetic — только с отдельного разрешения.

### 2.2 P0 блокировки ndm `Dns::Route::ResolveQueue`

**Факты:** 00:39:21 — `Resolved` не передавался 30 с, 00:39:51 — 60 с; 08:25:57 — `Cleanup` не стартовал 30 с;
стек `UpdateSet6_ / OnCacheSync_` (обновление IPv6-набора при синхронизации DNS-кэша).
**Гипотеза (не проверено):** ночное задание `10 0 * * *` (`vward-policy-chain.sh && vward-policy-reconcile.sh`)
разрешает домены групп через DNS роутера (`vward-policy-reconcile.sh`, `nslookup … $VWARD_DNS_SERVER`), и каждый
ответ пополняет FQDN-наборы Keenetic. Эта гипотеза держится, только если в 00:39 задание ещё шло. На 08:25 у VWARD
заданий по расписанию нет. Нужны время окончания задания и число IPv6-наборов (§5). IPv6 не отключается;
частота и пакетирование не меняются до воспроизведения.

### 2.3 P0/P1 объём маршрутов

**Факты:** 1 330 строк `ip route` в startup-config (1 329 с маской, 1 без); 34 356 записей `show ip route`;
≈2 727 уникальных `destination+interface+proto`; 28 FQDN-групп.
**Вывод (вероятно):** около 12,6 повторения на запись — это тиражирование статических маршрутов в таблицы
политик доступа Keenetic, а не 34 тыс. отдельных сетей. Разделение «свои VWARD / ручные / FQDN-derived / дубли
внутри таблицы» — **не проверено**; нужен отдельный read-only подсчёт после fix.36, без `show ip route` в общей
диагностике. Массовая очистка запрещена.

### 2.4 P1 ресурсы, ndnproxy, сессии

- CPU 42 % (avg 39, max 85 в окне cpustat), MemAvailable ≈85 МБ, zram ≈66 МБ, ndm 25 %/~58 МБ, load 1,27 — точки
  измерения, причина **не установлена**.
- ndnproxy: окно счётчиков неизвестно; доля NX и тайм-ауты — по журналу AGH, **не проверено**.
- 1 715 `Core::Server: started Session` за ≈13 ч (≈2,2/мин). VWARD вызывает ndmc из минутных заданий —
  значимая доля **вероятна**, точная атрибуция **не проверена**. Сокращать вызовы ценой устаревшего состояния нельзя.

### 2.5 P1 конфликт описания и пути

Группы с описанием «… (ISP)» привязаны `dns-proxy route object-group … OpkgTun4`. Описание не является маршрутом.
Предупреждение в Панели — после интеграции PR #32 (§1, последняя строка). Автоматической правки групп нет.

## 3. Исправления этой ветки

### 3.1 Ошибки CI #790 и состава PR (исправлено)

| Ошибка | Причина | Исправление |
|---|---|---|
| `updater-tests`: `docs/FIX37_GAP_MATRIX.md` нет в `SHA256SUMS` | `scripts/refresh-sha256sums.sh` берёт список из `git ls-files`, а я запустил его до `git add` нового файла | пересчёт после индексации; локально повторена проверка CI (`git ls-files` против `SHA256SUMS`) и `sha256sum -c` — совпадают. Проверка не ослаблялась |
| `BusyBox-1.0.3.tar.gz` в diff | PyPI-пакет «BusyBox» (Python-модули, не BusyBox), скачанный в рабочий каталог запасной командой `pip download busybox` при подготовке тестовой среды и попавший в `d438d22` через `git add -A` | удалён; в коде нигде не используется |

### 3.2 Одна проверка петли для Панели и стража DNS (RED → GREEN)

**Дефект (подтверждено, статически):** страж DNS (`agh_upstream_loops` в `vward-ads-privacy-dns-guard.sh`) считал
петлёй `upstream_dns` и `fallback_dns`, Панель (`api.cgi`, «Цепочка DNS») — только `upstream_dns` и при
`fallback_dns` → роутер показывала «Норма». В первой версии PR #33 общую функцию вызывала только Панель —
исправлено.

**Сейчас:** `vward_agh_dns_loops` (`components/runtime/lib/vward-device-profile.sh`) читает YAML только для чтения и
отделяет **настроенное** от **применяемого**. Правило ревью 02.11: настройку можно назвать безвредной **только при
доказательстве**, что обратного пути к роутеру нет. Адрес роутера в настройке или «локально выглядящее» имя таким
доказательством не считаются.

| Вид | Когда называется | Доказательство отсутствия обратного пути | Страж | Панель (AGH в цепочке) |
|---|---|---|---|---|
| `main` | строка `upstream_dns` без домена → роутер | — | держит AGH вне цепочки (как раньше) | FAIL |
| `fallback` | `fallback_dns` → роутер | — | держит вне цепочки (как раньше) | WARN |
| `bootstrap` | `bootstrap_dns` → роутер, и хоть один сервер задан именем (DoH/DoT/имя, `sdns://`, `upstream_dns_file`, upstream клиента) | — | не влияет | WARN |
| `bootstrap_idle` | `bootstrap_dns` → роутер, все серверы — адреса | AGH разрешает через bootstrap только имена своих серверов, а имён нет | не влияет | не называется |
| `private` | `local_ptr_upstreams` → роутер, приватные PTR включены (явно или по умолчанию AGH) | нет: обратные имена, которых Keenetic не знает, могут вернуться | не влияет | WARN |
| `private_off` | то же при `use_private_ptr_resolvers: false` | AGH эти серверы не спрашивает | не влияет | не называется |
| `domain` | `[/публичный домен/]роутер` | — | не влияет | WARN |
| `domain_local` | `[/lan, local, home.arpa, *.arpa…/]роутер` | нет: имена, которых Keenetic не знает, могут вернуться | не влияет | WARN |
| `domain_client` | доменные строки (публичные или локальные), но запросы от Keenetic их обходят | ровно один постоянный клиент AGH имеет **LAN-адрес** (адрес, с которого Keenetic спрашивает AGH) в `ids`; клиентов с CIDR-`ids` нет; у клиента есть свои серверы и ни один не ведёт на роутер (включая `[/домен/]`) | не влияет | не называется |

Роутер — это все адреса роутера (`vward_router_addresses`: LAN первым, затем все IPv4/IPv6 из `ip -o addr show`,
например гостевой сегмент), 127.0.0.0/8, `::1`, localhost; порт 53 или без порта; plain/udp/tcp. Не роутер:
`192.168.1.10`, `:5353`, DoH-URL. Пока AGH вне цепочки Keenetic, условные виды не называются: Keenetic их запросы в
AGH не передаёт. Ни одна строка не доказывает **активную** петлю: это свойства настройки. Активную петлю показывают
только журнал запросов AGH и журнал ndm (§5).

**Изменение поведения стража (явно):** для форм, которые знали оба прежних чтения, ничего не меняется. Новые формы
повтора всех запросов — `127.0.0.2…`, `::1`, другой адрес роутера (гостевой сегмент), inline-списки, несколько
адресов в одной строке — страж теперь тоже считает петлёй. В режиме «Наблюдение» (выбор владельца) это только
`WOULD_TAKE_OUT` в журнале. Bootstrap, PTR и доменные строки AGH из цепочки не выводят. Если библиотеки нет (старая
установка), страж работает по прежнему чтению. `main` при доказанном клиенте роутера намеренно не смягчается
(осторожная сторона).

| Тест | RED | GREEN |
|---|---|---|
| `check-console-diagnostics-dns.py` | на `dev` `dd4fb94`: `fallback_dns → 192.168.1.1:53` = PASS («Норма»); на `84129ff`: PTR к роутеру = PASS | доказанные случаи — PASS: неиспользуемый bootstrap, `use_private_ptr_resolvers: false`, свой клиент роутера (публичная и локальная строка), внешние адреса/порты. Отрицательные — WARN: PTR при включённых и по умолчанию; локальные зоны без клиента; клиент только с `127.0.0.1`; клиент с роутером среди серверов; клиент с `[/x/]127.0.0.1`; клиент без серверов; два клиента с LAN; CIDR-клиент; bootstrap при `sdns://`; bootstrap при имени у клиента. Upstream на гостевом адресе роутера — FAIL. Вне цепочки fallback не называется |
| `check-ads-dns-guard.py` | на `dev`: `127.0.0.2:53` — AGH возвращается в цепочку | `loop_upstream`; гостевой адрес роутера — `loop_upstream`; fallback вне цепочки с библиотекой и без неё; bootstrap/PTR/доменная строка AGH не выводят |

Проверено: оба теста на `sh` (dash) и BusyBox 1.36.1 (страж — оба интерпретатора в одном прогоне);
`busybox sh -n` и `shellcheck -S error` изменённых файлов. **На роутере владельца BusyBox v1.37.0** (Entware, баннер
Termius; сообщил владелец 02.11). Локально и в CI (`ubuntu-latest`) проверено на **1.36.1**; 1.37.0 в этой сессии
не проверялась: загрузку стороннего бинарного пакета 1.37 политика сессии не разрешила. Используются только `sh`, `awk`,
`sed -E`, `grep -E`, `date -d @…`, `readlink`, `tr` в формах, общих для 1.36 и 1.37; подтверждение на устройстве —
`sh -n` в начале запуска диагностики (§5) и её вывод.

**Риски и откат.** WARN возможен там, где обратного пути на деле нет, но доказать это по настройке нельзя
(например, PTR-запросы к роутеру: Keenetic может знать все имена). Формулировка говорит «настройка, а не
замеченный сбой». Нагрузка: один `awk` по YAML и одно `ip -o addr show` на запрос диагностики и на проверку стража,
без опроса и без вызовов Keenetic. Откат — штатный файловый rollback Update Engine (Ed25519/SHA-256 без ослабления);
конфигурацию Keenetic/AGH изменение не трогает.

## 4. Проверено статически / принять на Keenetic / заблокировано

- **Статически:** расхождение двух проверок петли и его закрытие; разделение «настроено / применяется»; путь
  reconcile → DNS роутера; `VWARD_DNS_SERVER` по умолчанию = LAN-адрес; отсутствие DNS-writer режимов
  AGH/dnsmasq/native; отсутствие «Отменить» удаления списков.
- **На Keenetic после установки fix.36 (владелец):** START_PHASE и время старта; один корень движка; режим DNS списка
  и лимит 8; установка пакетов без запуска; Ozon/Wildberries, Lampa TV, Supercell, ИИ на клиентах; ночное задание
  03.11 00:10 против ResolveQueue; новые `proxy loop detected` и их источник (§5).
- **Заблокировано без отдельного решения:** записи в Keenetic/AGH/DNS, активный опыт с DNS-запросами (H2), writer
  RS-6/RS-7, переключение DNS-режимов, запись `a2`, 8 ручных подсетей Google, 16 DNS-правил, NextDNS, режимы агентов,
  слияние, подпись, выпуск, установка; граница fix.36/fix.37 (§1).

## 5. Одна read-only диагностика с окном-параметром (termius-standard v2.3.3)

Команда только диагностическая, ничего не изменяет и DNS-запросов не отправляет. Восемь вставок
(897/855/856/943/1043/1056/925/1063 байт, строки ≤ 58 символов, ASCII) создают `/tmp/vward-f37.sh` и
`/tmp/vward-f37.awk` и сразу запускают проверку за последние 15 минут. Файлы остаются в `/tmp` (RAM) до перезагрузки,
поэтому дальше достаточно одной короткой строки:

| Когда | Строка в Termius | Окно |
|---|---|---|
| Сразу после нового `proxy loop detected` | `sh /tmp/vward-f37.sh 10` | последние 10 минут (1–60; иначе 15), шаг 1 мин |
| Известен момент события | `sh /tmp/vward-f37.sh '2026-11-03 21:14:05' +0300` | ±60 с вокруг момента, шаг 1 с; смещение — пояс, в котором записан момент (по умолчанию `+0300`) |
| После перезагрузки роутера | повторить восемь вставок | — |

**Время.** Окно задаётся абсолютными моментами `S..F` (эпоха). Момент пересчитывается в UTC по указанному смещению
(`date -u -d` + сдвиг) и не зависит от пояса оболочки Entware. Каждая запись AGH переводится в UTC по собственному
смещению из поля времени. Журналы VWARD ищутся по каждой минуте окна в местном времени оболочки **и** в UTC. Журнал
ndm фильтруется по видам событий, его метки выводятся как есть.

**Журнал AGH.** Основной путь — API самого AdGuard Home (`/control/querylog`), он отдаёт и записи из памяти, ещё не
сброшенные на диск. Вызов идёт через уже установленную функцию VWARD `ads_agh_api_get`: учётные данные curl получает
через stdin (`-K -`), в командной строке и в выводе их нет. Чтение идёт назад страницами по 500 до начала окна, не
больше 6 страниц. Если API недоступен (нет библиотеки VWARD, AGH не отвечает), читаются файлы `querylog.json.1`/`.json`
из каталога, найденного по процессу: исполняемый файл `*/AdGuardHome` в `/proc/*/exe`, затем `-w/--work-dir`,
`-c/--config`, `querylog.dir_path`; иначе путь из `device.conf` или `/opt/etc/AdGuardHome`.

Покрытие называется явно:
- `[ OK ] no queries in window` — журнал прочитан дальше начала окна, записей нет;
- `[ PARTIAL ] log not read back to window start` — 6 страниц не дошли до начала окна;
- `[ PARTIAL ] disk only, memory buffer not read` и `[ NOT_VERIFIED ] none found: …` — данных недостаточно, вывод
  «событий не было» запрещён.

**Обезличивание.** Из журнала AGH выводятся только счётчики `время UTC (шаг окна) / источник router|client / тип запроса /
класс upstream ROUTER|ext|cache|none`. Домены, URL, токены и IP клиентов не выводятся. Временные файлы с сырыми
записями (`/tmp/vward-f37.tsv`, `.json`) удаляются сразу после подсчёта. Строки ndm, VWARD и `resolv.conf` проходят
`anon` (адрес роутера → `router`, `127.0.0.1` → `loopback`, IPv4 → `<ip>`, IPv6 → `<ip6>`, MAC → `<mac>`, URL → `<url>`,
имена с точкой → `<name>`).

**Проверено на fixture** под BusyBox 1.36.1 (sh и все утилиты из BusyBox; подставные `ndmc`, `ipset`, API) и dash:
- момент `'2026-11-02 10:51:03' +0300` → окно 07:50:03Z–07:52:03Z: записи `+03:00`, `Z`, upstream `[::1]:53`
  классифицированы, запись вне окна отброшена; вторая страница запрошена с закодированным `older_than`, чтение
  остановлено при достижении начала окна;
- режим «последние 10 минут» на записях относительно текущего времени;
- API, не дочитанный до начала окна → `[ PARTIAL ]` после 6 страниц;
- без библиотеки VWARD — чтение с диска с `[ PARTIAL ] disk only…`;
- неверные аргументы → подсказка и код 2;
- процесс AGH находится по исполняемому файлу (`--work-dir=`, `-c`), процесс-приманка со словом «AdGuardHome» в
  командной строке игнорируется (первая версия ловила такую приманку — исправлено);
- в выводе нет имён, IP клиентов и URL.

Вставка 1 (заголовок, сохранение результата, обезличивание):

```sh
clear
cat > /tmp/vward-f37.sh <<'EOF'
OUT="/tmp/vward-f37-$(date +%Y%m%d-%H%M%S).txt"
ls -1t /tmp/vward-f37-*.txt 2>/dev/null |
 tail -n +5 | while read -r F; do rm -f "$F"; done
MAXB=30000
send_out() {
 ESC=$(printf '\033')
 sed "s/${ESC}\[[0-9;?]*[a-zA-Z]//g" "$OUT" |
  tail -c "$MAXB" | base64 | tr -d '\r\n' |
  { read -r B; printf '\033]52;c;%s\a' "$B"; }
}
on_abort() {
 trap '' INT TERM HUP; send_out
 echo "[ ABORTED / DISCONNECTED ]:" \
  "PARTIAL RESULT SAVED TO /tmp/last_result.txt"
 exit 130
}
trap on_abort INT TERM HUP
N='[A-Za-z0-9_-]'
anon() {
 sed -E -e "s/$LQ/@R@/g" -e 's/127\.0\.0\.1/@O@/g' \
 -e 's#[a-z]+://[^ ]*#<url>#g' \
 -e 's/([0-9]{1,3}\.){3}[0-9]{1,3}/<ip>/g' \
 -e 's/([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}/<mac>/g' \
 -e 's/(^|[ =(])[0-9a-fA-F]*::[0-9a-fA-F:]*/\1<ip6>/g' \
 -e "s/$N+(\.$N+)*\.[A-Za-z]{2,}/<name>/g" \
 -e 's/@R@/router/g' -e 's/@O@/loopback/g'
}
EOF
```

Вставка 2 (окно):

```sh
cat >> /tmp/vward-f37.sh <<'EOF'
A=${1:-15}; Z=${2:-+0300}; NOW=$(date +%s)
case "$A" in
 [0-9]|[0-9][0-9]) [ "$A" -ge 1 ] && [ "$A" -le 60 ] ||
  A=15; S=$((NOW-A*60)); F=$NOW; GR=60 ;;
 [12][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]' '[0-2]*)
  case "$Z" in [+-][0-9][0-9][0-9][0-9]) ;;
   *) echo "bad offset $Z"; exit 2 ;; esac
  E=$(date -u -d "$A" +%s) || exit 2
  H=${Z#?}; H=${H%??}; M=${Z#???}; H=${H#0}; M=${M#0}
  case "$Z" in -*) E=$((E+H*3600+M*60)) ;;
   *) E=$((E-H*3600-M*60)) ;; esac
  S=$((E-60)); F=$((E+60)); GR=1 ;;
 *) echo "usage: sh $0 [MIN 1-60 |" \
  "'YYYY-MM-DD HH:MM:SS' [+HHMM]]"; exit 2 ;;
esac
WIN="$(date -u -d @$S '+%F %T')Z..$(date -u -d @$F +%T)Z"
L=$(sed -n 's/^VWARD_LAN_ADDRESS=//p' \
 /opt/etc/vward/device.conf 2>/dev/null | tr -d '"')
[ -n "$L" ] || L=192.168.1.1
LQ=$(echo "$L" | sed 's/\./\\./g'); G=/opt/var/log
EOF
```

Вставка 3 (где AdGuard Home и его журнал):

```sh
cat >> /tmp/vward-f37.sh <<'EOF'
P=; for d in /proc/[0-9]*; do
 case "$(readlink "$d/exe" 2>/dev/null)" in
  */AdGuardHome) P=$d; break ;; esac
done
W=; Y=; [ -n "$P" ] && set -- $(tr '\0' ' ' <$P/cmdline)
while [ $# -gt 0 ]; do case "$1" in
 -w|--work-dir) W=$2 ;; -c|--config) Y=$2 ;;
 --work-dir=*) W=${1#*=} ;; --config=*) Y=${1#*=} ;;
esac; shift; done
[ -n "$W" ] || { X=$(readlink "$P/exe" 2>/dev/null)
 [ -n "$X" ] && W=${X%/*}; }
[ -n "$Y" ] || Y=$(sed -n 's/^VWARD_ADGUARD_CONFIG=//p' \
 /opt/etc/vward/device.conf 2>/dev/null | tr -d '"')
[ -n "$W" ] || W=${Y%/*}
[ -n "$W" ] || W=/opt/etc/AdGuardHome
[ -n "$Y" ] || Y=AdGuardHome.yaml
case "$Y" in /*) ;; *) Y=$W/$Y ;; esac
QD=$(awk '/^[^ #]/{q=($1=="querylog:");next}
 q&&$1=="dir_path:"{gsub(/["\047]/,"",$2);print $2}' \
 "$Y" 2>/dev/null)
[ -n "$QD" ] || QD=$W/data
Q=$QD/querylog.json
EOF
```

Вставка 4 (вспомогательный awk: время и классы):

```sh
cat > /tmp/vward-f37.awk <<'EOF'
function ep(t,  y,m,d,o,z){y=substr(t,1,4)+0
 m=substr(t,6,2)+0;d=substr(t,9,2)+0
 if(m<=2){y--;m+=9}else m-=3
 d=365*y+int(y/4)-int(y/100)+int(y/400)+\
 int((153*m+2)/5)+d-719469;o=0
 z=substr(t,length(t)-5)
 if(z~/^[+-][0-9][0-9]:[0-9][0-9]$/)o=(substr(z,1,1)\
 =="-"?-1:1)*(substr(z,2,2)*3600+substr(z,5,2)*60)
 return d*86400+substr(t,12,2)*3600+\
 substr(t,15,2)*60+substr(t,18,2)-o}
BEGIN{FS="\t"}
mode=="ep"{print ep($1);exit}
{t=ep($1);if(t<s||t>=f)next;n++;h=$4
 sub(/^[a-z]+:\/\//,"",h);sub(/\/.*/,"",h)
 sub(/:[0-9]+$/,"",h);gsub(/[][]/,"",h)
 r=(h==l||h~/^127\./||h=="::1")
 c=($2==l||$2~/^127\./||$2=="::1")?"router":"client"
 v=($5=="true")?"cache":(h=="")?"none":r?"ROUTER":"ext"
 k[(t-t%g)" "c" "$3" up="v]++}
END{if(mode=="ep")exit;if(!n)print "NONE"
 for(i in k){split(i,p," ");u=p[1]%86400
 printf "%02d:%02d:%02dZ %s %s %s %d\n",int(u/3600),\
 int(u%3600/60),u%60,p[2],p[3],p[4],k[i]}}
EOF
```

Вставка 5 (чтение журнала AGH: API, иначе диск):

```sh
cat >> /tmp/vward-f37.sh <<'EOF'
TQ=/tmp/vward-f37.tsv; TJ=/tmp/vward-f37.json
CL=${CL:-/opt/share/vward/ads-privacy-guard}
[ -f "$CL" ] || CL=$CL/vward-ads-privacy-common.sh
: >$TQ; API=0; COV=0; OT=; i=0
JQ='[.time,.client,.question.type,(.upstream//""),'\
'(.cached//false|tostring)]|@tsv'
while [ $i -lt 6 ] && [ -r $CL ]; do i=$((i+1))
 ( . $CL; ads_agh_api_get "querylog?limit=500&"\
"response_status=all${OT:+&older_than=$OT}" $TJ ) \
  >/dev/null 2>&1 || break
 API=1; jq -r ".data[]?|$JQ" $TJ >>$TQ 2>/dev/null
 OT=$(jq -r '.oldest//""' $TJ 2>/dev/null)
 [ -n "$OT" ] || { COV=1; break; }
 OE=$(echo "$OT" | awk -v mode=ep -f /tmp/vward-f37.awk)
 [ "${OE:-0}" -lt "$S" ] && { COV=1; break; }
 OT=$(echo "$OT" | sed 's/+/%2B/g;s/:/%3A/g')
done
if [ $API = 0 ]; then
 DP=; for T in $((S-86400)) $S $((F+86400)); do
  DP="$DP|$(date -u -d @$T +%F)"; done
 for f in $Q.1 $Q; do [ -r "$f" ] &&
  grep -hE "\"T\":\"(${DP#|})" "$f" | jq -r \
  '[.T,.IP,.QT,(.Upstream//""),'\
'(.Cached//false|tostring)]|@tsv' 2>/dev/null
 done >>$TQ
fi
EOF
```

Вставка 6 (вывод: окно, настройки журнала, записи):

```sh
cat >> /tmp/vward-f37.sh <<'EOF'
{
echo "== vward-f37 read-only $(date) $(date +%z)"
ndmc -c "show version" | grep -E 'release|device'
echo "-- window $WIN step=${GR}s"
echo "-- AGH proc=${P:+yes} work=$W conf=$Y"
[ -r "$Y" ] || echo "[ NOT_FOUND ] AGH config"
awk '/^[^ #]/{q=($1=="querylog:");next} q&&/^  [a-z]/' \
 "$Y" 2>/dev/null |
 grep -E 'enabled|interval|size_mem|dir_path'
for f in $Q.1 $Q; do
 [ -r "$f" ] || { echo "[ NOT_FOUND ] $f"; continue; }
 echo "$f $(wc -c <"$f")B" \
  "$(head -n1 "$f" | grep -o '"T":"[^"]*"')" \
  "$(tail -n1 "$f" | grep -o '"T":"[^"]*"')"
done
echo "-- AGH records (source: $([ $API = 1 ] &&
 echo api || echo disk), pages=$i)"
awk -v l="$L" -v s=$S -v f=$F -v g=$GR \
 -f /tmp/vward-f37.awk $TQ | sort >$TJ
NV="log not read back to window start"
[ $API = 1 ] || NV="disk only, memory buffer not read"
if grep -q '^NONE' $TJ; then
 if [ $COV = 1 ]; then echo "[ OK ] no queries in window"
 else echo "[ NOT_VERIFIED ] none found: $NV"; fi
else cat $TJ; [ $COV = 1 ] || echo "[ PARTIAL ] $NV"; fi
rm -f $TQ $TJ
EOF
```

Вставка 7 (ключи AGH, счётчики):

```sh
cat >> /tmp/vward-f37.sh <<'EOF'
echo "-- AGH keys: router/name/ext (counts only)"
awk -v l="$L" 'function r(k,v){gsub(/["\047]/,"",v)
 gsub(/[][]/," ",v);n=split(v,w,/[ ,]+/)
 for(i=1;i<=n;i++){a=w[i];if(a=="")continue;t="ext"
 if(index(a,l)||index(a,"127.0.0.1")||
 index(a,"localhost"))t="ROUTER"
 else if(a~/^[a-z]+:\/\/[a-z]/)t="name";c[k" "t]++}}
 /^[^ #]/{d=($1=="dns:");u=($1=="clients:");k="";next}
 u&&$1=="-"&&$2==l{rc++}
 d&&/^  [a-z_]+:/{k=$1;v=$0;sub(/^ *[a-z_]+: */,"",v)
 if(k~/ptr_res/)print k,v;else if(v!="")r(k,v)
 next}
 d&&$1=="-"&&k!=""{v=$0;sub(/^ *- */,"",v);r(k,v)}
 END{print "router_client_ids:",rc+0
 for(x in c)print (x~/ROUTER/?"[ WARNING ]":\
 "[ OK ]"),x,c[x]}' "$Y" 2>/dev/null |
 grep -E 'upstream|bootstrap|fallback|ptr|client'
echo "-- resolv.conf: $(grep nameserver /etc/resolv.conf |
 anon | tr '\n' ' ')"
echo "-- ipv6 sets: $(ipset -t list 2>/dev/null |
 grep -c 'family inet6')"
EOF
```

Вставка 8 (ndm, журналы VWARD, состояние; запускает):

```sh
cat >> /tmp/vward-f37.sh <<'EOF'
echo "-- ndm log: loop / inactivated / queue"
ndmc -c "show log" | grep -E 'loop det|inactivat|'\
'ResolveQueue' | anon | cut -c1-110 | tail -n 20
R=; T=$((S-S%60)); while [ $T -le $F ]; do
 R="$R|$(date -d @$T +%m-%d.%H:%M)"
 R="$R|$(date -u -d @$T +%m-%d.%H:%M)"; T=$((T+60)); done
echo "-- VWARD logs in window (local and UTC)"
grep -hE "(${R#|})" $G/vward*.log 2>/dev/null |
 anon | cut -c1-100 | tail -n 15
echo "-- route-dns / chain / night job (end, rc)"
ls /opt/etc/vward/ads-privacy-guard/route-dns.* 2>&1
cat /tmp/vward-route-dns.status \
 /tmp/vward-dns-chain/state /tmp/vward-dns-chain/reason \
 /tmp/vward-policy-chain.cron.last \
 /tmp/vward-policy-chain.cron.rc 2>/dev/null
} 2>&1 | tee "$OUT"
WN=$(grep -c "^\[ WARNING" "$OUT")
KN=$(grep -c "^\[ OK" "$OUT")
echo "SUMMARY: pass=0 ok=$KN warn=$WN fail=0" |
 tee -a "$OUT"
ln -sfn "$OUT" /tmp/last_result.txt
ln -sfn "$OUT" /tmp/last_vward.txt
send_out; echo "RESULT SENT (OSC52)"
echo "RAW: /tmp/last_result.txt"
EOF
sh -n /tmp/vward-f37.sh && sh /tmp/vward-f37.sh
```

Как читать:
- `… router A up=ROUTER` — AGH получил запрос с адреса роутера и отправил его роутеру: довод за H1.
- `router … up=ext` рядом со строками loop в ndm — довод за H2.
- Только `client … up=ext` — запросы шли от клиентов и ушли наружу.
- `NOT_VERIFIED`/`PARTIAL` — данных недостаточно; вывод «не проверено».
- `[ WARNING ] … ROUTER` в ключах — свойство настройки, не событие.

## 6. Интеграция после fix.36

**Только squash-слияние PR #33** (указание владельца 02.11). Коммит `d438d22` содержит сторонний PyPI-архив
`BusyBox-1.0.3.tar.gz`, удалённый в `c3a3df9`. Обычное слияние или rebase-слияние перенесло бы его в историю `dev`.
Слияние и выпуск — только по отдельному разрешению владельца.

Влить конечный HEAD PR #32 в эту ветку слиянием (не переносом файлов) и пересчитать `SHA256SUMS` после индексации.
Затем сделать предупреждение «описание ≠ путь» поверх кода PR #32, добавить записи в `docs/AGENT.md` и `CHANGELOG.md`
(сейчас не добавлены, чтобы не конфликтовать с хвостом PR #32) и запустить один полный CI. Граница fix.36/fix.37 —
по отдельному подтверждению владельца.
