# Интеграция Ads & Privacy Guard в VWARD dev

Этот документ описывает будущий merge. В текущем архиве ничего не применено.

## 1. Новый component ID

Предлагается:

```text
id: ads-privacy-guard
name: VWARD Ads & Privacy Guard
name_ru: Анализ рекламы и трекинга VWARD
```

Component registry fragment находится в:

```text
config/components/component-registry.fragment.json
```

## 2. Source/runtime mapping

См. `INSTALLATION_MAP.fragment.md`.

Код устанавливается в `/opt/bin` и `/opt/share/vward/ads-privacy-guard`.
Local config создаётся только при первом install и затем не является update payload.

## 3. Scheduler / cron

Предложение v2: один cron owner:

```text
* * * * * /opt/bin/vward-ads-privacy-scheduler.sh ...
```

Это lightweight tick. Он не запускает classifier каждую минуту. Он учитывает ENABLED,
PAUSED, RUN_MODE, query-log change, elapsed interval, load average per CPU, MemAvailable,
свободное место `/opt` и scan lock. Source update также принадлежит scheduler.

Режимы: `manual`, `scheduled`, `dynamic`. Подробный контракт:
`docs/ADS_PRIVACY_GUARD_SETTINGS_AND_RUNTIME.md`.

## 4. Console API

Добавить GET `ads-data`: health/status, counts, last run/source update, review queue,
runtime current domain/progress, scheduler phase/reason/next due, manual override counts.

Добавить GET/POST `ads-settings`: только whitelist параметров через
`vward-ads-privacy-settings.sh`, с backup, validation, atomic replace и audit. Нельзя принимать
произвольный shell config. Включение `AUTO_PUBLISH=1` требует confirm token.

Добавить POST `ads-control` через существующий `X-VWARD-Request: console` guard:

- `scan`;
- `sources-update`;
- `pause` / `resume`;
- `allow` / `block` / `remove-override` с `exact|suffix`;
- `publish` только с отдельным confirm token.

Никаких arbitrary command/domain shell interpolation. Domain и scope валидируются.

API fragment: `web/fragments/api-ads-privacy-guard.fragment.cgi`.

## 5. Console UI

Не создавать новый верхнеуровневый раздел. Карточка «Реклама и трекинг» остаётся в
едином центре управления, detail показывает состояние/очередь/быстрые действия.

В существующий раздел **«Настройки»** добавить три панели:

1. Основные настройки: enable, pause/resume, manual/scheduled/dynamic, intervals,
   resource gates, source refresh, publish policy.
2. Текущая проверка: phase, current domain, progress, next due, scheduler reason,
   ручной scan/source update/publish.
3. Свои правила: domain, exact/suffix, always allow, always block, remove override.

Fragments:

- `web/fragments/ads-privacy-guard-ui.fragment.html`;
- `web/fragments/ads-privacy-guard-settings.fragment.html`.

## 6. Diagnostics

`vward-ads-privacy-health.sh` должен быть добавлен в diagnostics profile `ads-privacy-guard`.
Проверять:

- config/registry/trust files;
- jq/curl;
- AdGuard query log;
- source index health;
- last source update;
- last scan;
- verdict counts.

## 7. Housekeeping

Добавить policy для:

- work directories;
- old backups;
- component log rotation;
- source cache replacement only atomic;
- НЕ удалять active verdict state.

## 8. Update Engine

При merge необходимо:

1. добавить runtime targets в authoritative component registry;
2. обновить installation mapping;
3. package ownership tests;
4. affected component set;
5. SHA256SUMS;
6. signed dev package/feed только после acceptance.

Local files `/opt/etc/vward/ads-privacy-guard/*` и persistent state
`/opt/var/lib/vward/ads-privacy-guard/*` не должны быть replace targets обычного
update package.

## 9. Acceptance перед публикацией

Минимум:

- BusyBox syntax;
- offline simulations;
- source URL smoke tests;
- source min-count validation;
- malformed feed tests;
- querylog schema tests;
- false-positive gates;
- Trust/allow/deny precedence;
- lost-source degraded mode;
- no-silent-unblock test;
- publisher dry-run;
- publisher backup/rollback simulation;
- repository consistency;
- updater simulations;
- console security checks;
- router staging acceptance без рабочего Beta.


## 10. HTTPS Content Guard (candidate v6)

Keep HTTPS filtering under the existing `ads-privacy-guard` component id. Install the
HTTPS control script and provider libraries as package-owned files, but seed local HTTPS
config/TSV files only on first install. Never overwrite CA/private keys during update.

Console fragment adds read-only status plus guarded `validate`, `ca-init`, `start`, `stop`
actions. CA creation/start require explicit confirmation. A future editor for intercept,
bypass and request-path rules must use validated transactions; raw proxy config must never
be accepted from the browser.

Initial integration must not add transparent NAT/iptables interception. Use explicit proxy
and generated PAC only until a separate firewall-ownership contract exists.
