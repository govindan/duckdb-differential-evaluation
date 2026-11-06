"""Phase 3 lifecycle checks in a disposable repository.

The primary comparison repository is never attached or written. Destructive
expiry and garbage collection run only in the lifecycle repository.
"""

import shutil
import subprocess
import sys
from pathlib import Path

from experiment_runner import (
    ROOT,
    attach_main,
    execute,
    load_config,
    one,
    preamble,
    query,
    require_cli,
    resolve_repository,
    sql_literal,
    write_rows,
)
from generate_data import build_rows, write_csv

PRIMARY = (ROOT / "repository").resolve()
LIFECYCLE = (ROOT / "lifecycle" / "repository").resolve()
DATABASE = "lifecycle"
CLONE = "lifecycle_clone"
LONE = "lone"
RESULTS = ROOT / "results" / "functional" / "phase3"


def main():
    config = load_config(ROOT / "config" / "experiment.yaml")
    evidence = run_lifecycle(Path(config["duckdb_cli"]))
    failed = [row for row in evidence["findings"] if row["status"] not in {"DEMONSTRATED", "DOCUMENTED", "UNVERIFIED"}]
    if failed or not evidence["primary_unchanged"]:
        raise SystemExit("phase 3 lifecycle checks failed")
    for row in evidence["findings"]:
        print(f"{row['status']}: {row['test_id']} {row['capability']}")
    print("phase 3 complete")


