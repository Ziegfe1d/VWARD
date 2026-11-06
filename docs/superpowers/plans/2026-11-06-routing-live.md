# Unified routing live wiring and dev candidate implementation plan

> **For agentic workers:** Use superpowers:executing-plans, one implementer. An independent addressed reviewer checks risky wiring/ownership/recovery/package deltas; no parallel implementation or repeat B audit.

**Goal:** Complete and publish the functioning unified routing chain in dev, with owner installation/hardware acceptance separate.

**Architecture:** Reuse the accepted RS7 F/G readers, canonical choices/policy, typed lowering and J2 coordinator. Add a fixed installed live adapter for real native/AGH completion and guarded metadata publication; preserve the DATA backend as the independent fixture backend. Fence every overlapping old writer before enabling real entry points, then route API/CLI decisions through one coordinator.

**Tech Stack:** POSIX sh/BusyBox ash+awk, existing jq/API/Panel JS, NDMC and supported AGH API; existing signed updater/workflow. No new daemon/backend.

**Spec:** RS7_EXECUTOR_WIRING_DESIGN.md F/G/G.5, ROUTING_AUDIT_CONTRACT.md, ROADMAP §7 owner GO 06.11.2026 (`VWARD_PR38_GO_Complete_And_Release_DEV_2026-11-06.md`). The explicit GO authorizes all stages/PR/dev publication without new approval. The accepted design and single-implementer method are preserved.

## Global constraints

- Start from code168a853 + docs e8f6b11; CI813 SUCCESS is baseline, never rerun merely for startup.
- Keep PR38/work/unified-routing-20261104; preserve foreign progress. No router connection/change/install/reboot, no main/stable.
- Agents Observation; existing protected manual/NextDNS/Google8/DNS16/removed SmartDNS unchanged. No owner secrets/raw outputs/private backups in repo.
- Every scope retains ownership/content/attributes CAS, old/new writer fences, admission→EDIT→CHANGE→J2, persistent unknown and no blind replay/inverse.
- One, two and three discovered supported VPNs; auto/default and explicit pin. No hardcoded tunnel or count; no second hardware tunnel for tests.
- Full reversible VPN/DNS/ISP/Auto, source8/transitions24, both supported stores/capacity8/server lifecycle; off removes S contribution, never implies ISP or erases independent M/A/DNS intent.
- Legacy migration observes first; unknown/foreign objects protected. No automatic route/mode/component change on install. Downgrade must retain pending and byte-exact verified baseline.
- Final candidate installs needed libs and working API/UI/actions; never publish activation-off/noendpoint as completion.
- One full exact-HEAD CI after connected package: consistency/updater+rehearsal+rollback/resource+stress+Chromium/signed-target checks; new correction after FAIL needs its own final CI.
- Dev publish only after addressed review closure/green exact gates/verified rollback; production key only in workflow. Public manifest/signature/package SHA/version/sequence verification precedes “released”.

## Review focus

1. Old restore/persist/reconciler/guard races with new owner pin: scoped gate before every overlapping physical/local write, including file-only/AGH and updater.
2. Parent-only death during real NDMC/HTTP: actual publisher lease/completion, persistent unknown, no matching-image ownership and no early lock release/replay.
3. Mixed/manual/excluded groups, sibling sources and shared URL/CDN: exact preview/authority and preserve unrelated members/upstreams/claims.
4. Missing selected tunnel or expired server: honest refusal/unknown, no silent provider fallback; deletion never probes withdrawn server.
5. Installed upgrade/downgrade with pending/tombstones: no loss of config/recovery/floor, no implicit activation or resurrection.

## Task 1 — owner decision and all legacy admission fences

**Files:** ROADMAP§7/AGENT§2/3/4/RS7G.5; new `components/runtime/lib/vward-routing-admission.sh`; existing console/profile/route-engine/reconciler/policy/guard/AGH control and updater boundary functions; `tests/routing-readers/check-live-admission.py`.
**Interfaces:** `vward_routing_legacy_command_gate STAGE JDIR COMMAND` returns0 only unmanaged/read-only,75 for managed handoff/pending/unknown. Production loader binds installed fixed state/native snapshot and calls the gate under existing locks. Broad/unknown routing mutation is never inferred safe; ordinary diagnostics remain readable.
- [x] Persist explicit GO and verify existing worktree/base; no repeated baseline CI.
- [ ] RED→GREEN actual canonical pin + legacy command scopes (group AND include domain, route, delete, DNS, save), unrelated/read-only, malformed data, persistent unknown and side-effect-free refusal.
- [ ] Wire all intersecting physical and local legacy writes plus updater pending/publisher quiescence; map each caller to a regression. No real new writer enabled before this matrix passes.
- [ ] Targeted shell/BusyBox/races/mode checks; coherent commit, no full CI yet.

