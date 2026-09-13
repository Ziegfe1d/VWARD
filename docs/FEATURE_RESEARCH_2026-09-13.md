# Исследование функций блокировщиков для VWARD Ads & Privacy Guard

Дата: 2026-09-13. Цель — собрать полезные паттерны интерфейса и защиты, а не копировать
реализацию или обещать функции, недоступные DNS-уровню.

## Что стоит перенять

### uBlock Origin

- единый Logger для диагностики: что разрешено/заблокировано и каким правилом;
- отдельные Filter lists / My filters / My rules / Trusted sites;
- статические списки + более точные локальные правила;
- быстрые per-site переключатели и режимы для опытных пользователей;
- backup/restore настроек;
- принцип производительности: широкая защита без постоянной тяжёлой обработки.

### AdGuard / AdGuard filters

- разбиение на Ads, Privacy, Tracking, Social, Annoyances;
- Tracking Protection, mail-tracking, analytics/counters;
- отдельные фильтры popup/annoyances;
- user rules + allowlist + filtering log;
- осторожность с антиботом/captcha и error-reporting сервисами: агрессивная privacy
  фильтрация может ломать функциональность.

### Adblock Plus / EasyList ecosystem

- управляемые filter subscriptions;
- собственные filters и exceptions;
- allowlisting;
- отдельная anti-circumvention идея;
- временное/самоистекающее разрешение как полезный UX-паттерн для будущего VWARD.

### Pi-hole

- группы и применение правил/списков по группам клиентов;
- exact/regex allow/deny;
- чёткий приоритет allowlist над denylist;
- возможность временно включать/выключать наборы правил.

### AdGuard Home

- per-client filtering и `$client`/`$ctag` rules уже существуют на стороне AGH;
- VWARD не должен дублировать AGH, а может построить поверх этого удобные client
  profiles и автоматическое создание только своих managed rules.

## Что часто нужно пользователям по обсуждениям

- понять, почему сайт сломался и какое правило было последним;
- быстро временно разрешить домен/группу и вернуть защиту автоматически;
- видеть статистику по конкретному клиенту, а не только общий счётчик;
- обнаруживать устройства/приложения, которые обходят локальный DNS через DoH/DoT/DoQ;
- не включать слишком много агрессивных списков без диагностики false positives.

## Что переносим в шаблон меню сейчас

1. Обзор и главный переключатель.
2. Ручная проверка домена.
3. Очередь и текущая проверка.
4. Управляемые правила VWARD.
5. Источники OFF/CHECK/ACTIVE.
6. Категории защиты Ads/Popup/Tracking/Analytics/Telemetry/Affiliate/Mail/Social.
7. История/Logger.
8. Профили клиентов — disabled placeholder.
9. Privacy Monitor — disabled placeholder.
10. Anti-bypass — disabled placeholder.
11. Breakage Assistant — disabled placeholder.
12. Backup/restore — disabled placeholder.

## Источники исследования

- https://github.com/gorhill/uBlock/wiki/
- https://github.com/gorhill/ublock/wiki/The-logger
- https://github.com/gorhill/ublock/wiki/Dashboard:-Filter-lists
- https://github.com/gorhill/ublock/wiki/Strict-blocking
- https://adguard.com/kb/general/ad-filtering/adguard-filters/
- https://adguard.com/kb/general/ad-filtering/filter-policy/
- https://help.adblockplus.org/adblock-plus-help-center/what-are-filter-lists
- https://help.adblockplus.org/adblock-plus-help-center/add-or-remove-a-custom-filter
- https://docs.pi-hole.net/group_management/
- https://docs.pi-hole.net/regex/
- https://github.com/AdguardTeam/AdGuardHome/wiki/Clients
- community discussions: r/AdGuardHome, r/pihole, r/uBlockOrigin
