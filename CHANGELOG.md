# Changelog

## Unreleased

- Added the signed Smart Updater production bootstrap, pinned Ed25519 public
  key, check-only production configuration and live-router installer.
- Corrected the Keenetic updater health probe to use the supported
  `ndmc -c "show version"` invocation.
- Imported the working VWARD shell, init, CGI and web sources from the verified
  2026-09-06 read-only router snapshot.
- Added the production cron schedule as managed source.
- Added the installation map, dependency inventory and future updater design.
- Classified generated and device-local configuration separately from source.
- Removed the obsolete initial UI-only updater placeholder.
- Added the disabled, implementation-stage Smart Updater v1 subsystem, signed
  manifest schema, rollback model and isolated simulation suite. It is not deployed.
- Synchronized the verified 2026-09-09 production fixes: Adaptive maintenance
  probe compatibility, Adaptive Live group-refresh throttling, self-healing
  tcpdump watchdog grace, cached WireGuard RCI checks, and bounded log/storage
  housekeeping with the active hourly cron schedule.

## 0.1.0-dev — 2026-09-06

- Добавлен текущий frontend snapshot v28.
- Подготовлена структура публичного репозитория.
- Добавлен безопасный updater интерфейса.
- Добавлены README, SECURITY, CONTRIBUTING и документация.
- Backend и WAN Guardian пока не публикуются как стабильные компоненты:
  требуется отдельная универсализация и security-аудит.
