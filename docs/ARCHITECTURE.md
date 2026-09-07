# Architecture

VWARD is a set of cooperating POSIX shell services and a small lighttpd/CGI web interface for KeeneticOS with Entware.

## Source versus runtime

The repository contains program source, init scripts, configuration examples and the managed cron schedule. An installed system separates:

- `/opt/bin` and service definitions — installed program files;
- `/opt/etc` — device-local configuration;
- `/opt/var/lib` — persistent runtime state;
- `/opt/var/log` — logs;
- `/opt/var/backups` — local backups;
- `/tmp` — transient locks, probes and cron status.

Future source updates must preserve local configuration and state.

## Components

### Adaptive routing

The adaptive scripts inspect Keenetic FQDN groups and DNS activity, probe direct ISP and WireGuard paths, and maintain the `AdaptiveAuto` group. `agh-adaptive-live.sh` observes DNS traffic; `adaptive-auto-maint.sh` rechecks previously adapted domains.

### VPN audit and reconciliation

The audit chain reads the live Keenetic configuration through `ndmc`, tests routing targets, records state and reconciles domains or subnets routed through `Wireguard1`.

### WireGuard protection

`wg-health-watch.sh` records health. `wg-failopen-guard.sh` uses that state to protect connectivity and can alter `Wireguard1` state.

### WAN recovery

`wan-guardian.sh` performs staged checks and recovery against the `ISP` interface and physical WAN device. `wan-recovery-actuator.sh` is the narrow DHCP-renew actuator.

### Runtime supervision

Entware init scripts control crond, the adaptive live process, its supervisor and the web service. The managed cron schedule invokes periodic jobs and writes transient status into `/tmp`.

### Web UI

lighttpd serves `web/index.html`; `web/cgi-bin/api.cgi` reports local status using `jq`, RCI endpoints and runtime files.

### Smart Updater v1

The disabled implementation-stage updater consumes a signed versioned feed rather than a mutable Git tree. It separates manifest checking, package staging, targeted backup, deterministic installation, health verification and rollback. Local configuration and runtime data are outside its target allow-list. No installer, production signing key or router deployment is included.

## Current maturity

The router snapshot proves the imported runtime components are in active use on the source device. Portability, installation and automated configuration discovery remain development work. Smart Updater v1 has code and isolated simulations, but production barrier integration and device validation remain outstanding.
