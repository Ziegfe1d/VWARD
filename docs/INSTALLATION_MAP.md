# Installation map

This map is derived from the verified 2026-09-06 router snapshot. Modes are the observed runtime modes.

| Repository source | Runtime destination | Mode |
|---|---|---:|
| `components/adaptive-routing/scripts/adaptive-2ip-test.sh` | `/opt/bin/adaptive-2ip-test.sh` | 0755 |
| `components/adaptive-routing/scripts/adaptive-auto-maint.sh` | `/opt/bin/adaptive-auto-maint.sh` | 0755 |
| `components/adaptive-routing/scripts/adaptive-hints-update.sh` | `/opt/bin/adaptive-hints-update.sh` | 0755 |
| `components/adaptive-routing/scripts/adaptive-housekeeping.sh` | `/opt/bin/adaptive-housekeeping.sh` | 0755 |
| `components/adaptive-routing/scripts/adaptive-resolve4.sh` | `/opt/bin/adaptive-resolve4.sh` | 0755 |
| `components/adaptive-routing/scripts/adaptive-route.sh` | `/opt/bin/adaptive-route.sh` | 0755 |
| `components/adaptive-routing/scripts/agh-adaptive-live.sh` | `/opt/bin/agh-adaptive-live.sh` | 0755 |
| `components/adaptive-routing/scripts/agh-adaptive-route.sh` | `/opt/bin/agh-adaptive-route.sh` | 0755 |
| `components/vpn-audit/scripts/vpn-domain-audit-chain.sh` | `/opt/bin/vpn-domain-audit-chain.sh` | 0755 |
| `components/vpn-audit/scripts/vpn-domain-audit.sh` | `/opt/bin/vpn-domain-audit.sh` | 0755 |
| `components/vpn-audit/scripts/vpn-night-reconcile.sh` | `/opt/bin/vpn-night-reconcile.sh` | 0755 |
| `components/vpn-audit/scripts/vpn-subnet-sync.sh` | `/opt/bin/vpn-subnet-sync.sh` | 0755 |
| `components/wireguard-protection/scripts/wg-health-watch.sh` | `/opt/bin/wg-health-watch.sh` | 0755 |
| `components/wireguard-protection/scripts/wg-failopen-guard.sh` | `/opt/bin/wg-failopen-guard.sh` | 0755 |
| `components/wan-guardian/scripts/wan-guardian.sh` | `/opt/bin/wan-guardian.sh` | 0755 |
| `components/wan-guardian/scripts/wan-recovery-actuator.sh` | `/opt/bin/wan-recovery-actuator.sh` | 0755 |
| `components/runtime-supervision/scripts/crond-supervisor.sh` | `/opt/bin/crond-supervisor.sh` | 0755 |
| `components/runtime-supervision/init.d/S90crond` | `/opt/etc/init.d/S90crond` | 0755 |
| `components/runtime-supervision/init.d/S91adaptive-live` | `/opt/etc/init.d/S91adaptive-live` | 0755 |
| `components/runtime-supervision/init.d/S92crond-supervisor` | `/opt/etc/init.d/S92crond-supervisor` | 0755 |
| `components/runtime-supervision/init.d/S93keenetic-apps` | `/opt/etc/init.d/S93keenetic-apps` | 0755 |
| `web/lighttpd.conf` | `/opt/etc/keenetic-apps/lighttpd.conf` | 0644 |
| `web/index.html` | `/opt/share/keenetic-apps/www/index.html` | 0644 |
| `web/cgi-bin/api.cgi` | `/opt/share/keenetic-apps/www/cgi-bin/api.cgi` | 0755 |
| `config/adaptive-route/force-vpn.conf.example` | initial `/opt/etc/adaptive-route/force-vpn.conf` | 0644 |
| `config/adaptive-route/services.conf.example` | initial `/opt/etc/adaptive-route/services.conf` | 0644 |
| `config/cron/root.crontab` | managed entries in `/opt/var/spool/cron/crontabs/root` | 0600 observed |

## Not mapped as source

| Snapshot file | Classification | Policy |
|---|---|---|
| `/opt/etc/adaptive-route/hints.conf` | generated | Create with `adaptive-hints-update.sh`; do not track the large generated list. |
| `/opt/etc/adaptive-route/skip-domains.conf` | local configuration | Preserve on update; do not publish this device's routing policy as a universal default. |
| `/opt/etc/adaptive-route/wg-failopen.disabled` | local state/control | Snapshot records it as absent; never replace from source. |

## Device-specific values

| Value | Location/use | Decision |
|---|---|---|
| `192.168.1.1` | DNS target, web bind/fallback | Current-device default only; future installer must detect LAN/router address. |
| `192.168.1.0/24` | adaptive DNS capture filter | Configurable; future installer must derive LAN subnet. |
| `eth3` | physical/direct WAN probes | Configurable; future installer must detect the WAN device. |
| `ISP` | Keenetic interface name | Current Keenetic default, but configurable. |
| `nwg1` | curl WireGuard interface | Configurable; derive from the selected WireGuard connection. |
| `Wireguard0`, `Wireguard1` | RCI/ndmc interface names | Configurable; discover available interfaces. |
| `domain-list22` | 2IP test/service FQDN group | Local policy identifier; configurable. |
| `AdaptiveAuto` | VWARD-managed FQDN group | VWARD default, with future override support. |
