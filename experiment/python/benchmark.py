"""Phase 4: Differential branches versus conventional independent DuckDB copies.

Timings are in-process DuckDB epoch_ns deltas. Filesystem copy and deletion use
Python perf_counter and include an fsync of each copied database file. Storage
is measured after the process that performed the operation has exited.
"""

import csv
import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from experiment_runner import (
    load_config,
    preamble,
    require_cli,
    resolve_under,
    sql_literal,
)
from generate_data import build_rows, canonical_checksum, write_csv

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = (
    ROOT / "repository",
    ROOT / "lifecycle" / "repository",
    ROOT / "lifecycle" / "retention" / "repository",
)
SCHEMA = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
BASELINE_SQL = (ROOT / "sql" / "baseline_transformation.sql").read_text(encoding="utf-8")
CANDIDATE_SQL = (ROOT / "sql" / "candidate_transformation.sql").read_text(encoding="utf-8")
COMPARISON_SQL = (ROOT / "sql" / "comparison.sql").read_text(encoding="utf-8").strip().rstrip(";")
DATABASE = "bench"
SEED = 20261106
FIELDS = (
    "workload", "system", "dataset_size", "changed_percent", "repetition", "warmup",
    "operation", "timing_source", "elapsed_ns", "checkpoint",
    "repository_bytes", "database_bytes", "wal_bytes", "segment_bytes", "journal_bytes",
    "temp_bytes", "state_storage_bytes",
    "intended_changed_rows", "actual_changed_rows",
    "added_records", "missing_records", "changed_records", "unchanged_records",
    "deleted_objects", "candidate_bytes", "notes",
)


def main():
    config = load_config(ROOT / "config" / "experiment.yaml")
    cli = require_cli(Path(config["duckdb_cli"]))
    run_benchmark(
        cli,
        work_root=ROOT / "benchmark" / "runs",
        results=ROOT / "results" / "benchmarks",
        sizes=(10_000, 100_000, 1_000_000),
        percents=(1, 10, 50, 100),
        reps=3,
        warmup=True,
    )


def run_benchmark(cli, work_root, results, sizes, percents, reps, warmup, seed=SEED):
    work_root = disposable(work_root)
    results = resolve_under(ROOT, results)
    for size in sizes:
        if size * min(percents) % 100 != 0:
            raise SystemExit(f"{size} does not divide evenly at the smallest percentage")
    signatures = {str(path): tree_signature(path) for path in PROTECTED}
    default_store = Path.home() / ".duckdb" / "differential"
    default_mtime = default_store.stat().st_mtime_ns if default_store.exists() else None
    results.mkdir(parents=True, exist_ok=True)
    recorder = Recorder(results / "observations.csv")
    started = time.perf_counter_ns()
    data_dir = disposable(ROOT / "benchmark" / "data")
    try:
        environment = probe_environment(cli, sizes, percents, reps, warmup, seed)
        (results / "environment.json").write_text(json.dumps(environment, indent=2) + "\n", encoding="utf-8")
        for size in sizes:
            csv_path, checksum = ensure_dataset(data_dir, size, seed)
            print(f"dataset {size} checksum {checksum}", flush=True)
            if size == 10_000 and checksum != "7e2de72f9e9f2f8a976ddb9377bb5e37f034459f46761efa209dd89d95bf3560":
                raise SystemExit(f"10k dataset checksum changed: {checksum}")
            passes = ([(0, True)] if warmup else []) + [(rep, False) for rep in range(1, reps + 1)]
            for repetition, is_warmup in passes:
                run_business(cli, recorder, work_root, csv_path, size, repetition, is_warmup, seed)
                for percent in percents:
                    run_controlled(
                        cli, recorder, work_root, size, percent, repetition, is_warmup, seed,
                    )
        write_summaries(recorder.rows, results)
    finally:
        changed = [path for path, signature in signatures.items() if tree_signature(Path(path)) != signature]
        after = default_store.stat().st_mtime_ns if default_store.exists() else None
        if changed or after != default_mtime:
            raise SystemExit(f"protected storage changed: {changed or 'default differential store'}")
    elapsed = time.perf_counter_ns() - started
    (results / "suite_elapsed_ns.txt").write_text(str(elapsed) + "\n", encoding="utf-8")
    print(f"benchmark finished in {elapsed / 1e9:.1f}s", flush=True)
    return recorder.rows


def run_business(cli, recorder, work_root, csv_path, size, repetition, is_warmup, seed):
    print(f"business size={size} rep={repetition} warmup={is_warmup}", flush=True)
    diff = case_dir(work_root, "business", "differential", size, "", repetition)
    native = case_dir(work_root, "business", "native", size, "", repetition)
    run_business_differential(cli, recorder, diff, csv_path, size, repetition, is_warmup, seed)
    run_business_native(cli, recorder, native, csv_path, size, repetition, is_warmup, seed)


def run_controlled(cli, recorder, work_root, size, percent, repetition, is_warmup, seed):
    print(f"controlled size={size} percent={percent} rep={repetition} warmup={is_warmup}", flush=True)
    intended = size * percent // 100
    diff = case_dir(work_root, "controlled", "differential", size, percent, repetition)
    native = case_dir(work_root, "controlled", "native", size, percent, repetition)
    run_controlled_differential(cli, recorder, diff, size, percent, intended, repetition, is_warmup, seed)
    run_controlled_native(cli, recorder, native, size, percent, intended, repetition, is_warmup, seed)


