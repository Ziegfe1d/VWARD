# VWARD 0.2 → Final: единый план

## Статус на 20.09.2026

- исходники: `0.2.0-dev.9`;
- активная линия разработки: `dev`;
- роутер, package и update feed не являются средой для незавершённого Dev-кода;
- Wi-Fi Client Guard имеет scheduler, Console API/UI и guarded manual control, но
  локально выключен: `ENABLED=0`, `CONTROL_ENABLED=0`, `AUTO_APPLY=0`;
- текущий dev feed содержит исторический manifest `0.1.7-beta` и не соответствует
  исходникам `0.2.0-dev.9`.

Последний пункт — **P0 release blocker**. До выпуска нового настоящего signed package
нельзя устанавливать Dev на роутер и нельзя считать feed готовым.

## Правила

1. Сначала доказательство по коду, тестам, журналам или live acceptance; затем вывод.
2. Любая правка начинается с отдельного regression-test или с доказательства, что
   дефект воспроизводим.
3. Нельзя отключать Ed25519, SHA-256, ownership checks, downgrade protection,
   backup, rollback или runtime barrier.
4. Рабочий роутер изменяется только отдельным acceptance-пакетом с backup,
   проверкой и rollback.
5. `main`, production feed и VERSION не меняются до отдельного release gate.
6. После каждого этапа фиксируются: commit, CI, тесты, открытые риски и gate.

## Этап 0 — доводка Dev до pre-RC

### P0: выпускной контур

- привести `VERSION`, package, manifest, compatibility, sequence, SHA256SUMS и feed
  к одному кандидату;
- собрать package только из package map и подписать штатным Ed25519-ключом;
- отдельно проверить подпись, package SHA, ownership и clean staging install;
- не публиковать package/feed до успешного локального и CI acceptance.

### P1: реальное устройство

- read-only acceptance Wi-Fi: `show associations`, реальные AP names, RSSI и parser;
- collector без control, сверка samples/analysis с Keenetic;
- отдельный manual control acceptance с backup, save, read-back и rollback;
- data-plane матрица DNS → AGH → upstream → WAN/WireGuard;
- reboot/recovery, locks, storage и cron на целевом роутере;
- проверка автоматического Device Profile: несколько WireGuard, гостевой сегмент,
  фактические ответы RCI `show interface` и `show interface system-name`.

### P1: исходники и Console

- BusyBox/Entware syntax и package validation в совместимой среде;
- полная цепочка Console action → API → backend → real state → UI;
- аудит lock, PID, temporary files, atomic replace и interrupted state;
- source-of-truth для update, WAN, VPN, DNS, routing, Ads и Wi-Fi;
- актуализация README, install/recovery runbooks и UI labels.

### Gate pre-RC

- Critical: 0;
- P0 feed mismatch: закрыт;
- repository/security/updater/package tests: PASS;
- BusyBox/Entware validation: PASS;
- live acceptance: PASS для затронутых компонентов;
- решение владельца: GO на RC1.

## RC1 — feature complete

Новых функций после RC1 не добавлять. Обязательны: signed candidate, clean install,
upgrade, rollback, reboot recovery, Console critical actions, data-plane probes и
24–48 часов наблюдения.

## RC2 — reliability

Только исправления дефектов RC1 с regression-тестами. Обязательны: RC1→RC2 update,
rollback, interrupted update, WAN/DNS/GitHub recovery, storage/CPU/RAM контроль и
3–7 суток soak.

## RC3 — final rehearsal

Code freeze. Обязательны: fresh-clone reproducible build, независимая verify подписи,
clean install, update/rollback chain, power-loss rehearsal, UI matrix, runbook и
7 суток unattended soak. Critical/High: 0.

## Final 0.2.0

Только после явного GO владельца: approved RC commit, VERSION/metadata, signed
release package, отдельная verify подписи, release notes, staged router rollout и
post-install проверка DNS, WAN, VPN, routes, Console, cron, logs и recovery.

## Доказательства для каждого gate

- commit SHA и CI URLs;
- VERSION, package SHA-256, manifest SHA-256, sequence и результат verify подписи;
- install, upgrade, rollback и reboot-recovery logs;
- full health, DNS/WAN/VPN/route probes;
- Console/API acceptance;
- CPU/RAM/storage baseline и soak interval;
- список известных рисков и итоговое PASS/FAIL.
