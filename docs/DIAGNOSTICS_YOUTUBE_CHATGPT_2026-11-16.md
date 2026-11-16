# YouTube Shorts и ChatGPT без VPN на телефоне: разбор 16.11.2026

Поручение владельца: только выяснить причину; ничего не менять в VWARD и Keenetic, не выпускать. Исполнитель -
Claude Code, ветка `ccr-d9589e94-8lasf3`. Источники: сводка владельца (16:53-16:57), журнал «Все» владельца
`vward-all-2026-11-16_2.txt` (по 17:00), код VWARD на `556aa11`, прошлые разборы (`docs/DIAGNOSTICS_SUPERCELL_2026-10-31.md`,
`docs/ROADMAP.md` о YouTube 13.10). Роутер не подключался.

Симптомы: ChatGPT иногда пишет «недоступен в вашем регионе»; Shorts грузится на треть-половину и встаёт; то работает,
то нет; с VPN на телефоне всё работает.

## 0. Итог (после команды владельца в 17:13)

1. **YouTube: виноват туннель, а не маршруты.** Все соединения телефона с Google (24 TCP и 23 UDP/QUIC) шли через
   туннель, ни одно - мимо. Напрямую YouTube у провайдера не открывается вовсе. Туннель за день 11 раз молчал по
   две минуты и дольше, даёт 7,6 Мбит/с и в 17:19:15 ещё раз не ответил 6 с (уже на сервере 28). Куски Shorts,
   попавшие на такие минуты, не приходят.
2. **ChatGPT: в VPN идут только отдельные имена, которые выучил Автоподбор, и он может их терять.**
   - На роутере `openai.com`, `oaistatic.com`, `oaiusercontent.com` не входят ни в один список; `chatgpt.com` есть
     только в группе Автоподбора. Остальные имена OpenAI (не выученные) идут через провайдера, то есть из России.
   - До обновления 16.11 около 05:00 Автоподбор считал ответ ChatGPT `http 403` (отказ страны) «открывается напрямую»
     (15.11 13:25; 16.11 02:23-03:12) и не отправлял ChatGPT в VPN. В 05:25 после обновления те же имена ушли в VPN.
   - Ошибка, которая остаётся (код): ежечасная проверка засчитывает прямой 403 как «открывается напрямую», если в эту
     минуту не ответил и туннель. В 11:08 так и случилось: `MAINT_DIRECT_CONFIRM chatgpt.com streak=1/3 http 403` -
     за 30 с до перезапуска туннеля; в 11:13 то же для `aw.api.openai.com`. Три таких случая - и `chatgpt.com`
     убирается из VPN до следующего изучения. При 11 молчаниях туннеля в день это вопрос времени.
3. **IPv6 сейчас ни при чём.** Глобального IPv6 нет ни у провайдера, ни в домашней сети, IPv6-маршрута по умолчанию
   нет. Подключение по IPv6 с регионом «DE» из сводки, скорее всего, было с включённым VPN на телефоне. Туннель
   без IPv6 (1.2) - риск на будущее, если провайдер включит IPv6.

## 1. Что доказано

### 1.1. Туннель VLESS сегодня молчал по две минуты и больше 11 раз (журнал)

| День | Перезапусков Xray агентом |
|---|---:|
| 13.11 | 1 |
| 14.11 | 4 |
| 15.11 | 3 |
| 16.11 | **11** |

16.11: 07:49; 11:04, 11:08, затем в 11:13 туннель сам перешёл с сервера 28 на сервер 19 `de28.xrock.cc`;
после этого ещё 8 перезапусков: 13:41, 13:45, 14:23, 14:39, 14:55, 15:51, 16:44, **16:54**. Тайм-аут YouTube в
16:53 из сводки владельца приходится на минуту до перезапуска в 16:54:23.

Почему каждая запись - это минимум две минуты без связи (код `vward-vless-engine.sh`, `op_supervise`): агент
компонентов раз в минуту открывает `http://1.1.1.1/cdn-cgi/trace` через адаптер туннеля (до 8 с). Первый отказ
только запоминается, перезапуск - на второй минуте подряд. Сам перезапуск обрывает все соединения через туннель,
и ещё 180 с туннель не проверяется.