def run_business_differential(cli, recorder, run, csv_path, size, repetition, is_warmup, seed):
    context = base_context("business", "differential", size, "", repetition, is_warmup)
    repo, temp = prepare_case(run)
    record_storage(recorder, context, "before_load", "before_load", measure("differential", repo, None, temp))
    rows = duck(
        cli, run, "load",
        session(repo, temp, [
            attach_branch("main_raw", "main"),
            SCHEMA,
            f"COPY main_raw.transactions FROM {sql_literal(str(csv_path.resolve()))} (HEADER true);\n",
            mark(1, "load"),
            timing_select([
                ("loaded_rows", "(SELECT count(*) FROM main_raw.transactions)"),
                ("duplicate_keys", "(SELECT count(*) - count(DISTINCT transaction_id) FROM main_raw.transactions)"),
                ("auto_gc", "current_setting('differential_auto_gc')"),
            ]),
        ]),
    )
    loaded = metric_row(rows)
    if loaded.get("auto_gc", "").lower() not in {"false", "0"}:
        raise SystemExit(f"differential_auto_gc was {loaded.get('auto_gc')}")
    if int(loaded["loaded_rows"]) != size or int(loaded["duplicate_keys"]) != 0:
        raise SystemExit(f"differential load returned {loaded}")
    record_steps(recorder, context, rows, "after_load", measure("differential", repo, None, temp), loaded)

    rows = duck(cli, run, "snapshot", session(repo, temp, [
        attach_branch("main_raw", "main"),
        """
        CREATE TABLE snap AS
        SELECT snapshot_id FROM differential_create_snapshot(
            'main_raw', name => 'raw-input', message => 'benchmark raw input');
        """,
        mark(1, "snapshot"),
        timing_select([("snapshot_id", "(SELECT snapshot_id FROM snap)")]),
    ]))
    record_steps(recorder, context, rows, "before_branch", measure("differential", repo, None, temp))

    raw_snapshot = lookup_snapshot(cli, run, repo, temp, "raw-input")
    rows = duck(cli, run, "branch_creation", session(repo, temp, [
        f"""
        CREATE TABLE branch_baseline AS
        SELECT snapshot_id FROM differential_create_branch(
            {sql_literal(DATABASE)}, 'baseline', snapshot => {raw_snapshot});
        CREATE TABLE branch_candidate AS
        SELECT snapshot_id FROM differential_create_branch(
            {sql_literal(DATABASE)}, 'candidate', snapshot => {raw_snapshot});
        """,
        mark(1, "branch_creation"),
        timing_select([
            ("baseline_snapshot_id", "(SELECT snapshot_id FROM branch_baseline)"),
            ("candidate_snapshot_id", "(SELECT snapshot_id FROM branch_candidate)"),
        ]),
    ]))
    created = metric_row(rows)
    if created.get("baseline_snapshot_id") != created.get("candidate_snapshot_id"):
        raise SystemExit(f"branches were not created from the same snapshot: {created}")
    record_steps(recorder, context, rows, "after_branch", measure("differential", repo, None, temp))

    rows = duck(cli, run, "baseline_transform", session(repo, temp, [
        attach_branch("baseline", "baseline"),
        BASELINE_SQL,
        mark(1, "baseline_transform"),
        timing_select([("output_rows", "(SELECT count(*) FROM baseline.classification)")]),
    ]))
    if int(metric_row(rows)["output_rows"]) != size:
        raise SystemExit(f"baseline transform returned {metric_row(rows)}")
    record_steps(recorder, context, rows, "", None)

    rows = duck(cli, run, "baseline_snapshot", session(repo, temp, [
        attach_branch("baseline", "baseline"),
        """
        CREATE TABLE snap AS
        SELECT snapshot_id FROM differential_create_snapshot(
            'baseline', name => 'baseline-output', message => 'baseline classification');
        """,
        mark(1, "baseline_snapshot"),
        timing_select([("snapshot_id", "(SELECT snapshot_id FROM snap)")]),
    ]))
    record_steps(recorder, context, rows, "after_baseline_snapshot", measure("differential", repo, None, temp))

    rows = duck(cli, run, "candidate_transform", session(repo, temp, [
        attach_branch("candidate", "candidate"),
        CANDIDATE_SQL,
        mark(1, "candidate_transform"),
        timing_select([("output_rows", "(SELECT count(*) FROM candidate.classification)")]),
    ]))
    if int(metric_row(rows)["output_rows"]) != size:
        raise SystemExit(f"candidate transform returned {metric_row(rows)}")
    record_steps(recorder, context, rows, "", None)

    rows = duck(cli, run, "candidate_snapshot", session(repo, temp, [
        attach_branch("candidate", "candidate"),
        """
        CREATE TABLE snap AS
        SELECT snapshot_id FROM differential_create_snapshot(
            'candidate', name => 'candidate-output', message => 'candidate classification');
        """,
        mark(1, "candidate_snapshot"),
        timing_select([("snapshot_id", "(SELECT snapshot_id FROM snap)")]),
    ]))
    candidate_snapshot = int(metric_row(rows)["snapshot_id"])
    record_steps(recorder, context, rows, "after_candidate_snapshot", measure("differential", repo, None, temp))

    rows = duck(cli, run, "comparison", session(repo, temp, [
        attach_branch("baseline", "baseline"),
        attach_branch("candidate", "candidate"),
        f"CREATE TABLE comparison_result AS\n{COMPARISON_SQL};\n",
        mark(1, "comparison"),
        timing_select([
            ("added_records", "(SELECT added_records FROM comparison_result)"),
            ("missing_records", "(SELECT missing_records FROM comparison_result)"),
            ("changed_records", "(SELECT changed_records FROM comparison_result)"),
            ("unchanged_records", "(SELECT unchanged_records FROM comparison_result)"),
            ("joined_rows", "(SELECT joined_rows FROM comparison_result)"),
            ("amount_mismatches", "(SELECT amount_mismatches FROM comparison_result)"),
            ("changed_outside_band", "(SELECT changed_outside_band FROM comparison_result)"),
            ("medium_to_high_in_band", "(SELECT medium_to_high_in_band FROM comparison_result)"),
            ("baseline_duplicate_keys", "(SELECT baseline_duplicate_keys FROM comparison_result)"),
            ("candidate_duplicate_keys", "(SELECT candidate_duplicate_keys FROM comparison_result)"),
        ]),
    ]))
    compared = metric_row(rows)
    check_business(compared, size, seed)
    record_steps(recorder, context, rows, "after_comparison", measure("differential", repo, None, temp), compared)

    rows = duck(cli, run, "branch_cleanup", session(repo, temp, [
        f"""
        CREATE TABLE dropped AS
        SELECT preservation_snapshot_id, snapshot_id, state
        FROM differential_drop_branch({sql_literal(DATABASE)}, 'candidate');
        """,
        mark(1, "branch_cleanup"),
        timing_select([
            ("preservation_snapshot_id", "(SELECT preservation_snapshot_id FROM dropped)"),
            ("snapshot_id", "(SELECT snapshot_id FROM dropped)"),
        ]),
    ]))
    record_steps(recorder, context, rows, "after_branch_deletion", measure("differential", repo, None, temp))

    rows = duck(cli, run, "snapshot_expiry", session(repo, temp, [
        f"""
        CREATE TABLE expired AS
        SELECT snapshot_id, dry_run FROM differential_expire_snapshots(
            {sql_literal(DATABASE)}, versions => [{candidate_snapshot}]);
        """,
        mark(1, "snapshot_expiry"),
        timing_select([
            ("snapshot_id", "(SELECT snapshot_id FROM expired)"),
            ("dry_run", "(SELECT dry_run FROM expired)"),
        ]),
    ]))
    expired = metric_row(rows)
    if expired.get("dry_run", "").lower() not in {"false", "0"} or int(expired["snapshot_id"]) != candidate_snapshot:
        raise SystemExit(f"candidate expiry returned {expired}")
    record_steps(recorder, context, rows, "after_expiry", measure("differential", repo, None, temp))

    rows = duck(cli, run, "garbage_collection", session(repo, temp, [
        """
        CREATE TABLE gc_result AS
        SELECT coalesce(sum(deleted_objects), 0) AS deleted_objects,
               coalesce(sum(candidate_bytes), 0) AS candidate_bytes
        FROM differential_cleanup_old_files(cleanup_all => true, max_objects => 10000);
        """,
        mark(1, "garbage_collection"),
        timing_select([
            ("deleted_objects", "(SELECT deleted_objects FROM gc_result)"),
            ("candidate_bytes", "(SELECT candidate_bytes FROM gc_result)"),
        ]),
    ]))
    collected = metric_row(rows)
    if int(collected["deleted_objects"]) >= 10000:
        raise SystemExit("garbage collection filled the 10000-object batch")
    storage = measure("differential", repo, None, temp)
    record_steps(recorder, context, rows, "after_gc", storage, collected)
    retained = duck(cli, run, "retention_check", session(repo, temp, [
        attach_branch("main_raw", "main"),
        attach_branch("baseline", "baseline"),
        """
        SELECT (SELECT count(*) FROM main_raw.transactions) AS raw_rows,
               (SELECT count(*) FROM baseline.classification) AS baseline_rows;
        """,
    ]))
    if int(retained[0]["raw_rows"]) != size or int(retained[0]["baseline_rows"]) != size:
        raise SystemExit(f"business retention changed after GC: {retained}")
    message = expect_error(cli, run, "candidate_detached", session(repo, temp, [
        attach_branch("candidate", "candidate"),
        "SELECT 1;\n",
    ]))
    if "not_found" not in message and "not found" not in message.lower():
        raise SystemExit(f"dropped candidate branch still attached: {message}")


