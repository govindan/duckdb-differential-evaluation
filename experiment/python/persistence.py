"""Phase 5 persistence checks in a disposable directory.

Normal exit, SIGKILL after a completed checkpoint or snapshot, and SIGKILL
during a later statement are separate cases. None of them drops the operating
system cache, so none is a power-loss result.
"""

import csv
import io
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from experiment_runner import preamble, require_cli, load_config, resolve_under, sql_literal

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = (
    ROOT / "repository",
    ROOT / "lifecycle" / "repository",
    ROOT / "lifecycle" / "retention" / "repository",
)
RESULTS = ROOT / "results" / "functional" / "phase5"
WORK = ROOT / "persistence"
DATABASE = "persist"
BASE_ROWS = 100
FIELDS = (
    "test_id", "system", "scenario", "durability_class", "power_loss",
    "command", "expected", "actual", "status", "evidence", "notes",
)


def main():
    config = load_config(ROOT / "config" / "experiment.yaml")
    cli = require_cli(Path(config["duckdb_cli"]))
    run_persistence(cli)


def run_persistence(cli):
    work = disposable(WORK)
    results = resolve_under(ROOT, RESULTS)
    results.mkdir(parents=True, exist_ok=True)
    signatures = {str(path): tree_signature(path) for path in PROTECTED}
    default_store = Path.home() / ".duckdb" / "differential"
    default_mtime = default_store.stat().st_mtime_ns if default_store.exists() else None
    rows = []
    try:
        if work.exists():
            import shutil
            shutil.rmtree(work)
        work.mkdir(parents=True)
        hooks = test_hooks(cli, work / "status")
        rows.append(hooks)
        rows.append(native_normal(cli, work / "pr01"))
        rows.append(differential_normal(cli, work / "pr02"))
        rows.append(native_kill_after_commit(cli, work / "pr03"))
        rows.append(differential_kill_after_commit(cli, work / "pr04"))
        rows.append(native_kill_during_write(cli, work / "pr05"))
        rows.append(differential_kill_during_write(cli, work / "pr06"))
        rows.append({
            "test_id": "PR08",
            "system": "both",
            "scenario": "Power-loss durability",
            "durability_class": "power_loss",
            "power_loss": "not_tested",
            "command": "not run",
            "expected": "Data readable after power loss and loss of the operating-system cache",
            "actual": "No power cut and no cache drop were performed",
            "status": "UNVERIFIED",
            "evidence": "",
            "notes": "A clean exit or SIGKILL leaves the page cache intact. Those tests are not power-loss evidence.",
        })
    finally:
        changed = [path for path, signature in signatures.items() if tree_signature(Path(path)) != signature]
        after = default_store.stat().st_mtime_ns if default_store.exists() else None
        if changed or after != default_mtime:
            raise SystemExit(f"protected storage changed: {changed or 'default differential store'}")
    write_rows(results / "persistence_tests.csv", rows)
    failed = [row["test_id"] for row in rows if row["status"] not in {"DEMONSTRATED", "DOCUMENTED", "UNVERIFIED"}]
    if failed:
        raise SystemExit(f"unexpected status for {failed}")
    print("persistence tests recorded", flush=True)
    for row in rows:
        print(f"{row['test_id']} {row['status']}: {row['actual']}", flush=True)
    return rows


def test_hooks(cli, run):
    repo = run / "repository"
    repo.mkdir(parents=True)
    found = query(cli, run, "status", preamble(repo) + """
        SELECT capability, status FROM differential_status() WHERE capability = 'test_hooks';
    """)
    status = found[0]["status"] if found else "missing"
    return {
        "test_id": "PR07",
        "system": "differential",
        "scenario": "Snapshot publication failure injection",
        "durability_class": "failure_injection",
        "power_loss": "not_tested",
        "command": "SELECT status FROM differential_status() WHERE capability = 'test_hooks'",
        "expected": "A supported hook that can fail snapshot publication",
        "actual": f"test_hooks={status}",
        "status": "UNVERIFIED",
        "evidence": str(run / "scripts" / "status.sql"),
        "notes": "The release CLI used for this evaluation has no failure hooks, so publication failure was not injected.",
    }


