# VWARD WAN Guard

VWARD WAN Guard разделён на read-only наблюдение и recovery path.

`wan-health-watch.sh` - новый read-only observer. Он получает роль `wan-guard` из
`VWARD Discovery`, использует фактический `rci_id` и `linux_if`, учитывает `via` для
PPPoE/логических uplink и выполняет только диагностические проверки. При
неоднозначном или неразрешённом mapping он работает fail-safe и не запускает
непривязанные сетевые probes.

`wan-guardian.sh` пока остаётся legacy recovery path рабочего роутера. Его команды
восстановления и текущая модель `ISP`/`eth3` этим этапом не меняются.

`wan-recovery-actuator.sh` остаётся отдельным dry-run actuator и также не изменяется.

Следующий этап после приёмки observer: перевести Console на его health-state, затем
отдельно спроектировать type-aware recovery по discovered WAN role. До этого observer
не должен инициировать `ndmc`, DHCP renew, down/up или другие network mutation.
