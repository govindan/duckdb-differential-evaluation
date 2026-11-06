# Cursor Implementation Specification
## DuckDB Differential Evaluation MVP v1.0
**Use case:** Banking transaction pipeline change validation  
**Status:** Reviewed implementation baseline  
**Scope:** Frozen. Do not expand without explicit user approval.

---

## 1. Objective

Build a small, understandable and reproducible experiment to evaluate DuckDB Differential using a synthetic banking transaction classification pipeline.

Evaluate two hypotheses:

- **H1: Storage and operational efficiency.** Differential can reduce the overhead of maintaining multiple database states compared with conventional independent DuckDB database copies.
- **H2: Data engineering workflow.** Snapshots, branches, historical access, clone and restore provide useful ways to manage data states during transformation changes.

The experiment must produce evidence. Do not assume either hypothesis is true.

This is an evaluation experiment, not an enterprise Data Assurance Framework.

## 2. Frozen scope

### Included

1. Synthetic banking transaction data.
2. One common raw-input snapshot.
3. Baseline and candidate branches created from that same snapshot.
4. Independent baseline and candidate classification transformations.
5. DuckDB SQL comparison.
6. Branch isolation and historical access tests.
7. Clone and restore tests, where supported by the installed build.
8. Snapshot expiry, branch deletion and garbage-collection tests, where supported.
9. Conventional DuckDB independent-copy control experiment.
10. Storage and performance measurements.
11. Persistence and feasible recovery tests.
12. CSV and Markdown reporting.

### Excluded

- Enterprise Data Assurance Framework.
- Canonical banking model.
- Soda or other data quality frameworks.
- Metadata or policy engines.
- Fee calculation.
- S3 integration.
- Web UI, dashboard, API or microservices.
- Generic connector or plugin framework.
- Production deployment.

Do not add excluded features.

## 3. Environment and safety

The known environment is macOS Apple Silicon, DuckDB 2.0.0 and a locally built DuckDB Differential v2.0.0 extension. The exact extension commit, build flags, artifact path and runtime configuration must be inspected and recorded rather than assumed.

Before coding:

1. Inspect the current working directory and repository.
2. Locate the DuckDB executable and extension artifact.
3. Inspect the extension documentation and source for the relevant commands.
4. Verify commands against the installed build using a disposable test database.
5. Record DuckDB version, extension version, source commit if available, OS/architecture and build configuration.
6. Do not rebuild the extension unless the existing build is unusable.
7. Do not modify, delete, clean, or reuse the user's existing Differential repository or prior experiment databases.

**Isolation requirement:** create a new working directory and a new, disposable Differential repository dedicated to this experiment. Destructive lifecycle and crash tests must use disposable test databases/repositories only. Add explicit safeguards that refuse to operate on known pre-existing repository paths.

If an extension command or capability cannot be verified, stop that subtask and report the gap. Do not invent SQL functions, command syntax or semantics.

## 4. Workload: synthetic banking transactions

Use one simple classification scenario. It is a controlled engineering workload, not a representation of an actual bank's policy.

### Raw input fields

- `transaction_id` VARCHAR, unique business key
- `customer_id` VARCHAR
- `transaction_date` DATE
- `account_id` VARCHAR
- `transaction_type` VARCHAR
- `currency` VARCHAR
- `transaction_amount` DECIMAL(18,2)

The raw input must not contain baseline or candidate classification output columns.

Use a fixed currency initially (AUD), synthetic identifiers and a deterministic random seed. Include explicit boundary records. No real personal or banking data.

### Baseline rule

- Amount < 1,000: LOW
- 1,000 <= amount < 5,000: MEDIUM
- 5,000 <= amount < 10,000: MEDIUM
- Amount >= 10,000: HIGH

### Candidate rule

- Amount < 1,000: LOW
- 1,000 <= amount < 5,000: MEDIUM
- Amount >= 5,000: HIGH

The candidate therefore changes classification for transactions in the interval [5,000, 10,000).

Include explicit boundary values: 999.99, 1,000.00, 4,999.99, 5,000.00, 9,999.99 and 10,000.00.

### Dataset sizes

