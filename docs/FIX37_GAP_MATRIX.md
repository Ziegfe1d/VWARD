# fix.37: незакрытое после fix.36 — матрица, разбор диагностики 02.11, первые исправления

Рабочий документ ветки `claude/new-session-kl9ijw` (draft PR в `dev`). Это **не** выпуск и не разрешение
выпуска: `VERSION`, лента, подпись и роутер не менялись. Личные данные самотеста (адреса провайдера,
MAC, URL Smart DNS, имена устройств) сюда не переносятся — только обезличенные счётчики и метки времени.

## 0. Контрольный снимок (перепроверен 02.11.2026)

| Объект | Состояние |
|---|---|
| `dev` | `dd4fb94e21adced28b6424eaccbbeecafe9a4b8d` — подписанный кандидат fix.35.1 (2026110102) |
| PR #32 `fix/fix36-20261102` | draft, HEAD `c0cc511e430bca665c81484ffd26b6199e26cf64`, 4 коммита, база `dd4fb94` |
| CI PR #32 на `c0cc511` | `updater-tests` success; `repository-consistency` **failure**: «Terminating signal trap safety», `components/route-engine/scripts/vward-route-engine.sh:1948` (`trap - EXIT HUP INT TERM`, новый код fix.36); `resource-audit` — в работе на момент снимка. В PR #32 не вмешивались |
| Эта ветка | от `dd4fb94`; пробное слияние с `c0cc511` (`git merge-tree`): код сливается автоматически, конфликт только в `SHA256SUMS` (пересчёт при интеграции) |
| Установленная версия на Keenetic | самотест 02.11 12:48 доказывает только KeeneticOS 5.1.8; версия VWARD им **не доказана**. fix.36 на момент самотеста не установлен — события 02.11 ему не приписываются |

Статусы: **подтверждено / вероятно / не проверено / опровергнуто**. «Есть код» ≠ «принято на Keenetic».

## 1. Полный цикл (ROADMAP §7, 31.10/01.11) против фактического PR #32

ROADMAP назначил fix.36 **весь** общий цикл (прежние fix.34.2, 34.2b, 34.3, журналы, dnsmasq, sing-box, Панель).
Уточнение fix.36 от 02.11 в самом PR #32 (`docs/ROADMAP.md`, «Уточнение состава fix.36») сужает выпуск до текущих
проблем. Это расхождение — **решение владельца**, здесь оно не переносится самовольно в fix.37.