def run_business_native(cli, recorder, run, csv_path, size, repetition, is_warmup, seed):
    context = base_context("business", "native", size, "", repetition, is_warmup)
    native, temp = prepare_native(run)
    baseline = native / "baseline.duckdb"
    candidate = native / "candidate.duckdb"
    record_storage(recorder, context, "before_load", "before_load", measure("native", None, native, temp))
    schema = SCHEMA.replace("main_raw.", "baseline.")
    rows = duck(cli, run, "load", session(None, temp, [
        f"ATTACH {sql_literal(str(baseline))} AS baseline;\n",
        schema,
        f"COPY baseline.transactions FROM {sql_literal(str(csv_path.resolve()))} (HEADER true);\n",
        mark(1, "load"),
        "CHECKPOINT baseline;\n",
        mark(2, "load_checkpoint"),
        timing_select([
            ("loaded_rows", "(SELECT count(*) FROM baseline.transactions)"),
            ("duplicate_keys", "(SELECT count(*) - count(DISTINCT transaction_id) FROM baseline.transactions)"),
        ]),
    ]))
    loaded = metric_row(rows)
    if int(loaded["loaded_rows"]) != size or int(loaded["duplicate_keys"]) != 0:
        raise SystemExit(f"native load returned {loaded}")
    record_steps(recorder, context, rows, "after_load", measure("native", None, native, temp), loaded)

    elapsed = copy_database(baseline, candidate)
    record_external(
        recorder, context, "database_copy", elapsed, "after_copy",
        measure("native", None, native, temp), "python perf_counter including fsync of the destination",
    )
    verify_same_table(cli, run, temp, baseline, candidate, "transactions", "copy_check")
    if repetition == 1 and not is_warmup:
        logical_copy(cli, recorder, context, run, temp, baseline, candidate, "transactions")

    rows = duck(cli, run, "baseline_transform", session(None, temp, [
        f"ATTACH {sql_literal(str(baseline))} AS baseline;\n",
        BASELINE_SQL,
        mark(1, "baseline_transform"),
        "CHECKPOINT baseline;\n",
        mark(2, "baseline_checkpoint"),
        timing_select([("output_rows", "(SELECT count(*) FROM baseline.classification)")]),
    ]))
    if int(metric_row(rows)["output_rows"]) != size:
        raise SystemExit(f"native baseline transform returned {metric_row(rows)}")
    record_steps(recorder, context, rows, "after_baseline_transform", measure("native", None, native, temp))

    rows = duck(cli, run, "candidate_transform", session(None, temp, [
        f"ATTACH {sql_literal(str(candidate))} AS candidate;\n",
        CANDIDATE_SQL,
        mark(1, "candidate_transform"),
        "CHECKPOINT candidate;\n",
        mark(2, "candidate_checkpoint"),
        timing_select([("output_rows", "(SELECT count(*) FROM candidate.classification)")]),
    ]))
    if int(metric_row(rows)["output_rows"]) != size:
        raise SystemExit(f"native candidate transform returned {metric_row(rows)}")
    record_steps(recorder, context, rows, "after_candidate_snapshot", measure("native", None, native, temp))

    rows = duck(cli, run, "comparison", session(None, temp, [
        f"ATTACH {sql_literal(str(baseline))} AS baseline (READ_ONLY);\n",
        f"ATTACH {sql_literal(str(candidate))} AS candidate (READ_ONLY);\n",
        f"CREATE TABLE comparison_result AS\n{COMPARISON_SQL};\n",
        mark(1, "comparison"),
        timing_select([
            ("added_records", "(SELECT added_records FROM comparison_result)"),
            ("missing_records", "(SELECT missing_records FROM comparison_result)"),
            ("changed_records", "(SELECT changed_records FROM comparison_result)"),
            ("unchanged_records", "(SELECT unchanged_records FROM comparison_result)"),
            ("joined_rows", "(SELECT joined_rows FROM comparison_result)"),
            ("amount_mismatches", "(SELECT amount_mismatches FROM comparison_result)"),
            ("changed_outside_band", "(SELECT changed_outside_band FROM comparison_result)"),
            ("medium_to_high_in_band", "(SELECT medium_to_high_in_band FROM comparison_result)"),
            ("baseline_duplicate_keys", "(SELECT baseline_duplicate_keys FROM comparison_result)"),
            ("candidate_duplicate_keys", "(SELECT candidate_duplicate_keys FROM comparison_result)"),
        ]),
    ]))
    compared = metric_row(rows)
    check_business(compared, size, seed)
    record_steps(recorder, context, rows, "after_comparison", measure("native", None, native, temp), compared)

    started = time.perf_counter_ns()
    remove_database(candidate)
    elapsed = time.perf_counter_ns() - started
    record_external(
        recorder, context, "database_cleanup", elapsed, "after_database_cleanup",
        measure("native", None, native, temp), "python perf_counter around unlink of the candidate database files",
    )


