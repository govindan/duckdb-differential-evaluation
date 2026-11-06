SET differential_repository = 'experiment/repository';
SET differential_auto_gc = false;
ATTACH 'differential:bank' AS main_raw (BRANCH 'main');

            SELECT operation_id, database_id, branch_id, snapshot_id, state
            FROM differential_create_branch('bank', 'candidate', snapshot => 1);
        