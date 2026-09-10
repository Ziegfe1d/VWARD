# Changelog

## 0.2.0-beta.1: Discovery First foundation

- Начата отдельная Beta-линия глубокой универсализации VWARD.
- Добавлен read-only `VWARD Discovery` в составе `VWARD Runtime`.
- WireGuard inventory определяется по фактическому RCI `type == "Wireguard"`, а не по имени, номеру или количеству интерфейсов.
- RCI ID сопоставляется с Linux-интерфейсом через штатный Keenetic `system-name`; fallback по фактическому IPv4-адресу остаётся только для read-only discovery.
- Для роли Tunnel Guard введены состояния `READY`, `NOT_FOUND`, `REQUIRES_SELECTION` и `STALE_MAPPING`.
- При нескольких туннелях VWARD не выбирает случайный интерфейс; допускается явный `tunnel_guard_rci_id`.
- `wg-health-watch.sh` переведён на read-only role selection через VWARD Discovery: RCI и Linux ID берутся из обнаруженного объекта, а не из жёстких имён.
- При неоднозначном или устаревшем mapping Tunnel Guard health остаётся `UNKNOWN` и не выполняет пробных RCI/network-запросов к угаданным интерфейсам.
- Добавлены read-only команды `wan` и `wan-guard` для динамического определения internet uplink без привязки к `ISP` и `ethN`.
- WAN-кандидаты классифицируются по RCI `global/defaultgw/security-level`, а VPN-role `misc` исключается из автоматического и explicit WAN mapping.
- Для логических uplink, включая PPPoE, Discovery сохраняет сам RCI/Linux interface и нижележащие `via_rci_id` / `via_linux_if`, чтобы recovery мог стать type-aware.
- WAN role поддерживает `READY`, `NOT_FOUND`, `REQUIRES_SELECTION`, `STALE_MAPPING` и `INVALID_MAPPING`; явно выбранный uplink сохраняет роль при временной потере `defaultgw`.
- Добавлен единый `vward-discovery.sh snapshot`, который одним проходом возвращает WireGuard/WAN inventories и роли Tunnel Guard/WAN Guard.
- Добавлен отдельный read-only `wan-health-watch.sh`. Он использует discovered `wan-guard`, разделяет logical `PATH_IF` и physical `PHYSICAL_IF`, поддерживает PPPoE `via` и не содержит `ndmc`, DHCP renew или interface down/up.
- WAN observer привязывает gateway/external probes к фактическому `PATH_IF`. Глобальный Keenetic Internet status больше не может сам по себе классифицировать выбранный WAN как `HEALTHY`, поэтому другой uplink не маскирует его отказ.
- При ambiguous/stale/invalid role, unresolved Linux mapping или physical carrier down WAN observer работает fail-safe и не запускает guessed/unbound probes.
- WAN observer пишет атомарный state в `/opt/var/lib/wan-health/state`, переходы в `/opt/var/log/wan-health.log` и запускается отдельным cron entry независимо от legacy recovery.
- Добавлен type-aware `wan-recovery-plan.sh` в обязательном режиме `dryrun`. Он повторно проверяет текущую роль `wan-guard`, свежесть observer state и совпадение RCI/Linux mapping перед выдачей любого плана.
- Recovery Planner использует решения `HOLD`, `DEFER`, `BLOCKED`, `PLAN`, различает `SESSION_RECONNECT` для логических uplink и `INTERFACE_RECONNECT` для подтверждённых физических path failures и всегда возвращает `EXECUTED=NO`.
- `PHY_DOWN`, DNS-only failure, ambiguity/stale/mismatch и физический `ADDRESS_FAILURE` без доказанной DHCP-capability не дают Planner права на автоматическую mutation. Тип Ethernet не считается доказательством DHCP.
- Recovery Planner зарегистрирован как runtime-target `VWARD WAN Guard`, покрыт behavioral tests и намеренно не включён в cron до отдельной приёмки динамического actuator.
- VWARD Console переведена на один Discovery snapshot на status request. Собственный full interface inventory, фильтрация `WireguardN` и прямой `show/interface?name=ISP` из CGI удалены.
- Для совместимости frontend `wg.interfaces[].name` остаётся alias фактического `rci_id`; API публикует `wg.discovery` и `wan.discovery`, а также реальные WAN `rci_id`, `linux_if`, `via_*` и тип uplink.
- `wan.status` и `wan.class` Console получает из `wan-health-watch`. State старше 180 секунд, другой observer RCI/Linux mapping или текущий не-READY WAN role отвергаются как `UNKNOWN`.
- Frontend определяет состояние WAN по `wan.status`, а не по глобальному `wan.internet`, включая Overview, hero, настройки и session chart.
- Legacy `wan-guardian.sh` пока остаётся отдельным recovery path. `wan.action`, recovery counters и legacy class явно маркируются `recovery_source=legacy-wan-guardian`; mutating WAN recovery этим этапом не менялся.
- Repository tests покрывают 0/1/N туннелей, произвольные RCI ID, stale mapping, discovery-driven health, Ethernet/PPPoE WAN, несколько uplink, VPN exclusion, selected-path probe isolation, Recovery Planner decision gates, Console snapshot/observer contracts и Entware `jq` без ONIGURUMA.
- High-risk fail-open и WAN recovery mutations, Policy Sync и Route Engine этим этапом пока не переключаются.

## 0.1.7-dev: критический переходный hotfix VWARD Console

- Удалена жёсткая привязка Console к `Wireguard0` и `Wireguard1`.
- Console API теперь обнаруживает фактические WireGuard-интерфейсы динамически через RCI и отдаёт их как `wg.interfaces[]`.
- Frontend поддерживает 0, 1 и несколько туннелей без фиксированных `g.wg0` / `g.wg1`.
- Исправлен подтверждённый случай, когда запрос отсутствующего `Wireguard0` постоянно загрязнял системный журнал Keenetic.
- Учтена целевая среда Keenetic/Entware: для этой логики не требуются regex-функции `jq` с ONIGURUMA и сложные GNU-only конструкции `awk`.
- Релиз остаётся переходным legacy `dev` bridge для установленных `0.1.6-dev`; Stable/Beta и большой Zero-Hardcode refactor выполняются отдельным этапом.
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
