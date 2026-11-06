"""Phase 1 checks. Run: python3 tests/test_phase1.py"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from experiment_runner import load_config, resolve_repository, run_experiment
from generate_data import build_rows, canonical_checksum
from verify_evidence import verify

CLI = Path(load_config(ROOT / "config" / "experiment.yaml")["duckdb_cli"])


def test_generation_repeats():
    first = build_rows(10_000, 20261106, "AUD")
    second = build_rows(10_000, 20261106, "AUD")
    assert first == second
    assert canonical_checksum(first) == canonical_checksum(second)
    assert canonical_checksum(build_rows(10_000, 20261107, "AUD")) != canonical_checksum(first)
    amounts = {row["transaction_id"]: row["transaction_amount"] for row in first}
    assert amounts["BND-999.99"] == "999.99"
    assert amounts["BND-1000.00"] == "1000.00"
    assert amounts["BND-4999.99"] == "4999.99"
    assert amounts["BND-5000.00"] == "5000.00"
    assert amounts["BND-9999.99"] == "9999.99"
    assert amounts["BND-10000.00"] == "10000.00"
    assert len(first) == 10_000
    assert len({row["transaction_id"] for row in first}) == 10_000


def test_repository_guard():
    for path in (
        Path.home() / ".duckdb" / "differential",
        ROOT.parent / "build" / "release" / "repository",
    ):
        try:
            resolve_repository(path)
        except SystemExit as exc:
            message = str(exc.code if exc.code not in (0, None) else exc)
            assert "refusing" in message
            continue
        raise AssertionError(f"repository guard accepted {path}")


def test_repeated_workflow():
    repo = ROOT / "test" / "phase1"
    if repo.exists():
        shutil.rmtree(repo)
    manifests = []
    for name in ("bank_a", "bank_b"):
        results = ROOT / "results" / "functional" / f"repeat_{name}"
        if results.exists():
            shutil.rmtree(results)
        manifests.append(run_experiment(
            duckdb_cli=CLI,
            repository=repo,
            database=name,
            dataset_size=10_000,
            seed=20261106,
            currency="AUD",
            results=results,
            data_csv=ROOT / "test" / f"{name}.csv",
        ))
    first, second = manifests
    for manifest, name in ((first, "bank_a"), (second, "bank_b")):
        checks = verify(
            duckdb_cli=CLI,
            repository=repo,
            database=name,
            input_csv=ROOT / "test" / f"{name}.csv",
            evidence=ROOT / "results" / "functional" / f"repeat_{name}" / "verification_evidence.csv",
        )
        failed = [row["verification"] for row in checks if row["result"] != "pass"]
        assert not failed, failed
    assert first["input_checksum_sha256"] == second["input_checksum_sha256"]
    assert first["raw_verification"]["main_fingerprint"] == second["raw_verification"]["main_fingerprint"]
    assert first["baseline_classification_fingerprint"] == second["baseline_classification_fingerprint"]
    assert first["candidate_classification_fingerprint"] == second["candidate_classification_fingerprint"]
    assert first["baseline_classification_fingerprint"] != first["candidate_classification_fingerprint"]
    for manifest in manifests:
        snapshot_id = manifest["snapshot"]["snapshot_id"]
        assert manifest["branches"]["baseline"]["snapshot_id"] == snapshot_id
        assert manifest["branches"]["candidate"]["snapshot_id"] == snapshot_id
        assert manifest["raw_verification"]["branches_from_snapshot"] == "2"
        assert manifest["isolation"]["main_classification_tables"] == "0"
        assert manifest["isolation"]["baseline_classification_tables"] == "1"
        assert manifest["isolation"]["candidate_classification_tables"] == "1"
        assert manifest["differential_auto_gc_setting"] == "false"


def main():
    test_generation_repeats()
    test_repository_guard()
    test_repeated_workflow()
    print("phase 1 tests passed")


if __name__ == "__main__":
    main()
