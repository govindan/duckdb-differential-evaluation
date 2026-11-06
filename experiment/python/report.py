"""Consolidate Phase 5 CSV and Markdown reports from recorded evidence."""

import csv
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "results" / "reports"
REQUIRED = ROOT / "results" / "benchmarks"
OPTIONAL = ROOT / "results" / "benchmarks" / "optional_10m"


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    storage = load(REQUIRED / "storage_summary.csv") + load(OPTIONAL / "storage_summary.csv")
    summary = load(REQUIRED / "summary.csv") + load(OPTIONAL / "summary.csv")
    persistence = load(ROOT / "results" / "functional" / "phase5" / "persistence_tests.csv")
    comparison = write_storage(storage)
    performance = write_performance(summary)
    matrix = write_matrix()
    acceptance = write_acceptance()
    write_not_executed()
    write_benchmark_lineage()
    write_manifest(persistence)
    write_markdown(comparison, performance, persistence, matrix, acceptance)
    print(f"wrote {REPORTS}")


def write_storage(storage):
    observations = load(REQUIRED / "observations.csv") + load(OPTIONAL / "observations.csv")
    rows = []
    for size in ("10000", "100000", "1000000", "10000000"):
        rows.append(paired_delta(
            observations, size, "differential",
            "metadata for baseline and candidate branches; raw branch already present",
            "before_branch", "snapshot", "after_branch", "branch_creation",
            "Median of the three per-repetition repository differences. Not the difference of checkpoint medians.",
        ))
        rows.append(paired_delta(
            observations, size, "native",
            "one additional physical copy of the checkpointed database",
            "after_load", "load_checkpoint", "after_copy", "database_copy",
            "Median of the three per-repetition file-copy differences. The source file remains.",
        ))
        for percent in ("1", "10", "50", "100"):
            rows.append(state_row(
                storage, "equivalent_source_plus_diverged", "controlled", "differential", size, percent,
                "after_candidate_snapshot",
                "untouched source branch plus one updated branch",
            ))
            rows.append(state_row(
                storage, "equivalent_source_plus_diverged", "controlled", "native", size, percent,
                "after_candidate_snapshot",
                "untouched original database plus one updated copy",
            ))
        rows.append(state_row(
            storage, "business_outputs_present", "business", "differential", size, "",
            "after_candidate_snapshot",
            "raw main, baseline output, and candidate output",
        ))
        rows.append(state_row(
            storage, "business_outputs_present", "business", "native", size, "",
            "after_candidate_snapshot",
            "two transformed database files; raw input is not retained as its own file",
        ))
        rows.append(state_row(
            storage, "after_candidate_removal", "business", "differential", size, "",
            "after_gc",
            "raw history and baseline output remain after candidate deletion, expiry, and local GC",
        ))
        rows.append(state_row(
            storage, "after_candidate_removal", "business", "native", size, "",
            "after_database_cleanup",
            "one remaining transformed database after the candidate copy is deleted",
        ))
    write_csv(REPORTS / "storage_comparison.csv", rows)
    return rows


def write_performance(summary):
    wanted = {
        ("business", "", "branch_creation"),
        ("business", "", "database_copy"),
        ("business", "", "baseline_transform"),
        ("business", "", "candidate_transform"),
        ("business", "", "baseline_snapshot"),
        ("business", "", "candidate_snapshot"),
        ("business", "", "baseline_checkpoint"),
        ("business", "", "candidate_checkpoint"),
        ("business", "", "comparison"),
        ("business", "", "garbage_collection"),
        ("controlled", "1", "controlled_update"),
        ("controlled", "100", "controlled_update"),
        ("controlled", "1", "database_copy"),
        ("controlled", "100", "database_copy"),
        ("controlled", "1", "branch_creation"),
        ("controlled", "100", "branch_creation"),
    }
    rows = [
        row for row in summary
        if (row["workload"], row["changed_percent"], row["operation"]) in wanted
    ]
    rows.sort(key=lambda row: (
        int(row["dataset_size"]), row["workload"], row["changed_percent"], row["system"], row["operation"],
    ))
    write_csv(REPORTS / "performance_comparison.csv", rows)
    return rows