def run_lifecycle(duckdb_cli):
    cli = require_cli(Path(duckdb_cli))
    repo = disposable_repository(LIFECYCLE)
    if repo.exists():
        shutil.rmtree(repo)
    repo.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    scripts = RESULTS / "scripts"
    if scripts.exists():
        shutil.rmtree(scripts)
    log = []
    index = {"n": 0}
    findings = []
    storage = []
    primary_before = tree_signature(PRIMARY)

    def script(name):
        index["n"] += 1
        return scripts / f"{index['n']:02d}_{name}.sql"

    def sql(body):
        return preamble(repo) + body

    def record(test_id, capability, command, preconditions, result, postcondition, status, notes=""):
        findings.append({
            "test_id": test_id,
            "capability": capability,
            "command": command,
            "preconditions": preconditions,
            "result": result,
            "postcondition": postcondition,
            "status": status,
            "notes": notes,
        })

    def measure(label):
        report = storage_report(repo)
        report["label"] = label
        storage.append(report)
        return report

    try:
        rows = build_rows(20, 303, "AUD")
        data_csv = ROOT / "lifecycle" / "transactions.csv"
        write_csv(rows, data_csv)
        schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
        execute(cli, sql(attach_main(DATABASE) + schema + f"""
            COPY main_raw.transactions FROM {sql_literal(str(data_csv.resolve()))} (HEADER true);
        """), script("load"), log)
        loaded = one(cli, sql(attach_main(DATABASE) + """
            SELECT count(*) AS n FROM main_raw.transactions;
        """), script("load_count"), log)
        if int(loaded["n"]) != 20:
            raise SystemExit(f"lifecycle load count is {loaded['n']}")
        snap1 = one(cli, sql(attach_main(DATABASE) + """
            SELECT snapshot_id, state FROM differential_create_snapshot(
                'main_raw', name => 'raw-input', message => 'lifecycle raw input');
        """), script("snapshot_raw"), log)
        raw_id = int(snap1["snapshot_id"])
        measure("after_raw_snapshot")

        reopened = one(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS hist (SNAPSHOT_NAME 'raw-input');
            SELECT id AS snapshot_id, (SELECT count(*) FROM hist.transactions) AS n
            FROM hist.current_snapshot();
        """), script("reopen_snapshot"), log)
        if int(reopened["n"]) != 20 or int(reopened["snapshot_id"]) != raw_id:
            raise SystemExit(f"snapshot reopen returned {reopened}")
        record(
            "LC01", "Snapshot reopen", "ATTACH SNAPSHOT_NAME 'raw-input'",
            f"snapshot {raw_id} named raw-input has 20 rows",
            f"reopened snapshot_id={reopened['snapshot_id']}, rows={reopened['n']}",
            "The named snapshot opens in a new process and returns the captured rows",
            "DEMONSTRATED",
        )

        execute(cli, sql(attach_main(DATABASE) + """
            INSERT INTO main_raw.transactions VALUES
                ('LC-EXTRA', 'C-EXTRA', DATE '2024-06-01', 'A-EXTRA', 'CARD', 'AUD', 1.00);
        """), script("insert_extra"), log)
        snap2 = one(cli, sql(attach_main(DATABASE) + """
            SELECT snapshot_id FROM differential_create_snapshot(
                'main_raw', name => 'revised', message => 'one extra row');
        """), script("snapshot_revised"), log)
        revised_id = int(snap2["snapshot_id"])
        history = one(cli, sql(attach_main(DATABASE) + f"""
            SELECT
                (SELECT count(*) FROM main_raw.transactions) AS live_rows,
                (SELECT count(*) FROM main_raw.transactions AT (VERSION => {raw_id})) AS version_raw,
                (SELECT count(*) FROM main_raw.transactions AT (VERSION => {revised_id})) AS version_revised;
        """), script("historical_at"), log)
        if [int(history[column]) for column in ("live_rows", "version_raw", "version_revised")] != [21, 20, 21]:
            raise SystemExit(f"historical AT returned {history}")
        record(
            "LC02", "Historical snapshot access",
            f"FROM transactions AT (VERSION => {raw_id}|{revised_id})",
            "Two published snapshots of main",
            f"live={history['live_rows']}, version {raw_id}={history['version_raw']}, version {revised_id}={history['version_revised']}",
            "Each version returns the row count captured by that snapshot",
            "DEMONSTRATED",
        )
        attached = one(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS old (SNAPSHOT_VERSION {raw_id});
            ATTACH 'differential:{DATABASE}' AS revised (SNAPSHOT_VERSION {revised_id});
            SELECT
                (SELECT count(*) FROM old.transactions) AS old_rows,
                (SELECT count(*) FROM revised.transactions) AS revised_rows;
        """), script("historical_attach"), log)
        if int(attached["old_rows"]) != 20 or int(attached["revised_rows"]) != 21:
            raise SystemExit(f"historical attach returned {attached}")
        record(
            "LC03", "Historical snapshot attach",
            f"ATTACH SNAPSHOT_VERSION {raw_id} and {revised_id}",
            "The same two snapshots",
            f"old_rows={attached['old_rows']}, revised_rows={attached['revised_rows']}",
            "Each snapshot attaches as its own read-only catalog",
            "DEMONSTRATED",
        )

        one(cli, sql(attach_main(DATABASE) + f"""
            SELECT branch_id, snapshot_id FROM differential_create_branch(
                {sql_literal(DATABASE)}, 'work', snapshot => {raw_id});
        """), script("branch_work"), log)
        execute(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS work (BRANCH 'work');
            INSERT INTO work.transactions VALUES
                ('LC-WORK', 'C-WORK', DATE '2024-06-02', 'A-WORK', 'CASH', 'AUD', 2.00);
        """), script("diverge_work"), log)
        attached_restore = expect_error(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS work (BRANCH 'work');
            SELECT snapshot_id FROM differential_restore(
                {sql_literal(DATABASE)}, {raw_id}, branch => 'work');
        """), script("restore_while_attached"), log)
        restored = one(cli, sql(f"""
            SELECT preservation_snapshot_id, snapshot_id, state
            FROM differential_restore({sql_literal(DATABASE)}, {raw_id}, branch => 'work');
        """), script("restore"), log)
        compared = one(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS work (BRANCH 'work');
            ATTACH 'differential:{DATABASE}' AS raw (SNAPSHOT_VERSION {raw_id});
            SELECT
                (SELECT count(*) FROM work.transactions) AS restored_rows,
                (SELECT count(*) FROM (
                    SELECT * FROM work.transactions
                    EXCEPT
                    SELECT * FROM raw.transactions
                )) AS restored_not_snapshot,
                (SELECT count(*) FROM (
                    SELECT * FROM raw.transactions
                    EXCEPT
                    SELECT * FROM work.transactions
                )) AS snapshot_not_restored;
        """), script("restore_compare"), log)
        if int(compared["restored_rows"]) != 20 or int(compared["restored_not_snapshot"]) != 0 or int(compared["snapshot_not_restored"]) != 0:
            raise SystemExit(f"restore comparison returned {compared}")
        if int(restored["snapshot_id"]) == raw_id:
            raise SystemExit(f"restore reused snapshot id {raw_id}")
        record(
            "LC04", "Restore",
            f"differential_restore({DATABASE}, {raw_id}, branch => 'work')",
            "Branch work diverged from snapshot raw-input and was detached. Restore while attached was rejected.",
            (
                f"attached_error={attached_restore}; "
                f"preservation_snapshot_id={restored['preservation_snapshot_id']}, "
                f"snapshot_id={restored['snapshot_id']}, state={restored['state']}"
            ),
            "Restored branch content matches snapshot raw-input. The published restore has a new snapshot id.",
            "DEMONSTRATED",
        )

        clone = one(cli, sql(attach_main(DATABASE) + f"""
            SELECT database_id, snapshot_id, state
            FROM differential_clone_database({sql_literal(DATABASE)}, {sql_literal(CLONE)}, snapshot => {raw_id});
        """), script("clone"), log)
        execute(cli, sql(f"""
            ATTACH 'differential:{CLONE}' AS cloned;
            CREATE TABLE cloned.marker AS SELECT 1 AS id;
        """), script("clone_write"), log)
        isolation = one(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS main_raw (BRANCH 'main');
            ATTACH 'differential:{CLONE}' AS cloned;
            SELECT
                (SELECT count(*) FROM cloned.transactions) AS clone_rows,
                (SELECT count(*) FROM cloned.marker) AS clone_marker,
                (SELECT count(*) FROM main_raw.transactions) AS source_rows,
                (SELECT count(*) FROM main_raw.transactions AT (VERSION => {raw_id})) AS source_snapshot_rows,
                (SELECT count(*) FROM information_schema.tables
                 WHERE table_catalog = 'main_raw' AND table_name = 'marker') AS source_marker;
        """), script("clone_isolation"), log)
        if [int(isolation[column]) for column in (
            "clone_rows", "clone_marker", "source_rows", "source_snapshot_rows", "source_marker"
        )] != [20, 1, 21, 20, 0]:
            raise SystemExit(f"clone isolation returned {isolation}")
        source_ids = one(cli, sql(f"""
            SELECT database_id FROM differential_databases() WHERE database_name = {sql_literal(DATABASE)};
        """), script("source_database_id"), log)
        if clone["database_id"] == source_ids["database_id"]:
            raise SystemExit("clone reused the source database id")
        record(
            "LC05", "Clone",
            f"differential_clone_database({DATABASE}, {CLONE}, snapshot => {raw_id})",
            "Source snapshot raw-input has 20 rows",
            f"clone_database_id={clone['database_id']}, clone_snapshot_id={clone['snapshot_id']}, state={clone['state']}",
            "Clone starts with the source snapshot content and has a new database id",
            "DEMONSTRATED",
        )
        record(
            "LC06", "Clone isolation",
            "CREATE TABLE cloned.marker",
            "Clone and source are both attached",
            (
                f"clone_rows={isolation['clone_rows']}, clone_marker={isolation['clone_marker']}, "
                f"source_rows={isolation['source_rows']}, source_snapshot_rows={isolation['source_snapshot_rows']}, "
                f"source_marker={isolation['source_marker']}"
            ),
            "The clone write is visible only on the clone. Source live data and snapshot raw-input are unchanged.",
            "DEMONSTRATED",
        )
        measure("after_clone")

        one(cli, sql(attach_main(DATABASE) + f"""
            SELECT branch_id FROM differential_create_branch(
                {sql_literal(DATABASE)}, 'drop_me', snapshot => {raw_id});
        """), script("branch_drop_me"), log)
        dropped = one(cli, sql(f"""
            SELECT preservation_snapshot_id, snapshot_id, state
            FROM differential_drop_branch({sql_literal(DATABASE)}, 'drop_me');
        """), script("drop_branch"), log)
        dropped_state = one(cli, sql(f"""
            SELECT state FROM differential_branches({sql_literal(DATABASE)}) WHERE branch_name = 'drop_me';
        """), script("dropped_state"), log)
        drop_error = expect_error(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS gone (BRANCH 'drop_me');
        """), script("attach_dropped"), log)
        main_after_drop = one(cli, sql(attach_main(DATABASE) + """
            SELECT count(*) AS n FROM main_raw.transactions;
        """), script("main_after_drop"), log)
        if dropped_state["state"] != "deleted" or int(main_after_drop["n"]) != 21:
            raise SystemExit(f"drop postcondition failed: {dropped_state}, {main_after_drop}")
        record(
            "LC07", "Branch deletion",
            f"differential_drop_branch({DATABASE}, 'drop_me')",
            "Branch drop_me was detached and was not the last branch",
            (
                f"preservation_snapshot_id={dropped['preservation_snapshot_id']}, "
                f"snapshot_id={dropped['snapshot_id']}, command_state={dropped['state']}, "
                f"branch_state={dropped_state['state']}, attach_error={drop_error}"
            ),
            "The branch is deleted, it cannot be attached, and main still has 21 rows",
            "DEMONSTRATED",
        )

        one(cli, sql(attach_main(DATABASE) + f"""
            SELECT branch_id FROM differential_create_branch(
                {sql_literal(DATABASE)}, 'side', snapshot => {raw_id});
        """), script("branch_side"), log)
        execute(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS side (BRANCH 'side');
            INSERT INTO side.transactions VALUES
                ('LC-SIDE', 'C-SIDE', DATE '2024-06-03', 'A-SIDE', 'PAYMENT', 'AUD', 3.00);
        """), script("side_write"), log)
        side_v = one(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS side (BRANCH 'side');
            SELECT snapshot_id FROM differential_create_snapshot('side', name => 'side-v', message => 'first side row');
        """), script("side_v"), log)
        execute(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS side (BRANCH 'side');
            INSERT INTO side.transactions VALUES
                ('LC-SIDE-2', 'C-SIDE', DATE '2024-06-04', 'A-SIDE', 'PAYMENT', 'AUD', 4.00);
        """), script("side_write_2"), log)
        side_v2 = one(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS side (BRANCH 'side');
            SELECT snapshot_id FROM differential_create_snapshot('side', name => 'side-v2', message => 'second side row');
        """), script("side_v2"), log)
        side_old = int(side_v["snapshot_id"])
        side_head = int(side_v2["snapshot_id"])
        before_expiry = measure("before_side_expiry")
        dry = one(cli, sql(f"""
            SELECT snapshot_id, dry_run FROM differential_expire_snapshots(
                {sql_literal(DATABASE)}, versions => [{side_old}], dry_run => true);
        """), script("expire_dry_run"), log)
        if int(dry["snapshot_id"]) != side_old or str(dry["dry_run"]).lower() != "true":
            raise SystemExit(f"expiry dry run returned {dry}")
        expired = one(cli, sql(f"""
            SELECT snapshot_id, dry_run FROM differential_expire_snapshots(
                {sql_literal(DATABASE)}, versions => [{side_old}]);
        """), script("expire"), log)
        retired = one(cli, sql(f"""
            SELECT retired FROM differential_snapshots({sql_literal(DATABASE)})
            WHERE snapshot_id = {side_old};
        """), script("retired_flag"), log)
        expire_error = expect_error(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS side (BRANCH 'side');
            SELECT count(*) FROM side.transactions AT (VERSION => {side_old});
        """), script("at_expired"), log)
        side_live = one(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS side (BRANCH 'side');
            SELECT
                (SELECT count(*) FROM side.transactions) AS live_rows,
                (SELECT count(*) FROM side.transactions AT (VERSION => {side_head})) AS head_rows;
        """), script("side_after_expiry"), log)
        after_expiry = measure("after_side_expiry")
        if str(retired["retired"]).lower() != "true" or int(side_live["live_rows"]) != 22 or int(side_live["head_rows"]) != 22:
            raise SystemExit(f"expiry postcondition failed: {retired}, {side_live}")
        record(
            "LC08", "Snapshot expiry",
            f"differential_expire_snapshots({DATABASE}, versions => [{side_old}])",
            f"side-v snapshot {side_old} is not the branch head. Head snapshot is {side_head}. Dry run selected snapshot {dry['snapshot_id']}.",
            f"expired snapshot_id={expired['snapshot_id']}, retired={retired['retired']}, at_error={expire_error}",
            (
                f"Historical access to snapshot {side_old} fails. The live side branch still has "
                f"{side_live['live_rows']} rows. Repository bytes {before_expiry['total']} -> {after_expiry['total']}."
            ),
            "DEMONSTRATED",
            "Expiry removes historical access. It does not by itself delete the live branch, and byte reclamation is measured separately.",
        )

        one(cli, sql(attach_main(DATABASE) + f"""
            SELECT branch_id FROM differential_create_branch(
                {sql_literal(DATABASE)}, 'garbage', snapshot => {raw_id});
        """), script("branch_garbage"), log)
        execute(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS garbage (BRANCH 'garbage');
            CREATE TABLE garbage.bulk AS
            SELECT range AS id, repeat('x', 2000) AS body FROM range(3000);
        """), script("bulk_write"), log)
        bulk = one(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS garbage (BRANCH 'garbage');
            SELECT snapshot_id, (SELECT count(*) FROM garbage.bulk) AS bulk_rows
            FROM differential_create_snapshot('garbage', name => 'bulk', message => 'unshared payload');
        """), script("bulk_snapshot"), log)
        bulk_id = int(bulk["snapshot_id"])
        if int(bulk["bulk_rows"]) != 3000:
            raise SystemExit(f"bulk snapshot returned {bulk}")
        after_bulk = measure("after_bulk_snapshot")
        bulk_drop = one(cli, sql(f"""
            SELECT preservation_snapshot_id, snapshot_id, state
            FROM differential_drop_branch({sql_literal(DATABASE)}, 'garbage');
        """), script("drop_garbage"), log)
        expire_ids = sorted({bulk_id, int(bulk_drop["preservation_snapshot_id"])} - {0})
        id_list = ", ".join(str(value) for value in expire_ids)
        before_gc_expiry = measure("before_bulk_expiry")
        expired_bulk = query(cli, sql(f"""
            SELECT snapshot_id, dry_run FROM differential_expire_snapshots(
                {sql_literal(DATABASE)}, versions => [{id_list}]);
        """), script("expire_bulk"), log)
        after_logical_delete = measure("after_bulk_expiry")
        dry_gc = query(cli, sql("""
            SELECT dry_run, candidate_objects, candidate_bytes, deleted_objects, live_pins, stale_pins
            FROM differential_cleanup_old_files(dry_run => true);
        """), script("gc_dry_run"), log)
        gc_steps = query(cli, sql("""
            SELECT dry_run, candidate_objects, candidate_bytes, deleted_objects, live_pins, stale_pins
            FROM differential_cleanup_old_files(cleanup_all => true, max_objects => 10000);
        """), script("gc_cleanup"), log)
        after_gc = measure("after_gc")
        retained = one(cli, sql(f"""
            ATTACH 'differential:{DATABASE}' AS main_raw (BRANCH 'main');
            ATTACH 'differential:{CLONE}' AS cloned;
            SELECT
                (SELECT count(*) FROM main_raw.transactions) AS main_rows,
                (SELECT count(*) FROM main_raw.transactions AT (VERSION => {raw_id})) AS snapshot_rows,
                (SELECT count(*) FROM cloned.marker) AS clone_marker;
        """), script("retained_after_gc"), log)
        if [int(retained[column]) for column in ("main_rows", "snapshot_rows", "clone_marker")] != [21, 20, 1]:
            raise SystemExit(f"retained data changed after GC: {retained}")
        deleted_objects = sum(int(row["deleted_objects"]) for row in gc_steps)
        deleted_bytes = sum(int(row["candidate_bytes"]) for row in gc_steps)
        write_rows(RESULTS / "gc_steps.csv", dry_gc + gc_steps)
        record(
            "LC09", "Garbage collection",
            "differential_cleanup_old_files(dry_run => true); differential_cleanup_old_files(cleanup_all => true)",
            (
                f"Branch garbage held snapshot {bulk_id} with 3000 unshared payload rows. "
                f"The branch was dropped (preservation_snapshot_id={bulk_drop['preservation_snapshot_id']}) "
                f"and snapshot ids {expire_ids} were expired. Expired snapshot ids returned: "
                f"{[row['snapshot_id'] for row in expired_bulk]}."
            ),
            (
                f"dry_run={dry_gc}; cleanup_steps={len(gc_steps)}; "
                f"deleted_objects={deleted_objects}; candidate_bytes={deleted_bytes}"
            ),
            (
                f"Repository bytes after bulk snapshot {after_bulk['total']}, "
                f"after expiry {after_logical_delete['total']}, after cleanup {after_gc['total']} "
                f"(delta {after_gc['total'] - after_logical_delete['total']}). "
                f"main, snapshot {raw_id}, and the clone marker remain readable."
            ),
            "DEMONSTRATED",
            "Logical expiry and physical cleanup are separate. A zero byte delta is a measured outcome.",
        )

        execute(cli, sql(f"ATTACH 'differential:{LONE}' AS lone;\n"), script("lone_create"), log)
        last_error = expect_error(cli, sql(f"""
            SELECT snapshot_id FROM differential_drop_branch({sql_literal(LONE)}, 'main');
        """), script("drop_last_branch"), log)
        lone_state = one(cli, sql(f"""
            SELECT state FROM differential_branches({sql_literal(LONE)}) WHERE branch_name = 'main';
        """), script("lone_state"), log)
        if lone_state["state"] != "active":
            raise SystemExit(f"last branch drop changed state to {lone_state}")
        record(
            "LC10", "Last branch deletion",
            f"differential_drop_branch({LONE}, 'main')",
            "Database lone has only branch main",
            f"error={last_error}; branch_state={lone_state['state']}",
            "The only remaining branch is rejected and remains active",
            "DEMONSTRATED",
        )
        record(
            "LC11", "Remote garbage collection",
            "differential_cleanup_remote_files",
            "S3 is outside the approved MVP scope",
            "not executed",
            "No remote reclamation result",
            "UNVERIFIED",
            "Documented for S3 locations. This local build was not pointed at S3.",
        )
        record(
            "LC12", "Metadata compaction",
            "differential_compact",
            "Not required to measure local payload collection",
            "not executed",
            "No compaction result",
            "DOCUMENTED",
            "Documented as SQLite incremental vacuum. Payload collection was measured with differential_cleanup_old_files.",
        )
    finally:
        primary_after = tree_signature(PRIMARY)
        evidence = {
            "findings": findings,
            "storage": storage,
            "primary_unchanged": primary_before == primary_after,
        }
        if findings:
            write_rows(RESULTS / "findings.csv", findings)
        if storage:
            write_rows(RESULTS / "storage.csv", storage)
        (RESULTS / "commands.log").write_text(__import__("json").dumps(log, indent=2) + "\n", encoding="utf-8")
        if primary_before != primary_after:
            raise SystemExit("primary comparison repository was modified")
    return evidence


def disposable_repository(path):
    repo = resolve_repository(path)
    if repo == PRIMARY or PRIMARY in repo.parents or repo in PRIMARY.parents:
        raise SystemExit(f"refusing primary comparison repository {repo}")
    return repo


def expect_error(cli, sql, script_path, log):
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(sql, encoding="utf-8")
    argv = [str(cli), "-no-init", "-no-agent", "-bail", "-csv", ":memory:", "-f", str(script_path)]
    log.append({"script": str(script_path), "argv": argv, "expect_error": True})
    proc = subprocess.run(argv, check=False, capture_output=True, text=True)
    if proc.returncode == 0:
        raise SystemExit(f"{script_path.name} succeeded; an error was required")
    message = " ".join((proc.stderr or proc.stdout).split())
    return message


def storage_report(repo):
    groups = {"engine.sqlite": 0, "segments": 0, "journal": 0, "other": 0, "total": 0}
    if not repo.exists():
        return groups
    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        size = path.stat().st_size
        groups["total"] += size
        top = path.relative_to(repo).parts[0]
        if top == "engine.sqlite" or top.startswith("engine.sqlite"):
            groups["engine.sqlite"] += size
        elif top == "segments":
            groups["segments"] += size
        elif top == "journal":
            groups["journal"] += size
        else:
            groups["other"] += size
    return groups


def tree_signature(path):
    rows = []
    for file_path in sorted(path.rglob("*")):
        if not file_path.is_file() or file_path.name == ".DS_Store":
            continue
        stat = file_path.stat()
        rows.append((str(file_path.relative_to(path)), stat.st_size, stat.st_mtime_ns))
    return rows


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(exc, file=sys.stderr)
        raise