def native_normal(cli, run):
    database = run / "base.duckdb"
    duck(cli, run, "write", native_setup(database) + f"""
        INSERT INTO base.t SELECT range, 'base' FROM range({BASE_ROWS});
        CHECKPOINT base;
    """)
    found = read_native(cli, run, database, "reopen")
    return result_row(
        "PR01", "native", "Normal close and restart", "normal_process_restart",
        "process exit 0 after CHECKPOINT; new process reads the table",
        "100 base rows with the committed fingerprint",
        found, run / "scripts" / "reopen.sql",
        "Clean process exit. This does not test power loss.",
    )


def differential_normal(cli, run):
    repo = run / "repository"
    repo.mkdir(parents=True)
    duck(cli, run, "write", diff_setup(repo) + f"""
        INSERT INTO main_raw.t SELECT range, 'base' FROM range({BASE_ROWS});
        CREATE TABLE snap AS
        SELECT snapshot_id FROM differential_create_snapshot(
            'main_raw', name => 'committed', message => 'normal restart');
    """)
    found = read_differential(cli, run, repo, "reopen")
    return result_row(
        "PR02", "differential", "Normal close and restart", "normal_process_restart",
        "process exit 0 after differential_create_snapshot; new process reads the branch and the snapshot",
        "100 live rows and 100 snapshot rows with the committed fingerprint",
        found, run / "scripts" / "reopen.sql",
        "Clean process exit. This does not test power loss.",
    )


def native_kill_after_commit(cli, run):
    database = run / "base.duckdb"
    marker = run / "ready.csv"
    outcome = run_until_marker(cli, run, "commit_then_busy", native_setup(database) + f"""
        INSERT INTO base.t SELECT range, 'base' FROM range({BASE_ROWS});
        CHECKPOINT base;
        COPY (SELECT 'ready') TO {sql_literal(str(marker))};
        COPY (SELECT range AS id, repeat('x', 200) AS body FROM range(5000000))
            TO {sql_literal(str(run / 'sink.csv'))};
    """, marker)
    found = read_native(cli, run, database, "reopen")
    return killed_row(
        "PR03", "native", "Committed write then process termination",
        "process_termination_after_commit", outcome, found,
        "CHECKPOINT returned and wrote the marker. SIGKILL followed during a later file copy. The OS page cache was not dropped.",
        run / "scripts" / "reopen.sql",
    )


def differential_kill_after_commit(cli, run):
    repo = run / "repository"
    repo.mkdir(parents=True)
    marker = run / "ready.csv"
    outcome = run_until_marker(cli, run, "commit_then_busy", diff_setup(repo) + f"""
        INSERT INTO main_raw.t SELECT range, 'base' FROM range({BASE_ROWS});
        CREATE TABLE snap AS
        SELECT snapshot_id FROM differential_create_snapshot(
            'main_raw', name => 'committed', message => 'kill after snapshot');
        COPY (SELECT 'ready') TO {sql_literal(str(marker))};
        COPY (SELECT range AS id, repeat('x', 200) AS body FROM range(5000000))
            TO {sql_literal(str(run / 'sink.csv'))};
    """, marker)
    found = read_differential(cli, run, repo, "reopen")
    return killed_row(
        "PR04", "differential", "Committed write then process termination",
        "process_termination_after_commit", outcome, found,
        "differential_create_snapshot returned and wrote the marker. SIGKILL followed during a later file copy. The OS page cache was not dropped.",
        run / "scripts" / "reopen.sql",
    )


def native_kill_during_write(cli, run):
    database = run / "base.duckdb"
    duck(cli, run, "commit_base", native_setup(database) + f"""
        INSERT INTO base.t SELECT range, 'base' FROM range({BASE_ROWS});
        CHECKPOINT base;
    """)
    before = read_native(cli, run, database, "before")
    marker = run / "ready.csv"
    outcome = run_until_marker(cli, run, "interrupt", f"""
        ATTACH {sql_literal(str(database))} AS base;
        COPY (SELECT 'ready') TO {sql_literal(str(marker))};
        INSERT INTO base.t
        SELECT {BASE_ROWS} + range, repeat('x', 500) FROM range(5000000);
    """, marker)
    found = read_native(cli, run, database, "reopen")
    return interrupt_row("PR05", "native", outcome, before, found, run / "scripts" / "reopen.sql")


