# Карта установки

Логическое владение задаёт `config/components/component-registry.json`. Старые имена
каталогов и runtime-файлов сохранены для совместимости. Режимы подтверждены исходным
snapshot и package metadata.

| Исходник | Runtime-цель | Mode |
|---|---|---:|
| `components/adaptive-routing/scripts/adaptive-2ip-test.sh` | `/opt/bin/adaptive-2ip-test.sh` | 0755 |
| `components/adaptive-routing/scripts/adaptive-auto-maint.sh` | `/opt/bin/adaptive-auto-maint.sh` | 0755 |
| `components/adaptive-routing/scripts/adaptive-hints-update.sh` | `/opt/bin/adaptive-hints-update.sh` | 0755 |
| `components/adaptive-routing/scripts/adaptive-housekeeping.sh` | `/opt/bin/adaptive-housekeeping.sh` | 0755 |
| `components/adaptive-routing/scripts/adaptive-resolve4.sh` | `/opt/bin/adaptive-resolve4.sh` | 0755 |
| `components/adaptive-routing/scripts/adaptive-route.sh` | `/opt/bin/adaptive-route.sh` | 0755 |
| `components/adaptive-routing/scripts/agh-adaptive-live.sh` | `/opt/bin/agh-adaptive-live.sh` | 0755 |
| `components/adaptive-routing/scripts/agh-adaptive-route.sh` | `/opt/bin/agh-adaptive-route.sh` | 0755 |
| `components/vpn-audit/scripts/*.sh` | `/opt/bin/<то же имя>` | 0755 |
| `components/wireguard-protection/scripts/*.sh` | `/opt/bin/<то же имя>` | 0755 |
| `components/wan-guardian/scripts/*.sh` | `/opt/bin/<то же имя>` | 0755 |
| `components/runtime-supervision/scripts/crond-supervisor.sh` | `/opt/bin/crond-supervisor.sh` | 0755 |
| `components/runtime-supervision/scripts/vward-discovery.sh` | `/opt/bin/vward-discovery.sh` | 0755 |
| `components/runtime-supervision/init.d/*` | `/opt/etc/init.d/<то же имя>` | 0755 |
| `web/lighttpd.conf` | `/opt/etc/keenetic-apps/lighttpd.conf` | 0644 |
| `web/index.html` | `/opt/share/keenetic-apps/www/index.html` | 0644 |
| `web/cgi-bin/api.cgi` | `/opt/share/keenetic-apps/www/cgi-bin/api.cgi` | 0755 |
| `config/adaptive-route/*.conf.example` | начальный local config без `.example` | 0644 |
| `config/cron/root.crontab` | VWARD entries в root crontab | 0600 |

## WAN Guard runtime

`components/wan-guardian/scripts/wan-health-watch.sh` устанавливается как
`/opt/bin/wan-health-watch.sh` и принадлежит компоненту `wan-guard`. Он создаёт только
runtime state/log:

- `/opt/var/lib/wan-health/state`;
- `/opt/var/log/wan-health.log`;
- `/tmp/wan-health-watch.*` для lock и cron status.

Эти runtime-файлы не являются source и не должны входить в update package как
предзаполненные данные.

`wan-health-watch.sh` и legacy `wan-guardian.sh` запускаются отдельными cron entries.
Первый является read-only observer, второй пока остаётся recovery path.

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
| `wg-failopen.disabled` | local control state | не заменять из Git |
| `/opt/var/lib/wan-health/state` | runtime state | создать observer, не включать в package |
| `/opt/var/log/wan-health.log` | runtime log | создать observer, не включать в package |

## Device-specific значения

| Значение | Текущее использование | Решение |
|---|---|---|
| `192.168.1.1` | отдельные legacy DNS/web paths | обнаруживать LAN address |
| `192.168.1.0/24` | отдельные legacy DNS capture paths | обнаруживать LAN subnet |
| `eth3` | legacy WAN recovery path | observer уже использует discovered `linux_if`; recovery перевести отдельно |
| `ISP` | legacy WAN recovery path | observer уже использует роль `wan-guard`; recovery перевести отдельно |
| `nwg1` | legacy tunnel/policy paths | сопоставлять с выбранным VPN |
| `Wireguard0/1` | legacy RCI/ndmc paths | выбирать discovered interfaces |
| `domain-list22` | local FQDN policy | запрашивать/настраивать |
| `AdaptiveAuto` | managed group | VWARD default с проверкой конфликта |
