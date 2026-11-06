SET differential_repository = 'experiment/repository';
SET differential_auto_gc = false;

        SELECT branch_name, branch_id, state, head_snapshot_id, source_snapshot_id, database_id
        FROM differential_branches('bank')
        ORDER BY branch_name;
    