| Требование (источник) | dev `dd4fb94` | PR #32 `c0cc511` | CI | Keenetic | Осталось | Статус |
|---|---|---|---|---|---|---|
| Orphan DNS-работы движка, второй корень (fix.35.1 открытое) | — | дети Live, ожидание при выходе (`vward-route-engine.sh`) | **красный** (trap safety) | нет | зелёный CI, приёмка START_PHASE | код есть, не подтверждено |
| Lease общей копии конфигурации, ABA | — | `vward-device-profile.sh` `vward_keenetic_config` | красный (общий прогон) | нет | приёмка времени старта | код есть |
| Независимый владелец запуска движка (cron-watchdog / supervisor / S91) | два вызывающих `S91 start` | описан, сериализация CONTROL_LOCK сохранена; один владелец **не введён** | — | нет | решение: оставить сериализацию или один владелец | не сделано (сознательно) |
| Режим «DNS» списка, лимит 8, ownership, откат | сегмент скрыт | `vward-console-config.sh` транзакция + Панель | красный | нет | приёмка | код есть |
| Установка dnsmasq/sing-box/Xray из Панели без включения | нет | есть | красный | нет | приёмка; удаление/сброс не делались | код есть |
| **Три взаимоисключающих DNS-режима AGH / dnsmasq / native, переключение и recovery** (§2 полного цикла) | только чтение/рендер/план (`vward-dns-mode.sh`: «no DNS writer is connected») | не добавлено | — | нет | весь writer, селектор в Панели, эмулятор `agh→dnsmasq→native→agh` | **не сделано** |
| sing-box как выключенный альтернативный движок с подтверждением протоколов | установка пакета | установка без запуска | — | нет | движок, протоколы, Панель | не сделано |
| fix.34.2: YouTube/подсети Google с владением, сверка без процесса на маршрут, «Всё в Smart DNS» пакетно | частично (см. PACKAGE_F) | нет | — | нет | всё | не сделано |
| fix.34.2 `a2` — только WOULD_ADD | наблюдение есть (`WOULD_ADD` в коде) | нет | — | нет | 24–48 ч данных + согласие | наблюдение есть, запись запрещена |
| fix.34.2b: резерв/возврат туннеля, третий независимый контроль, защита VLESS, ИИ при потере туннелей | частично | нет | — | нет | третий контроль (сейчас обе пробы — Cloudflare 1.1.1.1/1.0.0.1, отчёт fix.36 §WAIT_DEGRADED) | не сделано |
| fix.34.3: дубли FQDN-групп, повторное использование номера, независимые пути DNS/ISP/VPN для «Проверить сайт»/ИИ, DNS через VPN без петли | дубли — показ; `svc_open` есть | нет | — | нет | независимые резолверы, петля DNS (см. §2) | частично |
| Журналы «полного раздела» (события решений, RCI/ndmc-время, источники) | «Важное/Все», TXT/копировать/поделиться (fix.35.1) | START_PHASE | — | нет | статистика RCI/ndmc, единые причины | частично |
| Доменные списки: 0/1/N, массовые операции, **отмена удаления**, импорт/создание | список, режимы, удаление с копией | DNS-режим | — | нет | «Отменить» удаление (в коде нет) | частично |
| «Реклама и трекеры»: порядок, честные статусы, малый процент | `blockedShare` (191/38 232 ≠ 0 %), порядок блоков | — | зелёный в fix.35.1 | нет | приёмка 320/390 px | код есть |
| RS-6/RS-7 | audit/dry-run | без writer | — | нет | writer только по решению | заблокировано (верно) |
| TTL `smartdns.resolved` (Н) | 16 адресов без срока | — | — | нет | после подтверждения поведения | не сделано (низкий приоритет) |

**Что законно остаётся в fix.36 по договорённости** (если владелец не сузит состав явно): DNS-режимы с writer и
recovery, fix.34.2/34.2b/34.3, журналы полного раздела. **Что может уйти в fix.37 только решением владельца**:
то же самое. До решения эта ветка берёт лишь независимые доказанные дефекты (§3).

## 2. Диагностика Keenetic 02.11 12:48 (окно ndm-журнала ≈ 01.11 23:51 – 02.11 12:48)

### 2.1 P0 DNS-петля, 10:51:03–10:51:05

Факт: три `ndnproxy: proxy loop detected: 192.168.1.1 <-> 192.168.1.1, request dropped` и три
`DNS server 192.168.1.1 inactivated` за 2 с. Keenetic временно отключил свой upstream (AdGuard Home на адресе
роутера) — на это время клиенты без фильтрации и без Smart DNS через AGH.

Механизм (статически, **вероятно**): петлю даёт только запрос, который AGH сам отправил на :53 роутера.
Запросы самих скриптов VWARD к `192.168.1.1:53` (route-engine, reconcile, Панель) идут постоянно, а событий
только три — значит это не «любой запрос с адреса роутера», а возврат запроса из AGH. Возможные пути AGH →
роутер:

| Путь в `AdGuardHome.yaml` | Что зацикливается | Кто видел до fix.37 |
|---|---|---|
| `upstream_dns` (строка без домена) | каждый запрос | страж DNS и Панель |
| `fallback_dns` | при отказе основных | **только страж**; Панель — «Норма» |
| `bootstrap_dns` | разрешение имён собственных upstream (после перезапуска AGH / истечения кэша) — кратко | никто |
| `local_ptr_upstreams` | обратные запросы домашней сети | никто |
| `[/домен/]роутер` (функция `route-dns`, по умолчанию выключена) | эти домены; защищено клиентом «Keenetic DNS (VWARD)» | никто в Панели |

