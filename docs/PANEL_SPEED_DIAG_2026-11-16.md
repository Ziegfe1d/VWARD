# Скорость Панели VWARD: где именно теряется время (диагностика 16.11.2026)

Поручение владельца 16.11.2026: только выяснить, где и почему Панель медленная; ничего не исправлять, не выпускать.
Исполнитель - Claude Code, ветка `ccr-d9589e94-8lasf3` от `e5a38e1` (0.2.0-rc.2.fix.39.3). Код и настройки не менялись.
Это пункт 0 пакета fix.40 в `docs/ROADMAP.md` («скорость Панели - замер по шагам»).

Источники: код (`web/cgi-bin/api.cgi`, `web/assets/vward-console.js`, `vward-device-profile.sh`, `install.sh`), счёт запусков на
эмуляторе с конфигурацией размера роутера владельца, и **замер владельца на Viva 16.11.2026 в 10:49** командой из
раздела 7 (KeeneticOS 5.1.8, MT7621, VWARD fix.39.3). Всё, что ниже названо «замер», - с роутера.

## 1. Итог

По убыванию веса. Времена - замер на Viva.

1. **Каждый запрос Панели платит 0,75 с ещё до своей работы.** Самые лёгкие запросы (`notes`, `auth`, `vward-off`) -
   0,73-0,80 с. Из них 0,63-0,74 с - загрузка профиля сети (`vward_profile_load`): установщик записывает в `device.conf`
   одно-два имени, остальное VWARD находит заново при каждом запуске. Страница - это 5-12 запросов: на «Обзоре»
   около 6,8 с из 11,2 с всей работы - эта постоянная часть.
2. **Раз в 5 минут профиль пересобирается целиком внутри запроса Панели:** опрос каждого интерфейса Keenetic и чтение
   всей конфигурации, около 8,6 с (расчёт по замеру). Очереди нет: все запросы открытой страницы делают это
   одновременно. В журнале ожиданий - чтения всей конфигурации из Панели до 19,9 с при пределе браузера 20 с.
   Это самая вероятная причина «Часть данных не получена» и «нет ответа роутера» на первом скриншоте.
3. **Страница «DNS»: `ai-data` - 7,5 с, из них 5,9 с один расчёт в jq,** и он повторяется каждые 15 с, пока страница
   открыта. Страница целиком - 9,4 с. Это второй скриншот.
4. **Запросы состоят из десятков и сотен запусков:** `status` - 2,1 с, `lists-data` - 2,3-2,6 с, `config-data` - 1,5 с.
   Отдельного медленного шага в них нет: это сумма запусков (jq - 28 мс, curl - 41 мс каждый).
5. **Вся конфигурация Keenetic читается целиком** (4,7 с): сторож DNS - каждые 5 минут, Панель - после каждого изменения
   и раз в минуту в фоне.
6. **Одновременные запросы роутер ускоряет только в полтора раза:** 9 запросов «Обзора» по отдельности - 11,2 с,
   вместе - 7,3 с.

Не виноваты: веб-сервер (страница и скрипт отдаются за 5-10 мс), размер ответов, сами переключатели.

## 2. Замер на роутере (16.11.2026, 10:49-10:52)

Цена одного запуска:

| Что | Время |
|---|---:|
| запуск программы (`sh -c :`) | 5 мс |
| подоболочка / подстановка команды `$(...)` | 1,5 / 1,9 мс |
| запуск jq | 28 мс |
| запуск curl | 41 мс |
| запуск awk | 5 мс |
| чтение `api.cgi` оболочкой (весь файл, 285 КБ) | 80 мс |
| один проход awk по конфигурации (96 КБ, 2 410 строк) | 33 мс |

Ответы Keenetic (RCI):

| Запрос | Время | Размер |
|---|---:|---:|
| `show/version`, `show/internet/status`, `show/ip/hotspot` | 0,07-0,09 с | до 9 КБ |
| `show/interface` | 0,17 с | 27 КБ |
| `object-group/fqdn` (только списки: 21 список, 518 доменов) | 0,13 с | 29 КБ |
| `dns-proxy` (только пути списков) | 0,08 с | 4 КБ |
| `ip/route` (только подсети: 1 388) | **2,78 с** | 253 КБ |
| `show/running-config` (вся конфигурация) | **4,72 с** | 113 КБ |

Запросы Панели (два прогона подряд, копии тёплые):

| Запрос | Время, с | | Запрос | Время, с |
|---|---:|---|---|---:|
| `ai-data` | **7,5** | | `update-data`, `security-data`, `journal-data` | 0,9-1,0 |
| `lists-data` | 2,3-2,6 | | `ads-view` (три вида), `ads-https-data` | 0,8-1,0 |
| `status` | 2,1 | | `tunnel-quality` | 0,8 |
| `config-data` | 1,5-1,6 | | `backup-data` | 0,76 |
| `ads-data`, `cleanup-data` | 1,4 | | `vward-off` | 0,75-0,80 |
| `route-data` | 1,2-1,4 | | `auth` | 0,74 |
| `awg-data`, `wifi-data`, `cron-data`, `stability` | 1,1 | | `notes` | 0,73 |
| `services-data`, `ext-update-data` | 1,0 | | `ping` через веб-сервер | 0,79 |

Один выброс: второй прогон `wifi-data` - 4,2 с вместо 1,1. Причину этот замер не показывает.

Страница целиком (все её запросы сразу, как в браузере):

| Страница | Запросов | Время, с |
|---|---:|---:|
| DNS | 5 | 9,4 |
| Обзор | 9 | 7,3 |
| VPN | 9 | 6,8 |
| Маршруты | 8 | 6,5 |