Ложной тревогой это не выглядит: перед перезапусками Автоподбор в те же минуты получал «через VPN: тайм-аут»
для адресов, которые обычно открываются (16:43 `doubleclick.net` «vpn: tls: timeout»; 14:53-14:55 пять отказов подряд;
13:42 `api.themoviedb.org` «vpn: connect: timeout»).

Как это даёт симптомы: Shorts качается кусками через туннель - кусок, попавший на тихие минуты или на перезапуск,
не приходит, и видео встаёт. ChatGPT в эти минуты не отвечает. С VPN на телефоне трафик идёт мимо туннеля роутера,
поэтому всё работает.

Не установлено: виноват сервер (`de28.xrock.cc`: 8 из 11 сегодняшних случаев после перехода на него) или сам роутер
(во время замера скорости Панели в 10:52 Xray занимал 20 % процессора, ndm - 25 %, load 3,4). Ошибки Xray
(`/opt/var/run/vward/vless-engine/v0.err`) в журнал «Все» не попадают - их читает команда раздела 4.

### 1.2. IPv6 в туннель не попадает никогда (код)

- VWARD создаёт туннелю VLESS только IPv4-адрес `198.18.N.1/30` (`vward-vless-engine.sh`, строка 570). IPv6 у туннеля нет.
- Keenetic собирает IPv6-адреса доменов списков (`_NDM_OGDN_6_@<список>`), но 31.10 правила маршрутизации
  ссылались только на 2 из 29 таких наборов (`docs/DIAGNOSTICS_SUPERCELL_2026-10-31.md`). Тогда это не мешало:
  глобального IPv6 в домашней сети не было.
- Если в домашней сети появится IPv6, всё, что телефон откроет по IPv6, пойдёт мимо туннеля через провайдера.
- Команда 17:13: глобального IPv6 нет ни у провайдера, ни в домашней сети - сейчас это не причина.
- Защита от этого записана в `docs/ROADMAP.md` (не отдавать AAAA для доменов, идущих через VPN; проверка «IPv6 обходит
  VPN» в диагностике) и не сделана.


## 2. Что не подтверждено и проверяется командой

| Гипотеза из сводки | Как проверяется (раздел 4) |
|---|---|
| IPv6 телефона обходит VWARD (не подтвердилось) | IPv6 у провайдера и в домашней сети; соединения телефона по IPv6 к адресам из VPN-списков |
| не все адреса видеосерверов попадают в VPN | для каждого IPv4-соединения: в каком наборе списка адрес и через какой адрес роутера оно вышло (адрес туннеля или провайдера, по NAT) |
| Xray теряет работу при поднятом интерфейсе | доказано журналом (1.1); команда добавляет ошибки Xray, скорость через туннель и пробу раз в 5 с |
| Route Engine неправильно применяет маршруты | в каком списке ChatGPT и YouTube и куда идут эти списки |
| QUIC/UDP, MTU | соединения UDP 443 и их путь; MTU туннеля |
| DNS: телефон спрашивает не роутер | соединения к порту 853 (частный DNS Android) и к публичным серверам DoH |
| `ndnproxy: rogue answer` от 1.1.1.1 | число таких записей в журнале Keenetic за день |

## 3. Результат команды (16.11.2026, 17:13, сервер 28 выбран владельцем в 17:12)

| Что | Результат |
|---|---|
| IPv6 | глобального нет у провайдера и в домашней сети; маршрута IPv6 по умолчанию нет; у туннеля только `198.18.0.1/30` и link-local |
| Списки | 20 путей, 19 - в `OpkgTun0`. YouTube (`youtube.com`, `googlevideo.com`, `ytimg.com`, `youtubei.googleapis.com`, `ggpht.com`) - `domain-list25` -> туннель. `chatgpt.com` - только `AdaptiveAuto`; `openai.com`, `oaistatic.com`, `oaiusercontent.com` - ни в одном списке |
| chatgpt.com с роутера | туннель: 200, страна DE, 0,9 с; провайдер: 200, страна RU, 0,3 с |
| YouTube с роутера | туннель: 204 за 0,38 с, видеосервер Франкфурт; провайдер: нет ответа за 6 с |
| Скорость туннеля | 8 МБ за 8,5 с - 7,6 Мбит/с |
| Проба туннеля раз в 13 с (40 с ожидания) | 7 ответов 0,38-0,90 с, один - нет ответа за 6 с (17:19:15) |
| Соединения телефона (192.168.1.71) к порту 443 | через туннель: 24 TCP (7,5 МБ) и 23 UDP/QUIC (0,6 МБ), все к адресам Google; через провайдера: 7 TCP, 87 КБ (куда - в срез 25 крупнейших не попали) |
| Частный DNS (853) и DoH к публичным серверам | 0 |
| Ошибки Xray с последнего запуска (17:12) | одна: `received DATA after END_STREAM` (транспорт xHTTP) |
| Запусков Xray за день | 14 |
| `ndnproxy: rogue answer` | 12 за день |
| Не сработало в команде | DNS роутера (`nslookup -type` в BusyBox Keenetic ничего не вернул), счёт `ipset`/`iptables` (нет в PATH) - на выводы не влияет |

