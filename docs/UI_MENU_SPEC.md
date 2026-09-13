# VWARD Console: меню VWARD Ads & Privacy Guard

Компонент встраивается в существующую Console. Отдельная админка не создаётся.

## Карточка компонента

Название: **VWARD Ads & Privacy Guard**
Подпись: «Реклама, трекинг, аналитика и нежелательные редиректы».

Карточка показывает: статус, режим, очередь, текущий домен, VWARD-managed rules,
последний scan и последний source refresh.

## Вкладки компонента

### 1. Обзор

- Master switch;
- Работает / Пауза / Выключен / Ошибка;
- Manual / Scheduled / Dynamic;
- Проверить сейчас, Пауза/Продолжить, Обновить базы;
- текущий домен + прогресс;
- counters: проверено, block, allow, suspect, очередь;
- CPU/RAM/disk gate state.

### 2. Проверить домен

Поле `example.org` -> «Проверить». Результат показывает trust/manual state, совпадения
источников, историю AGH, DNS resolution, heuristic signals и итоговый verdict.
Действия: Заблокировать, Разрешить, Доверять, Наблюдать, Удалить VWARD override.

### 3. Мои правила

Таблица: domain, scope exact/suffix, action, enabled, category, origin MANUAL/AUTO,
confidence, created/last checked, note. Только VWARD-owned rules.

### 4. Источники

Для каждого источника: OFF / CHECK / ACTIVE, health, entries, last update, next update,
independence group. CHECK даёт evidence, но не должен сам разрешать AUTO BLOCK.

### 5. Категории защиты

Ads, Popup/Redirect, Tracking, Analytics, Telemetry, Affiliate, Mail tracking,
Social tracking, Resource abuse. На первом этапе часть controls может быть disabled с
меткой «Планируется».

### 6. История / Logger

Единый журнал по образцу диагностической ценности uBO: timestamp, client, domain,
verdict, action, matching sources, rule owner, reason. Фильтры по клиенту, домену,
категории, verdict, source.

### 7. Клиенты и профили (placeholder)

Standard / Strict / TV-IoT / Observe only; назначение профиля клиентам AGH.

### 8. Privacy Monitor (placeholder)

Top trackers/telemetry по клиентам, новые домены, динамика 24h/7d/30d.

### 9. Anti-bypass (placeholder)

Только мониторинг по умолчанию: признаки DoH/DoT/DoQ bypass. Firewall policy — другая
ответственность и не должна автоматически включаться компонентом.

### 10. Помощник при поломке (placeholder)

«Сайт перестал работать» -> последние VWARD-блокировки клиента -> временно разрешить
5/15/60 минут -> проверить -> закрепить ALLOW либо вернуть BLOCK.

### 11. Резервная копия (placeholder)

Export/import только локальных VWARD settings, source overrides, manual rules и client
profiles. Никаких секретов или полного `AdGuardHome.yaml` в экспортируемом профиле.

## Маркировка незавершённых функций

Заглушки обязательно показываются как `Планируется`, имеют disabled controls и не
отправляют backend-запросы. UI не должен притворяться, что функция уже работает.


## HTTPS Content Guard panel (v6)

Within the existing Ads & Privacy Guard settings area, show one compact panel: running
state, provider readiness, local CA state/fingerprint, number of intercept hosts/rules and
PAC path. Actions: refresh, validate, create CA, start, stop. Do not add a top-level menu.
Do not expose CA private keys or raw provider config. Complex rule editing remains a later
validated UI task.
# Dev.8 visual polish addendum

The current Settings Center keeps the existing information architecture and groups
the Ads & Privacy Guard settings into three visual sections. This is presentation
only: field IDs, setting keys and backend actions remain unchanged. Controls use a
minimum 44 px action height, two-column desktop layout, single-column compact layout,
visible keyboard focus and reduced-motion support. The lower action row is sticky
inside the component panel and uses the established VWARD button system.
