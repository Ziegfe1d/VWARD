# VWARD 0.2: единый план от RC1 до RETAIL

## Статус на 23.09.2026

- исходники: `0.2.0-rc.1` (этап RC1, feature complete);
- активная линия разработки: `dev`; рабочий роутер остаётся на `0.1.9-beta` (ветка `beta`);
- signed feed ветки `dev` ещё содержит исторический manifest `0.1.7-beta`: подписанный
  RC1 публикуется только после GO владельца (см. [`RELEASE_0.2.0.md`](RELEASE_0.2.0.md));
- Wi-Fi Client Guard по умолчанию выключен: `ENABLED=0`, `CONTROL_ENABLED=0`, `AUTO_APPLY=0`.

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

## Этапы выпуска

`RC1 → RC2 → RP1 → RP2 → RETAIL`. Версии: `0.2.0-rc.1`, `0.2.0-rc.2`, `0.2.0-rp.1`,
`0.2.0-rp.2`, `0.2.0`. Updater упорядочивает их именно так (`vu_version_cmp`);
каждый этап публикуется новым signed manifest с большим `sequence`.

### RC1 — feature complete (`0.2.0-rc.1`)

Новых функций после RC1 не добавлять. Сделано в коде: Console с записью настроек,
выбор туннеля, защита интернета, компоненты с проверкой зависимостей, Ads, cron,
вход по учётной записи Keenetic; release rehearsal
(`tests/updater/run-release-rehearsal.sh`): настоящий candidate подписывается штатным
`prepare-dev-release.sh` одноразовым ключом, ставится поверх файлов настоящих beta-пакетов,
проходит full health и полностью откатывается.

Gate RC1:

- repository/security/updater/package tests и rehearsal: PASS в CI;
- clean install, upgrade, rollback, reboot recovery, Console critical actions,
  data-plane probes и 24–48 часов наблюдения на целевом роутере;
- решение владельца: GO на подпись и публикацию RC1.

### RC2 — reliability (`0.2.0-rc.2`)

Только исправления дефектов RC1 с regression-тестами. Обязательны: RC1→RC2 update,
rollback, interrupted update, WAN/DNS/GitHub recovery, storage/CPU/RAM контроль и
3–7 суток soak.

### RP1 — release preview (`0.2.0-rp.1`)

Code freeze. Обязательны: fresh-clone reproducible build, независимая verify подписи,
clean install, update/rollback chain, power-loss rehearsal, UI matrix (320/390/1366 px),
runbook и 7 суток unattended soak. Critical/High: 0.

### RP2 — последний preview (`0.2.0-rp.2`)

Только исправления, найденные на RP1, и документация. Обязательны: RP1→RP2 update,
повтор power-loss и rollback, staged rollout на второй роутер (если есть), чек-лист
[`PUBLISHING_CHECKLIST.md`](PUBLISHING_CHECKLIST.md) без открытых пунктов.

### RETAIL — 0.2.0

Только после явного GO владельца: тот же код, что RP2, кроме VERSION/metadata;
signed release package, отдельная verify подписи, release notes, staged router rollout
и post-install проверка DNS, WAN, VPN, routes, Console, cron, logs и recovery.

## Доказательства для каждого gate

- commit SHA и CI URLs;
- VERSION, package SHA-256, manifest SHA-256, sequence и результат verify подписи;
- install, upgrade, rollback и reboot-recovery logs;
- full health, DNS/WAN/VPN/route probes;
- Console/API acceptance;
- CPU/RAM/storage baseline и soak interval;
- список известных рисков и итоговое PASS/FAIL.
