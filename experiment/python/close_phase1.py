"""Recompute Phase 1 fingerprints after candidate processing.

The baseline fingerprint recorded in the manifest was calculated by baseline_count.sql
before candidate.sql ran. This compares that saved value, and the pre-transformation
raw fingerprint, with the database as it stands now.
"""

import json
import sys
from pathlib import Path

from experiment_runner import (
    CLASS_FINGERPRINT,
    RAW_FINGERPRINT,
    attach_all,
    load_config,
    one,
    preamble,
    require_cli,
    resolve_repository,
    write_rows,
)

ROOT = Path(__file__).resolve().parents[1]


def main():
    config = load_config(ROOT / "config" / "experiment.yaml")
    manifest_path = ROOT / "results" / "functional" / "phase1" / "manifest.json"
    evidence = ROOT / "results" / "functional" / "phase1" / "closure_checks.csv"
    checks = close_phase1(
        duckdb_cli=Path(config["duckdb_cli"]),
        repository=Path(config["repository"]),
        database=str(config["database"]),
        manifest_path=manifest_path,
        evidence=evidence,
    )
    failed = [row for row in checks if row["result"] != "pass"]
    for row in checks:
        print(f"{row['result']}: {row['check']} | before={row['before']} after={row['after']}")
    if failed:
        raise SystemExit(f"{len(failed)} phase 1 closure checks failed")
    print("phase 1 complete")


def close_phase1(duckdb_cli, repository, database, manifest_path, evidence):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    cli = require_cli(Path(duckdb_cli))
    repo = resolve_repository(Path(repository))
    before_output = manifest["baseline_classification_fingerprint"]
    before_raw = manifest["raw_verification"]["main_fingerprint"]
    raw_before = {
        "main": manifest["raw_verification"]["main_fingerprint"],
        "baseline": manifest["raw_verification"]["baseline_fingerprint"],
        "candidate": manifest["raw_verification"]["candidate_fingerprint"],
    }
    if len(set(raw_before.values())) != 1:
        raise SystemExit(f"pre-transformation raw fingerprints differ: {raw_before}")
    snapshot_id = int(manifest["snapshot"]["snapshot_id"])
    current = one(cli, preamble(repo) + attach_all(database) + f"""
        SELECT
            (SELECT md5(string_agg({CLASS_FINGERPRINT}, chr(10) ORDER BY transaction_id))
             FROM baseline.classification) AS baseline_output_after,
            (SELECT count(*) FROM baseline.classification) AS baseline_output_rows,
            (SELECT md5(string_agg({RAW_FINGERPRINT}, chr(10) ORDER BY transaction_id))
             FROM main_raw.transactions) AS main_raw_after,
            (SELECT md5(string_agg({RAW_FINGERPRINT}, chr(10) ORDER BY transaction_id))
             FROM baseline.transactions) AS baseline_raw_after,
            (SELECT md5(string_agg({RAW_FINGERPRINT}, chr(10) ORDER BY transaction_id))
             FROM candidate.transactions) AS candidate_raw_after,
            (SELECT md5(string_agg({RAW_FINGERPRINT}, chr(10) ORDER BY transaction_id))
             FROM main_raw.transactions AT (VERSION => {snapshot_id})) AS snapshot_raw_after;
    """, evidence.parent / "closure_scripts" / "fingerprints.sql", [])
    checks = [
        {
            "check": "Baseline output fingerprint unchanged after candidate processing",
            "before": before_output,
            "after": current["baseline_output_after"],
            "result": "pass" if before_output == current["baseline_output_after"] else "fail",
        },
        {
            "check": "Raw input and shared snapshot unchanged after candidate processing",
            "before": before_raw,
            "after": (
                f"main={current['main_raw_after']}, baseline={current['baseline_raw_after']}, "
                f"candidate={current['candidate_raw_after']}, snapshot={current['snapshot_raw_after']}"
            ),
            "result": "pass" if {
                current["main_raw_after"],
                current["baseline_raw_after"],
                current["candidate_raw_after"],
                current["snapshot_raw_after"],
                before_raw,
            } == {before_raw} else "fail",
        },
    ]
    write_rows(evidence, checks)
    return checks


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(exc, file=sys.stderr)
        raise
