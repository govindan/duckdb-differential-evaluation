# DuckDB Differential evaluation

MVP v1.0 frozen baseline. The measurements and conclusions in this report are closed. S3, multi-host operation, and fault-injection testing require a separately versioned extension and must not change this evidence.

This report consolidates the MVP evidence. Measurements come from the recorded CSV files. They describe this machine, these datasets, and these workloads.

## Retained states

Storage figures are comparable only when the retained states are named.

The controlled workload keeps the same pair of states on both systems: the untouched source, and one diverged copy. On Differential that is the base branch plus the updated branch. On the conventional control that is the original database file plus the updated copy. Those rows are the equivalent-state comparison.

The business workload does not keep the same pair. While both classification outputs exist, Differential retains three states: raw `main`, the baseline output, and the candidate output. The conventional control retains two transformed database files and does not keep a separate raw file.

Removing the candidate still leaves different states. The conventional control then has one transformed database. Differential, after branch deletion, snapshot expiry, and local garbage collection, still retains the raw history and the baseline output. That checkpoint is a lifecycle comparison. It is not an equivalent-state comparison.

## Storage

Median bytes. The incremental rows are the bytes added by creating the Differential branches or the native physical copy. The later tables name the states those bytes retain.

| Rows | Branch metadata added | Physical copy added |
| --- | ---: | ---: |
| 10,000 | 0 | 1,323,008 |
| 100,000 | 16,384 | 6,041,600 |
| 1,000,000 | 73,728 | 57,159,680 |
| 10,000,000 | 749,568 (724,992–765,952) | 565,981,184 |

Equivalent controlled states at 100 percent updated: untouched source plus the diverged copy.

| Rows | Differential | Native original plus updated copy |
| --- | ---: | ---: |
| 10,000 | 3,178,150 | 1,859,584 |
| 100,000 | 10,923,264 | 4,218,880 |
| 1,000,000 | 20,140,916 | 32,006,144 |
| 10,000,000 | 191,253,142 | 318,529,536 |

Business outputs present. Differential holds raw history plus both outputs. Native holds two transformed files.

| Rows | Differential raw, baseline, and candidate | Native two transformed files |
| --- | ---: | ---: |
| 10,000 | 4,690,450 | 3,170,304 |
| 100,000 | 20,333,622 | 13,131,776 |
| 1,000,000 | 107,038,354 | 147,349,504 |
| 10,000,000 | 1,081,512,753 | 1,535,401,984 |

After the candidate is removed. These are different retained states: Differential still holds raw history and baseline; native holds one transformed database.

| Rows | Differential raw history and baseline | Native one transformed database |
| --- | ---: | ---: |
| 10,000 | 3,928,565 | 1,585,152 |
| 100,000 | 10,144,532 | 6,565,888 |
| 1,000,000 | 90,257,129 | 73,674,752 |
| 10,000,000 | 817,456,379 | 767,569,920 |

Expiry did not change repository size at the measured checkpoints. Local garbage collection then deleted eligible objects. At 10,000 controlled rows the repository returned to the pre-update size. At larger controlled sizes the segment bytes returned to the pre-update segment size while `engine.sqlite` stayed slightly larger. At 100,000 rows, allocated space fell below the pre-update size and the original rows still read back. The garbage-collection command's `candidate_bytes` is not the directory delta.

The complete checkpoint table is `results/benchmarks/storage_summary.csv` and `results/benchmarks/optional_10m/storage_summary.csv`. The classified extract is `results/reports/storage_comparison.csv`.

## Performance

Median milliseconds of three measured repetitions after one excluded warmup. Branch creation and copying are different operations.

| Rows | Branch creation | Database copy |
| --- | ---: | ---: |
| 10,000 | 4.0 (3.7–4.1) | 0.8 (0.7–0.9) |
| 100,000 | 4.0 (3.8–4.1) | 1.9 (1.6–2.0) |
| 1,000,000 | 4.7 (4.6–4.9) | 8.2 (8.1–8.5) |
| 10,000,000 | 12.0 (11.7–12.5) | 78.2 (77.6–79.1) |

At 10,000,000 business rows, branch creation took 12.0 ms and copying took 78.2 ms. Copying was faster at 10,000 and 100,000 rows. The per-operation ranges are in `results/reports/performance_comparison.csv`.

Business classification changed 1,986 of 10,000 rows, 19,975 of 100,000, 200,105 of 1,000,000, and 1,998,489 of 10,000,000. Both systems returned the same counts. The controlled workload changed exactly 1, 10, 50, and 100 percent of its own table. Those two workloads stayed separate.

Required benchmark wall clock, including warmup and dataset generation, was 60.0 seconds. The 10,000,000-row run was 220.9 seconds. WAL and temporary files were 0 bytes after every closed process.

