# Скорость Панели VWARD: где именно теряется время (диагностика 16.11.2026)

Поручение владельца 16.11.2026: только выяснить, где и почему Панель медленная; ничего не исправлять, не выпускать.
Исполнитель - Claude Code, ветка `ccr-d9589e94-8lasf3` от `e5a38e1` (0.2.0-rc.2.fix.39.3). Роутер не подключался,
код и настройки не менялись. Это пункт 0 пакета fix.40 в `docs/ROADMAP.md` («скорость Панели - замер по шагам»).

## 1. На чём основаны выводы

| Источник | Что даёт | Чего не даёт |
|---|---|---|
| Код `web/cgi-bin/api.cgi`, `web/assets/vward-console.js`, `vward-device-profile.sh` | что каждый запрос читает и запускает | время на роутере |
| `tests/perf/measure-panel.py` на `e5a38e1` (эмулятор, x86) | число запусков программ и обращений к Keenetic по каждому запросу и переключателю | время на роутере; запуски подоболочек не считает |
| Свой профиль на эмуляторе с конфигурацией размера роутера владельца: 126 КБ, 1 388 `ip route`, 22 списка, 516 доменов | запуски подоболочек, запуски программ, самые долгие шаги каждого запроса | время на роутере (x86 быстрее в десятки раз) |
| Замер владельца на Viva 12.11 (ROADMAP): `lists-data` 3,7 с, `status` 1,9 с, `config-data` 1,7 с, первое чтение настроек Keenetic 6,1 с | настоящее время трёх запросов | разбивку по шагам |
| Замеры на Viva 08.11 (комментарии в `vward-device-profile.sh`): вся конфигурация 5,5 с через RCI и 12,7 с через ndmc; чтение одной части 0,04-0,13 с | цену чтения Keenetic | - |
| Журнал владельца `vward-all-2026-11-16_1.txt` | что делал роутер в момент скриншотов | время ответов Панели: его в этом журнале нет |

Время на роутере по каждому шагу даст команда из раздела 6. Она только читает. До её результата всё, что ниже
помечено «оценка», - расчёт по счёту запусков, а не замер.

Журнал владельца: в момент первого скриншота (данные на 08:56, версия fix.39.2) на роутере шла обычная работа
Автоподбора (100 записей за час), обновление поставилось позже, в 09:45. Причины отказа `status` в нём нет: журнал
«кто ждал Keenetic» (`/opt/var/log/vward/keenetic-slow.log`) в выгрузку «Все» не входит. Команда из раздела 6 его читает.

## 2. Что найдено

По убыванию веса. «Доказано» - видно в коде и подтверждено счётом на эмуляторе; «оценка» - время на роутере не замерено.

### 2.1. Панель читает у Keenetic всю конфигурацию там, где хватает трёх её частей

- Доказано: все запросы данных берут `show running-config` целиком (`ndm_cached running`): `status`, `config-data`,
  `lists-data`, `ai-data`, `awg-data`, `wifi-data`, `list-data`, `diagnostics`, `tunnel-probe`, `site-test`,
  `route-probe` - 11 мест в `api.cgi`. Чтение частями (`vward_keenetic_part`: группы, `dns-proxy`, `ip route`) в
  библиотеке есть, Панель им не пользуется.
- Цена (замер 08.11): вся конфигурация 5,5 с (RCI) или 12,7 с (ndmc); часть - 0,04-0,13 с.
- Пока копии нет, запрос ждёт чтения целиком. Копию убирает любое изменение из Панели (`vward-console-config.sh`,
  строка 239) и любая запись агентов через ndmc (`vward-device-profile.sh`, строка 737). Отсюда «после переключателя
  страница думает»: следующий же запрос ждёт 5,5-12,7 с (замер владельца 12.11: 6,1 с).
