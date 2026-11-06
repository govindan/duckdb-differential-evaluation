"""Phase 1: load one raw snapshot, branch baseline and candidate, transform each.

DuckDB is the locally built v2.0.0 CLI. This module does not import a DuckDB
Python package. Snapshot expiry and garbage collection belong to a later phase.
"""

import argparse
import csv
import io
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from generate_data import BOUNDARIES, build_rows, canonical_checksum, write_csv

ROOT = Path(__file__).resolve().parents[1]
PHASE1_MAX_ROWS = 10_000
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
RAW_FINGERPRINT = (
    "transaction_id || '|' || customer_id || '|' || CAST(transaction_date AS VARCHAR)"
    " || '|' || account_id || '|' || transaction_type || '|' || currency"
    " || '|' || printf('%.2f', transaction_amount)"
)
CLASS_FINGERPRINT = "transaction_id || '|' || classification"


def main():
    parser = argparse.ArgumentParser(description="Run the phase 1 Differential workflow")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "experiment.yaml")
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--database")
    parser.add_argument("--dataset-size", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--data", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    repository = args.repository or Path(config["repository"])
    results = args.results or Path(config["results"])
    data = args.data or (ROOT / "data" / "transactions.csv")
    manifest = run_experiment(
        duckdb_cli=Path(config["duckdb_cli"]),
        repository=repository,
        database=args.database or str(config["database"]),
        dataset_size=args.dataset_size if args.dataset_size is not None else int(config["dataset_size"]),
        seed=args.seed if args.seed is not None else int(config["seed"]),
        currency=str(config["currency"]),
        results=results,
        data_csv=data,
    )
    print(json.dumps({
        "status": manifest["status"],
        "database": manifest["database"],
        "snapshot_id": manifest["snapshot"]["snapshot_id"],
        "results": manifest["results_dir"],
    }, indent=2))


def run_experiment(duckdb_cli, repository, database, dataset_size, seed, currency, results, data_csv):
    started = datetime.now(timezone.utc)
    cli = require_cli(Path(duckdb_cli))
    repo = resolve_repository(Path(repository))
    database = require_name(database, "database")
    if not 6 <= dataset_size <= PHASE1_MAX_ROWS:
        raise SystemExit(f"phase 1 dataset size must be 6..{PHASE1_MAX_ROWS}")
    results = resolve_under(ROOT, Path(results))
    data_csv = resolve_under(ROOT, Path(data_csv))
    results.mkdir(parents=True, exist_ok=True)
    scripts = results / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    log = []
    manifest = {
        "phase": 1,
        "status": "failed",
        "started_at": started.isoformat(),
        "database": database,
        "dataset_size": dataset_size,
        "seed": seed,
        "currency": currency,
        "differential_auto_gc": False,
        "duckdb_cli": str(cli),
        "repository": str(repo),
        "results_dir": str(results),
        "os": platform.platform(),
        "architecture": platform.machine(),
    }
    try:
        version = cli_version(cli)
        if "v2.0.0" not in version:
            raise SystemExit(f"refusing DuckDB CLI version {version}")
        manifest["duckdb_version"] = version
        rows = build_rows(dataset_size, seed, currency)
        checksum = write_csv(rows, data_csv)
        if canonical_checksum(rows) != checksum:
            raise SystemExit("written dataset checksum does not match the generated rows")
        manifest["input_checksum_sha256"] = checksum
        manifest["input_csv"] = str(data_csv)
        identity = session_identity(cli, repo, scripts, log)
        manifest["differential_version"] = identity["extension_version"]
        manifest["differential_auto_gc_setting"] = identity["auto_gc"]
        if str(identity["auto_gc"]).lower() not in ("false", "0"):
            raise SystemExit(f"differential_auto_gc is {identity['auto_gc']}")
        if Path(identity["repository"]).resolve() != repo:
            raise SystemExit("repository setting does not match the experiment repository")
        existing = database_names(cli, repo, scripts, log)
        if database in existing:
            raise SystemExit(f"database {database} already exists in {repo}; refusing to modify it")
        loaded = load_raw(cli, repo, database, data_csv, scripts, log)
        if int(loaded["loaded_rows"]) != dataset_size or int(loaded["keys"]) != dataset_size:
            raise SystemExit(f"loaded row check failed: {loaded}")
        snapshot = create_snapshot_for(cli, repo, database, scripts, log)
        branches = create_branches(cli, repo, database, int(snapshot["snapshot_id"]), scripts, log)
        verification = verify_raw(cli, repo, database, dataset_size, int(snapshot["snapshot_id"]), scripts, log)
        write_rows(results / "raw_verification.csv", [verification])
        manifest["snapshot"] = snapshot
        manifest["branches"] = branches
        manifest["raw_verification"] = verification
        baseline_fp = transform(
            cli, repo, database, dataset_size, scripts / "baseline.sql",
            ROOT / "sql" / "baseline_transformation.sql", "baseline", log,
        )
        candidate_fp = transform(
            cli, repo, database, dataset_size, scripts / "candidate.sql",
            ROOT / "sql" / "candidate_transformation.sql", "candidate", log,
        )
        isolation = verify_isolation(
            cli, repo, database, dataset_size, verification, baseline_fp, candidate_fp, scripts, log,
        )
        boundaries = boundary_rows(cli, repo, database, scripts, log)
        check_boundary_labels(boundaries)
        histograms = {
            "baseline": class_histogram(cli, repo, database, "baseline", scripts, log),
            "candidate": class_histogram(cli, repo, database, "candidate", scripts, log),
        }
        write_rows(results / "isolation.csv", [isolation])
        write_rows(results / "boundary_rows.csv", boundaries)
        write_rows(results / "baseline_classes.csv", histograms["baseline"])
        write_rows(results / "candidate_classes.csv", histograms["candidate"])
        manifest["baseline_classification_fingerprint"] = baseline_fp
        manifest["candidate_classification_fingerprint"] = candidate_fp
        manifest["isolation"] = isolation
        manifest["class_counts"] = {
            "baseline": {row["classification"]: int(row["n"]) for row in histograms["baseline"]},
            "candidate": {row["classification"]: int(row["n"]) for row in histograms["candidate"]},
        }
        manifest["status"] = "passed"
    except (Exception, SystemExit) as exc:
        detail = exc.code if isinstance(exc, SystemExit) and exc.code not in (0, None) else exc
        if isinstance(exc, SystemExit) and exc.code in (0, None):
            raise
        manifest["error"] = str(detail)
        (results / "error.txt").write_text(str(detail) + "\n", encoding="utf-8")
        raise
    finally:
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        (results / "commands.log").write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
        (results / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def load_config(path):
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    data = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip("'").strip('"')
        if re.fullmatch(r"-?\d+", value):
            value = int(value)
        data[key.strip()] = value
    override = os.environ.get("DUCKDB_CLI")
    if override:
        data["duckdb_cli"] = override
    required = ["duckdb_cli", "repository", "database", "dataset_size", "seed", "currency", "results"]
    missing = [key for key in required if key not in data]
    if missing:
        raise SystemExit(f"config missing {', '.join(missing)}")
    return data


def require_cli(path):
    path = Path(path)
    if not path.is_absolute():
        candidates = [ROOT / path, ROOT.parent / path, ROOT.parent.parent / path]
        path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
    path = path.resolve()
    text = str(path)
    if "homebrew" in text or "anaconda" in text or "conda" in text:
        raise SystemExit(f"refusing DuckDB CLI at {path}")
    if not path.is_file():
        raise SystemExit(f"DuckDB CLI not found: {path}")
    return path


def cli_version(cli):
    proc = subprocess.run(
        [str(cli), "-no-init", "-no-agent", "-version"],
        check=False, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "duckdb -version failed")
    return proc.stdout.strip()


def resolve_repository(path):
    repo = resolve_under(ROOT, path)
    if repo == ROOT or ROOT not in repo.parents:
        raise SystemExit(f"refusing repository outside {ROOT}: {repo}")
    for name in ("config", "python", "sql", "tests"):
        source = (ROOT / name).resolve()
        if repo == source or source in repo.parents:
            raise SystemExit(f"refusing to store Differential data inside {source}")
    default = (Path.home() / ".duckdb" / "differential").resolve()
    if repo == default or default in repo.parents or repo in default.parents:
        raise SystemExit(f"refusing pre-existing Differential repository {default}")
    parts = repo.parts
    for index in range(len(parts) - 2):
        if parts[index:index + 3] == ("build", "release", "repository"):
            raise SystemExit(f"refusing Differential build repository {repo}")
    return repo


def resolve_under(root, path):
    path = Path(path)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def require_name(value, label):
    if not NAME_RE.fullmatch(value):
        raise SystemExit(f"invalid {label}: {value}")
    return value


def session_identity(cli, repo, scripts, log):
    version = one(cli, preamble(repo) + """
        SELECT version() AS duckdb_version,
               current_setting('differential_auto_gc') AS auto_gc,
               current_setting('differential_repository') AS repository;
    """, scripts / "identity.sql", log)
    extension = one(cli, preamble(repo) + """
        SELECT extension_version
        FROM duckdb_extensions()
        WHERE extension_name = 'differential';
    """, scripts / "extension.sql", log)
    version["extension_version"] = extension["extension_version"]
    return version


def database_names(cli, repo, scripts, log):
    rows = query(cli, preamble(repo) + "SELECT database_name FROM differential_databases();",
                 scripts / "databases.sql", log)
    return [row["database_name"] for row in rows]


def load_raw(cli, repo, database, data_csv, scripts, log):
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    execute(cli, preamble(repo) + attach_main(database) + schema, scripts / "schema.sql", log)
    execute(
        cli,
        preamble(repo) + attach_main(database)
        + f"COPY main_raw.transactions FROM {sql_literal(str(data_csv))} (HEADER true);\n",
        scripts / "copy.sql",
        log,
    )
    return one(cli, preamble(repo) + attach_main(database) + """
        SELECT count(*) AS loaded_rows, count(DISTINCT transaction_id) AS keys
        FROM main_raw.transactions;
    """, scripts / "load_count.sql", log)


def create_snapshot_for(cli, repo, database, scripts, log):
    sql = preamble(repo) + attach_main(database) + """
        SELECT operation_id, database_id, branch_id, snapshot_id, state, export_state, snapshot_time
        FROM differential_create_snapshot(
            'main_raw',
            name => 'raw-input',
            author => 'phase1',
            message => 'raw banking transactions'
        );
    """
    return one(cli, sql, scripts / "snapshot.sql", log)


def create_branches(cli, repo, database, snapshot_id, scripts, log):
    created = {}
    for branch in ("baseline", "candidate"):
        sql = preamble(repo) + attach_main(database) + f"""
            SELECT operation_id, database_id, branch_id, snapshot_id, state
            FROM differential_create_branch({sql_literal(database)}, {sql_literal(branch)}, snapshot => {snapshot_id});
        """
        row = one(cli, sql, scripts / f"branch_{branch}.sql", log)
        if int(row["snapshot_id"]) != snapshot_id:
            raise SystemExit(f"{branch} was created from snapshot {row['snapshot_id']}, not {snapshot_id}")
        created[branch] = row
    return created


def verify_raw(cli, repo, database, dataset_size, snapshot_id, scripts, log):
    sql = preamble(repo) + attach_all(database) + f"""
        SELECT
            (SELECT count(*) FROM differential_branches({sql_literal(database)})
             WHERE branch_name IN ('baseline', 'candidate')
               AND source_snapshot_id = {snapshot_id}
               AND head_snapshot_id = {snapshot_id}) AS branches_from_snapshot,
            (SELECT head_snapshot_id FROM differential_branches({sql_literal(database)})
             WHERE branch_name = 'main') AS main_head,
            (SELECT count(*) FROM main_raw.transactions) AS main_count,
            (SELECT count(*) FROM baseline.transactions) AS baseline_count,
            (SELECT count(*) FROM candidate.transactions) AS candidate_count,
            (SELECT count(*) - count(DISTINCT transaction_id) FROM main_raw.transactions) AS main_duplicate_keys,
            (SELECT count(*) - count(DISTINCT transaction_id) FROM baseline.transactions) AS baseline_duplicate_keys,
            (SELECT count(*) - count(DISTINCT transaction_id) FROM candidate.transactions) AS candidate_duplicate_keys,
            (SELECT count(*) FROM (SELECT * FROM main_raw.transactions EXCEPT SELECT * FROM baseline.transactions)) AS main_not_baseline,
            (SELECT count(*) FROM (SELECT * FROM baseline.transactions EXCEPT SELECT * FROM main_raw.transactions)) AS baseline_not_main,
            (SELECT count(*) FROM (SELECT * FROM baseline.transactions EXCEPT SELECT * FROM candidate.transactions)) AS baseline_not_candidate,
            (SELECT count(*) FROM (SELECT * FROM candidate.transactions EXCEPT SELECT * FROM baseline.transactions)) AS candidate_not_baseline,
            (SELECT md5(string_agg({RAW_FINGERPRINT}, chr(10) ORDER BY transaction_id)) FROM main_raw.transactions) AS main_fingerprint,
            (SELECT md5(string_agg({RAW_FINGERPRINT}, chr(10) ORDER BY transaction_id)) FROM baseline.transactions) AS baseline_fingerprint,
            (SELECT md5(string_agg({RAW_FINGERPRINT}, chr(10) ORDER BY transaction_id)) FROM candidate.transactions) AS candidate_fingerprint;
    """
    row = one(cli, sql, scripts / "verify_raw.sql", log)
    expected = {
        "branches_from_snapshot": "2",
        "main_head": str(snapshot_id),
        "main_count": str(dataset_size),
        "baseline_count": str(dataset_size),
        "candidate_count": str(dataset_size),
        "main_duplicate_keys": "0",
        "baseline_duplicate_keys": "0",
        "candidate_duplicate_keys": "0",
        "main_not_baseline": "0",
        "baseline_not_main": "0",
        "baseline_not_candidate": "0",
        "candidate_not_baseline": "0",
    }
    mismatches = {key: row[key] for key, value in expected.items() if row[key] != value}
    fingerprints = {row["main_fingerprint"], row["baseline_fingerprint"], row["candidate_fingerprint"]}
    if mismatches or len(fingerprints) != 1:
        raise SystemExit(f"raw input verification failed: mismatches={mismatches} row={row}")
    return row


def transform(cli, repo, database, dataset_size, script_path, transformation_sql, alias, log):
    body = transformation_sql.read_text(encoding="utf-8")
    execute(cli, preamble(repo) + attach_all(database) + body, script_path, log)
    row = one(cli, preamble(repo) + attach_all(database) + f"""
        SELECT count(*) AS classified_rows,
               count(*) - count(DISTINCT transaction_id) AS duplicate_keys,
               count(*) - count(classification) AS null_classifications,
               md5(string_agg({CLASS_FINGERPRINT}, chr(10) ORDER BY transaction_id)) AS fingerprint
        FROM {alias}.classification;
    """, script_path.with_name(script_path.stem + "_count.sql"), log)
    if int(row["classified_rows"]) != dataset_size:
        raise SystemExit(f"{alias} classified {row['classified_rows']} rows, expected {dataset_size}")
    if int(row["duplicate_keys"]) != 0 or int(row["null_classifications"]) != 0:
        raise SystemExit(f"{alias} classification is not one label per transaction: {row}")
    return row["fingerprint"]


def verify_isolation(cli, repo, database, dataset_size, raw, baseline_fp, candidate_fp, scripts, log):
    raw_fp = raw["main_fingerprint"]
    sql = preamble(repo) + attach_all(database) + f"""
        SELECT
            (SELECT count(*) FROM information_schema.tables
             WHERE table_catalog = 'main_raw' AND table_name = 'classification') AS main_classification_tables,
            (SELECT count(*) FROM information_schema.tables
             WHERE table_catalog = 'baseline' AND table_name = 'classification') AS baseline_classification_tables,
            (SELECT count(*) FROM information_schema.tables
             WHERE table_catalog = 'candidate' AND table_name = 'classification') AS candidate_classification_tables,
            (SELECT count(*) FROM information_schema.columns
             WHERE table_catalog = 'main_raw' AND table_name = 'transactions'
               AND column_name = 'classification') AS main_classification_columns,
            (SELECT count(*) FROM baseline.classification) AS baseline_classified_rows,
            (SELECT count(*) FROM candidate.classification) AS candidate_classified_rows,
            (SELECT md5(string_agg({CLASS_FINGERPRINT}, chr(10) ORDER BY transaction_id))
             FROM baseline.classification) AS baseline_fingerprint,
            (SELECT md5(string_agg({CLASS_FINGERPRINT}, chr(10) ORDER BY transaction_id))
             FROM candidate.classification) AS candidate_fingerprint,
            (SELECT md5(string_agg({RAW_FINGERPRINT}, chr(10) ORDER BY transaction_id))
             FROM main_raw.transactions) AS main_raw_fingerprint,
            (SELECT md5(string_agg({RAW_FINGERPRINT}, chr(10) ORDER BY transaction_id))
             FROM baseline.transactions) AS baseline_raw_fingerprint,
            (SELECT md5(string_agg({RAW_FINGERPRINT}, chr(10) ORDER BY transaction_id))
             FROM candidate.transactions) AS candidate_raw_fingerprint,
            (SELECT count(*) FROM (SELECT * FROM main_raw.transactions EXCEPT SELECT * FROM baseline.transactions)) AS main_not_baseline,
            (SELECT count(*) FROM (SELECT * FROM baseline.transactions EXCEPT SELECT * FROM candidate.transactions)) AS baseline_not_candidate;
    """
    row = one(cli, sql, scripts / "isolation.sql", log)
    expected = {
        "main_classification_tables": "0",
        "baseline_classification_tables": "1",
        "candidate_classification_tables": "1",
        "main_classification_columns": "0",
        "baseline_classified_rows": str(dataset_size),
        "candidate_classified_rows": str(dataset_size),
        "baseline_fingerprint": baseline_fp,
        "candidate_fingerprint": candidate_fp,
        "main_raw_fingerprint": raw_fp,
        "baseline_raw_fingerprint": raw_fp,
        "candidate_raw_fingerprint": raw_fp,
        "main_not_baseline": "0",
        "baseline_not_candidate": "0",
    }
    mismatches = {key: row[key] for key, value in expected.items() if row[key] != value}
    if mismatches:
        raise SystemExit(f"branch isolation failed: {mismatches}")
    return row


def boundary_rows(cli, repo, database, scripts, log):
    ids = ", ".join(sql_literal(transaction_id) for transaction_id, _amount in BOUNDARIES)
    sql = preamble(repo) + attach_all(database) + f"""
        SELECT transaction_id, printf('%.2f', transaction_amount) AS transaction_amount,
               classification, 'baseline' AS branch
        FROM baseline.classification
        JOIN baseline.transactions USING (transaction_id)
        WHERE transaction_id IN ({ids})
        UNION ALL
        SELECT transaction_id, printf('%.2f', transaction_amount) AS transaction_amount,
               classification, 'candidate' AS branch
        FROM candidate.classification
        JOIN candidate.transactions USING (transaction_id)
        WHERE transaction_id IN ({ids})
        ORDER BY branch, transaction_id;
    """
    rows = query(cli, sql, scripts / "boundaries.sql", log)
    if len(rows) != len(BOUNDARIES) * 2:
        raise SystemExit(f"expected {len(BOUNDARIES) * 2} boundary classifications, got {len(rows)}")
    return rows


def check_boundary_labels(rows):
    expected = {}
    for transaction_id, amount in BOUNDARIES:
        expected[("baseline", transaction_id)] = baseline_label(amount)
        expected[("candidate", transaction_id)] = candidate_label(amount)
    for row in rows:
        key = (row["branch"], row["transaction_id"])
        if row["classification"] != expected[key]:
            raise SystemExit(f"boundary {key} classified as {row['classification']}, expected {expected[key]}")
        if Decimal(row["transaction_amount"]) != dict(BOUNDARIES)[row["transaction_id"]]:
            raise SystemExit(f"boundary amount changed for {key}")


def class_histogram(cli, repo, database, alias, scripts, log):
    sql = preamble(repo) + attach_all(database) + f"""
        SELECT classification, count(*) AS n
        FROM {alias}.classification
        GROUP BY classification
        ORDER BY classification;
    """
    return query(cli, sql, scripts / f"histogram_{alias}.sql", log)


def baseline_label(amount):
    if amount < 1000:
        return "LOW"
    if amount < 10000:
        return "MEDIUM"
    return "HIGH"


def candidate_label(amount):
    if amount < 1000:
        return "LOW"
    if amount < 5000:
        return "MEDIUM"
    return "HIGH"


def preamble(repo):
    return (
        f"SET differential_repository = {sql_literal(str(repo))};\n"
        "SET differential_auto_gc = false;\n"
    )


def attach_main(database):
    return f"ATTACH 'differential:{database}' AS main_raw (BRANCH 'main');\n"


def attach_all(database):
    return (
        attach_main(database)
        + f"ATTACH 'differential:{database}' AS baseline (BRANCH 'baseline');\n"
        + f"ATTACH 'differential:{database}' AS candidate (BRANCH 'candidate');\n"
    )


def execute(cli, sql, script_path, log):
    _run(cli, sql, script_path, log)


def query(cli, sql, script_path, log):
    stdout = _run(cli, sql, script_path, log)
    if not stdout.strip():
        return []
    return list(csv.DictReader(io.StringIO(stdout)))


def _run(cli, sql, script_path, log):
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(sql, encoding="utf-8")
    argv = [str(cli), "-no-init", "-no-agent", "-bail", "-csv", ":memory:", "-f", str(script_path)]
    log.append({"script": str(script_path), "argv": argv})
    proc = subprocess.run(argv, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "duckdb failed").strip()
        raise SystemExit(message)
    return proc.stdout


def one(cli, sql, script_path, log):
    rows = query(cli, sql, script_path, log)
    if len(rows) != 1:
        raise SystemExit(f"{script_path.name} returned {len(rows)} rows")
    return rows[0]


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sql_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(exc, file=sys.stderr)
        raise
