# VWARD WAN Guard

VWARD WAN Guard разделён на независимые слои обнаружения, наблюдения, планирования и выполнения recovery.

`VWARD Discovery` определяет фактическую роль `wan-guard`, RCI ID, Linux-интерфейс и `via` для логических uplink. Компоненты WAN Guard не должны угадывать `ISP`, `ethN` или другие installation-specific имена.

`wan-health-watch.sh` - read-only observer. Он использует фактические `rci_id` и `linux_if`, учитывает `via` для PPPoE/логических uplink и выполняет только диагностические проверки. При неоднозначном или неразрешённом mapping он работает fail-safe и не запускает непривязанные сетевые probes.

`wan-recovery-plan.sh` - новый type-aware Recovery Planner в режиме `dryrun`. Он читает свежий observer state, повторно проверяет текущую роль `wan-guard` и совпадение RCI/Linux mapping, ждёт подтверждённого числа ошибок и выдаёт только решение `HOLD`, `DEFER`, `BLOCKED` или `PLAN`. Planner всегда возвращает `EXECUTED=NO` и не содержит network mutation.

Planner различает логический и физический uplink. Для PPPoE/логического session failure он может запланировать `SESSION_RECONNECT`. Для подтверждённого физического path failure - `INTERFACE_RECONNECT`. `PHY_DOWN`, DNS-only failure, неясный Discovery и физический `ADDRESS_FAILURE` без доказанной DHCP-capability не дают права на автоматическую mutation.

`wan-guardian.sh` пока остаётся legacy recovery path рабочего роутера. Его существующие cooldown/rate-limit и текущая модель `ISP`/`eth3` этим этапом не меняются и не связаны с Planner.

`wan-recovery-actuator.sh` пока остаётся отдельным legacy dry-run actuator. Он ещё не переведён на новый role contract и не вызывается новым Planner.

Следующий этап - спроектировать динамический dry-run actuator, который перед любым действием самостоятельно повторно подтвердит текущую `wan-guard` роль и допустимую capability. Только после отдельного acceptance можно обсуждать включение реальных mutation.
