"""Compare a saved Phase 1 database with the input file and the classification rules.

The transformation SQL is not the oracle. Labels are recalculated here from the
amounts read back from each branch, and raw rows are compared with the CSV.
"""

import argparse
import csv
import sys
from decimal import Decimal
from pathlib import Path

from experiment_runner import (
    attach_all,
    baseline_label,
    candidate_label,
    load_config,
    preamble,
    query,
    require_cli,
    resolve_repository,
    sql_literal,
    write_rows,
)
from generate_data import FIELDS

ROOT = Path(__file__).resolve().parents[1]
RAW_FIELDS = FIELDS


def main():
    parser = argparse.ArgumentParser(description="Verify persisted Phase 1 evidence")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "experiment.yaml")
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--database")
    parser.add_argument("--input", type=Path, dest="input_csv")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    evidence = args.evidence or (ROOT / "results" / "functional" / "phase1" / "verification_evidence.csv")
    checks = verify(
        duckdb_cli=Path(config["duckdb_cli"]),
        repository=args.repository or Path(config["repository"]),
        database=args.database or str(config["database"]),
        input_csv=args.input_csv or (ROOT / "data" / "transactions.csv"),
        evidence=evidence,
    )
    failed = [row for row in checks if row["result"] != "pass"]
    for row in checks:
        print(f"{row['result']}: {row['verification']} | {row['actual']}")
    if failed:
        raise SystemExit(f"{len(failed)} verification checks failed")


def verify(duckdb_cli, repository, database, input_csv, evidence):
    cli = require_cli(Path(duckdb_cli))
    repo = resolve_repository(Path(repository))
    input_csv = Path(input_csv)
    if not input_csv.is_absolute():
        input_csv = (ROOT / input_csv).resolve()
    evidence = Path(evidence)
    if not evidence.is_absolute():
        evidence = (ROOT / evidence).resolve()
    scripts = evidence.parent / "verification_scripts"
    log = []
    source = _read_input(input_csv)
    snapshots = query(cli, preamble(repo) + f"""
        SELECT snapshot_id, snapshot_name, snapshot_time, retired, branch_id, database_id
        FROM differential_snapshots({sql_literal(database)})
        ORDER BY snapshot_id;
    """, scripts / "snapshots.sql", log)
    branches = query(cli, preamble(repo) + f"""
        SELECT branch_name, branch_id, state, head_snapshot_id, source_snapshot_id, database_id
        FROM differential_branches({sql_literal(database)})
        ORDER BY branch_name;
    """, scripts / "branches.sql", log)
    raw_rows = query(cli, preamble(repo) + attach_all(database) + """
        SELECT branch, transaction_id, customer_id, transaction_date, account_id,
               transaction_type, currency, transaction_amount
        FROM (
            SELECT 'main' AS branch, transaction_id, customer_id,
                   CAST(transaction_date AS VARCHAR) AS transaction_date,
                   account_id, transaction_type, currency,
                   printf('%.2f', transaction_amount) AS transaction_amount
            FROM main_raw.transactions
            UNION ALL
            SELECT 'baseline', transaction_id, customer_id,
                   CAST(transaction_date AS VARCHAR),
                   account_id, transaction_type, currency,
                   printf('%.2f', transaction_amount)
            FROM baseline.transactions
            UNION ALL
            SELECT 'candidate', transaction_id, customer_id,
                   CAST(transaction_date AS VARCHAR),
                   account_id, transaction_type, currency,
                   printf('%.2f', transaction_amount)
            FROM candidate.transactions
        )
        ORDER BY branch, transaction_id;
    """, scripts / "raw_rows.sql", log)
    labels = query(cli, preamble(repo) + attach_all(database) + """
        SELECT 'baseline' AS branch, transaction_id, classification
        FROM baseline.classification
        UNION ALL
        SELECT 'candidate', transaction_id, classification
        FROM candidate.classification
        ORDER BY branch, transaction_id;
    """, scripts / "labels.sql", log)
    stored = {
        branch: _index_raw(raw_rows, branch)
        for branch in ("main", "baseline", "candidate")
    }
    classified = {
        "baseline": _index_labels(labels, "baseline"),
        "candidate": _index_labels(labels, "candidate"),
    }
    checks = _checks(source, snapshots, branches, stored, classified)
    write_rows(evidence, checks)
    return checks


