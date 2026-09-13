# Changelog

## 0.2.0-dev.2: runtime-унификация и защита Console

- Runtime-файлы, init/cron, PID, lock, state, log и configuration paths напрямую
  переведены в каноническое пространство имён VWARD без aliases и wrappers.
- Update Engine allowlist, health checks, backup/rollback simulations, registry и
  release workflow синхронизированы с новыми runtime-targets.
- Console сохраняет LAN-only bind `192.168.1.1:8088`; wildcard bind запрещён тестом.
- Для всех изменяющих API-запросов обязателен request guard и form content type;
  удалён ненужный CORS-preflight путь.
- Добавлены browser security headers, запрет directory listing и выдачи файлов с
  типичными backup/editor suffixes.
- Проверка живых сокетов и firewall остаётся обязательным блокирующим этапом перед
  первой установкой Dev на роутер.

## 0.2.0-dev.1: начало основной dev-линии

- Ветка `dev` синхронизирована с полностью подписанной базой `0.1.7-beta`.
- Начат этап глубокой унификации VWARD Platform, Zero-Hardcode и совместимых миграций
  внутренних имён компонентов.
- Подписанный beta-feed `0.1.7-beta` сохранён без изменений; dev-пакет на роутер этим
  коммитом не публикуется.
- Зафиксирована односторонняя синхронизация Beta fixes -> Dev и схема версий для обеих
  линий.
- Добавлен поэтапный план Device Discovery, Zero-Hardcode, компонентной унификации и
  завершения VWARD Console.
- В актуальных исходных комментариях старое имя Smart Updater заменено на каноническое
  VWARD Update Engine без изменения runtime-логики.
- Source-дерево напрямую переведено на канонические каталоги Route Engine, Route
  Reconciler, Route Tools, Tunnel Guard, WAN Guard, Policy Sync, Runtime и Update Engine.
- Legacy component IDs удалены из Dev registry и schema; переходные aliases и wrappers
  в Dev не создаются.

## 0.1.7-beta: критический переходный hotfix VWARD Console

- Route Engine получил read-only сводку фактических доменных и IP/CIDR-каталогов: источники, категории, AdaptiveAuto, активные IP-категории и количество маршрутов Policy Sync без расширения mutation API.
- Журналы переведены с одиночных вкладок на компактный multi-source workspace: выбор нескольких источников, поиск, счётчик строк, ручное и автоматическое обновление, копирование, TXT-сохранение и системный Share.
- Добавлена общая контекстная лампочка-подсказка; текст зависит от открытого раздела и текущего backend-state.
- Detail pages очищены от повторяющихся заголовков, видимые статусы и служебные поля частично русифицированы, графики получили скруглённые окончания и соединения.
- Удалена жёсткая привязка Console к `Wireguard0` и `nwg1`.
- Console API теперь обнаруживает фактические WireGuard-интерфейсы динамически через RCI и отдаёт их как `wg.interfaces[]`.
- Frontend поддерживает 0, 1 и несколько туннелей без фиксированных `g.wg0` / `g.wg1`.
- Исправлен подтверждённый случай, когда запрос отсутствующего `Wireguard0` постоянно загрязнял системный журнал Keenetic.
- Учтена целевая среда Keenetic/Entware: для этой логики не требуются regex-функции `jq` с ONIGURUMA и сложные GNU-only конструкции `awk`.
- Релиз является переходным beta-мостом для установленных `0.1.6-dev`; большой Zero-Hardcode refactor продолжается в линии `0.2.0-dev.x`.
- Не изменяются Route Engine, Tunnel Guard, Policy Sync и высокорисковые runtime paths.

## 0.1.6-dev: панель управления и документация

- Обновлена русская документация по установке, компонентам и обновлениям.
- Добавлены локальные SVG-иконки, названия компонентов и плавающая нижняя панель на мобильных экранах.
- Уточнены настройки автообновления, диагностика и отображение журналов.
- Добавлены проверки согласованности документации и элементов панели.
- Подписанный пакет обновляет панель и VERSION с 0.1.4-dev или 0.1.5-dev.

## 0.1.5-dev — Interactive VWARD Console

- Rebuilt VWARD Console as a Keenetic-inspired component dashboard with
  clickable cards, responsive navigation and real session sparklines.
- Added detailed read-only component screens and a guarded editor for the four
  existing Smart Updater automatic-apply policy flags.
- Kept routing, tunnel, WAN recovery and other production settings read-only.

## 0.1.3-dev — Component-aware selective updates

- Corrected updater-slot activation for BusyBox `mv` symlink-to-directory semantics and added post-swap verification.
- Enforced canonical component ownership across the signed feed, package manifest and bundled registry.
- Added rejection of unknown/mismatched components, duplicate targets or sources, incorrect modes, missing dependencies and undeclared package files.
- Added atomic per-component installed state with rollback support and `--status-components`.
- Added component-specific health profiles while retaining the accepted default profile and legacy component aliases.
- Kept Update Engine self-update isolated behind the existing atomic slot installer.

## Unreleased

- Added the canonical VWARD Platform component registry and unified product
  names without changing runtime filenames, paths or the active signed feed.
- Added updater-owned runtime quiescing/resume orchestration, Entware-compatible
  file-mode verification and recovery-aware idempotent updater installation.
- Added the signed `0.1.2-dev` runtime-barrier acceptance package.
- Enabled signed automatic apply after live-router apply, rollback, runtime
  quiescing, service-resume and production-file preservation acceptance passed.
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