def differential_kill_during_write(cli, run):
    repo = run / "repository"
    repo.mkdir(parents=True)
    duck(cli, run, "commit_base", diff_setup(repo) + f"""
        INSERT INTO main_raw.t SELECT range, 'base' FROM range({BASE_ROWS});
        CREATE TABLE snap AS
        SELECT snapshot_id FROM differential_create_snapshot(
            'main_raw', name => 'committed', message => 'base before interruption');
    """)
    before = read_differential(cli, run, repo, "before")
    marker = run / "ready.csv"
    outcome = run_until_marker(cli, run, "interrupt", preamble(repo) + f"""
        ATTACH 'differential:{DATABASE}' AS main_raw (BRANCH 'main');
        COPY (SELECT 'ready') TO {sql_literal(str(marker))};
        INSERT INTO main_raw.t
        SELECT {BASE_ROWS} + range, repeat('x', 500) FROM range(5000000);
    """, marker)
    found = read_differential(cli, run, repo, "reopen")
    return interrupt_row("PR06", "differential", outcome, before, found, run / "scripts" / "reopen.sql")


def native_setup(database):
    database.parent.mkdir(parents=True, exist_ok=True)
    return f"""
        ATTACH {sql_literal(str(database))} AS base;
        CREATE TABLE base.t (id BIGINT PRIMARY KEY, body VARCHAR NOT NULL);
    """


def diff_setup(repo):
    return preamble(repo) + f"""
        ATTACH 'differential:{DATABASE}' AS main_raw (BRANCH 'main');
        CREATE TABLE main_raw.t (id BIGINT PRIMARY KEY, body VARCHAR NOT NULL);
    """


def read_native(cli, run, database, name):
    rows = query(cli, run, name, f"""
        ATTACH {sql_literal(str(database))} AS base (READ_ONLY);
        SELECT
            (SELECT count(*) FROM base.t) AS live_rows,
            (SELECT count(*) FROM base.t WHERE id < {BASE_ROWS} AND body = 'base') AS base_rows,
            (SELECT md5(string_agg(id::VARCHAR || '|' || body, chr(10) ORDER BY id))
             FROM base.t WHERE id < {BASE_ROWS}) AS base_fingerprint,
            (SELECT count(*) FROM base.t WHERE id >= {BASE_ROWS}) AS extra_rows;
    """)
    return rows[0]


def read_differential(cli, run, repo, name):
    rows = query(cli, run, name, preamble(repo) + f"""
        ATTACH 'differential:{DATABASE}' AS main_raw (BRANCH 'main');
        ATTACH 'differential:{DATABASE}' AS committed (SNAPSHOT_NAME 'committed');
        SELECT
            (SELECT count(*) FROM main_raw.t) AS live_rows,
            (SELECT count(*) FROM committed.t) AS snapshot_rows,
            (SELECT count(*) FROM committed.t WHERE id < {BASE_ROWS} AND body = 'base') AS base_rows,
            (SELECT md5(string_agg(id::VARCHAR || '|' || body, chr(10) ORDER BY id))
             FROM committed.t WHERE id < {BASE_ROWS}) AS base_fingerprint,
            (SELECT count(*) FROM main_raw.t WHERE id >= {BASE_ROWS}) AS extra_rows;
    """)
    return rows[0]


def result_row(test_id, system, scenario, durability, command, expected, found, evidence, notes):
    ok = committed_ok(found) and int(found.get("extra_rows", "0")) == 0
    if system == "differential":
        ok = ok and int(found["live_rows"]) == BASE_ROWS and int(found["snapshot_rows"]) == BASE_ROWS
    else:
        ok = ok and int(found["live_rows"]) == BASE_ROWS
    return {
        "test_id": test_id,
        "system": system,
        "scenario": scenario,
        "durability_class": durability,
        "power_loss": "false",
        "command": command,
        "expected": expected,
        "actual": describe(found),
        "status": "DEMONSTRATED" if ok else "UNVERIFIED",
        "evidence": str(evidence),
        "notes": notes if ok else notes + " Committed state did not match the expected 100 rows.",
    }


