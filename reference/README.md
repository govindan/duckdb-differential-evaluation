# DuckDB Differential Evaluation MVP v1.0

This package contains the reviewed, implementation-ready specification for the DuckDB Differential banking transaction pipeline experiment.

## How to use it in Cursor

1. Open the existing DuckDB Differential evaluation project (or the intended new working directory).
2. Add this package's `CURSOR_IMPLEMENTATION_SPEC.md` to the project, or open it as reference material.
3. Start with `PHASE_1_START_PROMPT.md`. Do not ask Cursor to implement all phases at once.
4. Review the Phase 1 report and tests before authorising Phase 2.
5. Preserve the frozen experiment scope. Any scope change requires explicit approval.

## Important safety instruction

Use a new, disposable experiment workspace and a new Differential repository for this MVP. Do not modify or delete the user's existing Differential build, repository, snapshots, branches, or prior experiment data.

The specification intentionally requires Cursor to inspect and verify the installed extension's actual commands and semantics before implementing them. It must not invent APIs.

## Package contents

- `CURSOR_IMPLEMENTATION_SPEC.md`: governing implementation specification.
- `PHASE_1_START_PROMPT.md`: first prompt to use in Cursor.
- `ACCEPTANCE_CRITERIA.csv`: concise acceptance checklist.
- `TEST_TO_CAPABILITY_TRACEABILITY.csv`: mapping from tests to capabilities.
- `DESIGN_DECISIONS.md`: frozen scope and key technical decisions.