Шаги внутри запроса (трассировка замедляет запрос и местами перемешивает строки параллельных шагов):

| Запрос | Шаг | Время, с |
|---|---|---:|
| все четыре | `vward_profile_load` | 0,63-0,74 |
| `ai-data` | один вызов jq (расчёт путей сервисов) | 5,88 |
| `status` | `vward_components_status` | 0,17 |
| `status` | сборка ответа в jq | 0,12 |
| `config-data` | передача конфигурации в awk, два раза | 0,11 и 0,06 |
| `lists-data` | сборка ответа (awk и jq по конфигурации) | около 0,85 и 0,29 |

Кто ждал Keenetic (журнал VWARD `keenetic-slow.log`, 575 записей с 15.11 06:10 по 16.11 10:52; запись - ответ от 1 с):

| Кто | Что | Раз | В среднем, с | Дольше всего, с |
|---|---|---:|---:|---:|
| сторож DNS (`vward-ads-privacy-dns-guard.sh`) | вся конфигурация | 331 | 4,9 | 7,3 |
| Панель (`api.cgi`) | имя интерфейса (`show/interface/system-name`) | 114 | 2,7 | 3,2 |
| Панель (`api.cgi`) | вся конфигурация | 68 | 6,4 | **19,9** |
| Панель (`api.cgi`) | `ndmc show object-group fqdn` | 30 | 2,4 | 5,0 |
| Панель (`api.cgi`) | `show/interface` | 22 | 2,0 | 4,1 |
| изменения из Панели (`vward-console-config.sh`) | вся конфигурация через ndmc | 6 | 7,3 | 12,4 |

Всего за 25 часов 4 530 запросов к Keenetic, из них 519 медленных. Во время замера: ndm - 25 % процессора,
Xray - 20 %, свободной памяти 126 МБ.

## 3. Причины подробно

### 3.1. Профиль сети находится заново на каждом запросе

- Замер: `vward_profile_load` - 0,63-0,74 с в каждом из четырёх разобранных запросов; запросы без своей работы -
  0,73-0,80 с.
- Код: установщик пишет в `device.conf` только `VWARD_TUNNEL_INTERFACE` и, если сетей несколько, `VWARD_LAN_ADDRESS`
  (`install.sh`, строки 313-316; что в файле владельца сейчас - раздел 8, часть 1). Устройство туннеля, имена WAN и
  LAN в Keenetic и группа не заданы, поэтому каждая
  загрузка берёт карту устройств (`vward-device-profile.sh`, строки 1521-1527) и несколько раз пропускает её через awk.
  В карте по строке на каждую статическую подсеть - 1 388 строк (строки 1061-1064).
- Группа (`VWARD_POLICY_GROUP`) при нескольких списках через VPN не находится вовсе (`vward_select_policy_group`
  отдаёт ответ только при одном кандидате), и поиск повторяется каждый раз.
- Постоянная часть сверх профиля: чтение `api.cgi` до нужного места (до 80 мс; `status` стоит последним), проверка
  `jq -n 1` на каждый запрос (28 мс, `api.cgi` строка 88).
- На эмуляторе этого не видно: там `device.conf` заполнен целиком, загрузка профиля - 0-10 мс. Поэтому ни прошлый
  аудит, ни бюджеты в CI эту цену не показывали.
- Сколько из 0,65 с даёт каждый шаг и сколько останется при заданных именах - команда раздела 8, части 4 и 5.

### 3.2. Пересборка карты устройств раз в 5 минут - внутри запроса и без очереди

- Код: карта живёт 300 с (`VWARD_DEVICE_MAP_TTL`). Кто первым нашёл её старой, тот и собирает
  (`vward_device_map`, строки 1077-1097): `show/interface`, затем отдельный запрос на каждый интерфейс (curl и jq на
  каждый), затем вся конфигурация, причём копия старше 55 с читается заново и запрос ждёт (строки 1028-1065).
  Замка нет: запросы одной страницы собирают карту каждый сам.
- Замер: три загрузки профиля подряд заняли 9,88 с при 0,65 с на загрузку с готовой картой - одна пересборка около
  8,6 с; в журнале ожиданий в эту минуту чтение всей конфигурации 4,9 с. Прямой замер - раздел 8, часть 6.
- Замер: Панель 114 раз ждала имя интерфейса по 2,7 с при пределе запроса 3 с и 68 раз - всю конфигурацию,
  до 19,9 с. Браузер ждёт 20 с (`vward-console.js`, `apiFetch`).
- При открытии Панель сначала ждёт `status`, `security-data` и `update-data` и только потом просит данные страницы:
  попав на пересборку, задерживается вся страница.

### 3.3. `ai-data`: расчёт путей ИИ-сервисов

- Замер: 7,5 с, из них 5,88 с - один вызов jq (`api.cgi`, строки 2890-2953).
- Код: для каждого из 17 ИИ-сервисов перебирается каждая строка `include` всех списков (518) x каждый домен сервиса
  x каждое исключение.
- Код: у `ai` нет срока свежести в `KEY_TTL` (`vward-console.js`), действует 5 с: открытая страница «DNS» повторяет
  расчёт при каждом обновлении, раз в 15 с.
- Код: каталог сервисов (34 КБ) jq читает три раза - в `ai-data` и в `services-data`.

### 3.4. Сотни запусков на запрос

Запуски - счёт на эмуляторе с конфигурацией размера роутера; время - замер на Viva.

