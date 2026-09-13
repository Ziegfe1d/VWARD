# Карта установки

Логическое владение задаёт `config/components/component-registry.json`. Runtime
использует только канонические имена VWARD. Режимы подтверждены source и package
metadata.

| Исходник | Runtime-цель | Mode |
|---|---|---:|
| `components/route-tools/scripts/vward-route-test.sh` | `/opt/bin/vward-route-test.sh` | 0755 |
| `components/route-reconciler/scripts/vward-route-reconciler.sh` | `/opt/bin/vward-route-reconciler.sh` | 0755 |
| `components/route-tools/scripts/vward-route-hints-update.sh` | `/opt/bin/vward-route-hints-update.sh` | 0755 |
| `components/runtime/scripts/vward-housekeeping.sh` | `/opt/bin/vward-housekeeping.sh` | 0755 |
| `components/route-tools/scripts/vward-route-resolve4.sh` | `/opt/bin/vward-route-resolve4.sh` | 0755 |
| `components/route-tools/scripts/vward-route.sh` | `/opt/bin/vward-route.sh` | 0755 |
| `components/route-engine/scripts/vward-route-engine.sh` | `/opt/bin/vward-route-engine.sh` | 0755 |
| `components/route-tools/scripts/vward-route-discovery.sh` | `/opt/bin/vward-route-discovery.sh` | 0755 |
| `components/policy-sync/scripts/*.sh` | `/opt/bin/<то же имя>` | 0755 |
| `components/tunnel-guard/scripts/*.sh` | `/opt/bin/<то же имя>` | 0755 |
| `components/wan-guard/scripts/*.sh` | `/opt/bin/<то же имя>` | 0755 |
| `components/runtime/scripts/vward-cron-supervisor.sh` | `/opt/bin/vward-cron-supervisor.sh` | 0755 |
| `components/runtime/lib/vward-device-profile.sh` | `/opt/lib/vward/vward-device-profile.sh` | 0755 |
| `components/runtime/init.d/*` | `/opt/etc/init.d/<то же имя>` | 0755 |
| `web/lighttpd.conf` | `/opt/etc/vward/console/lighttpd.conf` | 0644 |
| `web/index.html` | `/opt/share/vward/console/www/index.html` | 0644 |
| `web/cgi-bin/api.cgi` | `/opt/share/vward/console/www/cgi-bin/api.cgi` | 0755 |
| `config/route-engine/*.conf.example` | начальный local config без `.example` | 0644 |
| `config/cron/root.crontab` | VWARD entries в root crontab | 0600 |
| `config/device.conf.example` | `/opt/etc/vward/device.conf` при неоднозначном discovery | 0600 |

## Bootstrap Update Engine

Update Engine развёрнут после исходного snapshot. Bootstrap устанавливает VERSION,
public key, config и updater slot отдельно. После первого committed update
`/opt/var/lib/vward/updater/committed.state` - authoritative transaction state.
Targets берутся только из подписанного package manifest и allowlist.

## Не является source

| Файл | Класс | Политика |
|---|---|---|
| `hints.conf` | generated | создать скриптом, не публиковать |
| `skip-domains.conf` | local config | сохранять, не включать в package |
| `tunnel-guard.disabled` | local control state | не заменять из Git |

## Device Profile

`components/runtime/lib/vward-device-profile.sh` загружает единый профиль и
обнаруживает только однозначные WAN/LAN/tunnel candidates. Логическое имя WAN и
policy group задаются явно, когда их нельзя достоверно вывести из системы.