- 10,000 rows: functional test.
- 100,000 rows: small benchmark.
- 1,000,000 rows: principal benchmark.
- 10,000,000 rows: optional stress test, only after smaller sizes pass and resources permit.

Dataset size and seed must be configurable. The same seed and parameters must recreate the same logical input.

## 5. Core Differential workflow

The intended logical workflow is:

1. Generate and load one raw transaction population.
2. Verify row count, unique transaction keys and a deterministic input fingerprint/checksum appropriate to the chosen canonical representation.
3. Capture a named Differential snapshot of the raw input state.
4. Create a baseline branch from that snapshot.
5. Create a candidate branch from exactly the same snapshot.
6. Verify both branches initially expose the same raw input population.
7. Execute the original classification transformation on the baseline branch.
8. Execute the candidate classification transformation on the candidate branch.
9. Compare outputs using DuckDB SQL and `transaction_id`.
10. Verify candidate processing has not altered the baseline branch or common input state.

Do not assume a branch is a security boundary or that branch operations provide schema-level protection. Verify actual semantics experimentally.

### Physical layout

Keep the layout minimal. Use the smallest number of schemas/tables that clearly separates raw input from derived outputs. Do not prescribe complex schema separation if the extension's database/branch semantics make a simpler layout more appropriate.

The logical data states must remain distinct:

- Common raw input.
- Baseline transformation output.
- Candidate transformation output.

If the extension requires different connection or attachment patterns, document the verified arrangement and explain it in the README.

## 6. SQL comparison requirements

Compare baseline and candidate outputs using `transaction_id`.

Before comparison:

- Confirm `transaction_id` is unique in each output.
- Confirm expected columns and data types.
- Confirm both outputs were generated from the same input snapshot.

Report:

- Baseline row count.
- Candidate row count.
- Added record count.
- Missing record count.
- Changed classification count.
- Unchanged record count.
- Duplicate key count, if any.

A changed record is a key present in both outputs with a different classification. Added and missing records must be reported separately.

The expected classification change is deterministic: records with amounts in [5,000, 10,000) change from MEDIUM to HIGH. Boundary tests must confirm inclusive/exclusive behaviour.

Do not treat equal row counts or equal totals as proof of record-level parity.

## 7. Separate controlled-change workload for benchmarks

A classification threshold change does not guarantee an exact percentage of rows will change. Therefore, keep two workloads distinct:

### A. Business classification demonstration

Use the baseline and candidate threshold rules above. Report the actual number and percentage of records whose classification changes. Do not force this result to match a requested benchmark percentage.

### B. Controlled storage/write benchmark

For storage and write-overhead measurements, use a separate deterministic update workload that changes exactly 1%, 10%, 50% and 100% of eligible rows. Define the update precisely (for example, update a dedicated payload/status column in a benchmark table). Keep the business classification output unchanged in this workload.

For each percentage, record the exact intended and actual changed-row counts. This isolates physical change volume from business-rule selectivity.

## 8. Conventional DuckDB control

Implement a conventional DuckDB control using independent database copies.

Both the Differential experiment and control must start from identical logical input data and execute identical transformation SQL.

The control should:

1. Create a baseline database/state.
2. Create a full independent candidate copy using a clearly documented method.
3. Execute baseline and candidate transformations independently.
4. Compare outputs using the same DuckDB SQL logic.
5. Measure copy, transformation, comparison and cleanup operations.

Document exactly what is included in each timing and storage measurement. Do not claim that branch creation and full database copying are identical operations. The purpose is to compare the practical cost of maintaining equivalent independent states.

Use equivalent durability settings and the same hardware, input data and SQL. Record any unavoidable differences.

## 9. Storage measurement methodology

Do not rely only on the main database file size.

At minimum, record:

- Total size of the isolated Differential repository directory.
- Relevant DuckDB database file sizes.
- WAL and temporary file sizes where present.
- Size before branching.
- Size after branch creation.
- Size after candidate writes/snapshot.
- Size after branch deletion.
- Size after eligible snapshot expiry and garbage collection.

For the conventional control, measure the total size of both independent database copies and relevant WAL/temp files at equivalent checkpoints.