| Запрос | подоболочек | программ | из них jq | на Viva, с |
|---|---:|---:|---:|---:|
| `status` | 175 | 33 | 12 (+4 curl) | 2,1 |
| `ads-data` | 124 | 39 | 13 (+6 скриптов, 2 iptables) | 1,4 |
| `ai-data` | 92 | 15 | 5 | 7,5 |
| `config-data` | 84 | 23 | 15 | 1,5 |
| `cleanup-data` | 77 | 12 | 2 | 1,4 |
| `cron-data` | 73 | 9 | 4 | 1,1 |
| `lists-data` | 66 | 21 | 9 (+1 ndmc) | 2,3-2,6 |
| `wifi-data` | 55 | 17 | 8 (+1 curl) | 1,1 |
| `route-data` | 47 | 14 | 6 | 1,2-1,4 |
| `awg-data` | 36 | 13 | 4 | 1,1 |
| `services-data` | 33 | 13 | 6 | 1,0 |
| `notes`, `vward-off`, `security-data`, `backup-data` | 16-20 | 6-7 | 2 | 0,73-1,0 |

Проверка счётом для `status`: 0,75 с постоянная часть + 12 jq (0,34) + 4 curl (0,16) + 175 подоболочек (0,3) +
ответы Keenetic (0,17) + прочие программы (0,07) = 1,8 с из 2,1 с замера. Сходится: отдельного медленного шага нет.

### 3.5. Чтение всей конфигурации Keenetic

- Замер: вся конфигурация - 4,72 с; списки и их пути по частям - 0,13 + 0,08 с. Подсети по частям - 2,78 с: узкое
  чтение подсетей не дешёвое, его нельзя делать на каждый запрос.
- Сторож DNS читает всю конфигурацию каждые 5 минут (331 запись, 4,9 с), хотя в коде у него узкое чтение строк
  `ip name-server` (`vward-ads-privacy-dns-guard.sh`, строки 361-370). Значит, на этом роутере узкое чтение
  `nameservers` отклонено или не отвечает; почему - раздел 8, часть 7.
- Панель берёт всю конфигурацию в 11 местах `api.cgi` (`ndm_cached running`): `status`, `config-data`, `lists-data`,
  `ai-data`, `awg-data`, `wifi-data`, `list-data`, `diagnostics`, `tunnel-probe`, `site-test`, `route-probe`.
  `status` - только ради признака AmneziaWG (строка 3821).
- Копию убирает любое изменение из Панели (`vward-console-config.sh`, строка 239) и любая запись агентов через ndmc
  (`vward-device-profile.sh`, строка 737). Без копии запрос ждёт чтения целиком; остальные запросы ждут в очереди
  до 35 с шагами по 1 с (строки 910-948) - дольше, чем ждёт браузер.
- Сами изменения из Панели читают конфигурацию через ndmc: 7,3 с в среднем, до 12,4 с.
- `lists-data` раз в 120 с в фоне вызывает `ndmc show object-group fqdn` ради числа адресов: 2,4 с, до 5,0 с.

### 3.6. Открытая Панель нагружает роутер без действий

Код (`KEY_TTL`, `REFRESH_SEC = 15`): открытый «Обзор» каждые 15 с запрашивает `status` (2,1 с) и `ads-data` (1,4 с),
раз в 10-25 с - `vward-off`, `notes`, `awg-data` (0,75 + 0,73 + 1,1 с). По замеру это около 5 с работы процессора из
каждых 15, плюс фоновое чтение всей конфигурации раз в минуту (4,7 с работы Keenetic).

### 3.7. Проверено и не виновато

- Веб-сервер: страница - 5 мс, скрипт 675 КБ - 10 мс, стили - 4 мс. Сжатия нет (на запрос со сжатием пришли те же
  675 КБ), но в домашней сети это не время.
- Размер ответов: до 27 КБ.
- Переключатели без записи в Keenetic: ответ быстрый; медленной делает страницу то, что после них убрана копия (3.5).
- Smart DNS у владельца выключен, поэтому проверка сервера DoH (до 4 с внутри `lists-data` и `ai-data`, ответ
  запоминается на 5 минут) сейчас не выполняется. При включённом Smart DNS она идёт внутри запроса страницы.

## 4. Что ещё не установлено

1. Какие шаги внутри загрузки профиля дают 0,65 с и сколько она займёт при заданных именах.
2. Прямое время пересборки карты устройств и какой интерфейс отвечает дольше всех.
3. Почему сторож DNS читает всю конфигурацию: узкое чтение отклонено (и чем отличалось) или не отвечает.
4. Почему `status` не ответил именно в 08:56: пересборка карты (3.2) - самое вероятное, но для этой минуты не доказано.

Пункты 1-3 закрывает команда раздела 8 (одна вставка, только чтение).

## 5. Задание: пакет «Скорость Панели» (fix.40, пункт 0)

Порядок - по весу из замера. Каждый шаг - с замером до и после командой раздела 7.

