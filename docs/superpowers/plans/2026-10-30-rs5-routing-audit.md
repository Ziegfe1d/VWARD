# RS-5 Routing Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** Pure read-only routing explanations from explicit normalized input.
**Architecture:** Source-only POSIX shell library, one awk evaluator, no adapters.
**Tech Stack:** POSIX sh/awk; host and BusyBox ash behavioral tests.
**Spec:** docs/ROUTING_AUDIT_CONTRACT.md; docs/ROUTING_B_IMPLEMENTATION.md.

## Global Constraints

No daemon, new dependency, live query, route/DNS/state write or production caller.
Preserve API/Panel/services; no merge, publish, VERSION/feed/release/install.
Unknown/manual ownership stays reference; no silent source precedence.

## Review Focus

- Empty known manual input is valid; enabled unknown source cannot imply absence.
- Parent subtree coverage must not reverse child-to-parent or cross DNS/targets.
- Malformed late records cannot leak partially valid output.
- Duplicate REF must not overwrite an earlier conflicting definition.
- Loading/calling must not execute mutators or write outside test fixtures.

### Task 1: Document, specify, implement, verify

Files: contract above; components/runtime/lib/vward-routing-audit.sh;
tests/routing-audit/run-simulations.sh; SHA256SUMS.
Interface: `vward_routing_audit INTENTS SNAPSHOT` -> deterministic TSV, rc=0/2.

- [x] Write the brief normalized contract before code.
- [x] Write real-output tests for 8 combinations, 24 directed transitions,
  duplicate/ref ownership, conflicts, health, coverage, malformed/order inputs.
- [x] Run test first: expected FAIL missing routing audit library.
- [x] Implement only the documented pure function.
- [x] Run host sh and BusyBox ash behavioral tests; syntax and ShellCheck.
- [x] Review final diff, update own checksums, commit independently.

Ruling: owner supplied explicit implementation scope/method; proceed without
another approval. Parent owns chronology, final review/integration and CI.
Ruling: targeted tests only as explicitly required by owner, no full suite.

Evidence: initial `sh tests/routing-audit/run-simulations.sh` exited 1:
`FAIL: missing routing audit library (expected RED)`. After implementation,
host sh and BusyBox ash + awk returned `ROUTING_AUDIT_SIMULATIONS=PASS`.
An additional RED showed absent ISSUES output; GREEN now names all failed
or unknown dependencies even when a route conflict is the primary reason.
ShellCheck 0.9.0 and host sh/BusyBox ash syntax checks pass. A truncated
unpacked ShellCheck binary crashed; the complete extracted binary passed.
Final self-review: input grammar, ownership restrictions, deterministic sets,
coverage direction, no mutation/callers checked; parent owns independent review.
No full suite, live device, performance budget, integration or release claim.


Review fix pass: repeated subtree references caused nested intent/route scans
and quadratic evidence sorting for every domain. Bounded BusyBox RED:
64 domains /128 intent+route refs exceeded 3s. GREEN after route coverage
indexing and global merge-sorted evidence orders: exact 449454 output bytes,
64 rows, all 128 refs/rights and duplicate=127 preserved; 0.180s, same 3s bound.
No accepted maximum-size workload or heavy suite run. Added host-only Python
regression; runtime dependencies and public TSV contract remain unchanged.
