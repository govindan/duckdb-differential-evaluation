# DuckDB Differential evaluation

MVP v1.0 is frozen. This directory, its results, and its conclusions are the completed baseline. Later investigation, including S3, multi-host operation, and fault-injection testing, belongs in a separately versioned extension and must not change this evidence or these conclusions.

The evaluation uses a locally built DuckDB v2.0.0 CLI. `experiment/config/experiment.yaml` names it as `build/release/duckdb`. That relative path is resolved inside `experiment/`, beside this directory, or in the directory that contains this directory. Set `DUCKDB_CLI` to an absolute path when the binary is somewhere else. The run does not use another DuckDB binary, and it does not modify the Differential source tree.

The evidence and the consolidated report are in `experiment/results/`. Start with `experiment/results/REPORT.md`.

## Run from `experiment/`

```sh
python3 python/benchmark.py
python3 python/persistence.py
python3 python/report.py
```

`benchmark.py` repeats the Phase 4 measurements in disposable directories under `experiment/benchmark/`. `persistence.py` uses only `experiment/persistence/`. `report.py` rebuilds `experiment/results/REPORT.md` and `experiment/results/reports/` from the recorded CSV files.

The accepted Phase 1–3 databases live under `experiment/repository/` and `experiment/lifecycle/`. Do not point a new run at those directories. `python/lifecycle.py` rebuilds the lifecycle repository from scratch.

Remote garbage collection, metadata compaction, power-loss durability, and snapshot-publication failure are recorded with their evidence status in `experiment/results/reports/capability_matrix.csv`. They are not implied by a successful earlier command.