Use consistent measurement boundaries and report the method. Do not manually alter Differential internal storage files.

A branch or snapshot deletion may not reclaim data still referenced elsewhere. Test reclamation only after verifying retention/reference semantics. Report actual reclamation, including zero reclamation, without forcing a desired outcome.

## 10. Lifecycle tests

Implement and test individually, only after verifying exact syntax and semantics:

- Snapshot creation and reopening.
- Historical snapshot access.
- Branch creation and isolation.
- Independent clone and clone isolation.
- Restore to a selected earlier snapshot.
- Branch deletion.
- Eligible snapshot expiry.
- Garbage collection.

For each operation record: test ID, command/API used, preconditions, result, postcondition and evidence file.

If a capability is unsupported or unclear in the installed build, mark it unverified and continue only where dependencies allow. Do not emulate the capability and report it as Differential functionality.

## 11. Persistence and recovery

Use disposable repositories/databases only.

Test separately:

1. Normal close and restart.
2. Previously committed write surviving process termination.
3. In-progress write termination, only if safe and feasible.
4. Snapshot publication failure, only if supported failure hooks are available.
5. Post-restart integrity checks.

Do not describe normal restart or a committed write surviving process termination as proof of power-loss durability.

Never run crash or destructive tests against the user's existing Differential repository or existing experiment data. If failure injection is unavailable, record the test as unverified.

## 12. Benchmark method

Test 10K, 100K and 1M rows first. Attempt 10M only if resources permit.

For the controlled update workload, test 1%, 10%, 50% and 100% changed rows.

Measure separately:

- Initial load.
- Snapshot creation.
- Branch creation.
- Conventional database copy.
- Baseline transformation.
- Candidate transformation.
- SQL comparison.
- Branch/database cleanup.
- Snapshot expiry and garbage collection.
- Physical storage at defined checkpoints.

Run at least three measured repetitions where practical, after a warm-up. Preserve individual observations and report median and range. Record failures and resource limits.

Record hardware, OS, filesystem, DuckDB and extension versions, build identity, relevant settings, dataset seed/size and test parameters.

Do not set arbitrary performance pass thresholds. The benchmark is an evaluation, not a performance claim exercise.

## 13. Implementation style

Keep the code straightforward and small.

- DuckDB SQL for schema, transformations and comparisons.
- Python for orchestration, data generation, timing, filesystem measurements and report writing.
- Git for source versioning.
- CSV and Markdown for results.

Prefer a few readable functions over abstractions. Avoid unnecessary classes, inheritance, frameworks, APIs, services, dashboards, metadata repositories and dependencies.

Suggested structure:

```text
duckdb-differential-evaluation/
├── README.md
├── config/
│   └── experiment.yaml
├── sql/
│   ├── schema.sql
│   ├── baseline_transformation.sql
│   ├── candidate_transformation.sql
│   └── comparison.sql
├── python/
│   ├── generate_data.py
│   ├── experiment_runner.py
│   ├── differential_operations.py
│   ├── benchmark_runner.py
│   └── report_generator.py
├── tests/
│   ├── test_functional.py
│   ├── test_branch_isolation.py
│   ├── test_lifecycle.py
│   └── test_comparison.py
└── results/
    ├── functional/
    ├── benchmarks/
    └── reliability/
```

This is a guide, not a mandate to create empty or unnecessary modules. Combine small related functions if that makes the project easier to understand.

Use configurable paths. Do not scatter machine-specific absolute paths throughout the code.

## 14. Run manifest and reproducibility

Do not build a metadata framework. Write one simple JSON or CSV run manifest per experiment containing:

- Run ID.
- Dataset size and seed.
- Changed-row count/percentage where relevant.
- DuckDB version.
- Differential version and build identity if available.
- OS and architecture.
- Transformation source revision or Git commit.
- Snapshot and branch identifiers.
- Execution parameters.
- Start/end times and durations.
- Result status and evidence file references.

The manifest exists only to make this experiment reproducible.

## 15. Reporting

Generate simple CSV results and a concise Markdown report.

Every capability must have one evidence status:

