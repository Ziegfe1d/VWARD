# VWARD Ads & Privacy Guard

Component ID: `ads-privacy-guard`

Назначение: обнаруживать рекламные/трекерные домены, которые прошли текущую
фильтрацию AdGuard Home, и формировать отдельный управляемый VWARD block set с
консервативным evidence policy.

## Runtime targets

- `/opt/bin/vward-ads-privacy-guard.sh`
- `/opt/bin/vward-ads-privacy-sources-update.sh`
- `/opt/bin/vward-ads-privacy-publish.sh`
- `/opt/bin/vward-ads-privacy-probe.sh`
- `/opt/bin/vward-ads-privacy-control.sh`
- `/opt/bin/vward-ads-privacy-health.sh`
- `/opt/share/vward/ads-privacy-guard/vward-ads-privacy-common.sh`
- `/opt/share/vward/ads-privacy-guard/source-registry.json`
- `/opt/share/vward/ads-privacy-guard/trust-core.tsv`

## Local config/state

Local config (preserved across updates):

- `/opt/etc/vward/ads-privacy-guard/ads-privacy-guard.conf`
- `/opt/etc/vward/ads-privacy-guard/allowlist.tsv`
- `/opt/etc/vward/ads-privacy-guard/denylist.tsv`

Persistent state:

- `/opt/var/lib/vward/ads-privacy-guard/sources/*.domains`
- `/opt/var/lib/vward/ads-privacy-guard/verdicts.tsv`
- `/opt/var/lib/vward/ads-privacy-guard/review.tsv`
- `/opt/var/lib/vward/ads-privacy-guard/generated/vward-ads-privacy-guard.rules`

Logs/backups:

- `/opt/var/log/vward-ads-privacy-guard.log`
- `/opt/var/backups/vward/ads-privacy-guard/`

## State format

`verdicts.tsv`:

```text
domain|verdict|action|confidence|first_seen|last_seen|next_check_epoch|reason|evidence
```

`verdict`:

- `BLOCK`
- `SUSPECT`
- `ALLOW`
- `TRUST`

`action`:

- `BLOCK` - домен находится в генерируемом filter set;
- `NONE` - блокировка не применяется.

Разделение verdict/action позволяет оставить ранее заблокированный домен в блоке,
если его evidence исчезло и требуется повторная проверка.

## Candidate v6 runtime control

Additional scripts:

- `vward-ads-privacy-scheduler.sh` - single lightweight owner for manual/scheduled/dynamic timing and source refresh;
- `vward-ads-privacy-settings.sh` - validated Console-safe settings transaction;
- `vward-ads-privacy-control.sh pause|resume|status` - persistent pause and runtime visibility.

The active VWARD cron calls only the scheduler once per minute. In dynamic mode the classifier
runs only when the persisted AGH query log changed and resource gates pass. This is
intentional to keep CPU/I/O low on router-class hardware.

### DNS of every device through AdGuard Home

`vward-ads-privacy-dns-guard.sh` (off by default, switches on the Ads page):
- `enforce`: every DNS query from the LAN subnet on port 53, to any server, is
  DNAT-ed to AdGuard Home's DNS address (`dns.port` of AdGuardHome.yaml); queries to
  the router itself go on to the rules already there. Chain `VWARD_DNS` (nat).
- `bypass`: DoT/DoQ (853) refused from the LAN, 443 refused to well-known DoH
  addresses, HaGeZi's Encrypted DNS list added to (or switched off in) AdGuard Home.
  Chain `VWARD_DNS_FWD` (filter, FORWARD). REJECT, DROP where the kernel has no REJECT.
- exclusions by MAC, mapped to current addresses through RCI; when Keenetic does not
  answer the rules are left as they are, so an excluded device is never redirected.
- nothing can be switched on while an upstream of AdGuard Home is plain DNS
  (Smart DNS rows `[/domain/]...` aside): every device would then be read by the ISP.
- fail-safe: while AdGuard Home's DNS port is closed the redirect is taken off.
- `/opt/etc/ndm/netfilter.d/060-vward-dns-guard.sh` puts the rules back when
  Keenetic rebuilds its firewall; the scheduler reconciles every minute (no process
  when the guard is off).

### Routed domains through Keenetic's DNS

Keenetic routes a domain (`object-group fqdn` with a `route`) by the addresses it
learns from DNS answers passing through its own DNS. Devices that ask AdGuard Home
directly (the redirect of LAN port 53 to AdGuard Home, or the DNS guard) bypass it,
so Keenetic misses subdomains and rotating CDN addresses and such traffic leaves
outside the route. `vward-ads-privacy-route-dns.sh` (on by default, switch on the
Ads page) closes that gap:
- AdGuard Home gets one row `[/a.com/b.com/]LAN:53` with the domains of every routed
  Keenetic group: those queries go on to Keenetic's DNS, which learns the addresses
  before the device connects; devices keep their names and filtering in AdGuard Home;
- Keenetic's DNS asks AdGuard Home back as the client `Keenetic DNS (VWARD)`
  (ids: LAN address, 127.0.0.1) with AdGuard Home's servers minus that row, so there
  is no loop. The client is written first and the chain is tested
  (`test_upstream_dns`) before the row; on the way out the row goes first;
- only while Keenetic's DNS asks AdGuard Home (`ip name-server LAN:port`);
- a domain with its own row in AdGuard Home (Smart DNS) is left to that row;
- another client holding the router's address: nothing is written;
- the scheduler checks every 5 minutes (nothing while off and cleaned up). Switch:
  `route-dns.disabled` in the config directory; status in `/tmp/vward-route-dns.status`.

### Device names in AdGuard Home

`vward-ads-privacy-clients.sh` names in AdGuard Home the devices Keenetic has
registered and sees online (RCI `show/ip/hotspot`), through the clients API
(`/control/clients/add|update`): no restart, no DNS gap. A client is matched
by MAC, else by an IP-only entry; its name and address follow Keenetic, its
other ids and settings stay. An address that moved to another device is taken
from the old client first. Nothing is deleted. The scheduler calls it every
minute; with the same devices it makes no AdGuard Home call (a full pass once
an hour). It stays idle while `agh-keenetic-clients-sync.sh` (the old script
that rewrites AdGuardHome.yaml with a restart) is in root's crontab. Switch:
`clients-sync.disabled` in the config directory; status in
`/tmp/vward-ads-clients.status`.


## Optional HTTPS Content Guard

Candidate v6 includes `vward-ads-privacy-https.sh` and a provider adapter for 3proxy
SSLPlugin/PCREPlugin. The HTTPS branch is OFF by default, explicit-proxy only, uses a
local CA and generated PAC, and never changes iptables/NAT. Local HTTPS config and CA
material live under `/opt/etc/vward/ads-privacy-guard/https` and are preserved across
updates. See `docs/HTTPS_CONTENT_GUARD.md`.
