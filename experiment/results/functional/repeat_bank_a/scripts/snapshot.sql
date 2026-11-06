SET differential_repository = 'experiment/test/phase1';
SET differential_auto_gc = false;
ATTACH 'differential:bank_a' AS main_raw (BRANCH 'main');

        SELECT operation_id, database_id, branch_id, snapshot_id, state, export_state, snapshot_time
        FROM differential_create_snapshot(
            'main_raw',
            name => 'raw-input',
            author => 'phase1',
            message => 'raw banking transactions'
        );
    