## Persistence and recovery

All persistence work used `experiment/persistence/`. The Phase 1–3 repositories were not opened.

| Test | Class | Power loss | Status | Observed result |
| --- | --- | --- | --- | --- |
| PR07 Snapshot publication failure injection | failure_injection | not_tested | UNVERIFIED | test_hooks=absent |
| PR01 Normal close and restart | normal_process_restart | false | DEMONSTRATED | live_rows=100, base_rows=100, base_fingerprint=630e4e79ab397b2c5c06f3157d5fb9aa, extra_rows=0 |
| PR02 Normal close and restart | normal_process_restart | false | DEMONSTRATED | live_rows=100, snapshot_rows=100, base_rows=100, base_fingerprint=630e4e79ab397b2c5c06f3157d5fb9aa, extra_rows=0 |
| PR03 Committed write then process termination | process_termination_after_commit | false | DEMONSTRATED | killed signal=-9; live_rows=100, base_rows=100, base_fingerprint=630e4e79ab397b2c5c06f3157d5fb9aa, extra_rows=0 |
| PR04 Committed write then process termination | process_termination_after_commit | false | DEMONSTRATED | killed signal=-9; live_rows=100, snapshot_rows=100, base_rows=100, base_fingerprint=630e4e79ab397b2c5c06f3157d5fb9aa, extra_rows=0 |
| PR05 In-progress statement process interruption | process_interruption_during_statement | false | DEMONSTRATED | killed signal=-9; before live_rows=100, base_rows=100, base_fingerprint=630e4e79ab397b2c5c06f3157d5fb9aa, extra_rows=0; after live_rows=100, base_rows=100, base_fingerprint=630e4e79ab397b2c5c06f3157d5fb9aa, extra_rows=0 |
| PR06 In-progress statement process interruption | process_interruption_during_statement | false | DEMONSTRATED | killed signal=-9; before live_rows=100, snapshot_rows=100, base_rows=100, base_fingerprint=630e4e79ab397b2c5c06f3157d5fb9aa, extra_rows=0; after live_rows=100, snapshot_rows=100, base_rows=100, base_fingerprint=630e4e79ab397b2c5c06f3157d5fb9aa, extra_rows=0 |
| PR08 Power-loss durability | power_loss | not_tested | UNVERIFIED | No power cut and no cache drop were performed |

PR01 and PR02 are normal process restarts: the process exited 0 and a new process read the committed rows.

PR03 and PR04 are controlled process termination after a commit. `CHECKPOINT` or `differential_create_snapshot` had returned, a marker file was written, and `SIGKILL` arrived during a later statement. The committed 100 rows and fingerprint `630e4e79ab397b2c5c06f3157d5fb9aa` were readable.

PR05 and PR06 are controlled interruption during an `INSERT`. The previously committed 100 rows and the same fingerprint were readable after restart. The interrupted statement left 0 extra rows. That shows the open statement did not remain; it does not show that an in-progress write survives power loss.

PR08 is power-loss durability. It was not tested. A clean exit and `SIGKILL` leave the operating-system page cache in place. PR07 is snapshot publication failure. `test_hooks` is `absent` on this release CLI, so no publication failure was injected.

## Capability evidence

| Capability | Status |
| --- | --- |
| Dataset reproducibility | DEMONSTRATED |
| Common snapshot and two branches | DEMONSTRATED |
| Raw input identity and isolation | DEMONSTRATED |
| Baseline and candidate classification | DEMONSTRATED |
| Added, missing, changed, unchanged comparison | DEMONSTRATED |
| Classification boundaries | DEMONSTRATED |
| Repeated logical output | DEMONSTRATED |
| Snapshot reopen | DEMONSTRATED |
| Historical snapshot access | DEMONSTRATED |
| Clone and clone isolation | DEMONSTRATED |
| Restore | DEMONSTRATED |
| Branch deletion and snapshot expiry | DEMONSTRATED |
| Local garbage collection | DEMONSTRATED |
| Remote garbage collection | UNVERIFIED |
| Metadata compaction | DOCUMENTED |
| Shared-object retention | DEMONSTRATED |
| Conventional copy logical equivalence | DEMONSTRATED |
| 10K, 100K, 1M, and optional 10M benchmarks | DEMONSTRATED |
| Controlled 1, 10, 50, and 100 percent writes | DEMONSTRATED |
| Physical storage boundaries | DEMONSTRATED |
| Per-operation timings | DEMONSTRATED |
| Environment record | DEMONSTRATED |
| Normal process restart | DEMONSTRATED |
| Committed write after process termination | DEMONSTRATED |
| In-progress statement interruption | DEMONSTRATED |
| Recovered-state integrity | DEMONSTRATED |
| Power-loss durability | UNVERIFIED |
| Snapshot publication failure | UNVERIFIED |
| S3, shared writers, WAL shipping, and followers | UNVERIFIED |

