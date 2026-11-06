"""Phase 3 checks. Run: python3 experiment/tests/test_phase3.py"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from experiment_runner import load_config
from lifecycle import disposable_repository, run_lifecycle

CONFIG = load_config(ROOT / "config" / "experiment.yaml")
DEMONSTRATED = {
    "LC01", "LC02", "LC03", "LC04", "LC05", "LC06", "LC07", "LC08", "LC09", "LC10",
}


def test_refuses_primary_repository():
    try:
        disposable_repository(ROOT / "repository")
    except SystemExit as exc:
        assert "refusing" in str(exc.code)
        return
    raise AssertionError("primary repository was accepted")


def test_lifecycle():
    evidence = run_lifecycle(Path(CONFIG["duckdb_cli"]))
    assert evidence["primary_unchanged"]
    by_id = {row["test_id"]: row for row in evidence["findings"]}
    assert set(DEMONSTRATED) <= set(by_id)
    for test_id in DEMONSTRATED:
        assert by_id[test_id]["status"] == "DEMONSTRATED", by_id[test_id]
    assert by_id["LC11"]["status"] == "UNVERIFIED"
    assert by_id["LC12"]["status"] == "DOCUMENTED"
    labels = [row["label"] for row in evidence["storage"]]
    assert "after_bulk_snapshot" in labels
    assert "after_bulk_expiry" in labels
    assert "after_gc" in labels


def main():
    test_refuses_primary_repository()
    test_lifecycle()
    print("phase 3 tests passed")


if __name__ == "__main__":
    main()