Краткость (3 события за 2 с) лучше согласуется с `bootstrap`/PTR/доменной строкой или с моментом перезапуска
AGH, чем с постоянной петлёй основного upstream; `upstream_dns` → роутер на снимке исключается тем, что петля
была бы непрерывной. Точный путь **не проверен**: нужны ключи AGH и события VWARD 10:45–10:55 (§5).
Владелец снимал read-only вывод около 10:50 (FIX36_REPORT) — совпадение по времени отмечено, причинность
не доказана. DNS не переключался, конфигурация не переписывалась.

### 2.2 P0 блокировки ndm `Dns::Route::ResolveQueue` (00:39:21, 00:39:51, 08:25:57; `UpdateSet6_ / OnCacheSync_`)

Факт: обработка `Resolved` задерживалась 30/60 с; `Cleanup` не стартовал 30 с; стек — обновление IPv6-набора
при синхронизации DNS-кэша. Связь с VWARD: **не проверено**. Временная корреляция: ночное задание
`10 0 * * *` (`vward-policy-chain.sh && vward-policy-reconcile.sh`, `config/cron/root.crontab`) разрешает домены
групп через DNS роутера (`vward-policy-reconcile.sh:529`, `nslookup … $VWARD_DNS_SERVER`), каждый ответ
пополняет FQDN-наборы Keenetic. Если 00:39 приходится на его выполнение — это кандидат нагрузки на
ResolveQueue; на 08:25 у VWARD нет задания по расписанию. Нужен момент окончания ночного задания
(`/tmp/vward-policy-chain.cron.last`) и число IPv6-наборов (§5). IPv6 не отключается; частота/пакетирование
не меняются до воспроизведения.

### 2.3 P0/P1 объём маршрутов

1 330 строк `ip route` в startup-config против 34 356 записей `show ip route` при ≈2 727 уникальных
`destination+interface+proto`: ≈12,6 повторения на запись — это тиражирование статических маршрутов Keenetic в
таблицы политик доступа, а не 34 тыс. независимых сетей. Сокращение возможно только уменьшением числа
статических маршрутов или политик; массовая очистка запрещена, чужие/ручные (8 подсетей Google) не трогаются.
Разделение «свои VWARD (`owned.dynamic.routes`) / ручные / FQDN-derived / дубли внутри таблицы» — **не
проверено**, нужен отдельный read-only подсчёт после fix.36 (не входит в §5, чтобы не грузить ndm `show ip route`).

### 2.4 P1 ресурсы, ndnproxy, сессии

- CPU 42 % (avg 39, max 85 в окне cpustat), MemAvailable ≈85 МБ, zram ≈66 МБ, ndm 25 % / ~58 МБ, load 1,27 —
  точки измерения, причина **не установлена**. Бюджет: замеры «до/во время/после» только read-only, без тяжёлых запусков.
- ndnproxy для `192.168.1.1:65053`: `R.Sent=55, A.Rcvd=6, NX.Rcvd=21, Avg.Resp≈926 мс` — окно счётчиков
  неизвестно (вероятно, с последней активации сервера, т.е. после 10:51); число незавершённых из таблицы не
  выводится. Доля NX и таймауты — по журналу AGH, **не проверено**.
- 1 715 `Core::Server: started Session` за ≈13 ч ≈ 2,2/мин. VWARD вызывает ndmc из минутных заданий
  (wan-guard, tunnel-health/guard, supervisor, ads-scheduler) — **вероятно**, значимая доля; точная атрибуция и
  повторные чтения running-config — **не проверено**. Сокращать вызовы выдачей устаревшего состояния нельзя.

### 2.5 P1 конфликт описания и пути

Группы с описанием «… (ISP)» привязаны `dns-proxy route object-group … OpkgTun4` — описание не является маршрутом.
API `lists-data` уже отдаёт и `description`, и фактический `via`; предупреждение «описание говорит Провайдер, путь —
VPN» в Панели **не сделано**: PR #32 переписывает именно этот экран и jq `lists-data`, поэтому реализация —
после интеграции fix.36, без второй реализации. Никакой автоматической правки групп.

## 3. Сделано в этой ветке (RED → GREEN)