def write_matrix():
    rows = [
        ("Dataset reproducibility", "DEMONSTRATED", "AC01", "results/benchmarks/environment.json", "10,000-row checksum matches the Phase 1 dataset"),
        ("Common snapshot and two branches", "DEMONSTRATED", "AC03; AC04; AC05", "results/functional/phase1/manifest.json", "Both branches record the same source snapshot"),
        ("Raw input identity and isolation", "DEMONSTRATED", "AC02; AC06; AC09; AC10", "results/functional/phase1/closure_checks.csv", "Raw and baseline fingerprints unchanged after candidate processing"),
        ("Baseline and candidate classification", "DEMONSTRATED", "AC07; AC08", "results/functional/phase2/comparison.csv", "Same SQL files executed on both systems in Phase 4"),
        ("Added, missing, changed, unchanged comparison", "DEMONSTRATED", "AC11", "results/functional/phase2/comparison.csv", "FULL OUTER JOIN on transaction_id"),
        ("Classification boundaries", "DEMONSTRATED", "AC12", "results/functional/phase2/boundaries.csv", "Six boundary amounts"),
        ("Repeated logical output", "DEMONSTRATED", "AC13", "results/benchmarks/observations.csv", "Business change counts match across Differential and native"),
        ("Snapshot reopen", "DEMONSTRATED", "AC14", "results/functional/phase3/findings.csv", "LC01"),
        ("Historical snapshot access", "DEMONSTRATED", "AC15", "results/functional/phase3/findings.csv", "LC02 and LC03"),
        ("Clone and clone isolation", "DEMONSTRATED", "AC16", "results/functional/phase3/findings.csv", "LC05 and LC06"),
        ("Restore", "DEMONSTRATED", "AC17", "results/functional/phase3/findings.csv", "LC04. The branch must be detached"),
        ("Branch deletion and snapshot expiry", "DEMONSTRATED", "AC18", "results/functional/phase3/findings.csv", "LC07, LC08, and LC10. Expiry alone did not shrink storage"),
        ("Local garbage collection", "DEMONSTRATED", "AC19", "results/functional/phase3/findings.csv", "LC09 and the accepted shared-object retention test"),
        ("Remote garbage collection", "UNVERIFIED", "AC19", "results/functional/phase3/findings.csv", "LC11 was not executed"),
        ("Metadata compaction", "DOCUMENTED", "AC19", "results/functional/phase3/findings.csv", "LC12. differential_compact was not executed"),
        ("Shared-object retention", "DEMONSTRATED", "AC19", "results/functional/phase3/retention_summary.csv", "Shared fingerprint unchanged and unshared bytes reclaimed"),
        ("Conventional copy logical equivalence", "DEMONSTRATED", "AC20", "results/benchmarks/observations.csv", "EXCEPT both ways for the filesystem copy and COPY FROM DATABASE"),
        ("10K, 100K, 1M, and optional 10M benchmarks", "DEMONSTRATED", "AC21", "results/benchmarks/summary.csv", "10M is in results/benchmarks/optional_10m"),
        ("Controlled 1, 10, 50, and 100 percent writes", "DEMONSTRATED", "AC22", "results/benchmarks/observations.csv", "Intended and actual row counts matched"),
        ("Physical storage boundaries", "DEMONSTRATED", "AC23", "results/benchmarks/storage_summary.csv", "Repository total, database, WAL, and temp recorded after process exit"),
        ("Per-operation timings", "DEMONSTRATED", "AC24", "results/benchmarks/summary.csv", "Three measured repetitions after one warmup"),
        ("Environment record", "DEMONSTRATED", "AC25", "results/benchmarks/environment.json", "CLI, extension, OS, filesystem, seed, and settings"),
        ("Normal process restart", "DEMONSTRATED", "AC26", "results/functional/phase5/persistence_tests.csv", "PR01 and PR02. Clean exit is not power-loss evidence"),
        ("Committed write after process termination", "DEMONSTRATED", "AC27", "results/functional/phase5/persistence_tests.csv", "PR03 and PR04. SIGKILL after the commit statement returned"),
        ("In-progress statement interruption", "DEMONSTRATED", "AC28", "results/functional/phase5/persistence_tests.csv", "PR05 and PR06. The committed 100 rows remained; the interrupted INSERT left 0 rows"),
        ("Recovered-state integrity", "DEMONSTRATED", "AC29", "results/functional/phase5/persistence_tests.csv", "Committed fingerprint 630e4e79ab397b2c5c06f3157d5fb9aa on every recovery read"),
        ("Power-loss durability", "UNVERIFIED", "AC28", "results/functional/phase5/persistence_tests.csv", "PR08. The page cache was not dropped"),
        ("Snapshot publication failure", "UNVERIFIED", "AC28", "results/functional/phase5/persistence_tests.csv", "PR07. test_hooks=absent"),
        ("S3, shared writers, WAL shipping, and followers", "UNVERIFIED", "", "results/reports/not_executed.csv", "OS01. Outside this MVP execution"),
    ]
    encoded = [
        {
            "capability": capability, "status": status, "acceptance_criteria": criteria,
            "evidence": evidence, "notes": notes,
        }
        for capability, status, criteria, evidence, notes in rows
    ]
    write_csv(REPORTS / "capability_matrix.csv", encoded)
    return encoded