## Task 2 — real transport/coordinator/bootstrap and VPN entry points

**Files:** new fixed live loader/adapter under runtime/lib, existing pipeline/dispatch/workers/state/journal/legacy; console service/AI entry points; real-entry transport fixture.
**Interfaces:** live coordinator consumes validated action/SID/mode/target/DNS/revision, produces canonical common outcome. Real transport commands are closed compiled worker actions; native/AGH requests have actual publisher PID/start/BOOT lease, completion result and fresh readback before J2 finish/save. No environment/API executable selector or nested console CLI. Metadata targets are a closed mapping to authoritative installed files.
- [ ] RED real API/CLI request does not reach coordinator; implement fixed binding without changing DATA-only behavior of old tests.
- [ ] Bootstrap/import actual installed inputs into versioned decision set, preserving observations/history and archive; route proof requires actual private witness.
- [ ] One/2/3 VPN on/off/pin/default/A→B→C→A/repeat/new domain/disappeared target; actual route+registration+claim/readback/save and owner-only inverse.
- [ ] TERM/SIGKILL/late native child/save/foreign edit/admission tests; independent addressed review of transport/fences/ownership.

## Task 3 — full sources, reversible modes and DNS server lifecycle

**Files:** actual M/list/category/S/Auto callers and source state; DNS/lifecycle/shared coordinator; existing console+AGH locked helpers.
**Interfaces:** list/service/Auto and category actions submit typed decision deltas to the same coordinator; accepted pins outrank old history/probe; live server replace/delete uses opaque URI identity and both stores, saved/proofs/queue/persist withdrawal.
- [ ] RED→GREEN all8 M/S/A combinations/24 transitions through real entry points, sources independent, restart/persist/new confirmed domains, off != ISP.
- [ ] VPN↔DNS↔ISP↔Auto both Keenetic/AGH, global8/shared URL/upstream file/store auto+manual; unavailable backend reason, no new dnsmasq/backend.
- [ ] Server delete/replace exact own dependents and monotonic withdrawals, no old subscription probe; readback/rollback/unknown POST persistent evidence.
- [ ] Conflict/reference/excludes/CNAME/IPv6/shared CDN coverage and exact confirmation in ordinary action; no whole mixed-group adoption/deletion.

## Task 4 — installed package, common API/UI, migration/downgrade, connected acceptance

**Files:** package-map/signed allowlists exact necessary targets, installer/updater migration bridge; API common outcome and existing pages/actions; targeted fixture matrix.
- [ ] Register/install necessary libs and bind actual actions; installed/package fixture proves reachable live coordinator and excludes test executables/overrides.
- [ ] API/Panel selected/configured/client-verified/source/coverage projection on all related pages, finite outcomes/partial batch, no success before readback; retain VPN selector/store selector/mobile and existing functionality.
- [ ] Upgrade/downgrade/disable preserves settings/pending/tombstones, explicit own CAS rollback and baseline save; installer never silently changes native routes or modes.
- [ ] Connected fault matrix at significant steps: old/new concurrency, local write/save, unknown HTTP, parent-only kill/reboot, no unrelated probes/writes; reuse accepted fixtures.
- [ ] Addressed independent review wiring/locks/ownership/recovery/migration/package; close Important/Critical with RED→GREEN, no new general audit.

## Task 5 — final software gates, rollback and dev publication

- [ ] Fresh base/version/sequence/complete scope; CHANGELOG/ROADMAP/AGENT accurately distinguish software and hardware. No promised release number before this check.
- [ ] One mandatory exact final code CI, no successful same-tree reruns; one scheduled follow-up if running, no polling. Resolve specific failures under existing authorization.
- [ ] Signed previous dev package/public-key verification + realistic candidate rollback/rehearsal full health/foreign files/byte baseline; retain previous artifact for owner.
- [ ] Merge expected head into dev after gates, verify merged runtime tree; standard dev release workflow/private signing inside workflow only, no docs push during its feed push.
- [ ] Verify actual public feeds/package/production signature/SHA/version/sequence/targets/v2 blobs; dispatch is not publication. Append factual SHA/run/results and final PR report.
- [ ] One owner-run Termius command (backup, standard signed updater/pending, timeout only safe reads/downloads, full standard output/abort). One actual VPN hardware checklist and return/manual preservation; multi-VPN hardware only when available.