- Остальные запросы той же страницы ждут того же чтения в очереди: до 35 с, шагами по 1 с
  (`vward_keenetic_config`, строки 910-948). Браузер ждёт 20 с и пишет «нет ответа роутера».
- Пока Панель открыта, копия старше 60 с обновляется в фоне: примерно одно чтение всей конфигурации в минуту
  (5,5 с работы Keenetic из каждых 60).

### 2.2. `status` зависит от всей конфигурации ради одного признака

- Доказано: `status` (его ждёт каждая страница, он же запрашивается каждые 15 с) читает всю конфигурацию только чтобы
  найти строки `wireguard asc` - признак AmneziaWG (`api.cgi`, строка 3821). Нет копии - `status` ждёт, как в 2.1.
- Это прямой путь к картинке первого скриншота: «Часть данных не получена», «нет ответа роутера» при работающем роутере.
- Доказано: при открытии Панель сначала ждёт `status`, `security-data` и `update-data` и только потом просит данные
  страницы (`vward-console.js`, последняя строка запуска). Медленный `status` задерживает всю страницу.

### 2.3. Страница «DNS»: один расчёт в `ai-data` - самый тяжёлый шаг всей Панели

- Доказано: один вызов jq в `ai-data` (`api.cgi`, строки 2890-2953) перебирает каждый ИИ-сервис (17) x каждую строку
  `include` всех списков (516) x каждый домен сервиса x каждое исключение. На эмуляторе: 146 мс из 210 мс всего запроса;
  один этот шаг дольше любого другого запроса Панели целиком (самый долгий из остальных - `status`, 114 мс).
- Оценка для Viva: 2,5-7 с на каждый запрос (146 мс x 17-51: отношение Viva к эмулятору у трёх замеренных запросов).
  Замер - раздел 6, часть 5.
- Доказано: у `ai` нет срока свежести в `KEY_TTL` (`vward-console.js`), действует 5 с - открытая страница «DNS»
  повторяет этот расчёт каждые 15 с. Это второй скриншот: «Роутер отвечает медленно…», «Загрузка…».
- Доказано: каталог сервисов (34 КБ) в `ai-data` и `services-data` jq читает три раза: две проверки и сам ответ.

### 2.4. Каждый запрос - десятки и сотни запусков

Счёт на эмуляторе, тёплые копии, конфигурация размера роутера владельца:

| Запрос | подоболочек | программ | из них jq | читает всю конфигурацию | здесь, мс | на Viva 12.11 |
|---|---:|---:|---:|:---:|---:|---|
| `status` | 175 | 33 | 12 (+4 curl) | да | 114 | 1,9 с |
| `ads-data` | 124 | 39 | 13 (+6 скриптов, 2 iptables) | нет | 61 | не замерено |
| `ai-data` | 92 | 15 | 5 | да | 210 | не замерено |
| `config-data` | 84 | 23 | 15 | да | 77 | 1,7 с |
| `cleanup-data` | 77 | 12 | 2 | нет | 59 | не замерено |
| `cron-data` | 73 | 9 | 4 | нет | 39 | не замерено |
| `lists-data` | 66 | 21 | 9 (+1 ndmc) | да | 73 | 3,7 с |
| `wifi-data` | 55 | 17 | 8 (+1 curl) | да | 41 | не замерено |
| `route-data` | 47 | 14 | 6 | нет | 41 | не замерено |
| `update-data` | 39 | 22 | 4 | нет | 48 | не замерено |
| `awg-data` | 36 | 13 | 4 | да | 35 | не замерено |
| `ext-update-data` | 35 | 19 | 7 | нет | 50 | не замерено |
| `services-data` | 33 | 13 | 6 | нет | 44 | не замерено |
| `security-data`, `notes`, `vward-off`, `backup-data` | 16-20 | 6-7 | 2 | нет | 16-23 | не замерено |

- `status` и `config-data` на Viva медленны не из-за одного шага: это сумма 100-200 запусков. Отношение «Viva к
  эмулятору» у них 17 и 22 раза - ровно цена запусков на слабом процессоре.