- **DEMONSTRATED:** successfully executed and verified in this environment.
- **DOCUMENTED:** described by documentation but not independently demonstrated.
- **UNVERIFIED:** not tested successfully, unsupported in the current build, or evidence is insufficient.

For each test, report test ID, status, command/API, expected result, actual result, evidence path and notes.

Never fabricate measurements or mark a test successful without evidence.

## 16. Acceptance criteria

### Core functional

- AC01: Dataset is reproducible using the same seed and parameters.
- AC02: Raw input keys are unique and input count is verified.
- AC03: One common input snapshot is created.
- AC04: Baseline branch is created from that snapshot.
- AC05: Candidate branch is created from that same snapshot.
- AC06: Both branches expose identical raw input before transformations.
- AC07: Original transformation executes on baseline.
- AC08: Modified transformation executes on candidate.
- AC09: Input remains unchanged.
- AC10: Baseline remains unchanged by candidate writes.
- AC11: SQL correctly identifies added, missing, changed and unchanged records.
- AC12: Classification boundary tests pass.
- AC13: Repeated execution with identical inputs and code gives equivalent logical outputs.

### Lifecycle

- AC14: Snapshot can be reopened and queried.
- AC15: Historical state can be accessed.
- AC16: Clone and isolation are tested or marked unverified.
- AC17: Restore is tested or marked unverified.
- AC18: Branch deletion and eligible snapshot expiry are tested or marked unverified.
- AC19: Garbage collection outcome is measured and documented.

### Control and benchmarks

- AC20: Conventional DuckDB control produces equivalent logical outputs.
- AC21: 10K, 100K and 1M tests are attempted; 10M is optional.
- AC22: Controlled update workload changes exact 1%, 10%, 50% and 100% row counts.
- AC23: Storage is measured using consistent physical boundaries.
- AC24: Timings are separated by operation.
- AC25: Repeated measurements and environment details are recorded.

### Reliability and reporting

- AC26: Normal restart is tested.
- AC27: Committed-write process termination is tested safely.
- AC28: In-progress failure tests are run only where feasible, otherwise marked unverified.
- AC29: Recovered states pass applicable integrity checks.
- AC30: CSV and Markdown reports are generated.
- AC31: README explains setup and execution.
- AC32: Every capability is classified as demonstrated, documented or unverified.

A capability marked unverified is not a passing test. It is an explicit evidence gap. Do not hide it.

## 17. Cursor execution protocol: mandatory phased work

Do not implement the entire project in one pass.

### Phase 0: Inspect and plan only

Inspect repository, build, extension documentation and command syntax. Do not modify existing files or run destructive tests. Propose the smallest implementation plan and list any unresolved extension semantics. Stop and request approval.

### Phase 1: Minimal core workflow

Implement deterministic data generation, schema, baseline/candidate SQL, isolated experiment repository, common snapshot, two branches and independent transformations. Verify identical branch inputs and branch isolation. Add focused tests. Stop and report.

### Phase 2: Comparison

Implement SQL comparison and boundary tests. Verify expected changed records and counts. Stop and report.

### Phase 3: Lifecycle

Implement clone, restore, expiry and garbage-collection tests where supported. Use disposable repositories. Stop and report.

### Phase 4: Control and benchmarks

Implement conventional independent-copy control, controlled update workload, storage measurements and operation timings. Stop and report.

### Phase 5: Reliability and final reporting

Implement safe persistence/recovery tests, CSV/Markdown reporting and README. Mark unverified capabilities explicitly.

At the end of each phase, report:
1. Files created/changed.
2. Commands executed.
3. Tests passed/failed/not run.
4. Actual measured results.
5. Known limitations.
6. Acceptance criteria status.
7. Whether the next phase is ready.

Do not proceed to the next phase until the user approves.

## 18. Final deliverable

A small, reproducible experiment that answers:

1. Which Differential capabilities were demonstrated?
2. How does Differential compare with independent DuckDB copies for the tested workflow?
3. What storage differences were measured?
4. What performance overhead was observed?
5. What lifecycle and recovery behaviours were verified?
6. What remains undocumented or unverified?
7. Is further enterprise evaluation justified?

**Success means a simple experiment with defensible evidence, not a large software framework.**
