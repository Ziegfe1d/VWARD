# VWARD agent instructions

## Default working mode
Work directly and finish bounded, reversible tasks end-to-end. Do not stop for approval after routine analysis, edits, or targeted verification.

These project instructions override generic process-heavy workflow skills for VWARD. Do not invoke brainstorming, writing-plans, test-driven-development, git-worktree, subagent-driven-development, code-review, or similar ceremony by default.

Use heavier process only when it is actually needed:
- planning/design: a new subsystem, cross-cutting interface, migration, or ambiguous architecture;
- systematic debugging: the root cause is not yet established;
- regression-first testing: behavior-changing logic or a reproducible bug where an automated test is practical;
- subagents/parallel work: two or more independent workstreams with clear parallel benefit;
- worktrees/review: high-risk release work, parallel conflicting edits, or explicit request.

Documentation-only, copy, CSS, small configuration, and other low-risk changes do not require artificial TDD or approval gates.

## Scope and autonomy
- Preserve existing architecture, behavior, and UI unless the task requires changing them.
- Make the smallest complete change that solves the task.
- Do not refactor unrelated code.
- Do not create permanent branches unless explicitly requested; `main` is the working branch.
- Ask only when a choice is destructive, irreversible, security-sensitive, or materially ambiguous.

## Diagnose from evidence
For runtime, routing, DNS, WireGuard, AdaptiveAuto, updater, or Keenetic problems, inspect the actual logs/state first. Distinguish DNS/AdGuard blocking, routing/VPN failure, and real endpoint unavailability before changing logic. Do not claim a fix is verified without evidence.

On the Keenetic/Entware target, prefer `/opt/bin/sh` and verify command compatibility with the actual BusyBox/Entware environment. Do not assume GNU-only options are available.

## Read documentation progressively
Do not preload all docs. Read only what the task touches:
- architecture/components: `docs/ARCHITECTURE.md`, `docs/COMPONENT_MODEL.md`;
- console/web: `docs/CONSOLE.md`;
- updater/update flow: `docs/UPDATER_ARCHITECTURE.md` plus only the relevant `docs/UPDATE_*.md`;
- installation: `docs/INSTALL.md`, `docs/INSTALLATION_MAP.md`;
- release/publishing: `docs/PUBLISHING_CHECKLIST.md`, `docs/UPDATE_POLICY.md`, `docs/UPDATE_SECURITY.md`.

## Verification
Run the smallest relevant checks while iterating. Use the full relevant CI-equivalent checks before RC/release, for broad cross-component changes, or when targeted checks cannot establish safety.

Repository consistency:
`tests/repository/run-consistency-checks.sh`

Updater simulations, when updater code is affected:
`tests/updater/run-simulations.sh`
`tests/updater/run-fix-pass-1-simulations.sh`
`tests/updater/run-fix-pass-2-simulations.sh`
`tests/updater/run-fix-pass-3-simulations.sh`

When tracked files change, keep `SHA256SUMS` synchronized; it intentionally excludes itself.

## Definition of done
A task is done when the requested behavior/change is complete, affected checks pass or any limitation is stated, `SHA256SUMS` is current, and no unrelated files were changed. Report the result concisely: changed files, verification performed, and any remaining risk.
