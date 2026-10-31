# Supercell / Brawl Stars и AdaptiveAuto — разбор диагностики 31.10.2026

Данные: сообщение владельца о диагностике 22:55–22:58 МСК (Keenetic Viva KN-1913, KeeneticOS
5.01.C.8.0-2) и self-test того же дня 19:44 (только чтение). Роутер, VPN, AGH, DNS не менялись.
**Проблема Brawl Stars не объявляется решённой:** реальное подключение игры не проверено.

## 1. Почему `ip route get <IP игры>` на роутере показывает `eth3` — это не доказательство обхода VPN

FQDN-маршруты Keenetic (`dns-proxy route object-group …`) работают **политикой по меткам**, а не
основной таблицей (self-test, 19:44):

1. dns-proxy Keenetic видит DNS-ответы для доменов группы и заносит адреса в ipset
   `_NDM_OGDN_4_@domain-list11` (IPv4) и `_NDM_OGDN_6_@domain-list11` (IPv6).
2. Цепочка mangle `_NDM_DNSRT_PREROUTING_MANGLE` для пакетов **клиентов** с адресом назначения из
   ipset ставит метку (`MARK 0xffffaad…`) и `CONNMARK`, первая совпавшая группа выигрывает (`RETURN`).
3. `ip rule`: `fwmark 0xffff…/0xffffffff lookup 4096…4123` — таблицы с маршрутом в туннель.

`ip route get IP` без метки и без входного интерфейса клиента смотрит таблицу `main` — там маршрут по
умолчанию через провайдера (`eth3`). Поэтому три адреса `game.brawlstarsgame.com` (44.241.61.155,
52.33.95.61, 44.227.138.182) с `eth3` — **ожидаемый вывод** для такой проверки, а не признак ошибки.
Обход VPN он не доказывает и не исключает.

## 2. Что известно о группе Supercell (`domain-list11`)

| Факт (self-test 19:44) | Значение |
|---|---|
| 7 доменов (brawlstarsgame.com, clashroyaleapp.com, haydaygame.com, seeurlpcl.com, supercell.net, supercellgames.com, supercellid.com); `route object-group domain-list11 OpkgTun4 auto` | маршрут настроен |
| ipset IPv4: 76 адресов (в основном AWS 16.182.x / 52.216.x / 52.217.x) | dns-proxy видел DNS-ответы по этим доменам (включая поддомены — иначе S3-адресов CDN не было бы; какой поддомен дал какой адрес, не видно) |
| Три адреса игры из диагностики 22:55 **отсутствуют** в ipset на 19:44 | ожидаемо: адреса разрешены позже и могут меняться (round-robin AWS). Были ли они в ipset в 22:55 — **не проверено** |
| Пересечений ipset `domain-list11` с другими группами нет; группы ISP (`domain-list23`, `domain-list2`, `domain-list3`) стоят в цепочке раньше | затенения ISP-группой на 19:44 нет; при пересечении в будущем выиграет более ранняя группа (ISP) |
| ipset IPv6 `domain-list11`: 3 адреса, **ссылок 0** (из 29 IPv6-наборов используются только AdaptiveAuto и domain-list25) | IPv6-трафик этой группы не маршрутизируется политикой. На 19:44 глобального IPv6 нет (только link-local в conntrack, нет IPv6-маршрутов), поэтому сейчас это не путь обхода; при включении IPv6 у провайдера (`ipv6 address auto`, `ipv6 prefix auto` на ISP) станет риском |

**Не доказано и требует проверки на устройстве:**
1. Попадают ли реальные адреса игры в ipset, когда **клиент** (телефон) запускает игру.
2. Использует ли клиент DNS роутера: Android «Частный DNS» (DoT), DoH в приложении или жёстко
   заданный резолвер обходят dns-proxy — тогда адреса не попадают в ipset и трафик идёт через ISP.
3. Метка на реальных соединениях игры (conntrack `mark=`) и фактический выход через OpkgTun4.
4. Полный список доменов и портов игры. Новые домены и широкие CIDR **не добавляются** по
   предположению; общий захват трафика принадлежность пакетов игре не доказал.

## 3. AdaptiveAuto на установленной версии

Сигнатура 22:55–22:58 (`START_FAILED wait=12s`, `STOP reason=TERM rc=143 ran=13–14s`,
`last_stop=none`, процесса нет между попытками) совпадает с P0 из `DIAGNOSTICS_2026-10-31.md`.
Исправление (`124f10b`, PR #24, CI #769 success) **на роутере не установлено**, поэтому цикл
продолжается. Отдельной новой причины в данных нет; повторно P0 не исправлялся.

Связь с Supercell: `domain-list11` маршрутизирует сам Keenetic (ipset + метки), route-engine для этой
группы не нужен — для движка её домены «manual-known» (пропуск). Остановленный движок влияет только на
**AdaptiveAuto**: домены вне существующих групп не изучаются, пока цикл не устранён.

## 4. Прочие данные владельца (только для сведения)

Ozon (оба IPv4 отвечают через ISP, через VPN один — таймаут), Lampa (`lampa.mx` — ошибка TLS,
`cf.lampa.mx` — HTTP 200 через VPN, `yumata.github.io/lampa/` — через оба), `supercell.com` — HTTP 200
через оба. **Не основание** для смены маршрутов; доступность веб-сайта не равна доступности игровых
серверов.

## 5. Проверка на роутере (только чтение, по `docs/termius-standard.md`)

Команда только диагностическая, ничего не изменяет. Запускать **после** того, как на телефоне открыта игра
(1–2 минуты игры). Результат — в `/tmp/last_router.txt`.

```sh
clear
(
OUT="/tmp/router-sc-$(date +%Y%m%d-%H%M%S).txt"
S=_NDM_OGDN_4_@domain-list11
{
echo "== rules"; ip rule | grep -i 0xffffaad
echo "== set v4"; ipset list "$S" | head -8
for I in 44.241.61.155 52.33.95.61 44.227.138.182
do
echo "== $I"
ipset test "$S" "$I" 2>&1 | tail -1
grep -F "dst=$I " /proc/net/nf_conntrack |
 head -3
done
echo "== set v6"
ipset list _NDM_OGDN_6_@domain-list11 |
 grep -i references
echo "== engine"
tail -n 6 \
 /opt/var/log/vward-route-engine-events.log
} > "$OUT" 2>&1
ln -sfn "$OUT" /tmp/last_result.txt
ln -sfn "$OUT" /tmp/last_router.txt
ls -1t /tmp/router-sc-*.txt | tail -n +6 |
 while read -r F; do rm -f "$F"; done
cat "$OUT"
)
```

Как читать: `is in set` + строки conntrack с `mark=` ≠ 0 — трафик игры помечен для туннеля;
`is NOT in set` при идущей игре — клиент разрешил адрес мимо DNS роутера, либо игра использует
другой домен. Строк conntrack нет — игра не ходила на эти адреса.
