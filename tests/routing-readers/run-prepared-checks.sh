#!/bin/sh
# Complete OFF B integration coverage; each Python case keeps its own budget.
set -eu
ROOT=$(CDPATH='' cd -- "$(dirname "$0")/../.." && pwd -P)
cd "$ROOT"
for CASE in \
    check-agh-locked.py \
    check-agh-preflight-refusal.py \
    check-backwriter-eligibility.py \
    check-live-admission.py \
    check-live-native-boundary.py \
    check-live-updater-admission.py \
    check-boot-locks.py \
    check-bootstrap-read.py \
    check-coordinator-admission.py \
    check-dns-view.py \
    check-execution-dns.py \
    check-execution-faults.py \
    check-execution-locks.py \
    check-execution-modes.py \
    check-execution-signals.py \
    check-execution-step-faults.py \
    check-execution.py \
    check-inventory.py \
    check-journal2.py \
    check-legacy-ancestry.py \
    check-legacy-import.py \
    check-legacy-server.py \
    check-lock-election.py \
    check-outcome.py \
    check-pipeline.py \
    check-plan2.py \
    check-preflight-refusal.py \
    check-probe-lifetime.py \
    check-projection.py \
    check-publisher-cas.py \
    check-publisher-zombie.py \
    check-publisher.py \
    check-server-lifecycle.py \
    check-source-transitions.py \
    check-state-migration.py
do
    python3 "tests/routing-readers/$CASE" || {
        echo "FAIL: prepared OFF routing: $CASE" >&2
        exit 1
    }
done