| № | Что сделать | Закрывает | Готово, когда (на Viva) |
|---|---|---|---|
| 0 | Владелец выполняет команду раздела 8; по результату уточняются шаги 1 и 5 | раздел 4 | цифры в этом файле |
| 1 | Профиль сети: найденные имена хранить и перечитывать только при смене интерфейсов Keenetic; карту устройств собирать одному агенту под замком, никогда внутри запроса Панели | 3.1, 3.2 | `notes` не дольше 0,15 с; в журнале ожиданий нет `api.cgi` с `show/interface/system-name`; ни одного запроса Панели дольше 10 с |
| 2 | `ai-data`: расчёт путей за один проход (индекс доменов по спискам вместо перебора пар); срок свежести `ai` 55-110 с; каталог читать один раз | 3.3 | `ai-data` не дольше 1,5 с; страница «DNS» не дольше 3 с |
| 3 | Меньше запросов на страницу: `status`, `vward-off` и `notes` - одним ответом; данные страницы не ждут `security-data` и `update-data` | 3.1, 3.6 | «Обзор» - не больше 6 запросов при открытии и 1 в 15 с вне действий |
| 4 | Панель без всей конфигурации: `status` - без `running-config`; списки и пути - по частям (0,21 с); подсети - отдельной копией, обновляемой в фоне | 3.5 | после переключателя следующая страница не ждёт 4,7 с; фоновых чтений всей конфигурации от Панели нет |
| 5 | Сторож DNS: вернуть узкое чтение `ip name-server` (причина - по шагу 0) | 3.5 | в журнале ожиданий нет `dns-guard` с `running-config` |
| 6 | Очередь чтения конфигурации: ждать не дольше браузера, отдавать прошлую копию с возрастом | 3.5 | ни один запрос не висит дольше 10 с |
| 7 | Убрать лишние запуски в `status`, `config-data`, `ads-data`, `lists-data`: проверку `jq -n 1`, одиночные jq ради одной строки, повторные чтения одного файла | 3.4 | `status` не дольше 1 с, `lists-data` и `config-data` не дольше 0,8 с |
| 8 | Инструмент замера: `device.conf` как после установщика, конфигурация размера роутера, счёт подоболочек, цены с Viva (5 / 1,9 / 28 / 41 мс), бюджет по запросам в CI | 3.1, 3.4 | тест падает при росте сверх бюджета |

Риски и песочница:

- Шаги 2, 3, 6, 7, 8 - только чтение и показ, песочница не нужна.
- Шаг 1 меняет то, откуда все агенты берут имена туннеля, WAN и LAN, в том числе агенты, которые пишут в
  маршрутизацию. Устаревшее имя после смены туннеля владельцем - риск для маршрутизации: нужен адресный аудит и тест
  «сменили туннель - профиль обновился раньше следующего действия агента».
- Шаги 4 и 5 меняют источник данных для страниц и для сторожа DNS. Сверка «часть равна целому» в библиотеке есть
  (первое чтение части за загрузку сравнивается с целой конфигурацией); шаг 5 - область DNS, адресный аудит.

Ожидаемый итог (расчёт по замеру, не обещание): шаги 1-3 снимают около 0,6 с с каждого запроса и 6 с со страницы
«DNS»; «Обзор» - с 7,3 с примерно до 3,5 с, «DNS» - с 9,4 с примерно до 2,5 с; до цели доводит шаг 7. Цель пакета: любая страница с тёплыми
копиями - до 2 с, после переключателя - до 3 с, ни одного «нет ответа роутера» при работающем роутере.

## 6. Что в первой версии отчёта оказалось неточным

Первая версия (коммит `954f147`) написана до замера. Замер поправил:

- Вес причин: главным считалось чтение всей конфигурации; по замеру главное - постоянная цена запроса (3.1) и
  пересборка карты устройств (3.2). Обе на эмуляторе не видны.
- «Чтение частями 0,04-0,13 с» верно для списков и путей; подсети по частям - 2,78 с.
- Оценка `ai-data` 2,5-7 с - по замеру 7,5 с.
- В `lists-data` искался отдельный медленный шаг (3,7 с 12.11): сейчас 2,3-2,6 с, и это постоянная часть, сборка
  ответа и запуски.
- Цена запуска «около 10 мс на процесс» из аудита 08.11: по замеру 5 мс для программ BusyBox, 28 мс для jq,
  41 мс для curl.

Сверка с `docs/SPEED_AUDIT_2026-11-08.md`: после него сделаны общая копия конфигурации, показ прошлой копии с
обновлением в фоне, чтение через RCI, узкие чтения в библиотеке. Не сделаны: перевод Панели на узкие чтения, один
запрос состояния страницы, замер по шагам (перенесён в fix.40 и выполнен здесь).

## 7. Команда замера 1 (выполнена владельцем 16.11.2026, 10:49)

Команда только диагностическая, ничего не изменяет: читает Keenetic (RCI), запускает запросы Панели так же, как их
запускает открытая Панель, пишет результат в `/tmp` и копирует его в буфер. Запросов с изменениями (POST) и сетевой
диагностики в ней нет. На Viva шла около 3 минут. Ею же замеряется каждый шаг задания до и после.
Стандарт - `docs/termius-standard.md` v2.4: один блок, подоболочка, только ASCII.