def write_acceptance():
    source = list(csv.DictReader((ROOT.parent / "reference" / "ACCEPTANCE_CRITERIA.csv").open(encoding="utf-8")))
    status = {f"AC{number:02d}": "DEMONSTRATED" for number in range(1, 33)}
    notes = {
        "AC17": "Restore requires the branch to be detached",
        "AC19": "Local GC is demonstrated. Remote GC is unverified and compaction is documented",
        "AC21": "10M was run after the required sizes",
        "AC26": "Normal restart only. Not power-loss evidence",
        "AC27": "SIGKILL after a completed checkpoint or snapshot. Not power-loss evidence",
        "AC28": "In-progress SIGKILL was run. Power loss and publication-failure injection remain unverified",
        "AC30": "results/REPORT.md and results/reports",
        "AC31": "README.md at the evaluation project root",
        "AC32": "results/reports/capability_matrix.csv",
    }
    rows = []
    for item in source:
        identifier = item["Acceptance_ID"]
        rows.append({
            "acceptance_id": identifier,
            "criterion": item["Criterion"],
            "category": item["Category"],
            "status": status[identifier],
            "notes": notes.get(identifier, ""),
        })
    write_csv(REPORTS / "acceptance_criteria.csv", rows)
    return rows


def write_not_executed():
    rows = [{
        "test_id": "OS01",
        "capability": "S3, shared writers, WAL shipping, and followers",
        "command": "not run",
        "result": "not executed",
        "status": "UNVERIFIED",
        "notes": "These product capabilities were outside this MVP execution. No result was produced.",
    }]
    write_csv(REPORTS / "not_executed.csv", rows)


