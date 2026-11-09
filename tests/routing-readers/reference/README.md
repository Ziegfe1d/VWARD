# Reference implementations for equivalence checks

Byte-exact copies of earlier runtime libraries, used ONLY by the process-budget
equivalence checks (`check-process-budget-primitives.py`,
`check-batch-primitives.py`) to compare a rewritten primitive with the original
on the same inputs. They are test data: never installed, never sourced by the
runtime. Kept in the tree because CI checks out without history (depth 1).

- `4cf3388/` — before the 07.11.2026 process-budget pass.
- `c9d39f4/` — PR38 HEAD before the 08.11.2026 batch executor.
