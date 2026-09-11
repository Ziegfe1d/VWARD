# Changelog

## 0.2.0-beta.1: Discovery First foundation

- Начата отдельная Beta-линия глубокой универсализации VWARD.
- Добавлен read-only `VWARD Discovery` в составе `VWARD Runtime`.
- WireGuard inventory определяется по фактическому RCI `type == "Wireguard"`, а не по имени, номеру или количеству интерфейсов.
- RCI ID сопоставляется с Linux-интерфейсом через штатный Keenetic `system-name`; fallback по фактическому IPv4-адресу остаётся только для read-only discovery.
- Для роли Tunnel Guard введены состояния `READY`, `NOT_FOUND`, `REQUIRES_SELECTION` и `STALE_MAPPING`; при нескольких туннелях случайный интерфейс не выбирается.
- `wg-health-watch.sh` переведён на Discovery role selection; при неоднозначном/stale mapping health остаётся `UNKNOWN` без guessed probes.
- Добавлены `wan` и `wan-guard` для динамического определения internet uplink без `ISP`/`ethN` hardcode. VPN-role `misc` исключается из WAN targets.
- Для логических uplink Discovery сохраняет `via_rci_id` / `via_linux_if`, чтобы recovery различал logical session и physical path.
- Добавлен единый `vward-discovery.sh snapshot` для WireGuard/WAN inventories и ролей Tunnel Guard/WAN Guard.
- Добавлен read-only `wan-health-watch.sh`, который привязывает probes к выбранному `PATH_IF`; другой рабочий uplink не маскирует отказ наблюдаемого WAN.
- WAN observer атомарно пишет `/opt/var/lib/wan-health/state` и запускается отдельно от legacy recovery.
- Добавлен read-only `wan-capability.sh`: DHCP capability подтверждается только фактическим `ip address dhcp` из `show running-config`; содержимое конфига и credentials не публикуются.
- Добавлен type-aware `wan-recovery-plan.sh`, который всегда остаётся `dryrun` и выдаёт только `HOLD`, `DEFER`, `BLOCKED` или `PLAN`.
- Planner поддерживает typed actions `SESSION_RECONNECT`, `INTERFACE_RECONNECT` и capability-gated `DHCP_RENEW`; stale/ambiguous/mismatched/static/unknown states работают fail-safe.
- `wan-recovery-actuator.sh` переведён на Discovery/Capability contract и теперь содержит exact recovery operations, но execution по умолчанию выключен через `VWARD_WAN_RECOVERY_EXECUTION_ENABLED=0`.
- Для live Actuator дополнительно требуется внутренний `VWARD_WAN_RECOVERY_CONTROLLER_AUTH=1`; прямой вызов только с execution enable блокируется.
- Exact operations используют только повторно обнаруженный RCI ID: `DHCP_RENEW` через `interface <id> ip dhcp client renew`, а physical/logical reconnect через `interface <id> down/up`.
- Logical reconnect переключает logical RCI interface, а не physical `via`. При ошибке первого `up` выполняется один best-effort retry.
- `ndmc` запускается с очищенным `LD_LIBRARY_PATH`; `eval`, произвольный command handoff, `ISP`/`eth3` hardcode и `system configuration save` не используются.
- `wan-recovery-controller.sh` остаётся единственной Execution Gate точкой. Он не содержит network commands и не включён в cron.
- При execution enable Controller блокирует конфликт с Update Engine, legacy WAN recovery и Tunnel Guard mutation, применяет cooldown/rate-limit и резервирует attempt в persistent state/audit log до Actuator call.
- Default recovery policy: cooldown 300 секунд, окно 3600 секунд, максимум 3 attempts, 3 post-check с интервалом 3 секунды. Значения являются изменяемыми policy defaults, не installation-specific topology assumptions.
- После `EXECUTED=YES` Controller повторно запускает WAN Observer. `SUCCESS` возможен только при свежем `UP/HEALTHY` для тех же RCI/Linux IDs; иначе возвращается `RECOVERY_UNCONFIRMED` с сохранением факта mutation.
- Добавлены behavioral tests на default-off, direct-actuator authorization, exact mock `ndmc` operations, DHCP capability, TOCTOU, cooldown, rate-limit, updater/legacy/tunnel conflicts, persistent state/audit и post-check success/failure.
- Добавлен authoritative `docs/WAN_RECOVERY_PIPELINE.md` и обязательный documentation gate.
- `vward-update-runtime-policy.sh` разрешает установку нового WAN runtime stack и учитывает controller/observer locks при quiescing.
- VWARD Console использует один Discovery snapshot на status request; собственный full interface inventory, `WireguardN` filtering и `show/interface?name=ISP` удалены.
- `wan.status`/`wan.class` приходят из WAN Observer и проходят freshness + RCI/Linux mapping validation; legacy recovery telemetry маркируется отдельно.
- Component registry consistency проверяется структурно через `jq`, а не через формат-зависимый grep.
- Read-only preflight на реальном KN-1913 подтвердил Discovery `GigabitEthernet1 -> eth3`, DHCP capability, `UP/HEALTHY` observer state и zero-write Controller path без изменений production VWARD.
- Controlled live acceptance `DHCP_RENEW` на KN-1913 пройден: Planner выдал `PLAN/DHCP_RENEW`, Actuator выполнил `RCI_DHCP_RENEW`, Controller завершил `RESULT=SUCCESS`, `POSTCHECK=HEALTHY`, `EXECUTED=YES`.
- После live DHCP recovery WAN сохранил тот же адрес `100.85.218.53`, `link=up`, `connected=yes`, `defaultgw=true`; persistent state и audit log зафиксировали одну успешную attempt.
- Controlled live acceptance `INTERFACE_RECONNECT` на KN-1913 пройден отдельно: SSH safety check подтвердил management path через LAN `br0`, Planner выдал `PLAN/INTERFACE_RECONNECT`, Actuator выполнил `RCI_INTERFACE_RECONNECT`, Controller завершил `RESULT=SUCCESS`, `POSTCHECK=HEALTHY`, `EXECUTED=YES`.
- После physical down/up WAN вернулся в `UP/HEALTHY` с тем же `GigabitEthernet1 -> eth3`, тем же адресом и default route; аварийный delayed `up` rescue не понадобился.
- Для текущей физической DHCP topology оба применимых live action (`DHCP_RENEW`, `INTERFACE_RECONNECT`) приняты. `SESSION_RECONNECT` не моделируется искусственно: текущий Capability Provider возвращает `session_reconnect=false`, поэтому его live acceptance откладывается до реального logical uplink.
- Controller по-прежнему не стоит в cron, execution default остаётся `0`, legacy `wan-guardian.sh` остаётся production recovery path до отдельного controlled rollout/cutover нового stack.
- High-risk fail-open, Policy Sync и Route Engine ещё не полностью переведены на общий Zero-Hardcode role mapping.

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