def run_controlled_differential(cli, recorder, run, size, percent, intended, repetition, is_warmup, seed):
    del seed
    context = base_context("controlled", "differential", size, percent, repetition, is_warmup)
    context["intended_changed_rows"] = intended
    repo, temp = prepare_case(run)
    record_storage(recorder, context, "before_load", "before_load", measure("differential", repo, None, temp))
    rows = duck(cli, run, "load", session(repo, temp, [
        attach_branch("main_raw", "main"),
        f"""
        CREATE TABLE main_raw.rows (
            row_id BIGINT PRIMARY KEY,
            status VARCHAR NOT NULL,
            payload VARCHAR NOT NULL
        );
        INSERT INTO main_raw.rows
        SELECT range AS row_id, 'original' AS status, printf('p-%d', range) AS payload
        FROM range({size});
        """,
        mark(1, "load"),
        timing_select([
            ("loaded_rows", "(SELECT count(*) FROM main_raw.rows)"),
            ("auto_gc", "current_setting('differential_auto_gc')"),
        ]),
    ]))
    loaded = metric_row(rows)
    if loaded.get("auto_gc", "").lower() not in {"false", "0"} or int(loaded["loaded_rows"]) != size:
        raise SystemExit(f"controlled load returned {loaded}")
    record_steps(recorder, context, rows, "after_load", measure("differential", repo, None, temp))

    rows = duck(cli, run, "snapshot", session(repo, temp, [
        attach_branch("main_raw", "main"),
        """
        CREATE TABLE snap AS
        SELECT snapshot_id FROM differential_create_snapshot(
            'main_raw', name => 'base', message => 'controlled base');
        """,
        mark(1, "snapshot"),
        timing_select([("snapshot_id", "(SELECT snapshot_id FROM snap)")]),
    ]))
    record_steps(recorder, context, rows, "before_branch", measure("differential", repo, None, temp))

    base_snapshot = lookup_snapshot(cli, run, repo, temp, "base")
    rows = duck(cli, run, "branch_creation", session(repo, temp, [
        f"""
        CREATE TABLE created AS
        SELECT snapshot_id FROM differential_create_branch(
            {sql_literal(DATABASE)}, 'updated', snapshot => {base_snapshot});
        """,
        mark(1, "branch_creation"),
        timing_select([("snapshot_id", "(SELECT snapshot_id FROM created)")]),
    ]))
    record_steps(recorder, context, rows, "after_branch", measure("differential", repo, None, temp))

    rows = duck(cli, run, "controlled_update", session(repo, temp, [
        attach_branch("updated", "updated"),
        f"""
        UPDATE updated.rows
        SET status = 'changed', payload = payload || '-u'
        WHERE row_id < {intended};
        """,
        mark(1, "controlled_update"),
        timing_select([
            ("actual_changed_rows", "(SELECT count(*) FILTER (WHERE status = 'changed') FROM updated.rows)"),
            ("original_rows", "(SELECT count(*) FILTER (WHERE status = 'original') FROM updated.rows)"),
        ]),
    ]))
    updated = metric_row(rows)
    if int(updated["actual_changed_rows"]) != intended or int(updated["original_rows"]) != size - intended:
        raise SystemExit(f"controlled update returned {updated}, intended {intended}")
    record_steps(recorder, context, rows, "", None, updated)

    rows = duck(cli, run, "snapshot_after_update", session(repo, temp, [
        attach_branch("updated", "updated"),
        """
        CREATE TABLE snap AS
        SELECT snapshot_id FROM differential_create_snapshot(
            'updated', name => 'updated-output', message => 'controlled update');
        """,
        mark(1, "snapshot_after_update"),
        timing_select([("snapshot_id", "(SELECT snapshot_id FROM snap)")]),
    ]))
    update_snapshot = int(metric_row(rows)["snapshot_id"])
    record_steps(recorder, context, rows, "after_candidate_snapshot", measure("differential", repo, None, temp), updated)
    source = duck(cli, run, "source_check", session(repo, temp, [
        attach_branch("main_raw", "main"),
        "SELECT count(*) FILTER (WHERE status = 'original') AS original_rows FROM main_raw.rows;\n",
    ]))
    if int(source[0]["original_rows"]) != size:
        raise SystemExit(f"controlled source changed: {source}")

    rows = duck(cli, run, "branch_cleanup", session(repo, temp, [
        f"""
        CREATE TABLE dropped AS
        SELECT preservation_snapshot_id, snapshot_id, state
        FROM differential_drop_branch({sql_literal(DATABASE)}, 'updated');
        """,
        mark(1, "branch_cleanup"),
        timing_select([("preservation_snapshot_id", "(SELECT preservation_snapshot_id FROM dropped)")]),
    ]))
    record_steps(recorder, context, rows, "after_branch_deletion", measure("differential", repo, None, temp))

    rows = duck(cli, run, "snapshot_expiry", session(repo, temp, [
        f"""
        CREATE TABLE expired AS
        SELECT snapshot_id, dry_run FROM differential_expire_snapshots(
            {sql_literal(DATABASE)}, versions => [{update_snapshot}]);
        """,
        mark(1, "snapshot_expiry"),
        timing_select([("snapshot_id", "(SELECT snapshot_id FROM expired)"), ("dry_run", "(SELECT dry_run FROM expired)")]),
    ]))
    expired = metric_row(rows)
    if int(expired["snapshot_id"]) != update_snapshot or expired.get("dry_run", "").lower() not in {"false", "0"}:
        raise SystemExit(f"controlled expiry returned {expired}")
    record_steps(recorder, context, rows, "after_expiry", measure("differential", repo, None, temp))

    rows = duck(cli, run, "garbage_collection", session(repo, temp, [
        """
        CREATE TABLE gc_result AS
        SELECT coalesce(sum(deleted_objects), 0) AS deleted_objects,
               coalesce(sum(candidate_bytes), 0) AS candidate_bytes
        FROM differential_cleanup_old_files(cleanup_all => true, max_objects => 10000);
        """,
        mark(1, "garbage_collection"),
        timing_select([
            ("deleted_objects", "(SELECT deleted_objects FROM gc_result)"),
            ("candidate_bytes", "(SELECT candidate_bytes FROM gc_result)"),
        ]),
    ]))
    collected = metric_row(rows)
    if int(collected["deleted_objects"]) >= 10000:
        raise SystemExit("garbage collection filled the 10000-object batch")
    record_steps(recorder, context, rows, "after_gc", measure("differential", repo, None, temp), collected)
    retained = duck(cli, run, "retention_check", session(repo, temp, [
        attach_branch("main_raw", "main"),
        "SELECT count(*) FILTER (WHERE status = 'original') AS original_rows FROM main_raw.rows;\n",
    ]))
    if int(retained[0]["original_rows"]) != size:
        raise SystemExit(f"controlled base changed after GC: {retained}")