## 4. Задание (предложение, не выполнялось)

| № | Что | Почему | Риск |
|---|---|---|---|
| 1 | Ежечасная проверка Автоподбора: прямой 403 (и чужой сертификат, обрыв после первых КБ) не засчитывать как «открывается напрямую», когда туннель в эту минуту не отвечает - как уже сделано для прямых отказов (`reconcile.go`, `vpnOK`) | `chatgpt.com` иначе выпадает из VPN после трёх молчаний туннеля на проверке | меньше удалений из VPN; запись в маршрутизацию не добавляется; тест: 403 напрямую + туннель молчит -> серия не растёт |
| 2 | ChatGPT целиком в VPN: список с `openai.com`, `chatgpt.com`, `oaistatic.com`, `oaiusercontent.com` (сервис ИИ «через VPN»), а не отдельные выученные имена. Сначала выяснить, почему при «Все ИИ-сервисы: VPN» в Панели такого списка на роутере нет (в 16:41 владелец удалил `domain-list24` - каким сервисом он был, не установлено) | имена, которых Автоподбор ещё не видел, идут из России | решение владельца; маршрутизация - через Песочницу |
| 3 | Туннель: сравнить серверы подписки по молчаниям за сутки (журнал VLESS + проба) и показать это в Панели; выбрать сервер - владелец | 11 молчаний за день, 8 из них на сервере 19 | только чтение и показ |
| 4 | QUIC через туннель: проверить, не лучше ли YouTube с отклонённым UDP 443 через туннель (давний пункт ROADMAP) | 23 соединения QUIC идут через Xray с транспортом xHTTP | меняет путь трафика - через Песочницу |
| 5 | Команда диагностики: DNS роутера - через `nslookup` без `-type`, вывод соединений провайдера отдельно от 25 крупнейших | пробелы раздела 3 | нет |

IPv6 (AAAA для VPN-доменов) - пункт ROADMAP остаётся на будущее, сейчас не нужен.

## 5. Команда для роутера (Termius, выполнена владельцем 16.11.2026 в 17:13)

Команда только диагностическая, ничего не изменяет в VWARD и Keenetic. Как запускать: воспроизвести сбой на
телефоне (Wi-Fi роутера, VPN на телефоне выключен: открыть ChatGPT и отправить сообщение, полистать Shorts до
зависания), **сразу после этого** вставить команду. Первым делом она снимает таблицу соединений роутера
(conntrack) - соединения телефона там ещё видны. Затем открывает с роутера chatgpt.com и YouTube через туннель,
через провайдера и по IPv6, скачивает 8 МБ через туннель (`speed.cloudflare.com`), 40 с проверяет туннель раз в 5 с и
снимает таблицу ещё раз. Идёт около двух минут (оценка). Адреса IPv6 в выводе обрезаны.
Проверка: `sh -n` в BusyBox ash - без ошибок; пробный прогон в эмуляторе роутера дошёл до конца.

