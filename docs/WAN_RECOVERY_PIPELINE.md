# VWARD WAN Recovery Pipeline

Этот документ является authoritative описанием новой Discovery-driven цепочки восстановления WAN в Beta `0.2.x`.

## Статус

Текущая цепочка полностью собрана и протестирована в режиме `dryrun`:

`Discovery -> Observer -> Capability -> Planner -> Controller -> Actuator`

Новые Planner, Controller и Actuator не выполняют сетевых mutation и не запускаются из cron. Фактический рабочий recovery на роутере пока остаётся в legacy `wan-guardian.sh` до отдельной приёмки mutating path.

## 1. Discovery

`vward-discovery.sh wan-guard` определяет выбранный WAN по фактическому RCI state и role mapping. Код не предполагает имена `ISP`, `eth3` или любую конкретную нумерацию интерфейсов.

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

`wan-recovery-plan.sh` работает только в `MODE=dryrun` и всегда возвращает `EXECUTED=NO`.

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
- `DHCP_RENEW` только для физического `ADDRESS_FAILURE`, когда Capability Provider повторно подтверждает `addressing.mode=dhcp` и `dhcp_renew=true`.

`PHY_DOWN`, DNS-only failure, stale/ambiguous/mismatched state и неизвестная addressing capability не дают права на mutation.

## 5. Recovery Controller

`wan-recovery-controller.sh` является единственным новым Execution Gate.

Сейчас Controller также работает только в `MODE=dryrun` и всегда возвращает `EXECUTED=NO`.

Controller:
- создаёт `/tmp/wan-recovery-controller.lock`;
- запускает Planner;
- не вызывает Actuator для `HOLD`, `DEFER` или `BLOCKED`;
- принимает только `DECISION=PLAN`;
- разрешает только известные typed actions;
- передаёт в Actuator action + ожидаемые RCI/Linux IDs, а не shell-команду;
- проверяет ответ Actuator;
- блокирует несоответствие action, target, execution kind или execution guard.

Controller не содержит `ndmc`, `eval`, готовых recovery commands или installation-specific target.

## 6. Recovery Actuator

`wan-recovery-actuator.sh` является единственным местом, где в будущем могут появиться реальные WAN mutation. Сейчас mutation в нём отсутствуют.

Actuator повторно проверяет актуальный `wan-guard` непосредственно перед готовностью к операции. Для DHCP он повторно вызывает Capability Provider.

Текущие execution kinds:
- `RCI_SESSION_RECONNECT`;
- `RCI_INTERFACE_RECONNECT`;
- `RCI_DHCP_RENEW`.

Это только тип будущей операции. При текущем Beta state результат остаётся `EXECUTED=NO`.

Actuator не принимает произвольный command text, не использует `eval` и не строит имя интерфейса из номера или шаблона.

## 7. TOCTOU protection

Role/capability перепроверяются после Planner и до будущей mutation.

Regression tests проверяют минимум два изменения между PLAN и ACT:
- WAN role изменилась -> Actuator возвращает `BLOCKED`;
- DHCP capability изменилась на static -> `DHCP_RENEW` возвращает `BLOCKED`.

Таким образом, решение Planner не является бессрочным разрешением на действие.

## 8. Update Engine integration

Все новые WAN runtime files зарегистрированы как targets компонента `wan-guard` и разрешены Update Engine.

`vward-update-runtime-policy.sh` содержит актуальный target allowlist и учитывает WAN observer/controller locks при quiescing.

Health profile `wan-guard` требует полный runtime stack, включая Discovery-driven observer, Capability Provider, Planner, Actuator и Controller.

## 9. Что пока запрещено

До отдельной Beta acceptance запрещено:
- включать Controller/Planner/Actuator в cron;
- выполнять `ndmc` из новых Planner/Controller;
- выполнять recovery mutation из Controller;
- автоматически заменять legacy `wan-guardian.sh`;
- считать dry-run acceptance доказательством безопасной mutation на реальном роутере.

## 10. Следующий этап

Перед включением реальных действий необходимо отдельно принять exact operation для каждого action:
- `DHCP_RENEW`;
- `INTERFACE_RECONNECT`;
- `SESSION_RECONNECT`.

Затем в Controller/Actuator добавить:
- явный execution enable switch с default `off`;
- cooldown;
- rate limit / max recoveries per window;
- повторный pre-check непосредственно перед mutation;
- post-check через новый observer cycle;
- persistent recovery state и audit log;
- безопасное поведение при неуспешном post-check;
- блокировку при конфликте с VWARD Update Engine и другими mutating components.

Реальные mutation разрешаются только после отдельной приёмки на целевом Keenetic. До этого legacy recovery остаётся рабочим production path.
