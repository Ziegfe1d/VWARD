# CI #726: хаос-тест, сценарий kill, блокировка tunnel-health (2026-10-25)

Сохранено для разбора в fix.34 (третий пункт). Логи GitHub Actions хранятся ограниченное время.

- Прогон: VWARD CI #726, попытка 2, задание `resource-audit`, шаг «Chaos run on the router emulator (faults minute by minute)», 04:28:51-04:40:40 UTC.
- Код: `1822102` (fix.33.2). На `8c013ad` (тот же код, отличия только в документах) CI #728 зелёный, в нём Chaos пройден; в PR #5 (#724, #725) тоже.
- Находка теста: `FINDING ('kill', 77, '-', 'stale lock', 'tmp/vward-tunnel-health-watch.lock pid 73671')`.
- Сид: случайности в `tests/perf/check-chaos-emulated.py` нет. Сценарий `kill` (4 минуты сбоя, 4 после) убивает группу процессов задания через `0.05 + (minute % 4) * 0.07` с после запуска (`os.killpg(SIGKILL)`); задания: tunnel guard, WAN guard, ads scheduler, tunnel health, S91. Минута 77 - сквозной счётчик минут, `77 % 4 = 1`, пауза 0,12 с. Воспроизведение: `sudo python3 tests/perf/check-chaos-emulated.py` на `1822102`; точная гонка зависит от скорости раннера.
- Итог по сценариям (минуты, секунды): healthy 4/2,1; wan 12/68,6; tunnel 16/27,3; wan-flap 14/44,9; dns 8/41,6; ndmc-refuse 12/5,9; ndmc-slow 7/58,6; kill 8/65,5; twice 6/11,2; agh-silent 10/54,2; agh-blip 6/22,3; agh-loop 14/6,2; agh-down 10/54,1; curl-https-crash 7/15,7 (curl 2); jq-crash 8/18,7 (jq 20); wget-crash 6/27,4; rci-slow 6/97,7; agh-broken 7/63,8; opkg-missing 4/15,0. Шаги до хаоса (route-engine, reconciler, stabilization, cutover, install) - PASS.
- Предварительная гипотеза (не проверена): `kill -9` в момент между `mkdir` блокировки и записью `pid` оставляет блокировку; stale-проверка в `tunnel-health` смотрит живость pid, и тест считает её «осталась» на следующей минуте, пока её не подобрали. Нужно: определить, пропускает ли код блокировку без pid (старше 1 мин) и сколько минут тест ждёт после сценария.
