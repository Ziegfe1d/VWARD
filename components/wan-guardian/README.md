# VWARD WAN Guard

VWARD WAN Guard разделён на независимые слои обнаружения, наблюдения, планирования и выполнения recovery.

`VWARD Discovery` определяет фактическую роль `wan-guard`, RCI ID, Linux-интерфейс и `via` для логических uplink. Компоненты WAN Guard не должны угадывать `ISP`, `ethN` или другие installation-specific имена.

`wan-health-watch.sh` - read-only observer. Он использует фактические `rci_id` и `linux_if`, учитывает `via` для PPPoE/логических uplink и выполняет только диагностические проверки. При неоднозначном или неразрешённом mapping он работает fail-safe и не запускает непривязанные сетевые probes.

`wan-recovery-plan.sh` - type-aware Recovery Planner в режиме `dryrun`. Он читает свежий observer state, повторно проверяет текущую роль `wan-guard` и совпадение RCI/Linux mapping, ждёт подтверждённого числа ошибок и выдаёт только решение `HOLD`, `DEFER`, `BLOCKED` или `PLAN`. Planner всегда возвращает `EXECUTED=NO` и не содержит network mutation.

Planner различает логический и физический uplink. Для PPPoE/логического session failure он может запланировать `SESSION_RECONNECT`. Для подтверждённого физического path failure - `INTERFACE_RECONNECT`. `PHY_DOWN`, DNS-only failure, неясный Discovery и физический `ADDRESS_FAILURE` без доказанной DHCP-capability не дают права на автоматическую mutation.

`wan-recovery-actuator.sh` переведён на тот же Discovery/role contract, но пока также работает только в `dryrun`. Он принимает только типизированные действия `SESSION_RECONNECT` или `INTERFACE_RECONNECT` вместе с ожидаемыми RCI/Linux IDs, самостоятельно повторно запускает `wan-guard` Discovery и блокирует действие при любом изменении роли или mapping.

Actuator не принимает shell-команду, не использует `eval`, не содержит `ISP`, `eth3`, DHCP renew или подготовленных `ndmc` command strings. После успешной проверки он возвращает только `RESULT=READY`, тип будущей операции (`RCI_SESSION_RECONNECT` или `RCI_INTERFACE_RECONNECT`) и `EXECUTED=NO`.

Для логического reconnect обязательно наличие валидных `via_rci_id` и `via_linux_if`. Для физического reconnect наличие logical `via` наоборот блокирует действие. Это не позволяет применить физическую recovery-операцию к PPPoE/другому логическому uplink или наоборот.

`wan-guardian.sh` пока остаётся legacy recovery path рабочего роутера. Его существующие cooldown/rate-limit и текущая модель `ISP`/`eth3` этим этапом не меняются. Новый Planner/Actuator не подключены к его mutating path и не запускаются из cron.

Repository tests отдельно проверяют Planner, Actuator и полный Planner -> Actuator pipeline, включая TOCTOU-сценарий, когда роль WAN меняется после планирования. В таком случае Actuator обязан вернуть `BLOCKED` и ничего не выполнять.

Следующий этап - определить capability и exact RCI recovery operations для поддерживаемых типов WAN, затем спроектировать отдельный execution gate с lock/cooldown/post-check/rollback. Реальные mutation разрешать только после отдельного Beta acceptance и проверки на целевом Keenetic.