Remote garbage collection remains UNVERIFIED. Metadata compaction remains DOCUMENTED. The detail and evidence paths are in `results/reports/capability_matrix.csv`.

## Trace

Dataset sizes, the 1/10/50/100 percent writes, the CLI identity, and the wall-clock totals are in `results/reports/manifest.json`. Changed-row counts are the `warmup=false` comparison rows in the observations CSVs. Operation times are the `samples=3` rows in the summary CSVs. `logical_database_copy` has one sample and is not the physical-copy measurement. The commands are `benchmark.py`, `persistence.py`, and `report.py`. Phase 1 snapshot and branch identifiers are in `results/functional/phase1/manifest.json`. Each disposable benchmark execution is mapped to the snapshot id recorded in its saved `branch_creation.sql` by `results/reports/benchmark_snapshots.csv`. The manifest records the CLI hash, the extension source commit, and SHA-256 hashes of the SQL files, `benchmark.py`, and `generate_data.py`. The evaluation directory itself is untracked, so those file hashes identify the workload revision.

Storage totals are `state_storage_bytes` after the measured process has exited. Differential state is the repository directory plus the temp directory. Native state is the `.duckdb`, WAL, and temp files present then. WAL and temp were 0 bytes at every closed checkpoint. Absolute checkpoint tables use the median of three repetitions. The incremental table uses the median of the three paired repetition differences. At 10,000,000 rows those branch differences were 724,992, 749,568, and 765,952 bytes, so the median is 749,568. Subtracting the two checkpoint medians gives 765,952 and is not the median increment.

Headline branch and copy times each come from one named operation, repeated three times after a warmup. They are different operations. The 10,000,000-row ranges are 11.7–12.5 ms and 77.6–79.1 ms. Some shorter operations have wide relative ranges; those ranges are in the summary CSVs.

PR01 and PR02 are normal restarts. PR03 and PR04 are `SIGKILL` after a completed commit. PR05 and PR06 are `SIGKILL` during an insert. PR08 is the untested power-loss case. None of the executed rows has `power_loss=true`.

LC01–LC12 are rows in `results/functional/phase3/findings.csv`. PR01–PR08 are rows in `results/functional/phase5/persistence_tests.csv`. OS01 is the row in `results/reports/not_executed.csv`. Phase 1, Phase 2, and benchmark classifications point at the result CSV named in `results/reports/capability_matrix.csv`.

## Methodology

DuckDB was the local v2.0.0 CLI recorded in `results/benchmarks/environment.json`, with Differential v1.0.0 built in. `differential_auto_gc` was false during controlled measurements. SQL time is an in-process timestamp delta. Copy time includes `fsync` of the destination. Storage was measured after the process exited and includes the Differential repository or the native database, WAL, and temporary files present at that moment.

The business rules are the accepted baseline and candidate classification SQL. The controlled update is `row_id < size * percent / 100` on a separate table. One warmup was excluded. The median is the middle of three measured repetitions.

## Limitations

Results are limited to this environment and these workloads. Branch creation and a full file copy are different operations. Business storage compares three Differential states with two native files while both outputs exist, and raw-plus-baseline with one native file after candidate removal. The equivalent retained-state comparison is the controlled workload.

Closed-process measurements do not include WAL or temporary files that existed only while DuckDB was running. Local garbage collection can reclaim more or less than the bytes added by the expired state, and `engine.sqlite` can remain larger. Remote garbage collection, metadata compaction, power loss, snapshot-publication failure, S3, shared writers, WAL shipping, and followers were not demonstrated here.

## Findings

Differential branch creation added substantially less storage than a conventional physical copy at every tested size. Total storage still depends on the dataset size and on which states are retained. Conventional copying was faster for the smaller files. At 10,000,000 business rows, branch creation took 12.0 ms and copying took 78.2 ms.

Expiry alone did not reclaim storage. Local garbage collection reclaimed eligible objects. Metadata storage could remain slightly larger after cleanup. A normal restart and a `SIGKILL` after a completed commit both preserved the committed 100-row state. An interrupted insert did not leave its new rows. None of those process results is power-loss durability.

## Acceptance criteria

Every acceptance criterion has a row in `results/reports/acceptance_criteria.csv`. Local functional, lifecycle, benchmark, restart, committed-termination, and in-progress interruption checks were demonstrated. Power-loss durability and snapshot-publication failure remain explicit gaps under AC28.

All 32 acceptance rows record that the required check was run. Power-loss durability and snapshot-publication failure remain unverified capabilities under AC28, as listed in the matrix.

Further evaluation would be required before any claim about power loss, remote garbage collection, metadata compaction, or multi-host S3 operation.
