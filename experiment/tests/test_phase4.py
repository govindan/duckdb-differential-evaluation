"""Phase 4 checks. Run from experiment/: python3 tests/test_phase4.py"""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from benchmark import PROTECTED, run_benchmark, tree_signature
from experiment_runner import load_config, require_cli

CLI = require_cli(Path(load_config(ROOT / "config" / "experiment.yaml")["duckdb_cli"]))


def test_small_benchmark_keeps_protected_data():
    signatures = {path: tree_signature(path) for path in PROTECTED}
    rows = run_benchmark(
        CLI,
        work_root=ROOT / "benchmark" / "quick",
        results=ROOT / "results" / "benchmarks" / "quick",
        sizes=(1000,),
        percents=(1, 10, 50, 100),
        reps=1,
        warmup=False,
    )
    for path, signature in signatures.items():
        assert tree_signature(path) == signature, path
    measured = [row for row in rows if row["warmup"] == "false"]
    business = [row for row in measured if row["workload"] == "business" and row["operation"] == "comparison"]
    assert {row["system"] for row in business} == {"differential", "native"}
    for row in business:
        assert row["changed_percent"] == ""
        assert int(row["added_records"]) == 0
        assert int(row["missing_records"]) == 0
        assert int(row["changed_records"]) + int(row["unchanged_records"]) == 1000
    controlled = [
        row for row in measured
        if row["workload"] == "controlled" and row["actual_changed_rows"] != ""
    ]
    seen = {(row["system"], int(row["changed_percent"])) for row in controlled}
    assert seen == {(system, percent) for system in ("differential", "native") for percent in (1, 10, 50, 100)}
    for row in controlled:
        assert int(row["actual_changed_rows"]) == 1000 * int(row["changed_percent"]) // 100
        assert int(row["intended_changed_rows"]) == int(row["actual_changed_rows"])
    checkpoints = ROOT / "results" / "benchmarks" / "quick" / "storage_summary.csv"
    with checkpoints.open(encoding="utf-8") as handle:
        stored = list(csv.DictReader(handle))
    labels = {(row["system"], row["checkpoint"]) for row in stored}
    assert ("differential", "before_branch") in labels
    assert ("differential", "after_branch") in labels
    assert ("differential", "after_candidate_snapshot") in labels
    assert ("differential", "after_branch_deletion") in labels
    assert ("differential", "after_expiry") in labels
    assert ("differential", "after_gc") in labels
    assert ("native", "after_copy") in labels
    assert ("native", "after_candidate_snapshot") in labels
    assert ("native", "after_database_cleanup") in labels
    print("phase 4 checks passed")


if __name__ == "__main__":
    test_small_benchmark_keeps_protected_data()