def write_benchmark_lineage():
    rows = []
    for series, base in (("required", ROOT / "benchmark" / "runs"), ("optional_10m", ROOT / "benchmark" / "runs_10m")):
        if not base.exists():
            continue
        for script in sorted(base.rglob("branch_creation.sql")):
            run = script.parent.parent
            relative = run.relative_to(base)
            workload, _system, size, label, repetition = relative.parts
            text = script.read_text(encoding="utf-8")
            source_ids = re.findall(r"snapshot => (\d+)", text)
            if len(set(source_ids)) != 1:
                raise SystemExit(f"expected one source snapshot in {script}")
            snapshot_sql = script.parent / "snapshot.sql"
            names = re.findall(r"name => '([^']+)'", snapshot_sql.read_text(encoding="utf-8"))
            expiry = script.parent / "snapshot_expiry.sql"
            expired = re.findall(r"versions => \[(\d+)\]", expiry.read_text(encoding="utf-8"))
            rows.append({
                "series": series,
                "workload": workload,
                "dataset_size": size,
                "changed_percent": "" if label == "business" else str(int(label[1:])),
                "repetition": repetition.removeprefix("rep"),
                "warmup": "true" if repetition == "rep0" else "false",
                "database": "bench",
                "source_snapshot_id": source_ids[0],
                "source_snapshot_name": names[0] if names else "",
                "branches": "baseline,candidate" if workload == "business" else "updated",
                "expired_output_snapshot_id": expired[0] if expired else "",
                "run_dir": str(run.relative_to(ROOT)),
                "branch_script": str(script.relative_to(ROOT)),
            })
    if not rows:
        raise SystemExit("no benchmark branch scripts were found")
    write_csv(REPORTS / "benchmark_snapshots.csv", rows)


def source_identity():
    files = [
        "sql/schema.sql",
        "sql/baseline_transformation.sql",
        "sql/candidate_transformation.sql",
        "sql/comparison.sql",
        "python/benchmark.py",
        "python/generate_data.py",
    ]
    hashes = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in files
    }
    commit = subprocess.run(
        ["git", "-C", str(ROOT.parent.parent), "rev-parse", "HEAD"],
        check=False, capture_output=True, text=True,
    )
    return {
        "extension_source_commit": commit.stdout.strip() if commit.returncode == 0 else "",
        "evaluation_tree": "untracked under the extension source repository",
        "source_file_sha256": hashes,
    }