```sh
clear
(
P=vward-speed
ls -1t /tmp/$P-*.txt 2>/dev/null | tail -n +5 | while read -r F; do rm -f "$F"; done
OUT="/tmp/$P-$(date +%Y%m%d-%H%M%S).txt"
ln -sfn "$OUT" /tmp/last_result.txt
ln -sfn "$OUT" /tmp/last_$P.txt
MAXB=30000
W="/tmp/$P-work.$$"
CGI=/opt/share/vward/console/www/cgi-bin/api.cgi
LIB=/opt/lib/vward/vward-device-profile.sh
RCI=http://127.0.0.1:79/rci
SH=/opt/bin/sh; [ -x "$SH" ] || SH=sh
JQ=/opt/bin/jq
CURL=/opt/bin/curl; [ -x "$CURL" ] || CURL=curl
send_out() {
  ESC=$(printf '\033')
  SZ=$(wc -c < "$OUT" 2>/dev/null); SZ=${SZ:-0}
  [ "$SZ" -le "$MAXB" ] || echo "[ WARNING ] size=$SZ sent=last $MAXB bytes"
  sed "s/${ESC}\[[0-9;?]*[a-zA-Z]//g" "$OUT" | tail -c "$MAXB" | base64 | tr -d '\r\n' | { read -r B; printf '\033]52;c;%s\a' "$B"; }
}
on_abort() {
  trap '' INT TERM HUP
  rm -rf "$W"
  send_out
  echo "[ ABORTED / DISCONNECTED ]: PARTIAL RESULT SAVED TO /tmp/last_result.txt"
  exit 130
}
trap on_abort INT TERM HUP
tmo() {
  _ts=$1; shift
  "$@" & _tp=$!
  ( sleep "$_ts"; kill "$_tp" 2>/dev/null ) & _tw=$!
  wait "$_tp"; _tr=$?
  kill "$_tw" 2>/dev/null
  return $_tr
}
cs() { read -r _c _ < /proc/uptime; CS=${_c%.*}${_c#*.}; }
tag() { if [ "$2" -ne 0 ]; then echo "[ FAIL ]"; elif [ "$1" -ge 2000 ]; then echo "[ WARNING ]"; else echo "[ OK ]"; fi; }
rep() {
  _rn=$1; _rl=$2; shift 2
  cs; _r0=$CS; _ri=0
  while [ "$_ri" -lt "$_rn" ]; do "$@" >/dev/null 2>&1; _ri=$((_ri + 1)); done
  cs; _rd=$(( (CS - _r0) * 10 ))
  echo "[ OK ] $_rl: $_rd ms / $_rn = $((_rd / _rn)) ms each"
}
one() {
  _ol=$1; shift
  cs; _o0=$CS
  tmo 60 "$@" > "$W/o" 2>/dev/null; _orc=$?
  cs; _od=$(( (CS - _o0) * 10 ))
  echo "$(tag "$_od" "$_orc") $_ol: $_od ms rc=$_orc bytes=$(wc -c < "$W/o")"
}
api() { REQUEST_METHOD=GET QUERY_STRING="action=$1" REMOTE_ADDR=127.0.0.1 HTTP_HOST=127.0.0.1 SERVER_PORT=8088 "$SH" "$CGI"; }
req() {
  cs; _q0=$CS
  tmo 90 api "$1" > "$W/a" 2>/dev/null; _qrc=$?
  cs; _qd=$(( (CS - _q0) * 10 ))
  _qe=$(sed -n 's/.*"error":"\([a-z_]*\)".*/\1/p' "$W/a" | head -n 1)
  echo "$(tag "$_qd" "$_qrc") $2 $1: $_qd ms rc=$_qrc bytes=$(wc -c < "$W/a") ${_qe:+error=$_qe}"
}
page() {
  _pl=$1; shift
  cs; _p0=$CS
  for _pa in "$@"; do api "$_pa" > /dev/null 2>&1 & done
  wait
  cs; _pd=$(( (CS - _p0) * 10 ))
  echo "$(tag "$_pd" 0) page $_pl ($# requests at once): $_pd ms"
}
steps() {
  echo "--- steps of $1 (gaps of 50 ms and more, longest first)"
  cs; _s0=$CS
  REQUEST_METHOD=GET QUERY_STRING="action=$1" REMOTE_ADDR=127.0.0.1 HTTP_HOST=127.0.0.1 SERVER_PORT=8088 "$SH" -x "$CGI" 2>&1 >/dev/null | awk '
    function up(   u, a) { getline u < "/proc/uptime"; close("/proc/uptime"); split(u, a, " "); return a[1] + 0 }
    function out(t,   d) { if (cmd != "") { d = t - ct; if (d >= 0.05) printf "%.2f s  %s\n", d, cmd } }
    substr($0, 1, 2) == "+ " {
      t = up(); out(t); c = $0
      if (c ~ /^\+ [A-Za-z_][A-Za-z_0-9]*=/) sub(/=.*/, "=...", c)
      gsub(/[a-z]+:\/\/[^ ]*/, "<url>", c)
      cmd = substr(c, 1, 90); ct = t
    }
    END { out(up()) }' | sort -rn | head -n 12
  cs; echo "    total with trace: $(( (CS - _s0) * 10 )) ms"
}
dots() {
  _dn=0
  for _df in "$1"/*; do
    [ -f "$_df" ] || continue
    read -r _dh < "$_df" 2>/dev/null || continue
    _dn=$(( _dn + $(wc -c < "$_df") - ${#_dh} - 1 ))
  done
  echo "$_dn"
}
mkdir -p "$W"
{
echo "=== VWARD PANEL SPEED (read-only) $(date '+%Y-%m-%d %H:%M:%S') ==="
if command -v ndmc >/dev/null 2>&1; then ndmc -c "show version" 2>/dev/null | grep -E 'release|title|device'; fi
echo "vward: $(cat /opt/share/vward/VERSION 2>/dev/null)  jq: $($JQ --version 2>/dev/null)  load: $(cat /proc/loadavg)"
MA=$(awk '$1 == "MemAvailable:" {print int($2 / 1024); f = 1} END {if (!f) print -1}' /proc/meminfo)
[ "$MA" -ge 0 ] || MA=$(awk '$1 == "MemFree:" || $1 == "Buffers:" || $1 == "Cached:" {s += $2} END {print int(s / 1024)}' /proc/meminfo)
echo "memory available: $MA MB; cpu: $(grep -c '^processor' /proc/cpuinfo) x $(awk -F: '/cpu model|system type/ {print $2; exit}' /proc/cpuinfo)"
HEAVY=1
[ "$MA" -ge 20 ] || { HEAVY=0; echo "[ SKIPPED ] heavy parts: memory available below 20 MB"; }
[ -r "$CGI" ] || { HEAVY=0; echo "[ NOT_FOUND ] $CGI"; }

echo "--- 1. cost of one start (what every request is made of)"
rep 20 "process start (sh -c :)" "$SH" -c :
rep 1 "100 subshells in one shell" "$SH" -c 'i=0; while [ $i -lt 100 ]; do ( : ); i=$((i + 1)); done'
rep 1 "100 command substitutions" "$SH" -c 'i=0; while [ $i -lt 100 ]; do x=$(echo 1); i=$((i + 1)); done'
rep 10 "jq start (jq -n 1)" "$JQ" -n 1
rep 10 "curl start (curl --version)" "$CURL" --version
rep 10 "awk start" awk 'BEGIN {}'
[ ! -r "$CGI" ] || rep 3 "api.cgi read by the shell (sh -n)" "$SH" -n "$CGI"
[ ! -r "$LIB" ] || rep 3 "profile library load" "$SH" -c ". $LIB; vward_profile_load"

echo "--- 2. Keenetic answers (RCI, read only)"
one "rci show/version" "$CURL" -s -m 10 "$RCI/show/version"
one "rci show/interface" "$CURL" -s -m 10 "$RCI/show/interface"
one "rci show/internet/status" "$CURL" -s -m 10 "$RCI/show/internet/status"
one "rci show/ip/hotspot" "$CURL" -s -m 10 "$RCI/show/ip/hotspot"
one "rci object-group/fqdn (lists only)" "$CURL" -s -m 20 "$RCI/object-group/fqdn"
one "rci dns-proxy (routes of lists only)" "$CURL" -s -m 20 "$RCI/dns-proxy"
one "rci ip/route (subnets only)" "$CURL" -s -m 20 "$RCI/ip/route"
one "rci show/running-config (whole)" "$CURL" -s -m 45 "$RCI/show/running-config"
KC=/tmp/vward-keenetic/running-config
if [ -s "$KC" ]; then
  echo "[ OK ] shared copy of the configuration: age $(( $(date +%s) - $(date -r "$KC" +%s) )) s, $(wc -c < "$KC") bytes, $(wc -l < "$KC") lines"
  echo "       ip route: $(grep -c '^ip route ' "$KC")  lists: $(grep -c '^object-group fqdn ' "$KC")  domains: $(grep -c '^ *include ' "$KC")  interfaces: $(grep -c '^interface ' "$KC")"
  rep 3 "one awk pass over the copy" awk '$1 == "include" {n++} END {print n}' "$KC"
else
  echo "[ WARNING ] shared copy of the configuration is absent now: the next page reads Keenetic whole"
fi

if [ "$HEAVY" = 1 ]; then
echo "--- 3. every request of the Panel, two runs each (as the Panel asks them)"
for A in status config-data lists-data ai-data services-data route-data awg-data wifi-data security-data tunnel-quality ads-data "ads-view&view=stats" "ads-view&view=agh" "ads-view&view=publish-status" ads-https-data update-data ext-update-data cron-data stability backup-data cleanup-data vward-off notes auth journal-data; do
  req "$A" run1
  req "$A" run2
done
echo "--- 4. a page opened: its requests at once"
page Overview status route-data ads-data "ads-view&view=stats" lists-data awg-data tunnel-quality vward-off notes
page DNS ai-data status config-data vward-off notes
page Routes route-data security-data status config-data lists-data services-data vward-off notes
page VPN status security-data config-data route-data awg-data ext-update-data tunnel-quality vward-off notes
echo "--- 5. where the time goes inside the four heaviest"
for A in status config-data lists-data ai-data; do steps "$A"; done
fi

echo "--- 6. who waited for Keenetic (VWARD keeps this itself)"
SL=/opt/var/log/vward/keenetic-slow.log
if [ -s "$SL" ]; then
  echo "slow requests kept: $(wc -l < "$SL"), from $(head -n 1 "$SL" | cut -d'|' -f1) to $(tail -n 1 "$SL" | cut -d'|' -f1)"
  awk -F'|' '{k = $3 " | " $4; n[k]++; s[k] += $5; if ($5 + 0 > m[k] + 0) m[k] = $5}
    END {for (k in n) printf "%5d times, average %.1f s, longest %.1f s: %s\n", n[k], s[k] / n[k], m[k], k}' "$SL" | sort -rn | head -n 15
  echo "the last 12:"
  tail -n 12 "$SL"
else
  echo "[ NOT_FOUND ] $SL"
fi
echo "requests to Keenetic in the last 25 hours: $(dots /tmp/vward-keenetic-calls), of them slow: $(dots /tmp/vward-keenetic-slow)"
for D in /tmp/vward-ndmc-calls/*; do [ -d "$D" ] && echo "ndmc sessions: ${D##*/} $(dots "$D")"; done 2>/dev/null | sort -k4 -rn | head -n 12

echo "--- 7. load now"
cat /proc/loadavg
top -bn1 2>/dev/null | head -n 14 | cut -c1-110
echo "api.cgi running now: $(ps w 2>/dev/null | grep -c '[a]pi.cgi')"

echo "--- 8. the web server itself"
LC=/opt/var/run/vward/console-lighttpd.conf
HB=$(sed -n 's/^server.bind *= *"\(.*\)"/\1/p' "$LC" 2>/dev/null | head -n 1)
HP=$(sed -n 's/^server.port *= *\([0-9]*\).*/\1/p' "$LC" 2>/dev/null | head -n 1)
if [ -n "$HB" ] && [ -n "$HP" ]; then
  for U in /index.html /assets/vward-console.js /assets/vward-console.css "/cgi-bin/api.cgi?action=ping"; do
    echo "[ OK ] GET $U: $("$CURL" -s -m 30 -o /dev/null -w 'http=%{http_code} bytes=%{size_download} s=%{time_total}' "http://$HB:$HP$U")"
  done
  echo "[ OK ] GET vward-console.js asking for gzip: $("$CURL" -s -m 30 -H 'Accept-Encoding: gzip' -o /dev/null -w 'bytes=%{size_download} s=%{time_total}' "http://$HB:$HP/assets/vward-console.js")"
else
  echo "[ NOT_FOUND ] address of the Panel in $LC"
fi
echo "=== END ==="
} 2>&1 | tee "$OUT"
rm -rf "$W"
echo "SUMMARY: pass=$(grep -c '\[ PASS \]' "$OUT") ok=$(grep -c '\[ OK \]' "$OUT") warn=$(grep -c '\[ WARNING \]' "$OUT") fail=$(grep -c '\[ FAIL \]' "$OUT")" | tee -a "$OUT"
send_out
echo "RESULT SENT (OSC52)"
echo "RAW: /tmp/last_result.txt"
)
```