def run_controlled_native(cli, recorder, run, size, percent, intended, repetition, is_warmup, seed):
    del seed
    context = base_context("controlled", "native", size, percent, repetition, is_warmup)
    context["intended_changed_rows"] = intended
    native, temp = prepare_native(run)
    baseline = native / "baseline.duckdb"
    candidate = native / "candidate.duckdb"
    record_storage(recorder, context, "before_load", "before_load", measure("native", None, native, temp))
    rows = duck(cli, run, "load", session(None, temp, [
        f"ATTACH {sql_literal(str(baseline))} AS baseline;\n",
        f"""
        CREATE TABLE baseline.rows (
            row_id BIGINT PRIMARY KEY,
            status VARCHAR NOT NULL,
            payload VARCHAR NOT NULL
        );
        INSERT INTO baseline.rows
        SELECT range AS row_id, 'original' AS status, printf('p-%d', range) AS payload
        FROM range({size});
        """,
        mark(1, "load"),
        "CHECKPOINT baseline;\n",
        mark(2, "load_checkpoint"),
        timing_select([("loaded_rows", "(SELECT count(*) FROM baseline.rows)")]),
    ]))
    if int(metric_row(rows)["loaded_rows"]) != size:
        raise SystemExit(f"native controlled load returned {metric_row(rows)}")
    record_steps(recorder, context, rows, "after_load", measure("native", None, native, temp))

    elapsed = copy_database(baseline, candidate)
    record_external(
        recorder, context, "database_copy", elapsed, "after_copy",
        measure("native", None, native, temp), "python perf_counter including fsync of the destination",
    )
    verify_same_table(cli, run, temp, baseline, candidate, "rows", "copy_check")
    if repetition == 1 and not is_warmup and percent == 1:
        logical_copy(cli, recorder, context, run, temp, baseline, candidate, "rows")

    rows = duck(cli, run, "controlled_update", session(None, temp, [
        f"ATTACH {sql_literal(str(baseline))} AS baseline (READ_ONLY);\n",
        f"ATTACH {sql_literal(str(candidate))} AS candidate;\n",
        f"""
        UPDATE candidate.rows
        SET status = 'changed', payload = payload || '-u'
        WHERE row_id < {intended};
        """,
        mark(1, "controlled_update"),
        "CHECKPOINT candidate;\n",
        mark(2, "update_checkpoint"),
        timing_select([
            ("actual_changed_rows", "(SELECT count(*) FILTER (WHERE status = 'changed') FROM candidate.rows)"),
            ("original_rows", "(SELECT count(*) FILTER (WHERE status = 'original') FROM candidate.rows)"),
            ("source_original_rows", "(SELECT count(*) FILTER (WHERE status = 'original') FROM baseline.rows)"),
        ]),
    ]))
    updated = metric_row(rows)
    if int(updated["actual_changed_rows"]) != intended or int(updated["source_original_rows"]) != size:
        raise SystemExit(f"native controlled update returned {updated}, intended {intended}")
    record_steps(
        recorder, context, rows, "after_candidate_snapshot",
        measure("native", None, native, temp), updated,
    )
    started = time.perf_counter_ns()
    remove_database(candidate)
    elapsed = time.perf_counter_ns() - started
    record_external(
        recorder, context, "database_cleanup", elapsed, "after_database_cleanup",
        measure("native", None, native, temp), "python perf_counter around unlink of the updated copy",
    )


