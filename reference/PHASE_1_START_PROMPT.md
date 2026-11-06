# Cursor Prompt: Phase 0 and Phase 1

Use `CURSOR_IMPLEMENTATION_SPEC.md` as the governing specification.

## First: Phase 0 inspection only

Do not write or modify project files yet.

1. Inspect the current project directory and identify the existing DuckDB executable and Differential extension.
2. Inspect relevant extension documentation/source for snapshot, branch, attach/open, clone and restore semantics.
3. Verify exact commands using a new disposable database and a new repository path.
4. Record DuckDB version, Differential version/build identity, OS/architecture and relevant settings.
5. Do not touch or reuse the user's existing Differential repository or prior experiment data.
6. Identify any ambiguity about whether branches are database-level, repository-level, or connection-level, and how the same snapshot can be branched twice.
7. Present the smallest implementation plan and list commands verified versus unverified.

Stop after Phase 0 and ask for approval. Do not proceed automatically.

## After Phase 0 approval: Phase 1 only

Implement only the minimal core workflow:

- deterministic synthetic transaction generation;
- raw input table;
- baseline and candidate classification SQL;
- a new isolated Differential experiment repository;
- one common input snapshot;
- baseline and candidate branches from that exact snapshot;
- verify both branches have identical raw inputs before transformation;
- execute the two transformations independently;
- verify raw input and baseline isolation.

Do not implement benchmarks, clone/restore lifecycle tests, garbage collection, recovery tests, reporting frameworks or any excluded feature in Phase 1.

Keep the implementation simple. Use DuckDB SQL for transformations and Python for orchestration. Do not invent extension commands. If a required operation is not verified, stop and explain the gap rather than substituting an unrelated mechanism.

At the end, run focused tests and report files changed, commands, actual results, failures, limitations and acceptance criteria status. Stop and wait for approval before Phase 2.
