# VWARD WAN Recovery Pipeline

Этот документ является authoritative описанием новой Discovery-driven цепочки восстановления WAN в Beta `0.2.x`.

## Статус

Текущая цепочка:

`Discovery -> Observer -> Capability -> Planner -> Controller -> Actuator -> Observer post-check`

Planner остаётся полностью read-only/dry-run. Controller и Actuator теперь содержат подготовленный execution path, но он **выключен по умолчанию**: `VWARD_WAN_RECOVERY_EXECUTION_ENABLED=0`. Controller не включён в cron, поэтому новый stack сам по себе не выполняет recovery на роутере. Фактический рабочий production recovery пока остаётся в legacy `wan-guardian.sh` до отдельной live-приёмки.

## 1. Discovery

`vward-discovery.sh wan-guard` определяет выбранный WAN по фактическому RCI state и role mapping. Код не предполагает имена `ISP`, `eth3` или конкретную нумерацию интерфейсов.

Для выбранного uplink сохраняются:
- `rci_id`;
- `linux_if`;
- `type`;
- `via_rci_id` / `via_linux_if` для логического uplink;
- discovery/mapping state.

Неоднозначность, stale mapping и invalid mapping не разрешают recovery.

## 2. Observer

`wan-health-watch.sh` является read-only источником health state.

Он привязывает probes к фактическому `PATH_IF`, а для логического uplink отдельно учитывает физический `via` path. Глобальный Internet status не может сам по себе сделать выбранный WAN здоровым.

Observer пишет `/opt/var/lib/wan-health/state`. Recovery использует только свежий state, относящийся к текущему `rci_id` и `linux_if`.

## 3. Capability Provider

`wan-capability.sh` вызывается по требованию recovery и остаётся read-only.

Provider:
- повторно получает текущий `wan-guard`;
- читает `show running-config`;
- извлекает только блок выбранного RCI-интерфейса внутри процесса;
- не публикует running-config наружу;
- не публикует логины, пароли и другие строки конфигурации;
- возвращает только классификацию capability.

DHCP считается доказанным только при фактическом `ip address dhcp` в выбранном interface block. Тип `GigabitEthernet` сам по себе не считается доказательством DHCP.

Текущие addressing modes:
- `dhcp`;
- `static`;
- `logical`;
- `unknown`.

## 4. Recovery Planner

`wan-recovery-plan.sh` всегда работает в `MODE=dryrun` и возвращает `EXECUTED=NO`.

Перед PLAN он проверяет:
- свежесть observer state;
- текущий `wan-guard`;
- совпадение observer RCI ID с Discovery;
- совпадение Linux mapping;
- минимальное число подтверждённых ошибок;
- capability там, где она необходима.

Решения:
- `HOLD`;
- `DEFER`;
- `BLOCKED`;
- `PLAN`.

Разрешённые typed actions:
- `SESSION_RECONNECT` для подтверждённого отказа логической сессии/path;
- `INTERFACE_RECONNECT` для подтверждённого физического path failure;
- `DHCP_RENEW` только для физического `ADDRESS_FAILURE`, когда Capability Provider подтверждает `addressing.mode=dhcp` и `dhcp_renew=true`.

`PHY_DOWN`, DNS-only failure, stale/ambiguous/mismatched state и неизвестная addressing capability не дают права на mutation.

## 5. Recovery Controller

`wan-recovery-controller.sh` является единственным Execution Gate нового stack.

### Default OFF

Без явного `VWARD_WAN_RECOVERY_EXECUTION_ENABLED=1` Controller работает как dry-run validation gate:
- вызывает Planner;
- вызывает Actuator только для валидного `PLAN`;
- требует `MODE=dryrun` и `EXECUTED=NO`;
- не создаёт persistent recovery state или audit log;
- не выполняет network mutation.

### Execute path

Даже при `VWARD_WAN_RECOVERY_EXECUTION_ENABLED=1` Controller не передаёт shell-команду. Он передаёт Actuator только typed action и ожидаемые RCI/Linux IDs.

До вызова Actuator Controller:
- держит `/tmp/wan-recovery-controller.lock`;
- требует валидный Planner result;
- блокируется при активном Update Engine barrier/lock/request;
- блокируется при legacy WAN recovery lock;
- блокируется при Tunnel Guard fail-open mutation lock;
- проверяет cooldown;
- проверяет rate-limit window;
- резервирует попытку в persistent state;
- пишет audit record до mutation.

Консервативные defaults являются policy defaults, а не свойствами конкретного роутера:
- cooldown: `300` секунд;
- rate-limit window: `3600` секунд;
- max attempts: `3`;
- post-check attempts: `3`;
- delay между повторными post-check: `3` секунды.

Все значения доступны как отдельные runtime policy variables и не зависят от имени WAN, модели роутера или topology.

Persistent state по умолчанию: `/opt/var/lib/wan-recovery/state`.
Audit log по умолчанию: `/opt/var/log/wan-recovery.log`.

## 6. Recovery Actuator

`wan-recovery-actuator.sh` является единственным новым слоем, где разрешены exact network operations.

Actuator всегда заново проверяет актуальный `wan-guard` непосредственно перед operation. Для DHCP он повторно вызывает Capability Provider.

При default `execution_enabled=0` Actuator только возвращает readiness и `EXECUTED=NO`.