def logical_copy(cli, recorder, context, run, temp, baseline, candidate, table):
    logical_dir = run / "logical"
    logical_dir.mkdir(parents=True)
    logical = logical_dir / "logical.duckdb"
    rows = duck(cli, run, "logical_database_copy", session(None, temp, [
        f"ATTACH {sql_literal(str(baseline))} AS baseline (READ_ONLY);\n",
        f"ATTACH {sql_literal(str(logical))} AS logical;\n",
        "COPY FROM DATABASE baseline TO logical;\n",
        mark(1, "logical_database_copy"),
        timing_select([]),
    ]))
    verify_same_table(cli, run, temp, baseline, logical, table, "logical_check_baseline")
    verify_same_table(cli, run, temp, candidate, logical, table, "logical_check_candidate")
    storage = measure("logical", None, logical_dir, None)
    record_steps(
        recorder, context, rows, "logical_copy", storage, {},
    )
    recorder.rows[-1]["notes"] = (
        "COPY FROM DATABASE logical-equivalence check. "
        "Its bytes are not included in the filesystem-copy control total."
    )
    rewrite_last(recorder)


def verify_same_table(cli, run, temp, left_file, right_file, table, name):
    rows = duck(cli, run, name, session(None, temp, [
        f"ATTACH {sql_literal(str(left_file))} AS left_db (READ_ONLY);\n",
        f"ATTACH {sql_literal(str(right_file))} AS right_db (READ_ONLY);\n",
        f"""
        SELECT
            (SELECT count(*) FROM (SELECT * FROM left_db.{table} EXCEPT SELECT * FROM right_db.{table})) AS left_only,
            (SELECT count(*) FROM (SELECT * FROM right_db.{table} EXCEPT SELECT * FROM left_db.{table})) AS right_only;
        """,
    ]))
    if int(rows[0]["left_only"]) != 0 or int(rows[0]["right_only"]) != 0:
        raise SystemExit(f"{name} found differing rows: {rows[0]}")


def check_business(row, size, seed):
    added = int(row["added_records"])
    missing = int(row["missing_records"])
    changed = int(row["changed_records"])
    unchanged = int(row["unchanged_records"])
    if added or missing or int(row["amount_mismatches"]) or int(row["changed_outside_band"]):
        raise SystemExit(f"business comparison failed: {row}")
    if int(row["baseline_duplicate_keys"]) or int(row["candidate_duplicate_keys"]):
        raise SystemExit(f"business comparison has duplicate keys: {row}")
    if added + missing + changed + unchanged != int(row["joined_rows"]) or int(row["joined_rows"]) != size:
        raise SystemExit(f"business comparison does not partition {size} rows: {row}")
    if changed != int(row["medium_to_high_in_band"]):
        raise SystemExit(f"business changes are not the MEDIUM to HIGH band: {row}")
    if size == 10_000 and seed == SEED and changed != 1986:
        raise SystemExit(f"10k business change count is {changed}, expected 1986")


def session(repo, temp, statements):
    parts = []
    if repo is not None:
        parts.append(preamble(repo))
    parts.append(f"SET temp_directory = {sql_literal(str(temp))};\n")
    parts.append("CREATE TABLE timings (seq INTEGER, step VARCHAR, at_ns BIGINT);\n")
    parts.append("INSERT INTO timings VALUES (0, 'start', epoch_ns(get_current_timestamp()));\n")
    parts.extend(statements)
    return "".join(parts)


def mark(seq, step):
    return (
        f"INSERT INTO timings VALUES ({seq}, {sql_literal(step)}, epoch_ns(get_current_timestamp()));\n"
    )


def timing_select(extra):
    columns = "".join(f",\n    {expression} AS {name}" for name, expression in extra)
    return f"""
SELECT seq, step, at_ns - lag(at_ns) OVER (ORDER BY seq) AS elapsed_ns{columns}
FROM timings
ORDER BY seq;
"""


def lookup_snapshot(cli, run, repo, temp, name):
    rows = duck(cli, run, f"lookup_{name}", session(repo, temp, [
        f"""
        SELECT snapshot_id FROM differential_snapshots({sql_literal(DATABASE)})
        WHERE snapshot_name = {sql_literal(name)};
        """,
    ]))
    if len(rows) != 1:
        raise SystemExit(f"snapshot {name} returned {rows}")
    return int(rows[0]["snapshot_id"])


def attach_branch(alias, branch):
    return f"ATTACH 'differential:{DATABASE}' AS {alias} (BRANCH {sql_literal(branch)});\n"


def duck(cli, run, name, sql):
    script = run / "scripts" / f"{name}.sql"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(sql, encoding="utf-8")
    argv = [str(cli), "-no-init", "-no-agent", "-bail", "-csv", ":memory:", "-f", str(script)]
    proc = subprocess.run(argv, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "duckdb failed").strip()
        raise SystemExit(f"{script}: {message}")
    if "elapsed_ns" not in proc.stdout and proc.stdout.strip().lower().startswith("seq,"):
        pass
    return parse_csv(proc.stdout)


def expect_error(cli, run, name, sql):
    script = run / "scripts" / f"{name}.sql"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(sql, encoding="utf-8")
    argv = [str(cli), "-no-init", "-no-agent", "-bail", "-csv", ":memory:", "-f", str(script)]
    proc = subprocess.run(argv, check=False, capture_output=True, text=True)
    if proc.returncode == 0:
        raise SystemExit(f"{name} succeeded; an error was required")
    return " ".join((proc.stderr or proc.stdout).split())


