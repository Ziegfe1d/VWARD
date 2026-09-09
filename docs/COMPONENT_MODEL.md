# VWARD component model

VWARD Platform is one product composed of independently updateable logical
components. Component IDs are stable machine names used by signed manifests,
package metadata, logs and future UI/API output. Display names always use the
`VWARD` prefix.

| Component ID | Display name | Responsibility |
|---|---|---|
| `platform-core` | VWARD Platform Core | Platform release marker and shared platform metadata |
| `route-engine` | VWARD Route Engine | Live DNS-driven adaptive routing |
| `route-reconciler` | VWARD Route Reconciler | Hysteresis-based DIRECT recovery and route cleanup |
| `route-tools` | VWARD Route Tools | Routing probes, resolution, hints and one-shot route operations |
| `tunnel-guard` | VWARD Tunnel Guard | WireGuard health and fail-open protection |
| `wan-guard` | VWARD WAN Guard | WAN diagnosis and bounded recovery |
| `policy-sync` | VWARD Policy Sync | VPN policy audit, reconciliation and subnet synchronization |
| `runtime` | VWARD Runtime | Init scripts, cron supervision and housekeeping |
| `console` | VWARD Console | Web interface, CGI API and lighttpd configuration |
| `update-engine` | VWARD Update Engine | Signed update transactions and deterministic rollback |

The authoritative machine-readable mapping is
`config/components/component-registry.json`.

## Compatibility rules

- Existing runtime filenames, init names, cron commands and filesystem paths do
  not change during the naming migration.
- `legacy_ids` are accepted only for already published manifests, historical
  state and migration tooling. New packages use canonical component IDs.
- A runtime target belongs to exactly one canonical component.
- Device-local configuration, persistent state, logs, backups and secrets do
  not belong to update payloads.
- `update-engine` uses the verified slot installer. It is not a normal
  self-replacing signed-package target.

## Version policy

The platform keeps one SemVer release number in `VERSION`. Ordinary components
inherit the platform release that last changed them; unchanged components are
not rewritten merely to synchronize a displayed version. The updater records
the installed release, update ID, sequence and hashes of files it actually
replaces.

Independent component version numbers are not introduced at this stage. If a
future compatibility boundary requires one, it must be added as a registry
schema change rather than embedded ad hoc in shell scripts.

## Selective update policy

A signed package contains only files that need to change. Its
`affected_components` list names their canonical components, while every
package file entry carries the matching component ID. Backup, atomic replace,
health verification and rollback operate only on those declared files.

Component-specific health profiles are reserved in the registry but remain a
separate production acceptance gate. Smart Updater 1.1 implements the named
profiles; publishing uses `default` until the relevant profile has passed on
the router.

Smart Updater 1.1 enforces registry ownership before installation. The
canonicalized component set in the signed feed must exactly equal the component
set in the package. A package cannot write another component's target or carry
undeclared payload files.

Component installation state is stored separately from platform-wide committed
state. One release can therefore update only one component while preserving one
platform SemVer and a complete rollback transaction.