def _checks(source, snapshots, branches, stored, classified):
    active = [row for row in snapshots if str(row["retired"]).lower() == "false"]
    named = [row for row in active if row["snapshot_name"] == "raw-input"]
    one_snapshot = len(snapshots) == 1 and len(named) == 1
    snapshot = named[0] if named else {}
    snapshot_id = snapshot.get("snapshot_id", "")
    by_name = {row["branch_name"]: row for row in branches}
    baseline = by_name.get("baseline", {})
    candidate = by_name.get("candidate", {})
    baseline_from_snapshot = _from_common_snapshot(baseline, snapshot_id)
    candidate_from_snapshot = _from_common_snapshot(candidate, snapshot_id)
    counts = {name: len(rows) for name, rows in stored.items()}
    counts["input"] = len(source)
    identical_count = len(set(counts.values())) == 1 and counts["input"] > 0
    key_sets = {name: set(rows) for name, rows in stored.items()}
    key_sets["input"] = set(source)
    unique = all(len(rows) == len(set(rows)) for rows in stored.values()) and len(source) == len(set(source))
    identical_keys = len(set(frozenset(keys) for keys in key_sets.values())) == 1 and unique
    identical_contents = all(rows == source for rows in stored.values())
    baseline_mismatches = _label_mismatches(stored["baseline"], classified["baseline"], baseline_label)
    candidate_mismatches = _label_mismatches(stored["candidate"], classified["candidate"], candidate_label)
    disagree = [
        transaction_id
        for transaction_id, raw in source.items()
        if baseline_label(_amount(raw)) != candidate_label(_amount(raw))
    ]
    integrity_mismatches = [
        transaction_id
        for transaction_id in disagree
        if classified["baseline"].get(transaction_id) != baseline_label(_amount(source[transaction_id]))
    ]
    return [
        _row(
            "Common snapshot",
            "One identifiable snapshot",
            one_snapshot,
            _snapshot_text(snapshot, len(snapshots)),
        ),
        _row(
            "Baseline branch",
            "Created from common snapshot",
            baseline_from_snapshot,
            _branch_text(baseline, snapshot_id),
        ),
        _row(
            "Candidate branch",
            "Created from common snapshot",
            candidate_from_snapshot,
            _branch_text(candidate, snapshot_id),
        ),
        _row(
            "Raw input count",
            "Identical",
            identical_count,
            f"input={counts['input']}, main={counts['main']}, baseline={counts['baseline']}, candidate={counts['candidate']}",
        ),
        _row(
            "Raw transaction keys",
            "Identical and unique",
            identical_keys,
            f"unique={unique}, input_keys={len(key_sets['input'])}, "
            f"main_keys={len(key_sets['main'])}, baseline_keys={len(key_sets['baseline'])}, "
            f"candidate_keys={len(key_sets['candidate'])}",
        ),
        _row(
            "Raw input contents",
            "Identical",
            identical_contents,
            f"field mismatches: main={_content_mismatches(source, stored['main'])}, "
            f"baseline={_content_mismatches(source, stored['baseline'])}, "
            f"candidate={_content_mismatches(source, stored['candidate'])}",
        ),
        _row(
            "Baseline output",
            "Original classification applied",
            not baseline_mismatches and len(classified["baseline"]) == len(source),
            f"rows={len(classified['baseline'])}, rule_mismatches={len(baseline_mismatches)}",
        ),
        _row(
            "Candidate output",
            "Modified classification applied",
            not candidate_mismatches and len(classified["candidate"]) == len(source),
            f"rows={len(classified['candidate'])}, rule_mismatches={len(candidate_mismatches)}",
        ),
        _row(
            "Baseline integrity",
            "Unchanged after candidate processing",
            not integrity_mismatches and not baseline_mismatches,
            f"rows_where_rules_differ={len(disagree)}, "
            f"baseline_rows_changed_to_candidate_rule={len(integrity_mismatches)}",
        ),
    ]


def _read_input(path):
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {row["transaction_id"]: tuple(row[field] for field in RAW_FIELDS) for row in rows}


def _index_raw(rows, branch):
    return {
        row["transaction_id"]: tuple(row[field] for field in RAW_FIELDS)
        for row in rows
        if row["branch"] == branch
    }


def _index_labels(rows, branch):
    return {
        row["transaction_id"]: row["classification"]
        for row in rows
        if row["branch"] == branch
    }


def _label_mismatches(raw_rows, labels, rule):
    mismatches = []
    if set(raw_rows) != set(labels):
        mismatches.append("<key-set>")
    for transaction_id, raw in raw_rows.items():
        if labels.get(transaction_id) != rule(_amount(raw)):
            mismatches.append(transaction_id)
    return mismatches


def _content_mismatches(source, stored):
    if set(source) != set(stored):
        return len(set(source).symmetric_difference(stored))
    return sum(1 for key, value in source.items() if stored[key] != value)


def _amount(raw):
    return Decimal(raw[RAW_FIELDS.index("transaction_amount")])


def _snapshot_text(snapshot, count):
    if not snapshot:
        return f"snapshots={count}, raw-input snapshot not found"
    return (
        f"snapshots={count}, snapshot_id={snapshot['snapshot_id']}, "
        f"name={snapshot['snapshot_name']}, time={snapshot['snapshot_time']}, "
        f"database_id={snapshot['database_id']}, retired={snapshot['retired']}"
    )


def _from_common_snapshot(branch, snapshot_id):
    return (
        branch.get("state") == "active"
        and snapshot_id != ""
        and branch.get("source_snapshot_id") == snapshot_id
    )


def _branch_text(branch, snapshot_id):
    if not branch:
        return "branch not found"
    return (
        f"branch_id={branch['branch_id']}, state={branch['state']}, "
        f"source_snapshot_id={branch['source_snapshot_id']}, "
        f"head_snapshot_id={branch['head_snapshot_id']}, common_snapshot_id={snapshot_id}"
    )


def _row(verification, expected, passed, actual):
    return {
        "verification": verification,
        "expected": expected,
        "actual": actual,
        "result": "pass" if passed else "fail",
    }


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(exc, file=sys.stderr)
        raise