- Added the canonical VWARD Platform component registry and unified product names without changing runtime filenames, paths or the active signed feed.
- Added updater-owned runtime quiescing/resume orchestration, Entware-compatible file-mode verification and recovery-aware idempotent updater installation.
- Added the signed `0.1.2-dev` runtime-barrier acceptance package.
- Enabled signed automatic apply after live-router apply, rollback, runtime quiescing, service-resume and production-file preservation acceptance passed.
- Added the signed Smart Updater production bootstrap, pinned Ed25519 public key, check-only production configuration and live-router installer.
- Corrected the Keenetic updater health probe to use the supported `ndmc -c "show version"` invocation.
- Imported the working VWARD shell, init, CGI and web sources from the verified 2026-09-06 read-only router snapshot.
- Added the production cron schedule as managed source.
- Added the installation map, dependency inventory and future updater design.
- Classified generated and device-local configuration separately from source.
- Removed the obsolete initial UI-only updater placeholder.
- Added the disabled, implementation-stage Smart Updater v1 subsystem, signed manifest schema, rollback model and isolated simulation suite. It is not deployed.
- Synchronized the verified 2026-09-09 production fixes: Adaptive maintenance probe compatibility, Adaptive Live group-refresh throttling, self-healing tcpdump watchdog grace, cached WireGuard RCI checks, and bounded log/storage housekeeping with the active hourly cron schedule.

## 0.1.0-dev — 2026-09-06

- Добавлен текущий frontend snapshot v28.
- Подготовлена структура публичного репозитория.
- Добавлен безопасный updater интерфейса.
- Добавлены README, SECURITY, CONTRIBUTING и документация.
- Backend и WAN Guardian пока не публикуются как стабильные компоненты: требуется отдельная универсализация и security-аудит.