Для live path одновременно обязательны:
- `VWARD_WAN_RECOVERY_EXECUTION_ENABLED=1`;
- внутренний `VWARD_WAN_RECOVERY_CONTROLLER_AUTH=1`, устанавливаемый Controller;
- валидный discovered RCI/Linux mapping;
- совместимый typed action;
- дополнительная DHCP capability revalidation для `DHCP_RENEW`.

Прямой запуск Actuator только с `execution_enabled=1`, но без Controller authorization, блокируется.

Exact operations:

### DHCP_RENEW

Выполняется только для доказанного DHCP WAN:

`ndmc -c "interface <discovered-rci-id> ip dhcp client renew"`

### INTERFACE_RECONNECT

Только для physical WAN без logical `via`:

1. `ndmc -c "interface <discovered-rci-id> down"`
2. короткая bounded pause;
3. `ndmc -c "interface <discovered-rci-id> up"`

Если первый `up` не проходит, допускается один best-effort повтор `up`, чтобы не оставить интерфейс выключенным после частичного reconnect.

### SESSION_RECONNECT

Только для logical uplink с валидным `via` mapping. Переключается именно logical RCI interface, а не физический `via`:

1. `ndmc -c "interface <logical-discovered-rci-id> down"`
2. короткая bounded pause;
3. `ndmc -c "interface <logical-discovered-rci-id> up"`

Actuator очищает `LD_LIBRARY_PATH` только для запуска `ndmc`, чтобы не наследовать Entware library path в Keenetic control-plane process.

Recovery не вызывает `system configuration save`: временный reconnect не должен отдельно фиксировать пользовательскую конфигурацию.

Actuator не принимает произвольный command text, не использует `eval` и не строит имя интерфейса из номера или шаблона.

Execution kinds:
- `RCI_SESSION_RECONNECT`;
- `RCI_INTERFACE_RECONNECT`;
- `RCI_DHCP_RENEW`.

## 7. Post-check

Успешный возврат `ndmc` сам по себе не означает успешный recovery.

После `EXECUTED=YES` Controller повторно запускает `wan-health-watch.sh` и принимает recovery как `SUCCESS` только если свежий observer state одновременно показывает:
- тот же `RCI_ID`;
- тот же `LINUX_IF`;
- `STATUS=UP`;
- `CLASS=HEALTHY`;
- `LAST_CHECK` не старше момента recovery attempt.

Если post-check не подтверждает выбранный WAN, результат остаётся `RECOVERY_UNCONFIRMED`, хотя факт выполненной mutation сохраняется как `EXECUTED=YES`.

## 8. Cooldown и rate limit

Каждая live attempt резервируется до Actuator call. Это консервативно: даже crash/неопределённый результат не позволяет немедленно повторять потенциально разрушительную операцию бесконечно.

State хранит минимум:
- `LAST_ATTEMPT_EPOCH`;
- `LAST_SUCCESS_EPOCH`;
- `WINDOW_START_EPOCH`;
- `WINDOW_COUNT`;
- последний action;
- последние RCI/Linux IDs;
- последний result.

Rollback часов назад блокирует новый live attempt через `clock_regressed`, а не обнуляет защитные интервалы.

## 9. TOCTOU protection

Role/capability перепроверяются после Planner и непосредственно перед mutation.

Regression tests проверяют минимум:
- WAN role изменилась после PLAN -> Actuator `BLOCKED`;
- DHCP capability изменилась на static -> `DHCP_RENEW` `BLOCKED`;
- direct live Actuator без Controller authorization -> `BLOCKED`;
- updater/legacy WAN/Tunnel mutation conflict -> Controller `BLOCKED` до Actuator.

Решение Planner не является бессрочным разрешением на действие.

## 10. Update Engine integration

Все WAN runtime files зарегистрированы как targets компонента `wan-guard` и разрешены Update Engine.

`vward-update-runtime-policy.sh` учитывает WAN observer/controller locks при quiescing. В обратную сторону Controller проверяет updater lock/barrier/request до live mutation.

Health profile `wan-guard` требует полный runtime stack, включая Observer, Capability Provider, Planner, Actuator и Controller.

## 11. Что пока запрещено

До отдельной live Beta acceptance запрещено:
- добавлять Controller в cron;
- включать execution на рабочем роутере;
- автоматически заменять legacy `wan-guardian.sh` новым stack;
- считать mock/CI acceptance доказательством безопасной mutation на конкретном WAN;
- обходить Controller прямым вызовом live Actuator.

Planner и Controller не содержат `ndmc`; exact network commands существуют только в Actuator за двумя gates.

## 12. Следующий этап

Текущий этап считается готовым после полного CI и SHA acceptance.

Перед live-enable требуется отдельная read-only проверка на целевом Keenetic:
- фактический `wan-guard` discovery;
- фактическая addressing capability;
- наличие `/bin/ndmc` и корректность control-plane call из Entware environment;
- отсутствие конфликтующих locks;
- dry-run Controller result на реальном observer state;
- backup текущих VWARD runtime files;
- отдельный план отката.

Только после этой проверки можно провести одну контролируемую live mutation с немедленной post-check приёмкой. До этого `execution_enabled` остаётся `0`, Controller не входит в cron, а legacy recovery остаётся production path.
