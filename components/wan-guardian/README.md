# VWARD WAN Guard

VWARD WAN Guard разделён на независимые слои обнаружения, наблюдения, capability, планирования и выполнения recovery.

`VWARD Discovery` определяет фактическую роль `wan-guard`, RCI ID, Linux-интерфейс и `via` для логических uplink. Компоненты WAN Guard не должны угадывать `ISP`, `ethN` или другие installation-specific имена.

`wan-health-watch.sh` - read-only observer. Он использует фактические `rci_id` и `linux_if`, учитывает `via` для PPPoE/логических uplink и выполняет только диагностические проверки. При неоднозначном или неразрешённом mapping он работает fail-safe и не запускает непривязанные сетевые probes.

`wan-capability.sh` - read-only Capability Provider. Он запускается только по требованию recovery, повторно подтверждает роль `wan-guard` и читает `show running-config`, но наружу не публикует сам конфиг. Provider возвращает только безопасную классификацию addressing/recovery capability. DHCP считается подтверждённым только при фактической строке `ip address dhcp` в блоке выбранного RCI-интерфейса. Тип `GigabitEthernet` сам по себе не считается доказательством DHCP.

`wan-recovery-plan.sh` - type-aware Recovery Planner в режиме `dryrun`. Он читает свежий observer state, повторно проверяет текущую роль `wan-guard` и совпадение RCI/Linux mapping, ждёт подтверждённого числа ошибок и выдаёт только решение `HOLD`, `DEFER`, `BLOCKED` или `PLAN`. Planner всегда возвращает `EXECUTED=NO` и не содержит network mutation.

Planner различает логический и физический uplink. Для PPPoE/логического session failure он может запланировать `SESSION_RECONNECT`. Для подтверждённого физического path failure - `INTERFACE_RECONNECT`. Для физического `ADDRESS_FAILURE` Planner обращается к Capability Provider и может выдать `DHCP_RENEW` только при `state=READY`, совпадении RCI/Linux mapping, `addressing.mode=dhcp` и `dhcp_renew=true`. Static, unknown, stale, mismatch и неоднозначные состояния не дают права на DHCP action.

`wan-recovery-actuator.sh` переведён на тот же Discovery/Capability contract, но пока также работает только в `dryrun`. Он принимает только типизированные действия `SESSION_RECONNECT`, `INTERFACE_RECONNECT` или `DHCP_RENEW` вместе с ожидаемыми RCI/Linux IDs. Непосредственно перед готовностью к действию он заново запускает Discovery, а для DHCP ещё раз проверяет Capability Provider.

Actuator не принимает shell-команду, не использует `eval`, не содержит `ISP`, `eth3`, готового `ip dhcp client renew` или подготовленных `ndmc` command strings. После успешной проверки он возвращает только `RESULT=READY`, тип будущей операции (`RCI_SESSION_RECONNECT`, `RCI_INTERFACE_RECONNECT` или `RCI_DHCP_RENEW`) и `EXECUTED=NO`.

Для логического reconnect обязательно наличие валидных `via_rci_id` и `via_linux_if`. Для физического reconnect/DHCP наличие logical `via` блокирует действие. Это не позволяет применить физическую recovery-операцию к PPPoE/другому логическому uplink или наоборот.

`wan-guardian.sh` пока остаётся legacy recovery path рабочего роутера. Его существующие cooldown/rate-limit и текущая модель `ISP`/`eth3` этим этапом не меняются. Новый Capability/Planner/Actuator не подключены к его mutating path и не запускаются из cron.

Repository tests отдельно проверяют Capability Provider, Planner, Actuator и полный Planner -> Actuator pipeline. Покрыты TOCTOU-сценарии смены WAN role и смены DHCP capability после планирования. В обоих случаях Actuator обязан вернуть `BLOCKED` и ничего не выполнять.

Следующий этап - спроектировать отдельный execution gate с собственным lock, cooldown/rate-limit, повторным pre-check, post-check и безопасным recovery/rollback поведением. Реальные mutation разрешать только после отдельного Beta acceptance и проверки exact RCI operations на целевом Keenetic.
