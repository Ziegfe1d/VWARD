# VWARD Domain Classifier — dev.8 foundation

This module belongs to **VWARD Route Engine**. It is not a separate top-level product and does not change the Ads & Privacy Guard ownership boundary.

## Included in this candidate

- deterministic `host -> category | confidence | reason | source` classification;
- exact catalog match (`100`) and safe known-suffix inheritance (`95`);
- categories: X / Twitter, 4PDA, Steam, Epic Games and 18+;
- declarative category-to-Keenetic-group registry with `AUTO` unresolved state;
- permanent category catalogs independent from active VPN membership;
- atomic, threshold-gated, duplicate-safe catalog writes;
- root-owned validated configuration with bounded threshold/batch values;
- shared classifier lock for catalog mutation and stale-lock recovery;
- strict route-safe FQDN validation before persistent catalog writes;
- bounded stdin batch mode;
- conflict and unknown handling;
- migration dry-run showing the required add/verify/remove order;
- explicit retention of AdaptiveAuto when classification or target resolution is incomplete.

The 18+ catalog is intentionally empty. It may be populated only from reviewed category sources or explicit local confirmation. ASN/IP alone never establishes a category.

## Safety state

`MIGRATION_MODE=dry-run` is mandatory for this candidate. No script here changes a Keenetic object-group, WireGuard, firewall, DNS, AdaptiveAuto or system configuration.

The runtime reads `/opt/etc/vward/route-engine/domain-classifier.conf` only when it
is root-owned and mode `0600` or `0400`. The candidate rejects live migration modes.

`target_group=AUTO` means that the logical category is known but the current Keenetic object-group has not yet been resolved from the authoritative registry. In this state classification and catalog knowledge may continue, while route mutation is prohibited.

## Intended install mapping

| Candidate path | Proposed target |
|---|---|
| `components/route-engine/lib/vward-domain-classifier-lib.sh` | `/opt/lib/vward/vward-domain-classifier-lib.sh` |
| `components/route-engine/scripts/vward-domain-classifier.sh` | `/opt/bin/vward-domain-classifier.sh` |
| `components/route-engine/scripts/vward-domain-migrate-dry-run.sh` | `/opt/bin/vward-domain-migrate-dry-run.sh` |
| `config/route-engine/categories.tsv.example` | `/opt/etc/vward/route-engine/categories.tsv` |
| `config/route-engine/domain-classifier.conf.example` | merge into Route Engine configuration |
| `components/route-engine/data/catalogs/*.domains` | seed `/opt/etc/vward/route-engine/catalogs/` without overwriting learned data |

## Deferred until router acceptance

- discovery of actual logical category -> Keenetic group mappings;
- external category source registry/updater and trust scoring;
- CNAME and ASN/IP secondary evidence;
- integration into `adaptive-auto-maint.sh`;
- transactional live migration and rollback;
- night reconcile integration;
- read-only Console view.

Live migration must be implemented only after a router snapshot confirms the current production command grammar, AdaptiveAuto state format, lock owner and save/rollback path.
