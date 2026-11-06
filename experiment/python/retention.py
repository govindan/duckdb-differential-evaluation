"""Shared-object retention check for Phase 3.

Uses a new repository under experiment/lifecycle/retention. It does not attach
the primary comparison repository or the accepted lifecycle repository.
"""

import shutil
import sys
from pathlib import Path

from experiment_runner import (
    ROOT,
    RAW_FINGERPRINT,
    execute,
    load_config,
    one,
    preamble,
    query,
    require_cli,
    sql_literal,
    write_rows,
)
from generate_data import build_rows, write_csv
from lifecycle import disposable_repository, expect_error, storage_report, tree_signature

PRIMARY = (ROOT / "repository").resolve()
ACCEPTED = (ROOT / "lifecycle" / "repository").resolve()
RETENTION = (ROOT / "lifecycle" / "retention" / "repository").resolve()
DATABASE = "retention"
RESULTS = ROOT / "results" / "functional" / "phase3"


def main():
    config = load_config(ROOT / "config" / "experiment.yaml")
    evidence = run_retention(Path(config["duckdb_cli"]))
    if not evidence["protected_unchanged"] or evidence["result"] != "pass":
        raise SystemExit("shared-object retention test failed")
    print(evidence["summary"])
    print("retention test passed")


def run_retention(duckdb_cli):
    cli = require_cli(Path(duckdb_cli))
    repo = retention_repository(RETENTION)
    if repo.exists():
        shutil.rmtree(repo)
    repo.parent.mkdir(parents=True, exist_ok=True)
    scripts = RESULTS / "retention_scripts"
    if scripts.exists():
        shutil.rmtree(scripts)
    log = []
    index = {"n": 0}
    storage = []
    protected_before = {
        "primary": tree_signature(PRIMARY),
        "accepted_lifecycle": tree_signature(ACCEPTED),
    }

    def script(name):
        index["n"] += 1
        return scripts / f"{index['n']:02d}_{name}.sql"

    def sql(body):
        return preamble(repo) + body

    def measure(label):
        report = storage_report(repo)
        report["label"] = label
        storage.append(report)
        return report

    try:
        rows = build_rows(20, 404, "AUD")
        data_csv = ROOT / "lifecycle" / "retention" / "transactions.csv"
        write_csv(rows, data_csv)
        schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
        execute(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS main_raw (BRANCH 'main');
            {schema}
            COPY main_raw.transactions FROM {sql_literal(str(data_csv.resolve()))} (HEADER true);
        """), script("load"), log)
        shared = one(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS main_raw (BRANCH 'main');
            SELECT snapshot_id FROM differential_create_snapshot(
                'main_raw', name => 'shared-base', message => 'shared retention base');
        """), script("shared_snapshot"), log)
        shared_id = int(shared["snapshot_id"])
        for branch in ("keeper", "discard"):
            one(cli, sql(f"""
                ATTACH 'differential:{DATABASE}' AS main_raw (BRANCH 'main');
                SELECT snapshot_id FROM differential_create_branch(
                    {sql_literal(DATABASE)}, {sql_literal(branch)}, snapshot => {shared_id});
            """), script(f"branch_{branch}"), log)
        before = one(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS keeper (BRANCH 'keeper');
            ATTACH 'differential:{DATABASE}' AS discard (BRANCH 'discard');
            SELECT
                (SELECT count(*) FROM (
                    SELECT * FROM keeper.transactions
                    EXCEPT
                    SELECT * FROM discard.transactions
                )) AS keeper_only,
                (SELECT count(*) FROM (
                    SELECT * FROM discard.transactions
                    EXCEPT
                    SELECT * FROM keeper.transactions
                )) AS discard_only,
                (SELECT md5(string_agg({RAW_FINGERPRINT}, chr(10) ORDER BY transaction_id))
                 FROM keeper.transactions) AS keeper_fingerprint,
                (SELECT md5(string_agg({RAW_FINGERPRINT}, chr(10) ORDER BY transaction_id))
                 FROM discard.transactions) AS discard_fingerprint,
                (SELECT md5(string_agg({RAW_FINGERPRINT}, chr(10) ORDER BY transaction_id))
                 FROM keeper.transactions AT (VERSION => {shared_id})) AS snapshot_fingerprint;
        """), script("shared_before"), log)
        if int(before["keeper_only"]) != 0 or int(before["discard_only"]) != 0:
            raise SystemExit(f"branches did not start from the same rows: {before}")
        if len({before["keeper_fingerprint"], before["discard_fingerprint"], before["snapshot_fingerprint"]}) != 1:
            raise SystemExit(f"shared fingerprints differ: {before}")
        shared_fingerprint = before["keeper_fingerprint"]
        after_shared = measure("after_shared_branches")

        execute(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS discard (BRANCH 'discard');
            CREATE TABLE discard.bulk AS
            SELECT range AS id, 'UNSHARED-' || repeat('x', 2000) AS body
            FROM range(3000);
        """), script("unshared_write"), log)
        unshared = one(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS discard (BRANCH 'discard');
            SELECT snapshot_id,
                   (SELECT count(*) FROM discard.bulk WHERE body LIKE 'UNSHARED-%') AS unshared_rows
            FROM differential_create_snapshot('discard', name => 'unshared', message => 'discard-only payload');
        """), script("unshared_snapshot"), log)
        unshared_id = int(unshared["snapshot_id"])
        if int(unshared["unshared_rows"]) != 3000 or unshared_id == shared_id:
            raise SystemExit(f"unshared snapshot was not distinct: {unshared}")
        separated = one(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS keeper (BRANCH 'keeper');
            SELECT
                (SELECT count(*) FROM information_schema.tables
                 WHERE table_catalog = 'keeper' AND table_name = 'bulk') AS keeper_bulk_tables,
                (SELECT md5(string_agg({RAW_FINGERPRINT}, chr(10) ORDER BY transaction_id))
                 FROM keeper.transactions) AS keeper_fingerprint;
        """), script("keeper_without_payload"), log)
        if int(separated["keeper_bulk_tables"]) != 0 or separated["keeper_fingerprint"] != shared_fingerprint:
            raise SystemExit(f"unshared payload is visible on keeper: {separated}")
        after_unshared = measure("after_unshared_snapshot")

        dropped = one(cli, sql(f"""
            SELECT preservation_snapshot_id, snapshot_id, state
            FROM differential_drop_branch({sql_literal(DATABASE)}, 'discard');
        """), script("drop_discard"), log)
        expire_ids = sorted({
            unshared_id,
            int(dropped["preservation_snapshot_id"]),
        } - {0, shared_id})
        if not expire_ids:
            raise SystemExit("no unshared snapshot was eligible to expire")
        id_list = ", ".join(str(value) for value in expire_ids)
        dry = query(cli, sql(f"""
            SELECT snapshot_id, dry_run FROM differential_expire_snapshots(
                {sql_literal(DATABASE)}, versions => [{id_list}], dry_run => true);
        """), script("expire_dry_run"), log)
        dry_ids = sorted(int(row["snapshot_id"]) for row in dry)
        if dry_ids != expire_ids or shared_id in dry_ids:
            raise SystemExit(f"expiry dry run selected {dry_ids}, expected {expire_ids}")
        expired = query(cli, sql(f"""
            SELECT snapshot_id FROM differential_expire_snapshots(
                {sql_literal(DATABASE)}, versions => [{id_list}]);
        """), script("expire"), log)
        after_expiry = measure("after_unshared_expiry")
        expired_error = expect_error(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS gone (SNAPSHOT_VERSION {unshared_id});
            SELECT count(*) FROM gone.bulk;
        """), script("read_expired"), log)

        dry_gc = query(cli, sql("""
            SELECT dry_run, candidate_objects, candidate_bytes, deleted_objects
            FROM differential_cleanup_old_files(dry_run => true);
        """), script("gc_dry_run"), log)
        gc_steps = query(cli, sql("""
            SELECT dry_run, candidate_objects, candidate_bytes, deleted_objects
            FROM differential_cleanup_old_files(cleanup_all => true, max_objects => 10000);
        """), script("gc_cleanup"), log)
        after_gc = measure("after_gc")
        retained = one(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS keeper (BRANCH 'keeper');
            SELECT
                (SELECT count(*) FROM keeper.transactions) AS keeper_rows,
                (SELECT count(*) FROM (
                    SELECT * FROM keeper.transactions
                    EXCEPT
                    SELECT * FROM keeper.transactions AT (VERSION => {shared_id})
                )) AS keeper_not_snapshot,
                (SELECT count(*) FROM (
                    SELECT * FROM keeper.transactions AT (VERSION => {shared_id})
                    EXCEPT
                    SELECT * FROM keeper.transactions
                )) AS snapshot_not_keeper,
                (SELECT md5(string_agg({RAW_FINGERPRINT}, chr(10) ORDER BY transaction_id))
                 FROM keeper.transactions) AS keeper_fingerprint,
                (SELECT md5(string_agg({RAW_FINGERPRINT}, chr(10) ORDER BY transaction_id))
                 FROM keeper.transactions AT (VERSION => {shared_id})) AS snapshot_fingerprint,
                (SELECT count(*) FROM information_schema.tables
                 WHERE table_catalog = 'keeper' AND table_name = 'bulk') AS keeper_bulk_tables;
        """), script("retained_shared"), log)
        deleted_objects = sum(int(row["deleted_objects"]) for row in gc_steps)
        reclaimed_bytes = after_unshared["total"] - after_gc["total"]
        expiry_delta = after_expiry["total"] - after_unshared["total"]
        shared_ok = (
            int(retained["keeper_rows"]) == 20
            and int(retained["keeper_not_snapshot"]) == 0
            and int(retained["snapshot_not_keeper"]) == 0
            and retained["keeper_fingerprint"] == shared_fingerprint
            and retained["snapshot_fingerprint"] == shared_fingerprint
            and int(retained["keeper_bulk_tables"]) == 0
        )
        reclaimed_ok = deleted_objects > 0 and reclaimed_bytes > 0 and expiry_delta == 0
        result = "pass" if shared_ok and reclaimed_ok else "fail"
        summary = {
            "result": result,
            "shared_snapshot_id": shared_id,
            "unshared_snapshot_id": unshared_id,
            "expired_snapshot_ids": [int(row["snapshot_id"]) for row in expired],
            "drop_state": dropped["state"],
            "preservation_snapshot_id": dropped["preservation_snapshot_id"],
            "shared_fingerprint": shared_fingerprint,
            "keeper_fingerprint_after_gc": retained["keeper_fingerprint"],
            "snapshot_fingerprint_after_gc": retained["snapshot_fingerprint"],
            "keeper_rows_after_gc": retained["keeper_rows"],
            "keeper_bulk_tables_after_gc": retained["keeper_bulk_tables"],
            "bytes_after_shared": after_shared["total"],
            "bytes_after_unshared": after_unshared["total"],
            "bytes_after_expiry": after_expiry["total"],
            "bytes_after_gc": after_gc["total"],
            "expiry_byte_delta": expiry_delta,
            "gc_byte_delta": after_gc["total"] - after_expiry["total"],
            "deleted_objects": deleted_objects,
            "dry_run_candidate_objects": dry_gc[0]["candidate_objects"] if dry_gc else "0",
            "expired_read_error": expired_error,
        }
        if result != "pass":
            raise SystemExit(f"retention checks failed: {summary}")
    finally:
        protected_after = {
            "primary": tree_signature(PRIMARY),
            "accepted_lifecycle": tree_signature(ACCEPTED),
        }
        unchanged = protected_before == protected_after
        if "summary" in locals():
            summary["protected_unchanged"] = unchanged
            write_rows(RESULTS / "retention_storage.csv", storage)
            write_rows(RESULTS / "retention_summary.csv", [summary])
            (RESULTS / "retention_commands.log").write_text(
                __import__("json").dumps(log, indent=2) + "\n", encoding="utf-8")
        if not unchanged:
            raise SystemExit("primary or accepted lifecycle repository was modified")
    if "summary" not in locals():
        raise SystemExit("retention test did not finish")
    return {
        "result": summary["result"],
        "summary": summary,
        "storage": storage,
        "protected_unchanged": True,
    }


def retention_repository(path):
    repo = disposable_repository(path)
    if repo == ACCEPTED or ACCEPTED in repo.parents or repo in ACCEPTED.parents:
        raise SystemExit(f"refusing accepted lifecycle repository {repo}")
    return repo


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(exc, file=sys.stderr)
        raise