- У `lists-data` отношение 51: там есть шаг сверх запусков. Кандидаты (замер покажет): сборка ответа в jq на 1 388
  подсетях и 516 доменах; `show object-group fqdn` через ndmc (сотни КБ; на эмуляторе вызывается при каждом запросе,
  потому что пустой ответ не запоминается - на роутере проверить по счётчику «ndmc sessions: api.cgi»).
- Доказано: модель прошлого аудита (`measure-panel.py`: программы x 10 мс) подоболочки не считает и занижает время
  в 3-17 раз: `config-data` по модели 0,1 с, на Viva 1,7 с.

### 2.5. Постоянная цена каждого запроса, до всякой работы

Доказано, на каждый запрос, даже `notes` и `vward-off`:

- проверка `jq -n 1` (один запуск jq только чтобы убедиться, что jq жив), `api.cgi` строка 88;
- загрузка библиотеки профиля: 84 КБ, 1 400 строк, плюс `vward_profile_load`;
- разбор самого `api.cgi` до нужного места: 285 КБ; `status` стоит последним - читается весь файл.

На эмуляторе это 13-16 мс из 16-23 мс лёгкого запроса: у лёгких запросов почти всё время - эта постоянная часть.
Каждая страница добавляет к своим данным `vward-off` и `notes`.

### 2.6. Открытая Панель нагружает роутер сама, без действий

Доказано (`KEY_TTL`, `REFRESH_SEC = 15`): открытый «Обзор» каждые 15 с запрашивает `status` (всегда) и `ads-data`
(срок 10 с), раз в 10-25 с `vward-off`, `notes`, `awg-data` - около 350 подоболочек и 90 программ за круг, плюс фоновое
чтение всей конфигурации раз в минуту (2.1). Оценка для Viva: 2-3 с процессора из каждых 15.

Открытие страницы - 6-12 запросов сразу; у роутера два ядра, запросы делят их: страница готова не раньше суммы.

### 2.7. Что проверено и не виновато

- Размер ответов: самый большой - `lists-data` 31 КБ, `services-data` 22 КБ.
- Скрипт Панели 675 КБ отдаётся без сжатия (со сжатием было бы 204 КБ), но повторно не качается (ETag, ответ 304):
  это цена только первого открытия после обновления. Замер - раздел 6, часть 8.
- Переключатели без записи в Keenetic (агенты, сторожа, классификатор, Wi-Fi, пауза рекламы): 6-12 программ, ответ
  быстрый. Медленными их делает то, что после них убрана копия конфигурации (2.1).
- Smart DNS у владельца выключен, поэтому проверка сервера DoH (до 4 с внутри `lists-data` и `ai-data`, ответ
  запоминается на 5 минут) сейчас не выполняется. При включённом Smart DNS она идёт внутри запроса страницы -
  учесть в задании.

## 3. Чего диагностика не установила

1. Время каждого шага на Viva: сколько стоит запуск jq, curl, подоболочки; сколько занимает расчёт `ai-data`.
2. Что именно даёт 3,7 с в `lists-data` сверх запусков.
3. Почему `status` не ответил за 20 с в 08:56: ожидание чтения конфигурации (2.1-2.2) - самое вероятное, но не доказано.
4. Как часто и кем убирается копия конфигурации за сутки.

Всё это закрывает одна команда из раздела 6.

## 4. Задание: пакет «Скорость Панели» (fix.40, пункт 0)

Только чтение: пакет не меняет маршрутизацию, DNS и то, что VWARD пишет в Keenetic, - песочница не нужна.
Порядок - по весу; каждый шаг с замером до и после той же командой (раздел 6).