**Дефект (подтверждено):** два читателя одной петли расходились. Страж DNS
(`vward-ads-privacy-dns-guard.sh`, `agh_upstream_loops`) считает петлёй `upstream_dns` и `fallback_dns`,
диагностика Панели (`web/cgi-bin/api.cgi`, проверка «Цепочка DNS») — только `upstream_dns` и показывала «Норма»
при `fallback_dns` → роутер; `bootstrap_dns`, `local_ptr_upstreams` и доменные строки не видел никто.

**Исправление:** `vward_agh_dns_loops` в `components/runtime/lib/vward-device-profile.sh` — один read-only
разбор YAML (блочные и inline-списки, `udp://`/`tcp://`, порт 53 или без порта, LAN, 127/8, `::1`, localhost;
`:5353`, `192.168.1.10`, DoH-URL — не роутер); печатает только вид (`main/fallback/bootstrap/private/domain`),
без адресов. Панель: `main`/`fallback` — FAIL с причиной, кратковременные виды — WARN с объяснением про
«proxy loop detected» и временное отключение AGH. Без библиотеки — прежняя проверка. **Поведение стража
(когда он выводит AGH из цепочки) не изменено**, Keenetic и AGH не меняются.

| Тест | RED (до) | GREEN (после) |
|---|---|---|
| `tests/repository/check-console-diagnostics-dns.py` | `fallback_dns → 192.168.1.1:53`: `dns-chain = PASS` | FAIL «резервные…»; inline `[udp://127.0.0.1]` FAIL; bootstrap/PTR/домен — WARN; три не-петли — PASS; библиотека: ровно `bootstrap, domain, fallback` |

Проверено: тест на `sh` (dash) и BusyBox 1.36.1 (`sh`, `awk`, `sed`, `grep`, `tr`); `busybox sh -n` и
`shellcheck -S error` для изменённых файлов; `check-ads-dns-guard.py` PASS (страж не затронут);
`check-no-personal-data.py`, `check-version-synchronization.py` PASS; `SHA256SUMS` пересчитан
`scripts/refresh-sha256sums.sh`. Полный CI — один раз на конечном HEAD этого PR. BusyBox на Keenetic 5.1.8 —
**не проверен** на устройстве.

**Риски и откат.** Риск: ложное WARN, если в AGH намеренно указан роутер для локальной зоны (это и есть
возможная петля, поэтому WARN, не FAIL). Нагрузка: один `awk` по YAML на запрос диагностики, без опроса и
без вызовов Keenetic. Откат: штатный файловый rollback Update Engine к предыдущей версии (Ed25519/SHA-256 без
ослабления); пользовательских данных и конфигурации изменение не касается.

## 4. Что проверено статически / что принять на Keenetic / что заблокировано

- **Статически (эта ветка):** расхождение двух проверок петли и его закрытие; путь reconcile → DNS роутера;
  отсутствие DNS-writer режимов AGH/dnsmasq/native; отсутствие «Отменить» удаления списков.
- **На Keenetic после установки fix.36 (владелец):** START_PHASE и время старта; один корень движка;
  режим DNS списка и лимит 8; установка пакетов без запуска; Ozon/Wildberries, Lampa TV, Supercell, ИИ на
  клиентах; ночное задание 03.11 00:10 — совпадает ли с ResolveQueue; новые `proxy loop detected`.
- **Заблокировано без отдельного решения:** любые записи в Keenetic/AGH/DNS, writer RS-6/RS-7, переключение
  DNS-режимов, `a2` запись, 8 ручных подсетей Google, 16 DNS-правил, NextDNS, режимы агентов, слияние, подпись,
  выпуск, установка.

## 5. Одна read-only диагностика (termius-standard v2.3.3)

Команда только диагностическая, ничего не изменяет. Читает: ключи `dns:` AGH (печатает **счётчики** «роутер /
внешний», не URL), `/etc/resolv.conf`, число IPv6-наборов, последние 12 строк `show log` с
`loop detect|inactivat|ResolveQueue`, строки журналов VWARD 02.11 10:45–10:55, состояние `route-dns` и цепочки,
окончание ночного задания. Три вставки (716/851/912 байт, строки ≤ 55 символов, ASCII); запуск — в конце третьей.