## 8. Команда замера 2: профиль сети и узкие чтения (не выполнялась)

Команда только диагностическая, ничего не изменяет в VWARD и в Keenetic. Что делает: показывает, какие имена заданы в
`device.conf` (без значений); замеряет загрузку профиля как есть и с личной копией `device.conf` в памяти (`/tmp`),
где имена заданы; один раз собирает карту устройств в личный файл - так же, как это и без неё происходит каждые
5 минут (это одно чтение всей конфигурации Keenetic, если копия старше 55 с); спрашивает у Keenetic имя каждого
интерфейса; показывает, приняты ли узкие чтения. Идёт около минуты (оценка).
Проверка: `sh -n` в BusyBox ash - без ошибок; пробный прогон в эмуляторе роутера дошёл до конца.

```sh
clear
(
P=vward-speed2
ls -1t /tmp/$P-*.txt 2>/dev/null | tail -n +5 | while read -r F; do rm -f "$F"; done
OUT="/tmp/$P-$(date +%Y%m%d-%H%M%S).txt"
ln -sfn "$OUT" /tmp/last_result.txt
ln -sfn "$OUT" /tmp/last_$P.txt
MAXB=30000
W="/tmp/$P-work.$$"
LIB=/opt/lib/vward/vward-device-profile.sh
DC=/opt/etc/vward/device.conf
RCI=http://127.0.0.1:79/rci
SH=/opt/bin/sh; [ -x "$SH" ] || SH=sh
JQ=/opt/bin/jq
CURL=/opt/bin/curl; [ -x "$CURL" ] || CURL=curl
NAMES="VWARD_LAN_ADDRESS VWARD_LAN_SUBNET VWARD_LAN_DEVICE VWARD_LAN_INTERFACE VWARD_WAN_DEVICE VWARD_WAN_INTERFACE VWARD_TUNNEL_DEVICE VWARD_TUNNEL_INTERFACE VWARD_POLICY_GROUP VWARD_DNS_SERVER VWARD_PROBE_DNS VWARD_ADGUARD_ADDRESS VWARD_ADGUARD_PORT"
send_out() {
  ESC=$(printf '\033')
  SZ=$(wc -c < "$OUT" 2>/dev/null); SZ=${SZ:-0}
  [ "$SZ" -le "$MAXB" ] || echo "[ WARNING ] size=$SZ sent=last $MAXB bytes"
  sed "s/${ESC}\[[0-9;?]*[a-zA-Z]//g" "$OUT" | tail -c "$MAXB" | base64 | tr -d '\r\n' | { read -r B; printf '\033]52;c;%s\a' "$B"; }
}
on_abort() {
  trap '' INT TERM HUP
  rm -rf "$W"
  send_out
  echo "[ ABORTED / DISCONNECTED ]: PARTIAL RESULT SAVED TO /tmp/last_result.txt"
  exit 130
}
trap on_abort INT TERM HUP
tmo() {
  _ts=$1; shift
  "$@" & _tp=$!
  ( sleep "$_ts"; kill "$_tp" 2>/dev/null ) & _tw=$!
  wait "$_tp"; _tr=$?
  kill "$_tw" 2>/dev/null
  return $_tr
}
cs() { read -r _c _ < /proc/uptime; CS=${_c%.*}${_c#*.}; }
tag() { if [ "$2" -ne 0 ]; then echo "[ FAIL ]"; elif [ "$1" -ge 2000 ]; then echo "[ WARNING ]"; else echo "[ OK ]"; fi; }
one() {
  _ol=$1; shift
  cs; _o0=$CS
  tmo 60 "$@" > "$W/o" 2>/dev/null; _orc=$?
  cs; _od=$(( (CS - _o0) * 10 ))
  echo "$(tag "$_od" "$_orc") $_ol: $_od ms rc=$_orc bytes=$(wc -c < "$W/o")"
}
load_as_is() { "$SH" -c ". $LIB; vward_profile_load"; }
load_given() { VWARD_DEVICE_CONFIG="$W/device.conf" "$SH" -c ". $LIB; vward_profile_load"; }
map_private() { VWARD_DEVICE_MAP_CACHE="$W/map.tsv" "$SH" -c ". $LIB; vward_device_map"; }
age() { echo $(( $(date +%s) - $(date -r "$1" +%s 2>/dev/null || echo 0) )); }
mkdir -p "$W"
{
echo "=== VWARD PANEL SPEED 2: profile and narrow reads (read-only) $(date '+%Y-%m-%d %H:%M:%S') ==="
if command -v ndmc >/dev/null 2>&1; then ndmc -c "show version" 2>/dev/null | grep -E 'release|title|device'; fi
echo "vward: $(cat /opt/share/vward/VERSION 2>/dev/null)  load: $(cat /proc/loadavg)"

echo "--- 1. device.conf: which names it gives (values are not shown)"
if [ -r "$DC" ]; then
  for N in $NAMES; do
    V=$(sed -n "s/^$N=//p" "$DC" | tail -n 1 | tr -d '"\047')
    if [ -n "$V" ]; then echo "[ OK ] $N is given"; else echo "[ WARNING ] $N is not given: found again at every start"; fi
  done
else
  echo "[ NOT_FOUND ] $DC"
fi

echo "--- 2. device map: the copy every program shares (rebuilt when older than 300 s)"
MC=/tmp/vward-device-map.tsv
if [ -f "$MC" ]; then
  echo "[ OK ] map: age $(age "$MC") s, interfaces=$(grep -c '^I' "$MC") routes of lists=$(grep -c '^R' "$MC") static routes=$(grep -c '^S' "$MC") bytes=$(wc -c < "$MC")"
else
  echo "[ WARNING ] map is absent now"
fi
KC=/tmp/vward-keenetic/running-config
[ ! -s "$KC" ] || echo "       copy of the configuration: age $(age "$KC") s"

echo "--- 3. profile load as it is, five runs one by one"
for I in 1 2 3 4 5; do one "profile load, run $I" load_as_is; done
[ ! -f "$MC" ] || echo "       map age after the runs: $(age "$MC") s"

echo "--- 4. where the time goes inside the profile load (gaps of 20 ms and more)"
"$SH" -x -c ". $LIB; vward_profile_load" 2>&1 >/dev/null | awk '
  function up(   u, a) { getline u < "/proc/uptime"; close("/proc/uptime"); split(u, a, " "); return a[1] + 0 }
  function out(t,   d) { if (cmd != "") { d = t - ct; if (d >= 0.02) printf "%.2f s  %s\n", d, cmd } }
  substr($0, 1, 2) == "+ " {
    t = up(); out(t); c = $0; n++
    if (c ~ /^\+ [A-Za-z_][A-Za-z_0-9]*=/) sub(/=.*/, "=...", c)
    gsub(/[a-z]+:\/\/[^ ]*/, "<url>", c)
    cmd = substr(c, 1, 90); ct = t
  }
  END { out(up()); printf "0.00 s  commands traced: %d\n", n }' | sort -rn | head -n 16

echo "--- 5. the same load with every name given (a private copy of device.conf in RAM)"
if [ -r "$DC" ]; then
  ( umask 077; cp "$DC" "$W/device.conf" )
  "$SH" -c ". $LIB; vward_profile_load >/dev/null 2>&1 || exit 1; for N in $NAMES; do eval V=\\\$\$N; echo \"\$N=\$V\"; done" > "$W/found" 2>/dev/null
  if [ -s "$W/found" ]; then
    while IFS= read -r L; do
      N=${L%%=*}; V=${L#*=}
      if [ -z "$V" ]; then
        echo "       $N: the load itself finds nothing"
        [ "$N" != VWARD_POLICY_GROUP ] || V=AdaptiveAuto
      fi
      [ -z "$V" ] || echo "$N=$V" >> "$W/device.conf"
    done < "$W/found"
    for I in 1 2 3; do one "profile load with the names given, run $I" load_given; done
  else
    echo "[ FAIL ] the profile does not load"
  fi
fi

echo "--- 6. one rebuild of the device map into a private file (what happens every 5 minutes)"
one "device map rebuild" map_private
echo "       the slowest interface names:"
"$CURL" -s -m 10 "$RCI/show/interface" 2>/dev/null | "$JQ" -r 'to_entries[] | select(.value | type == "object") | select((.value.type // "") != "Port") | .key' 2>/dev/null | head -n 128 > "$W/ifs"
while IFS= read -r I; do
  cs; T0=$CS
  "$CURL" -s -m 5 -o /dev/null "$RCI/show/interface/system-name?name=$I"; RC=$?
  cs; echo "$(( (CS - T0) * 10 )) ms rc=$RC $I"
done < "$W/ifs" > "$W/ift"
echo "       asked: $(wc -l < "$W/ift") interfaces, together $(awk '{s += $1} END {print s + 0}' "$W/ift") ms"
sort -rn "$W/ift" | head -n 6

echo "--- 7. narrow reads of Keenetic: proven on this router or not"
KP=/tmp/vward-keenetic-part
for PART in groups dnsproxy nameservers iproutes; do
  if [ -e "$KP/$PART.bad" ]; then echo "[ WARNING ] $PART: refused, the whole configuration is read instead: $(cat "$KP/$PART.bad")"
  elif [ -e "$KP/$PART.ok" ]; then echo "[ OK ] $PART: proven"
  else echo "[ NOT_FOUND ] $PART: not tried since the boot"; fi
done
one "rci ip/name-server (what the DNS guard needs)" "$CURL" -s -m 20 "$RCI/ip/name-server"
echo "       answer starts with: $(head -c 80 "$W/o" | tr -cd 'A-Za-z0-9{}":,._ -')"
echo "=== END ==="
} 2>&1 | tee "$OUT"
rm -rf "$W"
echo "SUMMARY: pass=$(grep -c '\[ PASS \]' "$OUT") ok=$(grep -c '\[ OK \]' "$OUT") warn=$(grep -c '\[ WARNING \]' "$OUT") fail=$(grep -c '\[ FAIL \]' "$OUT")" | tee -a "$OUT"
send_out
echo "RESULT SENT (OSC52)"
echo "RAW: /tmp/last_result.txt"
)
```