def killed_row(test_id, system, scenario, durability, outcome, found, notes, evidence):
    ok = outcome["disposition"] == "killed" and committed_ok(found) and int(found.get("extra_rows", "0")) == 0
    if system == "differential":
        ok = ok and int(found["snapshot_rows"]) == BASE_ROWS and int(found["live_rows"]) == BASE_ROWS
    else:
        ok = ok and int(found["live_rows"]) == BASE_ROWS
    actual = f"{outcome['disposition']} signal={outcome['returncode']}; {describe(found)}"
    return {
        "test_id": test_id,
        "system": system,
        "scenario": scenario,
        "durability_class": durability,
        "power_loss": "false",
        "command": "CHECKPOINT or snapshot, then SIGKILL during a later statement",
        "expected": "The completed checkpoint or snapshot is readable after SIGKILL",
        "actual": actual,
        "status": "DEMONSTRATED" if ok else "UNVERIFIED",
        "evidence": str(evidence),
        "notes": notes,
    }


def interrupt_row(test_id, system, outcome, before, found, evidence):
    ok = (
        outcome["disposition"] == "killed"
        and committed_ok(before)
        and committed_ok(found)
        and before["base_fingerprint"] == found["base_fingerprint"]
    )
    actual = (
        f"{outcome['disposition']} signal={outcome['returncode']}; "
        f"before {describe(before)}; after {describe(found)}"
    )
    notes = (
        "SIGKILL arrived after the marker and during the uncommitted INSERT. "
        "The previously checkpointed or snapshotted 100 rows were checked after restart. "
        "Rows from the interrupted statement are reported separately. "
        "The OS page cache was not dropped, so this is not power-loss evidence."
    )
    return {
        "test_id": test_id,
        "system": system,
        "scenario": "In-progress statement process interruption",
        "durability_class": "process_interruption_during_statement",
        "power_loss": "false",
        "command": "SIGKILL during INSERT after a completed checkpoint or snapshot",
        "expected": "The previously committed 100 rows remain readable and unchanged",
        "actual": actual,
        "status": "DEMONSTRATED" if ok else "UNVERIFIED",
        "evidence": str(evidence),
        "notes": notes,
    }


def committed_ok(found):
    return int(found["base_rows"]) == BASE_ROWS and bool(found["base_fingerprint"])


def describe(found):
    parts = [f"{key}={found[key]}" for key in found]
    return ", ".join(parts)


def run_until_marker(cli, run, name, sql, marker):
    script = run / "scripts" / f"{name}.sql"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(sql, encoding="utf-8")
    stdout = script.with_suffix(".out")
    stderr = script.with_suffix(".err")
    with stdout.open("w", encoding="utf-8") as out, stderr.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(
            [str(cli), "-no-init", "-no-agent", "-bail", "-csv", ":memory:", "-f", str(script)],
            stdout=out, stderr=err,
        )
        deadline = time.time() + 60
        while not marker.exists():
            if proc.poll() is not None or time.time() > deadline:
                break
            time.sleep(0.05)
        if marker.exists() and proc.poll() is None:
            time.sleep(0.3)
        if proc.poll() is None:
            os.kill(proc.pid, signal.SIGKILL)
            proc.wait(timeout=30)
            disposition = "killed"
        else:
            disposition = "exited"
        returncode = proc.returncode
    if disposition != "killed":
        message = stderr.read_text(encoding="utf-8", errors="replace")[-500:]
        return {"disposition": disposition, "returncode": returncode, "error": message}
    return {"disposition": disposition, "returncode": returncode, "error": ""}


def duck(cli, run, name, sql):
    script = run / "scripts" / f"{name}.sql"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(sql, encoding="utf-8")
    proc = subprocess.run(
        [str(cli), "-no-init", "-no-agent", "-bail", "-csv", ":memory:", "-f", str(script)],
        check=False, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"{script}: {(proc.stderr or proc.stdout).strip()}")


def query(cli, run, name, sql):
    script = run / "scripts" / f"{name}.sql"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(sql, encoding="utf-8")
    proc = subprocess.run(
        [str(cli), "-no-init", "-no-agent", "-bail", "-csv", ":memory:", "-f", str(script)],
        check=False, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"{script}: {(proc.stderr or proc.stdout).strip()}")
    lines = [line for line in proc.stdout.splitlines() if line.strip() and line.strip() != "Success"]
    start = next(index for index, line in enumerate(lines) if line.split(",")[0] in {"live_rows", "capability"})
    return list(csv.DictReader(io.StringIO("\n".join(lines[start:]) + "\n")))


def write_rows(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def disposable(path):
    path = resolve_under(ROOT, path)
    if path == ROOT or ROOT not in path.parents:
        raise SystemExit(f"refusing path: {path}")
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