Вставка 1:

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
Y=/opt/etc/AdGuardHome/AdGuardHome.yaml
L=$(sed -n 's/^VWARD_LAN_ADDRESS=//p' \
 /opt/etc/vward/device.conf 2>/dev/null | tr -d '"')
[ -n "$L" ] || L=192.168.1.1
G=/opt/var/log
EOF
```

Вставка 2:

```sh
cat >> /tmp/vward-f37.sh <<'EOF'
{
echo "== vward-f37 read-only $(date)"
ndmc -c "show version" | grep -E 'release|device'
echo "-- AGH keys -> router (counts, no URLs)"
awk -v l="$L" 'function r(k,v){gsub(/["\047]/,"",v)
 gsub(/[][]/," ",v);n=split(v,w,/[ ,]+/)
 for(i=1;i<=n;i++){a=w[i];if(a=="")continue
 t="ext";if(index(a,l)||index(a,"127.0.0.1")||
 index(a,"localhost"))t="ROUTER";c[k" "t]++}}
 /^[^ #]/{d=($1=="dns:");k="";next}
 d&&/^  [a-z_]+:/{k=$1;v=$0;sub(/^ *[a-z_]+: */,"",v)
 if(k~/ptr_res/)print k,v;else if(v!="")r(k,v)
 next}
 d&&$1=="-"&&k!=""{v=$0;sub(/^ *- */,"",v);r(k,v)}
 END{for(x in c)print (x~/ROUTER/?"[ WARNING ]":\
 "[ OK ]"),x,c[x]}' "$Y" |
 grep -E 'upstream|bootstrap|fallback|ptr'
echo "-- resolv.conf"; grep nameserver /etc/resolv.conf
echo "-- ipv6 sets: $(ipset -t list 2>/dev/null |
 grep -c 'family inet6')"
EOF
```

Вставка 3 (запускает):

```sh
cat >> /tmp/vward-f37.sh <<'EOF'
echo "-- ndm log (last 12)"
ndmc -c "show log" | grep -E \
 'loop detect|inactivat|ResolveQueue' | tail -n 12
echo "-- VWARD 02.11 10:45-10:55"
grep -hE '11-02.10:(4[5-9]|5[0-5])' $G/vward*.log |
 cut -c1-100 | tail -n 15
echo "-- route-dns / chain"
ls /opt/etc/vward/ads-privacy-guard/route-dns.* 2>&1
cat /tmp/vward-route-dns.status 2>/dev/null
cat /tmp/vward-dns-chain/state \
 /tmp/vward-dns-chain/reason 2>/dev/null
echo "-- night job 00:10 (end, rc)"
cat /tmp/vward-policy-chain.cron.last \
 /tmp/vward-policy-chain.cron.rc 2>/dev/null
} 2>&1 | tee "$OUT"
W=$(grep -c "^\[ WARNING" "$OUT")
K=$(grep -c "^\[ OK" "$OUT")
echo "SUMMARY: pass=0 ok=$K warn=$W fail=0" |
 tee -a "$OUT"
ln -sfn "$OUT" /tmp/last_result.txt
ln -sfn "$OUT" /tmp/last_vward.txt
send_out; echo "RESULT SENT (OSC52)"
echo "RAW: /tmp/last_result.txt"
EOF
sh -n /tmp/vward-f37.sh && sh /tmp/vward-f37.sh
```

Проверено на fixture под BusyBox 1.36 и dash (вывод `[ WARNING ] bootstrap_dns: ROUTER 1` и т.п.). `show log`
читается один раз (как в самотесте); `show ip route` намеренно не запускается.

## 6. Интеграция после fix.36

Слить конечный HEAD PR #32 в эту ветку слиянием (не переносом файлов), пересчитать `SHA256SUMS`, затем:
предупреждение «описание ≠ путь» в `lists-data`/экране списка поверх кода PR #32; запись в `docs/AGENT.md` и
`CHANGELOG.md` (сейчас не добавлены, чтобы не конфликтовать с хвостом PR #32); один полный CI.