| № | Что сделать | Закрывает | Готово, когда |
|---|---|---|---|
| 0 | Владелец выполняет команду раздела 6 и присылает результат; по нему уточняются шаги 4-6 | раздел 3 | цифры в этом файле вместо оценок |
| 1 | `status`: признак AmneziaWG - из узкого чтения (или из ответа `show/interface`, если он его содержит: проверить на роутере), без всей конфигурации | 2.2 | `status` не читает `running-config`; без копии отвечает за то же время, что с копией |
| 2 | Запросы страниц читают части (`vward_keenetic_parts groups dnsproxy iproutes`), целиком - только диагностика | 2.1 | после переключателя следующая страница не ждёт 5,5 с; фоновых чтений всей конфигурации от Панели нет |
| 3 | `ai-data`: расчёт путей за один проход (индекс доменов по спискам вместо перебора всех пар); срок свежести `ai` 55-110 с; каталог читать один раз | 2.3 | расчёт на конфигурации владельца в эмуляторе не дольше остальных шагов запроса; на Viva `ai-data` в пределах 2 с |
| 4 | Убрать лишние запуски: проверку `jq -n 1` на каждый запрос, одиночные jq ради одной строки, повторные чтения одного файла; собрать ответ `status` и `config-data` одним jq | 2.4, 2.5 | `status` не больше 60 подоболочек и 12 программ, `config-data` не больше 30 и 8 |
| 5 | `lists-data`: убрать шаг, который покажет замер (сборка в jq или `show object-group fqdn`) | 2.4 | `lists-data` на Viva в пределах 2 с |
| 6 | Очередь чтения конфигурации: ждать не дольше, чем ждёт браузер; отдавать прошлую копию с отметкой возраста | 2.1 | ни один запрос страницы не висит дольше 10 с |
| 7 | Обновление открытой страницы: `ads-data` и `status` не чаще нужного; `vward-off` и `notes` - одним запросом со `status` | 2.6 | открытый «Обзор»: не больше 1 запроса в 15 с вне действий |
| 8 | `measure-panel.py`: считать подоболочки, конфигурация размера роутера, бюджет по запросам в CI | 2.4 | тест падает при росте числа запусков сверх бюджета |

Не входит: перевод API на Go-ядро, сжатие статики, изменения записи в Keenetic. Риск: шаг 2 меняет источник данных
страниц - нужна сверка «часть равна целому» (она в библиотеке уже есть: первое чтение части за загрузку сравнивается
с целой конфигурацией) и тест на реальной форме ответа RCI.

Цель пакета (предложение, уточнить после шага 0): любая страница с тёплыми копиями - до 2 с, после переключателя -
до 3 с, ни одного «нет ответа роутера» при работающем роутере.

## 5. Сверка с прошлым аудитом (`docs/SPEED_AUDIT_2026-11-08.md`)

- Сделано после него: общая копия конфигурации, показ прошлой копии с обновлением в фоне, чтение через RCI вместо
  ndmc, узкие чтения в библиотеке. Первое открытие страницы при живой копии больше не ждёт 4,8 с.
- Не сделано: Панель не переведена на узкие чтения; «один запрос состояния страницы»; замер по шагам (перенесён в fix.40).
- Новое в этой диагностике: расчёт `ai-data` (2.3), зависимость `status` от всей конфигурации (2.2), счёт подоболочек
  и ошибка модели времени (2.4), очередь до 35 с против 20 с у браузера (2.1).

## 6. Команда замера на роутере (Termius)

Команда только диагностическая, ничего не изменяет: читает Keenetic (RCI), запускает запросы Панели так же, как их
запускает открытая Панель, пишет результат в `/tmp` и копирует его в буфер. Запросов с изменениями (POST) и сетевой
диагностики в ней нет. Идёт 2-4 минуты; на это время Панель лучше закрыть, чтобы она не мешала замеру.
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

Проверка команды: `sh -n` в BusyBox ash - без ошибок; пробный прогон в эмуляторе роутера (`tests/perf/emulator`) дошёл
до конца. На роутере команда не выполнялась.