```sh
clear
(
P=vward-path
ls -1t /tmp/$P-*.txt 2>/dev/null | tail -n +5 | while read -r F; do rm -f "$F"; done
OUT="/tmp/$P-$(date +%Y%m%d-%H%M%S).txt"
ln -sfn "$OUT" /tmp/last_result.txt
ln -sfn "$OUT" /tmp/last_$P.txt
MAXB=30000
W="/tmp/$P-work.$$"
LIB=/opt/lib/vward/vward-device-profile.sh
CURL=/opt/bin/curl; [ -x "$CURL" ] || CURL=curl
JQ=/opt/bin/jq
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
mask6() { sed -E 's/([0-9a-fA-F]{1,4}:[0-9a-fA-F]{1,4}:[0-9a-fA-F]{1,4}):[0-9a-fA-F:]+/\1:x/g'; }
trace() {
  _tl=$1; shift
  _tb=$(tmo 15 "$CURL" -s -m 12 --connect-timeout 6 "$@" -w '\nHTTP=%{http_code} T=%{time_total}' https://chatgpt.com/cdn-cgi/trace 2>/dev/null)
  _tc=$(printf '%s\n' "$_tb" | sed -n 's/^HTTP=\([0-9]*\) T=\(.*\)/code=\1 time=\2s/p')
  _tg=$(printf '%s\n' "$_tb" | sed -n 's/^loc=//p')
  _tv=$(printf '%s\n' "$_tb" | sed -n 's/^ip=//p' | grep -c ':')
  if [ -n "$_tg" ]; then echo "[ OK ] chatgpt.com $_tl: $_tc country=$_tg ipv6_exit=$_tv"; else echo "[ FAIL ] chatgpt.com $_tl: ${_tc:-no answer}"; fi
}
yt() {
  _yl=$1; shift
  _yc=$(tmo 15 "$CURL" -s -m 12 --connect-timeout 6 -o /dev/null "$@" -w 'code=%{http_code} time=%{time_total}s' https://www.youtube.com/generate_204 2>/dev/null)
  _ym=$(tmo 15 "$CURL" -s -m 12 --connect-timeout 6 "$@" 'https://redirector.googlevideo.com/report_mapping?di=no' 2>/dev/null | head -n 1 | sed 's/.*=>//' | cut -c1-60)
  case "$_yc" in code=204*) _yt="[ OK ]" ;; *) _yt="[ FAIL ]" ;; esac
  echo "$_yt youtube $_yl: ${_yc:-no answer}; video cluster:${_ym:- no answer}"
}
mkdir -p "$W"
{
echo "=== VWARD PATH OF CHATGPT AND YOUTUBE (read-only) $(date '+%Y-%m-%d %H:%M:%S') ==="
if command -v ndmc >/dev/null 2>&1; then ndmc -c "show version" 2>/dev/null | grep -E 'release|title|device'; fi
echo "vward: $(cat /opt/share/vward/VERSION 2>/dev/null)  load: $(cat /proc/loadavg)"
[ ! -r "$LIB" ] || { . "$LIB" && vward_profile_load >/dev/null 2>&1; }
LAN=${VWARD_LAN_DEVICE:-br0}; WAN=${VWARD_WAN_DEVICE:-eth3}; TUN=${VWARD_TUNNEL_DEVICE:-opkgtun0}; TIF=${VWARD_TUNNEL_INTERFACE:-OpkgTun0}
echo "devices: lan=$LAN wan=$WAN tunnel=$TUN ($TIF)"

echo "--- 0. connections now (taken first: those of the failure just seen)"
CT=/proc/net/nf_conntrack
if [ -r "$CT" ]; then
  cp "$CT" "$W/ct1"
  echo "[ OK ] conntrack: $(wc -l < "$W/ct1") entries; with byte counts: $(grep -c ' bytes=' "$W/ct1")"
else
  : > "$W/ct1"
  echo "[ NOT_FOUND ] $CT"
fi

echo "--- 1. IPv6 on the router"
ip -6 addr show scope global 2>/dev/null | awk '/^[0-9]+:/ {d = $2} $1 == "inet6" {print "       " d " " $2}' | mask6
N6W=$(ip -6 addr show dev "$WAN" scope global 2>/dev/null | grep -c 'inet6')
N6L=$(ip -6 addr show dev "$LAN" scope global 2>/dev/null | grep -c 'inet6')
N6T=$(ip -6 addr show dev "$TUN" 2>/dev/null | grep -c 'inet6.*global')
if [ "$N6W" -gt 0 ] || [ "$N6L" -gt 0 ]; then echo "[ WARNING ] global IPv6: provider side=$N6W, home network=$N6L, tunnel=$N6T"; else echo "[ OK ] no global IPv6 on the provider side or the home network"; fi
echo "       IPv6 default routes:"
ip -6 route show table all 2>/dev/null | grep -E '^default|^::/0' | head -n 6 | sed 's/^/       /' | mask6
echo "       IPv6 rules: $(ip -6 rule show 2>/dev/null | wc -l), of them with a mark: $(ip -6 rule show 2>/dev/null | grep -c fwmark)"
echo "       IPv4 rules with a mark: $(ip rule show 2>/dev/null | grep -c fwmark)"
echo "       tunnel $TUN: $(ip -o addr show dev "$TUN" 2>/dev/null | awk '{printf "%s %s; ", $3, $4}') mtu $(cat /sys/class/net/$TUN/mtu 2>/dev/null)"
T4=$(ip -o -4 addr show dev "$TUN" 2>/dev/null | awk '{sub(/\/.*/, "", $4); print $4; exit}')
W4=$(ip -o -4 addr show dev "$WAN" 2>/dev/null | awk '{sub(/\/.*/, "", $4); print $4; exit}')
ip -6 addr show scope global 2>/dev/null | awk '$1 == "inet6" {sub(/\/.*/, "", $2); print $2}' > "$W/own6"

echo "--- 2. VPN lists and their IPv4/IPv6 address sets"
KC=/tmp/vward-keenetic/running-config
if [ -s "$KC" ]; then cp "$KC" "$W/rc"; else tmo 40 "$CURL" -s -m 35 http://127.0.0.1:79/rci/show/running-config 2>/dev/null | "$JQ" -r '.message[]?' > "$W/rc" 2>/dev/null; fi
awk '/^dns-proxy$/ {d = 1; next} /^!/ {d = 0} d && $1 == "route" && $2 == "object-group" {print $3, $4}' "$W/rc" > "$W/routes"
awk '/^object-group fqdn / {g = $3; next} /^!/ {g = ""} g != "" && $1 == "include" {print g, tolower($2)}' "$W/rc" > "$W/incl"
echo "       lists routed: $(wc -l < "$W/routes"), of them to $TIF: $(awk -v t="$TIF" '$2 == t' "$W/routes" | wc -l)"
for S in chatgpt.com openai.com oaistatic.com oaiusercontent.com youtube.com googlevideo.com ytimg.com youtubei.googleapis.com ggpht.com; do
  G=$(awk -v d="$S" '$2 == d {print $1}' "$W/incl" | tr '\n' ' ')
  R=; for X in $G; do R="$R $X->$(awk -v g="$X" '$1 == g {print $2; exit}' "$W/routes")"; done
  echo "       $S:${R:- in no list}"
done
if command -v ipset >/dev/null 2>&1; then
  ipset -t list 2>/dev/null | awk '/^Name:/ {n = $2} /^References:/ {r = $2} /^Number of entries:/ {print n, r, $4}' > "$W/sets"
  if [ ! -s "$W/sets" ]; then
    for S in $(ipset -n list 2>/dev/null | grep '^_NDM_OGDN_'); do
      echo "$S $(ipset -t list "$S" 2>/dev/null | awk '/^References:/ {print $2}') $(ipset list "$S" 2>/dev/null | awk 'f {n++} /^Members:/ {f = 1} END {print n + 0}')"
    done > "$W/sets"
  fi
  echo "       list                   v4:entries/refs  v6:entries/refs  route"
  awk -v t="$TIF" '$2 == t {print $1}' "$W/routes" | while read -r G; do
    A=$(awk -v s="_NDM_OGDN_4_@$G" '$1 == s {print $3 "/" $2}' "$W/sets")
    B=$(awk -v s="_NDM_OGDN_6_@$G" '$1 == s {print $3 "/" $2}' "$W/sets")
    printf '       %-22s %-16s %-16s %s\n' "$G" "${A:--}" "${B:--}" "$TIF"
  done
  echo "       IPv6 sets with addresses and no rule using them: $(awk '$1 ~ /^_NDM_OGDN_6_/ && $3 > 0 && $2 == 0' "$W/sets" | wc -l) of $(awk '$1 ~ /^_NDM_OGDN_6_/' "$W/sets" | wc -l)"
else
  echo "[ NOT_FOUND ] ipset"
fi
echo "       mark rules: IPv4 $(iptables -t mangle -S _NDM_DNSRT_PREROUTING_MANGLE 2>/dev/null | grep -c match-set), IPv6 $(ip6tables -t mangle -S _NDM_DNSRT_PREROUTING_MANGLE 2>/dev/null | grep -c match-set)"

echo "--- 3. what the router's DNS answers the phone (A = IPv4, AAAA = IPv6)"
DNS=${VWARD_LAN_ADDRESS:-127.0.0.1}
for H in chatgpt.com ab.chatgpt.com www.youtube.com youtubei.googleapis.com i.ytimg.com redirector.googlevideo.com; do
  NA=$(tmo 6 nslookup -type=A "$H" "$DNS" 2>/dev/null | awk '/^Name:/ {f = 1} f && /^Address/ {n++} END {print n + 0}')
  NQ=$(tmo 6 nslookup -type=AAAA "$H" "$DNS" 2>/dev/null | awk '/^Name:/ {f = 1} f && /^Address/ && /:.*:/ {n++} END {print n + 0}')
  echo "       $H: A=$NA AAAA=$NQ"
done

echo "--- 4. the same sites from the router: through the tunnel, through the provider, over IPv6"
trace "tunnel IPv4" -4 --interface "$TUN"
trace "provider IPv4" -4 --interface "$WAN"
trace "IPv6 (default route)" -6
yt "tunnel IPv4" -4 --interface "$TUN"
yt "provider IPv4" -4 --interface "$WAN"
yt "IPv6 (default route)" -6
SP=$(tmo 25 "$CURL" -s -4 --interface "$TUN" -m 20 --connect-timeout 6 -o /dev/null -w '%{size_download} %{time_total} %{speed_download}' 'https://speed.cloudflare.com/__down?bytes=8000000' 2>/dev/null)
echo "[ OK ] tunnel download 8 MB: $(echo "$SP" | awk '{printf "%d bytes in %.1f s = %.1f Mbit/s", $1, $2, $3 * 8 / 1000000}')"

echo "--- 5. tunnel steadiness: a probe every 5 s for 40 s"
I=0
while [ "$I" -lt 8 ]; do
  R=$(tmo 8 "$CURL" -s -4 --interface "$TUN" -m 6 --connect-timeout 4 -o /dev/null -w '%{http_code} %{time_total}' https://www.google.com/generate_204 2>/dev/null)
  echo "       $(date +%H:%M:%S) ${R:-no answer}"
  I=$((I + 1)); sleep 5
done
[ ! -r "$CT" ] || cp "$CT" "$W/ct2"

echo "--- 6. connections of the home devices to port 443 (both snapshots), and their path"
echo "       path: TUN = left through the tunnel ($T4), ISP = through the provider ($W4), IPv6 = no NAT, the tunnel has no IPv6"
cat "$W/ct1" "$W/ct2" 2>/dev/null | awk -v t4="$T4" -v w4="$W4" -v own="$W/own6" '
  BEGIN {while ((getline l < own) > 0) me[l] = 1}
  {
    fam = $1; pr = $3; os = od = dp = rd = mk = ""; by = 0; k = 0
    for (i = 4; i <= NF; i++) {
      split($i, a, "=")
      if (a[1] == "src") { k++; if (k == 1) os = a[2] }
      else if (a[1] == "dst") { if (k == 1) od = a[2]; else rd = a[2] }
      else if (a[1] == "dport" && k == 1) dp = a[2]
      else if (a[1] == "bytes") by += a[2]
      else if (a[1] == "mark") mk = a[2]
    }
    if (dp != "443" && dp != "853") next
    if (fam == "ipv4") { if (os !~ /^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.)/) next; path = (rd == t4 ? "TUN" : rd == w4 ? "ISP" : "other") }
    else { if (os ~ /^fe80/ || (os in me)) next; path = "IPv6" }
    key = fam " " pr " " os " " od " " dp
    if (!(key in seen)) { seen[key] = 1; n++ }
    if (by > b[key]) b[key] = by
    p[key] = path; m[key] = mk
  }
  END { for (x in seen) print x, p[x], m[x], b[x] + 0 }' > "$W/conns"
echo "       connections: $(wc -l < "$W/conns")"
awk '{c[$3 " " $1 " " $2 " " $6]++; s[$3 " " $1 " " $2 " " $6] += $8} END {for (x in c) printf "       %-40s %4d conn %9.1f KB\n", x, c[x], s[x] / 1024}' "$W/conns" | sort
echo "[ $( [ "$(awk '$5 == 853' "$W/conns" | wc -l)" -gt 0 ] && echo WARNING || echo OK ) ] private DNS (DoT, port 853) connections: $(awk '$5 == 853' "$W/conns" | wc -l)"
echo "       DoH to public resolvers: $(awk '$4 ~ /^(8\.8\.8\.8|8\.8\.4\.4|1\.1\.1\.1|1\.0\.0\.1|9\.9\.9\.9|149\.112\.112\.112|94\.140\.14\.14|2001:4860:4860::8888|2001:4860:4860::8844|2606:4700:4700::1111|2606:4700:4700::1001)$/' "$W/conns" | wc -l)"
echo "       largest 25 (family proto client destination port path mark bytes, in which VPN list set):"
sort -k8,8nr "$W/conns" | head -n 25 > "$W/top"
while read -r F PR S D PT PA MK BY; do
  IN=
  if command -v ipset >/dev/null 2>&1; then
    case "$F" in ipv4) PF=_NDM_OGDN_4_@ ;; *) PF=_NDM_OGDN_6_@ ;; esac
    for G in $(awk -v t="$TIF" '$2 == t {print $1}' "$W/routes"); do
      ipset test "$PF$G" "$D" >/dev/null 2>&1 && IN="$IN $G"
    done
  fi
  [ "$F" = ipv4 ] && [ "$PA" != TUN ] && [ -z "$IN" ] && RT=$(ip route get "$D" 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "dev") {print " route=" $(i + 1); exit}}') || RT=
  echo "       $F $PR $S $D $PT $PA mark=$MK $((BY / 1024))KB${IN:+ list:$IN}$RT"
done < "$W/top" | mask6

echo "--- 7. journals around the failure"
echo "       Keenetic: rogue DNS answers today: $(ndmc -c 'show log' 2>/dev/null | grep -c 'rogue answer')"
ndmc -c 'show log' 2>/dev/null | grep -iE 'rogue answer|opkgtun|OpkgTun' | tail -n 6 | cut -c1-150 | sed 's/^/       /'
for L in /opt/var/log/vward-tunnel-health.log /opt/var/log/vward-tunnel-guard.log /opt/var/log/vward-vless-engine.log; do
  [ -s "$L" ] && { echo "       ${L##*/}:"; tail -n 6 "$L" | cut -c1-150 | sed 's/^/         /'; }
done
ER=/opt/var/run/vward/vless-engine
for E in "$ER"/v*.err; do
  [ -s "$E" ] || continue
  echo "       Xray errors ${E##*/}: $(wc -l < "$E") lines; the last 8:"
  tail -n 8 "$E" | cut -c1-160 | sed 's/^/         /'
done
for E in "$ER"/v*.started "$ER"/v*.fails "$ER"/v*.miss "$ER"/v*.down; do
  [ -e "$E" ] && echo "       ${E##*/}: $(cat "$E" 2>/dev/null) $(date -r "$E" '+%H:%M:%S' 2>/dev/null)"
done
for E in /tmp/vward-engine-starts/v*; do
  [ -f "$E" ] && echo "       starts ${E##*/} today: $(awk -v d="$(date -d "$(date +%Y-%m-%d) 00:00" +%s 2>/dev/null || echo 0)" '$1 >= d' "$E" | wc -l), last at $(tail -n 1 "$E" | awk '{print strftime("%H:%M:%S", $1)}' 2>/dev/null)"
done
HL=/opt/var/log/vward-tunnel-health.log
[ ! -s "$HL" ] || echo "       tunnel probe journal: $(grep -c "^$(date +%Y-%m-%d)" "$HL") lines today, with fail/down/timeout: $(grep "^$(date +%Y-%m-%d)" "$HL" | grep -ciE 'fail|down|timeout|no answer')"
X=$(pidof xray 2>/dev/null | awk '{print $1}')
if [ -n "$X" ]; then
  echo "[ OK ] xray pid $X running for $(awk -v u="$(cut -d' ' -f1 /proc/uptime)" -v h="$(getconf CLK_TCK 2>/dev/null || echo 100)" '{printf "%d min", (u - $22 / h) / 60}' /proc/$X/stat 2>/dev/null), cpu now: $(top -bn1 2>/dev/null | awk -v p="$X" '$1 == p {print $8 "%"}')"
else
  echo "[ FAIL ] xray is not running"
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
