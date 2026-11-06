"""Phase 2 checks. Run: python3 experiment/tests/test_phase2.py"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from compare_outputs import compare
from experiment_runner import load_config

CONFIG = load_config(ROOT / "config" / "experiment.yaml")


def test_comparison():
    results = compare(
        duckdb_cli=Path(CONFIG["duckdb_cli"]),
        repository=Path(CONFIG["repository"]),
        database=str(CONFIG["database"]),
        results=ROOT / "results" / "functional" / "phase2",
    )
    assert results["result"] == "pass", results["failures"]
    summary = results["summary"]
    assert int(summary["added_records"]) == 0
    assert int(summary["missing_records"]) == 0
    assert (
        int(summary["added_records"])
        + int(summary["missing_records"])
        + int(summary["changed_records"])
        + int(summary["unchanged_records"])
        == int(summary["joined_rows"])
    )
    assert int(summary["baseline_rows"]) == int(summary["unchanged_records"]) + int(summary["changed_records"])
    assert int(summary["changed_records"]) == int(summary["rows_in_changed_band"])
    assert int(summary["changed_outside_band"]) == 0


def main():
    test_comparison()
    print("phase 2 tests passed")


if __name__ == "__main__":
    main()