def write_manifest(persistence):
    environment = json.loads((REQUIRED / "environment.json").read_text(encoding="utf-8"))
    identity = source_identity()
    manifest = {
        "baseline": "mvp-v1.0",
        "baseline_status": "frozen",
        "run_id": "mvp-v1-phase5",
        "dataset_seed": environment["dataset_seed"],
        "dataset_sizes": [10000, 100000, 1000000, 10000000],
        "controlled_percents": [1, 10, 50, 100],
        "duckdb_version": environment["duckdb_version_output"],
        "duckdb_cli_sha256": environment["duckdb_cli_sha256"],
        "extension_source_commit": identity["extension_source_commit"],
        "evaluation_tree": identity["evaluation_tree"],
        "source_file_sha256": identity["source_file_sha256"],
        "benchmark_snapshots": "results/reports/benchmark_snapshots.csv",
        "extension": environment["extension"],
        "platform": environment["platform"],
        "machine": environment["machine"],
        "processor": environment["processor"],
        "filesystem": environment["filesystem"],
        "settings": environment["settings"],
        "benchmark_wall_clock_ns": (REQUIRED / "suite_elapsed_ns.txt").read_text(encoding="utf-8").strip(),
        "optional_10m_wall_clock_ns": (OPTIONAL / "suite_elapsed_ns.txt").read_text(encoding="utf-8").strip(),
        "changed_row_evidence": "results/benchmarks/observations.csv and results/benchmarks/optional_10m/observations.csv; warmup=false; operation=comparison",
        "timing_evidence": "results/benchmarks/summary.csv and results/benchmarks/optional_10m/summary.csv; samples=3 excludes warmup; logical_database_copy has samples=1",
        "storage_evidence": "results/benchmarks/storage_summary.csv and results/benchmarks/optional_10m/storage_summary.csv; incremental bytes are the median of paired per-repetition differences in results/reports/storage_comparison.csv",
        "commands": [
            "python3 python/benchmark.py",
            "python3 python/persistence.py",
            "python3 python/report.py",
        ],
        "phase1_snapshot_and_branches": "results/functional/phase1/manifest.json",
        "persistence_tests": [row["test_id"] + " " + row["status"] for row in persistence],
        "evidence": [
            "results/functional/phase1",
            "results/functional/phase2",
            "results/functional/phase3",
            "results/benchmarks",
            "results/benchmarks/optional_10m",
            "results/functional/phase5/persistence_tests.csv",
            "results/reports",
            "results/REPORT.md",
        ],
    }
    (REPORTS / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def write_markdown(comparison, performance, persistence, matrix, acceptance):
    def increment_cell(size, system):
        hits = [
            row for row in comparison
            if row["comparison_class"] == "incremental_additional_state"
            and row["dataset_size"] == str(size) and row["system"] == system
        ]
        row = hits[0]
        median = int(row["median_bytes"])
        low = int(row["min_bytes"])
        high = int(row["max_bytes"])
        if low == high:
            return f"{median:,}"
        return f"{median:,} ({low:,}–{high:,})"

    def bytes_at(kind, size, system, percent=""):
        hits = [
            row for row in comparison
            if row["comparison_class"] == kind
            and row["dataset_size"] == str(size)
            and row["system"] == system
            and row["changed_percent"] == percent
        ]
        return int(hits[0]["median_bytes"])

    lines = [
        "# DuckDB Differential evaluation",
        "",
        "MVP v1.0 frozen baseline. The measurements and conclusions in this report are closed. S3, multi-host operation, and fault-injection testing require a separately versioned extension and must not change this evidence.",
        "",
        "This report consolidates the MVP evidence. Measurements come from the recorded CSV files. They describe this machine, these datasets, and these workloads.",
        "",
        "## Retained states",
        "",
        "Storage figures are comparable only when the retained states are named.",
        "",
        "The controlled workload keeps the same pair of states on both systems: the untouched source, and one diverged copy. On Differential that is the base branch plus the updated branch. On the conventional control that is the original database file plus the updated copy. Those rows are the equivalent-state comparison.",
        "",
        "The business workload does not keep the same pair. While both classification outputs exist, Differential retains three states: raw `main`, the baseline output, and the candidate output. The conventional control retains two transformed database files and does not keep a separate raw file.",
        "",
        "Removing the candidate still leaves different states. The conventional control then has one transformed database. Differential, after branch deletion, snapshot expiry, and local garbage collection, still retains the raw history and the baseline output. That checkpoint is a lifecycle comparison. It is not an equivalent-state comparison.",
        "",
        "## Storage",
        "",
        "Median bytes. The incremental rows are the bytes added by creating the Differential branches or the native physical copy. The later tables name the states those bytes retain.",
        "",
        "| Rows | Branch metadata added | Physical copy added |",
        "| --- | ---: | ---: |",
    ]
    for size in (10000, 100000, 1000000, 10000000):
        lines.append(
            f"| {size:,} | {increment_cell(size, 'differential')} "
            f"| {increment_cell(size, 'native')} |"
        )
    lines.extend([
        "",
        "Equivalent controlled states at 100 percent updated: untouched source plus the diverged copy.",
        "",
        "| Rows | Differential | Native original plus updated copy |",
        "| --- | ---: | ---: |",
    ])
    for size in (10000, 100000, 1000000, 10000000):
        lines.append(
            f"| {size:,} | {bytes_at('equivalent_source_plus_diverged', size, 'differential', '100'):,} "
            f"| {bytes_at('equivalent_source_plus_diverged', size, 'native', '100'):,} |"
        )
    lines.extend([
        "",
        "Business outputs present. Differential holds raw history plus both outputs. Native holds two transformed files.",
        "",
        "| Rows | Differential raw, baseline, and candidate | Native two transformed files |",
        "| --- | ---: | ---: |",
    ])
    for size in (10000, 100000, 1000000, 10000000):
        lines.append(
            f"| {size:,} | {bytes_at('business_outputs_present', size, 'differential'):,} "
            f"| {bytes_at('business_outputs_present', size, 'native'):,} |"
        )
    lines.extend([
        "",
        "After the candidate is removed. These are different retained states: Differential still holds raw history and baseline; native holds one transformed database.",
        "",
        "| Rows | Differential raw history and baseline | Native one transformed database |",
        "| --- | ---: | ---: |",
    ])
    for size in (10000, 100000, 1000000, 10000000):
        lines.append(
            f"| {size:,} | {bytes_at('after_candidate_removal', size, 'differential'):,} "
            f"| {bytes_at('after_candidate_removal', size, 'native'):,} |"
        )
    lines.extend([
        "",
        "Expiry did not change repository size at the measured checkpoints. Local garbage collection then deleted eligible objects. At 10,000 controlled rows the repository returned to the pre-update size. At larger controlled sizes the segment bytes returned to the pre-update segment size while `engine.sqlite` stayed slightly larger. At 100,000 rows, allocated space fell below the pre-update size and the original rows still read back. The garbage-collection command's `candidate_bytes` is not the directory delta.",
        "",
        "The complete checkpoint table is `results/benchmarks/storage_summary.csv` and `results/benchmarks/optional_10m/storage_summary.csv`. The classified extract is `results/reports/storage_comparison.csv`.",
        "",
        "## Performance",
        "",
        "Median milliseconds of three measured repetitions after one excluded warmup. Branch creation and copying are different operations.",
        "",
        "| Rows | Branch creation | Database copy |",
        "| --- | ---: | ---: |",
    ])
    for size in (10000, 100000, 1000000, 10000000):
        branch = timing(performance, size, "business", "", "differential", "branch_creation")
        copy = timing(performance, size, "business", "", "native", "database_copy")
        lines.append(f"| {size:,} | {ms(branch)} | {ms(copy)} |")
    lines.extend([
        "",
        "At 10,000,000 business rows, branch creation took 12.0 ms and copying took 78.2 ms. Copying was faster at 10,000 and 100,000 rows. The per-operation ranges are in `results/reports/performance_comparison.csv`.",
        "",
        "Business classification changed 1,986 of 10,000 rows, 19,975 of 100,000, 200,105 of 1,000,000, and 1,998,489 of 10,000,000. Both systems returned the same counts. The controlled workload changed exactly 1, 10, 50, and 100 percent of its own table. Those two workloads stayed separate.",
        "",
        "Required benchmark wall clock, including warmup and dataset generation, was 60.0 seconds. The 10,000,000-row run was 220.9 seconds. WAL and temporary files were 0 bytes after every closed process.",
        "",
        "## Persistence and recovery",
        "",
        "All persistence work used `experiment/persistence/`. The Phase 1–3 repositories were not opened.",
        "",
        "| Test | Class | Power loss | Status | Observed result |",
        "| --- | --- | --- | --- | --- |",
    ])
    for row in persistence:
        lines.append(
            f"| {row['test_id']} {row['scenario']} | {row['durability_class']} | {row['power_loss']} "
            f"| {row['status']} | {row['actual']} |"
        )
    lines.extend([
        "",
        "PR01 and PR02 are normal process restarts: the process exited 0 and a new process read the committed rows.",
        "",
        "PR03 and PR04 are controlled process termination after a commit. `CHECKPOINT` or `differential_create_snapshot` had returned, a marker file was written, and `SIGKILL` arrived during a later statement. The committed 100 rows and fingerprint `630e4e79ab397b2c5c06f3157d5fb9aa` were readable.",
        "",
        "PR05 and PR06 are controlled interruption during an `INSERT`. The previously committed 100 rows and the same fingerprint were readable after restart. The interrupted statement left 0 extra rows. That shows the open statement did not remain; it does not show that an in-progress write survives power loss.",
        "",
        "PR08 is power-loss durability. It was not tested. A clean exit and `SIGKILL` leave the operating-system page cache in place. PR07 is snapshot publication failure. `test_hooks` is `absent` on this release CLI, so no publication failure was injected.",
        "",
        "## Capability evidence",
        "",
        "| Capability | Status |",
        "| --- | --- |",
    ])
    for row in matrix:
        lines.append(f"| {row['capability']} | {row['status']} |")
    lines.extend([
        "",
        "Remote garbage collection remains UNVERIFIED. Metadata compaction remains DOCUMENTED. The detail and evidence paths are in `results/reports/capability_matrix.csv`.",
        "",
        "## Trace",
        "",
        "Dataset sizes, the 1/10/50/100 percent writes, the CLI identity, and the wall-clock totals are in `results/reports/manifest.json`. Changed-row counts are the `warmup=false` comparison rows in the observations CSVs. Operation times are the `samples=3` rows in the summary CSVs. `logical_database_copy` has one sample and is not the physical-copy measurement. The commands are `benchmark.py`, `persistence.py`, and `report.py`. Phase 1 snapshot and branch identifiers are in `results/functional/phase1/manifest.json`. Each disposable benchmark execution is mapped to the snapshot id recorded in its saved `branch_creation.sql` by `results/reports/benchmark_snapshots.csv`. The manifest records the CLI hash, the extension source commit, and SHA-256 hashes of the SQL files, `benchmark.py`, and `generate_data.py`. The evaluation directory itself is untracked, so those file hashes identify the workload revision.",
        "",
        "Storage totals are `state_storage_bytes` after the measured process has exited. Differential state is the repository directory plus the temp directory. Native state is the `.duckdb`, WAL, and temp files present then. WAL and temp were 0 bytes at every closed checkpoint. Absolute checkpoint tables use the median of three repetitions. The incremental table uses the median of the three paired repetition differences. At 10,000,000 rows those branch differences were 724,992, 749,568, and 765,952 bytes, so the median is 749,568. Subtracting the two checkpoint medians gives 765,952 and is not the median increment.",
        "",
        "Headline branch and copy times each come from one named operation, repeated three times after a warmup. They are different operations. The 10,000,000-row ranges are 11.7–12.5 ms and 77.6–79.1 ms. Some shorter operations have wide relative ranges; those ranges are in the summary CSVs.",
        "",
        "PR01 and PR02 are normal restarts. PR03 and PR04 are `SIGKILL` after a completed commit. PR05 and PR06 are `SIGKILL` during an insert. PR08 is the untested power-loss case. None of the executed rows has `power_loss=true`.",
        "",
        "LC01–LC12 are rows in `results/functional/phase3/findings.csv`. PR01–PR08 are rows in `results/functional/phase5/persistence_tests.csv`. OS01 is the row in `results/reports/not_executed.csv`. Phase 1, Phase 2, and benchmark classifications point at the result CSV named in `results/reports/capability_matrix.csv`.",
        "",
        "## Methodology",
        "",
        "DuckDB was the local v2.0.0 CLI recorded in `results/benchmarks/environment.json`, with Differential v1.0.0 built in. `differential_auto_gc` was false during controlled measurements. SQL time is an in-process timestamp delta. Copy time includes `fsync` of the destination. Storage was measured after the process exited and includes the Differential repository or the native database, WAL, and temporary files present at that moment.",
        "",
        "The business rules are the accepted baseline and candidate classification SQL. The controlled update is `row_id < size * percent / 100` on a separate table. One warmup was excluded. The median is the middle of three measured repetitions.",
        "",
        "## Limitations",
        "",
        "Results are limited to this environment and these workloads. Branch creation and a full file copy are different operations. Business storage compares three Differential states with two native files while both outputs exist, and raw-plus-baseline with one native file after candidate removal. The equivalent retained-state comparison is the controlled workload.",
        "",
        "Closed-process measurements do not include WAL or temporary files that existed only while DuckDB was running. Local garbage collection can reclaim more or less than the bytes added by the expired state, and `engine.sqlite` can remain larger. Remote garbage collection, metadata compaction, power loss, snapshot-publication failure, S3, shared writers, WAL shipping, and followers were not demonstrated here.",
        "",
        "## Findings",
        "",
        "Differential branch creation added substantially less storage than a conventional physical copy at every tested size. Total storage still depends on the dataset size and on which states are retained. Conventional copying was faster for the smaller files. At 10,000,000 business rows, branch creation took 12.0 ms and copying took 78.2 ms.",
        "",
        "Expiry alone did not reclaim storage. Local garbage collection reclaimed eligible objects. Metadata storage could remain slightly larger after cleanup. A normal restart and a `SIGKILL` after a completed commit both preserved the committed 100-row state. An interrupted insert did not leave its new rows. None of those process results is power-loss durability.",
        "",
        "## Acceptance criteria",
        "",
        "Every acceptance criterion has a row in `results/reports/acceptance_criteria.csv`. Local functional, lifecycle, benchmark, restart, committed-termination, and in-progress interruption checks were demonstrated. Power-loss durability and snapshot-publication failure remain explicit gaps under AC28.",
        "",
        "All 32 acceptance rows record that the required check was run. "
        "Power-loss durability and snapshot-publication failure remain unverified capabilities under AC28, as listed in the matrix.",
        "",
        "Further evaluation would be required before any claim about power loss, remote garbage collection, metadata compaction, or multi-host S3 operation.",
        "",
    ])
    (ROOT / "results" / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def checkpoint(storage, workload, system, size, percent, name):
    hits = [
        row for row in storage
        if row["workload"] == workload and row["system"] == system
        and row["dataset_size"] == str(size) and row["changed_percent"] == percent
        and row["checkpoint"] == name
    ]
    if len(hits) != 1:
        raise SystemExit(f"expected one checkpoint for {workload} {system} {size} {percent} {name}")
    return hits[0]


def state_row(storage, kind, workload, system, size, percent, name, retained):
    found = checkpoint(storage, workload, system, size, percent, name)
    return {
        "comparison_class": kind,
        "dataset_size": str(size),
        "changed_percent": percent,
        "system": system,
        "retained_states": retained,
        "checkpoint": name,
        "median_bytes": found["median_state_bytes"],
        "min_bytes": found["min_state_bytes"],
        "max_bytes": found["max_state_bytes"],
        "notes": "",
    }


def paired_delta(observations, size, system, retained, before_checkpoint, before_operation, after_checkpoint, after_operation, notes):
    before = paired_values(observations, size, system, before_checkpoint, before_operation)
    after = paired_values(observations, size, system, after_checkpoint, after_operation)
    deltas = sorted(after[repetition] - before[repetition] for repetition in before)
    return {
        "comparison_class": "incremental_additional_state",
        "dataset_size": str(size),
        "changed_percent": "",
        "system": system,
        "retained_states": retained,
        "checkpoint": "per_repetition_delta",
        "median_bytes": str(deltas[1]),
        "min_bytes": str(deltas[0]),
        "max_bytes": str(deltas[-1]),
        "notes": notes,
    }


def paired_values(observations, size, system, checkpoint, operation):
    rows = [
        row for row in observations
        if row["warmup"] == "false" and row["workload"] == "business"
        and row["dataset_size"] == str(size) and row["system"] == system
        and row["checkpoint"] == checkpoint and row["operation"] == operation
        and row["state_storage_bytes"] != ""
    ]
    values = {int(row["repetition"]): int(row["state_storage_bytes"]) for row in rows}
    if sorted(values) != [1, 2, 3]:
        raise SystemExit(f"expected repetitions 1..3 for {system} {size} {checkpoint}")
    return values


def timing(performance, size, workload, percent, system, operation):
    hits = [
        row for row in performance
        if row["dataset_size"] == str(size) and row["workload"] == workload
        and row["changed_percent"] == percent and row["system"] == system
        and row["operation"] == operation
    ]
    if len(hits) != 1:
        raise SystemExit(f"missing timing {size} {workload} {system} {operation}")
    return hits[0]


def ms(row):
    value = int(row["median_elapsed_ns"]) / 1e6
    return f"{value:.1f} ({int(row['min_elapsed_ns']) / 1e6:.1f}–{int(row['max_elapsed_ns']) / 1e6:.1f})"


def load(path):
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
