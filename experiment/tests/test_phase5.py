"""Phase 5 checks. Run from experiment/: python3 tests/test_phase5.py"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from experiment_runner import load_config, require_cli
from persistence import PROTECTED, run_persistence, tree_signature
from report import main as write_report

CLI = require_cli(Path(load_config(ROOT / "config" / "experiment.yaml")["duckdb_cli"]))


def test_persistence_classes_and_report():
    signatures = {path: tree_signature(path) for path in PROTECTED}
    rows = run_persistence(CLI)
    for path, signature in signatures.items():
        assert tree_signature(path) == signature
    by_id = {row["test_id"]: row for row in rows}
    assert by_id["PR01"]["durability_class"] == "normal_process_restart"
    assert by_id["PR04"]["durability_class"] == "process_termination_after_commit"
    assert by_id["PR06"]["durability_class"] == "process_interruption_during_statement"
    for test_id in ("PR01", "PR02", "PR03", "PR04", "PR05", "PR06"):
        assert by_id[test_id]["status"] == "DEMONSTRATED"
        assert by_id[test_id]["power_loss"] == "false"
        assert "630e4e79ab397b2c5c06f3157d5fb9aa" in by_id[test_id]["actual"]
    assert by_id["PR07"]["status"] == "UNVERIFIED"
    assert by_id["PR08"]["status"] == "UNVERIFIED"
    assert by_id["PR08"]["durability_class"] == "power_loss"
    write_report()
    report = (ROOT / "results" / "REPORT.md").read_text(encoding="utf-8")
    assert "untouched source, and one diverged copy" in report
    assert "raw history and the baseline output" in report
    assert "not an equivalent-state comparison" in report
    assert "749,568 (724,992–765,952)" in report
    assert "None of the executed rows has `power_loss=true`" in report
    assert "PR08 is power-loss durability" in report
    stored = list(csv.DictReader((ROOT / "results" / "reports" / "storage_comparison.csv").open()))
    classes = {row["comparison_class"] for row in stored}
    assert classes == {
        "incremental_additional_state",
        "equivalent_source_plus_diverged",
        "business_outputs_present",
        "after_candidate_removal",
    }
    matrix = list(csv.DictReader((ROOT / "results" / "reports" / "capability_matrix.csv").open()))
    statuses = {row["capability"]: row["status"] for row in matrix}
    assert statuses["Remote garbage collection"] == "UNVERIFIED"
    assert statuses["Metadata compaction"] == "DOCUMENTED"
    assert statuses["Power-loss durability"] == "UNVERIFIED"
    snapshots = list(csv.DictReader((ROOT / "results" / "reports" / "benchmark_snapshots.csv").open()))
    measured = [row for row in snapshots if row["warmup"] == "false"]
    assert {row["source_snapshot_id"] for row in measured} == {"1"}
    assert {row["source_snapshot_name"] for row in measured} == {"raw-input", "base"}
    manifest = json.loads((ROOT / "results" / "reports" / "manifest.json").read_text())
    assert manifest["extension_source_commit"]
    assert len(manifest["source_file_sha256"]["sql/comparison.sql"]) == 64
    assert manifest["duckdb_cli_sha256"]
    print("phase 5 checks passed")


if __name__ == "__main__":
    test_persistence_classes_and_report()
