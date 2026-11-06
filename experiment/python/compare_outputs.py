"""Phase 2: compare baseline and candidate classifications with SQL."""

import json
import sys
from pathlib import Path

from experiment_runner import (
    attach_all,
    load_config,
    one,
    preamble,
    query,
    require_cli,
    resolve_repository,
    sql_literal,
    write_rows,
)

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COLUMNS = (
    ("transaction_id", "VARCHAR"),
    ("classification", "VARCHAR"),
)
EXPECTED_BOUNDARIES = (
    ("BND-999.99", "999.99", "LOW", "LOW", "unchanged"),
    ("BND-1000.00", "1000.00", "MEDIUM", "MEDIUM", "unchanged"),
    ("BND-4999.99", "4999.99", "MEDIUM", "MEDIUM", "unchanged"),
    ("BND-5000.00", "5000.00", "MEDIUM", "HIGH", "changed"),
    ("BND-9999.99", "9999.99", "MEDIUM", "HIGH", "changed"),
    ("BND-10000.00", "10000.00", "HIGH", "HIGH", "unchanged"),
)


def main():
    config = load_config(ROOT / "config" / "experiment.yaml")
    results = compare(
        duckdb_cli=Path(config["duckdb_cli"]),
        repository=Path(config["repository"]),
        database=str(config["database"]),
        results=ROOT / "results" / "functional" / "phase2",
    )
    print(json.dumps(results["summary"], indent=2))
    if results["result"] != "pass":
        raise SystemExit("phase 2 comparison failed")


def compare(duckdb_cli, repository, database, results):
    cli = require_cli(Path(duckdb_cli))
    repo = resolve_repository(Path(repository))
    results = Path(results)
    if not results.is_absolute():
        results = (ROOT / results).resolve()
    scripts = results / "scripts"
    log = []
    prefix = preamble(repo) + attach_all(database)
    columns = query(cli, prefix + """
        SELECT table_catalog, column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'classification'
          AND table_catalog IN ('baseline', 'candidate')
        ORDER BY table_catalog, ordinal_position;
    """, scripts / "columns.sql", log)
    branches = query(cli, prefix + f"""
        SELECT branch_name, source_snapshot_id
        FROM differential_branches({sql_literal(database)})
        WHERE branch_name IN ('baseline', 'candidate')
        ORDER BY branch_name;
    """, scripts / "source_snapshot.sql", log)
    summary = one(cli, prefix + (ROOT / "sql" / "comparison.sql").read_text(encoding="utf-8"),
                  scripts / "comparison.sql", log)
    transitions = query(cli, prefix + (ROOT / "sql" / "classification_transitions.sql").read_text(encoding="utf-8"),
                        scripts / "transitions.sql", log)
    boundaries = query(cli, prefix + (ROOT / "sql" / "boundary_comparison.sql").read_text(encoding="utf-8"),
                       scripts / "boundaries.sql", log)
    failures = _failures(columns, branches, summary, boundaries)
    write_rows(results / "comparison.csv", [summary])
    write_rows(results / "transitions.csv", transitions)
    write_rows(results / "boundaries.csv", boundaries)
    (results / "failures.txt").write_text("\n".join(failures) + ("\n" if failures else ""), encoding="utf-8")
    (results / "commands.log").write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
    return {"result": "fail" if failures else "pass", "summary": summary, "failures": failures}


def _failures(columns, branches, summary, boundaries):
    failures = []
    for catalog in ("baseline", "candidate"):
        actual = [(row["column_name"], row["data_type"]) for row in columns if row["table_catalog"] == catalog]
        if actual != list(EXPECTED_COLUMNS):
            failures.append(f"{catalog} columns are {actual}")
    sources = {row["branch_name"]: row["source_snapshot_id"] for row in branches}
    if sources.get("baseline") != sources.get("candidate") or not sources.get("baseline"):
        failures.append(f"branches do not share one source snapshot: {sources}")
    baseline_rows = int(summary["baseline_rows"])
    candidate_rows = int(summary["candidate_rows"])
    added = int(summary["added_records"])
    missing = int(summary["missing_records"])
    changed = int(summary["changed_records"])
    unchanged = int(summary["unchanged_records"])
    if added + missing + changed + unchanged != int(summary["joined_rows"]):
        failures.append("added, missing, changed and unchanged do not partition the full outer join")
    if baseline_rows != unchanged + changed + missing:
        failures.append("baseline row count is not unchanged + changed + missing")
    if candidate_rows != unchanged + changed + added:
        failures.append("candidate row count is not unchanged + changed + added")
    if int(summary["baseline_duplicate_keys"]) != 0 or int(summary["candidate_duplicate_keys"]) != 0:
        failures.append("duplicate output keys")
    if int(summary["amount_mismatches"]) != 0:
        failures.append("compared rows do not share the same raw amount")
    if changed != int(summary["rows_in_changed_band"]) or changed != int(summary["medium_to_high_in_band"]):
        failures.append("changed records are not exactly the MEDIUM to HIGH rows in [5000, 10000)")
    if int(summary["changed_outside_band"]) != 0 or int(summary["changed_other_transition"]) != 0:
        failures.append("a change falls outside the expected transition")
    actual_boundaries = {
        row["transaction_id"]: (
            row["transaction_amount"],
            row["baseline_classification"],
            row["candidate_classification"],
            row["comparison"],
        )
        for row in boundaries
    }
    for transaction_id, amount, baseline_label, candidate_label, comparison in EXPECTED_BOUNDARIES:
        if actual_boundaries.get(transaction_id) != (amount, baseline_label, candidate_label, comparison):
            failures.append(
                f"{transaction_id} is {actual_boundaries.get(transaction_id)}, "
                f"expected {(amount, baseline_label, candidate_label, comparison)}"
            )
    return failures


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(exc, file=sys.stderr)
        raise
