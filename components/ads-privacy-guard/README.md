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

The proposed cron calls only scheduler once per minute. In dynamic mode the classifier
runs only when the persisted AGH query log changed and resource gates pass. This is
intentional to keep CPU/I/O low on router-class hardware.


## Optional HTTPS Content Guard

Candidate v6 includes `vward-ads-privacy-https.sh` and a provider adapter for 3proxy
SSLPlugin/PCREPlugin. The HTTPS branch is OFF by default, explicit-proxy only, uses a
local CA and generated PAC, and never changes iptables/NAT. Local HTTPS config and CA
material live under `/opt/etc/vward/ads-privacy-guard/https` and are preserved across
updates. See `docs/HTTPS_CONTENT_GUARD.md`.
