SET differential_repository = 'experiment/test/phase1';
SET differential_auto_gc = false;

        SELECT branch_name, branch_id, state, head_snapshot_id, source_snapshot_id, database_id
        FROM differential_branches('bank_b')
        ORDER BY branch_name;
    