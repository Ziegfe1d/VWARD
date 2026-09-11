# VWARD WAN Guard

VWARD WAN Guard разделён на независимые слои обнаружения, наблюдения, capability, планирования, execution gate, actuator и post-check.

`VWARD Discovery` определяет фактическую роль `wan-guard`, RCI ID, Linux-интерфейс и `via` для логических uplink. Компоненты WAN Guard не должны угадывать `ISP`, `ethN` или другие installation-specific имена.

`wan-health-watch.sh` - read-only observer. Он использует фактические `rci_id` и `linux_if`, учитывает `via` для PPPoE/логических uplink и выполняет только диагностические проверки. При неоднозначном или неразрешённом mapping он работает fail-safe и не запускает непривязанные сетевые probes.

`wan-capability.sh` - read-only Capability Provider. Он запускается только по требованию recovery, повторно подтверждает роль `wan-guard` и читает `show running-config`, но наружу не публикует сам конфиг. DHCP считается подтверждённым только при фактическом `ip address dhcp` в блоке выбранного RCI-интерфейса. Тип Ethernet сам по себе не считается доказательством DHCP.

`wan-recovery-plan.sh` - type-aware Recovery Planner. Он всегда остаётся `dryrun`, использует свежий observer state, повторно проверяет роль/mapping и выдаёт только `HOLD`, `DEFER`, `BLOCKED` или `PLAN`. Разрешённые typed actions: `SESSION_RECONNECT`, `INTERFACE_RECONNECT`, а также capability-gated `DHCP_RENEW`.

`wan-recovery-controller.sh` - единственный Execution Gate. По умолчанию `VWARD_WAN_RECOVERY_EXECUTION_ENABLED=0`, поэтому Controller и Actuator работают без mutation. Live path не включён в cron.

При явном execution enable Controller до Actuator проверяет:
- собственный lock;
- Update Engine lock/barrier/request;
- legacy WAN recovery lock;
- Tunnel Guard mutation lock;
- cooldown;
- max attempts per window;
- возможность persistent state/audit write.

Каждая live attempt резервируется до mutation. После успешного Actuator call Controller запускает `wan-health-watch.sh` и считает recovery успешным только при свежем `UP/HEALTHY` для тех же `rci_id` и `linux_if`. Иначе результат остаётся `RECOVERY_UNCONFIRMED`.

`wan-recovery-actuator.sh` - единственный новый слой с exact network operations. Даже при `execution_enabled=1` прямой live-вызов без внутреннего `VWARD_WAN_RECOVERY_CONTROLLER_AUTH=1` блокируется.

Exact operations используют только повторно обнаруженный RCI ID:
- `DHCP_RENEW`: `interface <rci-id> ip dhcp client renew`;
- `INTERFACE_RECONNECT`: `interface <rci-id> down`, затем `up`;
- `SESSION_RECONNECT`: `down/up` именно logical RCI interface, а не physical `via`.

Actuator запускает `ndmc` с очищенным `LD_LIBRARY_PATH`, не использует `eval`, не принимает произвольный shell command text и не вызывает `system configuration save`. Если первый `up` после reconnect не проходит, выполняется один best-effort повтор `up`.

Policy defaults Controller: cooldown 300 секунд, окно 3600 секунд, максимум 3 попытки, 3 post-check с интервалом 3 секунды. Это изменяемые recovery-policy defaults, а не installation-specific свойства роутера.

`wan-guardian.sh` пока остаётся legacy production recovery path рабочего роутера. Новый stack не заменяет его автоматически и execution на реальном устройстве пока не включён.

Repository tests покрывают default-off, direct-actuator authorization guard, exact mock `ndmc` operations, DHCP capability, role/mapping TOCTOU, cooldown, rate limit, updater/legacy/tunnel conflicts, persistent audit state и post-check success/failure.

Authoritative описание: `docs/WAN_RECOVERY_PIPELINE.md`.

Следующий этап - read-only preflight и одна контролируемая live-приёмка на целевом Keenetic. До неё `execution_enabled` остаётся `0`, Controller не добавляется в cron, legacy recovery остаётся production path.