def parse_csv(text):
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.split(",")[0] in {
            "seq", "loaded_rows", "raw_rows", "original_rows", "left_only", "snapshot_id",
        }:
            start = index
    if start is None:
        raise SystemExit(f"no CSV result:\n{text}")
    return list(csv.DictReader(io.StringIO("\n".join(lines[start:]) + "\n")))


def metric_row(rows):
    timed = [row for row in rows if row.get("step") not in {None, "", "start"}]
    return timed[-1] if timed else rows[-1]


def record_steps(recorder, context, rows, checkpoint, storage, metrics=None):
    timed = [row for row in rows if row.get("step") not in {None, "", "start"}]
    if not timed:
        raise SystemExit(f"no timed step in {rows}")
    metrics = metrics or {}
    for index, row in enumerate(timed):
        last = index == len(timed) - 1
        item = dict(context)
        item.update({
            "operation": row["step"],
            "timing_source": "duckdb_epoch_ns",
            "elapsed_ns": row.get("elapsed_ns", ""),
            "notes": "in-process epoch_ns delta; CLI startup is excluded",
        })
        if last and checkpoint:
            item["checkpoint"] = checkpoint
            item.update(storage or {})
        if last and metrics:
            for key in (
                "actual_changed_rows", "added_records", "missing_records",
                "changed_records", "unchanged_records", "deleted_objects", "candidate_bytes",
            ):
                if metrics.get(key) not in (None, ""):
                    item[key] = metrics[key]
            notes = [item["notes"]]
            if metrics.get("auto_gc"):
                notes.append(f"differential_auto_gc={metrics['auto_gc']}")
            if metrics.get("changed_records") not in (None, ""):
                size = int(context["dataset_size"])
                changed = int(metrics["changed_records"])
                notes.append(f"actual_changed_percent={changed / size * 100:.4f}")
            item["notes"] = "; ".join(notes)
        recorder.add(item)


def record_external(recorder, context, operation, elapsed, checkpoint, storage, note):
    item = dict(context)
    item.update({
        "operation": operation,
        "timing_source": "python_perf_counter",
        "elapsed_ns": elapsed,
        "checkpoint": checkpoint,
        "notes": note,
    })
    item.update(storage)
    recorder.add(item)


def record_storage(recorder, context, operation, checkpoint, storage):
    item = dict(context)
    item.update({"operation": operation, "checkpoint": checkpoint, "timing_source": "", "elapsed_ns": ""})
    item.update(storage)
    item["notes"] = "storage checkpoint with no timed operation"
    recorder.add(item)


def measure(kind, repo, native, temp):
    repository_bytes = directory_bytes(repo) if repo else 0
    database_bytes = 0
    wal_bytes = 0
    segment_bytes = 0
    journal_bytes = 0
    if repo and repo.exists():
        for path in repo.rglob("*"):
            if not path.is_file() or path.name == ".DS_Store":
                continue
            size = path.stat().st_size
            relative = path.relative_to(repo)
            top = relative.parts[0]
            if top == "segments":
                segment_bytes += size
            elif top == "journal":
                journal_bytes += size
            elif path.name == "engine.sqlite":
                database_bytes += size
            elif "wal" in path.name:
                wal_bytes += size
    if native and native.exists():
        for path in native.rglob("*"):
            if not path.is_file() or path.name == ".DS_Store":
                continue
            size = path.stat().st_size
            if path.name.endswith(".wal") or ".wal" in path.name:
                wal_bytes += size
            elif ".tmp" in path.name:
                temp_bytes += size
            elif path.suffix == ".duckdb":
                database_bytes += size
    temp_bytes = directory_bytes(temp)
    if kind == "differential":
        state = repository_bytes + temp_bytes
    else:
        state = database_bytes + wal_bytes + temp_bytes
    return {
        "repository_bytes": repository_bytes if kind == "differential" else 0,
        "database_bytes": database_bytes,
        "wal_bytes": wal_bytes,
        "segment_bytes": segment_bytes if kind == "differential" else 0,
        "journal_bytes": journal_bytes if kind == "differential" else 0,
        "temp_bytes": temp_bytes,
        "state_storage_bytes": state,
    }


def directory_bytes(path):
    if path is None or not path.exists():
        return 0
    total = 0
    for file_path in path.rglob("*"):
        if file_path.is_file() and file_path.name != ".DS_Store":
            total += file_path.stat().st_size
    return total


def copy_database(source, destination):
    started = time.perf_counter_ns()
    files = sorted(source.parent.glob(source.name + "*"))
    if source not in files:
        raise SystemExit(f"database file is missing: {source}")
    for path in files:
        if not path.is_file():
            continue
        target = destination.parent / (destination.name + path.name[len(source.name):])
        shutil.copy2(path, target)
        with target.open("rb") as handle:
            os.fsync(handle.fileno())
    directory = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return time.perf_counter_ns() - started


def remove_database(path):
    for candidate in path.parent.glob(path.name + "*"):
        if candidate.is_file():
            candidate.unlink()


def prepare_case(run):
    if run.exists():
        shutil.rmtree(run)
    repo = run / "repository"
    temp = run / "tmp"
    repo.mkdir(parents=True)
    temp.mkdir()
    return repo, temp


def prepare_native(run):
    if run.exists():
        shutil.rmtree(run)
    native = run / "native"
    temp = run / "tmp"
    native.mkdir(parents=True)
    temp.mkdir()
    return native, temp


def case_dir(work_root, workload, system, size, percent, repetition):
    label = "business" if percent == "" else f"p{int(percent):02d}"
    path = disposable(work_root / workload / system / str(size) / label / f"rep{repetition}")
    return path


def base_context(workload, system, size, percent, repetition, is_warmup):
    return {
        "workload": workload,
        "system": system,
        "dataset_size": size,
        "changed_percent": "" if percent == "" else int(percent),
        "repetition": repetition,
        "warmup": "true" if is_warmup else "false",
        "intended_changed_rows": "",
    }


def ensure_dataset(data_dir, size, seed):
    path = data_dir / f"transactions_{size}.csv"
    stamp = data_dir / f"transactions_{size}.sha256"
    rows = build_rows(size, seed, "AUD")
    checksum = canonical_checksum(rows)
    if path.exists() and stamp.exists() and stamp.read_text(encoding="utf-8").strip() == checksum:
        return path, checksum
    write_csv(rows, path)
    stamp.write_text(checksum + "\n", encoding="utf-8")
    return path, checksum


def probe_environment(cli, sizes, percents, reps, warmup, seed):
    version = subprocess.run(
        [str(cli), "-no-init", "-no-agent", "-version"],
        check=False, capture_output=True, text=True,
    )
    settings = subprocess.run(
        [str(cli), "-no-init", "-no-agent", "-csv", ":memory:", "-c",
         "SELECT version() AS duckdb_version, current_setting('threads') AS threads, "
         "current_setting('memory_limit') AS memory_limit;"],
        check=False, capture_output=True, text=True,
    )
    extension = subprocess.run(
        [str(cli), "-no-init", "-no-agent", "-csv", ":memory:", "-c",
         "SELECT extension_name, extension_version, installed, install_path FROM duckdb_extensions() "
         "WHERE extension_name = 'differential';"],
        check=False, capture_output=True, text=True,
    )
    df = subprocess.run(["df", "-k", str(ROOT)], check=False, capture_output=True, text=True)
    mem = subprocess.run(["sysctl", "-n", "hw.memsize", "hw.ncpu"], check=False, capture_output=True, text=True)
    digest = hashlib.sha256(cli.read_bytes()).hexdigest()
    return {
        "duckdb_cli": str(cli),
        "duckdb_cli_sha256": digest,
        "duckdb_version_output": (version.stdout or version.stderr).strip(),
        "settings": settings.stdout.strip(),
        "extension": extension.stdout.strip(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": mem.stdout.strip(),
        "filesystem": df.stdout.strip(),
        "dataset_seed": seed,
        "currency": "AUD",
        "sizes": list(sizes),
        "changed_percents": list(percents),
        "measured_repetitions": reps,
        "warmup_repetition": warmup,
        "differential_auto_gc": False,
        "timing": {
            "duckdb_operations": "epoch_ns(get_current_timestamp()) delta inside the operation process; CLI startup excluded",
            "filesystem_copy": "Python perf_counter around shutil.copy2 plus fsync of each destination file and its directory",
            "filesystem_delete": "Python perf_counter around unlink",
        },
        "storage": {
            "differential_state": "repository directory bytes plus temp_directory bytes; WAL is inside the repository total and also reported separately",
            "native_state": "sum of .duckdb, WAL and temp bytes for the baseline and candidate files present at the checkpoint",
            "logical_copy": "reported separately and excluded from the native filesystem-copy total",
        },
        "workloads": {
            "business": "baseline and candidate classification SQL; actual change count is measured",
            "controlled": "UPDATE status and payload WHERE row_id < size * percent / 100",
        },
    }


def write_summaries(rows, results):
    measured = [row for row in rows if row["warmup"] == "false" and row["elapsed_ns"] != ""]
    summary = []
    grouped = {}
    for row in measured:
        key = (
            row["workload"], row["system"], row["dataset_size"], row["changed_percent"], row["operation"],
        )
        grouped.setdefault(key, []).append(int(row["elapsed_ns"]))
    for key, values in grouped.items():
        ordered = sorted(values)
        summary.append({
            "workload": key[0], "system": key[1], "dataset_size": key[2],
            "changed_percent": key[3], "operation": key[4], "samples": len(ordered),
            "median_elapsed_ns": ordered[(len(ordered) - 1) // 2] if len(ordered) % 2 else (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2,
            "min_elapsed_ns": ordered[0], "max_elapsed_ns": ordered[-1],
        })
    write_csv_rows(results / "summary.csv", summary)
    checkpoints = [
        row for row in rows
        if row["warmup"] == "false" and row["checkpoint"] and row["state_storage_bytes"] != ""
    ]
    storage = []
    grouped = {}
    for row in checkpoints:
        key = (
            row["workload"], row["system"], row["dataset_size"], row["changed_percent"], row["checkpoint"],
        )
        grouped.setdefault(key, []).append(int(row["state_storage_bytes"]))
    for key, values in grouped.items():
        ordered = sorted(values)
        storage.append({
            "workload": key[0], "system": key[1], "dataset_size": key[2],
            "changed_percent": key[3], "checkpoint": key[4], "samples": len(ordered),
            "median_state_bytes": ordered[(len(ordered) - 1) // 2],
            "min_state_bytes": ordered[0], "max_state_bytes": ordered[-1],
        })
    write_csv_rows(results / "storage_summary.csv", storage)


def write_csv_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def rewrite_last(recorder):
    with recorder.path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(recorder.rows)


class Recorder:
    def __init__(self, path):
        self.path = path
        self.rows = []
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n").writeheader()

    def add(self, row):
        full = {key: "" for key in FIELDS}
        for key, value in row.items():
            if key in full:
                full[key] = value
        self.rows.append(full)
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n").writerow(full)


def disposable(path):
    path = resolve_under(ROOT, path)
    bench = (ROOT / "benchmark").resolve()
    if path != bench and bench not in path.parents:
        raise SystemExit(f"refusing path outside {bench}: {path}")
    for protected in PROTECTED:
        resolved = protected.resolve()
        if path == resolved or resolved in path.parents or path in resolved.parents:
            raise SystemExit(f"refusing protected path: {path}")
    return path


def tree_signature(path):
    if not path.exists():
        return None
    rows = []
    for file_path in sorted(path.rglob("*")):
        if file_path.is_file() and file_path.name != ".DS_Store":
            stat = file_path.stat()
            rows.append((str(file_path.relative_to(path)), stat.st_size, stat.st_mtime_ns))
    return tuple(rows)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(exc, file=sys.stderr)
        raise
